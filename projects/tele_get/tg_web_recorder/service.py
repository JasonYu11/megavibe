from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import analyzer, digest, runner
from .config import load_config
from .env import load_env


ROOT = Path(__file__).resolve().parents[1]


def utc_hhmm() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M")


def due_digest_slot(config: dict, sent_slots: set[str]) -> str | None:
    now = datetime.now(timezone.utc)
    now_hhmm = now.strftime("%H:%M")
    due_slots = sorted(slot for slot in config.get("digest_push_times_utc", []) if slot <= now_hhmm)
    if not due_slots:
        return None
    slot = due_slots[-1]
    key = now.strftime("%Y-%m-%d") + "T" + slot
    if key in sent_slots:
        return None
    sent_slots.add(key)
    return key


def safe_step(name: str, fn):
    try:
        return {"ok": True, "result": fn()}
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=8),
        }


def run_loop(config_path: str, env_path: str, profile: str, headless: bool, dry_run: bool) -> None:
    sent_digest_slots: set[str] = set()

    while True:
        cycle_t0 = time.monotonic()
        cycle_started = datetime.now(timezone.utc).isoformat()
        result = {"started_at": cycle_started, "dry_run": dry_run}
        try:
            config = load_config(config_path)
            env = load_env(env_path)
            interval = int(config.get("interval_seconds", 300))
        except Exception as exc:
            result["config"] = {"ok": False, "error": str(exc), "traceback": traceback.format_exc(limit=8)}
            interval = 300
            print(json.dumps(result, ensure_ascii=False), flush=True)
            time.sleep(interval)
            continue

        result["collect"] = safe_step("collect", lambda: runner.run_once(config, profile, headless))
        result["analyze"] = safe_step("analyze", lambda: analyzer.run_once(config, env, use_mock=False, push=not dry_run))

        digest_slot = due_digest_slot(config, sent_digest_slots)
        if digest_slot:
            result["digest_slot"] = digest_slot
            result["digest"] = safe_step(
                "digest",
                lambda: digest.run_digest_with_key(
                    config,
                    env,
                    hours=12,
                    use_mock=False,
                    push=not dry_run,
                    dedup_key=f"digest:{digest_slot}",
                ),
            )

        elapsed = time.monotonic() - cycle_t0
        result["elapsed_seconds"] = round(elapsed, 3)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        time.sleep(max(1, interval - elapsed))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run collector, LLM analyzer, immediate push, and scheduled digests.")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--env", default=str(ROOT / ".env"))
    parser.add_argument("--profile", default=str(ROOT / "profiles" / "telegram-web"))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Analyze but do not send Telegram pushes.")
    parser.add_argument("--once", action="store_true", help="Run one service cycle and exit.")
    args = parser.parse_args()
    if args.once:
        config = load_config(args.config)
        env = load_env(args.env)
        result = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": args.dry_run,
            "collect": safe_step("collect", lambda: runner.run_once(config, args.profile, args.headless)),
            "analyze": safe_step("analyze", lambda: analyzer.run_once(config, env, use_mock=False, push=not args.dry_run)),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return
    run_loop(args.config, args.env, args.profile, args.headless, args.dry_run)


if __name__ == "__main__":
    main()
