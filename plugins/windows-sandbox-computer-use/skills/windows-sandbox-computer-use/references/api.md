# Sandbox session API

Import `createSandbox` from `scripts/sandbox_session.mjs` in the persistent Node REPL.
Pass `emitImage: image => nodeRepl.emitImage(image)`. Optional `python` selects a Python
executable; `endpoint` selects the existing IronRDP IPC endpoint. No shell is used.

| Method | Arguments / result |
| --- | --- |
| `doctor()` | Dependency report; does not install or enable anything |
| `list_sandboxes()` | Returns `environments`; select exactly one returned `Id` |
| `status()` | Current daemon status; failure is not proof the daemon is absent |
| `start_daemon()` | Start only after establishing no daemon is available |
| `connect(id)` | Validate a returned ID, connect, wait for eight seconds of Connected state |
| `get_state()` | Display screenshot once and return an observation |
| `click({state,x,y,mouse_button?,click_count?})` | Full-frame pixel coordinates; defaults left, one click |
| `drag({state,from_x,from_y,to_x,to_y})` | Drag within the screenshot |
| `scroll({state,x,y,delta,horizontal?})` | Raw RDP wheel delta, positive vertical means up; unlike sky's scrollY |
| `press_key({state,key})` | `+` separated keys, e.g. `Control_L+a`, `Return`, `Alt+Tab` |
| `type_text({state,text})` | Literal text into visually verified focus; control characters rejected |
| `disconnect()` | Release control; does not stop or destroy the Sandbox |

An observation contains `sandbox: {id}`, `screenshotId`, `width`, `height`, and
`accessibility: null`. Pass the returned observation as `state`; never invent its
identifier. The session accepts REPL-serialized observations and checks the current
session-specific screenshot identifier, using its own stored dimensions for bounds.
Every successful input consumes that observation and returns a fresh,
automatically displayed observation. Inspect the new image before the next action.
Concurrent operations are rejected. Failed input or refresh invalidates the state;
call `get_state()` and inspect before deciding whether any retry is appropriate.

The module uses the existing Python adapter and Node built-ins only. Images are read
for display and the module's temporary screenshot directory is removed immediately.
It does not save a screenshot history. Use the adapter's `screenshot` command when
the user needs a retained artifact. The exported `runAdapter(argv, options)` supports
lifecycle and scoped sharing; consult `sandbox_cua.py --help` for those commands.
Do not mix direct adapter input or another daemon client with a connected session.

Supported keys are the adapter's `SCANCODES` and aliases: letters, number row,
F1–F12, navigation, Enter, Tab, Escape, Space, Backspace, Delete, Insert, Ctrl,
Shift and Alt. Unknown keys fail before injection. Numpad/punctuation keysyms and
UIA operations are not implemented; do not infer sky API parity.
