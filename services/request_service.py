from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import PurePath
from uuid import UUID

from domain.manager_queue import REVIEW_DAYS, REVIEW_POLICY_DESCRIPTION, attention_for_request
from domain.request_policy import (
    ACTIONS,
    FINAL_STATUSES,
    POLICY_VERSION,
    PRIORITIES,
    PROCEDURE,
    RequestConflictError,
    allowed_actions,
    require_participant_write,
    require_revision,
    require_text,
    require_visible,
)
from domain.workflow import (
    TYPE_LABELS,
    InvalidTransitionError,
    WorkflowDecisionError,
    WorkflowDraftData,
    WorkflowInterpreter,
    WorkflowNotFoundError,
    WorkflowPermissionError,
    WorkflowValidationError,
    duration_days,
    validate_request_fields,
)
from services.auth_service import DEMO_IDENTITIES
from storage.workflow_store import WorkflowStore

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS = 5


class RequestService:
    def __init__(
        self, db_path: str, interpreter: WorkflowInterpreter | None = None, *, clock=None
    ) -> None:
        self.store = WorkflowStore(db_path)
        self.interpreter = interpreter or WorkflowInterpreter()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def prepare_draft(self, text: str, applicant: str) -> dict | None:
        draft = self.interpreter.analyze(text, applicant)
        if draft is None:
            return None
        identity = next((item for item in DEMO_IDENTITIES.values() if item.id == applicant), None)
        draft = replace(
            draft,
            title=text.strip().splitlines()[0][:160],
            approver=identity.manager_id if identity and identity.manager_id else draft.approver,
        )
        return self.store.create_draft(draft)

    @staticmethod
    def _validated_fields(request: dict, fields: dict, *, submitting: bool) -> dict:
        editable = {"type", "title", "priority", "comment", "start_date", "end_date"}
        if set(fields) - editable:
            raise WorkflowValidationError(
                [
                    "Only request content can be edited. Author, assignee and decisions cannot be overwritten."
                ]
            )
        values = {key: fields.get(key, request.get(key)) for key in editable}
        for key in ("type", "title", "priority", "comment"):
            if values[key] is None:
                values[key] = request.get(key)
            if not isinstance(values[key], str):
                raise WorkflowValidationError([f"{key} must be text."])
            values[key] = values[key].strip()
        if values["type"] not in TYPE_LABELS or values["priority"] not in PRIORITIES:
            raise WorkflowValidationError(["Choose a supported category and priority."])
        if len(values["title"]) > 160 or len(values["comment"]) > 10000:
            raise WorkflowValidationError(
                ["Title is limited to 160 characters; description to 10000."]
            )
        errors = validate_request_fields(
            values["type"],
            values["start_date"],
            values["end_date"],
            values["comment"] or ("draft" if not submitting else ""),
            request["approver"],
        )
        if not submitting:
            errors = [
                error
                for error in errors
                if "required" not in error.lower() or "date" not in error.lower()
            ]
        if errors:
            raise WorkflowValidationError(errors)
        if submitting:
            require_text(values["title"], "Title", maximum=160)
            require_text(values["comment"], "Description")
        values["duration_days"] = duration_days(values["start_date"], values["end_date"])
        return values

    def create_structured_draft(
        self,
        *,
        request_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        comment: str = "",
        applicant: str,
        approver: str,
        title: str | None = None,
        priority: str = "normal",
        creation_key: str | None = None,
    ) -> dict:
        if creation_key is not None:
            try:
                creation_key = str(UUID(creation_key))
            except (ValueError, AttributeError, TypeError) as exc:
                raise WorkflowValidationError(["The creation key must be a UUID."]) from exc
        if not approver or approver == applicant:
            raise WorkflowValidationError(["A different, assigned manager is required."])
        fields = {
            "type": request_type,
            "start_date": start_date,
            "end_date": end_date,
            "comment": comment,
            "title": title
            if title is not None
            else (comment.strip().splitlines() or [TYPE_LABELS.get(request_type, "Request")])[0][
                :160
            ],
            "priority": priority,
            "approver": approver,
        }
        values = self._validated_fields(fields, {}, submitting=False)
        return self.store.create_draft(
            WorkflowDraftData(
                request_type=values["type"],
                start_date=values["start_date"],
                end_date=values["end_date"],
                comment=values["comment"],
                applicant=applicant,
                approver=approver,
                title=values["title"],
                priority=values["priority"],
            ),
            creation_key=creation_key,
        )

    def get_for_user(self, request_id: str, applicant: str) -> dict | None:
        request = self.store.get_request(request_id)
        return request if request and request["applicant"] == applicant else None

    def get_visible(self, request_id: str, user_id: str, *, employee: bool) -> dict:
        request = self.store.get_request(request_id)
        if request is None:
            raise WorkflowNotFoundError("The request could not be found.")
        require_visible(request, user_id, "employee" if employee else "manager")
        return request

    def detail(self, request_id: str, user_id: str, role: str) -> dict:
        with self.store.request_transaction(request_id) as (conn, request):
            require_visible(request, user_id, role)
            if role == "manager":
                request["manager_attention"] = attention_for_request(
                    request,
                    self.store.review_anchor(conn, request_id),
                    self.clock(),
                )
            return {
                "request": request,
                **self.store.read_history(conn, request_id),
                "allowed_actions": allowed_actions(request, user_id, role),
                "procedure": PROCEDURE,
                "policy_version": POLICY_VERSION,
            }

    def history(self, request_id: str) -> dict:
        """Internal diagnostics. HTTP callers must use the authorized detail method."""
        with self.store.request_transaction(request_id) as (conn, request):
            return {"request": request, **self.store.read_history(conn, request_id)}

    def list_for_user(self, applicant: str) -> list[dict]:
        return self.store.list_by_user(applicant)

    def list_visible(self, user_id: str, role: str, **filters) -> dict:
        if role != "manager" and (
            filters.get("assignee") or filters.get("attention", "all") != "all"
        ):
            raise WorkflowPermissionError("Manager queue filters are not available for your role.")
        if filters.get("attention", "all") not in {"all", "overdue", "needs_attention"}:
            raise WorkflowValidationError(["Choose a supported attention filter."])
        return self.store.list_visible(user_id, role, now=self.clock(), **filters)

    @staticmethod
    def _require_manager(role):
        if role != "manager":
            raise WorkflowPermissionError("This action is available to managers only.")

    def manager_overview(self, user_id: str, role: str) -> dict:
        self._require_manager(role)
        return {
            "summary": self.store.manager_summary(user_id, self.clock()),
            "policy": {"review_days": REVIEW_DAYS, "description": REVIEW_POLICY_DESCRIPTION},
        }

    def manager_activity(self, user_id: str, role: str, *, limit=20, offset=0) -> dict:
        self._require_manager(role)
        if not 1 <= limit <= 100 or offset < 0:
            raise WorkflowValidationError(["Choose a valid activity page."])
        return self.store.manager_activity(user_id, limit=limit, offset=offset)

    def bulk_start_review(self, actor: str, role: str, items: list[dict]) -> dict:
        self._require_manager(role)
        if not 1 <= len(items) <= 20:
            raise WorkflowValidationError(["Select between 1 and 20 requests."])
        identifiers = [item.get("id") for item in items]
        if any(not isinstance(item, str) or not item or len(item) > 200 for item in identifiers):
            raise WorkflowValidationError(["Every selected request must have a valid ID."])
        if len(set(identifiers)) != len(identifiers):
            raise WorkflowValidationError(["A request may only appear once in a bulk action."])
        if any(
            type(item.get("expected_revision")) is not int or item["expected_revision"] < 1
            for item in items
        ):
            raise WorkflowValidationError(
                ["Every selected request must include its current revision."]
            )
        results = []
        for item in items:
            try:
                request = self.act(
                    item["id"], actor, role, "start_review", item["expected_revision"]
                )
                results.append({"id": item["id"], "success": True, "request": request})
            except (
                WorkflowNotFoundError,
                WorkflowPermissionError,
                RequestConflictError,
                InvalidTransitionError,
            ) as error:
                results.append({"id": item["id"], "success": False, "error": str(error)})
        return {"results": results}

    def edit_draft(self, request_id, actor, fields, revision):
        with self.store.request_transaction(request_id) as (conn, request):
            require_visible(request, actor, "employee")
            require_revision(request, revision)
            if request["status"] != "draft":
                raise InvalidTransitionError(request["status"], "draft")
            changes = self._validated_fields(request, fields, submitting=False)
            return self.store.update_request(conn, request, actor, changes, "draft_updated")

    def confirm_draft(self, request_id, applicant, fields, *, revision=None):
        request = self.get_visible(request_id, applicant, employee=True)
        return self.act(
            request_id,
            applicant,
            "employee",
            "submit",
            revision if revision is not None else request["revision"],
            fields=fields,
        )

    def act(
        self,
        request_id: str,
        actor: str,
        role: str,
        action: str,
        revision: int,
        *,
        comment: str = "",
        basis: str = "",
        fair_review_confirmed: bool = False,
        fields: dict | None = None,
    ) -> dict:
        rule = ACTIONS.get(action)
        if not rule or role != rule[0]:
            raise WorkflowPermissionError("This action is not available for your role.")
        with self.store.request_transaction(request_id) as (conn, request):
            require_participant_write(request, actor, role)
            require_revision(request, revision)
            if request["status"] not in rule[1]:
                raise InvalidTransitionError(request["status"], rule[2])
            changes = {"status": rule[2]}
            details = {"action": action, "policy_version": POLICY_VERSION}
            event_type = "status_changed"
            if action == "submit":
                changes.update(self._validated_fields(request, fields or {}, submitting=True))
            elif fields:
                raise WorkflowValidationError(
                    ["Request content can only change in Draft. Add information as a comment."]
                )
            if action not in {"submit", "start_review"}:
                details["comment"] = require_text(comment, "Reason / additional information")
            if action in {"approve", "reject"}:
                if not fair_review_confirmed:
                    raise WorkflowDecisionError(
                        "Confirm that the same relevant criteria were applied without discrimination."
                    )
                details.update(
                    basis=require_text(basis, "Policy or objective criteria"),
                    fair_review_confirmed=True,
                    review_round=request["review_round"],
                )
                event_type = "decision_recorded"
            elif action == "appeal":
                changes["review_round"] = request["review_round"] + 1
                details.update(
                    previous_decision_id=self.store.last_decision_id(conn, request_id),
                    previous_status=request["status"],
                )
                event_type = "reconsideration_requested"
            elif action in {"request_information", "provide_information"}:
                item = self.store.insert_comment(conn, request_id, actor, details["comment"])
                details["comment_id"] = item["id"]
                event_type = action
            return self.store.update_request(conn, request, actor, changes, event_type, details)

    def comment(self, request_id, actor, role, body, revision):
        cleaned = require_text(body, "Comment", minimum=1)
        with self.store.request_transaction(request_id) as (conn, request):
            require_participant_write(request, actor, role)
            require_revision(request, revision)
            item = self.store.insert_comment(conn, request_id, actor, cleaned)
            updated = self.store.update_request(
                conn, request, actor, {}, "comment_added", {"comment_id": item["id"]}
            )
            return {"comment": item, "request": updated}

    def assign(self, request_id, actor, assignee, reason, revision):
        manager_ids = {item.id for item in DEMO_IDENTITIES.values() if item.role == "manager"}
        if assignee not in manager_ids:
            raise WorkflowValidationError(["Select a registered manager."])
        reason = require_text(reason, "Reason for reassignment")
        with self.store.request_transaction(request_id) as (conn, request):
            require_participant_write(request, actor, "manager")
            require_revision(request, revision)
            if request["status"] in FINAL_STATUSES or assignee in {
                request["applicant"],
                request["approver"],
            }:
                raise WorkflowValidationError(
                    [
                        "Reassignment requires an active request and a different manager, other than its author."
                    ]
                )
            return self.store.update_request(
                conn,
                request,
                actor,
                {"approver": assignee},
                "assignee_changed",
                {"comment": reason},
            )

    def attach(self, request_id, actor, role, filename, content, revision):
        filename = filename.strip()
        if (
            not filename
            or len(filename) > 180
            or any(c in filename for c in "/\\:")
            or any(ord(c) < 32 for c in filename)
        ):
            raise WorkflowValidationError(["Use a plain filename, at most 180 characters."])
        if not content or len(content) > MAX_ATTACHMENT_BYTES:
            raise WorkflowValidationError(["Attachments must be between 1 byte and 5 MB."])
        extension = PurePath(filename).suffix.lower()
        formats = {
            ".pdf": (b"%PDF-", "application/pdf"),
            ".png": (b"\x89PNG\r\n\x1a\n", "image/png"),
            ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
            ".jpeg": (b"\xff\xd8\xff", "image/jpeg"),
        }
        if extension == ".txt":
            try:
                text = content.decode("utf-8")
                if "\x00" in text:
                    raise ValueError()
            except (UnicodeDecodeError, ValueError):
                raise WorkflowValidationError(["Text attachments must contain UTF-8 text."])
            content_type = "text/plain"
        elif extension in formats and content.startswith(formats[extension][0]):
            content_type = formats[extension][1]
        else:
            raise WorkflowValidationError(
                [
                    "Supported attachments: PDF, PNG, JPEG and UTF-8 TXT. Content must match the extension."
                ]
            )
        with self.store.request_transaction(request_id) as (conn, request):
            require_participant_write(request, actor, role)
            require_revision(request, revision)
            if request["status"] in FINAL_STATUSES:
                raise WorkflowValidationError(
                    ["Request reconsideration before adding evidence to a closed decision."]
                )
            if self.store.attachment_count(conn, request_id) >= MAX_ATTACHMENTS:
                raise WorkflowValidationError(["A request can contain at most five attachments."])
            item = self.store.insert_attachment(
                conn, request_id, actor, filename, content_type, content
            )
            updated = self.store.update_request(
                conn, request, actor, {}, "attachment_added", {"attachment": item}
            )
            return {"attachment": item, "request": updated}

    def attachment(self, request_id, attachment_id, actor, role):
        with self.store.request_transaction(request_id) as (conn, request):
            require_visible(request, actor, role)
            return self.store.get_attachment(conn, request_id, attachment_id)
