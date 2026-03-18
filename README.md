# Net Blocker

A Windows utility that selectively blocks internet access for chosen applications with a configurable hotkey. Includes a built-in lagswitch overlay and spacebar spammer for gaming.

Created by **Infinite** — [GitHub](https://github.com/Infinite-Unknown)

---

## Features

- **Selective App Blocking** — Pick one or multiple running processes and block their outbound internet via Windows Firewall rules.
- **Hold or Toggle Mode** — Hold a key to block while pressed, or toggle on/off with a single press.
- **Hotkey Binding** — Bind any keyboard key or mouse button (including Mouse 4/5) as the activation hotkey.
- **Auto Refresh** — Automatically cycles block off/on at a configurable interval (1–999 ms) to prevent server-side disconnect detection.
- **Always-on-Top Overlay** — Draggable overlay showing "Lagswitch: On/Off" status with a live millisecond timer.
- **Spacebar Spammer** — Low-level keyboard hook intercepts physical spacebar, sends rapid synthetic press/release events with configurable delays. Works with DirectInput games (e.g. Roblox).
- **Config Profiles** — Save/load named configurations including selected apps, hotkey, mode, overlay state, and spammer settings.

## Requirements

- Windows 10/11
- Administrator privileges (required for firewall rule management)
- Python 3.10+ or the standalone `.exe`

## Installation

### Option 1: Standalone EXE (recommended)

Download `NetBlocker.exe` from the [Releases](https://github.com/Infinite-Unknown/NetBlocker/releases) page. Run as Administrator.

### Option 2: Run from source

```bash
# Clone the repo
git clone https://github.com/Infinite-Unknown/NetBlocker.git
cd NetBlocker

# Install dependencies
pip install -r requirements.txt

# Run (will auto-prompt for admin elevation)
pythonw net_blocker.pyw
```

## Building the EXE

A build script is included that uses a conda environment for a clean build:

```bash
# From the NetBlocker folder, run:
build.bat
```

This will:
1. Create a temporary conda environment (`netblocker_build`)
2. Install all dependencies
3. Build a single-file `.exe` with PyInstaller (includes UAC admin manifest)
4. Output to `dist/NetBlocker.exe`

To build manually:

```bash
conda create -n netblocker_build python=3.11 -y
conda activate netblocker_build
pip install psutil pynput customtkinter pyinstaller

pyinstaller --noconfirm --onefile --windowed --name "NetBlocker" --uac-admin \
    --collect-all customtkinter \
    --hidden-import pynput.keyboard._win32 \
    --hidden-import pynput.mouse._win32 \
    --hidden-import pynput._util \
    --hidden-import pynput._util.win32 \
    net_blocker.pyw
```

## Usage

1. Launch `NetBlocker.exe` (or `pythonw net_blocker.pyw`) — it will request admin privileges.
2. **Blocker tab**: Select apps from the process list, set your hotkey, choose Hold or Toggle mode.
3. **Configs tab**: Save your setup with a name. The first saved config auto-loads on startup.
4. **Misc tab**: Enable the spacebar spammer and tune press/release/activation delays.

### Hotkey Modes

| Mode   | Behavior |
|--------|----------|
| Hold   | Internet is blocked only while the hotkey is held down. |
| Toggle | Press once to block, press again to unblock. |

### Auto Refresh

When enabled, the blocker automatically unblocks for ~50 ms then re-blocks at your chosen interval. This keeps the connection alive on servers that detect prolonged packet loss.

## How It Works

- **Firewall blocking**: Creates temporary `netsh advfirewall` outbound block rules for selected executables. All rules are prefixed with `NetBlocker_` and cleaned up on exit.
- **Spacebar spammer**: Uses a Windows low-level keyboard hook (`WH_KEYBOARD_LL`) to intercept physical spacebar events, then sends synthetic key events via `SendInput` with scan codes (`KEYEVENTF_SCANCODE`) for DirectInput compatibility.
- **Orphan cleanup**: On startup, any leftover `NetBlocker_*` firewall rules from a previous crash are automatically removed.

## License

MIT License. See [LICENSE](LICENSE) for details.
