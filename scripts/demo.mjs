#!/usr/bin/env node
/** Local playground: isolated demo API + polling worker + Vite, one command. */
import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = path.join(
  root,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
);
const children = new Set();
let closing = false;
function stop(code = 0) {
  if (closing) return;
  closing = true;
  process.exitCode = code;
  for (const child of children) child.kill('SIGTERM');
  const timer = setTimeout(() => {
    for (const child of children) child.kill('SIGKILL');
  }, 5000);
  timer.unref();
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
function run(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit', ...options });
  if (result.error || result.status !== 0)
    throw new Error(`${command} failed. Python 3.12+ and Node 24 are required.`);
}
function launch(command, args, options = {}) {
  const child = spawn(command, args, { cwd: root, stdio: 'inherit', ...options });
  children.add(child);
  child.on('error', (error) => {
    console.error(error.message);
    stop(1);
  });
  child.on('exit', (code) => {
    children.delete(child);
    if (!closing) stop(code || 1);
  });
  return child;
}
async function freePort(start) {
  for (let port = start; port < start + 30; port++) {
    const available = await new Promise((resolve) => {
      const server = net.createServer();
      server.once('error', (error) => {
        if (error.code === 'EADDRINUSE') resolve(false);
        else {
          console.error(`Cannot bind localhost:${port}: ${error.message}`);
          resolve(null);
        }
      });
      server.listen(port, '127.0.0.1', () => server.close(() => resolve(true)));
    });
    if (available === true) return port;
    if (available === null) throw new Error('Local server binding is unavailable.');
  }
  throw new Error(`No available localhost port starting at ${start}`);
}
try {
  if (!existsSync(python)) {
    console.log('Preparing the local Python environment…');
    run(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), [
      '-m',
      'venv',
      path.join(root, '.venv'),
    ]);
  }
  const environment = {
    ...process.env,
    PYTHONPATH: path.join(root, 'backend'),
    LITELLM_LOCAL_MODEL_COST_MAP: 'True',
  };
  const probe = spawnSync(
    python,
    [
      '-c',
      "import importlib.util,sys;sys.exit(0 if all(importlib.util.find_spec(x) for x in ['fastapi','uvicorn','sqlalchemy','alembic','cryptography','pwdlib','jwt','httpx','multipart','jsonschema','pypdf','pgvector','celery','litellm','psycopg']) else 1)",
    ],
    { env: environment, stdio: 'ignore' },
  );
  if (probe.status !== 0) {
    console.log('Installing backend dependencies for the first run…');
    run(python, ['-m', 'pip', 'install', '-c', 'backend/requirements.lock', '-e', 'backend'], {
      env: environment,
    });
  }
  const apiPort = await freePort(8000);
  const uiPort = await freePort(5173);
  const origins = `http://localhost:${uiPort},http://127.0.0.1:${uiPort}`;
  const env = {
    ...environment,
    CCAI_DEMO_ORIGINS: origins,
    CCAI_API_URL: `http://127.0.0.1:${apiPort}`,
  };
  launch(python, ['scripts/demo.py', 'api', '--port', String(apiPort)], { env });
  let ready = false;
  for (let attempt = 0; attempt < 150 && !closing; attempt++) {
    try {
      const response = await fetch(`${env.CCAI_API_URL}/api/v1/health`, {
        signal: AbortSignal.timeout(1000),
      });
      if (response.ok) {
        ready = true;
        break;
      }
    } catch {
      /* API migrations and first-run data are not ready yet. */
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (!ready || closing)
    throw new Error('The demo API did not become ready; see the startup output above.');
  launch(python, ['scripts/demo.py', 'worker'], { env });
  launch(
    process.execPath,
    [
      path.join(root, 'node_modules/vite/bin/vite.js'),
      '--host',
      '127.0.0.1',
      '--port',
      String(uiPort),
      '--strictPort',
    ],
    { cwd: path.join(root, 'frontend'), env },
  );
  console.log(
    `\nOpen-CCAI local demo\n  URL:      http://localhost:${uiPort}\n  Email:    demo@openccai.local\n  Password: OpenCCAI-Demo123!\n\nSample data and mock models are local. Changes persist in data/demo/.\nPress Ctrl+C to stop the console, API, and worker together.\n`,
  );
} catch (error) {
  console.error(`\n${error.message}`);
  stop(1);
}
