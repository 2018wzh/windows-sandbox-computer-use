# Windows Sandbox workflow

## Prerequisites

Require the Store-delivered Windows Sandbox runtime with working `wsb --version`, `wsb list --raw`, and `wsb share` support. `ironrdp-agent` 0.1.0 or newer must be on `PATH`, discoverable from Cargo's user bin directory, or named by `IRONRDP_AGENT_BIN`.

One IronRDP daemon owns one Sandbox RDP session. A managed daemon is recorded under the user's platform state directory. The adapter accepts no remote host, RDP file, overlay, username, domain, password, or certificate-bypass option.

## Lifecycle

1. Run `doctor`; stop on any `wsb`, SandboxCore, or IronRDP incompatibility.
2. Run `sandbox-list` and select exactly one authorized Sandbox if one exists.
3. Run `status`. Reuse a compatible daemon, or run `daemon-start` if none exists.
4. Run `sandbox-start` only when a new Sandbox is requested, then run `sandbox-list` again to obtain its ID.
5. Run `sandbox-connect --id SANDBOX_ID`, then `wait-connected --stable-seconds 8`.
6. Initialize the Node session and follow guidance.md for visual control. Its `connect(id)` includes the stable wait from step 5.
7. Perform one action, then capture a fresh screenshot and verify the result.
8. Run `disconnect` when visual control is complete. Run `sandbox-stop` only when the user requested destruction and the confirmation policy permits it.

```sh
python scripts/sandbox_cua.py daemon-start
python scripts/sandbox_cua.py sandbox-start
python scripts/sandbox_cua.py sandbox-connect --id SANDBOX_ID
python scripts/sandbox_cua.py wait-connected --stable-seconds 8
python scripts/sandbox_cua.py screenshot work/sandbox-001.png
python scripts/sandbox_cua.py disconnect
```

Retail Windows builds may permit only one active Sandbox. Report that policy error; never destroy an existing Sandbox to bypass it unless the user explicitly requests and confirms the stop action.

## Scoped directory sharing

Use `sandbox-share` to mount one existing host directory at one explicit absolute Sandbox path. Read-only is the default and should be used for source, tools, fixtures, and installers. Use `--allow-write` only when the user explicitly authorizes the exact host directory as an output channel for build products, logs, traces, screenshots, dumps, or edited files.

```sh
python scripts/sandbox_cua.py sandbox-share \
  --id SANDBOX_ID \
  --host-path work/debug-input \
  --sandbox-path 'C:\DebugWorkspace'
```

Writable example after authorization:

```sh
python scripts/sandbox_cua.py sandbox-share \
  --id SANDBOX_ID \
  --host-path work/debug-output \
  --sandbox-path 'C:\DebugOutput' \
  --allow-write
```

The adapter resolves the host path, requires a directory, rejects filesystem roots, requires a drive-absolute Sandbox path, invokes `wsb share --raw`, and reports the exact mapping and mode. `wsb` has no unshare operation; the mapping belongs to that Sandbox session and is destroyed with the Sandbox. Do not claim guest-level file visibility without subsequently observing it in the UI.

## Observe, act, verify

Screenshots are full-frame observations without a remote UI Automation tree. The Node session displays and cleans temporary screenshots automatically. For retained diagnostic captures use a new filename; the adapter refuses overwrite unless `--overwrite` is explicit.

For every input action:

1. Capture a new screenshot.
2. Inspect dimensions, target, focus, modal state, and lock state.
3. Choose coordinates only from that screenshot.
4. Perform one click, drag, scroll, key, hotkey, or bounded text action.
5. Immediately capture and inspect a new screenshot.

Never reuse coordinates after resize, reconnect, resolution change, modal appearance, navigation, or uncertain input. Text is split into 96-character atomic requests; report partial entry if a later request fails.

## Recovery and observability

- If `doctor` fails, fix or upgrade the named dependency; do not activate another backend.
- If `status` fails, inspect the managed daemon log returned by `daemon-start`, then retry one lightweight status check.
- If connect fails or `wait-connected` reaches a terminal state, run `logs --last 100`; never weaken validation.
- If no frame is available, retry `screenshot` once after a short wait. Then report session and log state.
- Normal screenshots require `Connected`. `--allow-stale` is diagnostic-only and must be labeled as a cached frame.
- If input fails, its effect is unknown. Capture a new screenshot before any retry.
- Never treat CLI success as proof of the intended UI outcome; visual verification requires a fresh screenshot.
- `sandbox-stop` destroys the ephemeral environment and its shares. Treat it as deletion-like.

## Adapter output

Every successful operation emits one bounded JSON object with `ok: true`. Failures emit one JSON object to stderr with `ok: false`, an error category, and a bounded underlying message, then exit nonzero. No credential fields exist in the adapter interface.
