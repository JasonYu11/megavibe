from __future__ import annotations

import json

from mini_agent_lab.subagent_manager import SubagentManager
from mini_agent_lab.tool.base import JsonObject, Tool


class SubagentStatusTool(Tool):
    def __init__(self, manager: SubagentManager) -> None:
        self.manager = manager

    @property
    def name(self) -> str:
        return "subagent_status"

    @property
    def description(self) -> str:
        return "List subagents, or inspect one subagent by id."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "subagent_id": {"type": "string", "description": "Optional subagent id"},
            },
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        return json.dumps(
            self.manager.status(str(arguments.get("subagent_id", "") or "")),
            ensure_ascii=False,
            indent=2,
        )


class SubagentOutputTool(Tool):
    def __init__(self, manager: SubagentManager) -> None:
        self.manager = manager

    @property
    def name(self) -> str:
        return "subagent_output"

    @property
    def description(self) -> str:
        return "Read recent persisted events and final answer/error for a subagent."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "subagent_id": {"type": "string", "description": "Subagent id"},
                "limit": {"type": "integer", "description": "Number of recent events", "minimum": 1},
            },
            "required": ["subagent_id"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        subagent_id = str(arguments.get("subagent_id", "") or "")
        if not subagent_id:
            raise ValueError("subagent_id is required")
        return json.dumps(
            self.manager.output(subagent_id, limit=int(arguments.get("limit", 20) or 20)),
            ensure_ascii=False,
            indent=2,
        )


class WaitSubagentTool(Tool):
    def __init__(self, manager: SubagentManager) -> None:
        self.manager = manager

    @property
    def name(self) -> str:
        return "wait_subagent"

    @property
    def description(self) -> str:
        return "Wait for a background subagent to finish, or until timeout_seconds elapses."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "subagent_id": {"type": "string", "description": "Subagent id"},
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Optional maximum wait time. Omit or pass 0 to wait until completion.",
                    "minimum": 0,
                },
            },
            "required": ["subagent_id"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        subagent_id = str(arguments.get("subagent_id", "") or "")
        if not subagent_id:
            raise ValueError("subagent_id is required")
        return json.dumps(
            self.manager.wait(subagent_id, timeout_seconds=int(arguments.get("timeout_seconds", 0) or 0)),
            ensure_ascii=False,
            indent=2,
        )


class CancelSubagentTool(Tool):
    def __init__(self, manager: SubagentManager) -> None:
        self.manager = manager

    @property
    def name(self) -> str:
        return "cancel_subagent"

    @property
    def description(self) -> str:
        return "Request cooperative cancellation for a running background subagent."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "subagent_id": {"type": "string", "description": "Subagent id"},
            },
            "required": ["subagent_id"],
        }

    def execute(self, arguments: JsonObject) -> str:
        subagent_id = str(arguments.get("subagent_id", "") or "")
        if not subagent_id:
            raise ValueError("subagent_id is required")
        return json.dumps(self.manager.cancel(subagent_id), ensure_ascii=False, indent=2)
