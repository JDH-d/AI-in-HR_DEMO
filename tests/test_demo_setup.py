import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

from core.configuration import OPTIONAL_DEFAULTS, PUBLIC_DEFAULTS, STORAGE_FILES
from scripts.demo_setup import configure


def read_env(root):
    return dict(dotenv_values(root / ".env", interpolate=False))


def test_first_run_generates_unique_credentials_and_second_run_keeps_them(tmp_path):
    first = configure(tmp_path, {})
    assert set(first) == set(PUBLIC_DEFAULTS)
    assert first["OPENAI_API_KEY"] == ""
    assert len(first["DEMO_AUTH_SECRET"]) >= 32
    assert len(first["DEMO_LOGIN_PASSWORD"]) >= 20
    before = (tmp_path / ".env").stat().st_mtime_ns
    assert configure(tmp_path, {}) == first == read_env(tmp_path)
    assert (tmp_path / ".env").stat().st_mtime_ns == before
    another = tmp_path / "another"
    another.mkdir()
    assert configure(another, {})["DEMO_AUTH_SECRET"] != first["DEMO_AUTH_SECRET"]
    assert list(tmp_path.glob("*.db")) == []


def test_legacy_config_keeps_credentials_and_all_existing_data(tmp_path):
    directory = tmp_path / ".demo_state"
    directory.mkdir()
    for filename in STORAGE_FILES.values():
        (directory / filename).write_bytes(b"existing data")
    lines = [f"{key}={value}" for key, value in OPTIONAL_DEFAULTS.items()]
    lines += [f"{key}=.demo_state/{name}" for key, name in STORAGE_FILES.items()]
    lines += ["OPENAI_API_KEY=synthetic-key", "DEMO_AUTH_SECRET=" + "x" * 40]
    lines += ["DEMO_LOGIN_PASSWORD=existing-password", "OPENAI_MODEL=existing-model"]
    (tmp_path / ".env").write_text("\n".join(lines), encoding="utf-8")
    values = configure(tmp_path, {})
    assert len(read_env(tmp_path)) == 5
    assert values["DATA_DIR"] == ".demo_state"
    assert values["DEMO_AUTH_SECRET"] == "x" * 40
    assert values["DEMO_LOGIN_PASSWORD"] == "existing-password"
    assert values["OPENAI_API_KEY"] == "synthetic-key"
    assert values["OPENAI_MODEL"] == "existing-model"
    assert all(path.read_bytes() == b"existing data" for path in directory.iterdir())


@pytest.mark.parametrize(
    "entry",
    [
        "UNKNOWN_SETTING=custom",
        "OPENAI_TIMEOUT_SECONDS=99",
        "WORKFLOW_DB=somewhere/workflow.db",
        "DATA_DIR=data\nWORKFLOW_DB=elsewhere/workflow.db",
        "DEMO_AUTH_SECRET=short",
        "DEMO_LOGIN_PASSWORD=demo-password",
        "DEMO_LOGIN_PASSWORD='unterminated",
    ],
)
def test_unsafe_migration_does_not_rewrite_file(tmp_path, entry):
    path = tmp_path / ".env"
    path.write_text(entry, encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        configure(tmp_path, {})
    assert path.read_bytes() == before


def test_existing_data_is_discovered_without_env_and_ambiguity_is_rejected(tmp_path):
    legacy = tmp_path / ".demo_state"
    legacy.mkdir()
    (legacy / "workflow.db").write_bytes(b"legacy")
    assert configure(tmp_path, {})["DATA_DIR"] == ".demo_state"
    (tmp_path / ".env").unlink()
    (tmp_path / "data").mkdir()
    (tmp_path / "data/workflow.db").write_bytes(b"new")
    with pytest.raises(ValueError, match="Both"):
        configure(tmp_path, {})
    assert not (tmp_path / ".env").exists()


def test_example_is_secret_free_and_can_bootstrap(tmp_path):
    example = Path(__file__).resolve().parents[1] / ".env.example"
    (tmp_path / ".env").write_bytes(example.read_bytes())
    values = read_env(tmp_path)
    assert len(values) == 5
    assert all(
        not values[key] for key in ("OPENAI_API_KEY", "DEMO_AUTH_SECRET", "DEMO_LOGIN_PASSWORD")
    )
    assert configure(tmp_path, {})["DATA_DIR"] == "data"


def test_literal_special_characters_and_environment_precedence(tmp_path):
    config = configure(tmp_path, {})
    # Dotenv single quotes escape apostrophes and backslashes; shell interpolation is forbidden.
    password = "literal-${HOME}-$()-`quote`-!%&-пароль-\\-end"
    path = tmp_path / ".env"
    path.write_text(
        "DEMO_LOGIN_PASSWORD='"
        + password.replace("\\", "\\\\")
        + "'\n"
        + f"DEMO_AUTH_SECRET={config['DEMO_AUTH_SECRET']}\n"
        + "DATA_DIR='папка с пробелами'\n",
        encoding="utf-8",
    )
    values = configure(tmp_path, {"OPENAI_MODEL": "environment-model"})
    assert values["DEMO_LOGIN_PASSWORD"] == password
    assert read_env(tmp_path)["DEMO_LOGIN_PASSWORD"] == password
    assert values["OPENAI_MODEL"] == "environment-model"
    assert read_env(tmp_path)["OPENAI_MODEL"] == PUBLIC_DEFAULTS["OPENAI_MODEL"]
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    configure(tmp_path, {})
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_settings_derive_storage_paths_and_honor_advanced_overrides(tmp_path):
    environment = dict(os.environ)
    for key in STORAGE_FILES:
        environment.pop(key, None)
    environment.update(PYTHON_DOTENV_DISABLED="1", DATA_DIR=str(tmp_path / "данные с пробелами"))
    environment["LOG_PATH"] = str(tmp_path / "separate.jsonl")
    code = (
        "import json; from core import settings; from core.configuration import STORAGE_FILES; "
        "print(json.dumps({key: str(getattr(settings, key)) for key in STORAGE_FILES}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=environment, capture_output=True, check=True
    )
    paths = json.loads(result.stdout)
    for key, name in STORAGE_FILES.items():
        expected = (
            tmp_path / "separate.jsonl"
            if key == "LOG_PATH"
            else Path(environment["DATA_DIR"]) / name
        )
        assert Path(paths[key]) == expected
