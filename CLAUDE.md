# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Core Commands

### Development
```bash
# Install for development with all dependencies
make dev-install

# Run the MCP server
./run_chronos.sh
# or
python -m chronos_mcp

# Format code (required before committing)
make format

# Run linting checks
make lint

# Run all tests
make test

# Run specific test categories
make test-unit         # Unit tests only
make test-integration  # Integration tests only

# Run tests with coverage
make coverage

# Run a single test file
pytest tests/unit/test_events.py -v

# Run a specific test
pytest tests/unit/test_events.py::test_create_event -v

# Clean build artifacts
make clean
```

### Linting and Formatting
```bash
# Format with black and isort
black chronos_mcp tests
isort chronos_mcp tests

# Check formatting without modifying
black --check chronos_mcp tests
isort --check-only chronos_mcp tests

# Type checking
mypy chronos_mcp
```

## Architecture Overview

Chronos MCP is a Model Context Protocol server for CalDAV calendar management built with FastMCP 2.0. The codebase follows a layered architecture:

### Key Components

1. **MCP Interface Layer** (`server.py`)
   - Defines MCP tools using FastMCP decorators
   - Handles input validation and error sanitization
   - Maps tool calls to business logic managers

2. **Tool Interface Layer** (`tools/`)
   - `tools/base.py`: Base tool manager class with connection caching
   - `tools/accounts.py`: Account management tools
   - `tools/calendars.py`: Calendar CRUD tools
   - `tools/events.py`: Event lifecycle tools
   - `tools/tasks.py`: VTODO task tools
   - `tools/journals.py`: VJOURNAL journal tools
   - `tools/bulk.py`: Bulk operation tools
   - Delegation pattern: server.py delegates to tools/, tools/ delegate to business logic managers

3. **Business Logic Layer**
   - `accounts.py`: Multi-account management with connection caching
   - `calendars.py`: Calendar CRUD operations
   - `events.py`: Event lifecycle including recurring events (RRULE)
   - `tasks.py`: VTODO task management
   - `journals.py`: VJOURNAL journal entry management
   - `bulk.py`: Parallel bulk operations with rollback support
   - `search.py`: Advanced search with relevance ranking

3. **Data Layer**
   - `models.py`: Pydantic models for type safety
   - `config.py`: Account configuration persistence
   - `credentials.py`: Secure password storage via keyring

4. **Validation Layer**
   - `validation.py`: Input sanitization and XSS prevention
   - `rrule.py`: RRULE validation for recurring events
   - `exceptions.py`: Custom exceptions with error sanitization

### Important Patterns

- **Manager Pattern**: Each domain (accounts, calendars, events) has a dedicated manager class
- **Connection Caching**: DAV connections are cached per account to improve performance
- **Error Handling**: All errors are sanitized before returning to prevent information leakage
- **Async Tools**: All MCP tools are async functions decorated with `@mcp.tool`
- **Field Validation**: Pydantic Field() for parameter validation in tool definitions

### Key Files to Understand

- `server.py`: Entry point and tool definitions - start here to understand available operations
- `tools/base.py`: Base tool manager with connection caching and error handling
- `models.py`: Data structures used throughout the codebase
- `exceptions.py`: Error handling patterns and custom exceptions
- `validation.py`: Security-critical input validation logic

### Testing Approach

- Tests are in `tests/unit/` organized by module
- Each manager class has corresponding test file (e.g., `events.py` → `test_events.py`)
- Tests use pytest fixtures defined in `conftest.py`
- Mock CalDAV responses for unit tests to avoid external dependencies

### Security Considerations

- All user input is validated using `InputValidator` class
- Passwords stored securely via system keyring when available
- Path traversal and injection attacks prevented in validation layer
- Error messages sanitized to prevent information disclosure

### Common Development Tasks

When adding new CalDAV functionality:
1. Add Pydantic model to `models.py` if needed
2. Implement business logic in appropriate manager class (e.g., `events.py`)
3. Add tool wrapper in `tools/<domain>.py` if complex validation needed
4. Add tool definition in `server.py` with proper validation
5. Write unit tests following existing patterns
6. Update API documentation if adding new tools

When fixing bugs:
1. Check if error handling follows the sanitization pattern
2. Ensure input validation is applied consistently
3. Add test case reproducing the bug before fixing
4. Run full test suite to prevent regressions
