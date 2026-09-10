# Efficient guest commands

Use the persistent session to avoid repeated CLI discovery and verbose tool output.
`select()` chooses the sole running Sandbox; `select(id)` disambiguates multiple ones.
Selection and commands require only the Store `wsb` runtime, not IronRDP, a daemon,
an image callback, or visual focus. The adapter verifies the selected Sandbox still
exists before execution. It never creates or switches environments implicitly.

```js
await sandbox.select();
nodeRepl.write(JSON.stringify(await sandbox.exec({
  command: 'cmd.exe /c exit 0',
  cwd: 'C:\\',
  timeout: 30
})));
```

`command` is a Windows guest command line passed as one argument to native `wsb exec`.
No host shell is invoked. Name a guest shell explicitly for shell operators, scripts
or built-ins. The library does not guess shell syntax or split command lines.
Default `run_as` is `ExistingLogin`; `System` must be explicitly requested and used
only when the task requires that execution context. ExistingLogin requires an active
guest login. A failure never silently switches to System.

```js
nodeRepl.write(JSON.stringify(await sandbox.exec_many([
  { command: 'cmd.exe /c exit 0', timeout: 10 },
  { command: 'cmd.exe /c exit 0', timeout: 10 }
])));
```

Batch commands run in order; all request shapes are validated before the first launch.
The first failure throws with `failed_index` (zero-based), `completed` results and
the underlying `cause`/`result`. Remaining commands are not run; there is no rollback.
Use batches only for work already determined by the user task, not speculative UI
actions. Avoid printing full exceptions or repeating command text when a category and
exit code suffice. Never include credentials in commands or diagnostic output.

Successful execution returns `exit_code`, `elapsed_ms`, `stdout: null`, `stderr: null`.
The installed native CLI exposes no stdout/stderr channel. For output files, use an
explicitly authorized writable output directory via `share()` and make the guest tool
write there. No hidden writable share or persistent transcript is created.

Timeouts are 30 seconds by default, configurable up to 300. A timeout stops waiting
for `wsb`; it does not prove the guest process stopped. Do not retry a timed-out
mutation without checking its outcome. Native nonzero exit codes throw
`guest_command_failed`; malformed results and transport failures remain errors.

```js
await sandbox.share({host_path: 'work/input', sandbox_path: 'C:\\Input'});
nodeRepl.write(JSON.stringify(await sandbox.ip()));
```

Sharing is read-only by default. Set `allow_write: true` only for the authorized exact
source and destination. `ip()` returns the native JSON result without opening network
access or changing firewall settings. A guest command can modify mounted writable
host directories: keep it inside the task's authorized scope.

For mixed workflows create the session with `emitImage`, select a Sandbox, then call
`connect()` without repeating its ID. After command execution, use `get_state()` before
any visual input; automatic screenshots are intentionally omitted for commands.
`disconnect()` releases visual control but retains the command target.

The CLI equivalent, relative to the installed skill directory, is:

```sh
python scripts/sandbox_cua.py sandbox-exec --id SANDBOX_ID --command 'cmd.exe /c exit 0'
python scripts/sandbox_cua.py sandbox-ip --id SANDBOX_ID
```
