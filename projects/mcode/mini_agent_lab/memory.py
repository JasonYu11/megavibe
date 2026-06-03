from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_MEMORY_FILES = ("MEMORY.md", "MEMORY.local.md")
MAX_IMPORT_DEPTH = 3
VALID_MEMORY_TYPES = {"user", "feedback", "project", "reference"}
MAX_MEMORY_DESCRIPTION_CHARS = 240
MAX_MEMORY_BODY_CHARS = 2000


@dataclass(frozen=True)
class MemorySource:
    path: Path
    content: str


@dataclass(frozen=True)
class MemoryBundle:
    sources: list[MemorySource]
    auto_index: str = ""
    auto_dir: Optional[Path] = None

    @property
    def content(self) -> str:
        sections = [source.content.strip() for source in self.sources if source.content.strip()]
        index = self.auto_index.strip()
        if index:
            sections.append(
                "## Saved Memories\n\n"
                "These are durable facts saved by the agent. The index is loaded to keep the prompt small. "
                "When a saved memory looks relevant, read its linked markdown file with read_file. "
                "Save new durable facts with the remember tool; prefer updating an existing name over duplicating it.\n\n"
                + index
                + (f"\n\n(stored under {self.auto_dir})" if self.auto_dir else "")
            )
        return "\n\n".join(sections)

    @property
    def paths(self) -> list[Path]:
        return [source.path for source in self.sources]

    def is_empty(self) -> bool:
        return not self.content.strip()


@dataclass(frozen=True)
class SavedMemory:
    name: str
    description: str
    type: str
    body: str
    path: Path
    updated_at: str = ""


class AutoMemoryStore:
    """Reasonix-style durable memory store.

    The prompt gets only the index. Each fact lives in its own markdown file so
    the model can read relevant details on demand without growing every turn.
    """

    index_name = "MEMORY.md"

    def __init__(self, directory: str | Path = ".memory") -> None:
        self.directory = Path(directory)
        self.facts_dir = self.directory / "facts"

    @property
    def index_path(self) -> Path:
        return self.directory / self.index_name

    def index(self) -> str:
        if not self.index_path.exists():
            return ""
        return self.index_path.read_text(encoding="utf-8").strip()

    def path_for(self, name: str) -> Path:
        return self.facts_dir / f"{_slug(name)}.md"

    def save(self, *, name: str, description: str, type: str, body: str) -> SavedMemory:
        description = _one_line(description)
        body = body.strip()
        if not description:
            raise ValueError("description is required")
        if not body:
            raise ValueError("body is required")
        if len(description) > MAX_MEMORY_DESCRIPTION_CHARS:
            raise ValueError(f"description is too long; keep it under {MAX_MEMORY_DESCRIPTION_CHARS} characters")
        if len(body) > MAX_MEMORY_BODY_CHARS:
            raise ValueError(f"body is too long; summarize it under {MAX_MEMORY_BODY_CHARS} characters")
        if _looks_sensitive_text(description) or _looks_sensitive_text(body):
            raise ValueError("memory appears to contain sensitive secret-like content")

        slug = _slug(name or description)
        if not slug:
            slug = "memory-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        memory_type = normalize_memory_type(type)
        self.facts_dir.mkdir(parents=True, exist_ok=True)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path = self.path_for(slug)
        path.write_text(
            _render_saved_memory(
                name=slug,
                description=description,
                type=memory_type,
                body=body,
                updated_at=now,
            ),
            encoding="utf-8",
        )
        self._reindex()
        return SavedMemory(
            name=slug,
            description=description,
            type=memory_type,
            body=body,
            path=path,
            updated_at=now,
        )

    def list(self) -> list[SavedMemory]:
        if not self.facts_dir.exists():
            return []
        memories = []
        for path in sorted(self.facts_dir.glob("*.md")):
            parsed = _parse_saved_memory(path)
            if parsed:
                memories.append(parsed)
        return memories

    def _reindex(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        lines = ["# Memory", ""]
        cwd = Path.cwd().resolve(strict=False)
        for memory in self.list():
            resolved = memory.path.resolve(strict=False)
            rel = resolved.relative_to(cwd).as_posix() if _is_relative_to(resolved, cwd) else resolved.as_posix()
            lines.append(f"- [{memory.name}]({rel}) — [{memory.type}] {memory.description}")
        self.index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def load_memory(
    root: str | Path = ".",
    names: tuple[str, ...] = DEFAULT_MEMORY_FILES,
    auto_store: Optional[AutoMemoryStore] = None,
) -> MemoryBundle:
    """Load project memory files from the workspace root."""
    base = Path(root).resolve()
    sources: list[MemorySource] = []
    for name in names:
        path = base / name
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        expanded = _expand_imports(raw, base_dir=path.parent, root=base, seen={path.resolve()}, depth=0)
        sources.append(MemorySource(path=path, content=expanded))
    return MemoryBundle(
        sources=sources,
        auto_index=auto_store.index() if auto_store else "",
        auto_dir=auto_store.directory if auto_store else None,
    )


def compose_system_prompt(base_prompt: str, memory: MemoryBundle) -> str:
    """Attach project memory to the stable system prompt for new sessions."""
    memory_text = memory.content.strip()
    if not memory_text:
        return base_prompt
    return (
        base_prompt.rstrip()
        + "\n\n"
        + "## Project Memory\n\n"
        + "The following markdown is project-level guidance loaded before the conversation.\n\n"
        + memory_text
    )


def _expand_imports(
    text: str,
    *,
    base_dir: Path,
    root: Path,
    seen: set[Path],
    depth: int,
) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("@") or " " in stripped:
            lines.append(line)
            continue

        imported = _read_import(stripped[1:], base_dir=base_dir, root=root, seen=seen, depth=depth)
        lines.append(imported)
    return "\n".join(lines)


def _read_import(import_path: str, *, base_dir: Path, root: Path, seen: set[Path], depth: int) -> str:
    if depth >= MAX_IMPORT_DEPTH:
        return f"[memory import skipped: max depth reached for {import_path}]"

    candidate = Path(import_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (base_dir / candidate).resolve()

    if not _is_relative_to(resolved, root):
        return f"[memory import skipped: outside workspace: {import_path}]"
    if _looks_sensitive(resolved):
        return f"[memory import skipped: sensitive path: {import_path}]"
    if resolved in seen:
        return f"[memory import skipped: circular import: {import_path}]"
    if not resolved.exists() or not resolved.is_file():
        return f"[memory import skipped: missing file: {import_path}]"

    seen.add(resolved)
    body = resolved.read_text(encoding="utf-8")
    expanded = _expand_imports(body, base_dir=resolved.parent, root=root, seen=seen, depth=depth + 1)
    return f"\n[memory import: {resolved.relative_to(root)}]\n{expanded}\n[/memory import]\n"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _looks_sensitive(path: Path) -> bool:
    sensitive_names = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
    return any(part.startswith(".") for part in path.parts) or path.name in sensitive_names


def normalize_memory_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in VALID_MEMORY_TYPES:
        return normalized
    return "project"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _render_saved_memory(*, name: str, description: str, type: str, body: str, updated_at: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "metadata:\n"
        f"  type: {type}\n"
        f"updated_at: {updated_at}\n"
        "---\n\n"
        + body.strip()
        + "\n"
    )


def _parse_saved_memory(path: Path) -> Optional[SavedMemory]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter, body = _split_frontmatter(text)
    name = frontmatter.get("name") or path.stem
    description = frontmatter.get("description") or _one_line(body[:120])
    memory_type = normalize_memory_type(frontmatter.get("type", "project"))
    updated_at = frontmatter.get("updated_at", "")
    return SavedMemory(
        name=name,
        description=description,
        type=memory_type,
        body=body.strip(),
        path=path,
        updated_at=updated_at,
    )


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    raw = text[4:end].splitlines()
    body = text[end + len("\n---") :].strip()
    data: dict[str, str] = {}
    in_metadata = False
    for line in raw:
        if line.strip() == "metadata:":
            in_metadata = True
            continue
        if in_metadata and line.startswith("  ") and ":" in line:
            key, value = line.strip().split(":", 1)
            data[key.strip()] = value.strip()
            continue
        in_metadata = False
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    return data, body


def _looks_sensitive_text(text: str) -> bool:
    lowered = text.lower()
    secret_words = ["api_key", "apikey", "secret_key", "access_token", "password", "private key"]
    if any(word in lowered for word in secret_words):
        return True
    if re.search(r"sk-[a-zA-Z0-9_-]{16,}", text):
        return True
    return False
