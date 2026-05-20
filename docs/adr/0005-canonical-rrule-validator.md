# ADR-0005: Canonical RRULE Validator

## Status
Accepted

## Context
Chronos MCP had three separate RRULE validation implementations across the codebase:
- `RRuleValidator.validate_rrule()` in `rrule.py` (canonical, using dateutil.rrule.rrulestr)
- `utils.validate_rrule()` in `utils.py` (manual parsing, 78 lines)
- `InputValidator.validate_rrule()` in `validation.py` (basic format check)

This triple implementation created maintenance burden and inconsistent validation behavior. Changes to RRULE validation logic had to be replicated across three locations, increasing the risk of bugs and regressions.

## Decision
Designate `RRuleValidator.validate_rrule()` in `rrule.py` as the single canonical validator. Convert other implementations to thin wrappers that delegate to the canonical validator.

## Implementation
- **utils.validate_rrule()**: Replace entire function body with delegation to `RRuleValidator.validate_rrule()`. Preserve the `(True, None)` return for empty input (behavioral difference from RRuleValidator which rejects empty).
- **InputValidator.validate_rrule()**: Keep the security sanitizer role (strip, uppercase, length check). Continue basic format validation (FREQ check) but do NOT enforce COUNT/UNTIL requirement (that's business logic layer validation). This preserves backward compatibility with existing tests.

## Rationale
- **Single Source of Truth**: RRuleValidator uses dateutil.rrule.rrulestr for RFC 5545 compliance
- **Layered Validation**: InputValidator does security sanitization, RRuleValidator does structural validation, business logic layer enforces safety constraints (COUNT/UNTIL)
- **Backward Compatibility**: utils.validate_rrule() preserves empty-input behavior; InputValidator.validate_rrule() accepts RRULEs without COUNT/UNTIL (basic format only)
- **Reduced Code**: utils.py reduced from 78 lines to ~10 lines
- **Consistency**: All RRULE validation now uses the same underlying logic

## Consequences
- RRuleValidator is now the authoritative RRULE validation implementation
- Future RRULE validation changes only need to be made in one place
- InputValidator.validate_rrule() and utils.validate_rrule() are now thin wrappers
- 102 RRULE-related tests continue to pass with zero regressions
