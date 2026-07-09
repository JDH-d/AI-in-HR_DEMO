from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import requests


DEFAULT_API_BASE_URL = "http://localhost:8000"


def get_default_api_base_url() -> str:
    return os.getenv("API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")


def should_bypass_env_proxies(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").strip().lower()
    return hostname in {"127.0.0.1", "localhost", "::1"}


def safe_json(response: requests.Response) -> object | None:
    try:
        return response.json()
    except ValueError:
        return None


def extract_assistant_content(data: object) -> str:
    if isinstance(data, dict):
        if "content" in data:
            return str(data.get("content", "")).strip()
        if isinstance(data.get("message"), dict):
            return str((data.get("message") or {}).get("content", "")).strip()
        if isinstance(data.get("message"), str):
            return str(data.get("message", "")).strip()
        if "response" in data:
            return str(data.get("response", "")).strip()
        if isinstance(data.get("choices"), list) and data.get("choices"):
            first = data["choices"][0]
            if isinstance(first, dict):
                maybe_msg = first.get("message") or {}
                if isinstance(maybe_msg, dict):
                    return str(maybe_msg.get("content", "")).strip()
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if "content" in data[0]:
            return str(data[0].get("content", "")).strip()
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict) and "content" in parsed:
                return str(parsed.get("content", "")).strip()
        except json.JSONDecodeError:
            return data.strip()
    return ""


def extract_assistant_sources(data: object) -> list[dict]:
    payload = data
    if isinstance(data, str):
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return []

    if not isinstance(payload, dict):
        return []

    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list):
        return []

    normalized: list[dict] = []
    for item in raw_sources:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        text = str(item.get("text", "")).strip()
        if not source:
            continue
        chunk_id_raw = item.get("chunk_id", -1)
        try:
            chunk_id = int(chunk_id_raw)
        except (TypeError, ValueError):
            chunk_id = -1

        score_raw = item.get("score")
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            score = 0.0

        normalized.append(
            {
                "source": source,
                "chunk_id": chunk_id,
                "text": text,
                "score": score,
            }
        )
    return normalized


def format_http_error(response: requests.Response, data: object | None) -> str:
    detail = ""
    if isinstance(data, dict):
        if isinstance(data.get("detail"), str):
            detail = data["detail"].strip()
        elif isinstance(data.get("message"), str):
            detail = data["message"].strip()
    if not detail:
        detail = (response.text or "").strip()
    if detail:
        return f"Assistant service error ({response.status_code}): {detail}"
    return f"Assistant service error ({response.status_code}). Please try again."


class DemoAPIClient:
    def __init__(self, api_base_url: str | None = None, timeout_seconds: int = 30) -> None:
        resolved_base_url = api_base_url or get_default_api_base_url()
        self.api_base_url = resolved_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, headers: dict | None = None, **kwargs) -> requests.Response:
        url = f"{self.api_base_url}{path}"
        debug_enabled = os.getenv("DEBUG_API_CLIENT") == "1"
        if debug_enabled:
            print(f"demo_api_client_request={method} {url}")

        session = requests.Session()
        session.trust_env = not should_bypass_env_proxies(url)
        try:
            response = session.request(
                method,
                url,
                headers=headers or {},
                timeout=self.timeout_seconds,
                **kwargs,
            )
        finally:
            session.close()
        if debug_enabled:
            print(f"demo_api_client_status={response.status_code}")
        return response

    def chat(self, messages: list[dict], user_id: str | None = None) -> requests.Response:
        headers = {}
        if user_id:
            headers["X-User"] = user_id
        return self.request("POST", "/chat", headers=headers, json={"messages": messages})

    def list_requests(self, user_id: str | None = None) -> requests.Response:
        headers = {}
        if user_id:
            headers["X-User"] = user_id
        return self.request("GET", "/requests", headers=headers)

    def admin_request(self, method: str, path: str, token: str | None, **kwargs) -> requests.Response:
        headers = {}
        if token:
            headers["X-Admin-Token"] = token
        provided_headers = kwargs.pop("headers", None) or {}
        headers.update(provided_headers)
        return self.request(method, path, headers=headers, **kwargs)
