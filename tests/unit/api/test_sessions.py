from __future__ import annotations

from bird_recognition.api.sessions import IDLE_SECONDS, SessionStore


def test_tokens_validate_and_are_stored_only_as_digests() -> None:
    store = SessionStore()

    token = store.create()

    assert store.validate(token)
    assert token not in store._sessions
    assert not store.validate("other")
    assert not store.validate(None)


def test_sessions_expire_after_twelve_idle_hours_and_activity_extends_them() -> None:
    now = [0.0]
    store = SessionStore(clock=lambda: now[0])
    token = store.create()

    now[0] = IDLE_SECONDS - 1
    assert store.validate(token)
    now[0] = 2 * IDLE_SECONDS - 2
    assert store.validate(token)
    now[0] = 3 * IDLE_SECONDS
    assert not store.validate(token)


def test_revoke_and_clear_invalidate_tokens() -> None:
    store = SessionStore()
    first, second = store.create(), store.create()

    store.revoke(first)
    assert not store.validate(first)
    assert store.validate(second)
    store.clear()
    assert not store.validate(second)
    store.revoke("unknown")
