// Splits an assistant message into the parts the chat renders differently.
// Pure (no React, no DOM) so it can be unit-tested with `node --test`.

export type MessagePart =
  | { type: 'text'; content: string }
  | { type: 'code'; content: string; lang: string }
  | { type: 'mermaid'; content: string }
  | { type: 'plan'; content: string };

const FENCE_OPEN = /^\s*```\s*([\w#+.-]*)/;
const FENCE_CLOSE = /^\s*```\s*$/;
const PLAN_ITEM = /^\s*-\s*\[[ xX]\]\s+/;

/** Turns plain text into text and checklist ("plan") parts; a plan needs 2+ items in a row. */
function splitPlans(text: string, out: MessagePart[]): void {
  let currentText: string[] = [];
  let currentPlan: string[] = [];
  const flushText = () => {
    if (currentText.length > 0) out.push({ type: 'text', content: currentText.join('\n') });
    currentText = [];
  };
  const flushPlan = () => {
    if (currentPlan.length >= 2) {
      flushText();
      out.push({ type: 'plan', content: currentPlan.join('\n') });
    } else {
      currentText.push(...currentPlan);
    }
    currentPlan = [];
  };
  for (const line of text.split('\n')) {
    if (PLAN_ITEM.test(line)) {
      currentPlan.push(line);
    } else {
      flushPlan();
      currentText.push(line);
    }
  }
  flushPlan();
  flushText();
}

/**
 * Fenced blocks become `code` parts (```mermaid becomes a diagram once closed).
 * A fence still open at the end — a reply that is still streaming — is shown as
 * code so far, never as raw backticks.
 */
export function parseMessageParts(content: string): MessagePart[] {
  const parts: MessagePart[] = [];
  let text: string[] = [];
  let fence: { lang: string; lines: string[] } | null = null;

  const flushText = () => {
    if (text.length > 0) splitPlans(text.join('\n'), parts);
    text = [];
  };

  for (const line of content.split('\n')) {
    if (fence) {
      if (FENCE_CLOSE.test(line)) {
        const body = fence.lines.join('\n');
        parts.push(
          fence.lang.toLowerCase() === 'mermaid'
            ? { type: 'mermaid', content: body.trim() }
            : { type: 'code', content: body, lang: fence.lang },
        );
        fence = null;
      } else {
        fence.lines.push(line);
      }
      continue;
    }
    const open = FENCE_OPEN.exec(line);
    if (open) {
      flushText();
      fence = { lang: open[1] ?? '', lines: [] };
    } else {
      text.push(line);
    }
  }

  if (fence) parts.push({ type: 'code', content: fence.lines.join('\n'), lang: fence.lang });
  flushText();
  return parts;
}

export type InlineSegment = { code: boolean; text: string };

/** Splits `inline code` spans out of a line of prose. */
export function splitInlineCode(text: string): InlineSegment[] {
  const out: InlineSegment[] = [];
  const re = /`([^`\n]+)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push({ code: false, text: text.slice(last, m.index) });
    out.push({ code: true, text: m[1] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ code: false, text: text.slice(last) });
  return out;
}
