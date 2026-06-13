"""
Unit tests for the reactive stale-connection heal.

Background: iCloud (caldav.icloud.com) silently drops idle keep-alive sockets
after ~15-20 s. The python caldav/requests stack does NOT detect the dead socket;
the next CalDAV op hangs for the full read-timeout and never self-recovers without
a reconnect. ``AccountManager.execute_with_reconnect`` heals this: on a
dead-socket error it evicts the cached client, reconnects once, and retries the
operation against the fresh principal.

These tests use mocks only (no network).
"""

import types
from unittest.mock import Mock, patch

import pytest

from chronos_mcp.accounts import AccountManager, _is_stale_connection_error
from chronos_mcp.calendars import CalendarManager
from chronos_mcp.events import EventManager
from chronos_mcp.exceptions import AccountConnectionError, AccountNotFoundError
from chronos_mcp.models import Account

# ---------------------------------------------------------------------------
# Synthetic HTTP-backend exceptions (NO `import requests`).
#
# The fork's prod image runs caldav>=3 on **niquests** (NOT requests); a hard
# `import requests` here would (a) be an undeclared test dependency that only
# passes by transitive luck, and (b) — worse — exercise the requests-class path
# while the prod-critical classification is the backend-AGNOSTIC name heuristic
# in `_is_stale_connection_error` (module name ends in "exceptions" + the class
# name mentions Timeout/ConnectionError), the ONLY thing that classifies a
# niquests error when niquests can't be imported. A hard `import requests`
# crash-looped the first prod deploy precisely because prod lacked requests.
#
# So we synthesize backend-shaped exceptions from scratch in a module named
# "<backend>.exceptions" with Timeout/ConnectionError-shaped names. These do NOT
# inherit from builtin ConnectionError/socket.timeout, so they can ONLY match via
# the name heuristic — exactly the prod path. We also keep builtin-based cases for
# the class-match branch.
# ---------------------------------------------------------------------------
_niquests_exc_mod = types.ModuleType("niquests.exceptions")


def _make_backend_exc(class_name: str) -> type:
    """A niquests-shaped exception: lives in a '*.exceptions' module, the given
    name (e.g. 'ReadTimeout'), and does NOT subclass any builtin socket error —
    so it is classifiable ONLY by the backend-agnostic name heuristic."""
    cls = type(class_name, (Exception,), {})
    cls.__module__ = "niquests.exceptions"
    setattr(_niquests_exc_mod, class_name, cls)
    return cls


# niquests-shaped classes (heuristic-only path — the prod classification).
NiquestsReadTimeout = _make_backend_exc("ReadTimeout")
NiquestsConnectionError = _make_backend_exc("ConnectionError")
NiquestsChunkedEncodingError = _make_backend_exc("ChunkedEncodingError")


def _stale_exc(msg: str = "read timed out") -> Exception:
    """A representative dead-socket error as it surfaces in prod (niquests-shaped)."""
    return NiquestsReadTimeout(msg)


@pytest.fixture
def icloud_account():
    return Account(
        alias="icloud",
        url="https://caldav.icloud.com",
        username="user@icloud.com",
        password="app-specific-pw",
        display_name="iCloud",
    )


@pytest.fixture
def radicale_account():
    return Account(
        alias="default",
        url="http://radicale:5232",
        username="local",
        password="local",
        display_name="Radicale",
    )


class TestStaleErrorClassifier:
    # --- class-match branch (builtins; always present, no backend needed) ---
    def test_builtin_connection_error_is_stale(self):
        # builtin ConnectionError (and subclasses BrokenPipe/ConnectionReset) is in
        # _STALE_TYPES — the real dead-socket case.
        assert _is_stale_connection_error(ConnectionResetError("connection reset by peer"))

    def test_socket_timeout_is_stale(self):
        import socket

        assert _is_stale_connection_error(socket.timeout("timed out"))

    # --- name-heuristic branch (the PROD path: niquests, not importable here) ---
    def test_niquests_read_timeout_is_stale_via_name_heuristic(self):
        # The prod-critical path: a niquests Timeout error (caldav>=3 backend) that
        # does NOT subclass any builtin socket error is still classified stale by the
        # module(".exceptions")+name heuristic. This is the branch that exists because
        # a hard `import requests` crash-looped the first deploy; it must stay covered.
        exc = NiquestsReadTimeout("read timed out")
        assert not isinstance(exc, (ConnectionError,))  # proves it's heuristic-only
        assert _is_stale_connection_error(exc)

    def test_niquests_connection_error_is_stale_via_name_heuristic(self):
        assert _is_stale_connection_error(NiquestsConnectionError("conn reset"))

    def test_niquests_chunked_encoding_error_is_stale_via_name_heuristic(self):
        assert _is_stale_connection_error(NiquestsChunkedEncodingError("incomplete read"))

    def test_wrapped_in_cause_chain_is_stale(self):
        # caldav wraps the transport error inside its own DAVError; walk the chain.
        inner = NiquestsReadTimeout("read timed out")
        outer = RuntimeError("caldav wrapper")
        outer.__cause__ = inner
        assert _is_stale_connection_error(outer)

    # --- negatives: real errors must NOT be misclassified as stale ---
    def test_value_error_is_not_stale(self):
        assert not _is_stale_connection_error(ValueError("not found"))

    def test_auth_error_is_not_stale(self):
        # Auth/HTTP-status problems are real, must NOT trigger a reconnect+retry.
        assert not _is_stale_connection_error(PermissionError("403"))

    def test_niquests_auth_error_is_not_misclassified(self):
        # A niquests/caldav auth-shaped error (no Timeout/ConnectionError in the name)
        # must NOT be classified as a stale socket — else a real 401/403 would trigger
        # an endless evict+reconnect+retry instead of surfacing honestly.
        auth_exc = type("AuthorizationError", (Exception,), {})
        auth_exc.__module__ = "niquests.exceptions"
        assert not _is_stale_connection_error(auth_exc("401 Unauthorized"))


class TestExecuteWithReconnect:
    def _make_mgr(self, mock_config_manager, account):
        mock_config_manager.add_account(account)
        return AccountManager(mock_config_manager)

    @patch("chronos_mcp.accounts.DAVClient")
    def test_warm_path_does_not_reconnect(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        """No error -> operation runs once, no evict/reconnect (no perf regression)."""
        mgr = self._make_mgr(mock_config_manager, icloud_account)
        client = Mock()
        principal = Mock()
        client.principal.return_value = principal
        mock_dav_client.return_value = client

        # Warm the cache (one connect).
        mgr.connect_account("icloud")
        assert mock_dav_client.call_count == 1

        op = Mock(return_value=["cal-a", "cal-b"])
        result = mgr.execute_with_reconnect(op, account_alias="icloud")

        assert result == ["cal-a", "cal-b"]
        op.assert_called_once_with(principal)
        # No second DAVClient construction => no reconnect.
        assert mock_dav_client.call_count == 1

    @patch("chronos_mcp.accounts.DAVClient")
    def test_stale_then_success_evicts_reconnects_retries(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        """Stale-socket error ONCE -> evict + reconnect + retry -> returns result."""
        mgr = self._make_mgr(mock_config_manager, icloud_account)

        # Two distinct clients/principals so we can prove a fresh one was built.
        stale_client, stale_principal = Mock(name="stale_client"), Mock(name="stale_principal")
        fresh_client, fresh_principal = Mock(name="fresh_client"), Mock(name="fresh_principal")
        stale_client.principal.return_value = stale_principal
        fresh_client.principal.return_value = fresh_principal
        mock_dav_client.side_effect = [stale_client, fresh_client]

        mgr.connect_account("icloud")  # warm with stale_client
        assert mgr.principals["icloud"] is stale_principal

        # Operation fails on the stale principal, succeeds on the fresh one.
        def op(principal):
            if principal is stale_principal:
                raise _stale_exc("HTTPSConnectionPool: read timed out")
            return ["fresh-result"]

        result = mgr.execute_with_reconnect(op, account_alias="icloud")

        assert result == ["fresh-result"]
        # A second DAVClient was constructed (the reconnect).
        assert mock_dav_client.call_count == 2
        # Cache now holds the fresh principal (evict happened).
        assert mgr.principals["icloud"] is fresh_principal

    @patch("chronos_mcp.accounts.DAVClient")
    def test_persistent_failure_surfaces_honest_error_bounded(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        """Stale error EVERY time -> honest AccountConnectionError, bounded retry."""
        mgr = self._make_mgr(mock_config_manager, icloud_account)
        client = Mock()
        client.principal.return_value = Mock()
        mock_dav_client.return_value = client
        mgr.connect_account("icloud")

        call_count = {"n": 0}

        def op(principal):
            call_count["n"] += 1
            raise NiquestsConnectionError("connection reset by peer")

        # The reconnect itself succeeds, but the retried op fails again -> the
        # operation's own error propagates (NOT masked None/[]). Bounded: op runs
        # at most twice (initial + one retry).
        with pytest.raises(NiquestsConnectionError):
            mgr.execute_with_reconnect(op, account_alias="icloud")
        assert call_count["n"] == 2  # initial + exactly one retry (no infinite loop)

    @patch("chronos_mcp.accounts.DAVClient")
    def test_reconnect_failure_surfaces_account_connection_error(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        """If the reconnect can't establish a connection -> AccountConnectionError."""
        mgr = self._make_mgr(mock_config_manager, icloud_account)
        good_client = Mock()
        good_client.principal.return_value = Mock()
        # First construct succeeds (warm), reconnect attempts all fail.
        mock_dav_client.side_effect = [
            good_client,
            NiquestsConnectionError("down"),
            NiquestsConnectionError("down"),
            NiquestsConnectionError("down"),
        ]
        mgr.connect_account("icloud")
        mgr._base_retry_delay = 0  # don't sleep in test

        def op(principal):
            raise _stale_exc("read timed out")

        with pytest.raises(AccountConnectionError):
            mgr.execute_with_reconnect(op, account_alias="icloud")

    def test_no_alias_no_default_raises_not_found(self, mock_config_manager):
        """Genuine 'no alias, no default' -> AccountNotFoundError (not a masked None)."""
        mgr = AccountManager(mock_config_manager)
        with pytest.raises(AccountNotFoundError):
            mgr.execute_with_reconnect(lambda p: p, account_alias=None)

    @patch("chronos_mcp.accounts.DAVClient")
    def test_non_stale_error_not_retried(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        """A non-connection error (e.g. ValueError) must NOT trigger a reconnect."""
        mgr = self._make_mgr(mock_config_manager, icloud_account)
        client = Mock()
        client.principal.return_value = Mock()
        mock_dav_client.return_value = client
        mgr.connect_account("icloud")

        def op(principal):
            raise ValueError("genuine no match")

        with pytest.raises(ValueError):
            mgr.execute_with_reconnect(op, account_alias="icloud")
        # Only the warm connect, no reconnect.
        assert mock_dav_client.call_count == 1


class TestProactiveIdleReconnect:
    """The primary iCloud fix: proactively reconnect after an idle gap so a dead
    socket never gets hit (which would hang for the full read timeout)."""

    @patch("chronos_mcp.accounts.DAVClient")
    def test_idle_beyond_threshold_reconnects_before_op(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        mock_config_manager.add_account(icloud_account)
        mgr = AccountManager(mock_config_manager)
        mgr._idle_reconnect_seconds = 10.0

        client1, principal1 = Mock(), Mock(name="p1")
        client2, principal2 = Mock(), Mock(name="p2")
        client1.principal.return_value = principal1
        client2.principal.return_value = principal2
        mock_dav_client.side_effect = [client1, client2]

        mgr.connect_account("icloud")  # warm
        # Simulate the connection having been idle for 30s.
        mgr._last_activity["icloud"] = mgr._last_activity["icloud"] - 30

        op = Mock(return_value=["ok"])
        result = mgr.execute_with_reconnect(op, account_alias="icloud")

        assert result == ["ok"]
        # Reconnected proactively (fresh client built) and ran op on the fresh principal.
        assert mock_dav_client.call_count == 2
        op.assert_called_once_with(principal2)

    @patch("chronos_mcp.accounts.DAVClient")
    def test_proactive_idle_reconnect_is_serialized_under_the_per_alias_lock(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        """Regression guard: the idle check + reconnect AND the last-activity stamp run
        under self._connection_locks[alias] — the same lock _force_reconnect/get_principal
        use — so two concurrent requests can't both fire a redundant reconnect, and a
        disconnect can't interleave between the check and the reconnect. We assert the
        proactive path holds the lock for the reconnect (the lock-free core
        _force_reconnect_locked is invoked WHILE the lock is held)."""
        mock_config_manager.add_account(icloud_account)
        mgr = AccountManager(mock_config_manager)
        mgr._idle_reconnect_seconds = 10.0

        client1, client2 = Mock(), Mock()
        client1.principal.return_value = Mock(name="p1")
        client2.principal.return_value = Mock(name="p2")
        mock_dav_client.side_effect = [client1, client2]
        mgr.connect_account("icloud")
        mgr._last_activity["icloud"] = mgr._last_activity["icloud"] - 30  # idle

        lock = mgr._lock_for("icloud")
        held_during_reconnect = {"v": False}
        real_core = mgr._force_reconnect_locked

        def spy(alias, request_id=None):
            held_during_reconnect["v"] = lock.locked()
            return real_core(alias, request_id=request_id)

        with patch.object(mgr, "_force_reconnect_locked", side_effect=spy):
            mgr.execute_with_reconnect(Mock(return_value=["ok"]), account_alias="icloud")

        assert held_during_reconnect["v"], "proactive reconnect must run holding the per-alias lock"

    @patch("chronos_mcp.accounts.DAVClient")
    def test_recent_activity_does_not_reconnect(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        mock_config_manager.add_account(icloud_account)
        mgr = AccountManager(mock_config_manager)
        mgr._idle_reconnect_seconds = 10.0

        client, principal = Mock(), Mock()
        client.principal.return_value = principal
        mock_dav_client.return_value = client

        mgr.connect_account("icloud")  # last_activity = now (recent)
        op = Mock(return_value=["ok"])
        mgr.execute_with_reconnect(op, account_alias="icloud")

        # Within the idle window -> no proactive reconnect.
        assert mock_dav_client.call_count == 1
        op.assert_called_once_with(principal)

    @patch("chronos_mcp.accounts.DAVClient")
    def test_idle_guard_disabled_when_zero(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        mock_config_manager.add_account(icloud_account)
        mgr = AccountManager(mock_config_manager)
        mgr._idle_reconnect_seconds = 0  # disabled

        client, principal = Mock(), Mock()
        client.principal.return_value = principal
        mock_dav_client.return_value = client

        mgr.connect_account("icloud")
        mgr._last_activity["icloud"] = mgr._last_activity["icloud"] - 999
        op = Mock(return_value=["ok"])
        mgr.execute_with_reconnect(op, account_alias="icloud")
        # Disabled -> no proactive reconnect even though idle.
        assert mock_dav_client.call_count == 1


class TestManagerIntegration:
    @patch("chronos_mcp.accounts.DAVClient")
    def test_get_events_range_heals_stale_date_search(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        """get_events_range: stale socket on date_search -> reconnect -> events."""
        from datetime import datetime, timezone

        mock_config_manager.add_account(icloud_account)
        accounts = AccountManager(mock_config_manager)

        # Build a calendar whose url ends in the target uid.
        def make_calendar(stale: bool):
            cal = Mock()
            cal.url = "https://caldav.icloud.com/123/calendars/fam-uid/"
            if stale:
                cal.date_search.side_effect = _stale_exc("read timed out")
            else:
                event = Mock()
                event.data = (
                    "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:e1\nSUMMARY:Real Event\n"
                    "DTSTART:20260615T100000Z\nDTEND:20260615T110000Z\n"
                    "END:VEVENT\nEND:VCALENDAR"
                )
                cal.date_search.return_value = [event]
            return cal

        stale_principal = Mock(name="stale_principal")
        stale_principal.calendars.return_value = [make_calendar(stale=True)]
        fresh_principal = Mock(name="fresh_principal")
        fresh_principal.calendars.return_value = [make_calendar(stale=False)]

        stale_client = Mock()
        stale_client.principal.return_value = stale_principal
        fresh_client = Mock()
        fresh_client.principal.return_value = fresh_principal
        mock_dav_client.side_effect = [stale_client, fresh_client]

        accounts.connect_account("icloud")  # warm with stale

        cal_mgr = CalendarManager(accounts)
        evt_mgr = EventManager(cal_mgr)

        events = evt_mgr.get_events_range(
            "fam-uid",
            datetime(2026, 6, 1, tzinfo=timezone.utc),
            datetime(2026, 6, 30, tzinfo=timezone.utc),
            account_alias="icloud",
        )

        assert len(events) == 1
        assert events[0].summary == "Real Event"
        # Reconnect happened: a fresh DAVClient was built.
        assert mock_dav_client.call_count == 2

    @patch("chronos_mcp.accounts.DAVClient")
    def test_list_calendars_heals_stale_lookup(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        """list_calendars: stale socket on principal.calendars() -> reconnect."""
        mock_config_manager.add_account(icloud_account)
        accounts = AccountManager(mock_config_manager)

        stale_principal = Mock()
        stale_principal.calendars.side_effect = _stale_exc("timed out")
        fresh_cal = Mock()
        fresh_cal.url = "https://caldav.icloud.com/123/calendars/work/"
        fresh_cal.name = "Work"
        fresh_principal = Mock()
        fresh_principal.calendars.return_value = [fresh_cal]

        stale_client = Mock()
        stale_client.principal.return_value = stale_principal
        fresh_client = Mock()
        fresh_client.principal.return_value = fresh_principal
        mock_dav_client.side_effect = [stale_client, fresh_client]

        accounts.connect_account("icloud")
        cal_mgr = CalendarManager(accounts)

        calendars = cal_mgr.list_calendars(account_alias="icloud")
        assert len(calendars) == 1
        assert calendars[0].name == "Work"
        assert mock_dav_client.call_count == 2

    @patch("chronos_mcp.accounts.DAVClient")
    def test_get_calendar_surfaces_missing_explicit_account(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        """get_calendar de-mask: an EXPLICITLY-named account that isn't in config must
        surface AccountNotFoundError, NOT be swallowed to None (which the caller would
        mistranslate into a missing-calendar error)."""
        mock_config_manager.add_account(icloud_account)
        accounts = AccountManager(mock_config_manager)
        cal_mgr = CalendarManager(accounts)

        # "nope" is not a configured account -> connect_account raises
        # AccountNotFoundError -> must propagate, not return None.
        with pytest.raises(AccountNotFoundError):
            cal_mgr.get_calendar("any-uid", account_alias="nope")

    def test_get_calendar_no_alias_no_default_returns_none(self, mock_config_manager):
        """get_calendar: the genuine 'no alias AND no default account' case keeps the
        historic None contract (so the caller raises an accurate CalendarNotFoundError)."""
        accounts = AccountManager(mock_config_manager)  # no accounts, no default
        cal_mgr = CalendarManager(accounts)
        assert cal_mgr.get_calendar("any-uid", account_alias=None) is None

    @patch("chronos_mcp.accounts.DAVClient")
    def test_record_activity_identity_guard_does_not_stamp_replaced_principal(
        self, mock_dav_client, mock_config_manager, icloud_account
    ):
        """A slow op finishing AFTER a concurrent reconnect must NOT stamp the
        REPLACEMENT connection as freshly-used (which would suppress the next
        proactive idle reconnect)."""
        mock_config_manager.add_account(icloud_account)
        mgr = AccountManager(mock_config_manager)

        old_client, old_principal = Mock(), Mock(name="old_principal")
        new_client, new_principal = Mock(), Mock(name="new_principal")
        old_client.principal.return_value = old_principal
        new_client.principal.return_value = new_principal
        mock_dav_client.side_effect = [old_client, new_client]

        mgr.connect_account("icloud")  # caches old_principal, seeds activity
        # Simulate a concurrent reconnect replacing the cached principal.
        mgr.connect_account("icloud")
        assert mgr.principals["icloud"] is new_principal
        new_stamp = mgr._last_activity["icloud"]

        # An old/slow op finishing against old_principal must NOT overwrite the
        # fresher stamp belonging to new_principal.
        mgr._last_activity["icloud"] = new_stamp - 100  # pretend it went idle
        before = mgr._last_activity["icloud"]
        mgr._record_activity("icloud", old_principal)
        assert mgr._last_activity["icloud"] == before  # unchanged (identity mismatch)

        # Stamping for the CURRENT cached principal still works.
        mgr._record_activity("icloud", new_principal)
        assert mgr._last_activity["icloud"] > before

    @patch("chronos_mcp.accounts.DAVClient")
    def test_radicale_warm_path_unaffected(
        self, mock_dav_client, mock_config_manager, radicale_account
    ):
        """Radicale (local 'default') warm read does NOT reconnect — no regression."""
        mock_config_manager.add_account(radicale_account)
        accounts = AccountManager(mock_config_manager)

        cal = Mock()
        cal.url = "http://radicale:5232/local/reminders/"
        cal.name = "Reminders"
        principal = Mock()
        principal.calendars.return_value = [cal]
        client = Mock()
        client.principal.return_value = principal
        mock_dav_client.return_value = client

        accounts.connect_account("default")
        cal_mgr = CalendarManager(accounts)

        calendars = cal_mgr.list_calendars(account_alias="default")
        assert len(calendars) == 1
        assert calendars[0].name == "Reminders"
        # No reconnect — Radicale keep-alive is untouched.
        assert mock_dav_client.call_count == 1
