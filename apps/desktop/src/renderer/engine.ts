import { useEffect, useRef, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow';

export const ENGINE_WS_URL = 'ws://127.0.0.1:8765/ws';
const RECONNECT_DELAY_MS = 1500;

/** True when this page is the transparent HUD overlay window (or #overlay in a plain browser). */
export function isOverlayWindow(): boolean {
  return isTauri() ? getCurrentWebviewWindow().label === 'overlay' : window.location.hash === '#overlay';
}

/**
 * Keeps a WebSocket open to the Python engine. The bundled engine takes a few seconds to
 * start (and can restart), so the connection retries until it succeeds and after any drop.
 * Returns the open socket, or null while connecting.
 */
export function useEngineSocket(
  onMessage: (msg: any) => void,
  onOpen?: (socket: WebSocket) => void,
  url: string = ENGINE_WS_URL,
): WebSocket | null {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const handlers = useRef({ onMessage, onOpen });
  handlers.current = { onMessage, onOpen };

  useEffect(() => {
    let disposed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let current: WebSocket | null = null;

    const connect = () => {
      const ws = new WebSocket(url);
      current = ws;
      ws.onopen = () => {
        setSocket(ws);
        handlers.current.onOpen?.(ws);
      };
      ws.onmessage = (event) => {
        try {
          handlers.current.onMessage(JSON.parse(event.data));
        } catch (e) {
          console.error(e);
        }
      };
      ws.onclose = () => {
        setSocket(null);
        if (!disposed) retry = setTimeout(connect, RECONNECT_DELAY_MS);
      };
    };

    connect();
    return () => {
      disposed = true;
      clearTimeout(retry);
      current?.close();
    };
  }, [url]);

  return socket;
}
