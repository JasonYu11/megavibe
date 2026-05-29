from __future__ import annotations

import argparse

from app.bootstrap import build_trading_runtime_app
from app.config.settings import load_app_config
from app.dashboard.server import DashboardApp, serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local trading dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--runtime-config", default="configs/runtime.local.yaml")
    parser.add_argument("--risk-config", default="configs/risk_policy.example.yaml")
    parser.add_argument("--strategies-config", default="configs/strategies.example.yaml")
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()

    config = load_app_config(
        runtime_path=args.runtime_config,
        risk_policy_path=args.risk_config,
        strategies_path=args.strategies_config,
    )
    runtime = build_trading_runtime_app(config, db_path=args.db_path)
    dashboard = DashboardApp(store=runtime.store, handler=runtime.handler)
    server = serve(dashboard, host=args.host, port=args.port)
    print(f"dashboard running at http://{args.host}:{args.port}/ db={runtime.store.db_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("dashboard stopped")


if __name__ == "__main__":
    main()
