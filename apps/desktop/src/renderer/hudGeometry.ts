// Where the HUD overlay draws a highlight. Pure, so it is unit-tested with `node --test`.
//
// The engine is per-monitor DPI aware, so UI Automation bounds arrive in physical screen
// pixels. The overlay window covers the primary monitor (origin 0,0) and lays out in CSS
// pixels, which are physical pixels divided by devicePixelRatio (1.5 at 150% scaling).

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface OverlayRect {
  left: number;
  top: number;
  width: number;
  height: number;
  /** The label sits above the box unless that would put it off the top of the screen. */
  labelBelow: boolean;
}

/** Height of the action label drawn above a highlight, in CSS pixels. */
export const LABEL_HEIGHT = 28;

export function toOverlayRect(bounds: Box, devicePixelRatio: number, origin: { x: number; y: number } = { x: 0, y: 0 }): OverlayRect {
  const dpr = devicePixelRatio > 0 ? devicePixelRatio : 1;
  const top = (bounds.y - origin.y) / dpr;
  return {
    left: (bounds.x - origin.x) / dpr,
    top,
    width: bounds.width / dpr,
    height: bounds.height / dpr,
    labelBelow: top < LABEL_HEIGHT,
  };
}
