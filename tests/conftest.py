import os
import secrets
import tempfile
from pathlib import Path

_test_parent = Path(__file__).resolve().parents[1] / ".tmp_tests"
_test_parent.mkdir(exist_ok=True)
_test_directory = tempfile.TemporaryDirectory(prefix="peopleflow-tests-", dir=_test_parent)
_test_root = Path(_test_directory.name)
os.environ["DEMO_AUTH_SECRET"] = secrets.token_urlsafe(32)
os.environ["DEMO_LOGIN_PASSWORD"] = secrets.token_urlsafe(18)
os.environ["OPENAI_API_KEY"] = ""
os.environ["SLACK_WEBHOOK_URL"] = ""
os.environ["DISCORD_WEBHOOK_URL"] = ""
os.environ["DISCORD_CONNECTION_MODE"] = "gateway"
for variable in (
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "SLACK_TEAM_ID",
    "DISCORD_BOT_TOKEN",
    "DISCORD_PUBLIC_KEY",
    "DISCORD_APPLICATION_ID",
):
    os.environ[variable] = ""
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
# Tests must not inherit a developer's VPN/proxy configuration.
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
for variable, filename in {
    "WORKFLOW_DB": "workflow.db",
    "LOG_PATH": "chat_logs.jsonl",
    "INDEX_PATH": "index.json",
    "INDEX_STATUS_PATH": "index_status.json",
    "SYSTEM_PROMPT_PATH": "system_prompt.txt",
    "AI_SETTINGS_PATH": "ai_settings.json",
}.items():
    os.environ[variable] = str(_test_root / filename)


def pytest_sessionfinish(session, exitstatus):
    _test_directory.cleanup()


def pytest_configure(config):
    if config.option.basetemp is None:
        config.option.basetemp = str(_test_root / "pytest")
