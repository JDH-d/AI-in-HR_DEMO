import json
import os
from unittest.mock import patch

import pytest

from peopleflow_slack import config


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=unrelated-fixture\n"
        "SLACK_BOT_TOKEN=xoxb-fixture\n"
        "SLACK_APP_TOKEN=xapp-fixture\n"
        "SLACK_EMPLOYEE_USER_ID=UDEMO\n"
        "SLACK_TEAM_ID=TDEMO\n"
        "SLACK_APP_ID=ADEMO\n",
        encoding="utf-8",
    )
    with patch.dict(os.environ, {}, clear=True):
        yield tmp_path


def test_root_configuration_works_from_slack_directory_with_minimal_settings(project, monkeypatch):
    slack = project / "slack"
    slack.mkdir()
    (slack / ".env").write_text("SLACK_BOT_TOKEN=obsolete\n", encoding="utf-8")
    monkeypatch.chdir(slack)

    settings = config.Settings.load()

    assert settings.bot_token == "xoxb-fixture"
    assert settings.app_token == "xapp-fixture"
    assert settings.app_id == "ADEMO"
    assert settings.api_url == "http://127.0.0.1:8000"
    assert settings.password == "demo-password"
    assert settings.poll_interval == 8
    assert settings.api_timeout == 90
    assert "xoxb-fixture" not in repr(settings)


def test_process_configuration_overrides_root_file(project, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-process-fixture")
    monkeypatch.setenv("PEOPLEFLOW_API_URL", "http://127.0.0.1:8123/")
    monkeypatch.setenv("DEMO_LOGIN_PASSWORD", "shared-fixture-password")

    settings = config.Settings.load()

    assert settings.bot_token == "xoxb-process-fixture"
    assert settings.api_url == "http://127.0.0.1:8123"
    assert settings.password == "shared-fixture-password"


def test_root_password_is_shared_with_backend(project):
    with (project / ".env").open("a", encoding="utf-8") as env_file:
        env_file.write("DEMO_LOGIN_PASSWORD=shared-fixture-password\n")

    assert config.Settings.load().password == "shared-fixture-password"


def test_windows_utf8_bom_does_not_become_part_of_the_first_setting_name(project):
    path = project / ".env"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines = sorted(lines, key=lambda line: not line.startswith("SLACK_BOT_TOKEN="))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    assert config.Settings.load().bot_token == "xoxb-fixture"
    assert "SLACK_BOT_TOKEN" in os.environ


def test_launcher_address_is_discovered_without_env_setting(project):
    state = project / ".demo_state" / "demo_processes.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"api_url": "http://127.0.0.1:8124"}), encoding="utf-8-sig")

    assert config.Settings.load().api_url == "http://127.0.0.1:8124"


def test_explicit_api_address_takes_precedence_over_discovered_state(project, monkeypatch):
    state = project / ".demo_state" / "demo_processes.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"api_url": "http://127.0.0.1:8124"}), encoding="utf-8")
    monkeypatch.setenv("PEOPLEFLOW_API_URL", "http://127.0.0.1:8125")

    assert config.Settings.load().api_url == "http://127.0.0.1:8125"


def test_explicit_launcher_and_password_overrides_are_preserved(project, monkeypatch):
    state = project / "custom-state.json"
    state.write_text(json.dumps({"api_url": "http://127.0.0.1:8126"}), encoding="utf-8")
    monkeypatch.setenv("PEOPLEFLOW_LAUNCHER_STATE", str(state))
    monkeypatch.setenv("PEOPLEFLOW_API_URL", "http://127.0.0.1:8125")
    monkeypatch.setenv("DEMO_LOGIN_PASSWORD", "shared-fixture-password")
    monkeypatch.setenv("PEOPLEFLOW_DEMO_PASSWORD", "override-fixture-password")

    settings = config.Settings.load()

    assert settings.api_url == "http://127.0.0.1:8126"
    assert settings.password == "override-fixture-password"


def test_missing_token_error_points_to_root_env(project, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "")

    with pytest.raises(ValueError, match="SLACK_BOT_TOKEN in the root .env"):
        config.Settings.load()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000?secret=private-value",
        "http://127.0.0.1:8000/#private-value",
        "http://127.0.0.1:invalid",
        "http://127.0.0.1:70000",
        "http://127.0.0.1:0",
        "http://[bad-host",
    ],
)
def test_invalid_api_url_is_rejected_before_health_or_login(project, monkeypatch, url):
    monkeypatch.setenv("PEOPLEFLOW_API_URL", url)
    with pytest.raises(ValueError, match="PEOPLEFLOW_API_URL") as error:
        config.Settings.load()
    assert "private-value" not in str(error.value)


@pytest.mark.parametrize("value", [[], None, {"api_url": None}, {"api_url": 8000}])
def test_malformed_launcher_state_has_actionable_safe_error(project, monkeypatch, value):
    state = project / "test-launcher-state.json"
    state.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setenv("PEOPLEFLOW_LAUNCHER_STATE", str(state))
    with pytest.raises(ValueError, match="Cannot read PEOPLEFLOW_LAUNCHER_STATE"):
        config.Settings.load()


@pytest.mark.parametrize("name", ["POLL_INTERVAL_SECONDS", "API_TIMEOUT_SECONDS"])
def test_invalid_numeric_settings_do_not_echo_configured_value(project, monkeypatch, name):
    monkeypatch.setenv(name, "private-value")
    with pytest.raises(ValueError, match=name) as error:
        config.Settings.load()
    assert "private-value" not in str(error.value)


def test_empty_password_is_rejected_before_startup(project, monkeypatch):
    monkeypatch.setenv("PEOPLEFLOW_DEMO_PASSWORD", "")
    with pytest.raises(ValueError, match="non-empty PeopleFlow demo password"):
        config.Settings.load()
