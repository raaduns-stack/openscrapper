import os
import uuid
from pathlib import Path

from src.db import db
from psycopg.types.json import Jsonb

CATEGORIES = ("payment", "account", "login", "system", "scraping", "billing", "other")
STATUSES = ("new", "open", "waiting_user", "waiting_internal", "resolved", "closed")
PRIORITIES = ("low", "normal", "high", "urgent")
UPLOAD_ROOT = Path(os.getenv("SUPPORT_UPLOAD_DIR", str(Path(__file__).resolve().parents[1] / "storage" / "support")))


def _ticket(row):
    return {"id": str(row[0]), "user_id": str(row[1]), "subject": row[2], "category": row[3],
            "priority": row[4], "status": row[5], "created_at": row[6].isoformat(),
            "updated_at": row[7].isoformat(), "resolved_at": row[8].isoformat() if row[8] else None,
            "closed_at": row[9].isoformat() if row[9] else None, "assigned_to": str(row[10]) if row[10] else None}


def create_ticket(user_id, subject, category, description, priority="normal"):
    if category not in CATEGORIES or priority not in PRIORITIES:
        raise ValueError("Invalid support category or priority")
    tid = uuid.uuid4()
    mid = uuid.uuid4()
    with db() as conn:
        conn.execute("INSERT INTO support_tickets(id,user_id,subject,category,priority,status) VALUES(%s,%s,%s,%s,%s,'new')",
                     (tid, user_id, subject.strip(), category, priority))
        conn.execute("INSERT INTO support_ticket_messages(id,ticket_id,author_id,body) VALUES(%s,%s,%s,%s)",
                     (mid, tid, user_id, description.strip()))
        conn.execute("INSERT INTO support_audit_events(id,ticket_id,actor_id,action,metadata) VALUES(%s,%s,%s,'ticket_created',%s)",
                     (uuid.uuid4(), tid, user_id, Jsonb({"category": category, "priority": priority})))
        conn.commit()
    return get_ticket(user_id, tid)


def get_ticket(user_id, ticket_id, admin=False):
    with db() as conn:
        row = conn.execute("SELECT id,user_id,subject,category,priority,status,created_at,updated_at,resolved_at,closed_at,assigned_to FROM support_tickets WHERE id=%s" + ("" if admin else " AND user_id=%s"),
                           (ticket_id,) if admin else (ticket_id, user_id)).fetchone()
        if not row:
            return None
        messages = conn.execute("SELECT m.id,m.author_id,u.email,m.body,m.is_internal,m.created_at FROM support_ticket_messages m LEFT JOIN users u ON u.id=m.author_id WHERE m.ticket_id=%s AND (%s OR m.is_internal=false) ORDER BY m.created_at",
                                (ticket_id, admin)).fetchall()
        attachments = conn.execute("SELECT id,message_id,filename,content_type,size_bytes,storage_path,created_at FROM support_ticket_attachments WHERE ticket_id=%s ORDER BY created_at",
                                   (ticket_id,)).fetchall()
        rating = conn.execute("SELECT score,comment,created_at FROM support_ticket_ratings WHERE ticket_id=%s", (ticket_id,)).fetchone()
    item = _ticket(row)
    item["messages"] = [{"id": str(x[0]), "author_id": str(x[1]) if x[1] else None, "email": x[2],
                         "body": x[3], "is_internal": bool(x[4]), "created_at": x[5].isoformat()} for x in messages]
    item["attachments"] = [{"id": str(x[0]), "message_id": str(x[1]) if x[1] else None, "filename": x[2],
                            "content_type": x[3], "size_bytes": x[4], "created_at": x[6].isoformat()} for x in attachments]
    item["rating"] = {"score": rating[0], "comment": rating[1], "created_at": rating[2].isoformat()} if rating else None
    return item


def list_tickets(user_id=None, status=None, category=None, admin=False, limit=100, offset=0, search=None):
    clauses, values = [], []
    if not admin:
        clauses.append("t.user_id=%s"); values.append(user_id)
    if status:
        statuses = [x.strip() for x in str(status).split(",") if x.strip()]
        if len(statuses) == 1:
            clauses.append("t.status=%s"); values.append(statuses[0])
        else:
            clauses.append("t.status=ANY(%s)"); values.append(statuses)
    if category:
        clauses.append("t.category=%s"); values.append(category)
    if search:
        pattern = f"%{search.strip()}%"
        clauses.append("(t.subject ILIKE %s OR EXISTS (SELECT 1 FROM users su WHERE su.id=t.user_id AND su.email ILIKE %s))")
        values.extend([pattern, pattern])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    values.append(max(1, min(limit, 200)))
    values.append(max(0, offset))
    with db() as conn:
        rows = conn.execute(f"SELECT t.id,t.user_id,t.subject,t.category,t.priority,t.status,t.created_at,t.updated_at,t.resolved_at,t.closed_at,t.assigned_to FROM support_tickets t{where} ORDER BY t.updated_at DESC LIMIT %s OFFSET %s", values).fetchall()
    return [_ticket(r) for r in rows]


def add_message(user_id, ticket_id, body, admin=False, internal=False):
    if not body.strip():
        raise ValueError("Message cannot be empty")
    item = get_ticket(user_id, ticket_id, admin=admin)
    if not item:
        return None
    mid = uuid.uuid4()
    next_status = "open" if admin and not internal else ("waiting_user" if internal is False and item["status"] == "open" and not admin else item["status"])
    with db() as conn:
        conn.execute("INSERT INTO support_ticket_messages(id,ticket_id,author_id,body,is_internal) VALUES(%s,%s,%s,%s,%s)",
                     (mid, ticket_id, user_id, body.strip(), internal))
        if admin and not internal:
            conn.execute("UPDATE support_tickets SET status='waiting_user',updated_at=now() WHERE id=%s", (ticket_id,))
        elif not admin:
            conn.execute("UPDATE support_tickets SET status='open',updated_at=now() WHERE id=%s", (ticket_id,))
        conn.execute("INSERT INTO support_audit_events(id,ticket_id,actor_id,action,metadata) VALUES(%s,%s,%s,%s,%s)",
                     (uuid.uuid4(), ticket_id, user_id, "internal_note_added" if internal else "message_added", Jsonb({})))
        conn.commit()
    return get_ticket(user_id, ticket_id, admin=admin)


def set_status(user_id, ticket_id, status, admin=False):
    if status not in STATUSES:
        raise ValueError("Invalid support status")
    item = get_ticket(user_id, ticket_id, admin=admin)
    if not item:
        return None
    with db() as conn:
        conn.execute("UPDATE support_tickets SET status=%s, resolved_at=CASE WHEN %s='resolved' THEN now() ELSE resolved_at END, closed_at=CASE WHEN %s='closed' THEN now() ELSE closed_at END, updated_at=now() WHERE id=%s",
                     (status, status, status, ticket_id))
        conn.execute("INSERT INTO support_audit_events(id,ticket_id,actor_id,action,metadata) VALUES(%s,%s,%s,'status_changed',%s)",
                     (uuid.uuid4(), ticket_id, user_id, Jsonb({"status": status})))
        conn.commit()
    return get_ticket(user_id, ticket_id, admin=admin)


def set_assignment(user_id, ticket_id, assigned_to):
    item = get_ticket(user_id, ticket_id, admin=True)
    if not item:
        return None
    aid = uuid.UUID(assigned_to) if assigned_to else None
    with db() as conn:
        conn.execute("UPDATE support_tickets SET assigned_to=%s,updated_at=now() WHERE id=%s", (aid, ticket_id))
        conn.execute("INSERT INTO support_audit_events(id,ticket_id,actor_id,action,metadata) VALUES(%s,%s,%s,'ticket_assigned',%s)",
                     (uuid.uuid4(), ticket_id, user_id, Jsonb({"assigned_to": assigned_to})))
        conn.commit()
    return get_ticket(user_id, ticket_id, admin=True)


def rate_ticket(user_id, ticket_id, score, comment=None):
    if not 1 <= score <= 5:
        raise ValueError("Rating must be between 1 and 5")
    item = get_ticket(user_id, ticket_id, admin=False)
    if not item:
        return None
    if item["status"] not in ("resolved", "closed"):
        raise ValueError("Only resolved or closed tickets can be rated")
    with db() as conn:
        conn.execute("INSERT INTO support_ticket_ratings(ticket_id,user_id,score,comment) VALUES(%s,%s,%s,%s) ON CONFLICT(ticket_id) DO UPDATE SET score=EXCLUDED.score,comment=EXCLUDED.comment,created_at=now()",
                     (ticket_id, user_id, score, (comment or "").strip() or None))
        conn.commit()
    return get_ticket(user_id, ticket_id, admin=False)


def get_attachment(user_id, ticket_id, attachment_id, admin=False):
    item = get_ticket(user_id, ticket_id, admin=admin)
    if not item:
        return None
    with db() as conn:
        row = conn.execute("SELECT filename,content_type,storage_path FROM support_ticket_attachments WHERE id=%s AND ticket_id=%s", (attachment_id, ticket_id)).fetchone()
    return {"filename": row[0], "content_type": row[1], "storage_path": row[2]} if row else None


def save_attachment(user_id, ticket_id, filename, content_type, data, message_id=None, admin=False):
    item = get_ticket(user_id, ticket_id, admin=admin)
    if not item:
        return None
    safe = Path(filename).name[:180]
    if not safe:
        raise ValueError("Invalid filename")
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("Attachment exceeds 10 MB")
    suffix = Path(safe).suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".txt"}
    if suffix not in allowed:
        raise ValueError("Unsupported attachment type")
    folder = UPLOAD_ROOT / str(ticket_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(data)
    with db() as conn:
        if message_id is None:
            message_row = conn.execute("SELECT id FROM support_ticket_messages WHERE ticket_id=%s AND author_id=%s AND is_internal=false ORDER BY created_at DESC LIMIT 1", (ticket_id, user_id)).fetchone()
            message_id = message_row[0] if message_row else None
        aid = uuid.uuid4()
        conn.execute("INSERT INTO support_ticket_attachments(id,ticket_id,message_id,user_id,filename,content_type,size_bytes,storage_path) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                     (aid, ticket_id, message_id, user_id, safe, content_type, len(data), str(path)))
        conn.execute("UPDATE support_tickets SET updated_at=now() WHERE id=%s", (ticket_id,))
        conn.commit()
    return get_ticket(user_id, ticket_id, admin=admin)
