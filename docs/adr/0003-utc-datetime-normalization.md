# ADR-0003: UTC Normalization for CalDAV Datetime Storage

## Status
Accepted

## Context
Issue #17 reported that events created with non-UTC timezone offsets (e.g., `+02:00`) caused compatibility issues with CalDAV servers (notably Synology Calendar) that expect local timezone or TZID-formatted timestamps.

## Decision
Normalize all datetime values to UTC before writing to CalDAV servers. Datetimes with non-UTC timezone info are converted via `astimezone(timezone.utc)` before being passed to the icalendar library.

## Rationale
- UTC is the universal interchange format for iCalendar (RFC 5545)
- The icalendar library handles UTC datetimes correctly (appends `Z` suffix)
- Non-UTC offsets were being silently stripped by the icalendar library, causing data loss
- Converting to UTC preserves the correct instant in time while ensuring compatibility
- Most CalDAV servers handle UTC timestamps correctly

## Alternatives Considered
- **TZID support**: Would require account-level timezone configuration and more complex iCal generation. Rejected for v2.0 due to complexity.
- **Preserve original offset**: The icalendar library doesn't reliably preserve non-UTC offsets in serialization.

## Consequences
- All stored events use UTC timestamps
- Clients in non-UTC timezones must convert for display
- The response returns UTC-formatted timestamps regardless of input timezone
