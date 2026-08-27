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
wsb / SandboxCore -> IronRDP NamedPipe -> screenshots and remote input
```

Use `wsb share` for scoped directory sharing. Keep read-only as the default. Writable sharing requires explicit authorization for the exact source and destination.

## Change requirements

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
```
