# ADR-0002: Rate Limiting Postponed

## Status
Superseded (feature branch closed)

## Context
PR #5 implemented comprehensive token-bucket rate limiting with 28 files changed. After 8 months without merge, the branch accumulated conflicts with main, CI failures in lint and security scans, and diverged significantly from the current codebase.

## Decision
Close PR #5 and postpone rate limiting. If needed, re-implement from the current main branch.

## Rationale
- Branch was 8 months stale with merge conflicts
- CI failures in lint and security scan
- Rate limiting is a cross-cutting concern that touches every tool definition
- The 28-file scope makes conflict resolution risky
- Rate limiting is disabled by default in the PR; no users were depending on it

## Consequences
- No rate limiting in the current codebase
- Future rate limiting implementation should be smaller in scope
- Consider middleware-based approach rather than per-tool decorators
