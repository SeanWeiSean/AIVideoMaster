const { app, BrowserWindow, shell } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const net = require('net');

let mainWindow = null;
let serverProcess = null;
const SERVER_PORT = 5678;
const PROJECT_ROOT = path.resolve(__dirname, '..');

/**
 * Kill any existing process listening on the given port.
 * Prevents stale server processes from being reused after code changes.
 */
function killExistingServer(port) {
  try {
    // Windows: find PID listening on port and kill it
    const out = execSync(
      `powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"`,
      { encoding: 'utf-8', timeout: 5000 }
    ).trim();
    if (out) {
      const pids = [...new Set(out.split(/\r?\n/).map(s => s.trim()).filter(Boolean))];
      for (const pid of pids) {
        console.log(`Killing stale server process PID ${pid} on port ${port}`);
        try { execSync(`taskkill /F /PID ${pid}`, { timeout: 5000 }); } catch (_) {}
      }
      // Brief wait for port release
      execSync('powershell -NoProfile -Command "Start-Sleep -Milliseconds 500"', { timeout: 3000 });
    }
  } catch (_) {
    // No process on the port — that's fine
  }
}

function waitForServer(port, timeout = 30000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const check = () => {
      const sock = new net.Socket();
      sock.setTimeout(500);
      sock.on('connect', () => { sock.destroy(); resolve(); });
      sock.on('error', () => { sock.destroy(); retry(); });
      sock.on('timeout', () => { sock.destroy(); retry(); });
      sock.connect(port, '127.0.0.1');
    };
    const retry = () => {
      if (Date.now() - start > timeout) {
        reject(new Error('Server start timeout'));
      } else {
        setTimeout(check, 500);
      }
    };
    check();
  });
}

function getPythonExecutable() {
  const fs = require('fs');
  // Prefer virtual environment python if it exists
  const venvPython = path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(venvPython)) {
    console.log(`Using venv Python: ${venvPython}`);
    return venvPython;
  }
  return 'python';
}

function startPythonServer() {
  console.log('Starting Python API server...');
  const pythonExe = getPythonExecutable();
  serverProcess = spawn(pythonExe, ['server.py', '--port', String(SERVER_PORT)], {
    cwd: PROJECT_ROOT,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
  });

  serverProcess.stdout.on('data', (data) => {
    console.log(`[Server] ${data.toString().trim()}`);
  });

  serverProcess.stderr.on('data', (data) => {
    console.error(`[Server ERR] ${data.toString().trim()}`);
  });

  serverProcess.on('close', (code) => {
    console.log(`Server exited with code ${code}`);
    serverProcess = null;
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    title: 'AI Video Master',
    icon: path.join(__dirname, 'renderer', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    backgroundColor: '#0f0f23',
    show: false,
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // 外部链接用系统浏览器打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  killExistingServer(SERVER_PORT);
  startPythonServer();

  try {
    await waitForServer(SERVER_PORT);
    console.log('Server is ready!');
  } catch (e) {
    console.error('Failed to start server:', e.message);
  }

  createWindow();
});

app.on('window-all-closed', () => {
  if (serverProcess) {
    serverProcess.kill();
  }
  app.quit();
});

app.on('before-quit', () => {
  if (serverProcess) {
    serverProcess.kill();
  }
});
