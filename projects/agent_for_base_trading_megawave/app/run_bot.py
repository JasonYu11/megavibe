from __future__ import annotations

import argparse
import os
import webbrowser
from dataclasses import dataclass
from threading import Event, Thread
from typing import Any

from app.bootstrap import build_trading_runtime_app
from app.config.settings import load_app_config
from app.dashboard.server import DashboardApp, serve

DEFAULT_RUNTIME_CONFIG = "configs/runtime.local.yaml"
DEFAULT_RISK_CONFIG = "configs/risk_policy.example.yaml"
DEFAULT_STRATEGIES_CONFIG = "configs/strategies.example.yaml"
DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8787


@dataclass
class DashboardHandle:
    url: str
    server: Any
    thread: Thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local Base trading Telegram bot runtime.")
    parser.add_argument("--runtime-config", default=DEFAULT_RUNTIME_CONFIG)
    parser.add_argument("--risk-config", default=DEFAULT_RISK_CONFIG)
    parser.add_argument("--strategies-config", default=DEFAULT_STRATEGIES_CONFIG)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--once", action="store_true", help="Run one orchestrator tick and exit.")
    parser.add_argument("--no-dashboard", action="store_true", help="Do not start the local HTML dashboard with the bot.")
    parser.add_argument("--dashboard-host", default=os.environ.get("DASHBOARD_HOST", DEFAULT_DASHBOARD_HOST))
    parser.add_argument("--dashboard-port", type=int, default=int(os.environ.get("DASHBOARD_PORT", str(DEFAULT_DASHBOARD_PORT))))
    parser.add_argument(
        "--no-dashboard-open",
        action="store_true",
        help="Start the dashboard server but do not open it in the browser.",
    )
    return parser


def start_dashboard_for_runtime(
    runtime_app: Any,
    *,
    host: str = DEFAULT_DASHBOARD_HOST,
    port: int = DEFAULT_DASHBOARD_PORT,
    open_browser: bool = True,
    max_port_attempts: int = 20,
) -> DashboardHandle:
    last_error: OSError | None = None
    for candidate_port in range(port, port + max_port_attempts):
        try:
            server = serve(DashboardApp(store=runtime_app.store, handler=runtime_app.handler), host=host, port=candidate_port)
            break
        except OSError as exc:
            last_error = exc
    else:
        raise RuntimeError(f"dashboard failed to bind {host}:{port}-{port + max_port_attempts - 1}") from last_error

    thread = Thread(target=server.serve_forever, name="dashboard-server", daemon=True)
    thread.start()
    url = f"http://{host}:{server.server_port}/"
    runtime_app.store.set_runtime_value("dashboard_url", url)
    print(f"dashboard running at {url} db={runtime_app.store.db_path}", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"dashboard browser open failed: {exc}", flush=True)
    return DashboardHandle(url=url, server=server, thread=thread)


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    config = load_app_config(
        runtime_path=args.runtime_config,
        risk_policy_path=args.risk_config,
        strategies_path=args.strategies_config,
        env_path=args.env_file,
    )
    app = build_trading_runtime_app(config, db_path=args.db_path)
    if args.once:
        result = app.orchestrator.tick_once()
        print(
            "tick "
            f"telegram_ok={result.telegram_ok} "
            f"watcher_ok={result.watcher_ok} "
            f"copy_watcher_ok={result.copy_watcher_ok} "
            f"receipt_ok={result.receipt_ok} "
            f"heartbeat_ok={result.heartbeat_ok}"
        )
        return
    dashboard: DashboardHandle | None = None
    if not args.no_dashboard:
        dashboard = start_dashboard_for_runtime(
            app,
            host=args.dashboard_host,
            port=args.dashboard_port,
            open_browser=not args.no_dashboard_open,
        )
    print(
        "bot running "
        f"execution_mode={config.execution_mode} "
        f"db={app.store.db_path} "
        "press Ctrl+C to stop",
        flush=True,
    )
    try:
        app.orchestrator.run_forever(stop_event=Event())
    except KeyboardInterrupt:
        print("bot stopped", flush=True)
    finally:
        if dashboard is not None:
            dashboard.stop()
            print("dashboard stopped", flush=True)


if __name__ == "__main__":
    main()
