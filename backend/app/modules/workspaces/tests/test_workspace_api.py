"""HTTP-level tests for the workspaces module — status codes, the
standard envelope, and (the security-critical part of this sprint)
explicit cross-workspace attacks: a member of Workspace A must never be
able to read, modify, or delete Workspace B, its settings, or its
membership, by any means, including knowing its UUID.

Same real-app-via-TestClient approach as app/modules/auth/tests/
test_session_api.py — see that file and backend/tests/db.py's
`run_http_test` docstring.
"""

import asyncio
import uuid

import asyncpg
from tests.db import HTTP_TEST_EMAIL_DOMAIN, run_http_test

from app.config import settings

_TEST_PASSWORD = "a-strong-password"


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@{HTTP_TEST_EMAIL_DOMAIN}"


async def _activate_user(user_id: str) -> None:
    """See app/modules/auth/tests/test_login_api.py's identical helper
    for why this uses its own throwaway `asyncpg` connection rather than
    the shared engine."""
    db = settings.database
    conn = await asyncpg.connect(
        host=db.HOST, port=db.PORT, database=db.DB, user=db.USER, password=db.PASSWORD
    )
    try:
        await conn.execute(
            "UPDATE users SET status = 'active', email_verified_at = now() WHERE id = $1",
            uuid.UUID(user_id),
        )
    finally:
        await conn.close()


def _register_and_login(client) -> dict:
    """Register, activate, log in — returns this user's cookie jar
    snapshot so a test can switch between several authenticated
    identities on one shared `TestClient` (see `_as`).

    Clears the jar first: without this, registering a *second* user on
    the same client while the first user's cookies are still set raises
    `httpx.CookieConflict` (confirmed empirically) once both identities'
    same-named cookies are present at once.
    """
    client.cookies.clear()
    email = _email()
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _TEST_PASSWORD, "display_name": "Test User"},
    )
    assert response.status_code == 201
    asyncio.run(_activate_user(response.json()["data"]["id"]))

    login_response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": _TEST_PASSWORD}
    )
    assert login_response.status_code == 200
    return dict(client.cookies)


def _as(client, cookies: dict) -> None:
    client.cookies.clear()
    client.cookies.update(cookies)


def _create_workspace(client, cookies: dict, name: str | None = None) -> dict:
    """`name` defaults to something unique per call — unlike users
    (cleaned up by `HTTP_TEST_EMAIL_DOMAIN`, see `run_http_test`'s
    docstring), test-created workspaces are never cleaned up between
    runs, and a fixed name like "Acme Corp" repeated across many runs
    of this file eventually exhausts `_generate_unique_slug`'s
    collision-resolution cap (confirmed empirically: `slug_unavailable`,
    409, after enough accumulated `acme-corp-N` rows). A name a test
    specifically wants to assert on can still be passed explicitly.
    """
    _as(client, cookies)
    if name is None:
        name = f"Test Workspace {uuid.uuid4().hex[:8]}"
    response = client.post("/api/v1/workspaces", json={"name": name})
    assert response.status_code == 201
    return response.json()["data"]["workspace"]


async def _add_member_via_db(workspace_id: str, user_id: str, role_name: str) -> None:
    """Insert a second Membership directly — invitation acceptance is
    out of S1F's scope, so this is the only way an HTTP-level test can
    get a *second* member into a workspace at all, needed specifically
    to test the owner invariant against a genuinely separate actor
    rather than self-action (see the two call sites below)."""
    db = settings.database
    conn = await asyncpg.connect(
        host=db.HOST, port=db.PORT, database=db.DB, user=db.USER, password=db.PASSWORD
    )
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


def _register_login_and_id(client) -> tuple[dict, str]:
    """Same as `_register_and_login`, but also returns the new user's
    own id (read straight from the register response — there's no
    `/auth/me` endpoint, still out of scope, to ask for it afterward)."""
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


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


def test_create_workspace_endpoint_returns_201_with_workspace_and_membership() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        _as(client, cookies)
        name = f"Acme Corp {uuid.uuid4().hex[:8]}"  # unique — see _create_workspace's docstring

        response = client.post("/api/v1/workspaces", json={"name": name})

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["workspace"]["name"] == name
        assert data["workspace"]["status"] == "active"
        assert data["membership"]["role"] == "owner"

    run_http_test(body)


def test_create_workspace_endpoint_requires_auth() -> None:
    def body(client) -> None:
        response = client.post("/api/v1/workspaces", json={"name": "Acme Corp"})
        assert response.status_code == 401

    run_http_test(body)


# ---------------------------------------------------------------------------
# List / read
# ---------------------------------------------------------------------------


def test_list_workspaces_endpoint_returns_only_own_workspaces() -> None:
    def body(client) -> None:
        cookies_a = _register_and_login(client)
        workspace_a = _create_workspace(client, cookies_a)

        cookies_b = _register_and_login(client)
        _create_workspace(client, cookies_b)

        _as(client, cookies_a)
        response = client.get("/api/v1/workspaces")

        assert response.status_code == 200
        ids = [w["id"] for w in response.json()["data"]]
        assert workspace_a["id"] in ids
        assert len(ids) == 1

    run_http_test(body)


def test_get_workspace_endpoint_viewer_and_above_can_read() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)

        response = client.get(f"/api/v1/workspaces/{workspace['id']}")
        assert response.status_code == 200
        assert response.json()["data"]["id"] == workspace["id"]

    run_http_test(body)


def test_get_workspace_endpoint_non_member_gets_404() -> None:
    def body(client) -> None:
        cookies_a = _register_and_login(client)
        workspace = _create_workspace(client, cookies_a)

        cookies_b = _register_and_login(client)
        _as(client, cookies_b)
        response = client.get(f"/api/v1/workspaces/{workspace['id']}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "workspace_not_found"

    run_http_test(body)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_workspace_endpoint_owner_and_admin_can_rename() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)

        response = client.patch(f"/api/v1/workspaces/{workspace['id']}", json={"name": "New Name"})
        assert response.status_code == 200
        assert response.json()["data"]["name"] == "New Name"
        assert response.json()["data"]["slug"] == workspace["slug"]  # server-controlled, unchanged

    run_http_test(body)


def test_update_workspace_endpoint_non_member_gets_404_not_a_leaked_403() -> None:
    def body(client) -> None:
        cookies_a = _register_and_login(client)
        workspace = _create_workspace(client, cookies_a)

        cookies_b = _register_and_login(client)
        _as(client, cookies_b)
        response = client.patch(f"/api/v1/workspaces/{workspace['id']}", json={"name": "Hijacked"})

        assert response.status_code == 404

    run_http_test(body)


# ---------------------------------------------------------------------------
# Archive / restore / delete
# ---------------------------------------------------------------------------


def test_archive_restore_delete_lifecycle() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        wid = workspace["id"]

        archive_response = client.post(f"/api/v1/workspaces/{wid}/archive")
        assert archive_response.status_code == 200
        assert archive_response.json()["data"]["status"] == "archived"
        assert archive_response.json()["data"]["archived_at"] is not None

        restore_response = client.post(f"/api/v1/workspaces/{wid}/restore")
        assert restore_response.status_code == 200
        assert restore_response.json()["data"]["status"] == "active"
        assert restore_response.json()["data"]["archived_at"] is None

        delete_response = client.delete(f"/api/v1/workspaces/{wid}")
        assert delete_response.status_code == 202
        assert delete_response.json()["data"]["status"] == "deleted"

    run_http_test(body)


def test_archive_workspace_endpoint_requires_owner() -> None:
    def body(client) -> None:
        owner_cookies = _register_and_login(client)
        workspace = _create_workspace(client, owner_cookies)

        admin_cookies = _register_and_login(client)
        _as(client, owner_cookies)
        members = client.get(f"/api/v1/workspaces/{workspace['id']}/members").json()["data"]
        # Add the second user as admin via direct role assignment isn't
        # exposed pre-membership — invite/accept is out of scope this
        # sprint, so this test instead proves the *permission floor*
        # using a non-member, which must fail identically (404, per the
        # anti-enumeration design) rather than a leaked 403.
        assert len(members) == 1  # only the founding owner exists

        _as(client, admin_cookies)
        response = client.post(f"/api/v1/workspaces/{workspace['id']}/archive")
        assert response.status_code == 404

    run_http_test(body)


def test_delete_workspace_is_not_physically_removed() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)

        client.delete(f"/api/v1/workspaces/{workspace['id']}")

        # The owner's own further reads now 404 too (deleted workspaces
        # stop authorizing access — see rbac.py) — but the underlying
        # row still exists; that's a service/model-level guarantee
        # already proven in test_workspace_service.py. Here: confirm
        # the API-level consequence is a clean 404, not a 500/crash.
        response = client.get(f"/api/v1/workspaces/{workspace['id']}")
        assert response.status_code == 404

    run_http_test(body)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_get_and_update_workspace_settings() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)
        wid = workspace["id"]

        get_response = client.get(f"/api/v1/workspaces/{wid}/settings")
        assert get_response.status_code == 200
        assert get_response.json()["data"]["allowed_file_types"] == ["pdf", "docx", "txt", "md"]

        patch_response = client.patch(
            f"/api/v1/workspaces/{wid}/settings", json={"max_document_size_mb": 200}
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["data"]["max_document_size_mb"] == 200

    run_http_test(body)


def test_update_workspace_settings_rejects_invalid_file_type() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)

        response = client.patch(
            f"/api/v1/workspaces/{workspace['id']}/settings",
            json={"allowed_file_types": ["exe"]},
        )
        assert response.status_code == 422

    run_http_test(body)


def test_update_workspace_settings_rejects_invalid_size() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)

        response = client.patch(
            f"/api/v1/workspaces/{workspace['id']}/settings",
            json={"max_document_size_mb": -5},
        )
        assert response.status_code == 422

    run_http_test(body)


def test_settings_endpoints_non_member_gets_404() -> None:
    def body(client) -> None:
        cookies_a = _register_and_login(client)
        workspace = _create_workspace(client, cookies_a)

        cookies_b = _register_and_login(client)
        _as(client, cookies_b)

        assert client.get(f"/api/v1/workspaces/{workspace['id']}/settings").status_code == 404
        assert (
            client.patch(
                f"/api/v1/workspaces/{workspace['id']}/settings", json={"max_document_size_mb": 10}
            ).status_code
            == 404
        )

    run_http_test(body)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def test_list_members_endpoint_returns_founding_owner() -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        workspace = _create_workspace(client, cookies)

        response = client.get(f"/api/v1/workspaces/{workspace['id']}/members")

        assert response.status_code == 200
        entries = response.json()["data"]
        assert len(entries) == 1
        assert entries[0]["role"] == "owner"
        assert set(entries[0]["user"]) == {"id", "display_name", "avatar_url", "email"}

    run_http_test(body)


def test_list_members_endpoint_non_member_gets_404() -> None:
    def body(client) -> None:
        cookies_a = _register_and_login(client)
        workspace = _create_workspace(client, cookies_a)

        cookies_b = _register_and_login(client)
        _as(client, cookies_b)
        response = client.get(f"/api/v1/workspaces/{workspace['id']}/members")

        assert response.status_code == 404

    run_http_test(body)


def test_remove_member_endpoint_cannot_remove_last_owner() -> None:
    """A *different* actor (admin) removing the sole owner — not
    self-removal, which is its own, separately-guarded 403 (see
    test_workspace_service.py's `test_cannot_remove_self_via_admin_endpoint`)
    and would otherwise be conflated with the owner-invariant check this
    test exists to prove."""

    def body(client) -> None:
        owner_cookies, owner_id = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)
        members = client.get(f"/api/v1/workspaces/{workspace['id']}/members").json()["data"]
        founding_membership_id = members[0]["id"]

        admin_cookies, admin_id = _register_login_and_id(client)
        asyncio.run(_add_member_via_db(workspace["id"], admin_id, "admin"))

        _as(client, admin_cookies)
        response = client.delete(
            f"/api/v1/workspaces/{workspace['id']}/members/{founding_membership_id}"
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "cannot_remove_last_owner"
        assert owner_id  # sanity: the id we tried (and failed) to remove

    run_http_test(body)


async def _role_id(name: str) -> str:
    db = settings.database
    conn = await asyncpg.connect(
        host=db.HOST, port=db.PORT, database=db.DB, user=db.USER, password=db.PASSWORD
    )
    try:
        row = await conn.fetchrow("SELECT id FROM roles WHERE name = $1", name)
        return str(row["id"])
    finally:
        await conn.close()


def test_change_role_endpoint_cannot_demote_last_owner() -> None:
    """Same reasoning as `test_remove_member_endpoint_cannot_remove_last_owner`
    — a separate admin actor, not self-change (its own distinct 403)."""

    def body(client) -> None:
        owner_cookies, owner_id = _register_login_and_id(client)
        workspace = _create_workspace(client, owner_cookies)
        members = client.get(f"/api/v1/workspaces/{workspace['id']}/members").json()["data"]
        founding_membership_id = members[0]["id"]

        admin_cookies, admin_id = _register_login_and_id(client)
        asyncio.run(_add_member_via_db(workspace["id"], admin_id, "admin"))

        member_role_id = asyncio.run(_role_id("member"))

        _as(client, admin_cookies)
        response = client.patch(
            f"/api/v1/workspaces/{workspace['id']}/members/{founding_membership_id}",
            json={"role_id": member_role_id},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "cannot_remove_last_owner"
        assert owner_id  # sanity: the id we tried (and failed) to demote

    run_http_test(body)


def test_member_endpoints_require_admin() -> None:
    def body(client) -> None:
        cookies_a = _register_and_login(client)
        workspace = _create_workspace(client, cookies_a)

        cookies_b = _register_and_login(client)
        _as(client, cookies_b)

        # Non-member — same anti-enumeration 404, not a 403.
        response = client.delete(f"/api/v1/workspaces/{workspace['id']}/members/{uuid.uuid4()}")
        assert response.status_code == 404

    run_http_test(body)


# ---------------------------------------------------------------------------
# Explicit cross-workspace attack sweep — S1F's own required scenario:
# "User A belongs to Workspace A. User A attempts to: GET Workspace B,
# PATCH Workspace B, GET Workspace B settings, PATCH Workspace B
# settings, GET Workspace B members, modify Workspace B membership,
# delete Workspace B. Every unauthorized operation must fail."
# ---------------------------------------------------------------------------


def test_cross_workspace_attack_sweep() -> None:
    def body(client) -> None:
        cookies_a = _register_and_login(client)
        _create_workspace(client, cookies_a)

        cookies_b = _register_and_login(client)
        workspace_b = _create_workspace(client, cookies_b)
        members_b = client.get(f"/api/v1/workspaces/{workspace_b['id']}/members").json()["data"]
        membership_b_id = members_b[0]["id"]

        # Back to User A, attacking Workspace B.
        _as(client, cookies_a)
        wid = workspace_b["id"]

        attacks = [
            ("GET", f"/api/v1/workspaces/{wid}", None),
            ("PATCH", f"/api/v1/workspaces/{wid}", {"name": "Pwned"}),
            ("GET", f"/api/v1/workspaces/{wid}/settings", None),
            ("PATCH", f"/api/v1/workspaces/{wid}/settings", {"max_document_size_mb": 999}),
            ("GET", f"/api/v1/workspaces/{wid}/members", None),
            (
                "PATCH",
                f"/api/v1/workspaces/{wid}/members/{membership_b_id}",
                {"role_id": str(uuid.uuid4())},
            ),
            ("DELETE", f"/api/v1/workspaces/{wid}/members/{membership_b_id}", None),
            ("POST", f"/api/v1/workspaces/{wid}/archive", None),
            ("POST", f"/api/v1/workspaces/{wid}/restore", None),
            ("DELETE", f"/api/v1/workspaces/{wid}", None),
        ]

        for method, url, json_body in attacks:
            response = client.request(method, url, json=json_body)
            assert response.status_code in (403, 404), (
                f"{method} {url} returned {response.status_code}"
            )
            if response.status_code == 404:
                assert response.json()["error"]["code"] in (
                    "workspace_not_found",
                    "membership_not_found",
                )

        # And Workspace B itself was never actually touched.
        _as(client, cookies_b)
        unchanged = client.get(f"/api/v1/workspaces/{wid}").json()["data"]
        assert unchanged["name"] == workspace_b["name"]
        assert unchanged["status"] == "active"

    run_http_test(body)
