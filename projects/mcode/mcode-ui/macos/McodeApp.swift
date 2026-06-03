import Cocoa
import AVFoundation
import Security
import Speech
import WebKit

private let keychainService = "local.mcode.app"
private let keychainAccount = "DEEPSEEK_API_KEY"

func readDeepSeekKeyFromKeychain() -> String {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: keychainService,
        kSecAttrAccount as String: keychainAccount,
        kSecReturnData as String: true,
        kSecMatchLimit as String: kSecMatchLimitOne
    ]
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    guard status == errSecSuccess, let data = item as? Data else {
        return ""
    }
    return String(data: data, encoding: .utf8) ?? ""
}

final class SpeechController {
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: Locale.current.identifier))

    func start(
        localOnly: Bool,
        onUpdate: @escaping (String, Bool) -> Void,
        onError: @escaping (String) -> Void
    ) {
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                guard status == .authorized else {
                    onError("Speech recognition permission was not granted.")
                    return
                }
                self?.startAuthorized(localOnly: localOnly, onUpdate: onUpdate, onError: onError)
            }
        }
    }

    func stop() {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
    }

    private func startAuthorized(
        localOnly: Bool,
        onUpdate: @escaping (String, Bool) -> Void,
        onError: @escaping (String) -> Void
    ) {
        stop()
        guard let recognizer else {
            onError("Speech recognizer is unavailable for the current locale.")
            return
        }
        if localOnly {
            if #available(macOS 10.15, *) {
                guard recognizer.supportsOnDeviceRecognition else {
                    onError("On-device speech recognition is not available for the current locale.")
                    return
                }
            } else {
                onError("On-device speech recognition requires a newer macOS version.")
                return
            }
        }
        let nextRequest = SFSpeechAudioBufferRecognitionRequest()
        nextRequest.shouldReportPartialResults = true
        if #available(macOS 10.15, *), localOnly {
            nextRequest.requiresOnDeviceRecognition = true
        }
        request = nextRequest

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            nextRequest.append(buffer)
        }
        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            inputNode.removeTap(onBus: 0)
            onError("Could not start microphone capture: \(error.localizedDescription)")
            return
        }

        task = recognizer.recognitionTask(with: nextRequest) { [weak self] result, error in
            if let result {
                onUpdate(result.bestTranscription.formattedString, result.isFinal)
            }
            if let error {
                self?.stop()
                onError(error.localizedDescription)
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var backend: Process?
    private var appURL: URL!
    private var healthURL: URL!
    private var logURL: URL!
    private var titleObservation: NSKeyValueObservation?
    private let speech = SpeechController()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildWindow()
        buildMenu()
        startBackendAndLoad()
    }

    func applicationWillTerminate(_ notification: Notification) {
        backend?.terminate()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        guard let window else { return true }
        if !flag {
            window.makeKeyAndOrderFront(nil)
        }
        NSApp.activate(ignoringOtherApps: true)
        return true
    }

    private func buildWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        let userContent = WKUserContentController()
        userContent.add(self, name: "mcodeSpeech")
        userContent.addUserScript(WKUserScript(
            source: """
            window.mcodeNativeSpeech = true;
            window.addEventListener('mcode:speech-request', function(event) {
              window.webkit.messageHandlers.mcodeSpeech.postMessage(event.detail || {});
            });
            """,
            injectionTime: .atDocumentEnd,
            forMainFrameOnly: true
        ))
        configuration.userContentController = userContent
        webView = WKWebView(frame: .zero, configuration: configuration)
        titleObservation = webView.observe(\.title, options: [.new]) { [weak self] webView, _ in
            let pageTitle = (webView.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            DispatchQueue.main.async {
                self?.window.title = pageTitle.isEmpty ? "Mcode" : pageTitle
            }
        }
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Mcode"
        window.center()
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "mcodeSpeech", let body = message.body as? [String: Any] else { return }
        let action = body["action"] as? String ?? "start"
        if action == "stop" {
            speech.stop()
            dispatchSpeechTranscript(text: "", final: true, error: "")
            return
        }
        let localOnly = body["localOnly"] as? Bool ?? false
        speech.start(
            localOnly: localOnly,
            onUpdate: { [weak self] text, final in
                self?.dispatchSpeechTranscript(text: text, final: final, error: "")
            },
            onError: { [weak self] error in
                self?.dispatchSpeechTranscript(text: "", final: true, error: error)
            }
        )
    }

    private func buildMenu() {
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Mcode", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Settings...", action: #selector(openSettings), keyEquivalent: ",")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Quit Mcode", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        let fileMenuItem = NSMenuItem()
        let fileMenu = NSMenu(title: "File")
        fileMenu.addItem(withTitle: "New Session", action: #selector(newSession), keyEquivalent: "n")
        fileMenu.addItem(withTitle: "Open Project...", action: #selector(openProject), keyEquivalent: "o")
        fileMenu.addItem(NSMenuItem.separator())
        fileMenu.addItem(withTitle: "Show Logs", action: #selector(showLogs), keyEquivalent: "l")
        fileMenu.addItem(withTitle: "Restart Backend", action: #selector(restartBackend), keyEquivalent: "b")
        fileMenu.addItem(withTitle: "Reload Window", action: #selector(reloadWindow), keyEquivalent: "r")
        fileMenuItem.submenu = fileMenu
        mainMenu.addItem(fileMenuItem)

        let editMenuItem = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)

        let windowMenuItem = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowMenu.addItem(NSMenuItem.separator())
        windowMenu.addItem(withTitle: "Bring All to Front", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        windowMenuItem.submenu = windowMenu
        mainMenu.addItem(windowMenuItem)
        NSApp.windowsMenu = windowMenu
        NSApp.mainMenu = mainMenu
    }

    @objc private func showAbout() {
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: "Mcode",
            .applicationVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1.0",
            .version: Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        ])
    }

    @objc private func newSession() {
        dispatchNativeAction("new-session")
    }

    @objc private func openSettings() {
        dispatchNativeAction("open-settings")
    }

    @objc private func showLogs() {
        guard let logURL else { return }
        if FileManager.default.fileExists(atPath: logURL.path) {
            NSWorkspace.shared.open(logURL)
        } else {
            NSWorkspace.shared.open(logURL.deletingLastPathComponent())
        }
    }

    @objc private func reloadWindow() {
        webView.reload()
    }

    @objc private func restartBackend() {
        backend?.terminationHandler = nil
        backend?.terminate()
        backend = nil
        startBackendAndLoad()
    }

    @objc private func openProject() {
        let panel = NSOpenPanel()
        panel.title = "Open Project"
        panel.prompt = "Open"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            self?.createProjectFromNative(url)
        }
    }

    private func startBackendAndLoad() {
        guard let resources = Bundle.main.resourceURL else {
            showStartupFailure("Mcode 启动失败", details: "无法定位 app resources。")
            return
        }
        let backendDir = resources.appendingPathComponent("backend", isDirectory: true)
        let frontendDist = resources.appendingPathComponent("frontend-dist", isDirectory: true)
        guard FileManager.default.fileExists(atPath: backendDir.path) else {
            showStartupFailure("Mcode 启动失败", details: "找不到 backend 目录：\(backendDir.path)")
            return
        }
        guard FileManager.default.fileExists(atPath: frontendDist.appendingPathComponent("index.html").path) else {
            showStartupFailure("Mcode 启动失败", details: "找不到 frontend-dist/index.html：\(frontendDist.path)")
            return
        }

        let appDataDir = applicationSupportDirectory()
        let logsDir = appDataDir.appendingPathComponent("logs", isDirectory: true)
        try? FileManager.default.createDirectory(at: logsDir, withIntermediateDirectories: true)
        logURL = logsDir.appendingPathComponent("backend.log")

        let port = choosePort()
        appURL = URL(string: "http://127.0.0.1:\(port)/")!
        healthURL = URL(string: "http://127.0.0.1:\(port)/api/health")!

        backend = launchBackend(
            port: port,
            backendDir: backendDir,
            runtimeRoot: resources,
            frontendDist: frontendDist,
            appDataDir: appDataDir
        )
        backend?.terminationHandler = { [weak self] process in
            guard process.terminationStatus != 0 else { return }
            DispatchQueue.main.async {
                self?.showStartupFailure(
                    "Mcode backend 已停止",
                    details: "backend 进程退出，退出码：\(process.terminationStatus)\n\n日志：\(self?.logURL.path ?? "")\n\n\(self?.logTail() ?? "")"
                )
            }
        }
        waitAndLoad()
    }

    private func launchBackend(
        port: Int,
        backendDir: URL,
        runtimeRoot: URL,
        frontendDist: URL,
        appDataDir: URL
    ) -> Process {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = [
            "python3",
            "-m",
            "uvicorn",
            "app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "\(port)"
        ]
        process.currentDirectoryURL = backendDir
        var environment = ProcessInfo.processInfo.environment.merging([
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONPATH": runtimeRoot.path,
            "MCODE_RUNTIME_ROOT": runtimeRoot.path,
            "MCODE_FRONTEND_DIST": frontendDist.path,
            "MCODE_APP_DATA_DIR": appDataDir.path
        ]) { _, new in new }
        let keychainKey = readDeepSeekKeyFromKeychain()
        if !keychainKey.isEmpty {
            environment["DEEPSEEK_API_KEY"] = keychainKey
        }
        process.environment = environment

        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        if let handle = try? FileHandle(forWritingTo: logURL) {
            process.standardOutput = handle
            process.standardError = handle
        }
        do {
            try process.run()
        } catch {
            showStartupFailure("Mcode 启动失败", details: "无法启动 backend：\(error)\n\n日志：\(logURL.path)")
        }
        return process
    }

    private func waitAndLoad() {
        DispatchQueue.global(qos: .userInitiated).async {
            for _ in 0..<120 {
                if self.isReachable(self.healthURL) {
                    DispatchQueue.main.async {
                        self.webView.load(URLRequest(url: self.appURL))
                    }
                    return
                }
                Thread.sleep(forTimeInterval: 0.25)
            }
            DispatchQueue.main.async {
                self.showStartupFailure(
                    "Mcode 启动失败",
                    details: "backend 未能在 30 秒内启动。\n\nURL：\(self.healthURL.absoluteString)\n日志：\(self.logURL.path)\n\n\(self.logTail())"
                )
            }
        }
    }

    private func createProjectFromNative(_ url: URL) {
        guard let appURL else { return }
        let name = url.lastPathComponent.isEmpty ? "Project" : url.lastPathComponent
        let body: [String: String] = ["name": name, "root_path": url.path]
        var request = URLRequest(url: appURL.appendingPathComponent("api/projects"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            if let error {
                self?.dispatchNativeAction("error", payload: ["message": "Open Project failed: \(error.localizedDescription)"])
                return
            }
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode), let data else {
                self?.dispatchNativeAction("error", payload: ["message": "Open Project failed: backend rejected \(url.path)"])
                return
            }
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let projectId = object?["id"] as? String ?? ""
            self?.dispatchNativeAction("project-opened", payload: ["projectId": projectId, "rootPath": url.path])
        }.resume()
    }

    private func dispatchNativeAction(_ type: String, payload: [String: String] = [:]) {
        var detail = payload
        detail["type"] = type
        let data = (try? JSONSerialization.data(withJSONObject: detail)) ?? Data()
        let json = String(data: data, encoding: .utf8) ?? "{}"
        DispatchQueue.main.async {
            self.window?.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            self.webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('mcode:native-action', { detail: \(json) }));")
        }
    }

    private func dispatchSpeechTranscript(text: String, final: Bool, error: String) {
        var detail: [String: Any] = ["text": text, "final": final]
        if !error.isEmpty {
            detail["error"] = error
        }
        let data = (try? JSONSerialization.data(withJSONObject: detail)) ?? Data()
        let json = String(data: data, encoding: .utf8) ?? "{}"
        DispatchQueue.main.async {
            self.webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('mcode:speech-transcript', { detail: \(json) }));")
        }
    }

    private func showStartupFailure(_ title: String, details: String) {
        let escapedTitle = htmlEscape(title)
        let escapedDetails = htmlEscape(details)
        let html = """
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body { font: 14px -apple-system, BlinkMacSystemFont, sans-serif; margin: 42px; color: #1d1f1c; background: #f7f7f4; }
            h1 { font-size: 22px; margin: 0 0 12px; }
            pre { white-space: pre-wrap; background: #fff; border: 1px solid #deded8; border-radius: 8px; padding: 14px; }
          </style>
        </head>
        <body>
          <h1>\(escapedTitle)</h1>
          <pre>\(escapedDetails)</pre>
          <button onclick="window.location.reload()">Reload Window</button>
        </body>
        </html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    private func logTail(maxLines: Int = 80) -> String {
        guard let logURL, let content = try? String(contentsOf: logURL, encoding: .utf8) else {
            return ""
        }
        return content.split(separator: "\n").suffix(maxLines).joined(separator: "\n")
    }

    private func applicationSupportDirectory() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support", isDirectory: true)
        let dir = base.appendingPathComponent("Mcode", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    private func choosePort() -> Int {
        for port in 18080..<18280 {
            if !isReachable(URL(string: "http://127.0.0.1:\(port)/api/health")!) {
                return port
            }
        }
        return 18080
    }

    private func isReachable(_ url: URL) -> Bool {
        var request = URLRequest(url: url)
        request.timeoutInterval = 0.35
        let semaphore = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: request) { _, response, _ in
            if let http = response as? HTTPURLResponse, (200..<500).contains(http.statusCode) {
                ok = true
            }
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 0.45)
        return ok
    }

    private func htmlEscape(_ text: String) -> String {
        text
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
