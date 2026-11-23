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
  /** UI Automation control type (Button, TextInput, Hyperlink, MenuItem, ...), or Control/Window */
  role: string;
  class: string;
  /** Stable id the app gives the control (UI Automation only; often empty) */
  automation_id?: string;
  enabled?: boolean;
  /** How it was found: 'uia' (UI Automation) or absent for Win32 child windows */
  source?: 'uia';
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
  getBrowserStatus: async (): Promise<{ connected: boolean; extension_info: Record<string, any>; connected_browsers?: any[] }> => {
    try {
      const res = await fetch(`${ENGINE_HTTP_URL}/api/browser/status`);
      if (!res.ok) return { connected: false, extension_info: {}, connected_browsers: [] };
      return res.json();
    } catch {
      return { connected: false, extension_info: {}, connected_browsers: [] };
    }
  },

  revealExtensionFolder: async (browser: 'chrome' | 'firefox' = 'chrome'): Promise<{ opened: boolean; path: string }> => {
    try {
      const res = await fetch(`${ENGINE_HTTP_URL}/api/browser/reveal-extension`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ browser }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    } catch (e) {
      console.warn('[coworkApi] revealExtensionFolder failed:', e);
      return { opened: false, path: '' };
    }
  },

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

  typeText: async (text: string, x?: number, y?: number): Promise<void> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/cowork/type`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, x, y }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Type failed' }));
      throw new Error(err.detail || 'Type failed');
    }
  },

  runAgent: async (goal: string, hwnd?: number, model?: string): Promise<{ status: string; output: string }> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/cowork/run`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ goal, hwnd, model }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Cowork agent run failed' }));
      throw new Error(err.detail || 'Cowork agent run failed');
    }
    return res.json();
  },

  resizeHud: async (
    width?: number,
    height?: number,
    direction: string = 'West',
    x?: number,
    y?: number,
  ): Promise<{ status: string; width: number; height: number; x?: number; y?: number }> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/cowork/resize_hud`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ width, height, direction, x, y }),
    });
    if (!res.ok) throw new Error(`Failed to resize HUD: ${res.status}`);
    return res.json();
  },

  setAlwaysOnTop: async (enabled: boolean): Promise<{ status: string; always_on_top?: boolean }> => {
    try {
      const res = await fetch(`${ENGINE_HTTP_URL}/api/cowork/always_on_top`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    } catch (e) {
      console.warn('[coworkApi] setAlwaysOnTop failed:', e);
      return { status: 'error' };
    }
  },

  getSkillContent: async (skillId: string): Promise<Record<string, any>> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/skills/${encodeURIComponent(skillId)}/content`);
    if (!res.ok) throw new Error(`Failed to load skill content: ${res.status}`);
    const data = await res.json();
    return data.skill;
  },

  synthesizeSkill: async (payload: {
    id: string;
    title: string;
    description: string;
    instructions_md: string;
    triggers?: string[];
    selectors?: Record<string, string>;
    category?: string;
  }): Promise<{ status: string; skill: Record<string, any> }> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/skills/synthesize`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Failed to synthesize skill: ${res.status}`);
    return res.json();
  },

  approveSkill: async (skillId: string): Promise<{ status: string; skill_id: string; state: string }> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/skills/${encodeURIComponent(skillId)}/approve`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`Failed to approve skill: ${res.status}`);
    return res.json();
  },

  discardSkill: async (skillId: string): Promise<{ status: string; skill_id: string; state: string }> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/skills/${encodeURIComponent(skillId)}/discard`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`Failed to discard skill: ${res.status}`);
    return res.json();
  },

  patchSkill: async (
    skillId: string,
    payload: { selectors?: Record<string, string>; append_notes?: string },
  ): Promise<{ status: string; skill_id: string; state: string }> => {
    const res = await fetch(`${ENGINE_HTTP_URL}/api/skills/${encodeURIComponent(skillId)}/patch`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Failed to patch skill: ${res.status}`);
    return res.json();
  },
};
