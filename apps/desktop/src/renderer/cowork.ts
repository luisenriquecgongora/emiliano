// Client for the engine's desktop cowork API (see packages/engine/emiliano/server/app.py)

import { ENGINE_HTTP_URL } from './chats';

export interface DesktopWindow {
  hwnd: number;
  title: string;
  bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  is_pinned: boolean;
}

export interface UIElement {
  hwnd: number;
  name: string;
  role: 'Window' | 'Button' | 'TextInput' | 'List' | 'Control';
  class: string;
  bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  action: 'click' | 'type' | 'select' | 'focus';
}

export interface PinResponse {
  status: 'pinned' | 'unpinned';
  hwnd?: number;
  title?: string;
}

export const coworkApi = {
  listWindows: async (): Promise<DesktopWindow[]> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/cowork/windows`);
    if (!res.ok) throw new Error(`Failed to list windows: ${res.status}`);
    const data = await res.json();
    return data.windows || [];
  },

  pin: async (hwnd: number, title?: string): Promise<PinResponse> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/cowork/pin`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ hwnd, title }),
    });
    if (!res.ok) throw new Error(`Failed to pin window: ${res.status}`);
    return res.json();
  },

  unpin: async (): Promise<PinResponse> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/cowork/unpin`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`Failed to unpin window: ${res.status}`);
    return res.json();
  },

  getElements: async (hwnd?: number): Promise<UIElement[]> => {
    const url = hwnd
      ? `${ENGINE_HTTP_URL}/api/cowork/elements?hwnd=${hwnd}`
      : `${ENGINE_HTTP_URL}/api/cowork/elements`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to get UI elements: ${res.status}`);
    const data = await res.json();
    return data.elements || [];
  },

  click: async (x: number, y: number, button = 'left', clicks = 1): Promise<void> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/cowork/click`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ x, y, button, clicks }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Click failed' }));
      throw new Error(err.detail || 'Click failed');
    }
  },

  typeText: async (text: string): Promise<void> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/cowork/type`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Type failed' }));
      throw new Error(err.detail || 'Type failed');
    }
  },
};
