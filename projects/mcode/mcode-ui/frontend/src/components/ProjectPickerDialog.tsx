import { FolderOpen, Plus, X } from "lucide-react";
import { useState } from "react";
import type { PickFolderResult } from "../types";

export function ProjectPickerDialog({
  open,
  busy,
  picked,
  error,
  onPickFolder,
  onCreate,
  onClose,
}: {
  open: boolean;
  busy: boolean;
  picked?: PickFolderResult | null;
  error?: string;
  onPickFolder: () => void;
  onCreate: (name: string, rootPath: string) => void;
  onClose: () => void;
}) {
  const [manualPath, setManualPath] = useState("");
  const [manualName, setManualName] = useState("");
  if (!open) return null;
  const rootPath = picked?.root_path || manualPath.trim();
  const name = manualName.trim() || picked?.name || rootPath.split("/").filter(Boolean).pop() || "project";
  return (
    <div className="dialogBackdrop" role="presentation">
      <section className="dialog" role="dialog" aria-modal="true" aria-label="添加项目">
        <header className="dialog__header">
          <strong>添加项目</strong>
          <button className="iconButton" onClick={onClose} title="关闭">
            <X size={16} />
          </button>
        </header>
        <button className="pickerButton" onClick={onPickFolder} disabled={busy}>
          <FolderOpen size={17} />
          选择文件夹
        </button>
        {picked?.root_path && <div className="pickedPath">{picked.root_path}</div>}
        {picked?.cancelled && picked.reason && <div className="dialogError">{picked.reason}</div>}
        <label className="field">
          <span>手动路径</span>
          <input value={manualPath} onChange={(event) => setManualPath(event.target.value)} placeholder="/Users/macbot/project" />
        </label>
        <label className="field">
          <span>项目名称</span>
          <input value={manualName} onChange={(event) => setManualName(event.target.value)} placeholder={picked?.name || "自动使用文件夹名"} />
        </label>
        {error && <div className="dialogError">{error}</div>}
        <footer className="dialog__footer">
          <button className="secondaryButton" onClick={onClose}>
            取消
          </button>
          <button className="primaryButton" onClick={() => onCreate(name, rootPath)} disabled={busy || !rootPath}>
            <Plus size={15} />
            添加
          </button>
        </footer>
      </section>
    </div>
  );
}
