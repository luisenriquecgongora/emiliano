// Run with: node --test "apps/desktop/src/**/*.test.ts"  (Node 22+ strips the types itself)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { parseMessageParts, splitInlineCode } from './messageParts.ts';

test('a fenced code block becomes a code part, without the backtick fences', () => {
  // The reply shape that used to render with raw ``` in the chat.
  const reply = [
    "Here's a concise Python snippet:",
    '',
    '```python',
    'from collections import Counter',
    'print(Counter("a b a".split()).most_common(1))',
    '```',
    '',
    'One sentence explanation: it counts words.',
  ].join('\n');
  const parts = parseMessageParts(reply);
  assert.deepEqual(parts.map((p) => p.type), ['text', 'code', 'text']);
  assert.deepEqual(parts[1], {
    type: 'code',
    lang: 'python',
    content: 'from collections import Counter\nprint(Counter("a b a".split()).most_common(1))',
  });
  for (const p of parts) assert.ok(!p.content.includes('```'), `fence leaked into ${p.type}`);
});

test('a fence without a language keeps an empty lang', () => {
  const [code] = parseMessageParts('```\nls -la\n```');
  assert.deepEqual(code, { type: 'code', lang: '', content: 'ls -la' });
});

test('a closed mermaid block is still a diagram', () => {
  const parts = parseMessageParts('```mermaid\ngraph TD\n  A-->B\n```');
  assert.deepEqual(parts, [{ type: 'mermaid', content: 'graph TD\n  A-->B' }]);
});

test('a fence still open while streaming renders as code so far', () => {
  const parts = parseMessageParts('Sure:\n```ts\nconst a = 1;');
  assert.deepEqual(parts[1], { type: 'code', lang: 'ts', content: 'const a = 1;' });
  // An unfinished mermaid block is shown as code, not handed to the diagram parser half-written.
  assert.equal(parseMessageParts('```mermaid\ngraph TD')[0].type, 'code');
});

test('checklists of two or more items are plans; a single item stays text', () => {
  const parts = parseMessageParts('Steps:\n- [ ] one\n- [x] two\nDone.');
  assert.deepEqual(parts.map((p) => p.type), ['text', 'plan', 'text']);
  assert.deepEqual(parseMessageParts('- [ ] only one').map((p) => p.type), ['text']);
});

test('checklist lines inside a code block are not turned into a plan', () => {
  const parts = parseMessageParts('```md\n- [ ] a\n- [ ] b\n```');
  assert.deepEqual(parts.map((p) => p.type), ['code']);
});

test('splitInlineCode separates `code` spans from prose', () => {
  assert.deepEqual(splitInlineCode('counts with `Counter` and `re`.'), [
    { code: false, text: 'counts with ' },
    { code: true, text: 'Counter' },
    { code: false, text: ' and ' },
    { code: true, text: 're' },
    { code: false, text: '.' },
  ]);
  assert.deepEqual(splitInlineCode('no code here'), [{ code: false, text: 'no code here' }]);
});
