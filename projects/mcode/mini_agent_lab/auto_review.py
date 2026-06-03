from __future__ import annotations

import json
import re as re_mod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from mini_agent_lab.provider.deepseek import DeepSeekProvider
from mini_agent_lab.provider.types import Message


class Decision(Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"


@dataclass
class ReviewInput:
    """Input to the AutoReviewAgent."""
    user_message: str            # User's original input / intent
    tool_name: str               # Name of the tool being called
    tool_args: dict              # Arguments to the tool
    safety_reason: str           # Reason from SafetyGate for "ask" decision
    session_summary: str         # Brief summary of recent session context
    plan_mode: bool = False      # Whether agent is in plan mode


@dataclass
class ReviewOutput:
    decision: Decision
    reason: str


@dataclass
class AutoReviewConfig:
    """Auto-review configuration parsed from mcode-policy.json."""
    enabled: bool = True
    model: str = "deepseek-chat"
    temperature: float = 0.0
    skip_tools: list[str] = None  # type: ignore
    always_escalate: list[str] = None  # type: ignore
    strictness: dict[str, str] = None  # type: ignore

    def __post_init__(self):
        if self.skip_tools is None:
            self.skip_tools = []
        if self.always_escalate is None:
            self.always_escalate = []
        if self.strictness is None:
            self.strictness = {}

    @classmethod
    def from_dict(cls, raw: Optional[dict]) -> "AutoReviewConfig":
        if not raw or not isinstance(raw, dict):
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", True)),
            model=str(raw.get("model", "deepseek-chat")),
            temperature=float(raw.get("temperature", 0.0)),
            skip_tools=list(raw.get("skip_tools", [])),
            always_escalate=list(raw.get("always_escalate", [])),
            strictness={str(k): str(v) for k, v in raw.get("strictness", {}).items()},
        )

    def should_skip(self, tool_name: str, tool_args: dict) -> bool:
        """Check if this tool call should skip auto-review (go straight to human)."""
        subject = _subject(tool_name, tool_args)
        for rule in self.skip_tools:
            if _match_rule(rule, tool_name, subject):
                return True
        return False

    def should_always_escalate(self, tool_name: str, tool_args: dict) -> bool:
        """Check if this tool call should always escalate (never auto-approve)."""
        subject = _subject(tool_name, tool_args)
        for rule in self.always_escalate:
            if _match_rule(rule, tool_name, subject):
                return True
        return False

    def strictness_for(self, tool_name: str) -> str:
        """Get strictness level for a tool: 'high', 'normal', or 'low'."""
        return self.strictness.get(tool_name, "normal")


def _subject(tool_name: str, args: dict) -> str:
    """Extract the matchable subject from tool args (command, path, etc.)."""
    if tool_name == "bash":
        return str(args.get("command", ""))
    if tool_name in ("write_file", "edit_file"):
        return str(args.get("path", ""))
    if tool_name == "grep":
        return str(args.get("pattern", ""))
    return ""


def _match_rule(rule: str, tool_name: str, subject: str) -> bool:
    """Match a rule string like 'bash(git push*)' or 'write_file' against a tool call."""
    # Check if rule has a subject pattern: "ToolName(pattern)"
    m = re_mod.match(r"^(\w+)\((.+)\)$", rule.strip())
    if m:
        rule_tool = m.group(1)
        rule_pattern = m.group(2)
        if rule_tool != tool_name:
            return False
        if not subject:
            return False
        return _glob_match(rule_pattern, subject)
    # Bare tool name: "bash" or "write_file"
    return rule.strip() == tool_name


def _glob_match(pattern: str, text: str) -> bool:
    """Simple glob matching: * matches any chars, ? matches one char."""
    import fnmatch
    return fnmatch.fnmatch(text, pattern)


AUTO_REVIEW_SYSTEM = """\
You are a Safety Review Agent. Your job is to decide whether a tool call from a coding
AI agent should be automatically approved, rejected, or escalated to the human user.

## Decision Rules

**approve** — The tool call is clearly aligned with the user's intent AND the risk is
low (affects only workspace files, is reversible, does not touch system configs,
does not exfiltrate data).

**reject** — The tool call is dangerous (destructive commands, sudo, rm -rf, force push,
system-level changes) OR clearly violates the user's intent (e.g. committing code when
the user asked to search).

**escalate** — You cannot confidently decide. The risk is moderate and the alignment
with user intent is ambiguous. Let the human decide.

## Important
- If the user explicitly asked for an action (e.g. "commit my changes"), approve it.
- If the agent is doing something the user did NOT ask for, reject or escalate.
- Bash commands are high-risk by nature — be stricter with them.
- git commit/push without user request should be escalated or rejected.
- Read-only tools and workspace write_file/edit_file with clear user intent are safe.

Output ONLY a JSON object with no extra text:
{"decision": "approve|reject|escalate", "reason": "concise explanation in the user's language"}
"""


def _build_user_prompt(inp: ReviewInput, strictness: str) -> str:
    """Build the review prompt with strictness hints."""
    strictness_hint = ""
    if strictness == "high":
        strictness_hint = "\n## Strictness: HIGH\nBe extra cautious. Prefer reject over escalate, and escalate over approve."
    elif strictness == "low":
        strictness_hint = "\n## Strictness: LOW\nThis tool is generally safe. Prefer approve for clear matches."

    return f"""## User Intent
{inp.user_message}

## Tool Call
Tool: {inp.tool_name}
Arguments: {json.dumps(inp.tool_args, indent=2, ensure_ascii=False)}

## Risk Assessment (from static rules)
{inp.safety_reason}
{strictness_hint}
## Session Context
{inp.session_summary or "(no prior context)"}

## Plan Mode
{"Yes — agent should NOT execute write tools" if inp.plan_mode else "No — agent is in normal execution mode"}

Review this tool call and output your decision."""


class AutoReviewAgent:
    """LLM-based reviewer that sits between SafetyGate (static rules) and human Approver.

    When SafetyGate returns "ask", the AutoReviewAgent evaluates whether the call can
    be auto-approved based on user intent alignment and risk profile. Only ambiguous
    cases escalate to the human.
    """

    def __init__(
        self,
        provider: DeepSeekProvider,
        config: Optional[AutoReviewConfig] = None,
    ) -> None:
        self.provider = provider
        self.config = config or AutoReviewConfig()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def review(self, inp: ReviewInput) -> ReviewOutput:
        """Return (decision, reason) for a tool call that SafetyGate flagged as "ask"."""
        if not self.config.enabled:
            return ReviewOutput(
                decision=Decision.ESCALATE,
                reason="auto-review disabled",
            )

        # Check skip rules — go straight to human
        if self.config.should_skip(inp.tool_name, inp.tool_args):
            return ReviewOutput(
                decision=Decision.ESCALATE,
                reason=f"skipped by config: {inp.tool_name}",
            )

        # Check always_escalate rules — force escalate
        force_escalate = self.config.should_always_escalate(inp.tool_name, inp.tool_args)

        try:
            strictness = self.config.strictness_for(inp.tool_name)
            response = self._call_model(inp, strictness)
            result = self._parse_response(response)

            # Override: if always_escalate is set, never auto-approve
            if force_escalate and result.decision == Decision.APPROVE:
                return ReviewOutput(
                    decision=Decision.ESCALATE,
                    reason=f"force-escalated by config: {inp.tool_name} — {result.reason}",
                )

            # Override: plan mode should never auto-approve writes
            if inp.plan_mode and result.decision == Decision.APPROVE:
                return ReviewOutput(
                    decision=Decision.REJECT,
                    reason=f"plan mode rejects writes: {result.reason}",
                )

            return result
        except Exception:
            return ReviewOutput(
                decision=Decision.ESCALATE,
                reason="auto-review failed — escalating to human for safety",
            )

    def _call_model(self, inp: ReviewInput, strictness: str = "normal") -> str:
        messages = [
            Message(role="system", content=AUTO_REVIEW_SYSTEM),
            Message(role="user", content=_build_user_prompt(inp, strictness)),
        ]
        resp = self.provider.complete(messages, tools=None, max_tokens=256)
        return resp.content.strip()

    def _parse_response(self, raw: str) -> ReviewOutput:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            inner = "\n".join(lines[1:])
            if inner.endswith("```"):
                inner = inner[:-3]
            text = inner.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re_mod.search(r'\{[^{}]*"decision"[^{}]*\}', text)
            if m:
                try:
                    data = json.loads(m.group(0))
                except json.JSONDecodeError:
                    return ReviewOutput(
                        decision=Decision.ESCALATE,
                        reason=f"unparseable review response: {raw[:100]}",
                    )
            else:
                return ReviewOutput(
                    decision=Decision.ESCALATE,
                    reason=f"unparseable review response: {raw[:100]}",
                )

        decision_str = str(data.get("decision", "")).lower().strip()
        reason = str(data.get("reason", "no reason provided"))

        valid = {"approve": Decision.APPROVE, "reject": Decision.REJECT, "escalate": Decision.ESCALATE}
        decision = valid.get(decision_str, Decision.ESCALATE)
        return ReviewOutput(decision=decision, reason=reason)
