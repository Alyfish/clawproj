import { describe, it, beforeEach } from 'node:test';
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

// ── Tests ──────────────────────────────────────────────────────

describe('card.action routing', () => {
  let sessions: SessionManager;
  let router: MessageRouter;

  beforeEach(() => {
    sessions = new SessionManager();
    router = new MessageRouter(sessions);
  });

  it('returns VALIDATION_ERROR for missing payload', () => {
    const { ws, sent } = mockWs();
    const client = makeClient(ws);
    const session = sessions.createSession();
    client.sessionId = session.id;
    sessions.addClient(session.id, client);

    router.handleMessage(
      client,
      JSON.stringify({
        type: 'req',
        method: 'card.action',
        id: 'req-1',
        payload: {},
      }),
    );

    assert.equal(sent.length, 1);
    assert.equal(sent[0].payload?.error, 'VALIDATION_ERROR');
  });

  it('returns VALIDATION_ERROR for empty action string', () => {
    const { ws, sent } = mockWs();
    const client = makeClient(ws);
    const session = sessions.createSession();
    client.sessionId = session.id;
    sessions.addClient(session.id, client);

    router.handleMessage(
      client,
      JSON.stringify({
        type: 'req',
        method: 'card.action',
        id: 'req-2',
        payload: { action: '', cardType: 'flight', cardData: {} },
      }),
    );

    assert.equal(sent.length, 1);
    assert.equal(sent[0].payload?.error, 'VALIDATION_ERROR');
  });

  it('returns NO_AGENT when no agent is connected', () => {
    const { ws, sent } = mockWs();
    const client = makeClient(ws);
    const session = sessions.createSession();
    client.sessionId = session.id;
    sessions.addClient(session.id, client);

    router.handleMessage(
      client,
      JSON.stringify({
        type: 'req',
        method: 'card.action',
        id: 'req-3',
        payload: {
          action: 'watch_price',
          cardType: 'flight',
          cardData: { price: 350 },
        },
      }),
    );

    assert.equal(sent.length, 1);
    assert.equal(sent[0].payload?.error, 'NO_AGENT');
  });

  it('forwards card.action to agent and responds to operator', () => {
    const { ws: opWs, sent: opSent } = mockWs();
    const { ws: agentWs, sent: agentSent } = mockWs();

    const session = sessions.createSession();

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

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'card.action',
        id: 'req-4',
        payload: {
          action: 'watch_price',
          cardType: 'flight',
          cardData: { airline: 'UA', price: 350 },
        },
      }),
    );

    // Agent should receive forwarded event
    assert.equal(agentSent.length, 1);
    assert.equal(agentSent[0].type, 'event');
    assert.equal(agentSent[0].event, 'card/action');
    assert.equal(agentSent[0].payload?.action, 'watch_price');
    assert.equal(agentSent[0].payload?.cardType, 'flight');
    assert.deepEqual(agentSent[0].payload?.cardData, {
      airline: 'UA',
      price: 350,
    });
    assert.equal(agentSent[0].payload?.sessionId, session.id);
    assert.equal(agentSent[0].payload?.from, 'op-device');
    assert.ok(agentSent[0].payload?.timestamp);

    // Operator should receive ACK
    assert.equal(opSent.length, 1);
    assert.equal(opSent[0].type, 'res');
    assert.equal(opSent[0].id, 'req-4');
    assert.equal(opSent[0].method, 'card.action');
    assert.equal(opSent[0].payload?.status, 'received');
    assert.equal(opSent[0].payload?.action, 'watch_price');
  });

  it('stores card.action in session history', () => {
    const { ws: opWs } = mockWs();
    const { ws: agentWs } = mockWs();

    const session = sessions.createSession();

    const opClient = makeClient(opWs, {
      sessionId: session.id,
      deviceToken: 'op-hist',
      role: 'operator',
    });
    const agentClient = makeClient(agentWs, {
      sessionId: session.id,
      deviceToken: 'agent-hist',
      role: 'node',
      scopes: ['agent'],
    });

    sessions.addClient(session.id, opClient);
    sessions.addClient(session.id, agentClient);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'card.action',
        id: 'req-5',
        payload: { action: 'place_bet', cardType: 'pick', cardData: {} },
      }),
    );

    const history = sessions.getHistory(session.id);
    assert.ok(history.length >= 1);
    const last = history[history.length - 1];
    assert.equal(last.sender, 'operator');
    assert.equal(last.message.method, 'card.action');
  });

  it('defaults cardData to empty object when omitted', () => {
    const { ws: opWs, sent: opSent } = mockWs();
    const { ws: agentWs, sent: agentSent } = mockWs();

    const session = sessions.createSession();

    const opClient = makeClient(opWs, {
      sessionId: session.id,
      role: 'operator',
    });
    const agentClient = makeClient(agentWs, {
      sessionId: session.id,
      deviceToken: 'agent-def',
      role: 'node',
      scopes: ['agent'],
    });

    sessions.addClient(session.id, opClient);
    sessions.addClient(session.id, agentClient);

    router.handleMessage(
      opClient,
      JSON.stringify({
        type: 'req',
        method: 'card.action',
        id: 'req-6',
        payload: { action: 'save', cardType: 'doc' },
      }),
    );

    // Agent receives empty cardData
    assert.equal(agentSent.length, 1);
    assert.deepEqual(agentSent[0].payload?.cardData, {});

    // Operator receives ACK
    assert.equal(opSent.length, 1);
    assert.equal(opSent[0].payload?.status, 'received');
  });
});
