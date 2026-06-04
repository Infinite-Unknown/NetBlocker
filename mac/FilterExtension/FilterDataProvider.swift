import NetworkExtension
import os.log

/// Content-filter data provider. macOS routes every new network flow through
/// `handleNewFlow`. We keep flows belonging to the target apps under inspection
/// so that, while the lag switch is engaged, we can drop their outbound data —
/// including data on connections that were already open when the switch flipped.
///
/// State (which apps to target, and whether blocking is currently on) lives in
/// the shared App Group store. The app pokes us with a Darwin notification on
/// every change so we react without polling.
final class FilterDataProvider: NEFilterDataProvider {

    private let log = OSLog(subsystem: "com.infiniteunknown.netblocker", category: "filter")

    /// Cached copy of the shared state, refreshed on each Darwin notification.
    private var blocked = false
    private var targets = Set<String>()

    // MARK: - Lifecycle

    override func startFilter(completionHandler: @escaping (Error?) -> Void) {
        refreshState()
        registerForStateChanges()

        // Filter all outbound traffic; we narrow to target apps in handleNewFlow.
        let allTraffic = NENetworkRule(
            remoteNetwork: nil,
            remotePrefix: 0,
            localNetwork: nil,
            localPrefix: 0,
            protocol: .any,
            direction: .outbound
        )
        let rule = NEFilterRule(networkRule: allTraffic, action: .filterData)
        let settings = NEFilterSettings(rules: [rule], defaultAction: .allow)

        apply(settings) { error in
            if let error = error {
                os_log("Failed to apply filter settings: %{public}@", log: self.log, type: .error, error.localizedDescription)
            }
            completionHandler(error)
        }
    }

    override func stopFilter(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        unregisterForStateChanges()
        completionHandler()
    }

    // MARK: - Flow handling

    override func handleNewFlow(_ flow: NEFilterFlow) -> NEFilterNewFlowVerdict {
        guard isTarget(flow) else {
            // Not an app we manage — let it through and stop looking at it.
            return .allow()
        }

        // It's a target app. Keep inspecting its outbound bytes so we can switch
        // between drop/allow mid-connection as the lag switch toggles.
        // peekOutboundBytes is large enough that we get called back on activity.
        return .filterDataVerdict(
            withFilterInbound: false,
            peekInboundBytes: 0,
            filterOutbound: true,
            peekOutboundBytes: Int.max
        )
    }

    override func handleOutboundData(
        from flow: NEFilterFlow,
        readBytesStartOffset offset: Int,
        readBytes: Data
    ) -> NEFilterDataVerdict {
        if blocked && isTarget(flow) {
            // Lag switch engaged: drop this outbound chunk on the floor.
            // Returning .drop() tears the flow's data path down.
            return .drop()
        }
        // Allowed for now, but keep peeking so a later toggle still affects this flow.
        return .filterDataVerdict(
            withFilterInbound: false,
            peekInboundBytes: 0,
            filterOutbound: true,
            peekOutboundBytes: Int.max
        )
    }

    // MARK: - Targeting

    private func isTarget(_ flow: NEFilterFlow) -> Bool {
        guard !targets.isEmpty else { return false }
        // sourceAppIdentifier is the app's signing identifier, e.g. the bundle ID
        // for App Store / signed apps. Match against the user's selected targets.
        if let id = flow.sourceAppIdentifier, targets.contains(id) {
            return true
        }
        return false
    }

    // MARK: - Shared state

    private func refreshState() {
        let state = SharedState.shared
        blocked = state.blocked
        targets = Set(state.targetBundleIDs)
        os_log("State refreshed: blocked=%{public}@ targets=%{public}d",
               log: log, type: .info, String(blocked), targets.count)
    }

    private func registerForStateChanges() {
        let center = CFNotificationCenterGetDarwinNotifyCenter()
        let observer = Unmanaged.passUnretained(self).toOpaque()
        CFNotificationCenterAddObserver(
            center, observer,
            { _, observer, _, _, _ in
                guard let observer = observer else { return }
                let provider = Unmanaged<FilterDataProvider>.fromOpaque(observer).takeUnretainedValue()
                provider.refreshState()
            },
            NetBlockerIDs.stateChangedNotification as CFString,
            nil,
            .deliverImmediately
        )
    }

    private func unregisterForStateChanges() {
        let center = CFNotificationCenterGetDarwinNotifyCenter()
        let observer = Unmanaged.passUnretained(self).toOpaque()
        CFNotificationCenterRemoveEveryObserver(center, observer)
    }
}
