from __future__ import annotations

from workflow_domain import (
    InvalidTransitionError,
    WorkflowDraftData,
    WorkflowInterpreter,
    WorkflowNotFoundError,
    WorkflowValidationError,
    normalize_request_details,
    normalize_user_id,
    request_end_date,
    validate_request_fields,
)
from workflow_repository import WorkflowStore


class WorkflowService:
    def __init__(
        self,
        db_path: str,
        interpreter: WorkflowInterpreter | None = None,
    ) -> None:
        self.store = WorkflowStore(db_path)
        self.interpreter = interpreter or WorkflowInterpreter()

    def prepare_draft(self, text: str, applicant: str) -> dict | None:
        draft = self.interpreter.analyze(text, applicant)
        if draft is None:
            return None
        return self.store.create_draft(draft)

    def create_structured_draft(
        self,
        *,
        request_type: str,
        start_date: str | None,
        end_date: str | None,
        comment: str,
        applicant: str,
        approver: str,
        details: dict[str, object] | None = None,
    ) -> dict:
        normalized_type = request_type.strip().lower()
        normalized_details = normalize_request_details(normalized_type, details)
        normalized_end = request_end_date(
            normalized_type,
            start_date,
            end_date,
            normalized_details,
        )
        errors = validate_request_fields(
            normalized_type,
            start_date,
            normalized_end,
            comment,
            approver,
            normalized_details,
        )
        if errors:
            raise WorkflowValidationError(errors)
        return self.store.create_draft(
            WorkflowDraftData(
                request_type=normalized_type,
                start_date=start_date,
                end_date=normalized_end,
                comment=comment.strip(),
                applicant=normalize_user_id(applicant, "anonymous"),
                approver=normalize_user_id(approver, "manager.demo"),
                details=normalized_details,
            )
        )

    def confirm_draft(self, request_id: str, applicant: str, fields: dict) -> dict:
        return self.store.confirm_draft(
            request_id,
            normalize_user_id(applicant, "anonymous"),
            fields,
        )

    def cancel(self, request_id: str, applicant: str, comment: str = "") -> dict:
        request = self.get_for_user(request_id, applicant)
        if request is None:
            raise WorkflowNotFoundError("The workflow request could not be found.")
        return self.store.transition(
            request_id,
            "cancelled",
            normalize_user_id(applicant, "anonymous"),
            comment,
        )

    def discard_unshared_draft(self, request_id: str, applicant: str) -> bool:
        """Remove a draft when its surrounding chat exchange could not be persisted."""

        return self.store.delete_draft(request_id, applicant)

    def get_for_user(self, request_id: str, applicant: str) -> dict | None:
        request = self.store.get_request(request_id)
        if not request:
            return None
        if request["applicant"] != normalize_user_id(applicant, "anonymous"):
            return None
        return request

    def list_for_user(self, applicant: str) -> list[dict]:
        return self.store.list_by_user(applicant)

    def get_for_manager(self, request_id: str, manager_id: str) -> dict | None:
        return self.store.get_for_manager(
            request_id,
            normalize_user_id(manager_id, "manager.demo"),
        )

    def list_for_manager(self, manager_id: str, limit: int = 200) -> list[dict]:
        return self.store.list_by_approver(manager_id, limit=limit)

    def list_all(self, limit: int = 200) -> list[dict]:
        return self.store.list_all(limit=limit)

    def get_any(self, request_id: str) -> dict | None:
        return self.store.get_request(request_id)

    def manager_decision(
        self,
        request_id: str,
        manager_id: str,
        target_status: str,
        comment: str = "",
    ) -> dict:
        request = self.get_for_manager(request_id, manager_id)
        if request is None:
            raise WorkflowNotFoundError("The workflow request could not be found.")

        target = target_status.strip().lower()
        expected_target = "acknowledged" if request["type"] == "sick_leave" else None
        if request["type"] == "pto" and target in {"approved", "declined"}:
            expected_target = target
        if expected_target is None or target != expected_target:
            raise InvalidTransitionError(request["status"], target)
        if target == "declined" and not comment.strip():
            raise WorkflowValidationError(
                ["A manager comment is required when declining a request."]
            )
        return self.store.transition(request_id, target, manager_id, comment)

    def add_manager_comment(self, request_id: str, author: str, body: str) -> dict:
        if self.get_for_manager(request_id, author) is None:
            raise WorkflowNotFoundError("The workflow request could not be found.")
        return self.store.add_comment(request_id, author, body)

    def history(self, request_id: str) -> dict:
        request = self.store.get_request(request_id)
        if not request:
            raise WorkflowNotFoundError("The workflow request could not be found.")
        return {
            "request": request,
            "events": self.store.list_events(request_id),
            "comments": self.store.list_comments(request_id),
        }

    def add_feedback(
        self,
        request_id: str,
        user_id: str,
        rating: int,
        comment: str = "",
    ) -> dict:
        if self.get_for_user(request_id, user_id) is None:
            raise WorkflowNotFoundError("The workflow request could not be found.")
        return self.store.add_feedback(request_id, user_id, rating, comment)

    def metrics(self) -> dict:
        return self.store.metrics()

    def add_assistant_feedback(
        self,
        rating: int,
        comment: str = "",
        question: str = "",
        answer: str = "",
    ) -> dict:
        return self.store.add_assistant_feedback(rating, comment, question, answer)

    def list_assistant_feedback(self, sentiment: str = "all", limit: int = 200) -> list[dict]:
        return self.store.list_assistant_feedback(sentiment=sentiment, limit=limit)

    def review_quality_item(self, item_id: str, action: str) -> dict:
        return self.store.review_quality_item(item_id, action)

    def reviewed_quality_item_ids(self) -> set[str]:
        return self.store.reviewed_quality_item_ids()
