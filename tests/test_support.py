import os
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import app as api
from src.db import db


def _register(client, prefix):
    email = f"{prefix}-{uuid.uuid4().hex}@example.test"
    response = client.post("/auth/register", json={"email": email, "password": "StrongTestPassword123!"})
    assert response.status_code == 200
    return response.json(), email


def test_support_ticket_lifecycle_and_user_isolation():
    client = TestClient(api.app)
    customer, _ = _register(client, "support-customer")
    other, _ = _register(client, "support-other")
    headers = {"Authorization": f"Bearer {customer['token']}"}
    other_headers = {"Authorization": f"Bearer {other['token']}"}
    created = client.post("/support/tickets", headers=headers, json={
        "subject": "Payment issue",
        "category": "payment",
        "description": "My payment needs review.",
        "priority": "high",
    })
    assert created.status_code == 200
    ticket_id = created.json()["id"]
    assert created.json()["status"] == "new"
    assert client.get(f"/support/tickets/{ticket_id}", headers=other_headers).status_code == 404
    reply = client.post(f"/support/tickets/{ticket_id}/messages", headers=headers, json={"body": "Additional details."})
    assert reply.status_code == 200
    assert reply.json()["status"] == "open"
    resolved = client.post(f"/support/tickets/{ticket_id}/resolve", headers=headers)
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    rated = client.post(f"/support/tickets/{ticket_id}/rating", headers=headers, json={"score": 5, "comment": "Resolved."})
    assert rated.status_code == 200
    assert rated.json()["rating"]["score"] == 5


def test_support_admin_assignment_is_authorized_and_persistent():
    client = TestClient(api.app)
    customer, _ = _register(client, "support-assignment-customer")
    admin, admin_email = _register(client, "support-admin")
    os.environ["ADMIN_EMAILS"] = admin_email
    customer_headers = {"Authorization": f"Bearer {customer['token']}"}
    admin_headers = {"Authorization": f"Bearer {admin['token']}"}
    created = client.post("/support/tickets", headers=customer_headers, json={
        "subject": "Assign me",
        "category": "system",
        "description": "Please assign this ticket.",
    })
    assert created.status_code == 200
    ticket_id = created.json()["id"]
    assignees = client.get("/admin/support/assignees", headers=admin_headers)
    assert assignees.status_code == 200
    assert any(row["id"] == admin["user_id"] for row in assignees.json())
    assigned = client.post(f"/admin/support/tickets/{ticket_id}/assignment", headers=admin_headers,
                           json={"assigned_to": admin["user_id"]})
    assert assigned.status_code == 200
    assert assigned.json()["assigned_to"] == admin["user_id"]
    detail = client.get(f"/admin/support/tickets/{ticket_id}", headers=admin_headers)
    assert detail.status_code == 200
    assert detail.json()["assigned_to"] == admin["user_id"]


def test_support_admin_cannot_assign_non_admin():
    client = TestClient(api.app)
    customer, _ = _register(client, "support-nonadmin-customer")
    admin, admin_email = _register(client, "support-authorized-admin")
    nonadmin, _ = _register(client, "support-untrusted")
    os.environ["ADMIN_EMAILS"] = admin_email
    customer_headers = {"Authorization": f"Bearer {customer['token']}"}
    admin_headers = {"Authorization": f"Bearer {admin['token']}"}
    created = client.post("/support/tickets", headers=customer_headers, json={
        "subject": "Authorization test",
        "category": "account",
        "description": "Assignment authorization.",
    })
    assert created.status_code == 200
    ticket_id = created.json()["id"]
    response = client.post(f"/admin/support/tickets/{ticket_id}/assignment", headers=admin_headers,
                           json={"assigned_to": nonadmin["user_id"]})
    assert response.status_code == 403


def test_support_attachment_response_does_not_expose_storage_path():
    client = TestClient(api.app)
    customer, _ = _register(client, "support-attachment")
    headers = {"Authorization": f"Bearer {customer['token']}"}
    created = client.post("/support/tickets", headers=headers, json={
        "subject": "Attachment test",
        "category": "system",
        "description": "Attachment response must be safe.",
    })
    assert created.status_code == 200
    ticket_id = created.json()["id"]
    upload = client.post(f"/support/tickets/{ticket_id}/attachments", headers=headers,
                         files={"file": ("note.txt", b"support attachment", "text/plain")})
    assert upload.status_code == 200
    assert "storage_path" not in upload.json()["attachments"][-1]

def test_admin_support_reply_sends_customer_email_notification():
    client = TestClient(api.app)
    customer, customer_email = _register(client, "support-email-customer")
    admin, admin_email = _register(client, "support-email-admin")
    os.environ["ADMIN_EMAILS"] = admin_email
    customer_headers = {"Authorization": f"Bearer {customer['token']}"}
    admin_headers = {"Authorization": f"Bearer {admin['token']}"}
    created = client.post("/support/tickets", headers=customer_headers, json={
        "subject": "Extension is not working",
        "category": "system",
        "description": "The extension stops while scraping.",
    })
    assert created.status_code == 200
    ticket_id = created.json()["id"]
    sent = []

    class FakeSMTP:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def login(self, *_):
            pass

        def sendmail(self, sender, recipients, message):
            sent.append((sender, recipients, message))

    with patch.object(api.smtplib, "SMTP_SSL", return_value=FakeSMTP()):
        response = client.post(f"/admin/support/tickets/{ticket_id}/messages", headers=admin_headers,
                               json={"body": "Please reinstall the extension and sign in again."})

    assert response.status_code == 200
    assert len(sent) == 1
    assert sent[0][1] == [customer_email]
    assert "support ticket responded to" in sent[0][2]
    assert "Please reinstall the extension and sign in again." in sent[0][2]
    assert "Action required:" in sent[0][2]
