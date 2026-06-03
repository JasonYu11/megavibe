from __future__ import annotations

import json
from typing import Callable, Optional

from mini_agent_lab.skill import (
    Skill,
    SkillStore,
    render_inline_skill,
    render_skill,
)
from mini_agent_lab.tool.base import JsonObject, Tool


SubagentRunner = Callable[[Skill, str, str], str]


class ListSkillsTool(Tool):
    def __init__(self, store: SkillStore) -> None:
        self.store = store

    @property
    def name(self) -> str:
        return "list_skills"

    @property
    def description(self) -> str:
        return "List available skills with description, scope, path, run mode, and allowed tools."

    @property
    def schema(self) -> JsonObject:
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        rows = [
            {
                "name": skill.name,
                "description": skill.description,
                "scope": skill.scope,
                "path": skill.path,
                "run_as": skill.run_as,
                "allowed_tools": skill.allowed_tools,
                "model": skill.model,
            }
            for skill in self.store.list()
        ]
        return json.dumps({"skills": rows}, ensure_ascii=False, indent=2)


class ReadSkillTool(Tool):
    def __init__(self, store: SkillStore) -> None:
        self.store = store

    @property
    def name(self) -> str:
        return "read_skill"

    @property
    def description(self) -> str:
        return "Read one skill's full playbook body and metadata."

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name"},
            },
            "required": ["name"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        name = str(arguments.get("name", "")).strip()
        if not name:
            raise ValueError("name is required")
        skill = self.store.read(_clean_skill_name(name))
        if skill is None:
            raise ValueError(f"unknown skill {name!r}; available: {_available_names(self.store)}")
        return render_skill(skill, str(arguments.get("arguments", "") or ""))


class RunSkillTool(Tool):
    def __init__(self, store: SkillStore, runner: Optional[SubagentRunner] = None) -> None:
        self.store = store
        self.runner = runner

    @property
    def name(self) -> str:
        return "run_skill"

    @property
    def description(self) -> str:
        return (
            "Invoke a reusable skill from the Skills index. Pass the bare skill name, not tags. "
            "Inline skills return their playbook as a tool result to follow in the parent loop. "
            "Subagent skills run in an isolated child loop and return only the final answer."
        )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Bare skill identifier, such as test or review"},
                "arguments": {
                    "type": "string",
                    "description": "Concrete task or free-form arguments for the skill.",
                },
            },
            "required": ["name"],
        }

    def execute(self, arguments: JsonObject) -> str:
        raw_name = str(arguments.get("name", "")).strip()
        name = _clean_skill_name(raw_name)
        if not name:
            raise ValueError(f"run_skill requires a skill name; got {raw_name!r}")
        skill = self.store.read(name)
        if skill is None:
            raise ValueError(f"unknown skill {name!r}; available: {_available_names(self.store)}")
        task = str(arguments.get("arguments", "") or "").strip()
        if skill.run_as == "subagent":
            if self.runner is None:
                raise ValueError(f"skill {name!r} is run_as=subagent but no subagent runner is configured")
            if not task:
                raise ValueError(f"skill {name!r} is a subagent skill and requires arguments")
            return self.runner(skill, task, str(arguments.get("_tool_call_id", "") or ""))
        return render_inline_skill(skill, task)


class InstallSkillTool(Tool):
    def __init__(self, store: SkillStore) -> None:
        self.store = store

    @property
    def name(self) -> str:
        return "install_skill"

    @property
    def description(self) -> str:
        return (
            "Create a reusable skill playbook in project or global scope. Refuses to overwrite existing skills. "
            "Use this when the user wants a durable workflow the agent can invoke later."
        )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill identifier, 1-64 chars"},
                "description": {"type": "string", "description": "One-line skill description for the index"},
                "body": {"type": "string", "description": "Markdown playbook instructions"},
                "scope": {"type": "string", "enum": ["project", "global"], "description": "Default project"},
                "run_as": {"type": "string", "enum": ["inline", "subagent"], "description": "Default inline"},
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tool allowlist for subagent skills.",
                },
                "model": {"type": "string", "description": "Optional model hint for subagent skills."},
            },
            "required": ["name", "description", "body"],
        }

    def execute(self, arguments: JsonObject) -> str:
        path = self.store.create(
            name=str(arguments.get("name", "")),
            description=str(arguments.get("description", "")),
            body=str(arguments.get("body", "")),
            scope=str(arguments.get("scope", "project") or "project"),
            run_as=str(arguments.get("run_as", arguments.get("runAs", "inline")) or "inline"),
            allowed_tools=arguments.get("allowed_tools") or arguments.get("allowedTools") or [],
            model=str(arguments.get("model", "") or ""),
        )
        return json.dumps(
            {
                "installed": True,
                "path": str(path),
                "note": "Skill is immediately available through run_skill in this process and will appear in the skill index for new sessions.",
            },
            ensure_ascii=False,
            indent=2,
        )


def _clean_skill_name(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    text = text.split()[0]
    text = text.strip("`'\"[]()")
    if text in {"subagent", "inline"}:
        return ""
    return text


def _available_names(store: SkillStore) -> str:
    names = [skill.name for skill in store.list()]
    return ", ".join(names) if names else "(none)"
