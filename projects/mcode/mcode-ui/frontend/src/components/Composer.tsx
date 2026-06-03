import { ArrowUp, Brain, Check, ChevronDown, Copy, File, FileImage, FileText, Hand, ListChecks, Mic, Paperclip, Plus, RotateCcw, Shield, ShieldAlert, Square, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { MODEL_PRESETS, presetById, presetIdFor } from "../modelPresets";
import type { AttachmentInfo, PermissionMode } from "../types";

const PERMISSION_OPTIONS: Array<{ value: PermissionMode; label: string; description: string; icon: JSX.Element }> = [
  { value: "default", label: "默认权限", description: "低风险自动允许，高风险请求确认", icon: <Hand size={16} /> },
  { value: "auto_review", label: "自动审查", description: "自动判断 allow / ask / deny", icon: <Shield size={16} /> },
  { value: "full_access", label: "完全访问权限", description: "普通操作自动允许，极高风险仍拒绝", icon: <ShieldAlert size={16} /> },
];

type VoiceState = "idle" | "listening" | "finalizing" | "error";

export function Composer({
  running,
  busy,
  plan,
  permissionMode,
  model,
  thinkingMode,
  attachments = [],
  onPlanChange,
  onPermissionModeChange,
  onModelChange,
  onAttachFiles,
  onRemoveAttachment,
  onRetryAttachment,
  onSend,
  onCancel,
}: {
  running: boolean;
  busy?: boolean;
  plan: boolean;
  permissionMode: PermissionMode;
  model: string;
  thinkingMode: boolean;
  attachments?: AttachmentInfo[];
  onPlanChange: (value: boolean) => void;
  onPermissionModeChange: (value: PermissionMode) => void;
  onModelChange?: (model: string, thinkingMode: boolean) => void;
  onAttachFiles?: (files: FileList) => void;
  onRemoveAttachment?: (id: string) => void;
  onRetryAttachment?: (id: string) => void;
  onSend: (text: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [permissionOpen, setPermissionOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [plusOpen, setPlusOpen] = useState(false);
  const [openAttachmentId, setOpenAttachmentId] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState("");
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [voiceMessage, setVoiceMessage] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const interimVoiceTextRef = useRef("");
  const selectedPermission = PERMISSION_OPTIONS.find((item) => item.value === permissionMode) || PERMISSION_OPTIONS[1];
  const selectedPreset = presetById(presetIdFor(model, thinkingMode));
  const openAttachment = attachments.find((attachment) => attachment.id === openAttachmentId);
  const hasAttachmentActivity = attachments.some((attachment) => attachment.upload_status === "uploading" || attachment.upload_status === "failed");
  const submit = () => {
    const value = text.trim();
    if (!value || running || busy) return;
    setText("");
    onSend(value);
  };

  useEffect(() => {
    const onTranscript = (event: Event) => {
      const detail = (event as CustomEvent<{ text?: string; final?: boolean; error?: string }>).detail || {};
      if (detail.error) {
        setVoiceState("error");
        setVoiceMessage(detail.error);
        return;
      }
      const incomingText = (detail.text || "").trim();
      if (incomingText && detail.final) {
        appendComposerText(incomingText);
        interimVoiceTextRef.current = "";
        setVoiceMessage("语音已插入");
      } else if (incomingText) {
        interimVoiceTextRef.current = incomingText;
        setVoiceMessage(`正在识别：${incomingText}`);
      } else if (detail.final && interimVoiceTextRef.current) {
        appendComposerText(interimVoiceTextRef.current);
        interimVoiceTextRef.current = "";
        setVoiceMessage("语音已插入");
      }
      if (detail.final) setVoiceState("idle");
    };
    window.addEventListener("mcode:speech-transcript", onTranscript);
    return () => window.removeEventListener("mcode:speech-transcript", onTranscript);
  }, []);

  const toggleVoice = () => {
    if (voiceState === "listening") {
      window.dispatchEvent(new CustomEvent("mcode:speech-request", { detail: { action: "stop" } }));
      setVoiceState("finalizing");
      setVoiceMessage("正在整理语音...");
      return;
    }
    interimVoiceTextRef.current = "";
    window.dispatchEvent(new CustomEvent("mcode:speech-request", { detail: { action: "start", localOnly: false } }));
    setVoiceState("listening");
    setVoiceMessage("正在聆听...");
  };

  const appendComposerText = (value: string) => {
    setText((current) => `${current}${current && !current.endsWith(" ") ? " " : ""}${value}`.trimStart());
  };

  const attachFiles = () => {
    setPlusOpen(false);
    fileInputRef.current?.click();
  };

  const togglePlan = () => {
    onPlanChange(!plan);
    setPlusOpen(false);
  };

  const copyAttachmentValue = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopyStatus(`${label}已复制`);
    } catch {
      setCopyStatus("复制失败");
    }
    window.setTimeout(() => setCopyStatus(""), 1600);
  };

  return (
    <div className="composer">
      {attachments.length > 0 && (
        <div className="attachmentChips">
          {attachments.map((attachment) => (
            <span className={`attachmentChip attachmentChip--${attachment.upload_status || "uploaded"}`} key={attachment.id} title={attachment.name}>
              <button className="attachmentChip__main" onClick={() => setOpenAttachmentId(openAttachmentId === attachment.id ? null : attachment.id)} type="button">
                {attachmentIcon(attachment)}
                <span>{attachment.name}</span>
                <small>{formatBytes(attachment.size)}</small>
              </button>
              {attachment.upload_status === "failed" && attachment.local_file && attachment.size <= 5 * 1024 * 1024 && (
                <button onClick={() => onRetryAttachment?.(attachment.id)} type="button" title="重试上传">
                  <RotateCcw size={12} />
                </button>
              )}
              <button onClick={() => onRemoveAttachment?.(attachment.id)} type="button" title="移除附件">
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      {openAttachment && (
        <div className="attachmentPopover">
          <div className="attachmentPopover__head">
            <strong>{openAttachment.name}</strong>
            <button type="button" onClick={() => setOpenAttachmentId(null)} title="关闭附件预览" aria-label="关闭附件预览">
              <X size={14} />
            </button>
          </div>
          <dl>
            <div><dt>ID</dt><dd>{openAttachment.id}</dd></div>
            <div><dt>类型</dt><dd>{openAttachment.mime_type || "unknown"}</dd></div>
            <div><dt>大小</dt><dd>{formatBytes(openAttachment.size)}</dd></div>
            <div><dt>状态</dt><dd>{attachmentStatusText(openAttachment)}</dd></div>
          </dl>
          {openAttachment.error && <div className="attachmentPopover__error">{openAttachment.error}</div>}
          {openAttachment.is_image && openAttachment.data_url && <img className="attachmentPreviewImage" src={openAttachment.data_url} alt={openAttachment.name} />}
          {openAttachment.is_text && openAttachment.preview && <pre className="attachmentPreviewText">{openAttachment.preview}</pre>}
          {!openAttachment.preview_available && !openAttachment.error && (
            <p className="attachmentPopover__note">该附件可上传和随消息传递；当前不支持直接预览此类型。</p>
          )}
          <div className="attachmentPopover__actions">
            <button type="button" onClick={() => void copyAttachmentValue(openAttachment.id, "附件 ID")}>
              <Copy size={13} />
              复制 ID
            </button>
            <button type="button" onClick={() => void copyAttachmentValue(openAttachment.name, "文件名")}>
              <Copy size={13} />
              复制文件名
            </button>
            {copyStatus && <span className={copyStatus === "复制失败" ? "is-error" : ""}>{copyStatus}</span>}
          </div>
        </div>
      )}
      {hasAttachmentActivity && (
        <div className="attachmentStatus">
          {attachments.filter((attachment) => attachment.upload_status === "uploading").length > 0 && <span>附件上传中...</span>}
          {attachments.filter((attachment) => attachment.upload_status === "failed").length > 0 && <span className="is-error">有附件上传失败</span>}
        </div>
      )}
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder="要求 agent 做点什么"
      />
      {voiceMessage && <div className={`voiceStatus voiceStatus--${voiceState}`}>{voiceMessage}</div>}
      <div className="composer__bar">
        <div className="composer__tools">
          <div className="composerPlusMenu">
            <button
              className="iconButton"
              onClick={() => setPlusOpen((value) => !value)}
              type="button"
              title="打开添加菜单"
              aria-label="打开添加菜单"
              aria-expanded={plusOpen}
            >
              <Plus size={17} />
            </button>
            {plusOpen && (
              <div className="composerPlusMenu__popover">
                <button className="composerPlusMenu__item" onClick={attachFiles} type="button">
                  <Paperclip size={17} />
                  <span>添加照片和文件</span>
                </button>
                <button className="composerPlusMenu__item" onClick={togglePlan} type="button" aria-pressed={plan}>
                  <ListChecks size={17} />
                  <span>计划模式</span>
                  <span className={`composerSwitch ${plan ? "is-on" : ""}`} aria-hidden="true" />
                </button>
              </div>
            )}
          </div>
        <input
          ref={fileInputRef}
          className="hiddenFileInput"
          type="file"
          multiple
          onChange={(event) => {
            if (event.currentTarget.files?.length) onAttachFiles?.(event.currentTarget.files);
            event.currentTarget.value = "";
          }}
        />
        {plan && (
          <button className="planIndicator" onClick={() => onPlanChange(false)} type="button" title="计划模式已开启" aria-label="计划模式已开启">
            <ListChecks size={16} />
          </button>
        )}
        <div className="modelMenu">
          <button className="modelMenu__trigger" onClick={() => setModelOpen((value) => !value)} type="button" disabled={running || busy}>
            <span className="modelMenu__mark">DS</span>
            <span>{shortModelLabel(selectedPreset.label)}</span>
            {selectedPreset.thinkingMode && <Brain size={14} />}
            <ChevronDown size={14} />
          </button>
          {modelOpen && (
            <div className="modelMenu__popover">
              {MODEL_PRESETS.map((item) => (
                <button
                  className="modelMenu__option"
                  key={item.id}
                  onClick={() => {
                    onModelChange?.(item.model, item.thinkingMode);
                    setModelOpen(false);
                  }}
                  type="button"
                >
                  <span className="modelMenu__mark">DS</span>
                  <span>{item.label}</span>
                  {item.thinkingMode && <Brain size={16} />}
                  {item.id === selectedPreset.id && <Check size={16} />}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="permissionMenu">
          <button className="permissionMenu__trigger" onClick={() => setPermissionOpen((value) => !value)} type="button">
            {selectedPermission.icon}
            <span>{selectedPermission.label}</span>
            <ChevronDown size={14} />
          </button>
          {permissionOpen && (
            <div className="permissionMenu__popover">
              {PERMISSION_OPTIONS.map((item) => (
                <button
                  className="permissionMenu__option"
                  key={item.value}
                  onClick={() => {
                    onPermissionModeChange(item.value);
                    setPermissionOpen(false);
                  }}
                  type="button"
                >
                  {item.icon}
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.description}</small>
                  </span>
                  {item.value === permissionMode && <Check size={16} />}
                </button>
              ))}
            </div>
          )}
        </div>
        <button
          className={`iconButton voiceButton ${voiceState === "listening" || voiceState === "finalizing" ? "is-recording" : ""}`}
          onClick={toggleVoice}
          type="button"
          title={voiceState === "listening" ? "停止语音输入" : "语音输入"}
          aria-label={voiceState === "listening" ? "停止语音输入" : "语音输入"}
          disabled={voiceState === "finalizing"}
        >
          <Mic size={16} />
        </button>
        </div>
        <div className="composer__spacer" />
        <button
          className="sendButton"
          onClick={running ? onCancel : submit}
          disabled={busy || (!running && !text.trim())}
          title={running ? "请求停止" : "发送"}
        >
          {running ? <Square size={16} /> : <ArrowUp size={18} />}
        </button>
      </div>
    </div>
  );
}

function shortModelLabel(label: string): string {
  return label.split(":")[0].replace("DeepSeek-", "");
}

function attachmentIcon(attachment: AttachmentInfo): JSX.Element {
  if (attachment.is_image || attachment.mime_type.startsWith("image/")) return <FileImage size={13} />;
  if (attachment.is_text || attachment.mime_type.startsWith("text/")) return <FileText size={13} />;
  return <File size={13} />;
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 102.4) / 10} KB`;
  return `${Math.round(size / 1024 / 102.4) / 10} MB`;
}

function attachmentStatusText(attachment: AttachmentInfo): string {
  if (attachment.upload_status === "uploading") return "上传中";
  if (attachment.upload_status === "failed") return "上传失败";
  return "已上传";
}
