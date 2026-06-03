from __future__ import annotations

from mini_agent_lab.memory import AutoMemoryStore
from mini_agent_lab.tool.base import JsonObject, Tool


class RememberTool(Tool):
    def __init__(self, store: AutoMemoryStore) -> None:
        self.store = store

    @property
    def name(self) -> str:
        return "remember"

    @property
    def description(self) -> str:
        return (
            "Save a durable fact to project memory so it survives future sessions. "
            "Use only for long-term user preferences, work guidance with why/how to apply it, "
            "ongoing project goals or constraints not already in files, or external references. "
            "Do not save secrets, temporary conversation details, command output, code structure, "
            "or facts already recorded in the repository. Reusing the same name overwrites the old memory."
        )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short kebab-case name, such as prefers-chinese. Reuse to update an existing memory.",
                },
                "description": {
                    "type": "string",
                    "description": "One-line summary for the memory index.",
                    "maxLength": 240,
                },
                "type": {
                    "type": "string",
                    "enum": ["user", "feedback", "project", "reference"],
                    "description": "Category of the durable fact.",
                },
                "body": {
                    "type": "string",
                    "description": "The fact itself in concise Markdown. Include why/how for feedback or project guidance.",
                    "maxLength": 2000,
                },
            },
            "required": ["description", "body"],
        }

    def execute(self, arguments: JsonObject) -> str:
        memory = self.store.save(
            name=str(arguments.get("name") or arguments.get("description") or ""),
            description=str(arguments.get("description") or ""),
            type=str(arguments.get("type") or "project"),
            body=str(arguments.get("body") or ""),
        )
        return (
            f"saved memory {memory.name} to {memory.path}. "
            "It is indexed now and will load automatically in future sessions."
        )


class ListMemoryTool(Tool):
    def __init__(self, store: AutoMemoryStore) -> None:
        self.store = store

    @property
    def name(self) -> str:
        return "list_memory"

    @property
    def description(self) -> str:
        return "List saved durable memories from the project memory index."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {},
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        memories = self.store.list()
        if not memories:
            return "(no saved memories)"
        return "\n".join(
            f"- {memory.name} [{memory.type}] {memory.description} ({memory.path})"
            for memory in memories
        )
