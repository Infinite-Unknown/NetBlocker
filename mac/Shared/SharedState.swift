import Foundation

/// Identifiers shared between the main app and the Network Extension.
/// These must stay in sync with the values in the .entitlements files and project.yml.
enum NetBlockerIDs {
    /// App Group container shared by the app and the filter extension.
    /// Must match `com.apple.security.application-groups` in both entitlement files.
    static let appGroup = "group.com.infiniteunknown.netblocker"

    /// Bundle identifier of the Network Extension (the content filter).
    static let extensionBundleID = "com.infiniteunknown.netblocker.FilterExtension"

    /// Darwin notification posted by the app whenever the shared block state changes.
    /// The extension listens for this to flip its in-memory verdict with low latency.
    static let stateChangedNotification = "com.infiniteunknown.netblocker.stateChanged"
}

/// Keys used in the shared App Group UserDefaults suite.
private enum Keys {
    static let blocked = "blocked"
    static let targetBundleIDs = "targetBundleIDs"
}

/// Thin wrapper around the App Group UserDefaults that both the app (writer)
/// and the extension (reader) use to exchange the current lag-switch state.
///
/// The hot path (toggling `blocked`) is paired with a Darwin notification so the
/// extension reacts immediately instead of polling. The target app list changes
/// rarely, so it just rides along in the same store.
struct SharedState {
    static let shared = SharedState()

    private let defaults: UserDefaults?

    init() {
        defaults = UserDefaults(suiteName: NetBlockerIDs.appGroup)
    }

    /// Whether outbound traffic for the target apps should currently be dropped.
    var blocked: Bool {
        get { defaults?.bool(forKey: Keys.blocked) ?? false }
        nonmutating set {
            defaults?.set(newValue, forKey: Keys.blocked)
        }
    }

    /// Bundle identifiers of the apps whose outbound traffic we manage.
    var targetBundleIDs: [String] {
        get { defaults?.stringArray(forKey: Keys.targetBundleIDs) ?? [] }
        nonmutating set {
            defaults?.set(newValue, forKey: Keys.targetBundleIDs)
        }
    }

    /// Persist `blocked` and wake the extension via a Darwin notification.
    /// Called by the app on every hotkey transition and auto-refresh tick.
    func setBlocked(_ value: Bool) {
        blocked = value
        defaults?.synchronize()
        postStateChanged()
    }

    /// Persist the target list and notify the extension to re-read it.
    func setTargets(_ ids: [String]) {
        targetBundleIDs = ids
        defaults?.synchronize()
        postStateChanged()
    }

    /// Broadcast a cross-process Darwin notification. Free, async, no payload.
    func postStateChanged() {
        let name = CFNotificationName(NetBlockerIDs.stateChangedNotification as CFString)
        CFNotificationCenterPostNotification(
            CFNotificationCenterGetDarwinNotifyCenter(),
            name, nil, nil, true
        )
    }
}
