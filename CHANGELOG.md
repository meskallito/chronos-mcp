# Changelog

All notable changes to Chronos MCP will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.1.0] - 2026-05-19

### Fixed
- Timezone normalization for journal entries (same bug class as #17)
- All-day events now use VALUE=DATE instead of DATE-TIME (#13)
- Broken documentation links in README (#24)
- list_tasks now returns completed tasks (#14)
- Version mismatch: __init__.py updated from 0.1.2 to match pyproject.toml
- CONTRIBUTING.md GitHub org, email, and Discord links corrected
- ARCHITECTURE.md Python version corrected (3.9+ -> 3.10+)
- SECURITY.md version references updated from 0.2.0 to 2.0.0
- VTODO guide bulk operation examples corrected to use actual parameter names

### Changed
- CI: removed broken references to deleted test_imports.py and tests/integration/
- CI: removed hardcoded black --target-version from ci.yml lint job
- CI: removed integration test job and radicale dependencies
- Relocated DEPENDENCY_INJECTION_ARCHITECTURE.md to docs/adr/0004
- Relocated DEPENDENCY_UPDATE_REPORT.md to docs/
- Added CI status badge to README
- Added full API reference for task/journal tools in README
- Added [secure] optional dependency to pyproject.toml
- Removed language_version pin from pre-commit black hook

### Removed
- Vaporware "coming soon" feature promises from README (Import/Export, Sync)
- Stale test_imports.py negation rules from .gitignore
- test-integration Makefile target (directory deleted)
- Discord notification stubs from CI workflows

## [2.0.0] - 2025-07-24

### Added
- **Full VTODO (Tasks) Support**
  - Complete task management with create, update, delete, and list operations
  - Task priorities (1-9 scale, with 1 being highest)
  - Task status tracking (NEEDS-ACTION, IN-PROCESS, COMPLETED, CANCELLED)
  - Progress tracking with percentage completion (0-100%)
  - Due date management
  - Subtask relationships using related_to field
  - Bulk task operations with atomic transaction support
- **Full VJOURNAL (Journal Entries) Support**
  - Journal entry creation with timestamps and rich descriptions
  - Update and delete functionality for existing entries
  - Category support for organization
  - Related entry linking using related_to field
  - Bulk journal operations with efficient batch processing
- **Enhanced Bulk Operations**
  - Extended bulk operations to support tasks and journals
  - Atomic mode with automatic rollback on failure
  - Parallel execution with configurable concurrency
  - Dry-run mode for all bulk operations
  - Detailed operation results with timing metrics
- **Improved Search Functionality**
  - Extended search to include tasks and journal entries
  - Enhanced search algorithms for better performance
  - Support for searching across all component types
- **Enhanced Validation**
  - Comprehensive validation for all integer parameters
  - Improved date handling across all components
  - Better error messages with clear remediation steps
- **Documentation**
  - Comprehensive VTODO/VJOURNAL implementation guide
  - Updated API documentation with new endpoints
  - Examples for all new functionality

### Changed
- Major version bump to 2.0.0 due to significant new features
- Enhanced models to support new component types
- Improved server architecture to handle multiple component types
- Better separation of concerns across modules

### Fixed
- Integer parameter validation across all endpoints
- Date parsing edge cases for all-day events
- Bulk operation error handling improvements

### Security
- Enhanced input validation for new component types
- Improved sanitization for journal entry content
- Better protection against malformed iCalendar data

## [1.0.0-rc1] - 2025-07-05

### Added
- **Advanced Event Search** (Phase 4)
  - Full-text search across event fields (summary, description, location)
  - Multiple search types: contains, starts_with, ends_with, exact, regex
  - Case-sensitive and case-insensitive search options
  - Date range filtering combined with text search
  - Relevance ranking algorithm with field weights and recency boost
  - Performance optimized: <100ms for 1K events, <1s for 10K events
- **Bulk Operations** (Phase 4)
  - Bulk event creation with parallel execution (5x speedup)
  - Bulk event deletion with efficient batch processing
  - Three operation modes: atomic (all-or-nothing), continue-on-error, fail-fast
  - Detailed operation results with per-event status and timing
  - Dry-run mode for testing without execution
- **Enhanced Input Validation** (Phase 4)
  - Comprehensive security hardening against XSS, injection, and path traversal
  - Field-specific validation with length limits
  - RFC-compliant UID and email validation
  - Unicode normalization to prevent homograph attacks
  - HTML escaping for all text fields
  - Dangerous pattern detection and blocking
- Full RRULE (recurring events) support with comprehensive validation
- New `validate_rrule()` utility function for RFC 5545 compliance
- Support for DAILY, WEEKLY, MONTHLY, and YEARLY recurrence patterns
- RRULE validation with clear error messages
- Extraction of RRULE from parsed CalDAV events
- Comprehensive test suite for RRULE functionality (13 tests)
- Detailed RRULE documentation with examples
- Event update functionality with `update_event()` method
- Partial event updates (only specified fields are changed)
- Support for removing optional fields by passing empty strings
- 5 new tests for event update functionality

### Changed
- SearchOptions now uses field default factory for better initialization
- Improved error messages for validation failures
- Enhanced test coverage to 82%+ (excluding server.py)

### Fixed
- Duplicate account alias now raises `AccountAlreadyExistsError` instead of silently overwriting
- Fixed syntax errors in events.py related to recurrence_rule parameter
- Fixed import naming conflicts in search functionality

### Security
- Fixed potential data loss vulnerability where duplicate account aliases would overwrite existing accounts
- Added comprehensive input validation to prevent injection attacks
- Implemented path traversal protection for UIDs
- Added XSS prevention through HTML escaping
- Enhanced email and URL validation

## [0.1.2] - 2025-07-04

### Fixed
- delete_event now uses event_by_uid method with fallback to event filtering
- alarm_minutes parameter changed to string type to fix validation errors
- attendees parameter renamed to attendees_json and accepts JSON string

### Changed
- Improved error handling in delete_event with fallback methods
- Better logging for parameter parsing errors

## [0.1.1] - 2025-07-04

### Added
- Multi-account support with JSON configuration
- Account management tools (add, list, remove, test)
- Calendar operations (list, create, delete)
- Event creation with full metadata support
- Event deletion tool (implementation needs refinement)
- Date range event queries
- Environment variable support for backward compatibility
- Comprehensive error handling and logging
- Support for recurrence rules (RRULE) in create_event
- Support for attendees in create_event (validation issues pending)

### Fixed
- Stdout/stderr separation for MCP protocol compliance
- FastMCP 2.0 compatibility
- Python 3.13 compatibility (datetime.utcnow deprecation)
- Centralized logging configuration
- Added missing delete_calendar tool (working)
- Added missing delete_event tool (implementation issues)
- Added missing recurrence_rule and attendees parameters to create_event

### Known Issues
- Calendar properties (color, description) not persisted
- All-day event flag not properly set
- alarm_minutes parameter validation error (FastMCP type handling)
- attendees parameter validation error (FastMCP type handling)
- delete_event returns failure (CalDAV search method issues)

## [0.1.0] - 2025-07-04

### Added
- Initial release
- Basic CalDAV connectivity
- Core project structure
- FastMCP integration
- Pydantic models for type safety
