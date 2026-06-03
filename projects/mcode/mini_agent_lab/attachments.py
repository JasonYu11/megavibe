from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PREVIEW_BYTES = 2 * 1024 * 1024
PREVIEW_CHARS = 1200


@dataclass(frozen=True)
class AttachmentMeta:
    id: str
    session_id: str
    name: str
    size: int
    mime_type: str
    path: str
    preview: str
    created_at: float

    def to_dict(self, *, include_data_url: bool = True) -> dict[str, Any]:
        is_image = _is_image(self.mime_type, self.name)
        is_text = _looks_text(self.mime_type, self.name)
        data_url = ""
        if include_data_url and is_image and self.size <= MAX_IMAGE_PREVIEW_BYTES:
            try:
                data = Path(self.path).read_bytes()
                encoded = base64.b64encode(data).decode("ascii")
                data_url = f"data:{self.mime_type or 'application/octet-stream'};base64,{encoded}"
            except OSError:
                data_url = ""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "name": self.name,
            "size": self.size,
            "mime_type": self.mime_type,
            "path": self.path,
            "preview": self.preview,
            "is_image": is_image,
            "is_text": is_text,
            "preview_available": is_text or bool(data_url),
            "data_url": data_url,
            "created_at": self.created_at,
        }

    def storage_dict(self) -> dict[str, Any]:
        return self.to_dict(include_data_url=False)


class AttachmentStore:
    def __init__(self, root: str | Path = ".attachments") -> None:
        self.root = Path(root)

    def add_base64(self, session_id: str, name: str, content_base64: str, mime_type: str = "") -> AttachmentMeta:
        if not session_id.strip():
            raise ValueError("session_id is required")
        safe_name = Path(name).name or "attachment"
        raw = base64.b64decode(content_base64.encode("ascii"), validate=True)
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"attachment is too large; max {MAX_ATTACHMENT_BYTES} bytes")
        attachment_id = f"att_{uuid.uuid4().hex[:12]}"
        directory = self.root / _safe_id(session_id) / attachment_id
        directory.mkdir(parents=True, exist_ok=False)
        file_path = directory / safe_name
        file_path.write_bytes(raw)
        preview = _preview(raw, mime_type, safe_name)
        meta = AttachmentMeta(
            id=attachment_id,
            session_id=session_id,
            name=safe_name,
            size=len(raw),
            mime_type=mime_type,
            path=str(file_path),
            preview=preview,
            created_at=time.time(),
        )
        (directory / "meta.json").write_text(json.dumps(meta.storage_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    def list(self, session_id: str) -> list[AttachmentMeta]:
        base = self.root / _safe_id(session_id)
        if not base.exists():
            return []
        metas = []
        for meta_path in sorted(base.glob("*/meta.json")):
            metas.append(_load_meta(meta_path))
        return metas

    def get(self, session_id: str, attachment_id: str) -> AttachmentMeta:
        meta_path = self.root / _safe_id(session_id) / _safe_id(attachment_id) / "meta.json"
        if not meta_path.exists():
            raise KeyError(f"unknown attachment: {attachment_id}")
        return _load_meta(meta_path)

    def read(self, session_id: str, attachment_id: str, max_chars: int = 12000) -> str:
        meta = self.get(session_id, attachment_id)
        data = Path(meta.path).read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return f"{meta.name} is not UTF-8 text. mime_type={meta.mime_type} size={meta.size} bytes"
        if len(text) > max_chars:
            return text[:max_chars] + f"\n\n[truncated: {len(text) - max_chars} more chars]"
        return text


def attachment_context(metas: list[AttachmentMeta]) -> str:
    if not metas:
        return ""
    lines = [
        "",
        "[Attached files]",
        "Use list_attachments/read_attachment for text attachment contents.",
        "Image attachments are available as metadata/previews only; visual analysis requires a future vision provider path.",
    ]
    for meta in metas:
        preview = meta.preview.replace("\n", " ")[:260]
        kind = "image" if _is_image(meta.mime_type, meta.name) else "text" if _looks_text(meta.mime_type, meta.name) else "file"
        lines.append(f"- id={meta.id} kind={kind} name={meta.name} size={meta.size} mime={meta.mime_type or 'unknown'} preview={preview}")
    return "\n".join(lines)


def _load_meta(path: Path) -> AttachmentMeta:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return AttachmentMeta(
        id=str(raw["id"]),
        session_id=str(raw["session_id"]),
        name=str(raw["name"]),
        size=int(raw["size"]),
        mime_type=str(raw.get("mime_type", "")),
        path=str(raw["path"]),
        preview=str(raw.get("preview", "")),
        created_at=float(raw.get("created_at", 0)),
    )


def _preview(raw: bytes, mime_type: str, name: str) -> str:
    if _looks_text(mime_type, name):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return "(text-like file, but not valid UTF-8)"
        return text[:PREVIEW_CHARS]
    return f"(binary attachment: {mime_type or 'unknown'}; {len(raw)} bytes)"


def _looks_text(mime_type: str, name: str) -> bool:
    lowered = name.lower()
    if mime_type.startswith("text/"):
        return True
    return lowered.endswith((".txt", ".md", ".py", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml", ".csv", ".sh", ".go", ".rs"))


def _is_image(mime_type: str, name: str) -> bool:
    lowered = name.lower()
    if mime_type.startswith("image/"):
        return True
    return lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"))


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in value)
    if not safe:
        raise ValueError("invalid id")
    return safe
