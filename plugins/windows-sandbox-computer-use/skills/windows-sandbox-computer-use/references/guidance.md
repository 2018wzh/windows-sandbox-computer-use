# Persistent visual workflow

Initialize from SKILL.md once per Node REPL session. Keep the selected Sandbox and
latest observation on `globalThis`; use block-scoped temporary variables in examples.
Print metadata with `nodeRepl.write(JSON.stringify(value))`. Screenshots are displayed
automatically by the session's callback; do not emit, save, or decode them again just
to inspect them.

## Select and observe

Inspect `list_sandboxes()` before selecting an ID. If multiple Sandboxes could match
the task, resolve the target with the user. Never pick the first arbitrary candidate.
Run `status()`; investigate a failure before deciding to call `start_daemon()`.
Create a Sandbox only when requested, using the lifecycle adapter. Do not replace an
existing session belonging to another task. The selected daemon must be exclusively
used by this session; no concurrent external client may reconnect or inject input.

```js
await sandbox.connect(selectedId); // One Id from the inspected environment list.
globalThis.state = await sandbox.get_state();
```

Stop the cell and inspect the image. Identify the intended guest application and its
editable surface, dimensions, focus, overlays, dialogs and lock state. There is no
guest window enumeration or accessibility tree. Use visually grounded taskbar or
keyboard navigation to select the app. Do not invent window handles or element indexes.

## One action and refresh

In the next cell, perform exactly one action derived from the inspected state:

```js
{
  const observed = globalThis.state;
  globalThis.state = null;
  globalThis.state = await sandbox.click({ state: observed, x: 420, y: 260 });
}
```

The call refreshes and displays the result. Stop and inspect it before choosing another
action. Coordinates are full-frame pixels, not host-screen or window-relative pixels.
The module rejects out-of-frame points, stale observation objects and concurrent calls.
It cannot detect unrelated guest UI changes after capture: reobserve if time passed,
focus/layout changed, a modal appeared, or someone else interacted with the desktop.

For typing, first click the observed editable work surface. Inspect the refreshed
image to verify the caret/focus, then type in a separate cell:

```js
{
  const observed = globalThis.state;
  globalThis.state = null;
  globalThis.state = await sandbox.type_text({ state: observed, text: 'Hello' });
}
```

Window titles alone do not establish text focus. Use `press_key` for Enter, Tab,
arrows and chords; literal text cannot contain control characters. Inspect partial
text before retrying so a timeout does not cause duplication. Prefer keyboard
navigation when clearly grounded. For canvas drawing use `drag`.

## Recovery and completion

- Never retry input automatically. A failure can mean input happened but refresh did
  not; `get_state()` and inspection must precede a retry.
- On a lightweight status timeout, wait two seconds and retry once. If it fails again,
  inspect adapter logs and report the error; do not start a second daemon blindly.
- On capture failure discard all coordinates. Check status and logs, then retry one
  capture if Connected. Stop on persistent failure, lock, security/privacy prompts,
  or ambiguous target state. Ask the user to unlock or handle prohibited dialogs.
- After a Node reset, reinitialize, inspect the environment list and reconnect the
  authorized target. Old observations are invalid. Never reconstruct them.
- When a turn is interrupted, stop input. Reobserve before resuming.
- Use screenshots to verify the requested visible outcome. A successful CLI command,
  Connected state, or cached frame does not prove successful interaction.
- `disconnect()` releases control; it does not destroy the Sandbox. Use an explicit
  lifecycle stop only when destruction is within the user's authorized scope.

For a browser inside the guest, stay on this Sandbox visual surface. Host Browser Use
tabs cannot be assumed to represent the guest browser.
