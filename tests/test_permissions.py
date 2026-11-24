"""Tests for the permission matrix.

These are the tests worth having: the matrix is a specification, and a
specification that nobody checks drifts. Every assertion here corresponds to
a decision made on purpose, so a failing test means someone changed a policy,
not that someone broke a detail.

Run with:  docker compose exec app pytest tests/ -q
"""

import uuid

import pytest

from app.auth.permissions import (
    ROLE_PERMISSIONS,
    AccessContext,
    Permission,
    assignable_roles,
    role_can,
)
from app.models.enums import LogbookStatus, MembershipRole


def ctx(role: MembershipRole, state=LogbookStatus.ACTIVE) -> AccessContext:
    return AccessContext(
        user_id=uuid.uuid4(),
        logbook_id=uuid.uuid4(),
        role=role,
        logbook_status=state,
    )


# --- role hierarchy ---------------------------------------------------------


def test_roles_are_strictly_nested():
    """Each role must be a superset of the one below it.

    If this ever fails, someone granted a capability to editor but not owner,
    which always means a typo rather than a policy.
    """
    viewer = ROLE_PERMISSIONS[MembershipRole.VIEWER]
    commenter = ROLE_PERMISSIONS[MembershipRole.COMMENTER]
    editor = ROLE_PERMISSIONS[MembershipRole.EDITOR]
    owner = ROLE_PERMISSIONS[MembershipRole.OWNER]

    assert viewer < commenter < editor < owner


def test_every_permission_is_reachable():
    """No capability may be orphaned: if no role grants it, it is dead code
    pretending to be a feature."""
    granted = set().union(*ROLE_PERMISSIONS.values())
    orphans = set(Permission) - granted
    assert not orphans, f"Permisos que ningún rol otorga: {orphans}"


def test_owner_is_not_invitable():
    assert MembershipRole.OWNER not in assignable_roles()


# --- the decisions that matter ---------------------------------------------


def test_viewer_cannot_write_anything():
    a = ctx(MembershipRole.VIEWER)
    for p in (
        Permission.UPLOAD_DOCUMENT,
        Permission.CONFIRM_OBSERVATION,
        Permission.RECORD_HOME_READING,
        Permission.WRITE_JOURNAL,
        Permission.CREATE_COMMENT,
        Permission.CREATE_SHARE,
    ):
        assert not a.can(p)


def test_commenter_can_comment_but_not_change_data():
    a = ctx(MembershipRole.COMMENTER)
    assert a.can(Permission.CREATE_COMMENT)
    assert a.can(Permission.VIEW_DOCUMENT)
    assert not a.can(Permission.UPLOAD_DOCUMENT)
    assert not a.can(Permission.CONFIRM_OBSERVATION)
    assert not a.can(Permission.DELETE_ANY_COMMENT)


def test_confirming_a_transcription_requires_editor():
    """Promoting machine output to trusted data is the whole point of the
    review queue, so it is not something a reader can do."""
    assert not role_can(MembershipRole.COMMENTER, Permission.CONFIRM_OBSERVATION)
    assert role_can(MembershipRole.EDITOR, Permission.CONFIRM_OBSERVATION)


def test_only_owner_administers_membership():
    editor = ctx(MembershipRole.EDITOR)
    owner = ctx(MembershipRole.OWNER)
    for p in (
        Permission.INVITE_MEMBER,
        Permission.CHANGE_MEMBER_ROLE,
        Permission.REMOVE_MEMBER,
        Permission.TRANSFER_OWNERSHIP,
        Permission.DELETE_LOGBOOK,
        Permission.MANAGE_CONSENT,
    ):
        assert not editor.can(p)
        assert owner.can(p)


def test_editor_can_share():
    """Sharing is an everyday act, not an administrative one: the person who
    takes papá to the nephrologist has to be able to hand over the studies."""
    a = ctx(MembershipRole.EDITOR)
    assert a.can(Permission.CREATE_SHARE)
    assert a.can(Permission.REVOKE_SHARE)
    assert a.can(Permission.VIEW_SHARE_ACCESS_LOG)


# --- consent gate -----------------------------------------------------------


def test_revoked_consent_blocks_every_write_even_for_owner():
    a = ctx(MembershipRole.OWNER, LogbookStatus.CONSENT_REVOKED)
    for p in (
        Permission.UPLOAD_DOCUMENT,
        Permission.RECORD_HOME_READING,
        Permission.WRITE_JOURNAL,
        Permission.CONFIRM_OBSERVATION,
        Permission.POST_EPISODE_UPDATE,
        Permission.CREATE_COMMENT,
        Permission.INVITE_MEMBER,
    ):
        assert not a.can(p), f"{p} debería estar bloqueado sin consentimiento"


def test_revoked_consent_never_blocks_creating_a_share():
    a = ctx(MembershipRole.EDITOR, LogbookStatus.CONSENT_REVOKED)
    assert not a.can(Permission.CREATE_SHARE)


def test_revoked_consent_still_allows_read_and_export():
    """The subject's right of access survives revocation, and the owner needs
    the data out in order to delete the logbook."""
    a = ctx(MembershipRole.OWNER, LogbookStatus.CONSENT_REVOKED)
    assert a.can(Permission.VIEW_DOCUMENT)
    assert a.can(Permission.DOWNLOAD_DOCUMENT)
    assert a.can(Permission.EXPORT_LOGBOOK)
    assert a.can(Permission.DELETE_LOGBOOK)
    assert a.can(Permission.MANAGE_CONSENT)  # so it can be granted again
    assert a.can(Permission.REVOKE_SHARE)    # revoking is always allowed


def test_consent_gate_cannot_widen_a_role():
    """The gate only ever subtracts. A viewer does not gain anything when
    consent is revoked."""
    for state in LogbookStatus:
        for role in MembershipRole:
            assert ctx(role, state).granted() <= ROLE_PERMISSIONS[role]


def test_archived_logbook_is_read_only():
    a = ctx(MembershipRole.OWNER, LogbookStatus.ARCHIVED)
    assert a.can(Permission.VIEW_DOCUMENT)
    assert not a.can(Permission.UPLOAD_DOCUMENT)


@pytest.mark.parametrize("role", list(MembershipRole))
def test_denial_message_never_names_other_capabilities(role):
    a = ctx(role, LogbookStatus.CONSENT_REVOKED)
    msg = a.why_denied(Permission.UPLOAD_DOCUMENT)
    assert "upload" not in msg.lower()
    assert msg
