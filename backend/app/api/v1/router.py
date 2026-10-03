"""API v1 router.

Aggregates every v1 endpoint module. `health` (M0.2D), `auth`
(Sprint 1B–S1E), `workspaces` (S1F, extended by S1G with workspace-
scoped invitation management), and `invitations` (S1G's own top-level
public/self routes) exist so far — the REST API Contract's remaining
resource routers (documents, chat, ...) are added here module-by-module
in later sprints, each as its own `app.api.v1.endpoints.<resource>`
import, exactly like these.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, invitations, workspaces, documents, chat

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(invitations.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
