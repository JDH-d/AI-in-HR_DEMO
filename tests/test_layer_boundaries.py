import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "layer,forbidden",
    [
        ("api", {"storage", "integrations", "rag", "sqlite3"}),
        ("domain", {"api", "services", "storage", "integrations", "rag", "fastapi", "openai"}),
        ("storage", {"api", "services", "integrations", "rag", "fastapi", "openai"}),
        ("services", {"api", "fastapi", "openai"}),
        ("rag", {"api", "fastapi", "openai"}),
    ],
)
def test_dependency_direction(layer, forbidden):
    for path in (ROOT / layer).glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module or ""]
            assert not any(module.split(".")[0] in forbidden for module in modules), path


def test_feature_views_do_not_access_http_or_query_cache():
    for path in (ROOT / "frontend/src/features").rglob("*.tsx"):
        if ".test." in path.name:
            continue
        source = path.read_text(encoding="utf-8-sig")
        assert "api/client" not in source, path
        assert "@tanstack/react-query" not in source, path


def test_prompt_builders_have_no_storage_side_effects():
    tree = ast.parse((ROOT / "rag/prompts.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            assert not (isinstance(node.func, ast.Name) and node.func.id == "open")
            assert not (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"read_text", "write_text", "read_bytes", "write_bytes"}
            )
