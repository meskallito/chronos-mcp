# VTODO and VJOURNAL Support in Chronos MCP

Chronos MCP provides full support for CalDAV tasks (VTODO) and journal entries (VJOURNAL) as defined in RFC 5545.

## Overview

### VTODO (Tasks)
Tasks represent to-do items with support for:
- Due dates and priorities
- Progress tracking (0-100% completion)
- Status management (NEEDS-ACTION, IN-PROCESS, COMPLETED, CANCELLED)
- Hierarchical relationships (subtasks via RELATED-TO)
- Categories and descriptions

### VJOURNAL (Journal Entries)
Journal entries support:
- Timestamped entries with summaries and descriptions
- Categories for organization
- Relationships between entries (RELATED-TO)
- Rich text descriptions for detailed notes

## MCP Tools Available

### Task Management

#### create_task
Create a new task in a calendar.

```json
{
  "calendar_uid": "calendar-123",
  "summary": "Complete project documentation",
  "description": "Write comprehensive docs for new features",
  "due": "2025-02-01T15:00:00Z",
  "priority": 2,
  "status": "NEEDS-ACTION"
}
```

#### list_tasks
List all tasks in a calendar.

```json
{
  "calendar_uid": "calendar-123"
}
```

#### update_task
Update an existing task's properties.

```json
{
  "calendar_uid": "calendar-123",
  "task_uid": "task-456",
  "percent_complete": 75,
  "status": "IN-PROCESS"
}
```

#### delete_task
Delete a task from a calendar.

```json
{
  "calendar_uid": "calendar-123",
  "task_uid": "task-456"
}
```

#### bulk_create_tasks
Create multiple tasks efficiently with error handling modes.

```json
{
  "calendar_uid": "calendar-123",
  "tasks_json": "[{\"summary\": \"Research phase\", \"due\": \"2025-01-15T10:00:00Z\", \"priority\": 1}, {\"summary\": \"Implementation phase\", \"due\": \"2025-02-01T10:00:00Z\", \"priority\": 2}]",
  "mode": "continue"
}
```

### Journal Management

#### create_journal
Create a new journal entry.

```json
{
  "calendar_uid": "calendar-123",
  "summary": "Team Meeting Notes",
  "description": "Discussed Q1 objectives and project timelines",
  "dtstart": "2025-01-10T14:00:00Z"
}
```

#### list_journals
List all journal entries in a calendar.

```json
{
  "calendar_uid": "calendar-123"
}
```

#### update_journal
Update an existing journal entry.

```json
{
  "calendar_uid": "calendar-123",
  "journal_uid": "journal-789",
  "description": "Updated notes with action items from follow-up discussion"
}
```

#### delete_journal
Delete a journal entry.

```json
{
  "calendar_uid": "calendar-123",
  "journal_uid": "journal-789"
}
```

## Practical Examples

### Example 1: Project Task Management

Create a main task with subtasks:

```python
# Create main task
main_task = create_task(
    calendar_uid="project-calendar",
    summary="Launch new feature",
    due="2025-03-01T00:00:00Z",
    priority=1,
    status="NEEDS-ACTION"
)

# Create subtasks linked to main task
subtask1 = create_task(
    calendar_uid="project-calendar",
    summary="Design UI mockups",
    due="2025-02-01T00:00:00Z",
    priority=2,
    related_to=[main_task["uid"]]
)

subtask2 = create_task(
    calendar_uid="project-calendar",
    summary="Implement backend API",
    due="2025-02-15T00:00:00Z",
    priority=2,
    related_to=[main_task["uid"]]
)
```

### Example 2: Daily Journaling

Create linked journal entries for project documentation:

```python
# Initial planning journal
planning_journal = create_journal(
    calendar_uid="project-calendar",
    summary="Project Kickoff Meeting",
    description="Initial requirements gathering and timeline discussion",
    dtstart="2025-01-10T10:00:00Z"
)

# Follow-up journal linked to planning
followup_journal = create_journal(
    calendar_uid="project-calendar",
    summary="Week 1 Progress Review",
    description="Completed initial design phase, identified technical challenges",
    dtstart="2025-01-17T10:00:00Z",
    related_to=[planning_journal["uid"]]
)
```

## Best Practices

### Task Management
1. **Use priorities wisely**: 1 is highest priority, 9 is lowest
2. **Track progress**: Update percent_complete as work progresses
3. **Status transitions**: NEEDS-ACTION → IN-PROCESS → COMPLETED
4. **Create hierarchies**: Use related_to for subtasks and dependencies

### Journal Entries
1. **Be descriptive**: Use clear summaries and detailed descriptions2. **Link related entries**: Use related_to for follow-ups and related topics
3. **Timestamp appropriately**: Use dtstart to reflect when the journal entry relates to
4. **Categorize**: Use consistent categories for easier organization

## Error Handling

All operations include comprehensive error handling:

- **CalendarNotFoundError**: Invalid calendar UID
- **EventNotFoundError**: Task/Journal not found
- **EventCreationError**: Failed to create item
- **ValidationError**: Invalid input data

## Bulk Operations

For efficiency when working with multiple items:

```python
# Bulk create tasks with atomic mode (all succeed or all fail)
bulk_create_tasks(
    calendar_uid="calendar-123",
    tasks_json='[{"summary": "Research", "due": "2025-01-15T10:00:00Z", "priority": 1}]',
    mode="atomic"
)

# Bulk delete with continue mode (process all, report failures)
bulk_delete_tasks(
    calendar_uid="calendar-123",
    task_uids=["task-1", "task-2", "task-3"],
    mode="continue"
)

# Bulk create journal entries
bulk_create_journals(
    calendar_uid="calendar-123",
    journals_json='[{"summary": "Sprint Retro", "description": "What went well..."}, {"summary": "Design Review", "description": "Approved mockups"}]',
    mode="atomic"
)

# Bulk delete journal entries
bulk_delete_journals(
    calendar_uid="calendar-123",
    journal_uids=["journal-1", "journal-2"],
    mode="continue"
)
```

## CalDAV Server Compatibility

Chronos MCP's VTODO/VJOURNAL support works with any RFC 5545-compliant CalDAV server:
- Nextcloud
- ownCloud
- Radicale
- DAViCal
- And many others

The implementation includes automatic fallbacks for servers with varying levels of component support.
