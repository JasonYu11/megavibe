# Mcode Codex Layout And Speech Plan

## Scope

This plan borrows the parts of Codex that improve day-to-day workbench ergonomics without adding the Goal system yet. Goal tracking should wait until it has its own backend state model, queue semantics, and tests.

Included:

- Hideable left project/session sidebar.
- Hideable right workspace dock.
- Resizable three-column layout.
- Conversation top-right artifacts entry.
- Composer tool area for attachments, plan, model, permissions, plugins, and voice.
- macOS Speech framework investigation for voice-to-text.

Excluded for now:

- Goal mode.
- Long-running goal persistence.
- Automatic queued goal execution.
- Full plugin marketplace.
- Full offline Whisper/MLX speech model.

## Current App State

The app has changed since this plan was first written. The active UI is now under `mcode-ui/`; the old `mini-agent-ui/` tree appears to have been replaced by the new Mcode app tree.

Observed current state:

- `mcode-ui/frontend/src/App.tsx` owns the main three-panel shell state.
- `mcode-ui/frontend/src/components/ProjectSidebar.tsx` is the left project/session sidebar.
- `mcode-ui/frontend/src/components/ChatWorkspace.tsx` is the central conversation surface.
- `mcode-ui/frontend/src/components/WorkspaceDock.tsx` is the right dock.
- `WorkspaceDock` already has tabs for Files, Terminal, Browser, Events, Subagents, Settings, and Side Chat.
- `Composer` already has attachments, Plan mode, model selection, thinking-mode presets, permission mode, and send/cancel.
- `TerminalPanel` and file open-in-IDE behavior are already part of the current app direction.
- `mcode-ui/macos/McodeApp.swift` is now a real native macOS wrapper that launches the FastAPI backend on a local port and loads the built frontend in `WKWebView`.

Not yet observed in the current code:

- Manual left sidebar collapse on desktop.
- Manual right dock collapse on desktop.
- Draggable resizing between the three columns.
- Conversation-header artifacts popover.
- Composer plugin/capability menu.
- Composer microphone button.
- Native Speech framework permissions or Swift speech bridge.

Important working-tree note:

- The repository is currently in a large migration state: `mini-agent-ui/` files are deleted, `mcode-ui/` is untracked, and config/policy files appear to have been renamed to `mcode-*`.
- Any implementation should avoid touching unrelated migration files unless the branch intentionally commits the full rename.

## Codex Patterns To Borrow

### 1. Hideable Sidebars

Codex lets the user collapse side panels so the main work surface can breathe. Mcode should support:

- Collapse left sidebar into a narrow rail or hidden state.
- Collapse right dock into a single icon button.
- Restore each panel independently.
- Remember collapsed state per device in `localStorage`.

Initial UI controls:

- Top-left sidebar toggle.
- Top-right dock toggle.
- Keyboard shortcuts later, after layout behavior is stable.

Acceptance criteria:

- A user can hide the left sidebar without losing the current session.
- A user can hide the right dock without losing selected dock tab state.
- Reload restores the last collapsed/expanded layout.

### 2. Resizable Three-Column Layout

The current three-column layout should become adjustable:

```text
[project/session sidebar] | [conversation/work area] | [workspace dock]
```

Implementation direction:

- Use CSS grid with column widths controlled by React state.
- Add drag handles between left/main and main/right.
- Clamp sizes to avoid unusable layouts.
- Persist widths in `localStorage`.
- Implement the helpers as small pure functions first, then wire them into `App.tsx`.
- Keep the current mobile behavior where the sidebar disappears below 820px.

Suggested constraints:

- Left sidebar: 220px to 360px.
- Main area: minimum 460px.
- Right dock: 300px to 560px.
- On narrow screens, prefer overlay/collapse instead of squeezing all columns.

Acceptance criteria:

- Dragging a divider updates layout smoothly.
- Layout cannot collapse text or controls into unusable widths.
- Widths survive reload.
- Tests cover persisted layout parsing and clamp behavior.

### 3. Artifacts Entry In Conversation Header

Codex surfaces generated outputs near the conversation header. Mcode should add a compact "Artifacts" button at the top-right of the conversation header.

Artifact sources:

- Generated files from git classification.
- Modified files.
- File previews opened during the run.
- Browser URLs.
- Terminal sessions and command summaries.
- Images and screenshots.
- Final answer references.

Initial implementation:

- Add an artifacts button in `ChatWorkspace` header.
- Show a popover grouped by type: Files, Browser, Terminal, Images, Reports.
- Populate from run summary first; avoid inventing a new artifact database in phase 1.

Later implementation:

- Add an artifact event type to `RunRecorder`.
- Allow pinning artifacts.
- Allow "open in dock", "open in IDE", and "copy path".

Acceptance criteria:

- A generated file appears in artifacts after an agent run.
- Clicking a file artifact opens the file preview or external IDE action.
- Empty state is quiet and does not distract.

### 4. Composer Tool Area

Codex keeps action controls near the input because they change the meaning of the next request. Mcode should keep this pattern.

Current Mcode controls:

- Attachments.
- Plan.
- Model selector.
- Thinking-mode presets through the model selector.
- Permission selector.

Add next:

- Plugin menu.
- Voice input button.
- Optional compact mode when space is narrow.

Do not add Goal yet.

Plugin menu phase 1:

- Show installed/available local capabilities as a read-only menu.
- Group by: Browser, Chrome, Documents, Spreadsheets, Presentations, Build Web Apps, Build iOS Apps, Build macOS Apps, and local Mcode tools.
- Let users see what is available before we allow per-turn plugin enabling/disabling.
- Do not imply that a plugin can be toggled per turn until the backend supports that contract.

Voice button phase 1:

- Add microphone icon to composer.
- If native speech is not implemented, show a small tip: use macOS Dictation or enable experimental native speech.
- Keep text insertion behavior simple: recognized text appends to composer draft.

Acceptance criteria:

- Composer remains usable at 380px width.
- Long model/plugin names ellipsize without layout shift.
- Menu popovers stay inside viewport.

## macOS Speech Framework Difficulty

### Short Answer

Integrating Apple Speech framework is medium difficulty if Mcode keeps its current WebView wrapper and only needs "press mic, speak, insert text into composer". It becomes high difficulty if we need full offline guarantees, long-form transcription, punctuation cleanup, speaker diarization, or system-wide dictation.

### Why It Is Feasible

Apple provides a native Speech framework for recognizing live or recorded audio. A macOS Swift wrapper can capture microphone audio through `AVAudioEngine`, feed it into `SFSpeechAudioBufferRecognitionRequest`, and receive partial/final transcripts from `SFSpeechRecognizer`.

Useful Apple docs:

- https://developer.apple.com/documentation/speech/
- https://developer.apple.com/documentation/Speech/recognizing-speech-in-live-audio
- https://developer.apple.com/documentation/speech/sfspeechrecognizer/supportsondevicerecognition
- https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition

### Main Native Requirements

The macOS app needs:

- Microphone usage permission.
- Speech recognition permission.
- `NSSpeechRecognitionUsageDescription` in `Info.plist`.
- `NSMicrophoneUsageDescription` in `Info.plist`.
- Swift bridge from native code to WebView JavaScript.
- UI state for recording, partial transcript, final transcript, cancel.

Current native status:

- `mcode-ui/macos/McodeApp.swift` already creates an `NSWindow`, hosts `WKWebView`, starts the backend, chooses a local port, writes backend logs, and loads the app URL.
- `mcode-ui/macos/Info.plist` includes local networking, microphone, and speech-recognition permission descriptions.
- `McodeApp.swift` includes a `WKScriptMessageHandler` bridge and a native `SpeechController`.
- The composer can send `mcode:speech-request` events, including a persisted "Local" on-device preference.
- Native speech results return through `mcode:speech-transcript` and final transcripts are inserted into the composer draft.

### On-Device Recognition

Apple supports checking `SFSpeechRecognizer.supportsOnDeviceRecognition`. If supported, set `request.requiresOnDeviceRecognition = true`.

Important limitation:

- Not every locale or environment supports on-device recognition.
- If on-device is not supported, the app either falls back to Apple server recognition or disables native speech for privacy.

Mcode should expose this clearly:

- "Local only" toggle.
- If local recognition is unsupported, show a short message instead of silently using network speech.

### Recommended Architecture

```text
Swift macOS wrapper
  AVAudioEngine microphone capture
  SFSpeechRecognizer recognition task
  WKWebView bridge
    window.mcodeSpeech.insertTranscript(text)
    window.mcodeSpeech.setRecordingState(state)

React frontend
  Composer mic button
  transcript preview
  append/replace composer text
```

Do not route raw audio through the Python backend in phase 1. Keep audio entirely in the native macOS layer.

### Difficulty Breakdown

Low difficulty:

- Add composer microphone button.
- Add UI states: idle, recording, transcribing, error.
- Append mock transcript to composer for frontend testing.

Medium difficulty:

- Swift `SFSpeechRecognizer` live transcription.
- WebView bridge into React.
- Permission prompts and error states.
- Partial result rendering.

High difficulty:

- Fully offline speech guarantee across locales.
- Long audio transcription.
- Accurate punctuation and formatting cleanup.
- Speaker diarization.
- Background/system-wide dictation.
- Whisper/MLX fallback.

## Phased Implementation

### Phase 0: Stabilize The Rename/Migration

- Decide whether the current `mini-agent-ui/` to `mcode-ui/` rename is ready to commit as one migration.
- Ensure frontend commands are run from `mcode-ui/frontend`.
- Ensure macOS build scripts point only at `mcode-ui`.
- Update docs and tests that still mention old `mini-agent-ui` paths.
- Keep `mcode-config*.json` and `mcode-policy*.json` naming consistent.

Deliverable:

- The repo has one canonical app path: `mcode-ui/`.

Status: implemented in the current Mcode tree; the Python import package remains `mini_agent_lab` for compatibility.

### Phase 1: Layout Ergonomics

- Add left sidebar collapse state.
- Add right dock collapse state.
- Add drag handles for left/main/right widths.
- Persist layout in `localStorage`.
- Add tests for clamp/persistence helpers.
- Files likely touched:
  - `mcode-ui/frontend/src/App.tsx`
  - `mcode-ui/frontend/src/styles.css`
  - new `mcode-ui/frontend/src/layoutState.ts`
  - `mcode-ui/frontend/src/components/ProjectSidebar.tsx`
  - `mcode-ui/frontend/src/components/WorkspaceDock.tsx`

Deliverable:

- Mcode feels less crowded and can focus on the conversation or file preview.

Status: implemented with `layoutState.ts`, persisted column widths, collapsible sidebars, and frontend tests.

### Phase 2: Artifacts Popover

- Add conversation header artifacts button.
- Build artifacts from current run summary.
- Link file artifacts to preview/open-in-IDE.
- Link browser artifacts to Browser dock.
- Files likely touched:
  - `mcode-ui/frontend/src/components/ChatWorkspace.tsx`
  - new `mcode-ui/frontend/src/components/ArtifactsPopover.tsx`
  - `mcode-ui/frontend/src/types.ts`
  - `mcode-ui/frontend/src/state/events.ts`

Deliverable:

- User can quickly answer: "What did the agent produce?"

Status: implemented for file artifacts derived from current change-review data.

### Phase 3: Composer Plugin Menu

- Add plugin/capability menu.
- Show installed capabilities as grouped read-only entries.
- Keep per-turn plugin activation out of scope until backend support exists.
- Files likely touched:
  - `mcode-ui/frontend/src/components/Composer.tsx`
  - new `mcode-ui/frontend/src/components/PluginMenu.tsx`

Deliverable:

- User understands what tools Mcode can use without entering settings.

Status: implemented as a read-only grouped capability menu in the composer.

### Phase 4: Speech UI Stub

- Add microphone button.
- Add recording states and transcript insertion contract.
- Add frontend tests with mocked transcript events.
- Do not require native speech to exist in this phase.
- Files likely touched:
  - `mcode-ui/frontend/src/components/Composer.tsx`
  - `mcode-ui/frontend/src/types.ts`
  - `mcode-ui/frontend/src/components/ChatWorkspace.tsx`

Deliverable:

- UI is ready for native speech without requiring Swift implementation immediately.

Status: implemented and covered by mocked frontend transcript tests.

### Phase 5: Native Speech Framework

- Add macOS permissions to `Info.plist`.
- Implement Swift speech controller.
- Bridge recognized text into WebView.
- Add "local only" setting.
- Handle unsupported locale/network/permission errors.
- Files likely touched:
  - `mcode-ui/macos/Info.plist`
  - `mcode-ui/macos/McodeApp.swift`
  - possible new `mcode-ui/macos/SpeechController.swift`

Deliverable:

- User can dictate a prompt directly into Mcode on macOS.

Status: implemented in the native wrapper with Speech/AVFoundation, WebView bridge, permission strings, local-only handling, and frontend transcript insertion.

## Engineering Risks

- Resizable layout can create text overflow if column clamps are weak.
- Sidebar collapse can hide important status if no compact rail exists.
- Artifacts can become noisy if every internal run file is shown.
- Plugin menus can imply functionality that is not actually toggleable yet.
- Speech recognition permissions can fail silently if native error handling is thin.
- On-device speech support varies, so the UI must not promise full offline transcription until verified.

## Recommended Next Step

Run final verification and completion audit against this plan and the macOS native app plan. After that, move to Phase 3 runtime semantics and release packaging work.
