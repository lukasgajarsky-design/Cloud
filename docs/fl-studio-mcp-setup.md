# FL Studio piano roll MCP: local setup

How to connect Claude Code to FL Studio's piano roll with [calvinw/fl-studio-mcp](https://github.com/calvinw/fl-studio-mcp). This has to run on the computer where FL Studio is installed. A Claude Code cloud session can't reach your FL Studio.

## How it talks to FL Studio

No MIDI is involved, so you don't need IAC Driver, loopMIDI or any other virtual MIDI port.

1. Claude calls an MCP tool such as `send_notes`. The server writes the request to `mcp_request.json` in FL Studio's `Piano roll scripts` folder.
2. The server brings FL Studio to the front and presses **Cmd+Opt+Y** (macOS) or **Ctrl+Alt+Y** (Windows). In the piano roll, that shortcut re-runs the last script you ran.
3. That script is `ComposeWithLLM`. It applies the queued notes and writes the piano roll to `piano_roll_state.json`, which Claude reads with `get_piano_roll_state`.

The tools are `get_piano_roll_state`, `send_notes`, `delete_notes`, `clear_queue` and `clear_piano_roll`.

Upstream supports macOS fully and Windows only partly.

## Before you start

- Start FL Studio once, so it creates `Documents/Image-Line/FL Studio/Settings/Piano roll scripts`.
- Install [Claude Code](https://code.claude.com/docs/en/setup) and git.

## macOS

```bash
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
cd ~
git clone https://github.com/calvinw/fl-studio-mcp.git
cd fl-studio-mcp
./install_prerequisites.sh
claude mcp add -s user --transport stdio fl-studio-mcp -- "$PWD/.venv/bin/python" "$PWD/fl_studio_mcp_server.py"
```

How this differs from the upstream README:

- **uv is installed first.** If uv is missing, `install_prerequisites.sh` installs it but then looks for it in `~/.cargo/bin`. Current uv installs to `~/.local/bin`, so the script stops at `uv venv`.
- **`claude mcp add -s user` replaces `./install_mcp_for_claude.sh`.** The script registers the server for the `fl-studio-mcp` folder only, so the tools are missing when you start `claude` anywhere else. `-s user` makes them available in every folder.

`install_prerequisites.sh` creates `.venv/`, installs `fastmcp` and `pynput`, and copies `ComposeWithLLM.pyscript` plus empty JSON queue files into FL Studio's `Piano roll scripts` folder.

**Permissions:** in System Settings → Privacy & Security → Accessibility, turn on the terminal app you run `claude` in (Terminal, iTerm, Warp, …). The first time notes are sent, macOS asks whether that app may control "System Events". Click Allow. Without both permissions, the keystroke never reaches FL Studio.

## Windows (Command Prompt)

Upstream has no Windows installer, and its shell scripts register a macOS-style `.venv/bin/python` path. Run these steps instead. Install uv first:

```bat
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Open a new Command Prompt so `uv` is on the PATH, then run:

```bat
cd /d %USERPROFILE%
git clone https://github.com/calvinw/fl-studio-mcp.git
cd fl-studio-mcp
uv venv --python 3.12
uv pip install -e . pywin32
copy ComposeWithLLM.pyscript "%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Piano roll scripts\"
claude mcp add -s user --transport stdio fl-studio-mcp -- "%CD%\.venv\Scripts\python.exe" "%CD%\fl_studio_mcp_server.py"
```

You need `pywin32` even though `pyproject.toml` doesn't list it. Without it, the server can't focus the FL Studio window, so the automatic trigger always fails.

Windows gaps in upstream:

- **Process name.** Before triggering, the server checks that a process named `FL.exe` is running. 64-bit FL Studio usually runs as `FL64.exe` (check Task Manager → Details). If yours does, open `fl_studio_mcp_server.py` in Notepad and change these lines in `_is_fl_studio_running`:

  ```python
  result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq FL.exe'],
                        capture_output=True, text=True)
  return 'FL.exe' in result.stdout
  ```

  to:

  ```python
  result = subprocess.run(['tasklist'], capture_output=True, text=True)
  return 'FL.exe' in result.stdout or 'FL64.exe' in result.stdout
  ```

- **Documents in OneDrive.** The server and `ComposeWithLLM` both use `%USERPROFILE%\Documents\Image-Line\...`. If FL Studio keeps its files under `OneDrive\Documents`, copy `ComposeWithLLM.pyscript` there so it shows up in the menu. Also create the `%USERPROFILE%\Documents` path, because the queue files go there.
- **Manual fallback.** When the trigger fails, Claude says "trigger failed", but the notes are already queued. Press Ctrl+Alt+Y in the piano roll to apply them.

## Check the connection

Start `claude` in any folder and type `/mcp`. `fl-studio-mcp` should show as connected, with the five tools listed above. You can check from a shell with `claude mcp list`. It should print `fl-studio-mcp: … - ✓ Connected`.

## Every session

1. Open FL Studio and a piano roll.
2. Run **Tools → Scripting → ComposeWithLLM** once. After that, Cmd+Opt+Y / Ctrl+Alt+Y re-runs it.
3. Ask Claude, for example "Create a I-IV-V-I progression in C major". The notes show up about 2 seconds later.
4. If you edit notes by hand, press Cmd+Opt+Y / Ctrl+Alt+Y before your next request so Claude sees the changes.

Keep the piano roll in front while Claude works. The trigger presses keys on whatever window FL Studio has focused.

## Tested

On 2026-10-04 (upstream commit `54467fd`, fastmcp 4.0.10), these were run in a Linux container without FL Studio: the macOS steps above in a clean home folder with a stand-in `Piano roll scripts` folder, and an MCP client calling the server.

- `claude mcp list` reported the server as connected from an unrelated folder.
- All five tools were listed.
- `send_notes` wrote the correct queue to `mcp_request.json`.

Not tested: the keystroke trigger and the FL Studio side, which need a real Mac or PC with FL Studio. The Windows steps weren't run at all.
