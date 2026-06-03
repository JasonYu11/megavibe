import { FileCode, PackageOpen } from "lucide-react";
import { useMemo, useState } from "react";
import type { UiItem } from "../types";

export function ArtifactsPopover({ items, onOpenFile }: { items: UiItem[]; onOpenFile?: (path: string) => void }) {
  const [open, setOpen] = useState(false);
  const artifacts = useMemo(() => collectFileArtifacts(items), [items]);
  return (
    <div className="artifactsPopover">
      <button className="secondaryButton" onClick={() => setOpen((value) => !value)} type="button">
        <PackageOpen size={14} />
        Artifacts
        {artifacts.length > 0 && <span>{artifacts.length}</span>}
      </button>
      {open && (
        <div className="artifactsPopover__panel">
          <strong>Files</strong>
          {artifacts.length === 0 && <p>暂无产物</p>}
          {artifacts.map((path) => (
            <button
              key={path}
              onClick={() => {
                onOpenFile?.(path);
                setOpen(false);
              }}
            >
              <FileCode size={14} />
              <span>{path}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function collectFileArtifacts(items: UiItem[]): string[] {
  const seen = new Set<string>();
  for (const item of items) {
    if (item.kind === "change_review") {
      for (const change of item.changes) {
        if (change.path) seen.add(change.path);
      }
    }
    if (item.kind === "thinking") {
      for (const path of collectFileArtifacts(item.items)) seen.add(path);
    }
  }
  return [...seen].slice(0, 12);
}
