#!/usr/bin/env python3
"""Safe, observable Windows Sandbox adapter using wsb and IronRDP Agent."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path, PureWindowsPath
from typing import NoReturn, Sequence
from uuid import UUID


MIN_VERSION = (0, 1, 0)
MAX_CAPTURED_OUTPUT = 16_384
MAX_TEXT_CHARS = 96

# IBM PC/AT Set 1 scancodes as transported by RDP. Extended keys use an E0 prefix.
SCANCODES = {
    "ESC": 0x01,
    "BACKSPACE": 0x0E,
    "TAB": 0x0F,
    "ENTER": 0x1C,
    "CTRL": 0x1D,
    "SHIFT": 0x2A,
    "ALT": 0x38,
    "SPACE": 0x39,
    "CAPSLOCK": 0x3A,
    "F1": 0x3B,
    "F2": 0x3C,
    "F3": 0x3D,
    "F4": 0x3E,
    "F5": 0x3F,
    "F6": 0x40,
    "F7": 0x41,
    "F8": 0x42,
    "F9": 0x43,
    "F10": 0x44,
    "F11": 0x57,
    "F12": 0x58,
    "RCTRL": 0xE01D,
    "RALT": 0xE038,
    "HOME": 0xE047,
    "UP": 0xE048,
    "PAGEUP": 0xE049,
    "LEFT": 0xE04B,
    "RIGHT": 0xE04D,
    "END": 0xE04F,
    "DOWN": 0xE050,
    "PAGEDOWN": 0xE051,
    "INSERT": 0xE052,
    "DELETE": 0xE053,
}

SCANCODES.update({str(index): 0x01 + index for index in range(1, 10)})
SCANCODES["0"] = 0x0B
SCANCODES.update(
    {
        "Q": 0x10, "W": 0x11, "E": 0x12, "R": 0x13, "T": 0x14,
        "Y": 0x15, "U": 0x16, "I": 0x17, "O": 0x18, "P": 0x19,
        "A": 0x1E, "S": 0x1F, "D": 0x20, "F": 0x21, "G": 0x22,
        "H": 0x23, "J": 0x24, "K": 0x25, "L": 0x26,
        "Z": 0x2C, "X": 0x2D, "C": 0x2E, "V": 0x2F, "B": 0x30,
        "N": 0x31, "M": 0x32,
    }
)


class AdapterError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def _bounded(value: str) -> str:
    value = value.strip()
    if len(value) <= MAX_CAPTURED_OUTPUT:
        return value
    return value[:MAX_CAPTURED_OUTPUT] + "...<truncated>"


def _emit(operation: str, **details: object) -> None:
    # ASCII-only JSON survives Windows console code pages and remains lossless after JSON decoding.
    print(json.dumps({"ok": True, "operation": operation, **details}, ensure_ascii=True))


def _fail(operation: str, error: Exception) -> NoReturn:
    category = error.category if isinstance(error, AdapterError) else "adapter_error"
    payload = {
        "ok": False,
        "operation": operation,
        "category": category,
        "message": _bounded(str(error)),
    }
    print(json.dumps(payload, ensure_ascii=True), file=sys.stderr)
    raise SystemExit(1)


def _binary() -> str:
    configured = os.environ.get("IRONRDP_AGENT_BIN")
    if configured:
        return configured
    discovered = shutil.which("ironrdp-agent")
    if discovered:
        return discovered
    cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")).expanduser()
    candidate = cargo_home / "bin" / ("ironrdp-agent.exe" if os.name == "nt" else "ironrdp-agent")
    return str(candidate) if candidate.is_file() else "ironrdp-agent"


def _base_args(args: argparse.Namespace) -> list[str]:
    command = [_binary()]
    endpoint = getattr(args, "endpoint", None) or os.environ.get("IRONRDP_AGENT_ENDPOINT")
    if endpoint:
        command.extend(["--endpoint", endpoint])
    command.extend(["--backend", "daemon"])
    return command


def _run(
    args: argparse.Namespace,
    command: Sequence[str],
    *,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    argv = [*_base_args(args), *command]
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError as error:
        raise AdapterError("dependency_missing", f"ironrdp-agent executable not found: {_binary()}") from error
    except subprocess.TimeoutExpired as error:
        raise AdapterError("timeout", f"ironrdp-agent timed out after {timeout:g}s") from error
    if result.returncode != 0:
        message = _bounded(result.stderr or result.stdout or f"ironrdp-agent exited {result.returncode}")
        raise AdapterError("ironrdp_error", message)
    return result


def _state_dir() -> Path:
    configured = os.environ.get("IRONRDP_CUA_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        if not root:
            raise AdapterError("state_unavailable", "LOCALAPPDATA is unavailable; set IRONRDP_CUA_STATE_DIR")
        return Path(root) / "Codex" / "windows-sandbox-computer-use"
    root = os.environ.get("XDG_STATE_HOME")
    return (Path(root).expanduser() if root else Path.home() / ".local" / "state") / "codex" / "windows-sandbox-computer-use"


def _parse_version(text: str) -> tuple[int, int, int]:
    match = re.search(r"(?:ironrdp-agent\s+)?(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        raise AdapterError("incompatible_dependency", f"unable to parse ironrdp-agent version: {_bounded(text)}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _raw_binary(command: Sequence[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            [_binary(), *command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError as error:
        raise AdapterError("dependency_missing", f"ironrdp-agent executable not found: {_binary()}") from error
    except subprocess.TimeoutExpired as error:
        raise AdapterError("timeout", f"ironrdp-agent timed out after {timeout:g}s") from error
    if result.returncode != 0:
        raise AdapterError("ironrdp_error", _bounded(result.stderr or result.stdout))
    return result


def cmd_doctor(args: argparse.Namespace) -> None:
    version_result = _raw_binary(["--version"])
    version = _parse_version(version_result.stdout or version_result.stderr)
    if version < MIN_VERSION:
        raise AdapterError(
            "incompatible_dependency",
            f"ironrdp-agent {'.'.join(map(str, version))} is older than required {'.'.join(map(str, MIN_VERSION))}",
        )
    help_text = _raw_binary(["--help-agent"]).stdout
    required = ("daemon-start", "screenshot", "type-unicode", "sandbox start", "--sandbox-id")
    missing = [token for token in required if token not in help_text]
    if missing:
        raise AdapterError("incompatible_dependency", f"ironrdp-agent help is missing: {', '.join(missing)}")
    wsb, wsb_version, environments = _sandbox_bootstrap(require_share=True)
    _emit(
        "doctor",
        ironrdp_version=".".join(map(str, version)),
        ironrdp_binary=_binary(),
        wsb_binary=wsb,
        wsb_version=wsb_version,
        running_sandboxes=len(environments),
        capabilities=["sandbox-lifecycle", "sandbox-share", "screenshot", "remote-input"],
    )


def cmd_status(args: argparse.Namespace) -> None:
    result = _run(args, ["status"], timeout=10)
    _emit("status", status=_bounded(result.stdout))


def _session_state(status: str) -> str:
    for line in status.splitlines():
        if line.lower().startswith("state:"):
            state = line.split(":", 1)[1].strip()
            if state:
                return state
    raise AdapterError("invalid_status", "ironrdp-agent status did not include a state")


def cmd_wait_connected(args: argparse.Namespace) -> None:
    deadline = time.monotonic() + args.timeout
    connected_since: float | None = None
    last_status = ""
    while time.monotonic() < deadline:
        result = _run(args, ["status"], timeout=min(5, args.timeout))
        last_status = result.stdout
        state = _session_state(last_status)
        if state == "Connected":
            if connected_since is None:
                connected_since = time.monotonic()
            if time.monotonic() - connected_since >= args.stable_seconds:
                _emit("wait-connected", state=state, stable_seconds=args.stable_seconds, status=_bounded(last_status))
                return
        else:
            connected_since = None
            if state in {"Failed", "NoSession", "Disconnected"}:
                raise AdapterError("session_terminal", _bounded(last_status))
        time.sleep(0.25)
    raise AdapterError("session_not_ready", f"connection was not stable before timeout; last status: {_bounded(last_status)}")


def cmd_daemon_start(args: argparse.Namespace) -> None:
    try:
        _run(args, ["status"], timeout=3)
    except AdapterError as error:
        if error.category in {"dependency_missing", "timeout"}:
            raise
    else:
        raise AdapterError("daemon_conflict", "an ironrdp-agent daemon is already available; reuse it")
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / "daemon.log"
    metadata_path = state_dir / "daemon.json"
    command = [*_base_args(args), "daemon-start"]
    log_handle = log_path.open("ab", buffering=0)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            shell=False,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
    except FileNotFoundError as error:
        log_handle.close()
        raise AdapterError("dependency_missing", f"ironrdp-agent executable not found: {_binary()}") from error
    finally:
        log_handle.close()
    try:
        metadata_path.write_text(
            json.dumps({"pid": process.pid, "started_at": time.time(), "log": str(log_path)}),
            encoding="utf-8",
        )
    except OSError:
        process.terminate()
        process.wait(timeout=5)
        raise
    deadline = time.monotonic() + args.wait_seconds
    last_error = "daemon did not become ready"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            last_error = f"daemon exited with code {process.returncode}; inspect {log_path}"
            break
        try:
            _run(args, ["status"], timeout=2)
            _emit("daemon-start", pid=process.pid, log=str(log_path), state=str(metadata_path))
            return
        except AdapterError as error:
            last_error = str(error)
            time.sleep(0.25)
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    raise AdapterError("daemon_start_failed", f"{last_error}; daemon stopped; log: {log_path}")


def _sandbox_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as error:
        raise AdapterError("invalid_input", "sandbox id must be a UUID") from error


def _require_running_sandbox(environments: Sequence[object], sandbox_id: str) -> None:
    running_ids = {
        str(environment.get("Id", "")).lower()
        for environment in environments
        if isinstance(environment, dict)
    }
    if sandbox_id.lower() not in running_ids:
        raise AdapterError("sandbox_not_found", f"sandbox is not running: {sandbox_id}")


def cmd_sandbox_connect(args: argparse.Namespace) -> None:
    _wsb, _version, environments = _sandbox_bootstrap()
    sandbox_id = _sandbox_id(args.id)
    _require_running_sandbox(environments, sandbox_id)
    result = _run(args, ["connect", "--sandbox-id", sandbox_id], timeout=args.timeout)
    _emit("sandbox-connect", sandbox_id=sandbox_id, response=_bounded(result.stdout))


def _host_run(command: Sequence[str], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError as error:
        raise AdapterError("dependency_missing", f"host executable not found: {command[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise AdapterError("timeout", f"host command timed out after {timeout:g}s") from error
    if result.returncode != 0:
        raise AdapterError("host_command_error", _bounded(result.stderr or result.stdout))
    return result


def _wsb_binary() -> str:
    if os.name != "nt":
        raise AdapterError("unsupported_platform", "Windows Sandbox is available only on Windows")
    wsb = shutil.which("wsb.exe") or shutil.which("wsb")
    if not wsb:
        raise AdapterError(
            "sandbox_upgrade_required",
            "wsb is unavailable; upgrade to the Store-delivered Windows Sandbox runtime",
        )
    return wsb


def _sandbox_bootstrap(*, require_share: bool = False) -> tuple[str, str, list[object]]:
    wsb = _wsb_binary()
    version = _bounded(_host_run([wsb, "--version"], timeout=10).stdout)
    if require_share:
        share_help = _host_run([wsb, "share", "--help"], timeout=10).stdout
        required = ("--host-path", "--sandbox-path", "--allow-write", "--raw")
        missing = [option for option in required if option not in share_help]
        if missing:
            raise AdapterError(
                "sandbox_upgrade_required",
                f"wsb share is missing required options: {', '.join(missing)}",
            )
    raw = _host_run([wsb, "list", "--raw"], timeout=20).stdout
    try:
        payload = json.loads(raw)
        environments = payload["WindowsSandboxEnvironments"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise AdapterError("sandbox_bootstrap_failed", "wsb list returned an incompatible JSON document") from error
    if not isinstance(environments, list):
        raise AdapterError("sandbox_bootstrap_failed", "wsb environment list is not an array")
    return wsb, version, environments


def cmd_simple(args: argparse.Namespace, operation: str, command: Sequence[str], timeout: float = 30) -> None:
    result = _run(args, command, timeout=timeout)
    _emit(operation, response=_bounded(result.stdout))


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise AdapterError("invalid_screenshot", "ironrdp-agent did not write a valid PNG")
    return struct.unpack(">II", header[16:24])


def cmd_screenshot(args: argparse.Namespace) -> None:
    path = Path(args.path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not args.overwrite:
        raise AdapterError("output_exists", f"screenshot path already exists: {path}")
    status = _run(args, ["status"], timeout=10).stdout
    state = _session_state(status)
    if state != "Connected" and not args.allow_stale:
        raise AdapterError("session_not_connected", f"refusing cached screenshot while session state is {state}")
    _run(args, ["screenshot", str(path)], timeout=args.timeout)
    width, height = _png_dimensions(path)
    _emit(
        "screenshot",
        path=str(path),
        width=width,
        height=height,
        bytes=path.stat().st_size,
        session_state=state,
        stale=state != "Connected",
    )


def _coordinate(value: int, name: str) -> str:
    if not 0 <= value <= 65_535:
        raise AdapterError("invalid_input", f"{name} must be between 0 and 65535")
    return str(value)


def _mouse_button(args: argparse.Namespace, button: str, pressed: bool) -> None:
    _run(args, ["mouse-button", "--button", button, "--pressed", str(pressed).lower()], timeout=10)


def cmd_click(args: argparse.Namespace) -> None:
    _run(args, ["mouse-move", "--x", _coordinate(args.x, "x"), "--y", _coordinate(args.y, "y")], timeout=10)
    for completed in range(args.count):
        _mouse_button(args, args.button, True)
        try:
            _mouse_button(args, args.button, False)
        except AdapterError as error:
            raise AdapterError(
                "input_outcome_unknown",
                f"mouse release failed after press; {completed} earlier click(s) completed: {error}",
            ) from error
    _emit("click", x=args.x, y=args.y, button=args.button, count=args.count)


def cmd_drag(args: argparse.Namespace) -> None:
    start = ["mouse-move", "--x", _coordinate(args.from_x, "from-x"), "--y", _coordinate(args.from_y, "from-y")]
    _run(args, start, timeout=10)
    _mouse_button(args, args.button, True)
    try:
        for step in range(1, args.steps + 1):
            x = round(args.from_x + (args.to_x - args.from_x) * step / args.steps)
            y = round(args.from_y + (args.to_y - args.from_y) * step / args.steps)
            _run(args, ["mouse-move", "--x", _coordinate(x, "x"), "--y", _coordinate(y, "y")], timeout=10)
            if args.duration_ms:
                time.sleep(args.duration_ms / args.steps / 1000)
    except Exception as error:
        try:
            _mouse_button(args, args.button, False)
        except Exception as release_error:
            raise AdapterError("input_outcome_unknown", f"drag and release failed: {error}; release: {release_error}") from error
        raise AdapterError("input_outcome_unknown", f"drag failed after mouse press: {error}") from error
    try:
        _mouse_button(args, args.button, False)
    except AdapterError as error:
        raise AdapterError("input_outcome_unknown", f"mouse release failed after drag: {error}") from error
    _emit("drag", from_x=args.from_x, from_y=args.from_y, to_x=args.to_x, to_y=args.to_y, button=args.button)


def cmd_scroll(args: argparse.Namespace) -> None:
    if (args.x is None) != (args.y is None):
        raise AdapterError("invalid_input", "scroll x and y must be supplied together")
    if args.x is not None:
        _run(args, ["mouse-move", "--x", _coordinate(args.x, "x"), "--y", _coordinate(args.y, "y")], timeout=10)
    command = ["wheel", "--delta", str(args.delta)]
    if args.horizontal:
        command.append("--horizontal")
    _run(args, command, timeout=10)
    _emit("scroll", delta=args.delta, horizontal=args.horizontal, x=args.x, y=args.y)


def _key_event(args: argparse.Namespace, scancode: int, pressed: bool) -> None:
    _run(args, ["key-scancode", "--scancode", hex(scancode), "--pressed", str(pressed).lower()], timeout=10)


def _key_code(name: str) -> int:
    normalized = name.strip().upper()
    aliases = {"RETURN": "ENTER", "CONTROL": "CTRL", "ESCAPE": "ESC", "DEL": "DELETE", "PGUP": "PAGEUP", "PGDN": "PAGEDOWN"}
    normalized = aliases.get(normalized, normalized)
    try:
        return SCANCODES[normalized]
    except KeyError as error:
        raise AdapterError("invalid_input", f"unsupported key name: {name}") from error


def cmd_key(args: argparse.Namespace) -> None:
    code = _key_code(args.name)
    _key_event(args, code, True)
    try:
        _key_event(args, code, False)
    except AdapterError as error:
        raise AdapterError("input_outcome_unknown", f"key release failed after press: {error}") from error
    _emit("key", key=args.name.upper())


def cmd_hotkey(args: argparse.Namespace) -> None:
    names = [name.strip() for name in args.keys.split(",") if name.strip()]
    if not 2 <= len(names) <= 4:
        raise AdapterError("invalid_input", "hotkey requires 2 to 4 comma-separated keys")
    if len({name.upper() for name in names}) != len(names):
        raise AdapterError("invalid_input", "hotkey must not contain duplicate keys")
    codes = [_key_code(name) for name in names]
    pressed: list[int] = []
    try:
        for code in codes:
            _key_event(args, code, True)
            pressed.append(code)
        for code in reversed(codes):
            _key_event(args, code, False)
            pressed.remove(code)
    except AdapterError as error:
        cleanup_errors: list[str] = []
        for code in reversed(pressed):
            try:
                _key_event(args, code, False)
            except AdapterError as cleanup_error:
                cleanup_errors.append(str(cleanup_error))
        suffix = f"; cleanup failed: {'; '.join(cleanup_errors)}" if cleanup_errors else ""
        raise AdapterError("input_outcome_unknown", f"hotkey failed after partial input: {error}{suffix}") from error
    _emit("hotkey", keys=[name.upper() for name in names])


def cmd_type(args: argparse.Namespace) -> None:
    if not args.text:
        raise AdapterError("invalid_input", "text must not be empty")
    chunks = [args.text[index:index + MAX_TEXT_CHARS] for index in range(0, len(args.text), MAX_TEXT_CHARS)]
    completed = 0
    try:
        for chunk in chunks:
            _run(args, ["type-unicode", "--text", chunk], timeout=15)
            completed += len(chunk)
    except AdapterError as error:
        raise AdapterError("partial_input", f"typing failed after {completed} characters may have been entered: {error}") from error
    _emit("type", characters=len(args.text), requests=len(chunks))


def cmd_sandbox_start(args: argparse.Namespace) -> None:
    _sandbox_bootstrap()
    command = ["sandbox", "start"]
    if args.id:
        command.extend(["--id", _sandbox_id(args.id)])
    if args.config:
        command.extend(["--config", str(Path(args.config).expanduser().resolve(strict=True))])
    cmd_simple(args, "sandbox-start", command, timeout=args.timeout)


def cmd_sandbox_list(args: argparse.Namespace) -> None:
    _wsb, version, environments = _sandbox_bootstrap()
    _emit("sandbox-list", wsb_version=version, count=len(environments), environments=environments)


def cmd_sandbox_config(args: argparse.Namespace) -> None:
    _wsb, _version, environments = _sandbox_bootstrap()
    sandbox_id = _sandbox_id(args.id)
    _require_running_sandbox(environments, sandbox_id)
    cmd_simple(args, "sandbox-config", ["sandbox", "config", sandbox_id], timeout=15)


def _sandbox_path(value: str) -> str:
    path = PureWindowsPath(value)
    if not re.fullmatch(r"[A-Za-z]:\\.*", value) or not path.is_absolute():
        raise AdapterError("invalid_input", "sandbox path must be an absolute drive path such as C:\\DebugWorkspace")
    if ".." in path.parts:
        raise AdapterError("invalid_input", "sandbox path must not contain parent traversal")
    if path == PureWindowsPath(path.anchor):
        raise AdapterError("invalid_input", "sandbox path must not be a filesystem root")
    return str(path)


def _shared_host_directory(value: str) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise AdapterError("invalid_input", "host path must be an existing directory")
    if path.parent == path:
        raise AdapterError("invalid_input", "host path must not be a filesystem root")
    return path


def cmd_sandbox_share(args: argparse.Namespace) -> None:
    wsb, _version, environments = _sandbox_bootstrap(require_share=True)
    sandbox_id = _sandbox_id(args.id)
    _require_running_sandbox(environments, sandbox_id)
    host_path = _shared_host_directory(args.host_path)
    sandbox_path = _sandbox_path(args.sandbox_path)
    command = [
        wsb,
        "share",
        "--id",
        sandbox_id,
        "--host-path",
        str(host_path),
        "--sandbox-path",
        sandbox_path,
    ]
    if args.allow_write:
        command.append("--allow-write")
    command.append("--raw")
    result = _host_run(command, timeout=args.timeout)
    _emit(
        "sandbox-share",
        sandbox_id=sandbox_id,
        host_path=str(host_path),
        sandbox_path=sandbox_path,
        mode="read-write" if args.allow_write else "read-only",
        response=_bounded(result.stdout),
    )


def cmd_sandbox_stop(args: argparse.Namespace) -> None:
    _wsb, _version, environments = _sandbox_bootstrap()
    sandbox_id = _sandbox_id(args.id)
    _require_running_sandbox(environments, sandbox_id)
    cmd_simple(args, "sandbox-stop", ["sandbox", "stop", sandbox_id], timeout=30)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", help="explicit ironrdp-agent IPC endpoint")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    subparsers.add_parser("doctor").set_defaults(handler=cmd_doctor)
    subparsers.add_parser("status").set_defaults(handler=cmd_status)
    wait_connected = subparsers.add_parser("wait-connected")
    wait_connected.add_argument("--timeout", type=float, default=30)
    wait_connected.add_argument("--stable-seconds", type=float, default=2)
    wait_connected.set_defaults(handler=cmd_wait_connected)

    daemon = subparsers.add_parser("daemon-start")
    daemon.add_argument("--wait-seconds", type=float, default=10)
    daemon.set_defaults(handler=cmd_daemon_start)

    connect = subparsers.add_parser("sandbox-connect")
    connect.add_argument("--id", required=True)
    connect.add_argument("--timeout", type=float, default=45)
    connect.set_defaults(handler=cmd_sandbox_connect)

    subparsers.add_parser("disconnect").set_defaults(
        handler=lambda args: cmd_simple(args, "disconnect", ["disconnect"], timeout=15)
    )

    screenshot = subparsers.add_parser("screenshot")
    screenshot.add_argument("path")
    screenshot.add_argument("--timeout", type=float, default=15)
    screenshot.add_argument("--overwrite", action="store_true")
    screenshot.add_argument("--allow-stale", action="store_true", help="diagnostic-only cached frame")
    screenshot.set_defaults(handler=cmd_screenshot)

    click = subparsers.add_parser("click")
    click.add_argument("--x", type=int, required=True)
    click.add_argument("--y", type=int, required=True)
    click.add_argument("--button", choices=("left", "middle", "right", "x1", "x2"), default="left")
    click.add_argument("--count", type=int, choices=range(1, 4), default=1)
    click.set_defaults(handler=cmd_click)

    drag = subparsers.add_parser("drag")
    drag.add_argument("--from-x", type=int, required=True)
    drag.add_argument("--from-y", type=int, required=True)
    drag.add_argument("--to-x", type=int, required=True)
    drag.add_argument("--to-y", type=int, required=True)
    drag.add_argument("--button", choices=("left", "middle", "right"), default="left")
    drag.add_argument("--steps", type=int, choices=range(1, 101), default=12)
    drag.add_argument("--duration-ms", type=int, choices=range(0, 10_001), default=250)
    drag.set_defaults(handler=cmd_drag)

    scroll = subparsers.add_parser("scroll")
    scroll.add_argument("--delta", type=int, choices=range(-32_768, 32_768), required=True)
    scroll.add_argument("--horizontal", action="store_true")
    scroll.add_argument("--x", type=int)
    scroll.add_argument("--y", type=int)
    scroll.set_defaults(handler=cmd_scroll)

    key = subparsers.add_parser("key")
    key.add_argument("--name", required=True)
    key.set_defaults(handler=cmd_key)

    hotkey = subparsers.add_parser("hotkey")
    hotkey.add_argument("--keys", required=True, help="2-4 comma-separated key names")
    hotkey.set_defaults(handler=cmd_hotkey)

    type_parser = subparsers.add_parser("type")
    type_parser.add_argument("--text", required=True)
    type_parser.set_defaults(handler=cmd_type)

    logs = subparsers.add_parser("logs")
    logs.add_argument("--last", type=int, choices=range(1, 1001), default=100)
    logs.add_argument("--substring")
    subparsers.choices["logs"].set_defaults(
        handler=lambda args: cmd_simple(
            args,
            "logs",
            ["query-logs", "--last", str(args.last)]
            + (["--substring", args.substring] if args.substring else []),
            timeout=15,
        )
    )

    subparsers.add_parser("sandbox-list").set_defaults(handler=cmd_sandbox_list)
    sandbox_start = subparsers.add_parser("sandbox-start")
    sandbox_start.add_argument("--id")
    sandbox_start.add_argument("--config")
    sandbox_start.add_argument("--timeout", type=float, default=45)
    sandbox_start.set_defaults(handler=cmd_sandbox_start)

    sandbox_config = subparsers.add_parser("sandbox-config")
    sandbox_config.add_argument("id")
    sandbox_config.set_defaults(handler=cmd_sandbox_config)

    sandbox_share = subparsers.add_parser("sandbox-share")
    sandbox_share.add_argument("--id", required=True)
    sandbox_share.add_argument("--host-path", required=True)
    sandbox_share.add_argument("--sandbox-path", required=True)
    sandbox_share.add_argument("--allow-write", action="store_true")
    sandbox_share.add_argument("--timeout", type=float, default=30)
    sandbox_share.set_defaults(handler=cmd_sandbox_share)

    sandbox_stop = subparsers.add_parser("sandbox-stop")
    sandbox_stop.add_argument("id")
    sandbox_stop.set_defaults(handler=cmd_sandbox_stop)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except (AdapterError, OSError, ValueError) as error:
        _fail(args.operation, error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
