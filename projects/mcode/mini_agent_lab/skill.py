from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


CONVENTION_DIRS = (".mcode", ".mini-agent", ".reasonix", ".agents", ".agent", ".claude")
SKILLS_DIRNAME = "skills"
SKILL_FILE = "SKILL.md"
VALID_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
INDEX_MAX_CHARS = 6000


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    scope: str
    path: str
    run_as: str = "inline"
    allowed_tools: list[str] = field(default_factory=list)
    model: str = ""
    # 指导性字段
    context: str = ""
    heuristics: list[str] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    output_format: str = ""


@dataclass(frozen=True)
class SkillRoot:
    path: Path
    scope: str
    status: str
    priority: int


class SkillStore:
    """Discover and load reusable agent playbooks.

    Project skills win over custom paths, custom paths win over global skills,
    and all user-authored skills win over built-ins. Both flat `name.md` and
    directory-layout `name/SKILL.md` skills are supported.
    """

    def __init__(
        self,
        *,
        project_root: str | Path = ".",
        home_dir: str | Path | None = None,
        custom_paths: Optional[list[str | Path]] = None,
        include_builtins: bool = True,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve(strict=False) if project_root else None
        self.home_dir = Path(home_dir or Path.home()).expanduser().resolve(strict=False)
        base = self.project_root or Path.cwd().resolve(strict=False)
        self.custom_paths = [_resolve_custom_path(path, base, self.home_dir) for path in custom_paths or []]
        self.include_builtins = include_builtins

    def roots(self) -> list[SkillRoot]:
        entries: list[tuple[Path, str]] = []
        if self.project_root is not None:
            for convention in CONVENTION_DIRS:
                entries.append((self.project_root / convention / SKILLS_DIRNAME, "project"))
        for path in self.custom_paths:
            entries.append((path, "custom"))
        for convention in CONVENTION_DIRS:
            entries.append((self.home_dir / convention / SKILLS_DIRNAME, "global"))
        return [
            SkillRoot(path=path, scope=scope, status=_path_status(path), priority=index)
            for index, (path, scope) in enumerate(_dedupe_roots(entries))
        ]

    def list(self) -> list[Skill]:
        by_name: dict[str, Skill] = {}
        for root in self.roots():
            if root.status != "ok":
                continue
            for entry in sorted(root.path.iterdir(), key=lambda p: p.name.lower()):
                skill = self._read_entry(root.path, root.scope, entry)
                if skill and skill.name not in by_name:
                    by_name[skill.name] = skill
        if self.include_builtins:
            for skill in builtin_skills():
                if skill.name not in by_name:
                    by_name[skill.name] = skill
        return sorted(by_name.values(), key=lambda item: item.name)

    def read(self, name: str) -> Optional[Skill]:
        if not is_valid_skill_name(name):
            return None
        for root in self.roots():
            if root.status != "ok":
                continue
            directory_candidate = root.path / name / SKILL_FILE
            if directory_candidate.is_file():
                skill = self._parse(directory_candidate, name, root.scope)
                if skill:
                    return skill
            flat_candidate = root.path / f"{name}.md"
            if flat_candidate.is_file():
                skill = self._parse(flat_candidate, name, root.scope)
                if skill:
                    return skill
        if self.include_builtins:
            for skill in builtin_skills():
                if skill.name == name:
                    return skill
        return None

    def create(
        self,
        *,
        name: str,
        description: str,
        body: str,
        scope: str = "project",
        run_as: str = "inline",
        allowed_tools: Optional[list[str]] = None,
        model: str = "",
    ) -> Path:
        name = name.strip()
        description = _one_line(description)
        body = body.strip()
        if not is_valid_skill_name(name):
            raise ValueError(f"invalid skill name {name!r}; use letters, digits, _, -, or .")
        if not description:
            raise ValueError("description is required")
        if not body:
            raise ValueError("body is required")
        if run_as not in {"inline", "subagent"}:
            raise ValueError("run_as must be inline or subagent")

        root = self._write_root(scope)
        flat = root / f"{name}.md"
        directory = root / name / SKILL_FILE
        if flat.exists() or directory.exists():
            raise FileExistsError(f"skill {name!r} already exists")
        root.mkdir(parents=True, exist_ok=True)
        flat.write_text(
            render_skill_file(
                name=name,
                description=description,
                body=body,
                run_as=run_as,
                allowed_tools=allowed_tools or [],
                model=model,
            ),
            encoding="utf-8",
        )
        return flat

    def _write_root(self, scope: str) -> Path:
        normalized = scope.strip() or "project"
        if normalized == "project":
            if self.project_root is None:
                raise ValueError("project scope requires project_root")
            return self.project_root / ".mcode" / SKILLS_DIRNAME
        if normalized == "global":
            return self.home_dir / ".mcode" / SKILLS_DIRNAME
        raise ValueError("scope must be project or global")

    def _read_entry(self, root: Path, scope: str, entry: Path) -> Optional[Skill]:
        try:
            resolved = entry.resolve(strict=True)
        except OSError:
            return None
        name = entry.stem if entry.is_file() and entry.suffix == ".md" else entry.name
        if not is_valid_skill_name(name):
            return None
        if resolved.is_dir():
            candidate = resolved / SKILL_FILE
            if not candidate.is_file():
                return None
            return self._parse(candidate, name, scope)
        if resolved.is_file() and resolved.suffix == ".md":
            return self._parse(resolved, name, scope)
        return None

    def _parse(self, path: Path, stem: str, scope: str) -> Optional[Skill]:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        meta, body = parse_frontmatter(raw)
        name = str(meta.get("name") or stem).strip()
        if not is_valid_skill_name(name):
            return None
        description = _one_line(str(meta.get("description") or ""))
        run_as = _run_as(meta)
        allowed = _as_list(meta.get("allowed-tools", meta.get("allowed_tools", [])))
        model = str(meta.get("model") or "").strip()
        body = load_references(path, body.strip())
        return Skill(
            name=name,
            description=description,
            body=body,
            scope=scope,
            path=str(path),
            run_as=run_as,
            allowed_tools=allowed,
            model=model,
            context=_one_line(str(meta.get("context") or "")).replace("\\n", "\n"),
            heuristics=_as_lines(meta.get("heuristics")),
            checklist=_as_lines(meta.get("checklist")),
            anti_patterns=_as_lines(meta.get("anti_patterns")),
            output_format=_one_line(str(meta.get("output_format") or "")).replace("\\n", "\n"),
        )


def is_valid_skill_name(name: str) -> bool:
    return bool(VALID_NAME_RE.match(name.strip()))


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return _parse_meta_lines(lines[1:index]), "\n".join(lines[index + 1 :]).lstrip("\n")
    return {}, text


def render_skill_file(
    *,
    name: str,
    description: str,
    body: str,
    run_as: str = "inline",
    allowed_tools: Optional[list[str]] = None,
    model: str = "",
) -> str:
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        f"runAs: {run_as}",
    ]
    if model.strip():
        lines.append(f"model: {model.strip()}")
    cleaned_tools = [tool.strip() for tool in allowed_tools or [] if tool.strip()]
    if cleaned_tools:
        lines.append("allowed-tools: [" + ", ".join(cleaned_tools) + "]")
    lines.extend(["---", "", body.strip(), ""])
    return "\n".join(lines)


def render_skill(skill: Skill, arguments: str = "") -> str:
    lines = [
        f"# Skill: {skill.name}",
        "",
        f"Description: {skill.description or '(none)'}",
        f"Source: {skill.scope} ({skill.path})",
        f"Run mode: {skill.run_as}",
    ]
    if skill.allowed_tools:
        lines.append("Allowed tools: " + ", ".join(skill.allowed_tools))
    if skill.context:
        lines.extend(["", "## Context", skill.context.strip()])
    if skill.heuristics:
        lines.extend(["", "## Heuristics"] + [f"- {h}" for h in skill.heuristics])
    if skill.checklist:
        lines.extend(["", "## Checklist"] + [f"- [ ] {c}" for c in skill.checklist])
    if skill.anti_patterns:
        lines.extend(["", "## Anti-patterns (avoid)"] + [f"- ❌ {a}" for a in skill.anti_patterns])
    if skill.output_format:
        lines.extend(["", "## Output Format", skill.output_format.strip()])
    if arguments.strip():
        lines.extend(["", "Arguments:", arguments.strip()])
    lines.extend(["", "Instructions:", skill.body.strip()])
    return "\n".join(lines).strip()


def render_inline_skill(skill: Skill, arguments: str = "") -> str:
    return f'<skill-pin name="{skill.name}">\n{render_skill(skill, arguments)}\n</skill-pin>'


def apply_skill_index(base_prompt: str, skills: list[Skill]) -> str:
    indexed = [skill for skill in skills if skill.description.strip()]
    if not indexed:
        return base_prompt
    lines = [
        "# Skills - playbooks you can invoke",
        "",
        "Only the skill index is loaded here. When a listed playbook is useful, call "
        "`run_skill` with the bare skill name and a concrete arguments string. "
        "Inline skills return instructions inside this conversation. Subagent skills run in an isolated child loop "
        "and return only their final answer.",
        "",
    ]
    for skill in indexed:
        tag = " [subagent]" if skill.run_as == "subagent" else ""
        lines.append(f"- {skill.name}{tag} - {_one_line(skill.description)}")
    block = "\n".join(lines)
    if len(block) > INDEX_MAX_CHARS:
        block = block[: INDEX_MAX_CHARS - 80].rstrip() + "\n- ...[skills index truncated]"
    return base_prompt.rstrip() + "\n\n" + block


def load_references(skill_path: Path, body: str) -> str:
    if skill_path.name != SKILL_FILE:
        return body
    references = skill_path.parent / "references"
    if not references.is_dir():
        return body
    chunks = [body]
    for path in sorted(references.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            chunks.append(f"## Reference: {path.name}\n\n{text}")
    return "\n\n".join(chunk for chunk in chunks if chunk.strip())


def builtin_skills() -> list[Skill]:
    return [
        Skill(
            name="test",
            description="Run the project test suite, diagnose failures, fix them carefully, and rerun until green or blocked.",
            body=(
                "You are using the test skill inline. Detect the project's test command from its files, "
                "run the smallest useful test command first, diagnose failures from exact output, make focused fixes, "
                "and rerun. Do not install dependencies, delete tests, or silence failures without asking."
            ),
            scope="builtin",
            path="(builtin)",
            run_as="inline",
        ),
        Skill(
            name="init",
            description="Bootstrap or refresh a concise project memory file with commands, architecture, and conventions.",
            body=(
                "Analyze the project structure, manifests, README, and representative files. Then write or update a concise "
                "MEMORY.md/AGENTS.md-style guide with verified commands, architecture, conventions, and notes. Keep it short."
            ),
            scope="builtin",
            path="(builtin)",
            run_as="inline",
        ),
        Skill(
            name="explore",
            description="Read-only codebase investigation in an isolated subagent; returns a distilled answer with file references.",
            body=(
                "You are an exploration subagent. Use read_file, ls, glob, and grep. Cast a wide net, then read only relevant files. "
                "Return a concise answer with file references and mention searches used for negative claims."
            ),
            scope="builtin",
            path="(builtin)",
            run_as="subagent",
            allowed_tools=["read_file", "ls", "glob", "grep"],
        ),
        Skill(
            name="review",
            description="Review current changes in an isolated subagent for correctness, risks, and missing tests.",
            body=(
                "You are a code-review subagent. Inspect git status and diffs, read touched files when needed, and report findings "
                "by severity with file references. Stay read-only and do not modify files."
            ),
            scope="builtin",
            path="(builtin)",
            run_as="subagent",
            allowed_tools=["read_file", "ls", "glob", "grep", "bash", "git_status", "git_diff"],
        ),
        Skill(
            name="security-review",
            description="Security-focused review of changes for injection, auth, secrets, traversal, deserialization, and crypto risks.",
            body=(
                "You are a security-review subagent. Inspect diffs and relevant code for exploitable issues. Group findings by severity, "
                "cite files, and say plainly when no security issues are found."
            ),
            scope="builtin",
            path="(builtin)",
            run_as="subagent",
            allowed_tools=["read_file", "ls", "glob", "grep", "bash", "git_status", "git_diff"],
        ),
    ]


def _parse_meta_lines(lines: list[str]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    key = ""
    list_values: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if key and stripped.startswith("- "):
            list_values.append(stripped[2:].strip().strip("\"'"))
            meta[key] = list_values[:]
            continue
        key = ""
        list_values = []
        if ":" not in stripped:
            continue
        field, value = stripped.split(":", 1)
        field = field.strip()
        value = value.strip()
        if value == "":
            key = field
            list_values = []
            meta[field] = list_values
        else:
            meta[field] = _parse_meta_value(value)
    return meta


def _parse_meta_value(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",") if item.strip()]
    return value.strip().strip("\"'")


def _run_as(meta: dict[str, Any]) -> str:
    value = str(meta.get("runAs", meta.get("run_as", ""))).strip().lower()
    context = str(meta.get("context", "")).strip().lower()
    if value == "subagent" or context in {"fork", "subagent"}:
        return "subagent"
    return "inline"


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _resolve_custom_path(path: str | Path, base: Path, home: Path) -> Path:
    text = str(path)
    if text.startswith("~/"):
        return (home / text[2:]).resolve(strict=False)
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve(strict=False)


def _dedupe_roots(entries: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    seen: set[Path] = set()
    out: list[tuple[Path, str]] = []
    for path, scope in entries:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        out.append((resolved, scope))
        seen.add(resolved)
    return out


def _path_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    if not path.is_dir():
        return "not-directory"
    try:
        with os.scandir(path):
            return "ok"
    except OSError:
        return "unreadable"


def _one_line(text: str) -> str:
    return " ".join(str(text).strip().split())


def _as_lines(value: Any) -> list[str]:
    """Parse a YAML list or comma-separated string into lines."""
    if isinstance(value, list):
        return [str(item).strip().strip("\"'") for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip().strip("\"'") for item in value.split(",") if item.strip()]
    return []


def timestamp_slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())
