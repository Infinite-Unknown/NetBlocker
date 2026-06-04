import Foundation

/// How the hotkey drives the lag switch. Mirrors the Windows app's modes.
enum HotkeyMode: String, Codable, CaseIterable, Identifiable {
    case hold       // blocked while the key is held, unblocks on release
    case toggle     // each press flips block on/off
    case charge     // press starts a timed burst, auto-stops after autoRefreshMs
    case tapCharge  // tap to start a timed burst; tap again to cancel (if enabled)

    var id: String { rawValue }

    var label: String {
        switch self {
        case .hold: return "Hold"
        case .toggle: return "Toggle"
        case .charge: return "Charge"
        case .tapCharge: return "Tap Charge"
        }
    }
}

/// A selectable running application, identified by bundle ID (what the network
/// filter matches on) plus a display name and path for the UI.
struct AppTarget: Codable, Identifiable, Hashable {
    var bundleID: String
    var name: String
    var path: String

    var id: String { bundleID }
}

/// Persisted configuration. JSON-compatible, mirroring the Windows config schema
/// where it makes sense. Stored in Application Support / loaded on launch.
struct AppConfig: Codable {
    var targets: [AppTarget] = []
    var hotkey: HotkeyDescriptor = .init(keyCode: 63, displayName: "fn")
    var mode: HotkeyMode = .hold

    var autoRefreshEnabled: Bool = false
    var autoRefreshMs: Int = 600       // block duration before auto-release / refresh tick
    var chargeDelayMs: Int = 100       // cooldown after a charge burst
    var tapCancelEnabled: Bool = false

    static let `default` = AppConfig()
}

/// Loads and saves named configs as JSON files, like the Windows app's
/// net_blocker_configs directory. The first saved config auto-loads on startup.
final class ConfigStore {
    static let shared = ConfigStore()

    private let fm = FileManager.default

    private var directory: URL {
        let base = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("NetBlocker/configs", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    func list() -> [String] {
        let files = (try? fm.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? []
        return files.filter { $0.pathExtension == "json" }
            .map { $0.deletingPathExtension().lastPathComponent }
            .sorted()
    }

    func save(_ config: AppConfig, name: String) throws {
        let url = directory.appendingPathComponent("\(name).json")
        let data = try JSONEncoder().encode(config)
        try data.write(to: url, options: .atomic)
    }

    func load(name: String) -> AppConfig? {
        let url = directory.appendingPathComponent("\(name).json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(AppConfig.self, from: data)
    }

    func delete(name: String) {
        let url = directory.appendingPathComponent("\(name).json")
        try? fm.removeItem(at: url)
    }

    /// Loads the alphabetically-first saved config, if any, for auto-load on launch.
    func loadFirst() -> AppConfig? {
        guard let first = list().first else { return nil }
        return load(name: first)
    }
}
