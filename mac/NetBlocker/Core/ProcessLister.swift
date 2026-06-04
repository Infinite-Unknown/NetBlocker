import AppKit

/// Enumerates user-facing running applications, the macOS analogue of the
/// Windows app's psutil process list. We list GUI apps (those with a bundle ID),
/// because the network filter matches on the signing/bundle identifier.
enum ProcessLister {
    static func runningApps() -> [AppTarget] {
        NSWorkspace.shared.runningApplications
            .filter { $0.activationPolicy == .regular } // visible apps with a Dock icon
            .compactMap { app -> AppTarget? in
                guard let bundleID = app.bundleIdentifier else { return nil }
                let name = app.localizedName ?? bundleID
                let path = app.bundleURL?.path ?? ""
                return AppTarget(bundleID: bundleID, name: name, path: path)
            }
            .reduce(into: [AppTarget]()) { acc, target in
                if !acc.contains(where: { $0.bundleID == target.bundleID }) { acc.append(target) }
            }
            .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }
}
