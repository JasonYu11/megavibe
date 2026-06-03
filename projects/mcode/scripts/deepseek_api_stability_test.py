from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_agent_lab.config import load_config, load_dotenv
from mini_agent_lab.provider import DeepSeekProvider, Message, ProviderError


def _call_once(index: int, provider: DeepSeekProvider, prompt: str, max_tokens: int) -> dict[str, Any]:
    started = time.perf_counter()
    wall_started = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        response = provider.complete(
            [
                Message(role="system", content="You are a terse API health-check responder."),
                Message(role="user", content=prompt),
            ],
            max_tokens=max_tokens,
        )
        elapsed = time.perf_counter() - started
        return {
            "index": index,
            "ok": True,
            "started_at": wall_started,
            "elapsed_seconds": round(elapsed, 3),
            "model": response.raw_model,
            "content_preview": (response.content or "")[:120],
            "error": "",
            "error_kind": "",
        }
    except Exception as exc:
        provider_error = exc if isinstance(exc, ProviderError) else None
        elapsed = time.perf_counter() - started
        return {
            "index": index,
            "ok": False,
            "started_at": wall_started,
            "elapsed_seconds": round(elapsed, 3),
            "model": "",
            "content_preview": "",
            "error": str(exc),
            "error_kind": _classify_error(exc),
            "status_code": provider_error.status_code if provider_error else None,
            "retryable": provider_error.retryable if provider_error else False,
            "provider_attempt": provider_error.attempt if provider_error else None,
            "request_id": provider_error.request_id if provider_error else "",
        }


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, ProviderError):
        return exc.kind
    text = str(exc).lower()
    if "429" in text:
        return "http_429"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "incomplete read" in text:
        return "incomplete_read"
    if "api error 5" in text:
        return "http_5xx"
    if "api error 4" in text:
        return "http_4xx"
    if "connection failed" in text or "urlopen error" in text:
        return "connection"
    return type(exc).__name__


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [r["elapsed_seconds"] for r in results if r["ok"]]
    errors: dict[str, int] = {}
    for result in results:
        if not result["ok"]:
            errors[result["error_kind"]] = errors.get(result["error_kind"], 0) + 1
    summary: dict[str, Any] = {
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "errors": errors,
    }
    if latencies:
        sorted_latencies = sorted(latencies)
        summary.update(
            {
                "min_seconds": min(latencies),
                "median_seconds": round(statistics.median(latencies), 3),
                "p95_seconds": sorted_latencies[min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))],
                "max_seconds": max(latencies),
            }
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repeated DeepSeek API calls and report stability.")
    parser.add_argument("--count", type=int, default=10, help="number of calls to run")
    parser.add_argument("--concurrency", type=int, default=1, help="parallel calls")
    parser.add_argument("--max-tokens", type=int, default=32, help="small output budget for health checks")
    parser.add_argument("--prompt", default="Reply with exactly: ok", help="health-check prompt")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    cfg = load_config()
    provider = DeepSeekProvider(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        temperature=0.0,
    )

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = [
            pool.submit(_call_once, i + 1, provider, args.prompt, args.max_tokens)
            for i in range(max(1, args.count))
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if not args.json:
                status = "OK" if result["ok"] else f"FAIL:{result['error_kind']}"
                print(f"{result['index']:03d} {status} {result['elapsed_seconds']:.3f}s {result['content_preview']}", flush=True)
                if result["error"]:
                    print(f"    {result['error']}", flush=True)

    results.sort(key=lambda item: item["index"])
    payload = {"summary": _summarize(results), "results": results}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\nSummary")
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0 if payload["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
