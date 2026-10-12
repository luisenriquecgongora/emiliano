import { app, BrowserWindow, globalShortcut, screen, ipcMain } from 'electron';
import path from 'path';

let dockWindow: BrowserWindow | null = null;
let overlayWindow: BrowserWindow | null = null;

function createDockWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;

  const dockWidth = 420;
  const dockHeight = Math.min(840, height - 60);

  dockWindow = new BrowserWindow({
    width: dockWidth,
    height: dockHeight,
    x: width - dockWidth - 20,
    y: Math.max(30, Math.floor((height - dockHeight) / 2)),
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: true,
    skipTaskbar: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    dockWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    dockWindow.loadFile(path.join(__dirname, '../renderer/index.html'));
  }
}

function createOverlayWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.bounds;

  overlayWindow = new BrowserWindow({
    width,
    height,
    x: 0,
    y: 0,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    hasShadow: false,
    focusable: false,
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Make the entire window click-through so user can interact with apps behind it
  overlayWindow.setIgnoreMouseEvents(true, { forward: true });

  if (process.env.VITE_DEV_SERVER_URL) {
    overlayWindow.loadURL(`${process.env.VITE_DEV_SERVER_URL}#overlay`);
  } else {
    overlayWindow.loadFile(path.join(__dirname, '../renderer/index.html'), { hash: 'overlay' });
  }
}

app.whenReady().then(() => {
  createDockWindow();
  createOverlayWindow();

  // Emergency Kill-Switch: Escape key halts actions immediately
  globalShortcut.register('Escape', () => {
    console.log('[Safety] Emergency Kill-Switch (Escape) pressed.');
    dockWindow?.webContents.send('EMERGENCY_STOP');
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createDockWindow();
      createOverlayWindow();
    }
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
