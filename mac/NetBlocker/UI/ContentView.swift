import SwiftUI

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        TabView {
            BlockerView()
                .tabItem { Label("Blocker", systemImage: "network.slash") }
            ConfigsView()
                .tabItem { Label("Configs", systemImage: "folder") }
        }
        .padding()
    }
}

/// Main tab: filter status, app selection, hotkey + mode, live block state.
struct BlockerView: View {
    @EnvironmentObject var model: AppModel
    @State private var search = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            FilterStatusBar()

            if model.accessibilityDenied {
                PermissionBanner()
            }

            HStack {
                Image(systemName: model.engine.isBlocking ? "bolt.fill" : "bolt.slash")
                    .foregroundStyle(model.engine.isBlocking ? .red : .green)
                Text(model.engine.isBlocking ? "Lag switch: ON"
                     : model.engine.isCharging ? "Charging…" : "Lag switch: OFF")
                    .font(.headline)
                    .foregroundStyle(model.engine.isBlocking ? .red
                                     : model.engine.isCharging ? .orange : .green)
                Spacer()
            }

            HotkeyControls()

            Divider()

            HStack {
                Text("Target apps").font(.subheadline.bold())
                Spacer()
                Button("Refresh") { model.refreshApps() }
                TextField("Search", text: $search)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 160)
            }

            List {
                ForEach(filteredApps) { app in
                    Toggle(isOn: Binding(
                        get: { model.isSelected(app) },
                        set: { _ in model.toggleSelection(app) }
                    )) {
                        VStack(alignment: .leading) {
                            Text(app.name)
                            Text(app.bundleID).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .listStyle(.inset)
        }
    }

    private var filteredApps: [AppTarget] {
        guard !search.isEmpty else { return model.runningApps }
        return model.runningApps.filter {
            $0.name.localizedCaseInsensitiveContains(search) ||
            $0.bundleID.localizedCaseInsensitiveContains(search)
        }
    }
}

/// Filter activation / status row, including the system-extension install button.
struct FilterStatusBar: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        HStack {
            switch model.filter.status {
            case .ready:
                Label("Filter active", systemImage: "checkmark.shield.fill").foregroundStyle(.green)
            case .disabled:
                Label("Filter disabled", systemImage: "shield.slash").foregroundStyle(.orange)
                Button("Enable") { Task { await model.filter.enableFilter() } }
            case .needsApproval:
                Label("Approve NetBlocker in System Settings → Privacy & Security",
                      systemImage: "exclamationmark.shield").foregroundStyle(.orange)
            case .installing:
                ProgressView().scaleEffect(0.6)
                Text("Installing extension…")
            case .failed(let msg):
                Label(msg, systemImage: "xmark.shield").foregroundStyle(.red)
            case .unknown:
                Button("Install network filter") { model.filter.activate() }
            }
            Spacer()
        }
        .padding(8)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
    }
}

struct HotkeyControls: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        HStack {
            Text("Hotkey:")
            Button(model.capturingHotkey ? "Press a key/mouse button…" : model.config.hotkey.displayName) {
                model.beginCaptureHotkey()
            }
            .frame(minWidth: 160)

            Picker("Mode", selection: $model.config.mode) {
                ForEach(HotkeyMode.allCases) { Text($0.label).tag($0) }
            }
            .frame(width: 200)

            Spacer()
        }
    }
}

struct PermissionBanner: View {
    var body: some View {
        Label("Grant Accessibility & Input Monitoring in System Settings → Privacy & Security so the hotkey works.",
              systemImage: "hand.raised.fill")
            .foregroundStyle(.orange)
            .padding(8)
            .background(.yellow.opacity(0.15), in: RoundedRectangle(cornerRadius: 8))
    }
}

/// Configs tab: save/load named JSON configs, mirroring the Windows app.
struct ConfigsView: View {
    @EnvironmentObject var model: AppModel
    @State private var newName = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                TextField("Config name", text: $newName).textFieldStyle(.roundedBorder)
                Button("Save") {
                    guard !newName.isEmpty else { return }
                    model.saveConfig(named: newName)
                    newName = ""
                }
            }
            Divider()
            List {
                ForEach(model.savedConfigNames, id: \.self) { name in
                    HStack {
                        Text(name)
                        Spacer()
                        Button("Load") { model.loadConfig(named: name) }
                    }
                }
            }
            .listStyle(.inset)

            GroupBox("Auto refresh") {
                Toggle("Enable keep-alive refresh", isOn: $model.config.autoRefreshEnabled)
                HStack {
                    Text("Block window: \(model.config.autoRefreshMs) ms")
                    Slider(value: Binding(
                        get: { Double(model.config.autoRefreshMs) },
                        set: { model.config.autoRefreshMs = Int($0) }
                    ), in: 100...2000)
                }
                HStack {
                    Text("Charge cooldown: \(model.config.chargeDelayMs) ms")
                    Slider(value: Binding(
                        get: { Double(model.config.chargeDelayMs) },
                        set: { model.config.chargeDelayMs = Int($0) }
                    ), in: 100...2000)
                }
                Toggle("Tap to cancel (Tap Charge mode)", isOn: $model.config.tapCancelEnabled)
            }
        }
    }
}
