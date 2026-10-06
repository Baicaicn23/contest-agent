// 轻量 Markdown 渲染器（M10 解析器的 TS 移植）：块级扫描 → React 元素。
// 不引库、不走 dangerouslySetInnerHTML——免疫注入。
import type { ReactNode } from "react";

export function renderInline(text: string, keyPrefix = ""): ReactNode[] {
  const parts: ReactNode[] = [];
  const codeSplit = text.split(/(`[^`]+`)/g);
  codeSplit.forEach((seg, si) => {
    if (seg.startsWith("`") && seg.endsWith("`") && seg.length > 2) {
      parts.push(
        <code key={`${keyPrefix}c${si}`} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]">
          {seg.slice(1, -1)}
        </code>,
      );
      return;
    }
    const boldSplit = seg.split(/(\*\*[^*]+\*\*)/g);
    boldSplit.forEach((b, bi) => {
      if (b.startsWith("**") && b.endsWith("**") && b.length > 4) {
        parts.push(<strong key={`${keyPrefix}${si}-${bi}`}>{b.slice(2, -2)}</strong>);
      } else if (b) {
        parts.push(<span key={`${keyPrefix}${si}-${bi}`}>{b}</span>);
      }
    });
  });
  return parts;
}

type Block =
  | { type: "code"; lang: string; text: string }
  | { type: "table"; rows: string[] }
  | { type: "heading"; level: number; text: string }
  | { type: "hr" }
  | { type: "quote"; lines: string[] }
  | { type: "text"; lines: string[] };

function parseBlocks(text: string): Block[] {
  const lines = String(text).split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    if (/^\s*```/.test(line)) {
      const lang = line.replace(/^\s*```/, "").trim();
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1; // 闭合 ```；未闭合（流式中）自然到文末
      blocks.push({ type: "code", lang, text: buf.join("\n") });
      continue;
    }

    if (/^\s*\|.+\|\s*$/.test(line)) {
      const rows: string[] = [];
      while (i < lines.length && /^\s*\|.+\|\s*$/.test(lines[i])) {
        rows.push(lines[i]);
        i += 1;
      }
      blocks.push({ type: "table", rows });
      continue;
    }

    const heading = line.match(/^\s*(#{1,3})\s+(.*)$/);
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2] });
      i += 1;
      continue;
    }

    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      blocks.push({ type: "hr" });
      i += 1;
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ""));
        i += 1;
      }
      blocks.push({ type: "quote", lines: buf });
      continue;
    }

    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^\s*(```|\||#{1,3}\s|>|-{3,}|\*{3,})/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i += 1;
    }
    if (buf.length) blocks.push({ type: "text", lines: buf });
    else i += 1;
  }
  return blocks;
}

function renderTextLines(lines: string[], keyPrefix: string): ReactNode[] {
  return lines.map((line, i) => {
    const bullet = line.match(/^\s*[-•]\s+(.*)$/);
    const numbered = line.match(/^\s*(\d+)\.\s+(.*)$/);
    if (bullet) {
      return (
        <div key={keyPrefix + i} className="pl-4">
          • {renderInline(bullet[1], `${keyPrefix}${i}-`)}
        </div>
      );
    }
    if (numbered) {
      return (
        <div key={keyPrefix + i} className="pl-4">
          {numbered[1]}. {renderInline(numbered[2], `${keyPrefix}${i}-`)}
        </div>
      );
    }
    return (
      <div key={keyPrefix + i}>{renderInline(line, `${keyPrefix}${i}-`) || "\u00A0"}</div>
    );
  });
}

function renderTable(rows: string[], keyPrefix: string): ReactNode {
  const cells = (row: string) =>
    row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  const header = cells(rows[0]);
  const hasSep = rows.length >= 2 && /^[\s:|-]+$/.test(rows[1]);
  const bodyRows = rows.slice(hasSep ? 2 : 1);
  return (
    <div key={keyPrefix} className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-[0.92em] leading-relaxed">
        <thead>
          <tr>
            {header.map((c, j) => (
              <th key={j} className="border border-border bg-muted px-2.5 py-1.5 text-left font-semibold">
                {renderInline(c, `${keyPrefix}h${j}-`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {bodyRows.map((row, ri) => {
            const cs = cells(row);
            return (
              <tr key={ri} className="even:bg-muted/40">
                {header.map((_, j) => (
                  <td key={j} className="border border-border px-2.5 py-1.5 align-top">
                    {renderInline(cs[j] ?? "", `${keyPrefix}${ri}-${j}-`)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Markdown({ content }: { content: string }) {
  const blocks = parseBlocks(content);
  return (
    <>
      {blocks.map((b, i) => {
        switch (b.type) {
          case "code":
            return (
              <pre key={i} className="relative my-2.5 overflow-x-auto rounded-lg bg-muted p-3 font-mono text-[0.85em] leading-relaxed" style={{ whiteSpace: "pre" }}>
                {b.lang && <span className="absolute right-2 top-1 text-[10px] text-muted-foreground">{b.lang}</span>}
                <code>{b.text}</code>
              </pre>
            );
          case "table":
            return renderTable(b.rows, `t${i}-`);
          case "heading": {
            const cls = { 1: "text-[1.15em]", 2: "text-[1.08em]", 3: "text-[1.02em]" }[b.level] ?? "text-[1em]";
            return (
              <div key={i} className={`mt-3.5 mb-1.5 font-semibold leading-snug ${cls}`}>
                {renderInline(b.text, `h${i}-`)}
              </div>
            );
          }
          case "hr":
            return <hr key={i} className="my-3.5 border-border" />;
          case "quote":
            return (
              <blockquote key={i} className="my-2.5 border-l-[3px] border-border py-0.5 pl-3 text-muted-foreground">
                {b.lines.map((l, j) => (
                  <div key={j}>{renderInline(l, `q${i}-${j}-`) || "\u00A0"}</div>
                ))}
              </blockquote>
            );
          default:
            return <div key={i}>{renderTextLines(b.lines, `x${i}-`)}</div>;
        }
      })}
    </>
  );
}
