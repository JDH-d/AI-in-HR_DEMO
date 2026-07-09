from __future__ import annotations

import requests
import streamlit as st

from .api_client import DemoAPIClient, format_http_error, safe_json


def main() -> None:
    st.set_page_config(page_title="Administration Console", layout="wide")
    st.title("Administration Console")
    st.caption("Role-based manager and knowledge administration for the demo environment.")
    api_client = DemoAPIClient(timeout_seconds=30)
    _initialize_state()

    token = str(st.session_state.get("admin_auth_token", ""))
    user = st.session_state.get("admin_user")
    with st.sidebar:
        st.subheader("Demo Login")
        if not token:
            with st.form("admin-login"):
                account = st.selectbox(
                    "Account",
                    options=["manager", "knowledge_admin"],
                    format_func=lambda value: {
                        "manager": "Manager",
                        "knowledge_admin": "Knowledge Admin",
                    }[value],
                )
                password = st.text_input("Demo password", type="password")
                submitted = st.form_submit_button("Sign in")
            if submitted:
                response = _request(
                    api_client,
                    "POST",
                    "/api/v1/auth/login",
                    None,
                    json={
                        "username": account,
                        "password": password,
                    },
                )
                data = safe_json(response) if response is not None else None
                if response is not None and response.status_code == 200 and isinstance(data, dict):
                    st.session_state.admin_auth_token = data.get("access_token", "")
                    st.session_state.admin_user = data.get("user")
                    st.rerun()
                elif response is not None:
                    st.error(format_http_error(response, data))
        else:
            display_name = user.get("display_name", "") if isinstance(user, dict) else ""
            st.success(f"Signed in as {display_name}")
            if st.button("Sign out"):
                st.session_state.admin_auth_token = ""
                st.session_state.admin_user = None
                st.rerun()

    if not token or not isinstance(user, dict):
        st.info("Sign in with a predefined Manager or Knowledge Admin account.")
        return

    role = user.get("role")
    if role == "knowledge_admin":
        _render_knowledge_admin(api_client, token)
    elif role == "manager":
        _render_manager(api_client, token)
    else:
        st.error("This demo role does not have an administration workspace.")


def _initialize_state() -> None:
    defaults = {
        "admin_auth_token": "",
        "admin_user": None,
        "documents": [],
        "workflow_requests": [],
        "metrics": {},
        "logs": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _render_knowledge_admin(api_client: DemoAPIClient, token: str) -> None:
    st.subheader("System Metrics")
    if st.button("Refresh Metrics"):
        response = _request(api_client, "GET", "/api/v1/admin/metrics", token)
        data = safe_json(response) if response is not None else None
        if response is not None and response.status_code == 200 and isinstance(data, dict):
            st.session_state.metrics = data.get("metrics", {})
        elif response is not None:
            st.error(format_http_error(response, data))
    if st.session_state.metrics:
        st.json(st.session_state.metrics)

    st.divider()
    st.subheader("System Prompt")
    prompt_col, action_col = st.columns([4, 1])
    if action_col.button("Load Prompt"):
        response = _request(api_client, "GET", "/api/v1/admin/system-prompt", token)
        data = safe_json(response) if response is not None else None
        if response is not None and response.status_code == 200 and isinstance(data, dict):
            st.session_state.system_prompt = data.get("system_prompt", "")
        elif response is not None:
            st.error(format_http_error(response, data))
    prompt = prompt_col.text_area(
        "System prompt",
        value=st.session_state.get("system_prompt", ""),
        height=200,
    )
    if prompt_col.button("Save Prompt"):
        response = _request(
            api_client,
            "PUT",
            "/api/v1/admin/system-prompt",
            token,
            json={"system_prompt": prompt},
        )
        if response is not None and response.status_code == 200:
            st.success("System prompt saved.")
        elif response is not None:
            st.error(format_http_error(response, safe_json(response)))

    st.divider()
    st.subheader("Knowledge Documents")
    upload_col, refresh_col = st.columns([3, 1])
    uploaded = upload_col.file_uploader("Upload document", type=["txt", "md", "pdf", "docx"])
    if upload_col.button("Upload") and uploaded:
        response = _request(
            api_client,
            "POST",
            "/api/v1/documents",
            token,
            files={"file": (uploaded.name, uploaded.getvalue())},
        )
        if response is not None and response.status_code == 201:
            st.success(f"Uploaded {uploaded.name}.")
        elif response is not None:
            st.error(format_http_error(response, safe_json(response)))
    if refresh_col.button("Refresh Documents"):
        response = _request(api_client, "GET", "/api/v1/documents", token)
        data = safe_json(response) if response is not None else None
        if response is not None and response.status_code == 200 and isinstance(data, dict):
            st.session_state.documents = data.get("documents", [])
        elif response is not None:
            st.error(format_http_error(response, data))

    for document in st.session_state.documents:
        document_id = document.get("id", "")
        columns = st.columns([4, 2, 1, 1])
        columns[0].write(document.get("title") or document.get("name"))
        columns[1].write(f"{document.get('category')} · v{document.get('version')}")
        if columns[2].button("Index", key=f"index-{document_id}"):
            response = _request(
                api_client,
                "POST",
                f"/api/v1/documents/{document_id}/index",
                token,
            )
            if response is not None and response.status_code == 200:
                st.success("Index rebuilt.")
            elif response is not None:
                st.error(format_http_error(response, safe_json(response)))
        if columns[3].button("Delete", key=f"delete-{document_id}"):
            response = _request(
                api_client,
                "DELETE",
                f"/api/v1/documents/{document_id}",
                token,
            )
            if response is not None and response.status_code == 200:
                st.success("Document deleted.")
                st.rerun()
            elif response is not None:
                st.error(format_http_error(response, safe_json(response)))

    st.divider()
    st.subheader("Conversation Logs")
    if st.button("Load Logs"):
        response = _request(api_client, "GET", "/api/v1/admin/logs?limit=100", token)
        data = safe_json(response) if response is not None else None
        if response is not None and response.status_code == 200 and isinstance(data, dict):
            st.session_state.logs = data.get("logs", [])
        elif response is not None:
            st.error(format_http_error(response, data))
    if st.session_state.logs:
        st.dataframe(st.session_state.logs, width="stretch")


def _render_manager(api_client: DemoAPIClient, token: str) -> None:
    st.subheader("Workflow Requests")
    if st.button("Refresh Requests"):
        response = _request(api_client, "GET", "/api/v1/requests", token)
        data = safe_json(response) if response is not None else None
        if response is not None and response.status_code == 200 and isinstance(data, dict):
            st.session_state.workflow_requests = data.get("requests", [])
        elif response is not None:
            st.error(format_http_error(response, data))

    requests_data = st.session_state.workflow_requests
    if not requests_data:
        st.caption("No requests loaded.")
        return

    for request in requests_data:
        request_id = request.get("id", "")
        request_status = request.get("status", "")
        with st.expander(
            f"{request.get('type_label', request.get('type'))} · "
            f"{request.get('applicant')} · {request_status}"
        ):
            st.json(request)
            decision_comment = st.text_input(
                "Decision comment",
                key=f"decision-comment-{request_id}",
            )
            if request_status in {"submitted", "in_review"}:
                approve_col, decline_col = st.columns(2)
                if approve_col.button("Approve", key=f"approve-{request_id}"):
                    _decision(api_client, token, request_id, "approve", decision_comment)
                if decline_col.button("Decline", key=f"decline-{request_id}"):
                    _decision(api_client, token, request_id, "decline", decision_comment)
            elif request_status == "approved":
                if st.button("Mark Completed", key=f"complete-{request_id}"):
                    _decision(api_client, token, request_id, "complete", decision_comment)

            manager_comment = st.text_input("Manager comment", key=f"comment-{request_id}")
            if st.button("Add Comment", key=f"add-comment-{request_id}"):
                response = _request(
                    api_client,
                    "POST",
                    f"/api/v1/requests/{request_id}/comments",
                    token,
                    json={"author": "Manager", "body": manager_comment},
                )
                if response is not None and response.status_code == 201:
                    st.success("Comment added.")
                elif response is not None:
                    st.error(format_http_error(response, safe_json(response)))

            if st.button("Load History", key=f"history-{request_id}"):
                response = _request(
                    api_client,
                    "GET",
                    f"/api/v1/requests/{request_id}",
                    token,
                )
                data = safe_json(response) if response is not None else None
                if response is not None and response.status_code == 200 and isinstance(data, dict):
                    st.session_state[f"history-data-{request_id}"] = data
                elif response is not None:
                    st.error(format_http_error(response, data))
            history = st.session_state.get(f"history-data-{request_id}")
            if history:
                st.dataframe(history.get("events", []), width="stretch")
                st.dataframe(history.get("comments", []), width="stretch")


def _decision(
    api_client: DemoAPIClient,
    token: str,
    request_id: str,
    action: str,
    comment: str,
) -> None:
    response = _request(
        api_client,
        "POST",
        f"/api/v1/requests/{request_id}/{action}",
        token,
        json={"comment": comment},
    )
    if response is not None and response.status_code == 200:
        st.success(f"Request action applied: {action}.")
        st.rerun()
    elif response is not None:
        st.error(format_http_error(response, safe_json(response)))


def _request(
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
