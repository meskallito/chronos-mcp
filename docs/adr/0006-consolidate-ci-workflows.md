# ADR-0006: Consolidate CI Workflows

## Status
Accepted

## Context
Chronos MCP had two separate GitHub Actions workflow files:
- `.github/workflows/ci.yml` (main CI/CD pipeline: lint, test, security, build, notify jobs)
- `.github/workflows/test.yml` (duplicate test job with additional checks: ruff, radon, coverage threshold)

This duplication wasted CI minutes and made it unclear which workflow was the source of truth. The test.yml file also referenced deleted files (test_imports.py, tests/integration/) which were broken references.

## Decision
Merge unique checks from test.yml into ci.yml and delete test.yml. Consolidate all CI validation into a single workflow.

## Implementation
- **ci.yml lint job**: Replace isort + flake8 with `ruff check`. Add `radon cc` complexity check with C threshold warning.
- **ci.yml test job**: Add `--cov-fail-under=75` with warning (not blocking). This maintains aspirational coverage target without blocking PRs.
- **test.yml**: Delete entirely after merging unique checks.
- **Makefile**: Update `lint` target to use `ruff check` instead of `flake8/isort`. Update `format` target to use `ruff format` (keep black as primary formatter).

## Rationale
- **Single Source of Truth**: One CI workflow instead of two
- **Reduced CI Minutes**: No duplicate test runs
- **Modern Tooling**: Ruff replaces flake8/isort with faster, Python-native linter
- **Complexity Monitoring**: Radon cyclomatic complexity check highlights functions needing refactoring
- **Coverage Tracking**: 75% coverage threshold as aspirational goal (warning, not blocking)
- **Fixed Broken References**: Removed references to deleted test_imports.py and tests/integration/

## Consequences
- All CI checks now run in a single workflow (ci.yml)
- Makefile uses ruff instead of flake8/isort for consistency
- Coverage below 75% generates warning but doesn't block PRs
- High-complexity functions (C+ rating) generate warnings for refactoring
- Reduced CI runtime and resource usage
