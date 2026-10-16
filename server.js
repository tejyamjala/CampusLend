const { spawn } = require('node:child_process');

const python = process.env.PYTHON || 'python3';
const port = String(process.env.PORT || 3000);
const args = [
  '-m', 'gunicorn',
  '--bind', `0.0.0.0:${port}`,
  '--workers', '2',
  '--threads', '4',
  '--timeout', '60',
  'app:app',
];

const service = spawn(python, args, {
  stdio: 'inherit',
  env: { ...process.env, APP_ENV: process.env.APP_ENV || 'production' },
});

let shutdownRequested = false;
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    shutdownRequested = true;
    service.kill(signal);
  });
}

service.on('error', (error) => {
  console.error(`Could not start the CampusLend Flask service: ${error.message}`);
  process.exitCode = 1;
});

service.on('exit', (code, signal) => {
  process.exitCode = shutdownRequested ? 0 : signal ? 1 : (code ?? 1);
});
