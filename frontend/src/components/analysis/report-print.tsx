/**
 * Paper output for a screening report.
 *
 * The report is already on screen, so this does not re-read or re-shape it: it
 * renders the same markdown as normal document markup and lets the browser's
 * own print engine turn that into a PDF. Nothing is calculated here, and no
 * figure is re-worded - whatever the engine and the agents wrote reaches the
 * page verbatim, disclaimers included.
 *
 * Two decisions are worth stating, because both are visible in the result:
 *
 * - The report is portalled to the end of `<body>`. It otherwise sits inside a
 *   tab panel within a scrolling frame, and content nested in an `overflow`
 *   container is clipped rather than paginated when printed.
 *
 * - A class is set on `<body>` for as long as the report is mounted, and the
 *   print stylesheet keys on it. Without that marker a print from any other
 *   page would hide every element and produce blank paper.
 *
 * The markup is React-rendered rather than assembled as an HTML string, so the
 * report's text is escaped by construction - agent output is untrusted input.
 */

"use client";

import * as React from "react";
import { createPortal } from "react-dom";

import {
  parseInline,
  parseReportMarkdown,
} from "@/lib/report-markdown";

/**
 * Marks the document as holding a printable report. The print stylesheet only
 * suppresses the application chrome when this is present.
 */
export const PRINT_REPORT_CLASS = "has-print-report";

/** Opens the browser's print dialog, from which the file is saved as a PDF. */
export function printReport(): void {
  if (typeof window === "undefined") return;
  window.print();
}

function InlineText({ text }: { text: string }) {
  return (
    <>
      {parseInline(text).map((segment, index) =>
        segment.bold ? (
          <strong key={index}>{segment.text}</strong>
        ) : (
          <React.Fragment key={index}>{segment.text}</React.Fragment>
        ),
      )}
    </>
  );
}

/**
 * The report as a document, hidden on screen and printed in place of the app.
 *
 * `wellName` is carried onto the page for the same reason the markdown
 * filename carries it: an assessment that has left the platform must still be
 * attributable to the well it assessed.
 */
export function PrintableReport({
  markdown,
  wellName,
}: {
  markdown: string;
  wellName?: string | null;
}) {
  const blocks = React.useMemo(() => parseReportMarkdown(markdown), [markdown]);
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
    document.body.classList.add(PRINT_REPORT_CLASS);
    return () => {
      document.body.classList.remove(PRINT_REPORT_CLASS);
    };
  }, []);

  if (!mounted) return null;

  return createPortal(
    <article className="print-report" lang="en">
      <header className="print-report__header">
        <p className="print-report__platform">UK Geothermal Well Atlas</p>
        {wellName ? (
          <p className="print-report__well">
            {wellName}
          </p>
        ) : null}
        {/*
          The same wording the screen carries beside the export buttons. The
          report's own disclaimers sit at its foot, so on a long document they
          can be several pages away from the figure they qualify.
        */}
        <p className="print-report__notice">
          Screening output from desk-study data. It is not a statement of
          commercial viability, and no figure in it substitutes for engineering
          sign-off.
        </p>
      </header>

      {blocks.map((block, index) => {
        switch (block.kind) {
          case "heading": {
            const content = <InlineText text={block.text} />;
            if (block.level === 1) return <h1 key={index}>{content}</h1>;
            if (block.level === 2) return <h2 key={index}>{content}</h2>;
            if (block.level === 3) return <h3 key={index}>{content}</h3>;
            return <h4 key={index}>{content}</h4>;
          }
          case "paragraph":
            return <p key={index}><InlineText text={block.text} /></p>;
          case "list":
            return block.ordered ? (
              <ol key={index}>
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}><InlineText text={item} /></li>
                ))}
              </ol>
            ) : (
              <ul key={index}>
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}><InlineText text={item} /></li>
                ))}
              </ul>
            );
          case "hr":
            return <hr key={index} />;
        }
      })}
    </article>,
    document.body,
  );
}
