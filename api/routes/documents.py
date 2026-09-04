from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from api.v1_dependencies import Services, require_roles
from services.auth_service import DemoIdentity
from services.document_service import (
    MAX_DOCUMENT_BYTES,
    DocumentError,
    DocumentExistsError,
    DocumentNotFoundError,
    InvalidDocumentError,
)
from services.runtime import ServiceContainer

router = APIRouter(prefix="/api/v1", tags=["documents"])
logger = logging.getLogger(__name__)


@router.get("/documents")
def list_documents(
    services: Services,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    return {"documents": services.documents.list_documents()}


@router.post("/documents", status_code=status.HTTP_201_CREATED)
def upload_document(
    services: Services,
    file: UploadFile = File(...),
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    content = file.file.read(MAX_DOCUMENT_BYTES + 1)
    index_snapshot = services.documents.snapshot_index_files()
    try:
        name = services.documents.save_upload(file.filename or "", content)
    except InvalidDocumentError as exc:
        status_code = 413 if len(content) > MAX_DOCUMENT_BYTES else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except DocumentExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    document = next(
        (item for item in services.documents.list_documents() if item["name"] == name),
        None,
    )
    if document and services.ai_settings.get()["auto_index_uploads"]:
        try:
            documents = _rebuild_knowledge_index(services)
        except HTTPException:
            try:
                services.documents.delete_document(name)
                services.documents.restore_index_files(index_snapshot)
                services.knowledge_index.invalidate()
            except (DocumentError, OSError):
                logger.exception("Document upload rollback failed document=%s", name)
            raise
        document = next((item for item in documents if item["id"] == document["id"]), document)
    return {"document": document or {"id": services.documents.document_id(name), "name": name}}


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: str,
    services: Services,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> FileResponse:
    document = services.documents.find_by_id(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="The document could not be found.")
    try:
        path = services.documents.resolve_path(document["name"])
    except InvalidDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path=path, filename=path.name)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    services: Services,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    document = services.documents.find_by_id(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="The document could not be found.")
    index_snapshot = services.documents.snapshot_index_files()
    try:
        original = services.documents.delete_document(document["name"])
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        _rebuild_knowledge_index(services)
    except HTTPException as exc:
        try:
            services.documents.restore_document(document["name"], original)
            services.documents.restore_index_files(index_snapshot)
            services.knowledge_index.invalidate()
        except (DocumentError, OSError):
            logger.exception("Document deletion rollback failed document_id=%s", document_id)
        logger.warning("Document deletion rolled back document_id=%s", document_id)
        raise HTTPException(
            status_code=503,
            detail="The document could not be removed from the knowledge index. Deletion was rolled back.",
        ) from exc
    return {"status": "deleted", "document_id": document_id, "index_refreshed": True}


@router.post("/documents/index")
def index_documents(
    services: Services,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    documents = _rebuild_knowledge_index(services)
    return {
        "status": "indexed",
        "scope": "all_documents",
        "documents": documents,
        "index": services.documents.index_health(),
    }


def _rebuild_knowledge_index(services: ServiceContainer) -> list[dict]:
    try:
        services.documents.record_all_index_results("indexing")
        services.knowledge_index.rebuild()
        services.documents.record_all_index_results("indexed")
    except (RuntimeError, OSError, ValueError) as exc:
        error = f"{type(exc).__name__}: {str(exc)[:180]}"
        try:
            services.documents.record_all_index_results("error", error)
        except OSError:
            logger.exception("Knowledge index status could not be recorded")
        logger.warning("Knowledge index rebuild failed error=%s", exc)
        raise HTTPException(
            status_code=503,
            detail="Index rebuild failed. Check document readability and OpenAI configuration.",
        ) from exc
    return services.documents.list_documents()
