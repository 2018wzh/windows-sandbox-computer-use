#!/usr/bin/env python3
"""Validate the release layout shared by Codex Marketplace and npx skills."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "windows-sandbox-computer-use"
PLUGIN = ROOT / "plugins" / PLUGIN_NAME
SKILL = PLUGIN / "skills" / PLUGIN_NAME
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing required file: {path.relative_to(ROOT)}")
    except json.JSONDecodeError as error:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {error}")


def require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def validate_manifest() -> None:
    manifest = require_mapping(load_json(MANIFEST), "plugin manifest")
    if manifest.get("name") != PLUGIN_NAME:
        fail("plugin name must match its directory")
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        fail("plugin version must be strict semantic versioning")
    if manifest.get("skills") != "./skills/":
        fail("plugin skills path must be ./skills/")
    author = require_mapping(manifest.get("author"), "plugin author")
    interface = require_mapping(manifest.get("interface"), "plugin interface")
    for label, value in (
        ("description", manifest.get("description")),
        ("author.name", author.get("name")),
        ("interface.displayName", interface.get("displayName")),
        ("interface.shortDescription", interface.get("shortDescription")),
        ("interface.longDescription", interface.get("longDescription")),
        ("interface.developerName", interface.get("developerName")),
        ("interface.category", interface.get("category")),
    ):
        if not isinstance(value, str) or not value.strip():
            fail(f"{label} must be non-empty")


def validate_marketplace() -> None:
    marketplace = require_mapping(load_json(MARKETPLACE), "marketplace")
    if marketplace.get("name") != "windows-sandbox-tools":
        fail("unexpected marketplace name")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1:
        fail("marketplace must contain exactly one plugin")
    entry = require_mapping(plugins[0], "marketplace plugin entry")
    source = require_mapping(entry.get("source"), "marketplace source")
    policy = require_mapping(entry.get("policy"), "marketplace policy")
    if entry.get("name") != PLUGIN_NAME:
        fail("marketplace plugin name mismatch")
    if source != {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"}:
        fail("marketplace source must point to the canonical plugin")
    if policy.get("installation") != "AVAILABLE" or policy.get("authentication") != "ON_INSTALL":
        fail("marketplace policy is incomplete")


def validate_skill() -> None:
    skill_file = SKILL / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail("SKILL.md must start with YAML frontmatter")
    if f"name: {PLUGIN_NAME}" not in text:
        fail("SKILL.md name mismatch")
    if not re.search(r"^description:\s+\S", text, re.MULTILINE):
        fail("SKILL.md description is missing")
    for relative in (
        Path("scripts/sandbox_cua.py"),
        Path("references/workflow.md"),
        Path("scripts/sandbox_session.mjs"),
        Path("references/guidance.md"),
        Path("references/api.md"),
        Path("references/safety.md"),
        Path("references/confirmations.md"),
        Path("tests/test_session.mjs"),
        Path("tests/test_sandbox_cua.py"),
    ):
        if not (SKILL / relative).is_file():
            fail(f"missing skill resource: {relative.as_posix()}")


def main() -> int:
    try:
        validate_manifest()
        validate_marketplace()
        validate_skill()
    except (OSError, ValueError) as error:
        print(f"release validation failed: {error}", file=sys.stderr)
        return 1
    print("release layout is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
