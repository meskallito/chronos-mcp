# Chronos MCP Architecture

## System Overview

Chronos MCP is a Model Context Protocol server that provides CalDAV calendar operations through a structured, layered architecture.

```mermaid
graph TB
    subgraph "Client Layer"
        CLIENT[MCP Client/Claude]
    end

    subgraph "MCP Interface Layer"
        SERVER[MCP Server]
        TOOLS[Tool Definitions]
        VALID[Input Validation]
    end

    subgraph "Business Logic Layer"
        CONFIG[ConfigManager]
        ACCOUNTS[AccountManager]
        CALENDARS[CalendarManager]
        EVENTS[EventManager]
    end

    subgraph "CalDAV Integration Layer"
        CALDAV[CalDAV Client]
        AUTH[Authentication]
        PARSER[iCal Parser]
    end

    subgraph "Data Layer"
        MODELS[Pydantic Models]
        STORAGE[Config Storage]
        CACHE[Connection Cache]
    end

    subgraph "External Systems"
        CALDAV_SERVER[CalDAV Servers]
    end

    CLIENT -->|MCP Protocol| SERVER
    SERVER --> TOOLS
    TOOLS --> VALID

    VALID --> CONFIG
    VALID --> ACCOUNTS
    VALID --> CALENDARS
    VALID --> EVENTS

    ACCOUNTS --> CONFIG
    CALENDARS --> ACCOUNTS
    EVENTS --> CALENDARS

    ACCOUNTS --> CALDAV
    CALDAV --> AUTH
    CALDAV --> PARSER

    CONFIG --> STORAGE
    ACCOUNTS --> CACHE
    PARSER --> MODELS

    CALDAV -->|HTTP/WebDAV| CALDAV_SERVER
```

## Component Architecture

### Layer Responsibilities

#### 1. MCP Interface Layer
- **MCP Server**: Handles protocol communication
- **Tool Definitions**: Exposes CalDAV operations as MCP tools
- **Input Validation**: Validates and sanitizes user input

#### 2. Business Logic Layer
- **ConfigManager**: Account configuration and persistence
- **AccountManager**: Connection lifecycle and authentication
- **CalendarManager**: Calendar CRUD operations
- **EventManager**: Event lifecycle management

#### 3. CalDAV Integration Layer
- **CalDAV Client**: WebDAV protocol implementation
- **Authentication**: Credential management
- **iCal Parser**: RFC 5545 format handling

#### 4. Data Layer
- **Pydantic Models**: Type-safe data structures
- **Config Storage**: JSON-based configuration
- **Connection Cache**: Reusable DAV connections

## Data Flow

### Request Flow
```mermaid
sequenceDiagram
    participant User
    participant MCP
    participant Validation
    participant Manager
    participant CalDAV
    participant Server

    User->>MCP: Tool Request
    MCP->>Validation: Validate Input
    Validation->>Manager: Process Request
    Manager->>CalDAV: Build DAV Request
    CalDAV->>Server: HTTP/WebDAV
    Server-->>CalDAV: Response
    CalDAV-->>Manager: Parse Response
    Manager-->>MCP: Format Result
    MCP-->>User: Tool Response
```

### Authentication Flow
```mermaid
sequenceDiagram
    participant Manager
    participant Config
    participant Cache
    participant CalDAV
    participant Server

    Manager->>Config: Get Account
    Config-->>Manager: Credentials
    Manager->>Cache: Check Connection

    alt Connection Exists
        Cache-->>Manager: Cached Client
    else No Connection
        Manager->>CalDAV: Create Client
        CalDAV->>Server: Authenticate
        Server-->>CalDAV: Auth Token
        CalDAV-->>Manager: Client Instance
        Manager->>Cache: Store Connection
    end
```

## Module Dependencies

```mermaid
graph LR
    subgraph "Core Modules"
        CONFIG[config.py]
        ACCOUNTS[accounts.py]
        CALENDARS[calendars.py]
        EVENTS[events.py]
    end

    subgraph "Support Modules"
        MODELS[models.py]
        UTILS[utils.py]
        LOGGING[logging_config.py]
    end

    subgraph "Entry Points"
        SERVER[server.py]
        MAIN[__main__.py]
    end

    ACCOUNTS --> CONFIG
    CALENDARS --> ACCOUNTS
    EVENTS --> CALENDARS

    CONFIG --> MODELS
    ACCOUNTS --> MODELS
    CALENDARS --> MODELS
    EVENTS --> MODELS
    EVENTS --> UTILS

    SERVER --> CONFIG
    SERVER --> ACCOUNTS
    SERVER --> CALENDARS
    SERVER --> EVENTS

    MAIN --> SERVER

    style CONFIG fill:#f9f,stroke:#333,stroke-width:2px
    style MODELS fill:#9ff,stroke:#333,stroke-width:2px
```

## Error Handling Architecture

```mermaid
graph TB
    subgraph "Error Sources"
        INPUT[Input Validation]
        NETWORK[Network Errors]
        AUTH[Authentication]
        CALDAV[CalDAV Protocol]
        PARSE[Parsing Errors]
    end

    subgraph "Error Handling"
        CATCH[Exception Catching]
        LOG[Error Logging]
        SANITIZE[Error Sanitization]
    end

    subgraph "Error Response"
        SAFE[Safe Error Message]
        CODE[Error Code]
        REQ_ID[Request ID]
    end

    INPUT --> CATCH
    NETWORK --> CATCH
    AUTH --> CATCH
    CALDAV --> CATCH
    PARSE --> CATCH

    CATCH --> LOG
    CATCH --> SANITIZE

    SANITIZE --> SAFE
    SANITIZE --> CODE
    SANITIZE --> REQ_ID

    SAFE --> |User Response| USER[User]
    LOG --> |Full Details| LOGS[Log File]
```

## Security Architecture

### Current Implementation

```mermaid
graph TB
    subgraph "Security Layers"
        INPUT_VAL[Input Validation]
        AUTH_LAYER[Authentication]
        ERROR_SAN[Error Sanitization]
        LOG_MASK[Log Masking]
    end

    subgraph "Data Protection"
        CONFIG_FILE[Config File<br/>Plain Text]
        MEMORY[In-Memory<br/>Credentials]
        LOGS[Log Files<br/>Masked]
    end

    subgraph "Future Enhancements"
        KEYRING[OS Keyring]
        OAUTH[OAuth2]
        ENCRYPT[Encrypted Config]
    end

    INPUT_VAL --> |Prevent Injection| AUTH_LAYER
    AUTH_LAYER --> |Hide Errors| ERROR_SAN
    ERROR_SAN --> |Mask Sensitive| LOG_MASK

    CONFIG_FILE -.->|Future| KEYRING
    CONFIG_FILE -.->|Future| ENCRYPT
    MEMORY -.->|Future| OAUTH

    style CONFIG_FILE fill:#faa,stroke:#333,stroke-width:2px
    style KEYRING fill:#afa,stroke:#333,stroke-width:2px
    style OAUTH fill:#afa,stroke:#333,stroke-width:2px
    style ENCRYPT fill:#afa,stroke:#333,stroke-width:2px
```


## Class Relationships

```mermaid
classDiagram
    class ConfigManager {
        +Config config
        +Path config_path
        +add_account()
        +remove_account()
        +get_account()
        +list_accounts()
        +save_config()
        +load_config()
    }

    class AccountManager {
        +ConfigManager config
        +Dict connections
        +connect_account()
        +disconnect_account()
        +get_connection()
        +test_account()
        +get_principal()
    }

    class CalendarManager {
        +AccountManager accounts
        +list_calendars()
        +create_calendar()
        +delete_calendar()
        +get_calendar()
    }

    class EventManager {
        +CalendarManager calendars
        +create_event()
        +get_events_range()
        +delete_event()
        -_parse_caldav_event()
        -_parse_attendee()
    }

    class Account {
        +str alias
        +HttpUrl url
        +str username
        +str password
        +AccountStatus status
    }

    class Calendar {
        +str uid
        +str name
        +str description
        +str color
        +str account_alias
        +bool read_only
    }

    class Event {
        +str uid
        +str summary
        +datetime start
        +datetime end
        +List~Attendee~ attendees
        +List~Alarm~ alarms
    }

    ConfigManager --> Account : manages
    AccountManager --> ConfigManager : uses
    CalendarManager --> AccountManager : uses
    EventManager --> CalendarManager : uses

    CalendarManager --> Calendar : creates
    EventManager --> Event : creates
```

## State Management

### Connection State
```mermaid
stateDiagram-v2
    [*] --> Disconnected

    Disconnected --> Connecting : connect_account()
    Connecting --> Connected : Success
    Connecting --> Error : Failed

    Connected --> Disconnected : disconnect_account()
    Connected --> Error : Connection Lost

    Error --> Connecting : Retry
    Error --> Disconnected : Give Up

    Connected --> Active : Making Request
    Active --> Connected : Request Complete
    Active --> Error : Request Failed
```

### Event Lifecycle
```mermaid
stateDiagram-v2
    [*] --> Created : create_event()

    Created --> Validated : Input Validation
    Validated --> Formatted : Build iCal
    Formatted --> Sent : Send to Server

    Sent --> Stored : Server Accept
    Sent --> Failed : Server Reject

    Stored --> Retrieved : get_events_range()
    Stored --> Deleted : delete_event()

    Failed --> [*]
    Deleted --> [*]
```

## Deployment Architecture

### Docker Deployment
```mermaid
graph TB
    subgraph "Container"
        APP[Chronos MCP]
        CONFIG_VOL[Config Volume]
        LOG_VOL[Log Volume]
    end

    subgraph "Host System"
        STDIO[STDIO]
        CONFIG_DIR[~/.config/chronos-mcp]
        LOG_DIR[/var/log/chronos-mcp]
    end

    subgraph "Network"
        CALDAV1[CalDAV Server 1]
        CALDAV2[CalDAV Server 2]
        CALDAVN[CalDAV Server N]
    end

    STDIO <--> APP
    CONFIG_DIR <--> CONFIG_VOL
    LOG_DIR <--> LOG_VOL

    APP --> |HTTPS| CALDAV1
    APP --> |HTTPS| CALDAV2
    APP --> |HTTPS| CALDAVN
```

### System Integration
```mermaid
graph LR
    subgraph "AI Assistant"
        CLAUDE[Claude/LLM]
        MCP_CLIENT[MCP Client]
    end

    subgraph "MCP Servers"
        CHRONOS[Chronos MCP]
        OTHER1[File System MCP]
        OTHER2[Database MCP]
    end

    subgraph "Calendar Systems"
        GOOGLE[Google Calendar]
        NEXTCLOUD[Nextcloud]
        EXCHANGE[Exchange]
        APPLE[iCloud]
    end

    CLAUDE --> MCP_CLIENT
    MCP_CLIENT --> CHRONOS
    MCP_CLIENT --> OTHER1
    MCP_CLIENT --> OTHER2

    CHRONOS --> |CalDAV| GOOGLE
    CHRONOS --> |CalDAV| NEXTCLOUD
    CHRONOS --> |CalDAV| EXCHANGE
    CHRONOS --> |CalDAV| APPLE
```

## Performance Characteristics

### Request Processing
```mermaid
graph LR
    subgraph "Fast Operations O(1)"
        CONFIG_READ[Read Config]
        CACHE_CHECK[Check Cache]
        VALIDATE[Validate Input]
    end

    subgraph "Network Operations O(n)"
        AUTH[Authenticate]
        LIST_CAL[List Calendars]
        GET_EVENTS[Get Events]
    end

    subgraph "Heavy Operations O(n²)"
        BULK_CREATE[Bulk Create]
        CONFLICT_CHECK[Conflict Detection]
        SYNC_CAL[Calendar Sync]
    end
```

### Caching Strategy
```mermaid
graph TB
    subgraph "Cached"
        CONNECTIONS[DAV Connections]
        PRINCIPALS[Principal Objects]
        CONFIG[Configuration]
    end

    subgraph "Not Cached"
        CALENDARS[Calendar List]
        EVENTS[Event Data]
        PROPS[Calendar Properties]
    end

    subgraph "Future Caching"
        CAL_META[Calendar Metadata<br/>TTL: 5 min]
        EVENT_CACHE[Recent Events<br/>TTL: 1 min]
        ETAG[ETag Support]
    end

    CONNECTIONS --> |Reused| REQUESTS[All Requests]
    PRINCIPALS --> |Reused| CAL_OPS[Calendar Ops]
    CONFIG --> |Static| ALL[All Operations]

    style CAL_META fill:#ffa,stroke:#333,stroke-width:2px,stroke-dasharray: 5 5
    style EVENT_CACHE fill:#ffa,stroke:#333,stroke-width:2px,stroke-dasharray: 5 5
    style ETAG fill:#ffa,stroke:#333,stroke-width:2px,stroke-dasharray: 5 5
```

## Scalability Considerations

### Current Limitations
- Single-threaded execution
- No connection pooling
- No request queuing
- Synchronous operations only

### Future Scalability Path
```mermaid
graph TB
    subgraph "Current Architecture"
        SYNC[Synchronous]
        SINGLE[Single Thread]
        NO_POOL[No Pooling]
    end

    subgraph "Enhanced Architecture"
        ASYNC[Async Support]
        POOL[Connection Pool]
        QUEUE[Request Queue]
    end

    subgraph "Distributed Architecture"
        WORKERS[Worker Processes]
        REDIS[Redis Cache]
        LB[Load Balancer]
    end

    SYNC --> ASYNC
    SINGLE --> POOL
    NO_POOL --> QUEUE

    ASYNC --> WORKERS
    POOL --> REDIS
    QUEUE --> LB
```

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Protocol | MCP (Model Context Protocol) | AI tool interface |
| Language | Python 3.10+ | Implementation language |
| Framework | None (stdlib) | Minimal dependencies |
| Models | Pydantic 2.x | Data validation |
| CalDAV | python-caldav | CalDAV protocol |
| Calendar | icalendar | iCal format parsing |
| Config | JSON | Configuration storage |
| Logging | Python logging | Error tracking |
| Testing | pytest | Test framework |
| Coverage | pytest-cov | Code coverage |

## Architectural Decisions

See [docs/adr/](./adr/) for detailed rationale behind key architectural choices.
