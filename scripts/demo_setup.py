"""Dependency preflight and safe, idempotent local configuration for the launcher."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import secrets
import sys
from pathlib import Path

from core.configuration import (
    OPTIONAL_DEFAULTS,
    PUBLIC_DEFAULTS,
    STORAGE_FILES,
    validate_auth_values,
)


def check_dependencies(root: Path) -> list[str]:
    failures = []
    for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, expected = line.strip().split("==", 1)
        try:
            if importlib.metadata.version(name) != expected:
                failures.append(name)
        except importlib.metadata.PackageNotFoundError:
            failures.append(name)
    if not failures:
        for module in (
            "fastapi",
            "uvicorn",
            "openai",
            "dotenv",
            "pydantic",
            "pypdf",
            "docx",
            "python_multipart",
            "cryptography.hazmat.primitives.asymmetric.ed25519",
            "discord",
        ):
            try:
                importlib.import_module(module)
            except (ImportError, OSError):
                failures.append(module)
    return failures


def _data_directory(root: Path, values: dict[str, str | None]) -> str:
    explicit = values.get("DATA_DIR")
    legacy = {key: values[key] for key in STORAGE_FILES if values.get(key)}

    def resolve(value: str) -> Path:
        return (root / value).resolve()

    if explicit:
        directory = resolve(explicit)
        if any(resolve(value) != directory / STORAGE_FILES[key] for key, value in legacy.items()):
            raise ValueError("DATA_DIR conflicts with legacy storage paths; .env was not changed.")
        return explicit
    if legacy:
        paths = {
            key: resolve(values.get(key) or f"data/{filename}")
            for key, filename in STORAGE_FILES.items()
        }
        parents = {path.parent for path in paths.values()}
        if len(parents) != 1 or any(paths[key].name != name for key, name in STORAGE_FILES.items()):
            raise ValueError(
                "Legacy storage paths are not in one folder. Set DATA_DIR only after consolidating "
                "them, or use explicit process environment overrides. .env was not changed."
            )
        directory = parents.pop()
        return (
            os.path.relpath(directory, root) if directory.is_relative_to(root) else str(directory)
        )

    populated = [
        name
        for name in ("data", ".demo_state")
        if any((root / name / filename).exists() for filename in STORAGE_FILES.values())
    ]
    if len(populated) > 1:
        raise ValueError("Both data and .demo_state contain data. Select DATA_DIR in .env first.")
    return populated[0] if populated else PUBLIC_DEFAULTS["DATA_DIR"]


def configure(root: Path, environment: dict[str, str]) -> dict[str, str]:
    from dotenv import dotenv_values
    from dotenv.parser import parse_stream

    from storage.text_store import write_text

    path = root / ".env"
    values: dict[str, str | None] = {}
    if path.exists():
        with path.open(encoding="utf-8-sig") as handle:
            if any(binding.error for binding in parse_stream(handle)):
                raise ValueError("Invalid .env syntax. Fix the file; it was not changed.")
        values = dict(dotenv_values(path, encoding="utf-8-sig", interpolate=False))

    # Remove only redundant legacy options, never silently lose custom settings.
    legacy_defaults = {**OPTIONAL_DEFAULTS, "VITE_API_URL": "http://127.0.0.1:8000"}
    for key, value in values.items():
        if key in PUBLIC_DEFAULTS or key in STORAGE_FILES:
            continue
        if key not in legacy_defaults or value not in (None, "", legacy_defaults[key]):
            raise ValueError(
                f"Custom setting {key} cannot be removed automatically. Use a process environment "
                "override for this advanced setting, then remove it from .env. File unchanged."
            )

    result = {key: values.get(key) or default for key, default in PUBLIC_DEFAULTS.items()}
    result["DATA_DIR"] = _data_directory(root, values)
    result["DEMO_LOGIN_PASSWORD"] = result["DEMO_LOGIN_PASSWORD"] or secrets.token_urlsafe(18)
    result["DEMO_AUTH_SECRET"] = result["DEMO_AUTH_SECRET"] or secrets.token_urlsafe(32)
    validate_auth_values(result["DEMO_AUTH_SECRET"].strip(), result["DEMO_LOGIN_PASSWORD"].strip())
    effective = {key: environment.get(key, value) for key, value in result.items()}
    validate_auth_values(
        effective["DEMO_AUTH_SECRET"].strip(), effective["DEMO_LOGIN_PASSWORD"].strip()
    )

    def quote(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    content = "# Local configuration. Do not commit this file.\n"
    content += "\n".join(f"{key}={quote(value)}" for key, value in result.items()) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8-sig") != content:
        write_text(path, content)
    return effective


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check-deps", "configure"))
    parser.add_argument("--json", action="store_true", help="Emit credentials for launcher capture")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.action == "check-deps":
        failures = check_dependencies(root)
        if failures:
            print("Python packages need installation: " + ", ".join(failures))
            return 1
    else:
        try:
            # JSON is captured by the launcher, never logged or evaluated as shell code.
            values = configure(root, dict(os.environ))
            if args.json:
                print(json.dumps(values, ensure_ascii=True))
            else:
                print("Configuration ready. Find DEMO_LOGIN_PASSWORD in your local .env.")
        except (ValueError, OSError) as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
