from __future__ import annotations

import json

from mini_agent_lab.attachments import AttachmentStore
from mini_agent_lab.tool.base import JsonObject, Tool


class ListAttachmentsTool(Tool):
    def __init__(self, store: AttachmentStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id

    @property
    def name(self) -> str:
        return "list_attachments"

    @property
    def description(self) -> str:
        return "List files attached to the current session with id, name, size, mime type, and preview."

    @property
    def schema(self) -> JsonObject:
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        rows = [meta.to_dict() for meta in self.store.list(self.session_id)]
        return json.dumps(rows, ensure_ascii=False, indent=2) if rows else "(no attachments)"


class ReadAttachmentTool(Tool):
    def __init__(self, store: AttachmentStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id

    @property
    def name(self) -> str:
        return "read_attachment"

    @property
    def description(self) -> str:
        return "Read a text attachment by attachment_id. Use list_attachments first if you do not know the id."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "attachment_id": {"type": "string", "description": "Attachment id, such as att_abcd1234"},
                "max_chars": {"type": "integer", "description": "Maximum characters to return", "minimum": 1},
            },
            "required": ["attachment_id"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        attachment_id = str(arguments.get("attachment_id") or "")
        if not attachment_id:
            raise ValueError("attachment_id is required")
        max_chars = int(arguments.get("max_chars", 12000) or 12000)
        if max_chars <= 0:
            max_chars = 12000
        return self.store.read(self.session_id, attachment_id, max_chars=max_chars)
