"""HTTP-level tests for S1G's invitation endpoints — RBAC tiers, the
standard envelope, idempotency replay, and the security-critical
cross-workspace attack sweep (an Admin of Workspace A must never manage
Workspace B's invitations, by any means, including knowing an
invitation's UUID).

Same real-app-via-TestClient approach as test_workspace_api.py — see
that file and backend/tests/db.py's `run_http_test` docstring.

Raw invitation tokens are never returned by any API response (by
design — see `InvitationPublic`'s docstring), so tests that need one
(public details, accept) set a *known* token hash directly via a
throwaway `asyncpg` connection, the same technique `_add_member_via_db`
already uses in test_workspace_api.py for state the HTTP API itself has
no way to produce. One Mailpit-gated test (skipped if Mailpit isn't
reachable, same convention as app/core/tests/test_mailer.py) separately
proves email delivery is actually attempted end-to-end.
"""

import asyncio
import uuid

import asyncpg
import httpx
import pytest
from tests.db import HTTP_TEST_EMAIL_DOMAIN, run_http_test

from app.config import settings
from app.core.security import hash_refresh_token

_TEST_PASSWORD = "a-strong-password"


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@{HTTP_TEST_EMAIL_DOMAIN}"


async def _connect() -> asyncpg.Connection:
    db = settings.database
    return await asyncpg.connect(
        host=db.HOST, port=db.PORT, database=db.DB, user=db.USER, password=db.PASSWORD
    )


async def _activate_user(user_id: str) -> None:
    conn = await _connect()
    try:
        await conn.execute(
            "UPDATE users SET status = 'active', email_verified_at = now() WHERE id = $1",
            uuid.UUID(user_id),
        )
    finally:
        await conn.close()


def _register_login_and_id(client) -> tuple[dict, str]:
    client.cookies.clear()
    email = _email()
    register_response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _TEST_PASSWORD, "display_name": "Test User"},
    )
    assert register_response.status_code == 201
    user_id = register_response.json()["data"]["id"]
    asyncio.run(_activate_user(user_id))

    login_response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
    )
    assert login_response.status_code == 200
    return dict(client.cookies), user_id


def _register_and_login(client) -> dict:
    cookies, _user_id = _register_login_and_id(client)
    return cookies


def _as(client, cookies: dict) -> None:
    client.cookies.clear()
    client.cookies.update(cookies)


def _create_workspace(client, cookies: dict, name: str | None = None) -> dict:
    _as(client, cookies)
    if name is None:
        name = f"Test Workspace {uuid.uuid4().hex[:8]}"
    response = client.post("/api/v1/workspaces", json={"name": name})
    assert response.status_code == 201
    return response.json()["data"]["workspace"]


async def _add_member_via_db(workspace_id: str, user_id: str, role_name: str) -> None:
    conn = await _connect()
    try:
        role_id = await conn.fetchval("SELECT id FROM roles WHERE name = $1", role_name)
        await conn.execute(
            "INSERT INTO memberships (id, workspace_id, user_id, role_id, status) "
            "VALUES (gen_random_uuid(), $1, $2, $3, 'active')",
            uuid.UUID(workspace_id),
            uuid.UUID(user_id),
            role_id,
        )
    finally:
        await conn.close()


async def _role_id(name: str) -> str:
    conn = await _connect()
    try:
        row = await conn.fetchrow("SELECT id FROM roles WHERE name = $1", name)
        return str(row["id"])
    finally:
        await conn.close()


async def _set_known_token(invitation_id: str, raw_token: str) -> None:
    """Overwrite a real invitation's `token_hash` with the hash of a
    *known* raw token — the only way an HTTP-level test can obtain a raw
    token at all, since no API response ever returns one."""
    conn = await _connect()
    try:
        await conn.execute(
            "UPDATE invitations SET token_hash = $1 WHERE id = $2",
            hash_refresh_token(raw_token),
            uuid.UUID(invitation_id),
        )
    finally:
        await conn.close()


def _invite(client, workspace_id: str, email: str, role_name: str = "member") -> dict:
    role_id = asyncio.run(_role_id(role_name))
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/invitations",
        json={"email": email, "role_id": role_id},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201
    return response.json()["data"]


def _mailpit_available() -> bool:
    try:
        httpx.get("http://localhost:8025/api/v1/messages", timeout=1).raise_for_status()
        return True
    except Exception:  # noqa: BLE001 — any failure means "treat as unavailable, skip"
        return False


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_invitation_owner_can_invite() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)

        invitation = _invite(client, workspace["id"], _email())
        assert invitation["status"] == "pending"
        assert invitation["role"] == "member"
        assert "token_hash" not in invitation

    run_http_test(body)


def test_create_invitation_admin_can_invite() -> None:
    def body(client) -> None:
        owner_cookies, owner_id = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)

        admin_cookies, admin_id = _register_login_and_id(client)
        asyncio.run(_add_member_via_db(workspace["id"], admin_id, "admin"))

        _as(client, admin_cookies)
        invitation = _invite(client, workspace["id"], _email())
        assert invitation["status"] == "pending"
        assert owner_id  # sanity

    run_http_test(body)


def test_create_invitation_member_cannot_invite() -> None:
    def body(client) -> None:
        owner_cookies, _ = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)

        member_cookies, member_id = _register_login_and_id(client)
        asyncio.run(_add_member_via_db(workspace["id"], member_id, "member"))

        _as(client, member_cookies)
        role_id = asyncio.run(_role_id("member"))
        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations",
            json={"email": _email(), "role_id": role_id},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 403

    run_http_test(body)


def test_create_invitation_viewer_cannot_invite() -> None:
    def body(client) -> None:
        owner_cookies, _ = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)

        viewer_cookies, viewer_id = _register_login_and_id(client)
        asyncio.run(_add_member_via_db(workspace["id"], viewer_id, "viewer"))

        _as(client, viewer_cookies)
        role_id = asyncio.run(_role_id("member"))
        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations",
            json={"email": _email(), "role_id": role_id},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 403

    run_http_test(body)


def test_create_invitation_non_member_gets_404() -> None:
    def body(client) -> None:
        owner_cookies, _ = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)

        outsider_cookies, _ = _register_login_and_id(client)
        _as(client, outsider_cookies)
        role_id = asyncio.run(_role_id("member"))
        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations",
            json={"email": _email(), "role_id": role_id},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "workspace_not_found"

    run_http_test(body)


def test_create_invitation_requires_idempotency_key_header() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        role_id = asyncio.run(_role_id("member"))

        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations",
            json={"email": _email(), "role_id": role_id},
        )
        assert response.status_code == 422

    run_http_test(body)


def test_create_invitation_idempotency_key_replays_same_invitation() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        role_id = asyncio.run(_role_id("member"))
        email = _email()
        key = str(uuid.uuid4())

        first = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations",
            json={"email": email, "role_id": role_id},
            headers={"Idempotency-Key": key},
        )
        second = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations",
            json={"email": email, "role_id": role_id},
            headers={"Idempotency-Key": key},
        )

        assert first.status_code == second.status_code == 201
        assert first.json()["data"]["id"] == second.json()["data"]["id"]

    run_http_test(body)


def test_create_invitation_different_key_creates_distinct_invitations() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        role_id = asyncio.run(_role_id("member"))
        email = _email()

        first = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations",
            json={"email": email, "role_id": role_id},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        second = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations",
            json={"email": email, "role_id": role_id},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )

        assert first.status_code == second.status_code == 201
        assert first.json()["data"]["id"] != second.json()["data"]["id"]  # replaced, not merged

    run_http_test(body)


@pytest.mark.skipif(
    not _mailpit_available(), reason="Mailpit not reachable at localhost:8025 — skipping"
)
def test_create_invitation_sends_email_via_mailpit() -> None:
    def body(client) -> None:
        httpx.delete("http://localhost:8025/api/v1/messages", timeout=2)

        cookies = _register_and_login(client)
        workspace = _create_workspace(
            client, cookies, name=f"Mailpit HTTP Test {uuid.uuid4().hex[:6]}"
        )
        invited_email = _email()

        _invite(client, workspace["id"], invited_email)

        response = httpx.get(
            "http://localhost:8025/api/v1/messages",
            params={"query": f"to:{invited_email}"},
            timeout=3,
        )
        data = response.json()
        assert data["total"] >= 1

        httpx.delete("http://localhost:8025/api/v1/messages", timeout=2)

    run_http_test(body)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_invitations_admin_and_owner_can_view() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        _invite(client, workspace["id"], _email())

        response = client.get(f"/api/v1/workspaces/{workspace['id']}/invitations")
        assert response.status_code == 200
        entries = response.json()["data"]
        assert len(entries) == 1
        assert entries[0]["status"] == "pending"
        assert "token_hash" not in entries[0]

    run_http_test(body)


def test_list_invitations_member_cannot_view() -> None:
    def body(client) -> None:
        owner_cookies, _ = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)
        _invite(client, workspace["id"], _email())

        member_cookies, member_id = _register_login_and_id(client)
        asyncio.run(_add_member_via_db(workspace["id"], member_id, "member"))

        _as(client, member_cookies)
        response = client.get(f"/api/v1/workspaces/{workspace['id']}/invitations")
        assert response.status_code == 403

    run_http_test(body)


def test_list_invitations_excludes_resolved() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        pending = _invite(client, workspace["id"], _email())
        to_revoke = _invite(client, workspace["id"], _email())

        revoke_response = client.delete(
            f"/api/v1/workspaces/{workspace['id']}/invitations/{to_revoke['id']}"
        )
        assert revoke_response.status_code == 204

        response = client.get(f"/api/v1/workspaces/{workspace['id']}/invitations")
        ids = [i["id"] for i in response.json()["data"]]
        assert ids == [pending["id"]]

    run_http_test(body)


# ---------------------------------------------------------------------------
# Resend
# ---------------------------------------------------------------------------


def test_resend_invitation_succeeds_with_202() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        invitation = _invite(client, workspace["id"], _email())

        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations/{invitation['id']}/resend"
        )
        assert response.status_code == 202
        assert response.json()["data"]["id"] == invitation["id"]

    run_http_test(body)


def test_resend_invitation_member_cannot_resend() -> None:
    def body(client) -> None:
        owner_cookies, _ = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)
        invitation = _invite(client, workspace["id"], _email())

        member_cookies, member_id = _register_login_and_id(client)
        asyncio.run(_add_member_via_db(workspace["id"], member_id, "member"))

        _as(client, member_cookies)
        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations/{invitation['id']}/resend"
        )
        assert response.status_code == 403

    run_http_test(body)


def test_resend_invitation_already_resolved_rejected() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        invitation = _invite(client, workspace["id"], _email())

        client.delete(f"/api/v1/workspaces/{workspace['id']}/invitations/{invitation['id']}")

        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/invitations/{invitation['id']}/resend"
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "invitation_already_resolved"

    run_http_test(body)


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------


def test_revoke_invitation_admin_and_owner_can_revoke() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        invitation = _invite(client, workspace["id"], _email())

        response = client.delete(
            f"/api/v1/workspaces/{workspace['id']}/invitations/{invitation['id']}"
        )
        assert response.status_code == 204

    run_http_test(body)


def test_revoke_invitation_member_cannot_revoke() -> None:
    def body(client) -> None:
        owner_cookies, _ = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)
        invitation = _invite(client, workspace["id"], _email())

        member_cookies, member_id = _register_login_and_id(client)
        asyncio.run(_add_member_via_db(workspace["id"], member_id, "member"))

        _as(client, member_cookies)
        response = client.delete(
            f"/api/v1/workspaces/{workspace['id']}/invitations/{invitation['id']}"
        )
        assert response.status_code == 403

    run_http_test(body)


def test_revoke_invitation_already_resolved_rejected() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        invitation = _invite(client, workspace["id"], _email())

        first = client.delete(
            f"/api/v1/workspaces/{workspace['id']}/invitations/{invitation['id']}"
        )
        assert first.status_code == 204

        second = client.delete(
            f"/api/v1/workspaces/{workspace['id']}/invitations/{invitation['id']}"
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "invitation_already_resolved"

    run_http_test(body)


# ---------------------------------------------------------------------------
# Public details
# ---------------------------------------------------------------------------


def test_get_invitation_details_public_no_auth_required() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        invited_email = _email()
        invitation = _invite(client, workspace["id"], invited_email)
        raw_token = "public-details-test-token"
        asyncio.run(_set_known_token(invitation["id"], raw_token))

        client.cookies.clear()  # no auth cookie at all
        response = client.get(f"/api/v1/invitations/{raw_token}")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["invited_email"] == invited_email
        assert data["workspace_id"] == workspace["id"]
        assert data["status"] == "pending"
        assert "token_hash" not in data
        assert "invited_by_user_id" not in data

    run_http_test(body)


def test_get_invitation_details_invalid_token_rejected() -> None:
    def body(client) -> None:
        response = client.get("/api/v1/invitations/not-a-real-token")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "token_invalid"

    run_http_test(body)


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------


def test_accept_invitation_unauthenticated_rejected() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        invitation = _invite(client, workspace["id"], _email())
        raw_token = "accept-http-token-1"
        asyncio.run(_set_known_token(invitation["id"], raw_token))

        client.cookies.clear()
        response = client.post(
            f"/api/v1/invitations/{raw_token}/accept",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 401

    run_http_test(body)


def test_accept_invitation_email_mismatch() -> None:
    def body(client) -> None:
        owner_cookies, _ = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)
        invitation = _invite(client, workspace["id"], _email())  # invited email != impostor's
        raw_token = "accept-http-token-2"
        asyncio.run(_set_known_token(invitation["id"], raw_token))

        impostor_cookies, _ = _register_login_and_id(client)
        _as(client, impostor_cookies)
        response = client.post(
            f"/api/v1/invitations/{raw_token}/accept",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "email_mismatch"

    run_http_test(body)


def test_accept_invitation_succeeds_and_returns_membership() -> None:
    def body(client) -> None:
        owner_cookies, _ = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)

        invitee_cookies, invitee_id = _register_login_and_id(client)

        # Re-derive the invitee's own email from the DB (register response
        # doesn't echo it back, and cookies alone don't reveal it).
        async def _get_email(user_id: str) -> str:
            conn = await _connect()
            try:
                return await conn.fetchval(
                    "SELECT email FROM users WHERE id = $1", uuid.UUID(user_id)
                )
            finally:
                await conn.close()

        invitee_email = asyncio.run(_get_email(invitee_id))

        _as(client, owner_cookies)
        invitation = _invite(client, workspace["id"], invitee_email, role_name="admin")
        raw_token = "accept-http-token-3"
        asyncio.run(_set_known_token(invitation["id"], raw_token))

        _as(client, invitee_cookies)
        response = client.post(
            f"/api/v1/invitations/{raw_token}/accept",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 200
        membership = response.json()["data"]
        assert membership["workspace_id"] == workspace["id"]
        assert membership["user_id"] == invitee_id
        assert membership["role"] == "admin"
        assert membership["status"] == "active"

        # And they now actually appear in the member list.
        _as(client, owner_cookies)
        members = client.get(f"/api/v1/workspaces/{workspace['id']}/members").json()["data"]
        assert any(m["user"]["id"] == invitee_id for m in members)

    run_http_test(body)


def test_accept_invitation_requires_idempotency_key_header() -> None:
    def body(client) -> None:
        owner_cookies, _ = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)
        invitation = _invite(client, workspace["id"], _email())
        raw_token = "accept-http-token-4"
        asyncio.run(_set_known_token(invitation["id"], raw_token))

        response = client.post(f"/api/v1/invitations/{raw_token}/accept")
        assert response.status_code == 422

    run_http_test(body)


# ---------------------------------------------------------------------------
# Cross-workspace attack sweep — S1G's own required scenario: "User A is
# Admin in Workspace A. User A attempts to: list Workspace B invitations,
# resend Workspace B invitation, revoke Workspace B invitation, create
# invitation in Workspace B. Every unauthorized operation must fail."
# ---------------------------------------------------------------------------


def test_cross_workspace_invitation_attack_sweep() -> None:
    def body(client) -> None:
        cookies_a = _register_and_login(client)
        _create_workspace(client, cookies_a)

        cookies_b = _register_and_login(client)
        workspace_b = _create_workspace(client, cookies_b)
        invitation_b = _invite(client, workspace_b["id"], _email())

        # Back to User A (Owner of Workspace A, non-member of B),
        # attacking Workspace B's invitations.
        _as(client, cookies_a)
        role_id = asyncio.run(_role_id("member"))
        wid = workspace_b["id"]

        attacks = [
            (
                "POST",
                f"/api/v1/workspaces/{wid}/invitations",
                {"email": _email(), "role_id": role_id},
                {"Idempotency-Key": str(uuid.uuid4())},
            ),
            ("GET", f"/api/v1/workspaces/{wid}/invitations", None, None),
            (
                "POST",
                f"/api/v1/workspaces/{wid}/invitations/{invitation_b['id']}/resend",
                None,
                None,
            ),
            ("DELETE", f"/api/v1/workspaces/{wid}/invitations/{invitation_b['id']}", None, None),
        ]

        for method, url, json_body, headers in attacks:
            response = client.request(method, url, json=json_body, headers=headers)
            assert response.status_code in (403, 404), f"{method} {url} → {response.status_code}"
            if response.status_code == 404:
                assert response.json()["error"]["code"] == "workspace_not_found"

        # And Workspace B's invitation was never actually touched.
        _as(client, cookies_b)
        unchanged = client.get(f"/api/v1/workspaces/{wid}/invitations").json()["data"]
        assert len(unchanged) == 1
        assert unchanged[0]["status"] == "pending"

    run_http_test(body)


def test_accept_invitation_membership_always_bound_to_invitations_own_workspace() -> None:
    """The accept endpoint takes no client-supplied `workspace_id` at
    all (only the opaque token) — this proves the resulting Membership
    is always scoped to the *invitation's* workspace regardless of which
    other workspaces the accepting user belongs to."""

    def body(client) -> None:
        owner_a_cookies, _ = _register_login_and_id(client)
        workspace_a = _create_workspace(
            client, owner_a_cookies, name=f"Workspace A {uuid.uuid4().hex[:6]}"
        )

        owner_b_cookies, _ = _register_login_and_id(client)
        workspace_b = _create_workspace(
            client, owner_b_cookies, name=f"Workspace B {uuid.uuid4().hex[:6]}"
        )

        invitee_cookies, invitee_id = _register_login_and_id(client)

        async def _get_email(user_id: str) -> str:
            conn = await _connect()
            try:
                return await conn.fetchval(
                    "SELECT email FROM users WHERE id = $1", uuid.UUID(user_id)
                )
            finally:
                await conn.close()

        invitee_email = asyncio.run(_get_email(invitee_id))

        # The invitee is already a member of Workspace A (unrelated) —
        # proves accept doesn't get confused by the caller's *other*
        # memberships.
        asyncio.run(_add_member_via_db(workspace_a["id"], invitee_id, "member"))

        _as(client, owner_b_cookies)
        invitation = _invite(client, workspace_b["id"], invitee_email)
        raw_token = "cross-boundary-test-token"
        asyncio.run(_set_known_token(invitation["id"], raw_token))

        _as(client, invitee_cookies)
        response = client.post(
            f"/api/v1/invitations/{raw_token}/accept",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 200
        assert response.json()["data"]["workspace_id"] == workspace_b["id"]

    run_http_test(body)
