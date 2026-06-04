import Foundation
import Combine

/// Top-level coordinator that wires together the filter controller, the lag-switch
/// engine, and the global hotkey listener, and owns the editable config. Views
/// observe this object.
@MainActor
final class AppModel: ObservableObject {
    let filter = FilterController()
    let engine = LagSwitchEngine()
    let hotkeys = HotkeyManager()

    @Published var config: AppConfig {
        didSet { engine.config = config }
    }
    @Published var runningApps: [AppTarget] = []
    @Published var accessibilityDenied = false
    @Published var capturingHotkey = false

    init() {
        // Auto-load the first saved config, like the Windows app does.
        config = ConfigStore.shared.loadFirst() ?? .default
        engine.config = config

        hotkeys.onPress = { [weak self] in self?.engine.hotkeyPressed() }
        hotkeys.onRelease = { [weak self] in self?.engine.hotkeyReleased() }
        hotkeys.onPermissionDenied = { [weak self] in self?.accessibilityDenied = true }
        hotkeys.setBinding(config.hotkey)
    }

    func start() {
        refreshApps()
        hotkeys.start()
        engine.pushTargets()
        Task { await filter.refreshStatus() }
    }

    func refreshApps() {
        runningApps = ProcessLister.runningApps()
    }

    // MARK: - Target selection

    func isSelected(_ app: AppTarget) -> Bool {
        config.targets.contains { $0.bundleID == app.bundleID }
    }

    func toggleSelection(_ app: AppTarget) {
        if let idx = config.targets.firstIndex(where: { $0.bundleID == app.bundleID }) {
            config.targets.remove(at: idx)
        } else {
            config.targets.append(app)
        }
        engine.config = config
        engine.pushTargets()
    }

    // MARK: - Hotkey rebind

    func beginCaptureHotkey() {
        capturingHotkey = true
        hotkeys.captureNext = { [weak self] descriptor in
            guard let self = self else { return }
            self.config.hotkey = descriptor
            self.hotkeys.setBinding(descriptor)
            self.capturingHotkey = false
        }
    }

    // MARK: - Config persistence

    func saveConfig(named name: String) {
        try? ConfigStore.shared.save(config, name: name)
    }

    func loadConfig(named name: String) {
        guard let loaded = ConfigStore.shared.load(name: name) else { return }
        config = loaded
        engine.config = loaded
        hotkeys.setBinding(loaded.hotkey)
        engine.pushTargets()
    }

    var savedConfigNames: [String] { ConfigStore.shared.list() }
}
