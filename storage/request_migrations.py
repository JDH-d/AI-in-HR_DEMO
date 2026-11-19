"""Additive, transactional migrations; historical events are never rewritten."""

import json
import uuid

from domain.workflow import TYPE_LABELS, utc_now


def migrate_requests(conn) -> None:
    conn.execute("BEGIN IMMEDIATE")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(workflow_requests)")}
    additions = {
        "number": "INTEGER",
        "title": "TEXT NOT NULL DEFAULT ''",
        "priority": "TEXT NOT NULL DEFAULT 'normal'",
        "revision": "INTEGER NOT NULL DEFAULT 1",
        "review_round": "INTEGER NOT NULL DEFAULT 1",
    }
    for column, definition in additions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE workflow_requests ADD COLUMN {column} {definition}")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS request_numbers (number INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL)"
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS request_attachments (
        id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES workflow_requests(id),
        filename TEXT NOT NULL, content_type TEXT NOT NULL, size INTEGER NOT NULL,
        sha256 TEXT NOT NULL, content BLOB NOT NULL, author TEXT NOT NULL, created_at TEXT NOT NULL
    )""")
    rows = conn.execute(
        "SELECT * FROM workflow_requests WHERE number IS NULL ORDER BY created_at, id"
    ).fetchall()
    for row in rows:
        cursor = conn.execute("INSERT INTO request_numbers(request_id) VALUES (?)", (row["id"],))
        title = (row["comment"].strip().splitlines() or [TYPE_LABELS.get(row["type"], "Request")])[
            0
        ][:160]
        status = {"declined": "rejected", "done": "completed"}.get(row["status"], row["status"])
        approver = "manager.demo" if row["approver"] in {"Manager", "HR"} else row["approver"]
        changes = {
            key: {"before": None, "after": value}
            for key, value in (
                ("number", cursor.lastrowid),
                ("title", title),
                ("priority", "normal"),
            )
        }
        for key, value in (("status", status), ("approver", approver)):
            if row[key] != value:
                changes[key] = {"before": row[key], "after": value}
        conn.execute(
            "UPDATE workflow_requests SET number=?, title=?, status=?, approver=? WHERE id=?",
            (cursor.lastrowid, title, status, approver, row["id"]),
        )
        conn.execute(
            "INSERT INTO request_events VALUES (?, ?, 'schema_migrated', ?, ?, 'system', ?, ?)",
            (
                uuid.uuid4().hex,
                row["id"],
                row["status"],
                status,
                json.dumps({"changes": changes}),
                utc_now(),
            ),
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_request_number ON workflow_requests(number)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_request_assignee ON workflow_requests(approver, status, updated_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_request_attachment ON request_attachments(request_id)"
    )
    # App-level append-only audit, including protection against accidental SQL rewrites.
    # A database administrator can still replace the database; this is not cryptographic tamper proofing.
    for table in ("request_events", "request_comments", "request_attachments"):
        for operation in ("UPDATE", "DELETE"):
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()}
                BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'Request audit records are append-only'); END""")
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
