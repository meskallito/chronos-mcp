"""
Calendar operations for Chronos MCP
"""

import uuid
from typing import List, Optional

import caldav  # type: ignore[import-untyped,import-not-found]
from caldav import Calendar as CalDAVCalendar

from .accounts import AccountManager
from .exceptions import (
    AccountNotFoundError,
    CalendarCreationError,
    CalendarDeletionError,
    CalendarNotFoundError,
)
from .logging_config import setup_logging
from .models import Calendar

logger = setup_logging()


class CalendarManager:
    """Manage calendar operations"""

    def __init__(self, account_manager: AccountManager):
        self.accounts = account_manager

    def list_calendars(
        self, account_alias: Optional[str] = None, request_id: Optional[str] = None
    ) -> List[Calendar]:
        """List all calendars for an account - raises exceptions on failure"""
        request_id = request_id or str(uuid.uuid4())

        # De-masking note: the old `except Exception: return []` swallow around
        # `principal.calendars()` turned a cold iCloud timeout into a misleading
        # "0 calendars, no error". We now let connection/transient errors surface
        # (get_principal already raises AccountConnectionError on a connect
        # failure) so the tool layer returns a retryable error instead of an empty
        # list. A genuinely empty account still returns [].
        #
        # Stale-connection heal: `principal.calendars()` is the exact op that hangs
        # for iCloud after an idle gap. execute_with_reconnect evicts+reconnects+
        # retries it once on a dead-socket error (warm path = no reconnect).
        raw_calendars = self.accounts.execute_with_reconnect(
            lambda principal: principal.calendars(),
            account_alias=account_alias,
            request_id=request_id,
        )

        calendars = []
        for cal in raw_calendars:
            # Extract calendar properties
            cal_info = Calendar(
                uid=(
                    str(cal.url).split("/")[-2]
                    if str(cal.url).endswith("/")
                    else str(cal.url).split("/")[-1]
                ),
                name=cal.name or "Unnamed Calendar",
                description=None,  # Will need to fetch from properties
                color=None,  # Will need to fetch from properties
                account_alias=account_alias
                or self.accounts.config.config.default_account
                or "",
                url=str(cal.url),
                read_only=False,  # Will need to check permissions
            )
            calendars.append(cal_info)

        return calendars

    def create_calendar(
        self,
        name: str,
        description: Optional[str] = None,
        color: Optional[str] = None,
        account_alias: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Optional[Calendar]:
        """Create a new calendar - raises exceptions on failure"""
        request_id = request_id or str(uuid.uuid4())

        principal = self.accounts.get_principal(account_alias)
        if not principal:
            raise AccountNotFoundError(
                account_alias or self.accounts.config.config.default_account or "default",
                request_id=request_id,
            )

        try:
            cal_id = name.lower().replace(" ", "_")
            cal = principal.make_calendar(name=name, cal_id=cal_id)

            # Note: description and color properties would need CalDAV server support
            # for setting calendar properties beyond name

            return Calendar(
                uid=cal_id,
                name=name,
                description=description,
                color=color,
                account_alias=account_alias or self.accounts.config.config.default_account or "",
                url=str(cal.url),
                read_only=False,
            )

        except caldav.lib.error.AuthorizationError as e:
            logger.error(
                f"Authorization error creating calendar '{name}': {e}",
                extra={"request_id": request_id},
            )
            raise CalendarCreationError(name, "Authorization failed", request_id=request_id)
        except Exception as e:
            logger.error(
                f"Error creating calendar '{name}': {e}",
                extra={"request_id": request_id},
            )
            raise CalendarCreationError(name, str(e), request_id=request_id)

    def delete_calendar(
        self,
        calendar_uid: str,
        account_alias: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> bool:
        """Delete a calendar - raises exceptions on failure"""
        request_id = request_id or str(uuid.uuid4())

        principal = self.accounts.get_principal(account_alias)
        if not principal:
            raise AccountNotFoundError(
                account_alias or self.accounts.config.config.default_account or "default",
                request_id=request_id,
            )

        try:
            # Find calendar by UID
            for cal in principal.calendars():
                cal_id = (
                    str(cal.url).split("/")[-2]
                    if str(cal.url).endswith("/")
                    else str(cal.url).split("/")[-1]
                )
                if cal_id == calendar_uid:
                    cal.delete()
                    logger.info(
                        f"Deleted calendar '{calendar_uid}'",
                        extra={"request_id": request_id},
                    )
                    return True

            # Calendar not found
            raise CalendarNotFoundError(calendar_uid, account_alias, request_id=request_id)

        except CalendarNotFoundError:
            raise  # Re-raise our own exception
        except caldav.lib.error.AuthorizationError as e:
            logger.error(
                f"Authorization error deleting calendar '{calendar_uid}': {e}",
                extra={"request_id": request_id},
            )
            raise CalendarDeletionError(calendar_uid, "Authorization failed", request_id=request_id)
        except Exception as e:
            logger.error(
                f"Error deleting calendar '{calendar_uid}': {e}",
                extra={"request_id": request_id},
            )
            raise CalendarDeletionError(calendar_uid, str(e), request_id=request_id)

    @staticmethod
    def find_calendar_in_principal(
        principal, calendar_uid: str
    ) -> Optional[CalDAVCalendar]:
        """Resolve a CalDAV calendar object by UID from a given principal.

        Pure lookup (does the ``principal.calendars()`` round-trip). Exposed so
        callers in events/tasks/journals can resolve the calendar AND run their
        data op inside a single ``execute_with_reconnect`` closure — meaning a
        stale socket that surfaces on the data op (not just on the lookup) also
        heals against the freshly-reconnected principal. Returns ``None`` on a
        genuine no-uid-match.
        """
        for cal in principal.calendars():
            cal_id = (
                str(cal.url).split("/")[-2]
                if str(cal.url).endswith("/")
                else str(cal.url).split("/")[-1]
            )
            if cal_id == calendar_uid:
                return cal
        return None

    def get_calendar(
        self,
        calendar_uid: str,
        account_alias: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Optional[CalDAVCalendar]:
        """Get CalDAV calendar object by UID - internal utility method

        De-masking note: this method is intentionally NOT wrapped in
        ``ErrorHandler.safe_operation(default_return=None)`` and no longer swallows
        ``principal.calendars()`` failures to ``None``. A connection/cold-start
        timeout now propagates (as ``AccountConnectionError`` from
        ``get_principal``, or whatever ``principal.calendars()`` raises) so the
        caller does NOT mistake a transient outage for a missing calendar.

        ``None`` is returned ONLY for the genuine "iterated all calendars, no uid
        match" case (so callers in events/tasks/journals keep raising an accurate
        ``CalendarNotFoundError``). ``get_principal`` only returns ``None`` itself
        when no alias and no default account are configured.

        Stale-connection heal: the ``principal.calendars()`` lookup is the op that
        hangs for iCloud after an idle gap, so it runs through
        ``execute_with_reconnect`` (evict+reconnect+retry once on a dead-socket
        error; warm path does NOT reconnect). The returned CalDAV calendar object
        is bound to the now-fresh client, so the caller's subsequent data op uses
        a live socket.
        """
        try:
            return self.accounts.execute_with_reconnect(
                lambda principal: self.find_calendar_in_principal(principal, calendar_uid),
                account_alias=account_alias,
                request_id=request_id,
            )
        except AccountNotFoundError:
            # Distinguish the two AccountNotFoundError sources:
            #   1. Genuine "no alias AND no default account configured" — there is
            #      no account to resolve, so preserve the historic None contract
            #      (callers raise an accurate CalendarNotFoundError).
            #   2. An EXPLICITLY-named (or default) account that simply isn't in
            #      config — that is an honest config error and must surface, NOT
            #      be masked as a missing calendar. (This is the de-mask intent;
            #      AccountConnectionError already propagates untouched.)
            resolved_alias = account_alias or self.accounts.config.config.default_account
            if not resolved_alias:
                return None
            raise
