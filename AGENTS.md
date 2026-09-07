# Repository instructions

## Product boundary

This repository ships one Windows Sandbox-only skill through two distribution surfaces:

- a skills-only Codex plugin and repo Marketplace;
- the open Agent Skills layout discovered by `npx skills`.

Both surfaces must consume the single canonical skill tree at:

```text
plugins/windows-sandbox-computer-use/skills/windows-sandbox-computer-use/
```

Do not create a second skill copy, generic RDP backend, legacy Sandbox window backend, compatibility layer, credential path, or silent fallback.

## Runtime architecture

```text
Node session -> Python adapter -> wsb / SandboxCore -> IronRDP NamedPipe
```

Use `wsb share` for scoped directory sharing. Keep read-only as the default. Writable sharing requires explicit authorization for the exact source and destination.

## Change requirements

- Use the persistent Node session for guest input, with one inspected observation per action and automatic screenshot refresh. Keep guidance, API, safety and confirmations self-contained.
- No guest UIA or window enumeration is available; do not advertise those capabilities. Lifecycle and sharing remain owned by the Python adapter. Node built-ins are the only JavaScript dependencies.

- Fail closed on missing or incompatible dependencies.
- Preserve structured, bounded error output and observable lifecycle state.
- Keep repository paths relative and never commit machine-specific paths, Sandbox IDs, screenshots, logs, or credentials.
- Update `README.md`, plugin metadata, Marketplace metadata, tests, and this file when product scope or distribution changes.
- Increment the strict semantic version in `.codex-plugin/plugin.json` for releases.

## Validation

Run focused checks before committing:

```sh
python scripts/validate_release.py
python -m unittest discover \
  -s plugins/windows-sandbox-computer-use/skills/windows-sandbox-computer-use/tests \
  -p 'test_*.py' \
  -v
npx skills add . --list
node --test plugins/windows-sandbox-computer-use/skills/windows-sandbox-computer-use/tests/test_session.mjs
```
