# ADR-0001: Use FastMCP 2.0 as MCP Framework

## Status
Accepted

## Context
Chronos MCP needs a Python framework to implement the Model Context Protocol (MCP) server interface. The MCP protocol enables LLM clients to interact with calendar services through a standardized tool interface.

## Decision
Use FastMCP 2.0 as the MCP server framework.

## Rationale
- FastMCP 2.0 provides native async support via decorator-based tool registration (`@mcp.tool`)
- Built-in input validation and error handling patterns
- Active maintenance and growing ecosystem
- Clean separation between MCP interface and business logic
- Supports both stdio and HTTP transports

## Consequences
- All MCP tools are defined as async functions decorated with `@mcp.tool`
- Error handling follows the `@handle_tool_errors` decorator pattern
- FastMCP-specific patterns must be followed for tool parameter definitions
