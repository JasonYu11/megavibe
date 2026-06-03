from __future__ import annotations

from mini_agent_lab.tool.base import Tool


class ToolRegistry:
    """Per-agent collection of tools, keyed by model-visible name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._order: list[str] = []

    def add(self, tool: Tool) -> None:
        if tool.name not in self._tools:
            self._order.append(tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def names(self) -> list[str]:
        return list(self._order)

    def items(self) -> list[tuple[str, Tool]]:
        return [(name, self._tools[name]) for name in self._order]

    def schemas(self) -> list[dict]:
        out = []
        for name in sorted(self._tools):
            tool = self._tools[name]
            out.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.schema,
                }
            )
        return out
