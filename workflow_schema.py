from __future__ import annotations

import json
import sqlite3
import uuid

from workflow_domain import normalize_user_id, utc_now

SCHEMA_VERSION = 10


def initialize_workflow_schema(conn: sqlite3.Connection) -> None:
    needs_legacy_rebuild = _workflow_table_needs_rebuild(conn)
    foreign_keys = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    legacy_alter_table = int(conn.execute("PRAGMA legacy_alter_table").fetchone()[0])
    if needs_legacy_rebuild:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if schema_version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Workflow database schema {schema_version} is newer than supported "
                f"version {SCHEMA_VERSION}."
            )
        legacy_table = _rename_legacy_table(conn) if needs_legacy_rebuild else None
        _create_workflow_tables(conn)
        request_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(workflow_requests)").fetchall()
        }
        if "details" not in request_columns:
            conn.execute(
                "ALTER TABLE workflow_requests ADD COLUMN details TEXT NOT NULL DEFAULT '{}'"
            )
        if legacy_table:
            _migrate_legacy_rows(conn, legacy_table)
            _remove_orphaned_workflow_children(conn)
            conn.execute(f'DROP TABLE "{legacy_table}"')
        _ensure_workflow_indexes(conn)
        _run_versioned_migrations(conn, schema_version)

        assistant_feedback_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(assistant_feedback)").fetchall()
        }
        if "answer" not in assistant_feedback_columns:
            conn.execute(
                "ALTER TABLE assistant_feedback ADD COLUMN answer TEXT NOT NULL DEFAULT ''"
            )
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise sqlite3.IntegrityError("Workflow migration left invalid foreign-key references.")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        if needs_legacy_rebuild:
            conn.execute(f"PRAGMA legacy_alter_table = {legacy_alter_table}")
            conn.execute(f"PRAGMA foreign_keys = {foreign_keys}")


def _create_workflow_tables(conn: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS workflow_requests (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            duration_days INTEGER,
            comment TEXT NOT NULL,
            applicant TEXT NOT NULL,
            approver TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS request_events (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            actor TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (request_id) REFERENCES workflow_requests(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS request_comments (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            author TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (request_id) REFERENCES workflow_requests(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (request_id) REFERENCES workflow_requests(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_feedback (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS quality_reviews (
            item_id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
    )
    for statement in statements:
        conn.execute(statement)


def _ensure_workflow_indexes(conn: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE INDEX IF NOT EXISTS idx_requests_applicant
        ON workflow_requests(applicant, created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_events_request
        ON request_events(request_id, created_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_comments_request
        ON request_comments(request_id, created_at)
        """,
    )
    for statement in statements:
        conn.execute(statement)


def _run_versioned_migrations(conn: sqlite3.Connection, schema_version: int) -> None:
    if schema_version < 3:
        conn.execute("UPDATE workflow_requests SET status = 'in_review' WHERE status = 'submitted'")
        conn.execute(
            "UPDATE request_events SET from_status = 'in_review' WHERE from_status = 'submitted'"
        )
        conn.execute(
            "UPDATE request_events SET to_status = 'in_review' WHERE to_status = 'submitted'"
        )
        conn.execute(
            """
            DELETE FROM request_events
            WHERE event_type = 'status_changed'
              AND from_status = 'in_review'
              AND to_status = 'in_review'
            """
        )
    if schema_version < 4:
        conn.execute("UPDATE workflow_requests SET status = 'approved' WHERE status = 'completed'")
        conn.execute(
            "UPDATE request_events SET from_status = 'approved' WHERE from_status = 'completed'"
        )
        conn.execute(
            "UPDATE request_events SET to_status = 'approved' WHERE to_status = 'completed'"
        )
        conn.execute(
            """
            DELETE FROM request_events
            WHERE event_type = 'status_changed'
              AND from_status = 'approved'
              AND to_status = 'approved'
            """
        )
    if schema_version < 7:
        conn.execute(
            """
            UPDATE request_events
            SET from_status = 'reported'
            WHERE from_status = 'in_review'
              AND request_id IN (
                  SELECT id FROM workflow_requests
                  WHERE type = 'sick_leave' AND status = 'in_review'
              )
            """
        )
    if schema_version < 8:
        conn.execute(
            """
            UPDATE workflow_requests
            SET approver = 'manager.demo'
            WHERE lower(trim(approver)) IN ('manager', 'demo manager')
            """
        )
    if schema_version < 9:
        conn.execute("UPDATE assistant_feedback SET user_id = 'anonymous'")
    if schema_version < 10:
        conn.execute("DROP TABLE IF EXISTS users")
        conn.execute(
            """
            UPDATE request_events
            SET to_status = 'reported'
            WHERE to_status = 'in_review'
              AND request_id IN (
                  SELECT id FROM workflow_requests
                  WHERE type = 'sick_leave' AND status = 'in_review'
              )
            """
        )
        conn.execute(
            """
            UPDATE workflow_requests
            SET status = 'reported'
            WHERE type = 'sick_leave' AND status = 'in_review'
            """
        )


def _workflow_table_needs_rebuild(conn: sqlite3.Connection) -> bool:
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_requests'"
    ).fetchone()
    if not existing:
        return False
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(workflow_requests)").fetchall()
    }
    return not {"start_date", "applicant", "approver", "updated_at"}.issubset(columns)


def _rename_legacy_table(conn: sqlite3.Connection) -> str:
    legacy_table = f"workflow_requests_legacy_{uuid.uuid4().hex[:8]}"
    conn.execute(f'ALTER TABLE workflow_requests RENAME TO "{legacy_table}"')
    return legacy_table


def _remove_orphaned_workflow_children(conn: sqlite3.Connection) -> None:
    for table in ("request_events", "request_comments", "feedback"):
        conn.execute(
            f"""
            DELETE FROM {table}
            WHERE request_id NOT IN (SELECT id FROM workflow_requests)
            """
        )


def _migrate_legacy_rows(conn: sqlite3.Connection, legacy_table: str) -> None:
    status_map = {
        "new": "draft",
        "pending": "in_review",
        "approved": "approved",
        "declined": "declined",
        "done": "approved",
    }
    rows = conn.execute(f'SELECT * FROM "{legacy_table}"').fetchall()
    for row in rows:
        data = dict(row)
        request_type = {
            "pto": "pto",
            "sick": "sick_leave",
            "sick_leave": "sick_leave",
        }.get(str(data.get("type", "")).lower())
        if request_type is None:
            continue
        applicant = normalize_user_id(data.get("created_by"), "anonymous")
        approver = normalize_user_id(data.get("assigned_to"), "manager.demo")
        if approver.lower() in {"manager", "demo manager"}:
            approver = "manager.demo"
        created_at = data.get("created_at") or utc_now()
        status = status_map.get(str(data.get("status", "")).lower(), "in_review")
        conn.execute(
            """
            INSERT INTO workflow_requests
            (id, type, start_date, end_date, duration_days, comment, applicant, approver,
             details, status, created_at, updated_at)
            VALUES (?, ?, NULL, NULL, NULL, ?, ?, ?, '{}', ?, ?, ?)
            """,
            (
                data["id"],
                request_type,
                data.get("comment", ""),
                applicant,
                approver,
                status,
                created_at,
                created_at,
            ),
        )
        _insert_migration_event(
            conn,
            str(data["id"]),
            status,
            {"legacy_period": data.get("period_or_date", "")},
            created_at=str(created_at),
        )


def _insert_migration_event(
    conn: sqlite3.Connection,
    request_id: str,
    status: str,
    details: dict[str, object],
    *,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO request_events
        (id, request_id, event_type, from_status, to_status, actor, details, created_at)
        VALUES (?, ?, 'legacy_request_migrated', NULL, ?, 'system', ?, ?)
        """,
        (
            uuid.uuid4().hex,
            request_id,
            status,
            json.dumps(details, ensure_ascii=False),
            created_at,
        ),
    )
