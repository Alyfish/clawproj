import { describe, it, beforeEach, afterEach, mock } from 'node:test';
import assert from 'node:assert/strict';
import MessageRouter from '../message-router.js';
import SessionManager from '../session-manager.js';
import type { ConnectedClient, ConnectPayload, WSMessage } from '../types.js';

// ── Helpers ────────────────────────────────────────────────────

function mockWs(): { ws: ConnectedClient['ws']; sent: WSMessage[] } {
  const sent: WSMessage[] = [];
  const ws = {
    send(data: string) {
      sent.push(JSON.parse(data));
    },
    readyState: 1,
  } as unknown as ConnectedClient['ws'];
  return { ws, sent };
}

function makeClient(
  ws: ConnectedClient['ws'],
  overrides?: Partial<ConnectedClient>,
): ConnectedClient {
  return {
    ws,
    deviceToken: 'op-device-1',
    role: 'operator',
    scopes: ['chat'],
    sessionId: 'sess-1',
    connectedAt: new Date().toISOString(),
    lastSeen: new Date().toISOString(),
    ...overrides,
  };
}

const TEST_REQUEST_ID = '550e8400-e29b-41d4-a716-446655440000';

function setupSession(sessions: SessionManager) {
  const session = sessions.createSession();

  const { ws: opWs, sent: opSent } = mockWs();
  const { ws: agentWs, sent: agentSent } = mockWs();

  const opClient = makeClient(opWs, {
    sessionId: session.id,
    deviceToken: 'op-device',
    role: 'operator',
  });
  const agentClient = makeClient(agentWs, {
    sessionId: session.id,
    deviceToken: 'agent-device',
    role: 'node',
    scopes: ['agent'],
  });

  sessions.addClient(session.id, opClient);
  sessions.addClient(session.id, agentClient);

  return { session, opClient, agentClient, opSent, agentSent };
}

// ── Tests ──────────────────────────────────────────────────────

describe('OAuth token lifecycle', () => {
  let sessions: SessionManager;
  let router: MessageRouter;

  beforeEach(() => {
    sessions = new SessionManager();
    router = new MessageRouter(sessions);
  });

  afterEach(() => {
    mock.timers.reset();
  });

  // ── Token delivery on connect ──────────────────────────────

  it('delivers token to agent immediately when operator connects with googleOAuthToken', () => {
    const session = sessions.createSession();

    // Agent already in session
    const { ws: agentWs, sent: agentSent } = mockWs();
    const agentClient = makeClient(agentWs, {
      sessionId: session.id,
      deviceToken: 'agent-d',
      role: 'node',
      scopes: ['agent'],
    });
    sessions.addClient(session.id, agentClient);

    // Operator connects with token
    const { ws: opWs } = mockWs();
    const opClient = makeClient(opWs, {
      sessionId: session.id,
      deviceToken: 'op-d',
      role: 'operator',
    });
    sessions.addClient(session.id, opClient);

    const payload: ConnectPayload = {
      role: 'operator',
      scopes: ['chat'],
      googleOAuthToken: 'ya29.test-token-abc',
    };
    router.onClientConnected(opClient, payload);

    // Agent receives credential/token event
    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].type, 'event');
    assert.equal(agentSent[0].event, 'credential/token');
    const p = agentSent[0].payload as Record<string, unknown>;
    assert.equal(p.service, 'google');
    assert.equal(p.token, 'ya29.test-token-abc');
    assert.equal(p.sessionId, session.id);
  });

  it('delivers token to agent when agent joins later (deferred)', () => {
    const session = sessions.createSession();

    // Operator connects first with token
    const { ws: opWs } = mockWs();
    const opClient = makeClient(opWs, {
      sessionId: session.id,
      deviceToken: 'op-d',
      role: 'operator',
    });
    sessions.addClient(session.id, opClient);

    const opPayload: ConnectPayload = {
      role: 'operator',
      scopes: ['chat'],
      googleOAuthToken: 'ya29.deferred-token',
    };
    router.onClientConnected(opClient, opPayload);

    // Agent connects later
    const { ws: agentWs, sent: agentSent } = mockWs();
    const agentClient = makeClient(agentWs, {
      sessionId: session.id,
      deviceToken: 'agent-d',
      role: 'node',
      scopes: ['agent'],
    });
    sessions.addClient(session.id, agentClient);

    const agentPayload: ConnectPayload = {
      role: 'node',
      scopes: ['agent'],
    };
    router.onClientConnected(agentClient, agentPayload);

    // Agent receives credential/token event
    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].event, 'credential/token');
    assert.equal(
      (agentSent[0].payload as Record<string, unknown>).token,
      'ya29.deferred-token',
    );
  });

  it('ignores empty/whitespace-only token with warning', () => {
    const session = sessions.createSession();

    const { ws: agentWs, sent: agentSent } = mockWs();
    const agentClient = makeClient(agentWs, {
      sessionId: session.id,
      deviceToken: 'agent-d',
      role: 'node',
      scopes: ['agent'],
    });
    sessions.addClient(session.id, agentClient);

    const { ws: opWs } = mockWs();
    const opClient = makeClient(opWs, {
      sessionId: session.id,
      deviceToken: 'op-d',
      role: 'operator',
    });
    sessions.addClient(session.id, opClient);

    router.onClientConnected(opClient, {
      role: 'operator',
      scopes: ['chat'],
      googleOAuthToken: '   ',
    });

    // No token delivered to agent
    assert.equal(agentSent.length, 0);
  });

  it('last token wins when multiple operators provide tokens', () => {
    const session = sessions.createSession();

    const { ws: agentWs, sent: agentSent } = mockWs();
    const agentClient = makeClient(agentWs, {
      sessionId: session.id,
      deviceToken: 'agent-d',
      role: 'node',
      scopes: ['agent'],
    });
    sessions.addClient(session.id, agentClient);

    // First operator
    const { ws: op1Ws } = mockWs();
    const op1 = makeClient(op1Ws, {
      sessionId: session.id,
      deviceToken: 'op-1',
      role: 'operator',
    });
    sessions.addClient(session.id, op1);
    router.onClientConnected(op1, {
      role: 'operator',
      scopes: ['chat'],
      googleOAuthToken: 'ya29.first',
    });

    // Second operator overwrites
    const { ws: op2Ws } = mockWs();
    const op2 = makeClient(op2Ws, {
      sessionId: session.id,
      deviceToken: 'op-2',
      role: 'operator',
    });
    sessions.addClient(session.id, op2);
    router.onClientConnected(op2, {
      role: 'operator',
      scopes: ['chat'],
      googleOAuthToken: 'ya29.second',
    });

    // Agent received two deliveries — the last one has the second token
    assert.equal(agentSent.length, 2);
    assert.equal(
      (agentSent[1].payload as Record<string, unknown>).token,
      'ya29.second',
    );
  });

  // ── Token refresh flow ─────────────────────────────────────

  it('routes credential/token:expired from agent to operators as credential/token:refresh', () => {
    const { agentClient, opSent } = setupSession(sessions);

    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/token:expired',
        payload: { service: 'google' },
      }),
    );

    assert.equal(opSent.length, 1);
    assert.equal(opSent[0].type, 'event');
    assert.equal(opSent[0].event, 'credential/token:refresh');
    const p = opSent[0].payload as Record<string, unknown>;
    assert.equal(p.service, 'google');
    assert.ok(p.requestId); // UUID generated
  });

  it('routes credential.tokenRefreshed from operator to agent as credential/token', () => {
    const { agentClient, opClient, opSent, agentSent } = setupSession(sessions);

    // Agent signals expired
    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/token:expired',
        payload: { service: 'google' },
      }),
    );

    // Get the requestId from the refresh event sent to operator
    const refreshPayload = opSent[0].payload as Record<string, unknown>;
    const requestId = refreshPayload.requestId as string;

    // Operator responds with refreshed token
    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.tokenRefreshed',
        id: 'req-refresh-1',
        payload: {
          service: 'google',
          token: 'ya29.refreshed-token',
          requestId,
        },
      }),
    );

    // Agent receives credential/token event
    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].event, 'credential/token');
    assert.equal(
      (agentSent[0].payload as Record<string, unknown>).token,
      'ya29.refreshed-token',
    );

    // Operator receives ACK
    assert.equal(opSent.length, 2); // refresh event + ACK
    assert.equal((opSent[1].payload as Record<string, unknown>).status, 'sent');
  });

  // ── Timeout ────────────────────────────────────────────────

  it('sends credential/none with timeout reason after 30 seconds on refresh', () => {
    mock.timers.enable({ apis: ['setTimeout'] });

    const { agentClient, agentSent } = setupSession(sessions);

    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/token:expired',
        payload: { service: 'google' },
      }),
    );

    assert.equal(agentSent.length, 0);

    // Advance time by 30 seconds
    mock.timers.tick(30_000);

    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].event, 'credential/none');
    const p = agentSent[0].payload as Record<string, unknown>;
    assert.equal(p.reason, 'timeout');
    assert.equal(p.domain, 'oauth:google');
  });

  it('clears timeout when credential.tokenRefreshed received before expiry', () => {
    mock.timers.enable({ apis: ['setTimeout'] });

    const { agentClient, opClient, opSent, agentSent } = setupSession(sessions);

    // Agent signals expired
    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/token:expired',
        payload: { service: 'google' },
      }),
    );

    const requestId = (opSent[0].payload as Record<string, unknown>)
      .requestId as string;

    // Operator responds before timeout
    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.tokenRefreshed',
        id: 'req-early',
        payload: {
          service: 'google',
          token: 'ya29.new',
          requestId,
        },
      }),
    );

    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].event, 'credential/token');

    // Advance past timeout — should NOT send another message
    mock.timers.tick(30_000);
    assert.equal(agentSent.length, 1);
  });

  // ── History exclusion ──────────────────────────────────────

  it('token events are excluded from session history', () => {
    const { session, agentClient, opClient } = setupSession(sessions);

    // credential/token:expired event
    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/token:expired',
        payload: { service: 'google' },
      }),
    );

    const history = sessions.getHistory(session.id);
    const tokenEntries = history.filter((h) =>
      (h.message.event ?? '').startsWith('credential/token'),
    );
    assert.equal(tokenEntries.length, 0);
  });

  // ── Cleanup ────────────────────────────────────────────────

  it('cleans up tokens when session becomes empty', () => {
    const session = sessions.createSession();

    // Operator provides token
    const { ws: opWs } = mockWs();
    const opClient = makeClient(opWs, {
      sessionId: session.id,
      deviceToken: 'op-cleanup',
      role: 'operator',
    });
    sessions.addClient(session.id, opClient);
    router.onClientConnected(opClient, {
      role: 'operator',
      scopes: ['chat'],
      googleOAuthToken: 'ya29.cleanup-test',
    });

    // Disconnect operator (session now empty)
    sessions.removeClient('op-cleanup', session.id);
    router.onClientDisconnected(session.id);

    // New agent joins — should NOT receive old token
    const { ws: agentWs, sent: agentSent } = mockWs();
    const agentClient = makeClient(agentWs, {
      sessionId: session.id,
      deviceToken: 'agent-cleanup',
      role: 'node',
      scopes: ['agent'],
    });
    sessions.addClient(session.id, agentClient);
    router.onClientConnected(agentClient, {
      role: 'node',
      scopes: ['agent'],
    });

    assert.equal(agentSent.length, 0);
  });

  // ── Validation errors ──────────────────────────────────────

  it('returns VALIDATION_ERROR for invalid credential.tokenRefreshed payload', () => {
    const { opClient, opSent } = setupSession(sessions);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.tokenRefreshed',
        id: 'req-bad',
        payload: { service: 'google' }, // missing token
      }),
    );

    assert.equal(opSent.length, 1);
    assert.equal(
      (opSent[0].payload as Record<string, unknown>).error,
      'VALIDATION_ERROR',
    );
  });

  it('returns NO_AGENT for credential.tokenRefreshed when no agent connected', () => {
    const session = sessions.createSession();
    const { ws, sent } = mockWs();
    const opClient = makeClient(ws, {
      sessionId: session.id,
      deviceToken: 'op-solo',
      role: 'operator',
    });
    sessions.addClient(session.id, opClient);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.tokenRefreshed',
        id: 'req-no-agent',
        payload: {
          service: 'google',
          token: 'ya29.orphan',
        },
      }),
    );

    assert.equal(sent.length, 1);
    assert.equal(
      (sent[0].payload as Record<string, unknown>).error,
      'NO_AGENT',
    );
  });

  it('does not deliver token when operator connects without googleOAuthToken', () => {
    const session = sessions.createSession();

    const { ws: agentWs, sent: agentSent } = mockWs();
    const agentClient = makeClient(agentWs, {
      sessionId: session.id,
      deviceToken: 'agent-d',
      role: 'node',
      scopes: ['agent'],
    });
    sessions.addClient(session.id, agentClient);

    const { ws: opWs } = mockWs();
    const opClient = makeClient(opWs, {
      sessionId: session.id,
      deviceToken: 'op-d',
      role: 'operator',
    });
    sessions.addClient(session.id, opClient);

    // Connect without token
    router.onClientConnected(opClient, {
      role: 'operator',
      scopes: ['chat'],
    });

    assert.equal(agentSent.length, 0);
  });
});
