from __future__ import annotations

import json
from typing import Any, Callable, Union

from mini_agent_lab.tool.base import JsonObject, Tool


TaskRunner = Callable[[JsonObject], Union[str, dict[str, Any]]]


class TaskTool(Tool):
    def __init__(self, runner: TaskRunner) -> None:
        self.runner = runner

    @property
    def name(self) -> str:
        return "task"

    @property
    def description(self) -> str:
        return (
            "Delegate a focused subtask to an isolated subagent. Use this for research, review, "
            "or implementation subtasks that benefit from a fresh context. The subagent returns only "
            "its final answer to the parent loop."
        )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The exact task for the subagent to complete.",
                },
                "description": {
                    "type": "string",
                    "description": "Short human-readable label for UI/status.",
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tool allowlist. Omit or pass [] to allow all safe subagent tools.",
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Optional child loop limit. Defaults to half of the parent limit.",
                    "minimum": 1,
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Run the subagent in the background and return a subagent id immediately.",
                },
            },
            "required": ["prompt"],
        }

    def execute(self, arguments: JsonObject) -> str:
        prompt = str(arguments.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("prompt is required")
        tools = arguments.get("tools") or []
        if not isinstance(tools, list):
            raise ValueError("tools must be a list of tool names")

        payload = {
            "prompt": prompt,
            "description": str(arguments.get("description", "") or "").strip(),
            "tools": [str(name) for name in tools if str(name).strip()],
            "max_steps": int(arguments.get("max_steps", 0) or 0),
            "run_in_background": bool(arguments.get("run_in_background", False)),
            "_tool_call_id": str(arguments.get("_tool_call_id", "") or ""),
        }
        result = self.runner(payload)
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return json.dumps(
            {
                "subagent": "completed",
                "description": payload["description"],
                "answer": result,
            },
            ensure_ascii=False,
            indent=2,
        )
