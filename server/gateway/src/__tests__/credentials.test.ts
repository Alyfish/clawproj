import { describe, it, beforeEach, afterEach, mock } from 'node:test';
import assert from 'node:assert/strict';
import MessageRouter from '../message-router.js';
import SessionManager from '../session-manager.js';
import type { ConnectedClient, WSMessage } from '../types.js';

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

describe('credential routing', () => {
  let sessions: SessionManager;
  let router: MessageRouter;

  beforeEach(() => {
    sessions = new SessionManager();
    router = new MessageRouter(sessions);
  });

  afterEach(() => {
    mock.timers.reset();
  });

  // ── credential.response ──────────────────────────────────

  it('routes credential.response from operator to agent', () => {
    const { opClient, opSent, agentSent } = setupSession(sessions);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.response',
        id: 'req-cred-1',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          credentials: [{ username: 'user@email.com', password: 's3cret' }],
        },
      }),
    );

    // Agent receives credential/response event
    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].type, 'event');
    assert.equal(agentSent[0].event, 'credential/response');
    assert.equal(
      (agentSent[0].payload as Record<string, unknown>).requestId,
      TEST_REQUEST_ID,
    );
    assert.equal(
      (agentSent[0].payload as Record<string, unknown>).domain,
      'amazon.com',
    );
    const creds = (agentSent[0].payload as Record<string, unknown>)
      .credentials as Array<{ username: string; password: string }>;
    assert.equal(creds.length, 1);
    assert.equal(creds[0].username, 'user@email.com');
    assert.equal(creds[0].password, 's3cret');

    // Operator receives ACK
    assert.equal(opSent.length, 1);
    assert.equal(opSent[0].type, 'res');
    assert.equal((opSent[0].payload as Record<string, unknown>).status, 'sent');
  });

  it('returns VALIDATION_ERROR for invalid credential.response payload', () => {
    const { opClient, opSent } = setupSession(sessions);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.response',
        id: 'req-cred-bad',
        payload: { domain: 'amazon.com' },
      }),
    );

    assert.equal(opSent.length, 1);
    assert.equal(
      (opSent[0].payload as Record<string, unknown>).error,
      'VALIDATION_ERROR',
    );
  });

  it('returns VALIDATION_ERROR for empty credentials array', () => {
    const { opClient, opSent } = setupSession(sessions);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.response',
        id: 'req-cred-empty',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          credentials: [],
        },
      }),
    );

    assert.equal(opSent.length, 1);
    assert.equal(
      (opSent[0].payload as Record<string, unknown>).error,
      'VALIDATION_ERROR',
    );
  });

  // ── credential.none ──────────────────────────────────────

  it('routes credential.none from operator to agent', () => {
    const { opClient, opSent, agentSent } = setupSession(sessions);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.none',
        id: 'req-cred-none-1',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          reason: 'no_credentials',
        },
      }),
    );

    // Agent receives credential/none event
    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].type, 'event');
    assert.equal(agentSent[0].event, 'credential/none');
    assert.equal(
      (agentSent[0].payload as Record<string, unknown>).reason,
      'no_credentials',
    );

    // Operator receives ACK
    assert.equal(opSent.length, 1);
    assert.equal((opSent[0].payload as Record<string, unknown>).status, 'sent');
  });

  it('returns VALIDATION_ERROR for invalid credential.none reason', () => {
    const { opClient, opSent } = setupSession(sessions);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.none',
        id: 'req-cred-none-bad',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          reason: 'invalid_reason',
        },
      }),
    );

    assert.equal(opSent.length, 1);
    assert.equal(
      (opSent[0].payload as Record<string, unknown>).error,
      'VALIDATION_ERROR',
    );
  });

  // ── credential/request event routing ─────────────────────

  it('routes credential/request event from agent to operators', () => {
    const { agentClient, opSent } = setupSession(sessions);

    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/request',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          reason: 'Login required to check order status',
        },
      }),
    );

    // Operator receives credential/request event
    assert.equal(opSent.length, 1);
    assert.equal(opSent[0].type, 'event');
    assert.equal(opSent[0].event, 'credential/request');
    assert.equal(
      (opSent[0].payload as Record<string, unknown>).domain,
      'amazon.com',
    );
  });

  // ── Sensitive events excluded from history ───────────────

  it('credential/request events are excluded from session history', () => {
    const { session, agentClient } = setupSession(sessions);

    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/request',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          reason: 'Login required',
        },
      }),
    );

    const history = sessions.getHistory(session.id);
    const credentialEntries = history.filter(
      (h) => h.message.event === 'credential/request',
    );
    assert.equal(credentialEntries.length, 0);
  });

  // ── NO_AGENT error ───────────────────────────────────────

  it('returns NO_AGENT when no agent is connected for credential.response', () => {
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
        method: 'credential.response',
        id: 'req-no-agent',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          credentials: [{ username: 'u', password: 'p' }],
        },
      }),
    );

    assert.equal(sent.length, 1);
    assert.equal(
      (sent[0].payload as Record<string, unknown>).error,
      'NO_AGENT',
    );
  });

  // ── 30-second timeout ────────────────────────────────────

  it('sends credential/none with timeout reason after 30 seconds', () => {
    mock.timers.enable({ apis: ['setTimeout'] });

    const { agentClient, agentSent } = setupSession(sessions);

    // Agent sends credential/request
    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/request',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          reason: 'Login required',
        },
      }),
    );

    // Clear the broadcast message the agent client doesn't receive
    // (it goes to operators only, agentSent should be empty here)
    assert.equal(agentSent.length, 0);

    // Advance time by 30 seconds
    mock.timers.tick(30_000);

    // Agent should receive credential/none with reason 'timeout'
    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].type, 'event');
    assert.equal(agentSent[0].event, 'credential/none');
    assert.equal(
      (agentSent[0].payload as Record<string, unknown>).reason,
      'timeout',
    );
    assert.equal(
      (agentSent[0].payload as Record<string, unknown>).requestId,
      TEST_REQUEST_ID,
    );
  });

  it('clears timeout when credential.response is received', () => {
    mock.timers.enable({ apis: ['setTimeout'] });

    const { agentClient, opClient, agentSent } = setupSession(sessions);

    // Agent sends credential/request
    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/request',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          reason: 'Login required',
        },
      }),
    );

    // Operator responds with credentials before timeout
    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.response',
        id: 'req-early',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          credentials: [{ username: 'u', password: 'p' }],
        },
      }),
    );

    // Agent received the credential/response event
    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].event, 'credential/response');

    // Advance time past timeout — should NOT send another message
    mock.timers.tick(30_000);
    assert.equal(agentSent.length, 1); // Still only the one response
  });

  it('clears timeout when credential.none is received', () => {
    mock.timers.enable({ apis: ['setTimeout'] });

    const { agentClient, opClient, agentSent } = setupSession(sessions);

    // Agent sends credential/request
    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/request',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          reason: 'Login required',
        },
      }),
    );

    // Operator responds with "no credentials"
    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.none',
        id: 'req-none-early',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          reason: 'user_denied',
        },
      }),
    );

    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].event, 'credential/none');
    assert.equal(
      (agentSent[0].payload as Record<string, unknown>).reason,
      'user_denied',
    );

    // Advance time past timeout — should NOT send timeout
    mock.timers.tick(30_000);
    assert.equal(agentSent.length, 1);
  });

  // ── Security: history exclusion ──────────────────────────

  it('credential.response is not stored in session history', () => {
    const { session, opClient, agentSent } = setupSession(sessions);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.response',
        id: 'req-hist-1',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          credentials: [{ username: 'u', password: 'p' }],
        },
      }),
    );

    // Verify agent received the event
    assert.equal(agentSent.length, 1);

    // Verify nothing in history
    const history = sessions.getHistory(session.id);
    const credEntries = history.filter(
      (h) =>
        h.message.method === 'credential.response' ||
        h.message.event === 'credential/response',
    );
    assert.equal(credEntries.length, 0);
  });

  it('credential.none is not stored in session history', () => {
    const { session, opClient } = setupSession(sessions);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'credential.none',
        id: 'req-hist-2',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          reason: 'no_credentials',
        },
      }),
    );

    const history = sessions.getHistory(session.id);
    const credEntries = history.filter(
      (h) =>
        h.message.method === 'credential.none' ||
        h.message.event === 'credential/none',
    );
    assert.equal(credEntries.length, 0);
  });

  it('credential/request only reaches operator clients, not other nodes', () => {
    const session = sessions.createSession();

    const { ws: opWs, sent: opSent } = mockWs();
    const { ws: agentWs, sent: agentSent } = mockWs();
    const { ws: otherNodeWs, sent: otherNodeSent } = mockWs();

    const opClient = makeClient(opWs, {
      sessionId: session.id,
      deviceToken: 'op-iso',
      role: 'operator',
    });
    const agentClient = makeClient(agentWs, {
      sessionId: session.id,
      deviceToken: 'agent-iso',
      role: 'node',
      scopes: ['agent'],
    });
    const otherNode = makeClient(otherNodeWs, {
      sessionId: session.id,
      deviceToken: 'other-node-iso',
      role: 'node',
      scopes: ['worker'],
    });

    sessions.addClient(session.id, opClient);
    sessions.addClient(session.id, agentClient);
    sessions.addClient(session.id, otherNode);

    // Agent sends credential/request
    router.handleMessage(
      agentClient,
      JSON.stringify({
        type: 'event',
        event: 'credential/request',
        payload: {
          requestId: TEST_REQUEST_ID,
          domain: 'amazon.com',
          reason: 'Login required',
        },
      }),
    );

    // Operator receives it
    assert.equal(opSent.length, 1);
    assert.equal(opSent[0].event, 'credential/request');

    // Other node does NOT receive it
    assert.equal(otherNodeSent.length, 0);
  });
});
