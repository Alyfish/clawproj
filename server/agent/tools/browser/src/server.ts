import express from 'express';
import type { Request, Response } from 'express';
import { z } from 'zod';
import { SessionManager } from './sessions.js';
import { ActionExecutor } from './executor.js';
import type { ActionResult } from './executor.js';
import { CheckpointDetector } from './checkpoint.js';

// ── Constants ────────────────────────────────────────────────────

const VALID_ACTIONS = [
  'navigate',
  'search',
  'fill_form',
  'click',
  'extract_data',
  'take_screenshot',
  'get_page_content',
] as const;

const PORT = parseInt(process.env.CLAWBOT_BROWSER_PORT || '8090', 10);

// ── Validation Schemas ───────────────────────────────────────────

const ExecuteRequestSchema = z.object({
  session_id: z.string().optional().default('default'),
  action: z.enum(VALID_ACTIONS),
  params: z.record(z.string(), z.unknown()),
});

const CloseSessionSchema = z.object({
  session_id: z.string().min(1, 'session_id is required'),
});

// ── App Setup ────────────────────────────────────────────────────

const app = express();
app.use(express.json({ limit: '10mb' })); // screenshots can be large

const sessionManager = new SessionManager();
const checkpointDetector = new CheckpointDetector();
const executor = new ActionExecutor(sessionManager, checkpointDetector);

// ── GET /health ──────────────────────────────────────────────────

app.get('/health', (_req: Request, res: Response) => {
  try {
    res.json({
      status: 'ok',
      uptime: process.uptime(),
      sessions: sessionManager.getStatus(),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    res.status(500).json({ status: 'error', error: message });
  }
});

// ── POST /execute ────────────────────────────────────────────────

app.post('/execute', async (req: Request, res: Response) => {
  const parsed = ExecuteRequestSchema.safeParse(req.body);

  if (!parsed.success) {
    res.status(400).json({
      success: false,
      error: `Validation error: ${parsed.error.issues.map((i) => i.message).join(', ')}`,
    });
    return;
  }

  const { session_id, action, params } = parsed.data;

  try {
    const result: ActionResult = await executor.execute(
      session_id,
      action,
      params,
    );
    res.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal error';
    console.error(`[BrowserSidecar] Execute error: ${message}`);
    res.status(500).json({
      success: false,
      error: message,
      screenshot: undefined,
    });
  }
});

// ── POST /session/close ──────────────────────────────────────────

app.post('/session/close', async (req: Request, res: Response) => {
  const parsed = CloseSessionSchema.safeParse(req.body);

  if (!parsed.success) {
    res.status(400).json({
      success: false,
      error: `Validation error: ${parsed.error.issues.map((i) => i.message).join(', ')}`,
    });
    return;
  }

  const { session_id } = parsed.data;

  try {
    await (sessionManager as any).closeSession(session_id);
    res.json({ success: true, message: `Session ${session_id} closed` });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal error';
    console.error(`[BrowserSidecar] Session close error: ${message}`);
    res.status(500).json({ success: false, error: message });
  }
});

// ── Startup ──────────────────────────────────────────────────────

async function main() {
  console.log(`[BrowserSidecar] Initializing browser...`);
  await sessionManager.initialize();
  console.log(`[BrowserSidecar] Browser ready`);

  const server = app.listen(PORT, () => {
    console.log(`[BrowserSidecar] Listening on port ${PORT}`);
    console.log(`[BrowserSidecar] Health: http://localhost:${PORT}/health`);
  });

  // Graceful shutdown
  const shutdown = async (signal: string) => {
    console.log(`[BrowserSidecar] Received ${signal}, shutting down...`);
    server.close();
    await sessionManager.shutdown();
    console.log(`[BrowserSidecar] Shutdown complete`);
    process.exit(0);
  };

  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
}

main().catch((err) => {
  console.error('[BrowserSidecar] Fatal error:', err);
  process.exit(1);
});
