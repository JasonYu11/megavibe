# Mcode UI

Codex-style local agent workbench for Mcode.

## Run

Start the backend:

```bash
cd backend
python3 -m uvicorn app:app --host 127.0.0.1 --port 8008
```

Start the frontend:

```bash
cd frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## macOS App

Build:

```bash
mcode-ui/macos/build_app.sh
```

Open:

```text
mcode-ui/dist/mcode.app
```

The app starts the local FastAPI backend and Vite frontend if they are not already running, then embeds the UI in a native WKWebView window.

## Checks

Backend smoke test:

```bash
python3 tests/test_ui_backend.py
```

Frontend tests:

```bash
cd mcode-ui/frontend
npm run test -- --run
npm run build
```

## Data Sources

- Projects: `.mcode-ui/projects.json`
- Sessions: `.sessions/*.jsonl`
- Runs/events: `.runs/*.events.jsonl`, `.runs/*.summary.json`
- Subagents: `.subagents/<session>/*`
- Jobs: `.jobs/*`
- Files: selected project root, guarded against path escape

## Runtime Model

The backend uses `mini_agent_lab.control.ControllerManager`.

- One `MiniController` owns one session lifecycle.
- One controller allows only one active turn at a time.
- `cancel` is cooperative and is passed into `Agent` through its `cancelled` callback.
- Session and subagent state files are written through temp-file + rename.
