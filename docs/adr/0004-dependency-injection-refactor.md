# ADR 0004: Dependency Injection Refactor

- **Status**: Proposed
- **Date**: 2025-09-20

## Context

# Chronos MCP Dependency Injection Architecture Plan

## Executive Summary

This document outlines a comprehensive refactoring plan to eliminate the critical architectural debt in chronos-mcp's global manager initialization pattern. The current implementation at `server.py:24-35` creates tight coupling, testing difficulties, and violates SOLID principles. This plan provides a dependency injection solution that maintains backward compatibility while improving testability and maintainability.

## Current Architecture Problems

### Global State Issues
- **Location**: `chronos_mcp/server.py` lines 24-35
- **Problem**: All managers initialized as global variables during module import
- **Impact**: Testing requires complex patching, no isolation between test cases
- **SOLID Violations**: Dependency Inversion Principle violated through direct instantiation

### Dependency Chain Analysis
```
ConfigManager (root)
    ↓
AccountManager(config_manager)
    ↓
CalendarManager(account_manager)
    ↓
EventManager(calendar_manager)
TaskManager(calendar_manager)
JournalManager(calendar_manager)
    ↓
BulkOperationManager(event_manager, task_manager, journal_manager)
```

### Testing Difficulties
1. **Global State**: Impossible to test in isolation
2. **Complex Mocking**: Requires patching at module level
3. **Resource Leaks**: No proper cleanup between tests
4. **Circular Dependencies**: Risk of import cycles

## Proposed Dependency Injection Solution

### 1. ChronosDIContainer Architecture

```python
# chronos_mcp/di_container.py
from abc import ABC, abstractmethod
from typing import TypeVar, Type, Callable, Dict, Any
import threading
from contextlib import contextmanager

T = TypeVar('T')

class ChronosDIContainer:
    """Thread-safe dependency injection container with lifecycle management"""

    def __init__(self):
        self._services: Dict[Type, Any] = {}
        self._factories: Dict[Type, Callable] = {}
        self._singletons: Dict[Type, Any] = {}
        self._lock = threading.RLock()
        self._is_initialized = False

    def register_singleton(self, interface: Type[T], factory: Callable[[], T]) -> None:
        """Register a singleton service factory"""
        with self._lock:
            self._factories[interface] = factory

    def register_transient(self, interface: Type[T], factory: Callable[[], T]) -> None:
        """Register a transient service factory"""
        with self._lock:
            self._factories[interface] = factory

    def resolve(self, interface: Type[T]) -> T:
        """Resolve a service dependency"""
        with self._lock:
            if interface in self._singletons:
                return self._singletons[interface]

            if interface not in self._factories:
                raise DependencyNotRegisteredError(f"No factory registered for {interface}")

            instance = self._factories[interface]()
            self._singletons[interface] = instance
            return instance

    @contextmanager
    def lifecycle_scope(self):
        """Context manager for proper resource cleanup"""
        try:
            yield self
        finally:
            self.cleanup()

    def cleanup(self):
        """Cleanup all managed resources"""
        with self._lock:
            for service in self._singletons.values():
                if hasattr(service, '__cleanup__'):
                    service.__cleanup__()
            self._singletons.clear()
```

### 2. Manager Interface Abstractions

```python
# chronos_mcp/interfaces.py
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

class IConfigManager(ABC):
    """Interface for configuration management"""

    @abstractmethod
    def get_account(self, alias: str) -> Optional['Account']:
        pass

    @abstractmethod
    def list_accounts(self) -> List['Account']:
        pass

class IAccountManager(ABC):
    """Interface for CalDAV account management"""

    @abstractmethod
    def connect_account(self, alias: str) -> bool:
        pass

    @abstractmethod
    def get_connection(self, alias: str) -> 'DAVClient':
        pass

class ICalendarManager(ABC):
    """Interface for calendar operations"""

    @abstractmethod
    def list_calendars(self, account_alias: str) -> List['Calendar']:
        pass

    @abstractmethod
    def get_calendar(self, account_alias: str, calendar_uid: str) -> 'Calendar':
        pass

class IEventManager(ABC):
    """Interface for event operations"""

    @abstractmethod
    def create_event(self, event: 'Event') -> str:
        pass

    @abstractmethod
    def get_events_range(self, calendar_uid: str, start: str, end: str) -> List['Event']:
        pass

# Similar interfaces for ITaskManager, IJournalManager, IBulkOperationManager
```

### 3. Factory Functions for Manager Creation

```python
# chronos_mcp/factories.py
from .interfaces import *
from .config import ConfigManager
from .accounts import AccountManager
from .calendars import CalendarManager
from .events import EventManager
from .tasks import TaskManager
from .journals import JournalManager
from .bulk import BulkOperationManager

def create_config_manager() -> IConfigManager:
    """Factory for ConfigManager"""
    return ConfigManager()

def create_account_manager(container: ChronosDIContainer) -> IAccountManager:
    """Factory for AccountManager with injected dependencies"""
    config_manager = container.resolve(IConfigManager)
    return AccountManager(config_manager)

def create_calendar_manager(container: ChronosDIContainer) -> ICalendarManager:
    """Factory for CalendarManager with injected dependencies"""
    account_manager = container.resolve(IAccountManager)
    return CalendarManager(account_manager)

def create_event_manager(container: ChronosDIContainer) -> IEventManager:
    """Factory for EventManager with injected dependencies"""
    calendar_manager = container.resolve(ICalendarManager)
    return EventManager(calendar_manager)

def create_task_manager(container: ChronosDIContainer) -> ITaskManager:
    """Factory for TaskManager with injected dependencies"""
    calendar_manager = container.resolve(ICalendarManager)
    return TaskManager(calendar_manager)

def create_journal_manager(container: ChronosDIContainer) -> IJournalManager:
    """Factory for JournalManager with injected dependencies"""
    calendar_manager = container.resolve(ICalendarManager)
    return JournalManager(calendar_manager)

def create_bulk_manager(container: ChronosDIContainer) -> IBulkOperationManager:
    """Factory for BulkOperationManager with injected dependencies"""
    event_manager = container.resolve(IEventManager)
    task_manager = container.resolve(ITaskManager)
    journal_manager = container.resolve(IJournalManager)
    return BulkOperationManager(
        event_manager=event_manager,
        task_manager=task_manager,
        journal_manager=journal_manager
    )
```

### 4. Container Configuration and Setup

```python
# chronos_mcp/container_config.py
from .di_container import ChronosDIContainer
from .interfaces import *
from .factories import *

def configure_container() -> ChronosDIContainer:
    """Configure the DI container with all service registrations"""
    container = ChronosDIContainer()

    # Register services in dependency order
    container.register_singleton(IConfigManager, create_config_manager)
    container.register_singleton(IAccountManager, lambda: create_account_manager(container))
    container.register_singleton(ICalendarManager, lambda: create_calendar_manager(container))
    container.register_singleton(IEventManager, lambda: create_event_manager(container))
    container.register_singleton(ITaskManager, lambda: create_task_manager(container))
    container.register_singleton(IJournalManager, lambda: create_journal_manager(container))
    container.register_singleton(IBulkOperationManager, lambda: create_bulk_manager(container))

    return container
```

### 5. Refactored Server.py with Backward Compatibility

```python
# chronos_mcp/server.py (new implementation)
"""
Chronos MCP Server - Advanced CalDAV Management with Dependency Injection
"""
import os
from fastmcp import FastMCP
from .di_container import ChronosDIContainer
from .container_config import configure_container
from .interfaces import *
from .logging_config import setup_logging
from .tools import register_all_tools

logger = setup_logging()
mcp = FastMCP("chronos-mcp")

# Global container for backward compatibility
_global_container: Optional[ChronosDIContainer] = None
_legacy_managers: Optional[Dict[str, Any]] = None

def get_container() -> ChronosDIContainer:
    """Get or create the global DI container"""
    global _global_container
    if _global_container is None:
        _global_container = configure_container()
    return _global_container

def get_legacy_managers() -> Dict[str, Any]:
    """Get manager instances in legacy format for backward compatibility"""
    global _legacy_managers
    if _legacy_managers is None:
        container = get_container()
        _legacy_managers = {
            "config_manager": container.resolve(IConfigManager),
            "account_manager": container.resolve(IAccountManager),
            "calendar_manager": container.resolve(ICalendarManager),
            "event_manager": container.resolve(IEventManager),
            "task_manager": container.resolve(ITaskManager),
            "journal_manager": container.resolve(IJournalManager),
            "bulk_manager": container.resolve(IBulkOperationManager),
        }
    return _legacy_managers

# Initialize with DI container
logger.info("Initializing Chronos MCP Server with Dependency Injection...")

try:
    # Use DI container if enabled, otherwise fall back to legacy
    use_di = os.getenv("CHRONOS_USE_DI", "true").lower() == "true"

    if use_di:
        container = get_container()
        register_all_tools(mcp, container)
    else:
        # Legacy fallback for gradual migration
        managers = get_legacy_managers()
        register_all_tools(mcp, managers)

    logger.info("All tools registered successfully")

except Exception as e:
    logger.error(f"Error initializing Chronos MCP Server: {e}")
    raise

# Backward compatibility exports - maintain existing import structure
config_manager = property(lambda self: get_legacy_managers()["config_manager"])
account_manager = property(lambda self: get_legacy_managers()["account_manager"])
calendar_manager = property(lambda self: get_legacy_managers()["calendar_manager"])
event_manager = property(lambda self: get_legacy_managers()["event_manager"])
task_manager = property(lambda self: get_legacy_managers()["task_manager"])
journal_manager = property(lambda self: get_legacy_managers()["journal_manager"])
bulk_manager = property(lambda self: get_legacy_managers()["bulk_manager"])

# Export all tools for backwards compatibility (unchanged)
from .tools.accounts import add_account, list_accounts, remove_account, test_account
# ... rest of imports unchanged
```

### 6. Enhanced Tool Registration with Interface Injection

```python
# chronos_mcp/tools/events.py (updated)
from ..interfaces import IEventManager, ICalendarManager

def register_event_tools(mcp, container_or_managers):
    """Register event tools with proper dependency injection"""

    # Support both new DI container and legacy managers dict
    if hasattr(container_or_managers, 'resolve'):
        # New DI container approach
        event_manager = container_or_managers.resolve(IEventManager)
        calendar_manager = container_or_managers.resolve(ICalendarManager)
    else:
        # Legacy managers dict approach
        event_manager = container_or_managers["event_manager"]
        calendar_manager = container_or_managers["calendar_manager"]

    @mcp.tool()
    def create_event(
        summary: str,
        start: str,
        end: str,
        calendar_uid: str,
        account_alias: str = "default",
        description: str = "",
        location: str = "",
        all_day: bool = False
    ) -> str:
        """Create a new calendar event"""
        # Implementation unchanged - uses injected event_manager
        return event_manager.create_event(...)
```

### 7. Enhanced Test Infrastructure

```python
# tests/conftest.py (updated)
import pytest
from unittest.mock import Mock
from chronos_mcp.di_container import ChronosDIContainer
from chronos_mcp.interfaces import *

@pytest.fixture
def mock_di_container():
    """Mock DI container for testing"""
    container = Mock(spec=ChronosDIContainer)

    # Mock all interface resolvers
    container.resolve.side_effect = lambda interface: Mock(spec=interface)

    return container

@pytest.fixture
def isolated_container():
    """Real DI container with test configuration"""
    from chronos_mcp.container_config import configure_container

    container = configure_container()

    # Override with test implementations
    container.register_singleton(IConfigManager, lambda: Mock(spec=IConfigManager))
    container.register_singleton(IAccountManager, lambda: Mock(spec=IAccountManager))

    yield container

    # Cleanup
    container.cleanup()

@pytest.fixture
def event_manager_with_mocks(isolated_container):
    """Event manager with properly mocked dependencies"""
    return isolated_container.resolve(IEventManager)
```

## Migration Strategy and Timeline

### Phase 1: Foundation (1-2 weeks, Low Risk)
**Deliverables:**
- Create interface abstractions (`interfaces.py`)
- Implement DI container (`di_container.py`)
- Create factory functions (`factories.py`)
- Add container configuration (`container_config.py`)

**Risk Mitigation:**
- No changes to existing code
- Comprehensive unit tests for new components
- Feature flag for gradual enablement

### Phase 2: Integration (2-3 weeks, Medium Risk)
**Deliverables:**
- Update `server.py` with DI container integration
- Maintain backward compatibility facade
- Enhanced test fixtures with DI support
- Environment variable configuration

**Risk Mitigation:**
- Dual-mode operation (DI + legacy)
- Extensive integration testing
- Gradual rollout with monitoring

### Phase 3: Tool Migration (3-4 weeks, Medium Risk)
**Deliverables:**
- Update tool registration to use interfaces
- Migrate test infrastructure to DI patterns
- Performance optimization and monitoring
- Deprecation warnings for legacy patterns

**Risk Mitigation:**
- Tool-by-tool migration
- Parallel testing with both systems
- Performance benchmarking
- Rollback procedures documented

### Phase 4: Cleanup (1-2 weeks, Low Risk)
**Deliverables:**
- Remove legacy manager global variables
- Update documentation and examples
- Final performance optimization
- Production monitoring integration

**Risk Mitigation:**
- Final validation testing
- Performance monitoring
- Documentation updates

## Backward Compatibility Guarantees

### Import Compatibility
```python
# These imports continue to work unchanged
from chronos_mcp.server import (
    config_manager,
    account_manager,
    calendar_manager,
    event_manager,
    task_manager,
    journal_manager,
    bulk_manager
)

# Tool imports remain unchanged
from chronos_mcp.server import create_event, list_calendars, add_account
```

### Test Compatibility
- Existing test fixtures continue to work
- Current mocking patterns remain functional
- Test execution time should improve with better isolation

### Configuration Compatibility
- Current configuration files and environment variables work unchanged
- New DI system enabled via `CHRONOS_USE_DI=true` environment variable
- Default behavior maintains current functionality

## Benefits and Impact

### Immediate Benefits
1. **Improved Testability**: Isolated unit tests with clean mocking
2. **Better Maintainability**: Clear dependency relationships
3. **Enhanced Flexibility**: Easy to swap implementations
4. **Resource Management**: Proper lifecycle and cleanup

### Long-term Benefits
1. **Scalability**: Easy to add new managers and tools
2. **Performance**: Lazy loading and optimized resource usage
3. **Observability**: Built-in monitoring and health checks
4. **Extensibility**: Plugin architecture for custom managers

### Risk Mitigation
1. **Zero Breaking Changes**: Backward compatibility maintained
2. **Gradual Migration**: Feature flags enable incremental adoption
3. **Comprehensive Testing**: Enhanced test infrastructure
4. **Rollback Capability**: Easy reversion if issues arise

## Conclusion

This dependency injection refactoring addresses critical architectural debt while maintaining full backward compatibility. The phased approach minimizes risk while delivering immediate benefits in testability and maintainability. The investment in proper architecture will pay dividends in long-term system stability and developer productivity.

The plan transforms chronos-mcp from a tightly coupled system with global state to a modern, testable architecture following SOLID principles and Python best practices.
