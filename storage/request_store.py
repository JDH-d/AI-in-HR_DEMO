"""Persistence primitives. Authorization and lifecycle rules live in the service/domain."""

import hashlib
import json
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone

from domain.manager_queue import as_utc, attention_for_request
from domain.request_policy import STATUSES, RequestConflictError
from domain.workflow import TYPE_LABELS, WorkflowNotFoundError, duration_days, utc_now

# Cancellation does not publish a private draft. Derive sharing from the immutable
# history, including legacy review states, without rewriting existing records.
_SHARED_STATES = ",".join(
    f"'{status}'"
    for status in (*STATUSES, "declined", "done")
    if status not in {"draft", "cancelled"}
)
_SUBMISSION_EVIDENCE = f"""(workflow_requests.status IN ({_SHARED_STATES}) OR EXISTS (
    SELECT 1 FROM request_events e WHERE e.request_id=workflow_requests.id
    AND (e.from_status IN ({_SHARED_STATES}) OR e.to_status IN ({_SHARED_STATES}))))"""
_REQUEST_SELECT = (
    f"SELECT workflow_requests.*, {_SUBMISSION_EVIDENCE} AS was_submitted FROM workflow_requests"
)
# Only employee submissions/reconsiderations and replies begin a new review period.
# Taking a request into review, comments, and assignment events do not extend it.
_REVIEW_ANCHOR = """(SELECT json_object('created_at', e.created_at, 'event_type', e.event_type)
    FROM request_events e WHERE e.request_id=workflow_requests.id AND (
        (e.to_status='submitted' AND e.from_status IN ('draft','approved','rejected','completed'))
        OR (e.event_type='provide_information' AND e.from_status='needs_information'
            AND e.to_status='in_review'))
    ORDER BY e.created_at DESC, e.rowid DESC LIMIT 1)"""
_MANAGER_SCOPE = f"approver=? AND status != 'draft' AND {_SUBMISSION_EVIDENCE}"
_MANAGER_CTE = f"""WITH visible_requests AS (
    SELECT workflow_requests.*, 1 AS was_submitted, {_REVIEW_ANCHOR} AS review_anchor
    FROM workflow_requests WHERE {_MANAGER_SCOPE}
), annotated AS (
    SELECT visible_requests.*,
        manager_attention(status, priority, review_round, created_at, review_anchor) AS attention_data
    FROM visible_requests
) """
_REQUEST_SORTS = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "number": "number",
    "title": "casefold(title)",
    "priority": "CASE priority WHEN 'urgent' THEN 3 WHEN 'high' THEN 2 WHEN 'normal' THEN 1 ELSE 0 END",
}


def request_view(row) -> dict:
    return {
        **dict(row),
        "was_submitted": bool(row["was_submitted"]),
        "type_label": TYPE_LABELS.get(row["type"], row["type"]),
    }


class RequestStore:
    @staticmethod
    def _require_request(conn, request_id):
        row = conn.execute(_REQUEST_SELECT + " WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise WorkflowNotFoundError("The workflow request could not be found.")
        return row

    @staticmethod
    def last_decision_id(conn, request_id):
        row = conn.execute(
            "SELECT id FROM request_events WHERE request_id=? AND event_type='decision_recorded' ORDER BY rowid DESC LIMIT 1",
            (request_id,),
        ).fetchone()
        return row["id"] if row else None

    @staticmethod
    def attachment_count(conn, request_id):
        return conn.execute(
            "SELECT COUNT(*) FROM request_attachments WHERE request_id=?", (request_id,)
        ).fetchone()[0]

    @contextmanager
    def request_transaction(self, request_id: str):
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._require_request(conn, request_id)
                yield conn, request_view(row)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def create_draft(self, draft, *, creation_key: str | None = None) -> dict:
        # Scope a retry to its authenticated author. The existing primary key
        # and write transaction serialize concurrent retries without a migration.
        request_id = (
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                json.dumps(["peopleflow/request-create/v1", draft.applicant, creation_key]),
            ).hex
            if creation_key is not None
            else uuid.uuid4().hex
        )
        now = utc_now()
        try:
            duration = duration_days(draft.start_date, draft.end_date)
        except ValueError:
            duration = None
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if creation_key is not None:
                existing = conn.execute(_REQUEST_SELECT + " WHERE id=?", (request_id,)).fetchone()
                if existing is not None:
                    if existing["applicant"] != draft.applicant:
                        raise RequestConflictError("This creation attempt could not be recovered.")
                    expected = {
                        "type": draft.request_type,
                        "title": draft.title,
                        "priority": draft.priority,
                        "start_date": draft.start_date,
                        "end_date": draft.end_date,
                        "comment": draft.comment,
                        "approver": draft.approver,
                    }
                    if existing["status"] != "draft" or any(
                        existing[key] != value for key, value in expected.items()
                    ):
                        raise RequestConflictError(
                            f"REQ-{existing['number']:06d} was already saved for this attempt. "
                            "Open it in My requests to review the saved fields and status before editing. "
                            "Your latest changes were not applied."
                        )
                    return {**request_view(existing), "validation_errors": draft.validation_errors}
            self._ensure_user(conn, draft.applicant, "employee", draft.approver)
            number = conn.execute(
                "INSERT INTO request_numbers(request_id) VALUES (?)", (request_id,)
            ).lastrowid
            conn.execute(
                """INSERT INTO workflow_requests
                (id, number, type, title, priority, start_date, end_date, duration_days, comment,
                 applicant, approver, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)""",
                (
                    request_id,
                    number,
                    draft.request_type,
                    draft.title,
                    draft.priority,
                    draft.start_date,
                    draft.end_date,
                    duration,
                    draft.comment,
                    draft.applicant,
                    draft.approver,
                    now,
                    now,
                ),
            )
            snapshot = request_view(self._require_request(conn, request_id))
            self._insert_event(
                conn,
                request_id,
                "draft_created",
                None,
                "draft",
                draft.applicant,
                {"fields": snapshot, "validation_errors": draft.validation_errors},
            )
        return {**snapshot, "validation_errors": draft.validation_errors}

    def get_request(self, request_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(_REQUEST_SELECT + " WHERE id=?", (request_id,)).fetchone()
        return request_view(row) if row else None

    def list_by_user(self, applicant: str) -> list[dict]:
        return self.list_visible(applicant, "employee", limit=1000)["requests"]

    def list_visible(
        self,
        user_id,
        role,
        *,
        status=None,
        category=None,
        priority=None,
        q="",
        sort="updated_at",
        order="desc",
        limit=50,
        offset=0,
        assignee=None,
        attention="all",
        now=None,
    ) -> dict:
        if role == "manager":
            return self._list_manager(
                user_id,
                status=status,
                category=category,
                priority=priority,
                q=q,
                sort=sort,
                order=order,
                limit=limit,
                offset=offset,
                assignee=assignee,
                attention=attention,
                now=now,
            )
        scope, params = (
            ("applicant=?", [user_id])
            if role == "employee"
            else (f"approver=? AND status != 'draft' AND {_SUBMISSION_EVIDENCE}", [user_id])
        )
        if role not in {"employee", "manager"}:
            scope, params = "0=1", []
        where = [scope]
        for column, value in (("status", status), ("type", category), ("priority", priority)):
            if value:
                where.append(f"{column}=?")
                params.append(value)
        if q.strip():
            where.append("""(instr(casefold(title||' '||comment||' '||applicant||' '||approver||' '||
                printf('REQ-%06d', number)), ?) > 0 OR EXISTS
                (SELECT 1 FROM request_comments c WHERE c.request_id=workflow_requests.id
                 AND instr(casefold(c.body), ?) > 0))""")
            params.extend([q.strip().casefold()] * 2)
        # Sort identifiers are never interpolated from untrusted input.
        ordering = _REQUEST_SORTS.get(sort, "updated_at") + (" ASC" if order == "asc" else " DESC")
        clause = " AND ".join(where)
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            total = conn.execute(
                f"SELECT COUNT(*) FROM workflow_requests WHERE {clause}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"{_REQUEST_SELECT} WHERE {clause} ORDER BY {ordering}, number DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            counts = {
                r["status"]: r["count"]
                for r in conn.execute(
                    f"SELECT status, COUNT(*) AS count FROM workflow_requests WHERE {scope} GROUP BY status",
                    [user_id] if role in {"employee", "manager"} else [],
                )
            }
        return {"requests": [request_view(row) for row in rows], "total": total, "counts": counts}

    @staticmethod
    def review_anchor(conn, request_id):
        row = conn.execute(
            f"SELECT {_REVIEW_ANCHOR} AS anchor FROM workflow_requests WHERE id=?", (request_id,)
        ).fetchone()
        return json.loads(row["anchor"]) if row and row["anchor"] else None

    @staticmethod
    def _manager_query_functions(conn, now):
        # A pure domain rule serves both filtering and response metadata, so the
        # displayed deadline cannot disagree with the queue's overdue filter.
        now = as_utc(now) or datetime.now(timezone.utc)

        def metadata(status, priority, review_round, created_at, anchor):
            return json.dumps(
                attention_for_request(
                    {
                        "status": status,
                        "priority": priority,
                        "review_round": review_round,
                        "created_at": created_at,
                    },
                    json.loads(anchor) if anchor else None,
                    now,
                )
            )

        conn.create_function("manager_attention", 5, metadata, deterministic=True)

    def _list_manager(
        self,
        user_id,
        *,
        status,
        category,
        priority,
        q,
        sort,
        order,
        limit,
        offset,
        assignee,
        attention,
        now,
    ):
        where, params = [], [user_id]
        for column, value in (
            ("status", status),
            ("type", category),
            ("priority", priority),
            ("approver", assignee),
        ):
            if value:
                where.append(f"{column}=?")
                params.append(value)
        if attention == "overdue":
            where.append("json_extract(attention_data, '$.overdue')=1")
        elif attention == "needs_attention":
            where.append("json_array_length(attention_data, '$.reasons')>0")
        if q.strip():
            where.append("""(instr(casefold(title||' '||comment||' '||applicant||' '||approver||' '||
                printf('REQ-%06d', number)), ?) > 0 OR EXISTS
                (SELECT 1 FROM request_comments c WHERE c.request_id=annotated.id
                 AND instr(casefold(c.body), ?) > 0))""")
            params.extend([q.strip().casefold()] * 2)
        ordering = _REQUEST_SORTS.get(sort, "updated_at") + (" ASC" if order == "asc" else " DESC")
        clause = " AND ".join(where) or "1=1"
        with closing(self._connect()) as conn:
            self._manager_query_functions(conn, now)
            conn.execute("BEGIN")
            total = conn.execute(
                _MANAGER_CTE + f"SELECT COUNT(*) FROM annotated WHERE {clause}", params
            ).fetchone()[0]
            rows = conn.execute(
                _MANAGER_CTE
                + f"SELECT * FROM annotated WHERE {clause} ORDER BY {ordering}, number DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            counts = {
                r["status"]: r["count"]
                for r in conn.execute(
                    _MANAGER_CTE
                    + "SELECT status, COUNT(*) AS count FROM annotated GROUP BY status",
                    [user_id],
                )
            }
        requests = []
        for row in rows:
            item = request_view(row)
            item["manager_attention"] = json.loads(item.pop("attention_data"))
            item.pop("review_anchor")
            requests.append(item)
        return {"requests": requests, "total": total, "counts": counts}

    def manager_summary(self, user_id, now):
        with closing(self._connect()) as conn:
            self._manager_query_functions(conn, now)
            conn.execute("BEGIN")
            row = conn.execute(
                _MANAGER_CTE
                + """SELECT
                COALESCE(SUM(status='submitted'),0) AS new,
                COALESCE(SUM(status='in_review'),0) AS in_review,
                COALESCE(SUM(status='needs_information'),0) AS waiting_for_employee,
                COALESCE(SUM(status='approved'),0) AS awaiting_completion,
                COALESCE(SUM(json_extract(attention_data,'$.overdue')),0) AS overdue,
                COALESCE(SUM(json_array_length(attention_data,'$.reasons')>0),0) AS needs_attention,
                COALESCE(SUM(EXISTS (
                    SELECT 1 FROM request_events e WHERE e.request_id=annotated.id
                    AND e.to_status='completed' AND e.from_status!='completed'
                    AND julianday(e.created_at)>=julianday(?,'-30 days')
                    AND julianday(e.created_at)<=julianday(?)
                )),0) AS completed_last_30_days
                FROM annotated""",
                [user_id, now.isoformat(), now.isoformat()],
            ).fetchone()
        return dict(row)

    def manager_activity(self, user_id, *, limit=20, offset=0):
        # The same current-assignee scope applies to every event. Reassignment
        # therefore removes the old manager's access to its activity immediately.
        visible = f"SELECT id FROM workflow_requests WHERE {_MANAGER_SCOPE}"
        with closing(self._connect()) as conn:
            conn.execute("BEGIN")
            total = conn.execute(
                f"SELECT COUNT(*) FROM request_events WHERE request_id IN ({visible})", [user_id]
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT e.*, r.number AS request_number, r.title AS request_title
                FROM request_events e JOIN workflow_requests r ON r.id=e.request_id
                WHERE e.request_id IN ({visible})
                ORDER BY e.created_at DESC, e.rowid DESC LIMIT ? OFFSET ?""",
                [user_id, limit, offset],
            ).fetchall()
        return {
            "events": [{**dict(row), "details": json.loads(row["details"])} for row in rows],
            "total": total,
        }

    def update_request(
        self, conn, request: dict, actor: str, changes: dict, event_type: str, details=None
    ):
        allowed = {
            "type",
            "title",
            "priority",
            "comment",
            "start_date",
            "end_date",
            "duration_days",
            "approver",
            "status",
            "review_round",
        }
        if not set(changes) <= allowed:
            raise ValueError("Unsupported request field")
        differences = {
            key: {"before": request[key], "after": value}
            for key, value in changes.items()
            if request[key] != value
        }
        values = {**changes, "updated_at": utc_now(), "revision": request["revision"] + 1}
        conn.execute(
            f"UPDATE workflow_requests SET {', '.join(key + '=?' for key in values)} WHERE id=?",
            [*values.values(), request["id"]],
        )
        self._insert_event(
            conn,
            request["id"],
            event_type,
            request["status"],
            changes.get("status", request["status"]),
            actor,
            {**(details or {}), "changes": differences, "revision": values["revision"]},
        )
        return request_view(self._require_request(conn, request["id"]))

    def insert_comment(self, conn, request_id, author, body):
        item = {
            "id": uuid.uuid4().hex,
            "request_id": request_id,
            "author": author,
            "body": body,
            "created_at": utc_now(),
        }
        conn.execute(
            "INSERT INTO request_comments VALUES (:id, :request_id, :author, :body, :created_at)",
            item,
        )
        return item

    def insert_attachment(self, conn, request_id, author, filename, content_type, content):
        item = {
            "id": uuid.uuid4().hex,
            "request_id": request_id,
            "author": author,
            "filename": filename,
            "content_type": content_type,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "created_at": utc_now(),
        }
        conn.execute(
            """INSERT INTO request_attachments
            (id, request_id, filename, content_type, size, sha256, author, created_at, content)
            VALUES (:id, :request_id, :filename, :content_type, :size, :sha256, :author, :created_at, :content)""",
            {**item, "content": content},
        )
        return item

    def get_attachment(self, conn, request_id, attachment_id):
        row = conn.execute(
            "SELECT * FROM request_attachments WHERE request_id=? AND id=?",
            (request_id, attachment_id),
        ).fetchone()
        if row is None:
            raise WorkflowNotFoundError("Attachment not found.")
        return dict(row)

    def read_history(self, conn, request_id):
        events = [
            {**dict(row), "details": json.loads(row["details"])}
            for row in conn.execute(
                "SELECT * FROM request_events WHERE request_id=? ORDER BY created_at, rowid",
                (request_id,),
            )
        ]
        comments = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM request_comments WHERE request_id=? ORDER BY created_at, rowid",
                (request_id,),
            )
        ]
        attachments = [
            dict(row)
            for row in conn.execute(
                "SELECT id, filename, content_type, size, sha256, author, created_at FROM request_attachments WHERE request_id=? ORDER BY created_at, rowid",
                (request_id,),
            )
        ]
        return {"events": events, "comments": comments, "attachments": attachments}
