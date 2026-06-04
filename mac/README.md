# NetBlocker for macOS

A native macOS rewrite of NetBlocker's **network lag switch**: select running apps
and toggle their outbound internet on/off with a global hotkey, with an optional
keep-alive auto-refresh.

This is **not** a line-by-line port of the Windows Python app — it can't be. The
Windows version blocks traffic with `netsh advfirewall ... program=game.exe`,
which has no equivalent on macOS. The macOS firewall (`socketfilterfw`) only
controls *inbound* connections, and `pfctl` filters by IP/port, not by app. The
only supported way to block a specific application's outbound traffic on modern
macOS is a **Network Extension content filter** — the same mechanism Little
Snitch and LuLu use. So the OS layer is rebuilt natively in Swift.

> ⚠️ This scaffold was authored on Linux and has **not been compiled on macOS**.
> Treat it as a complete, reviewable starting point that you build and test in
> Xcode. Expect to fix small API/signing details on first build.

## How it works

```
┌─────────────────────────────┐         shared App Group store
│ NetBlocker.app (SwiftUI)     │   ┌──────────────────────────────┐
│  • app picker (NSWorkspace)  │   │ blocked: Bool                │
│  • global hotkey (CGEventTap)│──▶│ targetBundleIDs: [String]    │◀─┐
│  • lag-switch state machine  │   └──────────────────────────────┘  │
│  • installs/enables filter   │            ▲   Darwin notification   │
└─────────────────────────────┘            │   "stateChanged"        │
                                            │                         │
┌───────────────────────────────────────────────────────────────────┘
│ FilterExtension (NEFilterDataProvider, system extension)
│  • sees every new outbound flow
│  • for target apps, keeps inspecting the flow
│  • while blocked == true, returns .drop() on outbound data
│    → cuts traffic even on already-open connections (true lag switch)
└────────────────────────────────────────────────────────────────────
```

The hotkey path is intentionally cheap: on every press/release the app flips a
bool in the shared App Group store and posts a Darwin notification; the extension
reacts in-memory without polling.

## Project layout

| Path | Purpose |
|---|---|
| `Shared/SharedState.swift` | App Group store + Darwin notification, used by both targets |
| `FilterExtension/FilterDataProvider.swift` | The content filter — actual drop logic |
| `FilterExtension/Info.plist`, `*.entitlements` | NE provider class registration + entitlements |
| `NetBlocker/Core/FilterController.swift` | Installs the system extension, enables `NEFilterManager` |
| `NetBlocker/Core/HotkeyManager.swift` | Global hotkey via `CGEventTap` (key + mouse buttons) |
| `NetBlocker/Core/LagSwitchEngine.swift` | Hold / Toggle / Charge / Tap-Charge + auto-refresh state machine |
| `NetBlocker/Core/ProcessLister.swift` | Lists running GUI apps (`NSWorkspace`) |
| `NetBlocker/Core/AppConfig.swift` | Config model + JSON save/load (named configs) |
| `NetBlocker/App/*` | `@main` app + `AppModel` coordinator |
| `NetBlocker/UI/ContentView.swift` | Blocker + Configs tabs |
| `project.yml` | XcodeGen spec wiring the two targets together |

## Prerequisites

- macOS 12+ and Xcode 15+.
- An **Apple Developer account**. Per-app network filtering needs the
  `com.apple.developer.networking.networkextension` entitlement
  (`content-filter-provider`). For Mac App Store / notarized distribution you must
  request this capability from Apple; for local development a paid team is
  generally required to sign a system extension.
- [XcodeGen](https://github.com/yonprez/XcodeGen): `brew install xcodegen`.

## Build & run

```bash
cd mac
xcodegen generate          # produces NetBlocker.xcodeproj
open NetBlocker.xcodeproj
```

Then in Xcode:

1. Set your **Development Team** on both targets (or fill `DEVELOPMENT_TEAM` in
   `project.yml` and regenerate).
2. Replace the `com.infiniteunknown.*` bundle IDs and the
   `group.com.infiniteunknown.netblocker` App Group with IDs registered to your
   team (keep them consistent across both entitlement files, `SharedState.swift`,
   and `project.yml`).
3. Build & run the **NetBlocker** scheme.

System extensions are easier to iterate on outside the sandbox during dev — see
Apple's "Debugging and testing system extensions" (you may need
`systemextensionsctl developer on` and to run from `/Applications`).

## First-run permissions

The app will ask for several approvals — all expected:

1. **Install network filter** → approve the system extension in
   *System Settings → General → Login Items & Extensions* (and the filter prompt).
2. **Accessibility** + **Input Monitoring** (System Settings → Privacy &
   Security) so the global hotkey works.

## Feature status

Implemented (matching the requested **network lag switch**):

- [x] List + multi-select running apps as targets
- [x] Global hotkey (keyboard keys and extra mouse buttons)
- [x] Hold / Toggle / Charge / Tap-Charge modes
- [x] Auto-refresh keep-alive pulsing
- [x] Per-app outbound drop on new *and* established connections
- [x] Named JSON config save/load with auto-load on launch

Not ported in this pass (the Windows app's gaming extras):

- [ ] Spacebar spammer / auto-bhop — would map to `CGEventTap` + `CGEventPost`
- [ ] Always-on-top overlays — would be a borderless `NSWindow` (`.statusBar` level)

## Known caveats / TODO

- `NEFilterFlow.sourceAppIdentifier` is the app's signing identifier. For most
  signed apps this equals the bundle ID we match on; verify for your targets and
  fall back to `sourceAppAuditToken` if needed.
- The auto-refresh "unblock pulse" timing (currently 30 ms) is a starting value;
  tune `LagSwitchEngine.startAutoRefresh()` for your use case.
- Dropping outbound data on an established TCP flow severs that connection rather
  than merely pausing it; this matches lag-switch behavior but means apps will
  reconnect after the block clears.
- The `system-extension` target type requires a recent XcodeGen; if yours is
  older, create the extension target manually in Xcode and add the same sources,
  Info.plist, and entitlements.
```
