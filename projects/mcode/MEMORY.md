# Mcode Memory

This file is loaded into every new session's system prompt.
Keep it concise, durable, and project-level.

## Project Goal

Build a learning implementation of a coding agent runtime.
The goal is to understand the architecture and tradeoffs, not to blindly clone Reasonix.

## Conventions

- Keep modules small and explicit.
- Prefer core runtime before UI.
- All tools implement the same Tool interface.
- Tool schemas describe what the model may request.
- The program validates, authorizes, executes, and records tool calls.
- Safety policy is config-driven.
- Write operations should produce preview and checkpoint.
- Long shell tasks should run through background jobs.
- Compact uses LLM semantic summary by default.
- Events should describe runtime state for future UI.

## Current Architecture

- Provider: DeepSeek OpenAI-compatible API.
- Session: in-memory messages plus JSONL persistence.
- Tool Registry: built-in tools exposed to the model.
- Agent Loop: model -> tool -> result -> model.
- SafetyGate: allow/ask/deny from config.
- Checkpoint: preview diff and restore support.
- Compact: LLM semantic summary with archives.
- Events: structured event stream for future UI.
- Memory: project instructions loaded from markdown into system prompt.

## Current Focus

Build the stable core before React UI.
Use Reasonix as a reference, but implement the smallest understandable version first.
