import { ExternalLink, Globe } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";

export function BrowserPanel() {
  const [draft, setDraft] = useState("https://api-docs.deepseek.com/");
  const [url, setUrl] = useState("");

  function open(event: FormEvent) {
    event.preventDefault();
    const next = normalizeUrl(draft);
    setDraft(next);
    setUrl(next);
  }

  return (
    <div className="panelBody browserPanel">
      <form className="browserBar" onSubmit={open}>
        <Globe size={16} />
        <input value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="Browser URL" />
        <button className="primaryButton" disabled={!draft.trim()}>
          打开
        </button>
      </form>
      {url ? (
        <>
          <div className="browserHint">
            <span>{url}</span>
            <a href={url} target="_blank" rel="noreferrer">
              <ExternalLink size={14} />
              新窗口
            </a>
          </div>
          <iframe className="browserFrame" src={url} title="Browser preview" sandbox="allow-forms allow-scripts allow-same-origin" />
          <div className="emptyNote">如果页面拒绝嵌入，请使用“新窗口”打开。</div>
        </>
      ) : (
        <div className="dockEmpty">
          <Globe size={24} />
          <strong>浏览器</strong>
          <span>输入 URL 后在侧边栏预览网页。</span>
        </div>
      )}
    </div>
  );
}

function normalizeUrl(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}
