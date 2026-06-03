from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.config import load_config, load_dotenv
from mini_agent_lab.provider import DeepSeekProvider, Message, ProviderError


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe DeepSeek API connection stability.")
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--out-dir", default=str(ROOT.parent / "api_connection_tests"))
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    os.environ["DEEPSEEK_TIMEOUT_SECONDS"] = str(args.timeout)
    os.environ["DEEPSEEK_MAX_RETRIES"] = str(args.retries)
    cfg = load_config()
    provider = DeepSeekProvider(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        temperature=0.0,
    )

    rows: list[dict[str, Any]] = []
    for index in range(1, args.attempts + 1):
        started = time.time()
        row: dict[str, Any] = {
            "attempt": index,
            "started_at": started,
            "timeout_seconds": args.timeout,
            "max_retries": args.retries,
        }
        try:
            response = provider.complete(
                [
                    Message(role="system", content="Reply with OK only."),
                    Message(role="user", content=f"ping {index}"),
                ],
                max_tokens=8,
            )
            row.update(
                {
                    "ok": True,
                    "latency_seconds": round(time.time() - started, 3),
                    "raw_model": response.raw_model,
                    "content": (response.content or "")[:80],
                    "error": "",
                    "error_type": "",
                }
            )
        except Exception as exc:
            provider_error = exc if isinstance(exc, ProviderError) else None
            row.update(
                {
                    "ok": False,
                    "latency_seconds": round(time.time() - started, 3),
                    "raw_model": "",
                    "content": "",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "failure_kind": provider_error.kind if provider_error else "",
                    "status_code": provider_error.status_code if provider_error else None,
                    "retryable": provider_error.retryable if provider_error else False,
                    "provider_attempt": provider_error.attempt if provider_error else None,
                    "request_id": provider_error.request_id if provider_error else "",
                }
            )
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
        if index != args.attempts:
            time.sleep(args.delay)

    success = [item for item in rows if item["ok"]]
    failed = [item for item in rows if not item["ok"]]
    latencies = [float(item["latency_seconds"]) for item in success]
    summary = {
        "base_url": cfg.base_url,
        "model": cfg.model,
        "attempts": args.attempts,
        "success_count": len(success),
        "failure_count": len(failed),
        "success_rate": round(len(success) / max(1, args.attempts), 3),
        "timeout_seconds": args.timeout,
        "max_retries": args.retries,
        "latency_min_seconds": round(min(latencies), 3) if latencies else None,
        "latency_median_seconds": round(statistics.median(latencies), 3) if latencies else None,
        "latency_max_seconds": round(max(latencies), 3) if latencies else None,
        "failure_kinds": _counts(str(item.get("failure_kind") or item["error_type"]) for item in failed),
        "error_types": _counts(str(item["error_type"]) for item in failed),
        "rows": rows,
    }
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-deepseek-connection.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nSUMMARY")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2))
    print(f"[connection-test] report={out_path}")
    return 0 if not failed else 1


def _counts(values) -> dict[str, int]:
    rows: dict[str, int] = {}
    for value in values:
        rows[value] = rows.get(value, 0) + 1
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
