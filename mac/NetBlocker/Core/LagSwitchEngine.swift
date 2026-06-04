import Foundation
import Combine

/// The app-side state machine that translates hotkey events into block on/off
/// decisions and writes them to the shared store the extension reads. This is
/// the macOS reimplementation of the Windows app's hotkey-mode logic
/// (Hold / Toggle / Charge / Tap Charge) plus auto-refresh.
@MainActor
final class LagSwitchEngine: ObservableObject {

    /// Whether outbound traffic for the targets is currently being dropped.
    @Published private(set) var isBlocking = false
    /// True during the cooldown after a charge burst.
    @Published private(set) var isCharging = false

    var config: AppConfig = .default {
        didSet { pushTargets() }
    }

    private var refreshTimer: Timer?
    private var chargeTimer: Timer?
    private var cooldownTimer: Timer?

    // MARK: - Target sync

    /// Publish the selected bundle IDs to the extension.
    func pushTargets() {
        SharedState.shared.setTargets(config.targets.map(\.bundleID))
    }

    // MARK: - Hotkey entry points (wired to HotkeyManager)

    func hotkeyPressed() {
        switch config.mode {
        case .hold:
            startBlocking()
        case .toggle:
            isBlocking ? stopBlocking() : startBlocking()
        case .charge:
            startCharge()
        case .tapCharge:
            if isBlocking {
                if config.tapCancelEnabled { cancelCharge() }
            } else {
                startCharge()
            }
        }
    }

    func hotkeyReleased() {
        if config.mode == .hold {
            stopBlocking()
        }
    }

    // MARK: - Core block control

    private func startBlocking() {
        guard !isBlocking else { return }
        isBlocking = true
        SharedState.shared.setBlocked(true)
        if config.autoRefreshEnabled { startAutoRefresh() }
    }

    private func stopBlocking() {
        guard isBlocking else { return }
        isBlocking = false
        SharedState.shared.setBlocked(false)
        stopAutoRefresh()
    }

    // MARK: - Charge mode

    /// A timed burst: block for autoRefreshMs, then enter a chargeDelayMs cooldown.
    private func startCharge() {
        guard !isBlocking && !isCharging else { return }
        startBlocking()
        chargeTimer?.invalidate()
        chargeTimer = Timer.scheduledTimer(withTimeInterval: Double(config.autoRefreshMs) / 1000.0,
                                           repeats: false) { [weak self] _ in
            Task { @MainActor in self?.endCharge() }
        }
    }

    private func endCharge() {
        stopBlocking()
        isCharging = true
        cooldownTimer?.invalidate()
        cooldownTimer = Timer.scheduledTimer(withTimeInterval: Double(config.chargeDelayMs) / 1000.0,
                                             repeats: false) { [weak self] _ in
            Task { @MainActor in self?.isCharging = false }
        }
    }

    private func cancelCharge() {
        chargeTimer?.invalidate()
        stopBlocking()
        isCharging = false
    }

    // MARK: - Auto refresh

    /// Periodically flips block off→on so long-lived server connections don't
    /// fully time out during a sustained block (the "keep-alive" behavior).
    private func startAutoRefresh() {
        stopAutoRefresh()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: Double(config.autoRefreshMs) / 1000.0,
                                            repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self = self, self.isBlocking else { return }
                // brief unblock pulse, then re-block
                SharedState.shared.setBlocked(false)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.03) {
                    if self.isBlocking { SharedState.shared.setBlocked(true) }
                }
            }
        }
    }

    private func stopAutoRefresh() {
        refreshTimer?.invalidate()
        refreshTimer = nil
    }
}
