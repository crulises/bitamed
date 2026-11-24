"""Logbook and invitation endpoints.

Stub: no routes defined yet. Exists so app.main can import
`router` and `invitations_router` while the real endpoints are built out.
"""

from fastapi import APIRouter

router = APIRouter(tags=["logbooks"])
invitations_router = APIRouter(tags=["invitations"])
