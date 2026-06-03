# Mcode macOS Native App Plan

## Goal

Build Mcode into a macOS native desktop application with a Codex-style local agent workbench.

The recommended direction is not to rewrite the agent or UI from scratch. Mcode already has a usable Python agent core, FastAPI backend, React frontend, and a minimal Swift `WKWebView` wrapper. The first product milestone should convert this development stack into a shippable local app:

```text
Mcode.app
  Swift native launcher
  WKWebView workbench
  local FastAPI sidecar
  built React frontend
  project-scoped agent data
```

## Current State

Core pieces already exist:

- `mini_agent_lab/`
  Python agent kernel: sessions, provider, tools, safety, git baseline, checkpoints, run recorder, memory, skills, subagents.
- `mcode-ui/backend/`
  FastAPI API layer for projects, sessions, events, messages, approvals, files, terminals, settings, tests, and runtime discovery.
- `mcode-ui/frontend/`
  React/Vite UI with a Codex-like three-column workbench.
- `mcode-ui/macos/`
  Minimal Swift `WKWebView` app wrapper.

Current macOS wrapper behavior after Phase 1:

- Builds `frontend/dist` and serves it from FastAPI.
- Starts one bundled FastAPI backend sidecar from `Mcode.app`.
- Chooses a local port in the `18080...18279` range.
- Opens `http://127.0.0.1:<port>/` in `WKWebView`.
- Stores app-level state in `~/Library/Application Support/Mcode`.
- Writes startup logs to `~/Library/Application Support/Mcode/logs/backend.log`.
- Supports app-local API key storage through `~/Library/Application Support/Mcode/.env`.

Phase 1 removed the dev-server dependency. The app is now usable as a local desktop app, but it is not yet fully productized as a native macOS application.

## Completed Work

Phase 1 is complete as of 2026-06-02:

- `Mcode.app` can be built from `mcode-ui/macos/build_app.sh`.
- The Swift launcher no longer starts Vite.
- The backend serves the built React app.
- Bundle resources include `frontend-dist`, `backend`, `mini_agent_lab`, and `scripts`.
- App state and logs moved to Application Support.
- API Key can be configured from the Settings UI without editing repository `.env`.
- Product acceptance currently includes 11 checks and passes 11/11.

## Recommended Architecture

### Short-Term Architecture

Use a native macOS launcher around the existing web workbench:

```text
Swift AppDelegate
  ├─ choose a free localhost port
  ├─ start backend sidecar
  ├─ wait for /api/health
  ├─ load http://127.0.0.1:<port>/
  └─ terminate child process on quit

FastAPI backend
  ├─ /api/*
  ├─ serves frontend/dist
  ├─ reads/writes app-level state from Application Support
  └─ reads/writes project-level agent state inside selected projects

React frontend
  ├─ calls relative /api paths
  ├─ renders transcript, tools, diff review, terminal, files
  └─ keeps Codex-style workbench layout
```

### Long-Term Architecture

After the first macOS app milestone, move toward stronger runtime isolation:

- One worker process per active project/session, or at least per project.
- No global `chdir` lock in the controller.
- Running-turn semantics for guide, queue, and interrupt.
- Keychain-backed API credentials.
- App menus, settings, update checks, signed/notarized release flow.

## Why This Route

This route is the best fit for Mcode now because:

- The React UI already handles complex surfaces that would be slow to rebuild in SwiftUI: transcript, tool cards, diff previews, event timelines, file tree, terminal panes, and settings.
- The Python backend already exposes a broad product API.
- `WKWebView` gives a native macOS window while preserving fast frontend iteration.
- The app can become product-like without delaying on a full native rewrite.
- It matches the Codex desktop feel: native shell, local agent runtime, dense workbench UI.

Avoid for the first milestone:

- Electron: too heavy for this project and unnecessary on macOS.
- Tauri: useful, but would add Rust packaging complexity without solving the Python sidecar problem.
- Pure SwiftUI rewrite: high effort and likely to slow iteration on agent UX.
- Wails-style direct binding: good for a Go kernel like Reasonix, less natural for the current Python kernel.

## Phase 1: Make a Real Local App

Target: double-click `Mcode.app` and use the app without manually starting frontend/backend services.

### 1. Serve Built Frontend from Backend

Modify `mcode-ui/backend/app.py`:

- Mount `frontend/dist` as static assets.
- Keep all `/api/*` routes unchanged.
- Serve `index.html` for non-API paths.
- Make frontend path configurable for bundled app layout.

Expected runtime:

```text
http://127.0.0.1:<port>/
http://127.0.0.1:<port>/api/health
```

The frontend already uses relative `/api` URLs, so it should not need a large API client rewrite.

### 2. Replace Vite Dev Server in macOS Launcher

Modify `mcode-ui/macos/McodeApp.swift`:

- Remove `npm run dev` launch.
- Remove fixed `5173` and `8008` ports.
- Remove hard-coded repository root.
- Resolve bundled resources through `Bundle.main`.
- Start one backend process with a chosen port.
- Load the backend URL in `WKWebView`.
- Add startup failure UI with log path.

Launcher should pass arguments such as:

```text
--host 127.0.0.1
--port <dynamic-port>
--app-data-dir ~/Library/Application Support/Mcode
--frontend-dist <bundle-resource-path>/frontend-dist
```

### 3. Update Build Script

Modify `mcode-ui/macos/build_app.sh`:

- Run frontend build.
- Copy `frontend/dist` into app resources.
- Copy backend sources or a backend sidecar into app resources.
- Compile Swift launcher.
- Generate `dist/Mcode.app`.

First version can use local Python for speed, but it must no longer require `npm run dev`.

Suggested bundle layout for phase 1:

```text
Mcode.app/
  Contents/
    Info.plist
    MacOS/
      Mcode
    Resources/
      frontend-dist/
      backend/
      mini_agent_lab/
      scripts/
```

### 4. Keep Project Data in Project Roots

For phase 1, project-level agent state should remain in the selected project root:

```text
.sessions/
.runs/
.jobs/
.gitstate/
.checkpoints/
.archives/
.memory/
.subagents/
```

This keeps Mcode transparent and easy to inspect.

### 5. Move App-Level State to Application Support

Move app-level state out of the repository:

```text
~/Library/Application Support/Mcode/
  projects.json
  logs/
  runtime/
```

Project sessions and run artifacts still live inside each project. App-level project registry and logs should not.

## Phase 2: Productize macOS Behavior

Target: make Mcode feel like a real macOS app instead of a web app inside a window.

Recommended split:

- Phase 2A: native shell, menus, window behavior, project opening.
- Phase 2B: Keychain credentials.
- Phase 2C: Speech framework voice input.
- Phase 2D: backend resilience and restart behavior.

### Phase 2A: Native Shell

Implement first.

Goals:

- Add a standard macOS menu bar.
- Add native folder picking for opening projects.
- Make Dock reopen behavior correct.
- Make the window title reflect the active project/session.
- Keep the backend lifecycle predictable.

Implementation tasks:

1. Add native menu construction in `mcode-ui/macos/McodeApp.swift`.
2. Add menu items:
   - New Session
   - Open Project
   - Settings
   - Show Logs
   - Reload Window
   - Quit
3. Add `applicationShouldHandleReopen` so clicking the Dock icon reopens the main window.
4. Use `NSOpenPanel` in Swift for `Open Project`.
5. Send the selected folder to the backend via `POST /api/projects`.
6. Navigate the WebView to the selected project route or notify the frontend through a bridge endpoint.
7. Add a small bridge endpoint if needed, for example:

```text
POST /api/app/native-action
GET  /api/app/state
```

8. Keep backend termination in `applicationWillTerminate`.

Acceptance:

- `Mcode.app` has native menu items.
- `Open Project` uses an actual macOS folder picker.
- Selecting a folder creates or focuses a project.
- Dock icon click reopens the window after it has been closed.
- `Show Logs` opens the Application Support log file.
- Quitting the app terminates the bundled backend process.

Verification:

- `mcode-ui/macos/build_app.sh`
- `plutil -lint mcode-ui/dist/Mcode.app/Contents/Info.plist`
- `codesign --verify --deep --strict mcode-ui/dist/Mcode.app`
- Open the app and manually test each menu item.

### Phase 2B: Credentials and Keychain

The current implementation stores API keys in:

```text
macOS Keychain
```

The app keeps `~/Library/Application Support/Mcode/.env` and project `.env` as fallback paths for development and CI, but the product path is Keychain-first.

Goals:

- Settings UI lets user enter DeepSeek API key.
- Native bridge or backend helper writes to Keychain.
- Backend loads credentials from Keychain first, then `.env` as fallback.
- Never store secrets in `projects.json`.

Recommended implementation:

1. Add a small Swift credential bridge using Security.framework:
   - `SecItemAdd`
   - `SecItemUpdate`
   - `SecItemCopyMatching`
   - `SecItemDelete`
2. Expose it to the WebView/backend through one of:
   - Swift launches backend with `DEEPSEEK_API_KEY` loaded from Keychain.
   - Swift exposes local bridge endpoints.
   - Backend calls `/usr/bin/security` as a fallback for development.
3. Keep `.env` fallback for development and CI.
4. Update Settings UI copy from “saved in app env” to “saved securely on this Mac”.
5. Keep API responses as status-only:

```json
{"api_key_configured": true}
```

Acceptance:

- Saving a key writes to Keychain.
- Clearing a key removes the Keychain item.
- API responses never include the key.
- App still works if only `.env` is present.
- Tests cover fallback behavior.

Status: implemented with Swift `Security.framework` startup loading, backend `/usr/bin/security` helper, `.env` fallback, and mocked/real smoke tests.

### Phase 2C: Speech Framework

Speech input should be native, not browser-only.

Goals:

- Add push-to-talk voice input for the composer.
- Use Apple's Speech framework and microphone permissions.
- Transcribe locally through native macOS APIs when available.
- Insert recognized text into the existing composer rather than creating a separate chat mode.

Implementation tasks:

1. Add frameworks to Swift compilation:

```text
-framework Speech
-framework AVFoundation
```

2. Add Info.plist usage descriptions:

```xml
<key>NSSpeechRecognitionUsageDescription</key>
<string>Mcode uses speech recognition to turn your voice into composer text.</string>
<key>NSMicrophoneUsageDescription</key>
<string>Mcode uses the microphone for voice input.</string>
```

3. Add native speech controller in Swift:
   - request authorization
   - start microphone capture with `AVAudioEngine`
   - stream audio into `SFSpeechAudioBufferRecognitionRequest`
   - stop on command or timeout
4. Bridge transcription to WebView:
   - `WKScriptMessageHandler` for frontend -> native commands
   - JavaScript event dispatch for native -> frontend transcript updates
5. Add frontend composer controls:
   - microphone icon button
   - recording state
   - permission/error state
   - insert recognized text into composer draft
6. Keep fallback state when Speech is unavailable.

Acceptance:

- Microphone button appears in composer only in native app mode.
- First use triggers macOS permission prompts.
- Recognized speech inserts text into the composer.
- Stopping recognition does not send automatically unless explicitly configured.
- Permission denied is shown as a recoverable UI state.

Status: implemented with `Speech` and `AVFoundation`, Info.plist permission strings, WebView bridge, composer microphone button, local-only toggle, and frontend transcript tests.

### Phase 2D: Backend Robustness

Add:

- Dynamic port selection.
- Backend health checks.
- Startup logs in Application Support.
- Better crash reporting in the app failure screen.
- Recovery when backend is already running or port is occupied.

Current Phase 1 already implements dynamic port selection, health checks, and logs. Phase 2D should improve recovery and diagnostics:

1. Detect backend process exit and show a restart UI.
2. Add a native “Restart Backend” menu item.
3. Include last log lines in the startup failure screen.
4. If the selected port becomes occupied before launch, choose another port and retry.
5. Add backend version/build metadata:

```text
GET /api/app/about
```

Acceptance:

- Backend crash does not leave the UI silently stale.
- User can restart backend from the menu.
- Failure screen includes actionable log tail.
- Health endpoint includes app/backend version.

Status: implemented for menu restart, process termination detection, log-tail failure screen, and `/api/app/about`.

## Phase 3: Runtime and UX Improvements

### Running-Turn Semantics

Implement the plan from `MCODE_CODEX_GAP_AND_TURN_QUEUE_PLAN.md`:

- Guide current run.
- Queue next turn.
- Interrupt and replace.

This is important for Codex-style interaction because the composer should remain useful while the agent is running.

### Session Isolation

Current controller uses a global cwd lock to protect project-local execution. This is safe for phase 1, but it limits concurrency.

Long-term options:

- Run each project/session in a worker process.
- Avoid global `os.chdir` and pass explicit cwd into all tools.
- Keep per-session lifecycle state durable.
- Allow multiple projects to run without blocking each other.

### Release Flow

Add:

- Ad-hoc signing for local builds.
- Developer ID signing for distribution.
- Notarization.
- Zip or DMG packaging.
- Versioned app bundle metadata.
- Optional update manifest later.

## UI Direction

Mcode should stay close to Codex-style workbench UI:

```text
Left sidebar
  Projects
  Sessions
  Run/test shortcuts

Center workspace
  Transcript
  Collapsible thinking/tool process
  Final answer
  Change review cards
  Composer

Right inspector
  Files
  Terminal
  Events
  Subagents
  Settings
  Browser/side chat later
```

### Visual Style

- Quiet, dense, macOS-native feeling.
- Light neutral background.
- Navy/cyan brand accents used sparingly.
- No marketing hero layout.
- No large decorative gradients.
- No nested card-heavy layout.
- Composer is the strongest surface.
- Inspector is compact and utilitarian.

### Immediate UI Cleanup

- Remove remaining legacy `Mini Agent Lab` text from user-facing UI.
- Use the Mcode logo consistently.
- Keep left sidebar as navigation, not branding-heavy decoration.
- Make right dock tabs more compact.
- Keep tool cards collapsible.
- Keep change review cards visually prominent.
- Ensure text fits in all buttons and tabs.

## Proposed Implementation Order

### Done: Phase 1 Local App

Completed:

1. Build frontend with Vite.
2. Serve `frontend/dist` from FastAPI.
3. Update Swift launcher to start only backend.
4. Copy built assets and backend resources into `Mcode.app`.
5. Move app-level state to Application Support.
6. Add Settings API key storage in app-local `.env`.

Current acceptance:

- No manual `npm run dev`.
- No manual `uvicorn`.
- Double-click app opens Mcode.
- `/api/health` works.
- Existing projects/sessions load.
- API key can be configured from Settings.
- Product acceptance passes 11/11.

### Done: Phase 2A Native Shell

Implemented:

1. Native menu bar.
2. `NSOpenPanel` open project flow.
3. Dock reopen behavior.
4. Show logs action.
5. New session action.
6. Window title updates.

Why it mattered:

- It gives the strongest native macOS feel.
- It is low risk compared with Keychain and Speech.
- It creates the native bridge surface needed by later features.

### Then: Phase 2B Keychain

Move API key storage from app-local `.env` to Keychain while keeping `.env` fallback.

Recommended work:

1. Add Swift Security.framework helper.
2. Load Keychain credential before launching backend.
3. Save/clear Keychain credential from Settings.
4. Keep API responses status-only.

Status: implemented.

### Then: Phase 2C Speech Input

Add native voice input to the composer.

Recommended work:

1. Add Speech and AVFoundation frameworks.
2. Add Info.plist permission strings.
3. Add Swift speech recognizer.
4. Add WKWebView bridge.
5. Add composer microphone button and recording state.

Status: implemented.

### Then: Phase 2D Backend Recovery

Improve failure and restart behavior.

Recommended work:

1. Detect backend process exit.
2. Add restart backend menu item.
3. Show log tail in failure UI.
4. Add `/api/app/about`.

Status: implemented.

### Phase 3: Runtime and Release

After Phase 2:

1. Running-turn guide/queue/interrupt.
2. Worker process isolation.
3. Backend sidecar packaging.
4. Signing and notarization.
5. DMG or zip release artifact.

## Key Files

Phase 1 files:

- `mcode-ui/backend/app.py`
- `mcode-ui/backend/project_store.py`
- `mcode-ui/backend/runtime.py`
- `mcode-ui/backend/settings_api.py`
- `mcode-ui/macos/McodeApp.swift`
- `mcode-ui/macos/build_app.sh`
- `mcode-ui/macos/Info.plist`
- `mcode-ui/frontend/src/App.tsx`
- `mcode-ui/frontend/src/components/ChatWorkspace.tsx`
- `mcode-ui/frontend/src/components/ProjectSidebar.tsx`
- `mcode-ui/frontend/src/components/SettingsPanel.tsx`
- `mcode-ui/frontend/src/styles.css`

Phase 2A files:

- `mcode-ui/macos/McodeApp.swift`
- `mcode-ui/macos/Info.plist`
- `mcode-ui/backend/app.py`
- `mcode-ui/backend/project_store.py`
- `mcode-ui/frontend/src/api/client.ts`
- `mcode-ui/frontend/src/App.tsx`
- `mcode-ui/frontend/src/components/ProjectSidebar.tsx`

Phase 2B files:

- `mcode-ui/macos/McodeApp.swift`
- `mcode-ui/backend/settings_api.py`
- `mcode-ui/frontend/src/components/SettingsPanel.tsx`
- `mcode-ui/backend/test_settings_api.py`

Phase 2C files:

- `mcode-ui/macos/McodeApp.swift`
- `mcode-ui/macos/Info.plist`
- `mcode-ui/frontend/src/components/Composer.tsx`
- `mcode-ui/frontend/src/components/ChatWorkspace.tsx`
- `mcode-ui/frontend/src/api/client.ts`
- `mcode-ui/frontend/src/styles.css`

## Risks

### Python Packaging

Python sidecar packaging is the largest practical risk.

Mitigation:

- Do phase 1 with source-backed local Python.
- Stabilize backend/static frontend first.
- Package backend only after app launch flow works.

### Working Directory

The agent currently relies on controlled cwd switching.

Mitigation:

- Keep phase 1 single backend process and one active turn per session.
- Move to worker processes later.

### File Permissions

The app needs to access arbitrary project folders.

Mitigation:

- Start unsandboxed for local builds.
- Use native folder picker and bookmark/security-scoped access later if sandboxing is required.

### Secrets

`.env` is acceptable for development but not polished for desktop.

Mitigation:

- Keep `.env` fallback.
- Add Keychain support in phase 2.

## Verification Checklist

Always run after macOS app work:

- `python3 tests/test_ui_backend.py`
- `python3 mcode-ui/backend/test_settings_api.py`
- `npm run test -- --run` in `mcode-ui/frontend`
- `npm run build` in `mcode-ui/frontend`
- `python3 scripts/product_acceptance.py`
- `mcode-ui/macos/build_app.sh`
- `plutil -lint mcode-ui/dist/Mcode.app/Contents/Info.plist`
- `codesign --verify --deep --strict mcode-ui/dist/Mcode.app`

Phase 1 checks already covered:

- `npm run build` succeeds in `mcode-ui/frontend`.
- Backend serves `index.html`.
- Backend API routes still work.
- Swift app starts backend.
- WebView loads app URL.
- Existing project list appears.
- New session can be created.
- A simple message can be sent.
- Approval flow still appears.
- File tree and event dock still load.
- App quits and child backend process terminates.

Phase 2A checks:

- Logs are visible and useful.
- App can open a selected folder.
- Menu items trigger the expected native actions.
- Dock reopen behavior restores the main window.
- Window title reflects current project/session when possible.

Phase 2B checks:

- API key can be set without editing `.env`.
- Keychain write/read/clear works.
- `.env` fallback still works.
- Settings responses never include secret values.

Phase 2C checks:

- Speech permission prompts appear on first use.
- Denied permission is recoverable.
- Voice transcription inserts text into composer.
- Recording can be stopped without sending the message.

Phase 2D checks:

- App survives backend startup failure with a clear message.
- Backend crash is detected.
- Restart backend action works.
- Failure screen includes useful log tail.

## Recommendation

Run a final completion audit against Phase 2A-2D and the layout/speech plan. Once verified, move to Phase 3: running-turn guide/queue/interrupt, worker isolation, backend sidecar packaging, signing, notarization, and release artifacts.
