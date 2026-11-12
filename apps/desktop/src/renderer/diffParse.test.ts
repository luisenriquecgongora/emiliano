import assert from 'node:assert/strict';
import { test } from 'node:test';
import { looksLikeUnifiedDiff, parseUnifiedDiff, toSplitRows } from './diffParse.ts';

const GIT_DIFF = `diff --git a/calc.py b/calc.py
index 1111111..2222222 100644
--- a/calc.py
+++ b/calc.py
@@ -1,4 +1,5 @@
 def total(n):
-    return sum(range(n))
+    # include n itself
+    return sum(range(1, n + 1))

 print(total(3))
diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+hello
`;

test('git diff: files, status, counts and line numbers', () => {
  const files = parseUnifiedDiff(GIT_DIFF);
  assert.equal(files.length, 2);
  const [calc, added] = files;
  assert.equal(calc.newPath, 'calc.py');
  assert.equal(calc.status, 'modified');
  assert.equal(calc.additions, 2);
  assert.equal(calc.deletions, 1);
  const lines = calc.hunks[0].lines;
  assert.deepEqual(lines[0], { kind: 'context', text: 'def total(n):', oldNo: 1, newNo: 1 });
  assert.deepEqual(lines[1], { kind: 'del', text: '    return sum(range(n))', oldNo: 2, newNo: null });
  assert.deepEqual(lines[3], { kind: 'add', text: '    return sum(range(1, n + 1))', oldNo: null, newNo: 3 });
  // The blank context line keeps both counters in step
  assert.deepEqual(lines[4], { kind: 'context', text: '', oldNo: 3, newNo: 4 });
  assert.deepEqual(lines[5], { kind: 'context', text: 'print(total(3))', oldNo: 4, newNo: 5 });
  assert.equal(added.status, 'added');
  assert.equal(added.newPath, 'new.txt');
});

test('a bare hunk from a model becomes one unnamed file', () => {
  const files = parseUnifiedDiff('@@ -3,2 +3,2 @@\n-a = 1\n+a = 2\n b = 3');
  assert.equal(files.length, 1);
  assert.equal(files[0].newPath, '(diff)');
  assert.equal(files[0].hunks[0].lines.length, 3);
});

test('CRLF line endings and the no-newline marker', () => {
  const files = parseUnifiedDiff('--- a/x\r\n+++ b/x\r\n@@ -1 +1 @@\r\n-old\r\n+new\r\n\\ No newline at end of file\r\n');
  assert.deepEqual(files[0].hunks[0].lines.map((l) => l.kind), ['del', 'add']);
});

test('split rows pair deletions with the additions that follow', () => {
  const rows = toSplitRows(parseUnifiedDiff(GIT_DIFF)[0].hunks[0]);
  assert.equal(rows[0].left?.text, 'def total(n):');
  assert.equal(rows[1].left?.kind, 'del');
  assert.equal(rows[1].right?.text, '    # include n itself');
  assert.equal(rows[2].left, null); // the second added line has no deleted partner
  assert.equal(rows[2].right?.kind, 'add');
});

test('diff detection', () => {
  assert.ok(looksLikeUnifiedDiff(GIT_DIFF));
  assert.ok(!looksLikeUnifiedDiff('def f():\n    return 1'));
  assert.ok(!looksLikeUnifiedDiff('- item one\n- item two'));
});
