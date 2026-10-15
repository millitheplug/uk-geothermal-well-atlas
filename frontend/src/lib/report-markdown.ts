/**
 * A deliberately small markdown reader for the screening report, plus the
 * shared filename slug used by every export.
 *
 * It exists because the report needs to leave the platform as paper as well as
 * text, and the reader of a printed assessment must see exactly what the
 * reader of the screen sees.
 *
 * Two rules govern this file:
 *
 * 1. Nothing is dropped. A line that is not recognised is kept as paragraph
 *    text rather than discarded, because a figure absent from the printed copy
 *    is a figure its reader believes was never computed. Unknown syntax
 *    degrades to literal text, never to silence.
 *
 * 2. It parses structure only. It performs no calculation, formats no figure
 *    and supplies no wording of its own - the numbers reach the page exactly
 *    as the engine and the agents wrote them.
 *
 * The constructs are restricted to what the report actually emits (one `#`,
 * twenty-one `##`, occasional `###`, paragraphs, dashes, one horizontal rule).
 * Anything richer than that is kept as text rather than guessed at.
 */

export type InlineSegment = { text: string; bold: boolean };

export type ReportBlock =
  | { kind: "heading"; level: 1 | 2 | 3 | 4; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "hr" };

const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const ORDERED = /^\s*\d+[.)]\s+(.*)$/;
const HR = /^\s*([-*_])\1{2,}\s*$/;
const FENCE = /^\s*(?:```|~~~)/;

/**
 * Turn a well name into a filename fragment.
 *
 * Shared by the markdown and PDF exports so both artefacts from one assessment
 * sort together and stay attributable once they leave the platform. A document
 * that cannot be traced back to the well it assessed is one waiting to be
 * misquoted.
 */
export function slugifyWellName(wellName?: string | null): string {
  return (
    (wellName ?? "well")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "well"
  );
}

/**
 * Split a line into plain and bold runs.
 *
 * Only `**...**` is recognised. An unmatched marker is left literal, so a
 * half-written emphasis in agent output reads as the characters the writer
 * typed rather than being silently swallowed.
 */
export function parseInline(text: string): InlineSegment[] {
  const segments: InlineSegment[] = [];
  const pattern = /\*\*([^*\n]+)\*\*/g;
  let cursor = 0;
  let match = pattern.exec(text);

  while (match !== null) {
    if (match.index > cursor) {
      segments.push({ text: text.slice(cursor, match.index), bold: false });
    }
    segments.push({ text: match[1] ?? "", bold: true });
    cursor = match.index + match[0].length;
    match = pattern.exec(text);
  }

  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), bold: false });
  }

  return segments.length > 0 ? segments : [{ text, bold: false }];
}

/**
 * Read report markdown into blocks.
 *
 * Paragraph lines are joined with a single space because the generator wraps
 * prose across lines; blank lines are what separate one paragraph from the
 * next, not the line ending itself.
 */
export function parseReportMarkdown(markdown: string): ReportBlock[] {
  const blocks: ReportBlock[] = [];
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");

  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let inFence = false;

  const flushParagraph = (): void => {
    if (paragraph.length > 0) {
      blocks.push({ kind: "paragraph", text: paragraph.join(" ").trim() });
      paragraph = [];
    }
  };

  const flushList = (): void => {
    if (list) {
      blocks.push({ kind: "list", ordered: list.ordered, items: list.items });
      list = null;
    }
  };

  const flushAll = (): void => {
    flushParagraph();
    flushList();
  };

  const pushListLine = (ordered: boolean, text: string): void => {
    flushParagraph();

    // Read `list` through a local so the type survives the branch: appending to
    // the wrong list, or to a list that was just flushed, is how two different
    // kinds of list end up merged into one.
    const active = list && list.ordered === ordered ? list : null;
    if (active) {
      active.items.push(text.trim());
      return;
    }

    flushList();
    list = { ordered, items: [text.trim()] };
  };

  for (const raw of lines) {
    const line = raw.trim();

    if (FENCE.test(line)) {
      // Markers themselves are structure, not content, but anything between
      // them is content and stays: it is kept verbatim rather than re-read.
      inFence = !inFence;
      flushAll();
      continue;
    }

    if (inFence) {
      paragraph.push(line);
      continue;
    }

    if (line.length === 0) {
      flushAll();
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      const hashes = heading[1] ?? "#";
      flushAll();
      blocks.push({
        kind: "heading",
        // Deeper than four is folded into four: the report does not go further,
        // and inventing an outline level for it would be inventing structure.
        level: Math.min(hashes.length, 4) as 1 | 2 | 3 | 4,
        text: (heading[2] ?? "").trim(),
      });
      continue;
    }

    if (HR.test(line)) {
      flushAll();
      blocks.push({ kind: "hr" });
      continue;
    }

    const bullet = BULLET.exec(line);
    if (bullet) {
      pushListLine(false, bullet[1] ?? "");
      continue;
    }

    // ORDERED has a single capture group - `\d+` is not parenthesised - so the
    // item text is group 1, not group 2.
    const ordered = ORDERED.exec(line);
    if (ordered) {
      pushListLine(true, ordered[1] ?? "");
      continue;
    }

    // Unknown syntax: kept as prose, markers and all.
    paragraph.push(line);
  }

  flushAll();
  return blocks;
}

/** The text of one block, with no structural markers. */
export function reportBlockText(block: ReportBlock): string {
  switch (block.kind) {
    case "heading":
      return block.text;
    case "paragraph":
      return block.text;
    case "list":
      return block.items.join(" ");
    case "hr":
      return "";
  }
}

/**
 * Every word the report carries, for tests and for anything that needs the
 * document as one string.
 */
export function reportPlainText(markdown: string): string {
  return parseReportMarkdown(markdown)
    .map(reportBlockText)
    .filter((text) => text.length > 0)
    .join(" ");
}
