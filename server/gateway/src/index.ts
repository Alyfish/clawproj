import GatewayServer from './ws-server.js';
import { createApprovalSystem } from '../approvals/index.js';
import { createPushService, type PushService } from './push.js';
import { Scheduler } from './scheduler.js';
import { z } from 'zod';

const PORT = parseInt(process.env.GATEWAY_PORT ?? '8080', 10);

const server = new GatewayServer({ port: PORT });

// ── Push service (graceful no-op if APNS_* env vars missing) ──
const pushService: PushService | null = createPushService(server.getDB());

// Create approval system with persistence + push integration
const _approvalSystem = createApprovalSystem(
  (sessionId, event, payload) => {
    // Broadcast to connected operators via WebSocket
    const clients = server
      .getSessionManager()
      .getSessionClients(sessionId, { role: 'operator' });
    for (const c of clients) {
      try {
        c.ws.send(JSON.stringify({ type: 'event', event, payload }));
      } catch {
        // Client disconnected, will be cleaned up
      }
    }

    // Send push notification for approval requests
    if (pushService && event === 'approval/requested') {
      pushService
        .sendApprovalRequest(sessionId, {
          id: payload.id as string,
          taskId: payload.taskId as string,
          action: payload.action as string,
          description: payload.description as string,
        })
        .catch((err) => {
          console.error('Push approval error:', err);
        });
    }
  },
  600_000,
  server.getDB(),
);

// ── Push hook for agent events (task complete, price alerts) ──
const pushHook = pushService
  ? (sessionId: string, event: string, payload: Record<string, unknown>) => {
      switch (event) {
        case 'task/update':
          if (payload.status === 'completed') {
            pushService
              .sendTaskComplete(sessionId, {
                taskId: payload.taskId as string,
                summary: payload.summary as string | undefined,
              })
              .catch((err) => console.error('Push task error:', err));
          }
          break;
        case 'monitoring/alert':
          pushService
            .sendPriceAlert(sessionId, {
              taskId: payload.taskId as string,
              title: (payload.title as string) ?? 'Price Alert',
              body:
                (payload.body as string) ?? 'A monitored price has changed.',
            })
            .catch((err) => console.error('Push price error:', err));
          break;
      }
    }
  : undefined;

// ── Configure router with DB access and push hook ──
server.configureRouter(server.getDB(), pushHook);

// ── Scheduler (cron jobs for autonomous watches) ──
const scheduler = new Scheduler({
  db: server.getDB(),
  findAgentSession: (_userId: string) => {
    const sessions = server.getSessionManager().listSessions();
    for (const session of sessions) {
      const agents = server
        .getSessionManager()
        .getSessionClients(session.id, { role: 'node' });
      const agent = agents.find((n) => n.scopes.includes('agent'));
      if (agent) {
        return { sessionId: session.id, agentWs: agent.ws };
      }
    }
    return null;
  },
  sendToAgent: (ws, event, payload) => {
    try {
      ws.send(JSON.stringify({ type: 'event', event, payload }));
    } catch {
      // Agent disconnected
    }
  },
  broadcastToOperators: (sessionId, event, payload) => {
    const operators = server
      .getSessionManager()
      .getSessionClients(sessionId, { role: 'operator' });
    for (const op of operators) {
      try {
        op.ws.send(JSON.stringify({ type: 'event', event, payload }));
      } catch {
        // Operator disconnected
      }
    }
  },
});
server.getRouter().setScheduler(scheduler);
scheduler.start();

// ── Test push endpoint ──
if (pushService) {
  const TestPushSchema = z.object({
    sessionId: z.string(),
    type: z.enum([
      'APPROVAL_REQUEST',
      'TASK_COMPLETE',
      'PRICE_ALERT',
      'AGENT_MESSAGE',
    ]),
  });

  server.setTestPushHandler((body, res) => {
    try {
      const parsed = TestPushSchema.parse(JSON.parse(body));
      const tokens = server.getDB().getDeviceTokensForSession(parsed.sessionId);
      if (tokens.length === 0) {
        res.writeHead(404, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'No device tokens for session' }));
        return;
      }
      pushService
        .sendTestPush(
          tokens.map((t) => t.token),
          parsed.type,
        )
        .then((result) => {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ ok: true, ...result }));
        })
        .catch((err) => {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: String(err) }));
        });
    } catch {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid request body' }));
    }
  });
}

await server.start();

console.log(
  JSON.stringify({
    level: 'info',
    event: 'gateway:started',
    data: { port: PORT, push: pushService ? 'enabled' : 'disabled' },
    timestamp: new Date().toISOString(),
  }),
);

// Graceful shutdown
const shutdown = async (signal: string) => {
  console.log(
    JSON.stringify({
      level: 'info',
      event: 'gateway:shutdown',
      data: { signal },
      timestamp: new Date().toISOString(),
    }),
  );
  scheduler.destroy();
  pushService?.shutdown();
  await server.stop();
  process.exit(0);
};

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
