import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Tauri loads the renderer from devUrl in development and from dist/ in builds
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
  },
  envPrefix: ['VITE_', 'TAURI_ENV_'],
  build: {
    outDir: 'dist',
    target: 'es2021',
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
});
