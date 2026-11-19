from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from domain.errors import ChatInputError, ConversationError, DocumentError
from domain.request_policy import RequestConflictError
from domain.workflow import (
    InvalidTransitionError,
    WorkflowDecisionError,
    WorkflowNotFoundError,
    WorkflowPermissionError,
    WorkflowValidationError,
)
from services.auth_service import AuthenticationError


def register_error_handlers(app: FastAPI) -> None:
    async def request_validation_error(request: Request, exc: RequestValidationError):
        # Pydantic's default `input` and `ctx` can contain passwords or private messages.
        errors = [
            {key: error[key] for key in ("loc", "msg", "type") if key in error}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    async def document_error(request: Request, exc: DocumentError):
        status = {
            "invalid": 400,
            "forbidden": 403,
            "not_found": 404,
            "conflict": 409,
            "too_large": 413,
            "unavailable": 503,
        }[exc.code]
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    async def validation_error(request: Request, exc: WorkflowValidationError):
        return JSONResponse(status_code=422, content={"detail": exc.errors})

    def handler_for(status: int):
        async def handler(request: Request, exc: Exception):
            return JSONResponse(status_code=status, content={"detail": str(exc)})

        return handler

    app.add_exception_handler(DocumentError, document_error)
    app.add_exception_handler(RequestValidationError, request_validation_error)
    app.add_exception_handler(ConversationError, document_error)
    app.add_exception_handler(WorkflowValidationError, validation_error)
    for exception, status in (
        (AuthenticationError, 401),
        (ChatInputError, 400),
        (WorkflowNotFoundError, 404),
        (WorkflowPermissionError, 403),
        (InvalidTransitionError, 409),
        (WorkflowDecisionError, 422),
        (RequestConflictError, 409),
    ):
        app.add_exception_handler(exception, handler_for(status))
