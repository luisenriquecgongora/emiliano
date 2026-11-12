// Parses unified diffs (`git diff`, `diff -u`, a model's ```diff block) for the chat's diff viewer.
// Pure (no React, no DOM) so it can be unit-tested with `node --test`.

export type DiffLineKind = 'context' | 'add' | 'del';

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
  oldNo: number | null; // line number in the old file; null for added lines
  newNo: number | null; // line number in the new file; null for deleted lines
}

export interface DiffHunk {
  header: string; // "@@ -10,6 +10,8 @@ def total():"
  lines: DiffLine[];
}

export interface DiffFile {
  oldPath: string;
  newPath: string;
  status: 'modified' | 'added' | 'deleted' | 'renamed';
  hunks: DiffHunk[];
  additions: number;
  deletions: number;
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

function cleanPath(raw: string): string {
  const path = raw.split('\t')[0].trim();
  if (path === '/dev/null') return path;
  return path.replace(/^[ab]\//, '');
}

/** True when the text holds at least one hunk header after file markers or a diff --git line. */
export function looksLikeUnifiedDiff(text: string): boolean {
  return /^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@/m.test(text) && /^(?:--- |diff --git |\+\+\+ )/m.test(text);
}

/**
 * Files with their hunks. Lines before the first file header (prose, `index ...` lines) are skipped; a hunk
 * without file headers (a model's bare snippet) becomes one file named "(diff)".
 */
export function parseUnifiedDiff(text: string): DiffFile[] {
  const files: DiffFile[] = [];
  let file: DiffFile | null = null;
  let hunk: DiffHunk | null = null;
  let oldNo = 0;
  let newNo = 0;

  const startFile = (oldPath = '(diff)', newPath = '(diff)') => {
    file = { oldPath, newPath, status: 'modified', hunks: [], additions: 0, deletions: 0 };
    files.push(file);
    hunk = null;
  };

  const lines = text.replace(/\r\n/g, '\n').split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith('diff --git ')) {
      const m = /^diff --git a\/(.+?) b\/(.+)$/.exec(line);
      startFile(m?.[1] ?? '(diff)', m?.[2] ?? '(diff)');
      continue;
    }
    // "--- a/x" followed by "+++ b/x" opens a file (or names the one diff --git opened)
    if (line.startsWith('--- ') && lines[i + 1]?.startsWith('+++ ')) {
      const oldPath = cleanPath(line.slice(4));
      const newPath = cleanPath(lines[i + 1].slice(4));
      const current = file as DiffFile | null;
      if (!current || current.hunks.length > 0) startFile(oldPath, newPath);
      else {
        current.oldPath = oldPath;
        current.newPath = newPath;
      }
      i++;
      continue;
    }
    if (file && !hunk) {
      const f = file as DiffFile;
      if (line.startsWith('new file mode')) f.status = 'added';
      else if (line.startsWith('deleted file mode')) f.status = 'deleted';
      else if (line.startsWith('rename from ')) f.oldPath = line.slice(12).trim();
      else if (line.startsWith('rename to ')) {
        f.newPath = line.slice(10).trim();
        f.status = 'renamed';
      }
    }

    const h = HUNK.exec(line);
    if (h) {
      if (!file) startFile();
      hunk = { header: line, lines: [] };
      (file as unknown as DiffFile).hunks.push(hunk);
      oldNo = Number(h[1]);
      newNo = Number(h[2]);
      continue;
    }
    if (!hunk || !file) continue;

    const current = hunk as DiffHunk;
    const f = file as DiffFile;
    if (line.startsWith('+')) {
      current.lines.push({ kind: 'add', text: line.slice(1), oldNo: null, newNo: newNo++ });
      f.additions++;
    } else if (line.startsWith('-')) {
      current.lines.push({ kind: 'del', text: line.slice(1), oldNo: oldNo++, newNo: null });
      f.deletions++;
    } else if (line.startsWith(' ') || line === '') {
      // An empty line inside a hunk is a context line whose leading space was trimmed (common in model output)
      if (line === '' && i === lines.length - 1) continue;
      current.lines.push({ kind: 'context', text: line.slice(1), oldNo: oldNo++, newNo: newNo++ });
    }
    // "\ No newline at end of file" and anything else is ignored
  }

  for (const f of files) {
    if (f.oldPath === '/dev/null') f.status = 'added';
    else if (f.newPath === '/dev/null') f.status = 'deleted';
  }
  return files.filter((f) => f.hunks.length > 0);
}

export interface SplitRow {
  left: DiffLine | null;
  right: DiffLine | null;
}

/**
 * Pairs a hunk's lines for the side-by-side view: context on both sides, and each run of deletions next to the
 * run of additions that follows it (the usual "changed lines" layout).
 */
export function toSplitRows(hunk: DiffHunk): SplitRow[] {
  const rows: SplitRow[] = [];
  let dels: DiffLine[] = [];
  let adds: DiffLine[] = [];
  const flush = () => {
    for (let k = 0; k < Math.max(dels.length, adds.length); k++) {
      rows.push({ left: dels[k] ?? null, right: adds[k] ?? null });
    }
    dels = [];
    adds = [];
  };
  for (const line of hunk.lines) {
    if (line.kind === 'del') {
      if (adds.length > 0) flush();
      dels.push(line);
    } else if (line.kind === 'add') {
      adds.push(line);
    } else {
      flush();
      rows.push({ left: line, right: line });
    }
  }
  flush();
  return rows;
}
