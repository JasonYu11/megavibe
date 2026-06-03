import { MessageCirclePlus, Send } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api/client";
import type { Message, PermissionMode } from "../types";

export function SideChatPanel({ projectId }: { projectId?: string }) {
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !draft.trim()) return;
    setBusy(true);
    setError("");
    const text = draft;
    setDraft("");
    try {
      let target = sessionId;
      if (!target) {
        const created = await api.createSession(projectId, "side-ui");
        target = created.id;
        setSessionId(target);
      }
      setMessages((current) => [...current, { role: "user", content: text }]);
      await api.send(projectId, target, text, false, "auto_review" as PermissionMode, []);
      window.setTimeout(() => void refresh(projectId, target), 1200);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function refresh(id = projectId, target = sessionId) {
    if (!id || !target) return;
    const data = await api.session(id, target);
    setMessages(data.messages);
  }

  return (
    <div className="panelBody sideChatPanel">
      <div className="sideChatPanel__head">
        <MessageCirclePlus size={17} />
        <strong>侧边聊天</strong>
        <button className="secondaryButton" disabled={!sessionId} onClick={() => void refresh()} type="button">
          刷新
        </button>
      </div>
      <div className="sideChatMessages">
        {messages.length === 0 && (
          <div className="dockEmpty">
            <MessageCirclePlus size={24} />
            <strong>发起侧边对话</strong>
            <span>旁路会话不会写入当前主聊天 transcript。</span>
          </div>
        )}
        {messages
          .filter((message) => message.role !== "system")
          .map((message, index) => (
            <div className={`sideBubble sideBubble--${message.role}`} key={`${message.role}-${index}`}>
              <span>{message.role}</span>
              <p>{message.content}</p>
            </div>
          ))}
      </div>
      <form className="sideChatComposer" onSubmit={send}>
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={projectId ? "问一个旁路问题" : "先选择项目"}
          disabled={!projectId || busy}
          aria-label="Side chat message"
        />
        <button className="iconButton" disabled={!projectId || !draft.trim() || busy} title="发送">
          <Send size={15} />
        </button>
      </form>
      {error && <button className="terminalError" onClick={() => setError("")}>{error}</button>}
    </div>
  );
}
