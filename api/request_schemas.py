from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

RequestStatus = Literal[
    "draft",
    "submitted",
    "in_review",
    "needs_information",
    "approved",
    "rejected",
    "cancelled",
    "completed",
]
RequestCategory = Literal["pto", "sick_leave", "document"]
RequestPriority = Literal["low", "normal", "high", "urgent"]
RequestAttention = Literal["all", "overdue", "needs_attention"]


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StructuredRequestCreate(StrictPayload):
    creation_key: UUID | None = None
    type: RequestCategory
    title: str | None = Field(None, max_length=160)
    comment: str = Field("", max_length=10000)
    priority: RequestPriority = "normal"
    start_date: str | None = None
    end_date: str | None = None


class RevisionPayload(StrictPayload):
    expected_revision: int = Field(..., ge=1)


class RequestUpdate(RevisionPayload):
    type: RequestCategory | None = None
    title: str | None = Field(None, max_length=160)
    comment: str | None = Field(None, max_length=10000)
    priority: RequestPriority | None = None
    start_date: str | None = None
    end_date: str | None = None


class RequestAction(RevisionPayload):
    comment: str = Field("", max_length=10000)
    basis: str = Field("", max_length=10000)
    fair_review_confirmed: bool = False


class RequestComment(RevisionPayload):
    body: str = Field(..., min_length=1, max_length=10000)


class RequestAssignment(RevisionPayload):
    assignee: str = Field(..., max_length=200)
    comment: str = Field(..., min_length=3, max_length=10000)


class BulkReviewItem(RevisionPayload):
    id: str = Field(..., min_length=1, max_length=200)


class BulkStartReview(StrictPayload):
    items: list[BulkReviewItem] = Field(..., min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_requests(self):
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("A request may only appear once in a bulk action.")
        return self
