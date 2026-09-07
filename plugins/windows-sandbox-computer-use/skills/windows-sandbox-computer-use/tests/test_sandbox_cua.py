from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "sandbox_cua.py"
SPEC = importlib.util.spec_from_file_location("sandbox_cua", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


SANDBOX_ID = "12345678-1234-1234-1234-1234567890ab"


def completed(stdout: str = "ok\n") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["tool"], 0, stdout=stdout, stderr="")


class AdapterTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows known-folder API")
    def test_state_directory_without_localappdata(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            directory = MODULE._state_dir()
        self.assertTrue(directory.is_absolute())
        self.assertEqual(directory.name, "windows-sandbox-computer-use")
        self.assertTrue(directory.parent.parent.is_dir())

    def test_keysym_aliases_and_duplicate_alias_rejection(self) -> None:
        self.assertEqual(MODULE._key_code("Control_L"), 0x1D)
        self.assertEqual(MODULE._key_code("Alt_R"), 0xE038)
        with patch.object(MODULE, "_run") as run, redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.main(["hotkey", "--keys", "CTRL,Control_L"])
            run.assert_not_called()

    def test_control_text_rejected_before_input(self) -> None:
        with patch.object(MODULE, "_run") as run, redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.main(["type", "--text", "hello\n"])
            run.assert_not_called()

    def test_key_aliases_and_extended_scancodes(self) -> None:
        self.assertEqual(MODULE._key_code("return"), 0x1C)
        self.assertEqual(MODULE._key_code("delete"), 0xE053)
        with self.assertRaises(MODULE.AdapterError):
            MODULE._key_code("windows")

    def test_type_is_chunked_at_protocol_limit(self) -> None:
        calls: list[list[str]] = []

        def fake_run(_args, command, **_kwargs):
            calls.append(list(command))
            return completed()

        output = StringIO()
        with patch.object(MODULE, "_run", side_effect=fake_run), redirect_stdout(output):
            exit_code = MODULE.main(["type", "--text", "x" * 193])
        self.assertEqual(exit_code, 0)
        self.assertEqual([len(call[-1]) for call in calls], [96, 96, 1])
        self.assertEqual(json.loads(output.getvalue())["characters"], 193)

    def test_generic_rdp_interfaces_are_not_exposed(self) -> None:
        parser = MODULE.build_parser()
        rejected = (
            ["connect", "--server", "host"],
            ["sandbox-connect", "--id", SANDBOX_ID, "--username", "operator"],
            ["daemon-start", "--overlay", "credentials.rdp"],
        )
        for arguments in rejected:
            with self.subTest(arguments=arguments), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(arguments)

    def test_sandbox_paths_are_absolute_scoped_and_traversal_free(self) -> None:
        self.assertEqual(MODULE._sandbox_path(r"C:\DebugWorkspace"), r"C:\DebugWorkspace")
        for value in (r"DebugWorkspace", "C:\\", r"C:\Debug\..\Escape", r"\\server\share"):
            with self.subTest(value=value), self.assertRaises(MODULE.AdapterError):
                MODULE._sandbox_path(value)

    def test_sandbox_share_defaults_to_read_only_and_uses_raw_output(self) -> None:
        calls: list[list[str]] = []

        def fake_host_run(command, **_kwargs):
            calls.append(list(command))
            return completed('{"Shared":true}\n')

        with tempfile.TemporaryDirectory() as directory:
            output = StringIO()
            with (
                patch.object(MODULE, "_sandbox_bootstrap", return_value=("wsb", "0.8.0", [{"Id": SANDBOX_ID}])),
                patch.object(MODULE, "_host_run", side_effect=fake_host_run),
                redirect_stdout(output),
            ):
                exit_code = MODULE.main([
                    "sandbox-share",
                    "--id", SANDBOX_ID,
                    "--host-path", directory,
                    "--sandbox-path", r"C:\DebugWorkspace",
                ])
        self.assertEqual(exit_code, 0)
        self.assertNotIn("--allow-write", calls[0])
        self.assertEqual(calls[0][-1], "--raw")
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "read-only")
        self.assertEqual(payload["sandbox_path"], r"C:\DebugWorkspace")

    def test_sandbox_share_write_mode_is_explicit(self) -> None:
        calls: list[list[str]] = []

        def fake_host_run(command, **_kwargs):
            calls.append(list(command))
            return completed()

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(MODULE, "_sandbox_bootstrap", return_value=("wsb", "0.8.0", [{"Id": SANDBOX_ID}])),
                patch.object(MODULE, "_host_run", side_effect=fake_host_run),
                redirect_stdout(StringIO()),
            ):
                MODULE.main([
                    "sandbox-share",
                    "--id", SANDBOX_ID,
                    "--host-path", directory,
                    "--sandbox-path", r"D:\DebugOutput",
                    "--allow-write",
                ])
        self.assertIn("--allow-write", calls[0])

    def test_png_dimensions_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frame.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + b"\x00\x00\x03\x20\x00\x00\x02\x58")
            self.assertEqual(MODULE._png_dimensions(path), (800, 600))

    def test_session_state_is_required_and_parsed(self) -> None:
        self.assertEqual(MODULE._session_state("state: Connected\nresolution: 1280x720\n"), "Connected")
        with self.assertRaises(MODULE.AdapterError):
            MODULE._session_state("resolution: 1280x720\n")


if __name__ == "__main__":
    unittest.main()
