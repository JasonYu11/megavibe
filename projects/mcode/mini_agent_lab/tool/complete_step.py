from __future__ import annotations

from dataclasses import dataclass

from mini_agent_lab.tool.base import JsonObject, Tool


VALID_EVIDENCE_KINDS = {"verification", "diff", "files", "manual"}


@dataclass(frozen=True)
class StepEvidence:
    kind: str
    summary: str
    command: str = ""
    paths: tuple[str, ...] = ()


class CompleteStepTool(Tool):
    @property
    def name(self) -> str:
        return "complete_step"

    @property
    def description(self) -> str:
        return (
            "Record the evidence-backed completion of one approved plan step. "
            "Use it after finishing a concrete step, not before. Evidence is required: "
            "cite the verification command/result, changed files or diff, or a manual check. "
            "Fields: step, result, evidence[] with kind verification|diff|files|manual and summary."
        )

    @property
    def schema(self) -> JsonObject:
        return {
            "type": "object",
            "properties": {
                "step": {
                    "type": "string",
                    "description": "The approved plan step being completed.",
                },
                "result": {
                    "type": "string",
                    "description": "What is now true after completing the step.",
                },
                "evidence": {
                    "type": "array",
                    "minItems": 1,
                    "description": "Proof that the step is complete.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["verification", "diff", "files", "manual"],
                            },
                            "summary": {
                                "type": "string",
                                "description": "The actual evidence: test result, diff summary, file list, or manual confirmation.",
                            },
                            "command": {
                                "type": "string",
                                "description": "Command run for verification evidence.",
                            },
                            "paths": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Files this evidence refers to.",
                            },
                        },
                        "required": ["kind", "summary"],
                    },
                },
                "notes": {
                    "type": "string",
                    "description": "Optional caveats or follow-up notes.",
                },
            },
            "required": ["step", "result", "evidence"],
        }

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, arguments: JsonObject) -> str:
        step = _required_text(arguments, "step")
        result = _required_text(arguments, "result")
        evidence = _parse_evidence(arguments.get("evidence"))
        kinds = ", ".join(item.kind for item in evidence)
        return (
            f'Step "{step}" completed with {len(evidence)} evidence item(s) [{kinds}]. '
            f"Result: {result}"
        )


def _required_text(arguments: JsonObject, key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _parse_evidence(raw: object) -> list[StepEvidence]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("evidence must be a non-empty array")
    evidence: list[StepEvidence] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"evidence {index}: item must be an object")
        kind = item.get("kind")
        if kind not in VALID_EVIDENCE_KINDS:
            raise ValueError(f"evidence {index}: kind must be verification, diff, files, or manual")
        summary = item.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"evidence {index}: summary is required")
        command = item.get("command", "")
        if command is not None and not isinstance(command, str):
            raise ValueError(f"evidence {index}: command must be a string")
        paths = item.get("paths", [])
        if paths is None:
            paths = []
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            raise ValueError(f"evidence {index}: paths must be an array of strings")
        evidence.append(
            StepEvidence(
                kind=kind,
                summary=summary.strip(),
                command=(command or "").strip(),
                paths=tuple(path for path in paths if path),
            )
        )
    return evidence
