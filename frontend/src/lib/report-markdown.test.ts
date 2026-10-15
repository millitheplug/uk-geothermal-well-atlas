import { describe, expect, it } from "vitest";

import {
  parseInline,
  parseReportMarkdown,
  reportPlainText,
  slugifyWellName,
} from "./report-markdown";

/**
 * The report leaves the platform as paper as well as screen, so the printed
 * page has to carry every word the screen does. A figure dropped by the
 * reader is a figure its reader believes was never computed - which is the one
 * failure this parser must not be capable of.
 */
describe("parseReportMarkdown", () => {
  /** Shaped like a real assessment: one title, numbered sections, a disclaimer foot. */
  const report = [
    "# Geothermal Reuse Screening Report",
    "",
    "## Executive summary",
    "",
    "SPRINGS ROAD scores 40/100 on feasibility with 37% evidence confidence,",
    "giving a recommendation of LOW PRIORITY.",
    "",
    "## Temperature assessment",
    "",
    "Recorded temperature 116.0 degC (status: MEASURED, confidence: unknown).",
    "",
    "## Validation",
    "",
    "- Confirm the depth record",
    "- Check the temperature provenance",
    "",
    "## Next action",
    "",
    "1. Run a heat demand survey",
    "2. Re-run the screening",
    "",
    "---",
    "",
    "### Disclaimers",
    "",
    "- This report is not a statement of commercial viability.",
    "- Thermal output is estimated.",
  ].join("\n");

  it("reads the title and each section at its own level", () => {
    const blocks = parseReportMarkdown(report);
    const headings = blocks.filter((b) => b.kind === "heading");

    expect(headings[0]).toMatchObject({ level: 1, text: "Geothermal Reuse Screening Report" });
    expect(headings[1]).toMatchObject({ level: 2, text: "Executive summary" });
    expect(headings.at(-1)).toMatchObject({ level: 3, text: "Disclaimers" });
    expect(headings.filter((h) => h.kind === "heading" && h.level === 2)).toHaveLength(4);
  });

  it("joins a paragraph that the generator wrapped across lines", () => {
    const paragraph = parseReportMarkdown(report).find(
      (b) => b.kind === "paragraph" && b.text.startsWith("SPRINGS ROAD"),
    );
    expect(paragraph).toBeDefined();
    // One sentence, not two fragments: the line break was formatting, not meaning.
    expect(paragraph).toMatchObject({
      text: expect.stringContaining("confidence, giving a recommendation"),
    });
  });

  it("separates paragraphs at blank lines rather than at line endings", () => {
    const blocks = parseReportMarkdown("First line one.\nFirst line two.\n\nSecond paragraph.");
    expect(blocks).toEqual([
      { kind: "paragraph", text: "First line one. First line two." },
      { kind: "paragraph", text: "Second paragraph." },
    ]);
  });

  it("groups consecutive bullets and numbered lines into their own lists", () => {
    const blocks = parseReportMarkdown(report);
    const lists = blocks.filter((b) => b.kind === "list");

    expect(lists[0]).toMatchObject({
      ordered: false,
      items: ["Confirm the depth record", "Check the temperature provenance"],
    });
    expect(lists[1]).toMatchObject({
      ordered: true,
      items: ["Run a heat demand survey", "Re-run the screening"],
    });
  });

  it("splits two adjacent lists of different kinds instead of merging them", () => {
    const blocks = parseReportMarkdown("- a bullet\n- another\n1. first step");
    expect(blocks).toEqual([
      { kind: "list", ordered: false, items: ["a bullet", "another"] },
      { kind: "list", ordered: true, items: ["first step"] },
    ]);
  });

  it("reads a horizontal rule as a rule, not as a paragraph of dashes", () => {
    const blocks = parseReportMarkdown("Above\n\n---\n\nBelow");
    expect(blocks).toEqual([
      { kind: "paragraph", text: "Above" },
      { kind: "hr" },
      { kind: "paragraph", text: "Below" },
    ]);
  });

  it("keeps syntax it does not understand as literal prose", () => {
    // Tables, quotes and stray markers are not part of the report's shape, but
    // agents are free to emit them. They must reach the page as characters, not
    // vanish because the reader had no rule for them.
    const text = reportPlainText(
      ["> sourced from the NSTA register", "| well | depth |", "A stray ** marker", ""].join("\n"),
    );
    expect(text).toContain("> sourced from the NSTA register");
    expect(text).toContain("| well | depth |");
    expect(text).toContain("A stray ** marker");
  });

  it("drops no word from the document", () => {
    const lines = report.split("\n").filter((line) => line.trim().length > 0);
    const flat = reportPlainText(report);

    for (const line of lines) {
      // Strip the structural marker, then require the content to survive.
      const content = line.replace(/^(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)/, "").trim();
      if (content.length === 0) continue;
      // A rule has no words in it: it renders as a line, and carries no text.
      if (/^([-*_])\1{2,}$/.test(content)) continue;
      expect(flat).toContain(content);
    }
  });

  it("folds a heading deeper than four levels rather than inventing an outline", () => {
    const blocks = parseReportMarkdown("##### Deep");
    expect(blocks[0]).toMatchObject({ kind: "heading", level: 4 });
  });

  it("keeps fenced content as text and ignores the fence markers", () => {
    const blocks = parseReportMarkdown("```\nkept verbatim\n```");
    expect(blocks).toEqual([{ kind: "paragraph", text: "kept verbatim" }]);
  });

  it("normalises windows line endings", () => {
    expect(reportPlainText("# Title\r\n\r\nBody text")).toBe("Title Body text");
  });
});

describe("parseInline", () => {
  it("splits bold runs from the text around them", () => {
    expect(parseInline("a **b** c")).toEqual([
      { text: "a ", bold: false },
      { text: "b", bold: true },
      { text: " c", bold: false },
    ]);
  });

  it("leaves an unmatched marker as the characters that were typed", () => {
    expect(parseInline("half a **bold run")).toEqual([
      { text: "half a **bold run", bold: false },
    ]);
  });

  it("returns the whole line as plain text when there is no emphasis", () => {
    expect(parseInline("116.0 degC (status: MEASURED)")).toEqual([
      { text: "116.0 degC (status: MEASURED)", bold: false },
    ]);
  });
});

/**
 * Both exports name the file after the well, so the paper copy and the text
 * copy of one assessment sort together once they leave the platform.
 */
describe("slugifyWellName", () => {
  it("lowercases and hyphenates a well name", () => {
    expect(slugifyWellName("SPRINGS ROAD")).toBe("springs-road");
  });

  it("collapses the publisher id's slash and space", () => {
    expect(slugifyWellName("L46/16- 31")).toBe("l46-16-31");
  });

  it("never returns an empty filename when the name is missing or unusable", () => {
    expect(slugifyWellName(null)).toBe("well");
    expect(slugifyWellName(undefined)).toBe("well");
    expect(slugifyWellName("")).toBe("well");
    expect(slugifyWellName("   ")).toBe("well");
    expect(slugifyWellName("!!!")).toBe("well");
  });

  it("strips a name that would otherwise start or end with a hyphen", () => {
    expect(slugifyWellName("-- Springs Road --")).toBe("springs-road");
  });
});
