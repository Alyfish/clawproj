/**
 * Standalone CLI test client for the Claw Gateway.
 *
 * Usage:
 *   npx tsx test-client.ts              — connect as operator (new session)
 *   npx tsx test-client.ts node <sid>   — connect as agent node to session <sid>
 */

import WebSocket from 'ws';
import { randomUUID } from 'node:crypto';

const GATEWAY_URL = process.env.GATEWAY_URL ?? 'ws://localhost:8080';
const role = process.argv[2] ?? 'operator';
const targetSessionId = process.argv[3];

// ── Helpers ────────────────────────────────────────────────

function uuid(): string {
  return randomUUID();
}

function ts(): string {
  return new Date().toISOString();
}

function log(label: string, data: unknown): void {
  console.log(`[${ts()}] ${label}:`, JSON.stringify(data, null, 2));
}

function send(ws: WebSocket, msg: Record<string, unknown>): void {
  const raw = JSON.stringify(msg);
  console.log(`[${ts()}] >>> SEND:`, raw);
  ws.send(raw);
}

// ── Banner ─────────────────────────────────────────────────

console.log('═══════════════════════════════════════════');
console.log('  Claw Gateway — Test Client');
console.log(`  Role: ${role}`);
console.log(`  Gateway: ${GATEWAY_URL}`);
if (targetSessionId) console.log(`  Session: ${targetSessionId}`);
console.log('═══════════════════════════════════════════');
console.log();

// ── Connect ────────────────────────────────────────────────

const ws = new WebSocket(GATEWAY_URL);

let sessionId: string | undefined;
let deviceToken: string | undefined;

ws.on('open', () => {
  log('CONNECTED', { url: GATEWAY_URL });

  if (role === 'node') {
    // Node handshake — must specify sessionId to join
    send(ws, {
      type: 'req',
      id: uuid(),
      method: 'connect',
      payload: {
        role: 'node',
        scopes: ['agent'],
        sessionId: targetSessionId,
      },
    });
  } else {
    // Operator handshake
    send(ws, {
      type: 'req',
      id: uuid(),
      method: 'connect',
      payload: {
        role: 'operator',
        scopes: ['chat', 'approval', 'task'],
      },
    });
  }
});

ws.on('message', (data) => {
  let msg: Record<string, unknown>;
  try {
    msg = JSON.parse(data.toString()) as Record<string, unknown>;
  } catch {
    console.log(`[${ts()}] <<< RAW:`, data.toString());
    return;
  }

  log('<<< RECV', msg);

  // Handle connect response — extract session info
  if (msg.type === 'res' && msg.method === 'connect') {
    const payload = msg.payload as Record<string, unknown> | undefined;
    if (payload && !payload.error) {
      sessionId = payload.sessionId as string;
      deviceToken = payload.deviceToken as string;
      console.log();
      console.log('  ┌─────────────────────────────────────');
      console.log(`  │ Session:     ${sessionId}`);
      console.log(`  │ DeviceToken: ${deviceToken}`);
      console.log('  └─────────────────────────────────────');
      console.log();

      if (role === 'operator') {
        scheduleOperatorActions();
      }
    }
  }

  // Node: simulate agent response on incoming chat message
  if (
    role === 'node' &&
    msg.type === 'event' &&
    msg.event === 'chat/message:new'
  ) {
    simulateAgentResponse(msg.payload as Record<string, unknown>);
  }
});

ws.on('close', (code, reason) => {
  log('DISCONNECTED', { code, reason: reason.toString() });
  process.exit(0);
});

ws.on('error', (err) => {
  log('ERROR', { message: err.message });
});

// ── Operator: scheduled test actions ───────────────────────

function scheduleOperatorActions(): void {
  // After 2s: send a chat message
  setTimeout(() => {
    console.log('\n--- Sending chat.send ---');
    send(ws, {
      type: 'req',
      id: uuid(),
      method: 'chat.send',
      payload: {
        text: 'Find me flights from SFO to JFK next Friday, cheapest options',
        idempotencyKey: uuid(),
      },
    });
  }, 2_000);

  // After 10s: request chat history
  setTimeout(() => {
    console.log('\n--- Requesting chat.history ---');
    send(ws, {
      type: 'req',
      id: uuid(),
      method: 'chat.history',
      payload: {},
    });
  }, 10_000);
}

// ── Node: simulate agent response ──────────────────────────

function simulateAgentResponse(payload: Record<string, unknown>): void {
  const incomingText = (payload?.text as string) ?? '';
  console.log(`\n--- Agent received: "${incomingText}" ---`);
  console.log('--- Simulating agent response stream ---\n');

  const runId = uuid();

  // Lifecycle: start
  setTimeout(() => {
    send(ws, {
      type: 'event',
      event: 'agent/stream:lifecycle',
      payload: { status: 'start', runId },
    });
  }, 500);

  // Thinking steps
  const thinkingSteps = [
    {
      id: uuid().slice(0, 8),
      description: 'Searching SFO → JFK flights...',
      status: 'running' as const,
      toolName: 'flight_search',
      timestamp: ts(),
    },
    {
      id: uuid().slice(0, 8),
      description: 'Comparing prices across airlines...',
      status: 'running' as const,
      toolName: 'price_compare',
      timestamp: ts(),
    },
    {
      id: uuid().slice(0, 8),
      description: 'Ranking results by price...',
      status: 'running' as const,
      toolName: 'ranking',
      timestamp: ts(),
    },
  ];

  thinkingSteps.forEach((step, i) => {
    setTimeout(
      () => {
        send(ws, {
          type: 'event',
          event: 'chat/state:delta',
          payload: { thinkingStep: step, sessionId },
        });
      },
      1_000 + i * 300,
    );
  });

  // Text deltas
  const deltas = [
    'I found ',
    '3 flights ',
    'from SFO to JFK. ',
    'The cheapest is $127 ',
    'on United, departing 6:00 AM.',
  ];

  deltas.forEach((delta, i) => {
    setTimeout(
      () => {
        send(ws, {
          type: 'event',
          event: 'agent/stream:assistant',
          payload: { delta },
        });
      },
      2_000 + i * 100,
    );
  });

  // Lifecycle: end
  setTimeout(() => {
    send(ws, {
      type: 'event',
      event: 'agent/stream:lifecycle',
      payload: { status: 'end', runId },
    });
  }, 3_000);
}

// Keep alive
process.on('SIGINT', () => {
  console.log('\nShutting down...');
  ws.close();
});
