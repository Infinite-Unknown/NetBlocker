import Foundation
import CoreGraphics
import AppKit

/// Identifies a bound hotkey. We support keyboard keys (by CGKeyCode) and the
/// extra mouse buttons (button 3/4/5), matching the Windows app's "Mouse 4/5".
struct HotkeyDescriptor: Codable, Equatable {
    enum Kind: String, Codable { case key, mouse }

    var kind: Kind = .key
    var keyCode: Int = 0       // CGKeyCode for .key
    var mouseButton: Int = 0   // CGMouseButton raw value for .mouse
    var displayName: String = ""

    init(keyCode: Int, displayName: String) {
        self.kind = .key
        self.keyCode = keyCode
        self.displayName = displayName
    }

    init(mouseButton: Int, displayName: String) {
        self.kind = .mouse
        self.mouseButton = mouseButton
        self.displayName = displayName
    }
}

/// Global input listener built on a CGEventTap — the macOS counterpart to the
/// Windows WH_KEYBOARD_LL hook. It reports press/release of the bound hotkey
/// system-wide (works even when NetBlocker isn't focused).
///
/// Requires the **Accessibility** (and for mouse, **Input Monitoring**)
/// permission. Without it, `start()` fails and `onPermissionDenied` fires.
final class HotkeyManager {

    var onPress: (() -> Void)?
    var onRelease: (() -> Void)?
    var onPermissionDenied: (() -> Void)?

    /// While set, the next key/mouse event is captured as the new binding
    /// instead of being treated as the active hotkey.
    var captureNext: ((HotkeyDescriptor) -> Void)?

    private var binding: HotkeyDescriptor?
    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var isHeld = false

    func setBinding(_ descriptor: HotkeyDescriptor) {
        binding = descriptor
        isHeld = false
    }

    func start() {
        guard eventTap == nil else { return }

        guard AXIsProcessTrusted() else {
            onPermissionDenied?()
            return
        }

        let mask: CGEventMask =
            (1 << CGEventType.keyDown.rawValue) |
            (1 << CGEventType.keyUp.rawValue) |
            (1 << CGEventType.otherMouseDown.rawValue) |
            (1 << CGEventType.otherMouseUp.rawValue)

        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .listenOnly,
            eventsOfInterest: mask,
            callback: { _, type, event, refcon in
                guard let refcon = refcon else { return Unmanaged.passUnretained(event) }
                let manager = Unmanaged<HotkeyManager>.fromOpaque(refcon).takeUnretainedValue()
                manager.handle(type: type, event: event)
                return Unmanaged.passUnretained(event)
            },
            userInfo: selfPtr
        ) else {
            onPermissionDenied?()
            return
        }

        eventTap = tap
        runLoopSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), runLoopSource, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
    }

    func stop() {
        if let tap = eventTap { CGEvent.tapEnable(tap: tap, enable: false) }
        if let source = runLoopSource { CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes) }
        eventTap = nil
        runLoopSource = nil
    }

    // MARK: - Event dispatch

    private func handle(type: CGEventType, event: CGEvent) {
        // Capture mode: record this event as a new binding and consume it.
        if let capture = captureNext {
            if let descriptor = descriptor(for: type, event: event, pressOnly: true) {
                captureNext = nil
                DispatchQueue.main.async { capture(descriptor) }
            }
            return
        }

        guard let binding = binding else { return }

        switch type {
        case .keyDown:
            let code = Int(event.getIntegerValueField(.keyboardEventKeycode))
            if binding.kind == .key && code == binding.keyCode { press() }
        case .keyUp:
            let code = Int(event.getIntegerValueField(.keyboardEventKeycode))
            if binding.kind == .key && code == binding.keyCode { release() }
        case .otherMouseDown:
            let button = Int(event.getIntegerValueField(.mouseEventButtonNumber))
            if binding.kind == .mouse && button == binding.mouseButton { press() }
        case .otherMouseUp:
            let button = Int(event.getIntegerValueField(.mouseEventButtonNumber))
            if binding.kind == .mouse && button == binding.mouseButton { release() }
        default:
            break
        }
    }

    private func descriptor(for type: CGEventType, event: CGEvent, pressOnly: Bool) -> HotkeyDescriptor? {
        switch type {
        case .keyDown:
            let code = Int(event.getIntegerValueField(.keyboardEventKeycode))
            return HotkeyDescriptor(keyCode: code, displayName: KeyNames.name(for: code))
        case .otherMouseDown:
            let button = Int(event.getIntegerValueField(.mouseEventButtonNumber))
            return HotkeyDescriptor(mouseButton: button, displayName: "Mouse \(button + 1)")
        default:
            return nil
        }
    }

    private func press() {
        guard !isHeld else { return } // ignore auto-repeat
        isHeld = true
        DispatchQueue.main.async { self.onPress?() }
    }

    private func release() {
        guard isHeld else { return }
        isHeld = false
        DispatchQueue.main.async { self.onRelease?() }
    }
}

/// Minimal CGKeyCode → label map for the common keys. Extend as needed.
enum KeyNames {
    static func name(for code: Int) -> String {
        let map: [Int: String] = [
            49: "Space", 36: "Return", 53: "Esc", 48: "Tab",
            122: "F1", 120: "F2", 99: "F3", 118: "F4",
            96: "F5", 97: "F6", 98: "F7", 100: "F8",
            101: "F9", 109: "F10", 103: "F11", 111: "F12",
            63: "fn"
        ]
        return map[code] ?? "Key \(code)"
    }
}
