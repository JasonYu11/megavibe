import { useMemo, useState } from "react";

const COLLAPSE_LINE_COUNT = 10;
const COLLAPSE_CHAR_COUNT = 1200;

export function FinalAnswerRenderer({ text, onOpenFile }: { text: string; onOpenFile?: (path: string) => void }) {
  const rendered = useMemo(() => normalizeFinalAnswer(text), [text]);
  const [expanded, setExpanded] = useState(false);
  const shouldCollapse = rendered.lines.length > COLLAPSE_LINE_COUNT || rendered.clean.length > COLLAPSE_CHAR_COUNT;
  const visibleLines = shouldCollapse && !expanded ? rendered.lines.slice(0, COLLAPSE_LINE_COUNT) : rendered.lines;

  return (
    <div className="finalAnswer" data-testid="final-answer">
      {visibleLines.map((line, index) => (
        <p className={classNameForLine(line)} key={`${line}-${index}`}>
          {renderInline(line, onOpenFile)}
        </p>
      ))}
      {shouldCollapse && (
        <button className="finalAnswer__toggle" onClick={() => setExpanded((value) => !value)}>
          {expanded ? "收起完整回答" : "展开完整回答"}
        </button>
      )}
    </div>
  );
}

export function normalizeFinalAnswer(text: string): { clean: string; lines: string[] } {
  const lines = text
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map(cleanLine)
    .filter((line) => line.trim().length > 0)
    .filter((line) => !isReportHeading(line));
  return { clean: lines.join("\n"), lines };
}

function cleanLine(line: string): string {
  return line
    .replace(/^[#]{1,6}\s*/, "")
    .replace(/^[\s>*-]*[📋✅❌⚠️🔧🧪📁📄🚀]+\s*/gu, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/^\d+[.)]\s+/, "")
    .trim();
}

function classNameForLine(line: string): string {
  if (/^(验证|测试|结果|文件|输出|改动|下一步)[:：]/.test(line)) return "finalAnswer__line finalAnswer__line--label";
  return "finalAnswer__line";
}

function isReportHeading(line: string): boolean {
  return /^(完整工作回顾|工作回顾|执行总结|完成总结|任务总结|完整执行报告|工作完成)[:：]?$/.test(line);
}

function renderInline(line: string, onOpenFile?: (path: string) => void) {
  const parts = line.split(/(`[^`]+`|(?:\.?\.?\/|\/|~\/)?[\w@.-]+(?:\/[\w@().+\-[\]\u4e00-\u9fff]+)+(?:\.[\w.-]+)?|[\w.-]+\.(?:tsx|ts|py|js|json|md|png|jpeg|jpg|txt|sh|yaml|yml))/g);
  return parts.map((part, index) => {
    if (!part) return null;
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={`${part}-${index}`}>{part.slice(1, -1)}</code>;
    }
    if (looksLikePath(part)) {
      if (onOpenFile) {
        return (
          <button className="finalAnswer__fileLink" key={`${part}-${index}`} onClick={() => onOpenFile(part)} type="button">
            {part}
          </button>
        );
      }
      return <code key={`${part}-${index}`}>{part}</code>;
    }
    return <span key={`${part}-${index}`}>{part}</span>;
  });
}

function looksLikePath(value: string): boolean {
  return /[/.]/.test(value) && !/\s/.test(value) && /(?:\/|\.tsx$|\.ts$|\.py$|\.js$|\.json$|\.md$|\.png$|\.jpeg$|\.jpg$|\.txt$|\.sh$|\.ya?ml$)/.test(value);
}
