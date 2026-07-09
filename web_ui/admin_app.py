from __future__ import annotations

import os
from urllib.parse import quote

import requests
import streamlit as st

from .api_client import DemoAPIClient


ENV_ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()


def main() -> None:
    st.set_page_config(page_title="Administration Console", layout="wide")
    st.title("Administration Console")
    st.caption("Manage prompt configuration, source documents, audit logs, and workflow requests for the demo environment.")
    api_client = DemoAPIClient(timeout_seconds=30)

    if "admin_token" not in st.session_state:
        st.session_state.admin_token = ENV_ADMIN_TOKEN

    with st.sidebar:
        st.subheader("Access")
        token = st.text_input(
            "Administrator token",
            type="password",
            value=st.session_state.admin_token,
        )
        if st.button("Save Token"):
            st.session_state.admin_token = token.strip()
        if st.session_state.admin_token:
            st.success("Administrator token is loaded.")
        else:
            st.info("Provide the administrator token to enable privileged actions.")

    token = st.session_state.admin_token

    st.divider()
    st.subheader("System Prompt")
    col_prompt, col_actions = st.columns([3, 1])
    with col_actions:
        if st.button("Load Current Prompt"):
            resp = _admin_request(api_client, "GET", "/admin/system-prompt", token)
            if resp is not None:
                if resp.status_code == 200:
                    st.session_state.system_prompt = resp.json().get("system_prompt", "")
                else:
                    st.error(f"Unable to load the system prompt: {resp.status_code} {resp.text}")

    prompt_value = st.session_state.get("system_prompt", "")
    new_prompt = col_prompt.text_area("System prompt", value=prompt_value, height=240)
    if col_prompt.button("Save Prompt"):
        resp = _admin_request(
            api_client,
            "PUT",
            "/admin/system-prompt",
            token,
            json={"system_prompt": new_prompt},
        )
        if resp is not None:
            if resp.status_code == 200:
                st.success("The system prompt was updated successfully.")
            else:
                st.error(f"Unable to save the system prompt: {resp.status_code} {resp.text}")

    st.divider()
    st.subheader("Knowledge Base Documents")
    col_docs, col_upload = st.columns([3, 1])

    with col_upload:
        uploaded = st.file_uploader("Upload document", type=["txt", "md", "pdf", "docx"])
        if st.button("Upload Document"):
            if not uploaded:
                st.warning("Select a document before uploading.")
            else:
                resp = _admin_request(
                    api_client,
                    "POST",
                    "/admin/documents",
                    token,
                    files={"file": (uploaded.name, uploaded.getvalue())},
                )
                if resp is not None:
                    if resp.status_code == 200:
                        st.success(f"Document uploaded: {uploaded.name}")
                    else:
                        st.error(f"Document upload failed: {resp.status_code} {resp.text}")

    if col_docs.button("Refresh Document List"):
        resp = _admin_request(api_client, "GET", "/admin/documents", token)
        if resp is not None:
            if resp.status_code == 200:
                st.session_state.documents = resp.json().get("documents", [])
            else:
                st.error(f"Unable to load documents: {resp.status_code} {resp.text}")

    documents = st.session_state.get("documents", [])
    if documents:
        for doc in documents:
            name = doc.get("name", "")
            size = doc.get("size", 0)
            modified = doc.get("modified", "")
            row = st.columns([4, 1, 2, 1])
            row[0].write(name)
            row[1].write(f"{size} bytes")
            row[2].write(modified)
            if row[3].button("Delete", key=f"del-{name}"):
                resp = _admin_request(api_client, "DELETE", f"/admin/documents/{quote(name)}", token)
                if resp is not None:
                    if resp.status_code == 200:
                        st.success(f"Document deleted: {name}")
                    else:
                        st.error(f"Document deletion failed: {resp.status_code} {resp.text}")
    else:
        st.caption("No documents have been loaded yet.")

    st.divider()
    st.subheader("Vector Index")
    if st.button("Rebuild Index"):
        resp = _admin_request(api_client, "POST", "/admin/rebuild-index", token)
        if resp is not None:
            if resp.status_code == 200:
                st.success("The vector index rebuild completed successfully.")
            else:
                st.error(f"Unable to rebuild the vector index: {resp.status_code} {resp.text}")

    st.divider()
    st.subheader("Conversation Logs")
    st.caption("User text may be masked depending on LOG_USER_TEXT_MODE.")
    limit = st.slider("Log entries", min_value=10, max_value=500, value=100, step=10)
    if st.button("Load Logs"):
        resp = _admin_request(api_client, "GET", f"/admin/logs?limit={limit}", token)
        if resp is not None:
            if resp.status_code == 200:
                st.session_state.logs = resp.json().get("logs", [])
            else:
                st.error(f"Unable to load logs: {resp.status_code} {resp.text}")

    logs = st.session_state.get("logs", [])
    if logs:
        st.dataframe(logs, use_container_width=True)
    else:
        st.caption("No log entries are available.")

    st.divider()
    st.subheader("Workflow Requests")
    req_limit = st.slider(
        "Request entries",
        min_value=10,
        max_value=500,
        value=100,
        step=10,
    )
    if st.button("Load Requests"):
        resp = _admin_request(api_client, "GET", f"/admin/requests?limit={req_limit}", token)
        if resp is not None:
            if resp.status_code == 200:
                st.session_state.workflow_requests = resp.json().get("requests", [])
            else:
                st.error(f"Unable to load workflow requests: {resp.status_code} {resp.text}")

    workflow_requests = st.session_state.get("workflow_requests", [])
    if workflow_requests:
        st.caption("Select a new status and click Update to persist the change.")
        for req in workflow_requests:
            status_options = ["new", "pending", "approved", "declined", "done"]
            current_status = (req.get("status") or "pending").lower()
            status_index = (
                status_options.index(current_status)
                if current_status in status_options
                else 1
            )
            cols = st.columns([2, 1, 1, 1, 2, 1, 1])
            cols[0].write(req.get("id", ""))
            cols[1].write(req.get("type", ""))
            cols[2].write(req.get("created_by", ""))
            cols[3].write(req.get("status", ""))
            cols[4].write(req.get("created_at", ""))
            new_status = cols[5].selectbox(
                "Status",
                options=status_options,
                index=status_index,
                key=f"status-{req.get('id', '')}",
                label_visibility="collapsed",
            )
            if cols[6].button("Update", key=f"update-{req.get('id', '')}"):
                resp = _admin_request(
                    api_client,
                    "PUT",
                    f"/admin/requests/{req.get('id', '')}/status",
                    token,
                    json={"status": new_status},
                )
                if resp is not None:
                    if resp.status_code == 200:
                        st.success(f"Workflow request updated: {req.get('id', '')}")
                        req["status"] = new_status
                    else:
                        st.error(f"Workflow update failed: {resp.status_code} {resp.text}")
    else:
        st.caption("No workflow requests are available.")


def _admin_request(
    api_client: DemoAPIClient,
    method: str,
    path: str,
    token: str | None,
    **kwargs,
) -> requests.Response | None:
    try:
        return api_client.admin_request(method, path, token, **kwargs)
    except requests.RequestException as exc:
        st.error(f"API request failed: {exc}")
        return None


if __name__ == "__main__":
    main()
