"""Tests for the skill system."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.skill import Skill, SkillStore, apply_skill_index, parse_frontmatter, render_skill
from mini_agent_lab.tool import default_registry
from mini_agent_lab.tool.registry import ToolRegistry
from mini_agent_lab.tool.skill_tools import InstallSkillTool, ListSkillsTool, ReadSkillTool, RunSkillTool


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_parse_frontmatter_and_render_index() -> None:
    meta, body = parse_frontmatter(
        "---\n"
        "name: demo\n"
        "description: demo skill\n"
        "runAs: subagent\n"
        "allowed-tools: [read_file, grep]\n"
        "---\n"
        "\n"
        "Body\n"
    )
    skill = Skill(name="demo", description=meta["description"], body=body, scope="project", path="x", run_as="subagent")
    prompt = apply_skill_index("BASE", [skill])

    _assert(meta["name"] == "demo", "frontmatter parses name")
    _assert(meta["allowed-tools"] == ["read_file", "grep"], "frontmatter parses list")
    _assert(body == "Body", "frontmatter strips body")
    _assert("# Skills" in prompt, "skill index is appended")
    _assert("demo [subagent]" in prompt, "subagent skill is tagged in index")


def test_store_discovers_priority_layouts_and_references() -> None:
    with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as home_tmp:
        project = Path(project_tmp)
        home = Path(home_tmp)
        _write(home / ".mini-agent" / "skills" / "dupe.md", "---\ndescription: global\n---\nglobal body")
        _write(project / ".reasonix" / "skills" / "dupe.md", "---\ndescription: project\n---\nproject body")
        _write(project / ".agents" / "skills" / "flat.md", "---\ndescription: flat\n---\nflat body")
        _write(project / ".mcode" / "skills" / "dir" / "SKILL.md", "---\ndescription: dir\n---\nmain body")
        _write(project / ".mcode" / "skills" / "dir" / "references" / "b.md", "second ref")
        _write(project / ".mcode" / "skills" / "dir" / "references" / "a.md", "first ref")
        _write(project / ".mcode" / "skills" / "bad name.md", "---\ndescription: bad\n---\nbody")

        store = SkillStore(project_root=project, home_dir=home, include_builtins=False)
        skills = {skill.name: skill for skill in store.list()}
        dupe = store.read("dupe")
        directory = store.read("dir")

        _assert(dupe is not None and dupe.scope == "project", "project skill wins over global")
        _assert("flat" in skills, "flat skill is discovered")
        _assert(directory is not None and "first ref" in directory.body, "directory references are appended")
        _assert(directory is not None and directory.body.index("first ref") < directory.body.index("second ref"), "references are sorted")
        _assert("bad name" not in skills, "invalid skill names are skipped")


def test_install_skill_refuses_overwrite_and_is_readable() -> None:
    with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as home_tmp:
        store = SkillStore(project_root=project_tmp, home_dir=home_tmp, include_builtins=False)
        path = store.create(
            name="writer",
            description="write things",
            body="Use write_file carefully.",
            scope="project",
            run_as="inline",
        )
        skill = store.read("writer")

        _assert(path.name == "writer.md", "skill installs as flat markdown file")
        _assert(skill is not None and skill.description == "write things", "installed skill is readable")
        try:
            store.create(name="writer", description="dup", body="body", scope="project")
            raise AssertionError("duplicate install should fail")
        except FileExistsError:
            print("  OK: duplicate skill install is rejected")


def test_skill_tools_inline_subagent_list_read_install() -> None:
    with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as home_tmp:
        project = Path(project_tmp)
        _write(project / ".mcode" / "skills" / "note.md", "---\ndescription: note skill\n---\nTake a note.")
        _write(
            project / ".mcode" / "skills" / "dig.md",
            "---\ndescription: dig skill\nrunAs: subagent\nallowed-tools: [read_file]\n---\nDig.",
        )
        store = SkillStore(project_root=project, home_dir=home_tmp, include_builtins=False)
        calls: list[tuple[str, str, str]] = []

        def runner(skill: Skill, task: str, parent_tool_call_id: str) -> str:
            calls.append((skill.name, task, parent_tool_call_id))
            return f"subagent:{skill.name}:{task}"

        listed = json.loads(ListSkillsTool(store).execute({}))
        read = ReadSkillTool(store).execute({"name": "note"})
        inline = RunSkillTool(store, runner).execute({"name": "note", "arguments": "hello"})
        subagent = RunSkillTool(store, runner).execute({"name": "dig", "arguments": "find x"})
        installed = json.loads(
            InstallSkillTool(store).execute(
                {
                    "name": "newskill",
                    "description": "new skill",
                    "body": "Do new things.",
                    "scope": "project",
                    "run_as": "subagent",
                    "allowed_tools": ["grep"],
                }
            )
        )

        _assert(listed["skills"][0]["name"] == "dig", "list_skills returns sorted skills")
        _assert("# Skill: note" in read, "read_skill renders skill body")
        _assert(inline.startswith("<skill-pin"), "inline run_skill wraps skill pin")
        _assert("Arguments:\nhello" in inline, "inline run_skill includes arguments")
        _assert(subagent == "subagent:dig:find x", "subagent run_skill calls runner")
        _assert(calls == [("dig", "find x", "")], "runner receives skill, task, and optional parent call id")
        _assert(installed["installed"] is True, "install_skill returns installed flag")
        _assert(store.read("newskill") is not None and store.read("newskill").run_as == "subagent", "installed subagent skill is readable")


def test_default_registry_includes_skill_tools_when_store_is_supplied() -> None:
    with tempfile.TemporaryDirectory() as project_tmp:
        store = SkillStore(project_root=project_tmp, include_builtins=False)
        registry = default_registry(skill_store=store)
        names = set(registry.names())

        _assert({"list_skills", "read_skill", "run_skill", "install_skill"}.issubset(names), "default registry includes skill tools")


def test_subagent_registry_filters_meta_tools() -> None:
    from mini_agent_lab.subagent import filter_registry

    class DummyTool:
        def __init__(self, name: str) -> None:
            self._name = name

        @property
        def name(self) -> str:
            return self._name

        @property
        def description(self) -> str:
            return self._name

        @property
        def schema(self):
            return {"type": "object"}

        @property
        def read_only(self) -> bool:
            return True

        def execute(self, arguments):
            return self._name

    parent = ToolRegistry()
    for name in ["read_file", "grep", "task", "run_skill", "install_skill", "todo_write", "git_commit", "bash"]:
        parent.add(DummyTool(name))

    child = filter_registry(parent, allowed=["read_file", "grep", "run_skill", "task", "git_commit"])
    _assert(child.names() == ["read_file", "grep"], "subagent registry keeps allowed tools and strips meta tools")


if __name__ == "__main__":
    test_parse_frontmatter_and_render_index()
    test_store_discovers_priority_layouts_and_references()
    test_install_skill_refuses_overwrite_and_is_readable()
    test_skill_tools_inline_subagent_list_read_install()
    test_default_registry_includes_skill_tools_when_store_is_supplied()
    test_subagent_registry_filters_meta_tools()
    print("All skill tests passed.")
