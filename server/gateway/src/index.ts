import GatewayServer from './ws-server.js';

const PORT = parseInt(process.env.GATEWAY_PORT ?? '8080', 10);

const server = new GatewayServer({ port: PORT });

await server.start();

console.log(
  JSON.stringify({
    level: 'info',
    event: 'gateway:started',
    data: { port: PORT },
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
  await server.stop();
  process.exit(0);
};

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
