import { ChevronDown, ChevronRight, Copy, ExternalLink, FileText, Folder, FolderSearch, MoreHorizontal } from "lucide-react";
import { useState } from "react";
import type { CSSProperties, MouseEvent } from "react";
import type { FileNode } from "../types";

type FileOpenApp = "" | "system" | "finder";
type FileMenuState = { path: string; x: number; y: number } | null;

export function FileTreePanel({
  tree,
  selectedPath,
  fileContent,
  onRead,
  onOpenExternal,
}: {
  tree?: FileNode | null;
  selectedPath?: string;
  fileContent?: string;
  onRead: (path: string) => void;
  onOpenExternal?: (path: string, app?: string) => void;
}) {
  const [previewMenuOpen, setPreviewMenuOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<FileMenuState>(null);
  const [copyStatus, setCopyStatus] = useState("");

  const copyPath = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      setCopyStatus("已复制路径");
    } catch {
      setCopyStatus("复制失败");
    }
    window.setTimeout(() => setCopyStatus(""), 1600);
  };

  const runOpen = (path: string, app: FileOpenApp) => {
    onOpenExternal?.(path, app);
    setPreviewMenuOpen(false);
    setContextMenu(null);
  };

  return (
    <div className={`panelBody fileTreePanel ${selectedPath ? "has-preview" : ""}`} data-testid="file-tree" onClick={() => setContextMenu(null)}>
      <div className="fileTreePanel__tree">
        {tree ? (
          <TreeNode
            node={tree}
            onRead={onRead}
            onContextMenu={(path, event) => {
              event.preventDefault();
              setContextMenu({ path, x: event.clientX, y: event.clientY });
            }}
            root
          />
        ) : (
          <div className="emptyNote">暂无文件树</div>
        )}
      </div>
      {selectedPath && (
        <div className="filePreview">
          <div className="filePreview__title">
            <span>{selectedPath}</span>
            <div className="filePreview__actions">
              {copyStatus && <span className={`copyStatus ${copyStatus === "复制失败" ? "is-error" : ""}`}>{copyStatus}</span>}
              <button className="secondaryButton" onClick={() => setPreviewMenuOpen((value) => !value)} type="button" aria-expanded={previewMenuOpen}>
                <MoreHorizontal size={14} />
                打开方式
              </button>
              {previewMenuOpen && (
                <FileActionMenu
                  path={selectedPath}
                  onPreview={onRead}
                  onOpen={runOpen}
                  onCopy={(path) => void copyPath(path)}
                  includePreview={false}
                />
              )}
            </div>
          </div>
          <pre>{fileContent}</pre>
        </div>
      )}
      {contextMenu && (
        <FileActionMenu
          path={contextMenu.path}
          onPreview={(path) => {
            onRead(path);
            setContextMenu(null);
          }}
          onOpen={runOpen}
          onCopy={(path) => {
            void copyPath(path);
            setContextMenu(null);
          }}
          style={{ left: contextMenu.x, top: contextMenu.y }}
        />
      )}
    </div>
  );
}

function TreeNode({
  node,
  onRead,
  onContextMenu,
  root = false,
}: {
  node: FileNode;
  onRead: (path: string) => void;
  onContextMenu: (path: string, event: MouseEvent) => void;
  root?: boolean;
}) {
  const [open, setOpen] = useState(root);
  if (node.is_dir) {
    return (
      <div className="treeNode">
        <button className="treeNode__row" onClick={() => setOpen(!open)}>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Folder size={14} />
          <span>{root ? "root" : node.name}</span>
        </button>
        {open && (
          <div className="treeNode__children">
            {node.children.map((child) => (
              <TreeNode key={child.path} node={child} onRead={onRead} onContextMenu={onContextMenu} />
            ))}
          </div>
        )}
      </div>
    );
  }
  return (
    <button className="treeNode__row treeNode__row--file" onClick={() => onRead(node.path)} onContextMenu={(event) => onContextMenu(node.path, event)}>
      <span className="treeNode__pad" />
      <FileText size={14} />
      <span>{node.name}</span>
    </button>
  );
}

function FileActionMenu({
  path,
  onPreview,
  onOpen,
  onCopy,
  includePreview = true,
  style,
}: {
  path: string;
  onPreview: (path: string) => void;
  onOpen: (path: string, app: FileOpenApp) => void;
  onCopy: (path: string) => void;
  includePreview?: boolean;
  style?: CSSProperties;
}) {
  return (
    <div className={`fileActionMenu ${style ? "is-context" : ""}`} style={style} role="menu">
      {includePreview && (
        <button type="button" onClick={() => onPreview(path)}>
          <FileText size={14} />
          预览
        </button>
      )}
      <button type="button" onClick={() => onOpen(path, "system")}>
        <ExternalLink size={14} />
        默认打开
      </button>
      <button type="button" onClick={() => onOpen(path, "finder")}>
        <FolderSearch size={14} />
        Finder 中显示
      </button>
      <button type="button" onClick={() => onOpen(path, "")}>
        <ExternalLink size={14} />
        使用配置打开
      </button>
      <button type="button" onClick={() => onCopy(path)}>
        <Copy size={14} />
        复制路径
      </button>
    </div>
  );
}
