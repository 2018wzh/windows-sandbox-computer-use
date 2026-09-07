# Windows Sandbox Computer Use

A Windows-only agent skill for creating, inspecting, sharing scoped directories with, and visually controlling Windows Sandbox through the current `wsb` CLI and IronRDP Agent.

The control path is deliberately singular:

```text
wsb / SandboxCore -> IronRDP NamedPipe -> screenshots and remote input
```

It does not connect to ordinary RDP hosts, automate the local Sandbox window, or fall back to legacy Windows Sandbox clients.

## Requirements

- Windows 11 with the Store-delivered Windows Sandbox runtime and a working `wsb` CLI
- Windows Sandbox enabled by the operator
- Python 3.10 or newer
- Node.js 22 or newer and a persistent Node REPL with image display
- `ironrdp-agent` 0.1.0 or newer on `PATH`, in Cargo's user bin directory, or selected through `IRONRDP_AGENT_BIN`

Install IronRDP Agent from its official release, or with:

```sh
cargo install ironrdp-agent
```

## Install with the Codex plugin Marketplace

Register the repository Marketplace and install the plugin:

```sh
codex plugin marketplace add 2018wzh/windows-sandbox-computer-use --ref v1.0.0
codex plugin add windows-sandbox-computer-use@windows-sandbox-tools
```

Start a new Codex task after installation, then invoke:

```text
$windows-sandbox-computer-use
```

## Install with `npx skills`

Install globally for Codex:

```sh
npx skills add 2018wzh/windows-sandbox-computer-use \
  --skill windows-sandbox-computer-use \
  --agent codex \
  --global \
  --yes
```

List the skill without installing it:

```sh
npx skills add 2018wzh/windows-sandbox-computer-use --list
```

## Validate the environment

After loading the skill, use its adapter from the installed skill directory:

```sh
python scripts/sandbox_cua.py doctor
python scripts/sandbox_cua.py sandbox-list
python scripts/sandbox_cua.py status
```

`doctor` fails closed when the installed Windows Sandbox or IronRDP Agent lacks a required capability.

## Persistent visual control

The skill uses a persistent JavaScript session with automatic screenshot display,
single-use observations, coordinate bounds, one input followed by refresh, and
explicit recovery after unknown outcomes. Safety and confirmation references are
bundled. The session uses the existing Python adapter and Node built-ins.

This aligns the visual workflow with Computer Use. IronRDP does not expose guest
accessibility trees, app/window enumeration or per-window capture. See the skill
references for initialization and API examples.

## Scoped directory sharing

Directory sharing is read-only by default:

```sh
python scripts/sandbox_cua.py sandbox-share \
  --id SANDBOX_ID \
  --host-path work/debug-input \
  --sandbox-path 'C:\DebugWorkspace'
```

Allow Sandbox writes only for an explicitly authorized output directory:

```sh
python scripts/sandbox_cua.py sandbox-share \
  --id SANDBOX_ID \
  --host-path work/debug-output \
  --sandbox-path 'C:\DebugOutput' \
  --allow-write
```

The adapter rejects filesystem roots, missing directories, relative Sandbox paths, parent traversal, unknown Sandbox IDs, generic RDP credentials, and generic RDP connection options.

## Development

Run the focused validation suite:

```sh
python scripts/validate_release.py
python -m unittest discover \
  -s plugins/windows-sandbox-computer-use/skills/windows-sandbox-computer-use/tests \
  -p 'test_*.py' \
  -v
npx skills add . --list
node --test plugins/windows-sandbox-computer-use/skills/windows-sandbox-computer-use/tests/test_session.mjs
```

The repository contains one canonical skill tree under the plugin. Both the Codex Marketplace and `npx skills` consume that same tree.

## Security

This skill controls an isolated Windows desktop and can expose explicitly selected host directories. Read [SECURITY.md](SECURITY.md) before reporting a vulnerability or enabling writable sharing.

## License

MIT. IronRDP is an external dependency and is not redistributed by this repository.
