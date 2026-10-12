import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('emilianoApi', {
  onEmergencyStop: (callback: () => void) => {
    ipcRenderer.on('EMERGENCY_STOP', () => callback());
  },
  engineWsUrl: 'ws://127.0.0.1:8765/ws',
});
