import assert from 'node:assert/strict';
import { test } from 'node:test';
import { toOverlayRect } from './hudGeometry.ts';

const box = { x: 300, y: 150, width: 120, height: 60 };

test('at 100% scaling physical pixels are CSS pixels', () => {
  assert.deepEqual(toOverlayRect(box, 1), { left: 300, top: 150, width: 120, height: 60, labelBelow: false });
});

test('at 150% scaling bounds are divided by the device pixel ratio', () => {
  // Without this the box drew 1.5x too far right and down on scaled laptop screens.
  assert.deepEqual(toOverlayRect(box, 1.5), { left: 200, top: 100, width: 80, height: 40, labelBelow: false });
});

test('a monitor origin is subtracted before scaling', () => {
  const r = toOverlayRect({ x: 2020, y: 100, width: 10, height: 10 }, 2, { x: 1920, y: 0 });
  assert.equal(r.left, 50);
  assert.equal(r.top, 50);
});

test('a target at the top edge gets its label below, not off screen', () => {
  assert.equal(toOverlayRect({ x: 0, y: 4, width: 40, height: 20 }, 1).labelBelow, true);
});

test('a bad device pixel ratio falls back to 1', () => {
  assert.equal(toOverlayRect(box, 0).left, 300);
});
