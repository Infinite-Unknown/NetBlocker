import Foundation
import NetworkExtension
import SystemExtensions
import os.log

/// Drives the content-filter system extension: installs/activates it the first
/// time, then enables it through `NEFilterManager`. Once running, the actual
/// per-flow drop decisions happen in the extension; this class only manages
/// lifecycle and surfaces status to the UI.
@MainActor
final class FilterController: NSObject, ObservableObject {

    enum Status: Equatable {
        case unknown
        case needsApproval      // user must approve the system extension in System Settings
        case installing
        case ready              // installed + enabled, filtering active
        case disabled           // installed but filter turned off
        case failed(String)
    }

    @Published private(set) var status: Status = .unknown

    private let log = OSLog(subsystem: "com.infiniteunknown.netblocker", category: "controller")

    // MARK: - Activation

    /// Request installation/activation of the bundled system extension.
    /// Triggers a user approval prompt on first run (System Settings → Privacy).
    func activate() {
        status = .installing
        let request = OSSystemExtensionRequest.activationRequest(
            forExtensionWithIdentifier: NetBlockerIDs.extensionBundleID,
            queue: .main
        )
        request.delegate = self
        OSSystemExtensionManager.shared.submitRequest(request)
    }

    /// Configure and enable the network filter once the extension is approved.
    func enableFilter() async {
        let manager = NEFilterManager.shared()
        do {
            try await manager.loadFromPreferences()
        } catch {
            os_log("loadFromPreferences failed: %{public}@", log: log, type: .error, error.localizedDescription)
        }

        if manager.providerConfiguration == nil {
            let config = NEFilterProviderConfiguration()
            config.filterDataProviderBundleIdentifier = NetBlockerIDs.extensionBundleID
            config.filterPackets = false
            config.filterSockets = true
            manager.providerConfiguration = config
            manager.localizedDescription = "NetBlocker"
        }
        manager.isEnabled = true

        do {
            try await manager.saveToPreferences()
            status = .ready
        } catch {
            status = .failed(error.localizedDescription)
            os_log("saveToPreferences failed: %{public}@", log: log, type: .error, error.localizedDescription)
        }
    }

    /// Turn the filter off without uninstalling the extension.
    func disableFilter() async {
        let manager = NEFilterManager.shared()
        try? await manager.loadFromPreferences()
        manager.isEnabled = false
        try? await manager.saveToPreferences()
        status = .disabled
    }

    /// Refresh `status` from the current NEFilterManager state.
    func refreshStatus() async {
        let manager = NEFilterManager.shared()
        try? await manager.loadFromPreferences()
        if manager.providerConfiguration == nil {
            status = .unknown
        } else {
            status = manager.isEnabled ? .ready : .disabled
        }
    }
}

// MARK: - OSSystemExtensionRequestDelegate

extension FilterController: OSSystemExtensionRequestDelegate {
    nonisolated func request(_ request: OSSystemExtensionRequest,
                             actionForReplacingExtension existing: OSSystemExtensionProperties,
                             withExtension ext: OSSystemExtensionProperties) -> OSSystemExtensionRequest.ReplacementAction {
        .replace // always take the version bundled in this app
    }

    nonisolated func requestNeedsUserApproval(_ request: OSSystemExtensionRequest) {
        Task { @MainActor in self.status = .needsApproval }
    }

    nonisolated func request(_ request: OSSystemExtensionRequest,
                             didFinishWithResult result: OSSystemExtensionRequest.Result) {
        Task { @MainActor in
            if result == .completed {
                await self.enableFilter()
            } else {
                self.status = .needsApproval
            }
        }
    }

    nonisolated func request(_ request: OSSystemExtensionRequest, didFailWithError error: Error) {
        Task { @MainActor in self.status = .failed(error.localizedDescription) }
    }
}
