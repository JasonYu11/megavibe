"""Tests for session attachments and attachment tools."""

from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.attachments import AttachmentStore, attachment_context
from mini_agent_lab.tool.builtin import default_registry


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _b64_bytes(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_attachment_store_add_list_read_and_context() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = AttachmentStore(Path(tmp) / ".attachments")
        meta = store.add_base64("s1", "../notes.md", _b64("# Notes\nhello attachment"), "text/markdown")
        listed = store.list("s1")
        context = attachment_context([meta])

        _assert(meta.name == "notes.md", "attachment name is sanitized")
        _assert(listed[0].id == meta.id, "attachment is listed")
        _assert(store.read("s1", meta.id) == "# Notes\nhello attachment", "attachment text is read")
        _assert("[Attached files]" in context, "attachment context has marker")
        _assert(meta.id in context and "notes.md" in context, "attachment context exposes id and name")


def test_image_attachment_metadata_and_preview_boundary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = AttachmentStore(Path(tmp) / ".attachments")
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
        meta = store.add_base64("s1", "figure.png", _b64_bytes(png_bytes), "image/png")
        payload = meta.to_dict()
        context = attachment_context([meta])

        _assert(payload["is_image"] is True, "image attachment is marked as image")
        _assert(payload["is_text"] is False, "image attachment is not marked as text")
        _assert(payload["preview_available"] is True, "small image attachment has preview available")
        _assert(str(payload["data_url"]).startswith("data:image/png;base64,"), "image attachment exposes data url preview")
        _assert("visual analysis requires" in context, "attachment context states image vision boundary")
        _assert("not UTF-8 text" in store.read("s1", meta.id), "image attachment is not treated as UTF-8 text")


def test_attachment_tools_are_registered_when_store_is_available() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = AttachmentStore(Path(tmp) / ".attachments")
        meta = store.add_base64("s1", "data.txt", _b64("alpha beta"), "text/plain")
        registry = default_registry(Path(tmp), attachment_store=store, attachment_session_id="s1")

        names = set(registry.names())
        _assert("list_attachments" in names, "list_attachments tool is registered")
        _assert("read_attachment" in names, "read_attachment tool is registered")
        _assert(meta.id in registry.get("list_attachments").execute({}), "list tool returns attachment id")
        _assert(
            registry.get("read_attachment").execute({"attachment_id": meta.id}) == "alpha beta",
            "read tool returns attachment text",
        )


if __name__ == "__main__":
    test_attachment_store_add_list_read_and_context()
    test_image_attachment_metadata_and_preview_boundary()
    test_attachment_tools_are_registered_when_store_is_available()
    print("All attachment tests passed.")
