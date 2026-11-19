from domain.workflow import WorkflowNotFoundError
from services.request_service import RequestService


class WorkflowService(RequestService):
    """Request workflow plus the existing assistant-quality feedback facade."""

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
        user_id: str,
        rating: int,
        comment: str = "",
        question: str = "",
        answer: str = "",
    ) -> dict:
        return self.store.add_assistant_feedback(user_id, rating, comment, question, answer)

    def list_assistant_feedback(self, sentiment: str = "all", limit: int = 200) -> list[dict]:
        return self.store.list_assistant_feedback(sentiment=sentiment, limit=limit)

    def review_quality_item(self, item_id: str, action: str) -> dict:
        return self.store.review_quality_item(item_id, action)

    def reviewed_quality_item_ids(self) -> set[str]:
        return self.store.reviewed_quality_item_ids()
