"""MCP server adapter — expose the vault to AI agents over stdio (offline; optional `mcp` extra).

A thin shell: it registers the pure `TOOLS` from `core.query` and routes every `call-tool` through
`dispatch`, serializing the result to JSON. The transport is **stdio** (no sockets), so an agent like
Claude Desktop can read the vault with **zero network egress** (QAS-1). `mcp` is a lazily-imported
optional dependency (`pip install grandplan[mcp]`); the core and the gate never need it.
"""

from __future__ import annotations

import json

from grandplan.core.directive import (
    DIRECTIVE_TOOLS,
    DirectiveStore,
    dispatch_directive,
)
from grandplan.core.query import TOOLS, ToolSpec, VaultQuery, dispatch
from grandplan.core.write import WRITE_TOOLS, VaultWrite, dispatch_write


def tools_for(*, write_enabled: bool, directives_enabled: bool = False) -> tuple[ToolSpec, ...]:
    """The tools the server exposes: read TOOLS, plus WRITE_TOOLS / DIRECTIVE_TOOLS when enabled."""
    tools = TOOLS
    if write_enabled:
        tools = tools + WRITE_TOOLS
    if directives_enabled:
        tools = tools + DIRECTIVE_TOOLS
    return tools


def route(
    query: VaultQuery,
    write: VaultWrite | None,
    name: str,
    arguments: dict[str, object],
    directives: DirectiveStore | None = None,
) -> object:
    """Route a tool call to read-, write-, or directive-dispatch (pure; stdio shell wraps this).

    Read tools dispatch first. Write and directive tools route only when their capability is enabled
    (the corresponding argument is not None); otherwise the tool is rejected like any unknown one, so
    a read-only server never mutates the vault and directive tools stay off until asked.
    """
    if name in {tool.name for tool in TOOLS}:
        return dispatch(query, name, arguments)
    if write is not None and name in {tool.name for tool in WRITE_TOOLS}:
        return dispatch_write(write, name, arguments)
    if directives is not None and name in {tool.name for tool in DIRECTIVE_TOOLS}:
        return dispatch_directive(directives, name, arguments)
    raise ValueError(f"unknown tool: {name!r}")


def run_stdio_server(
    query: VaultQuery,
    write: VaultWrite | None = None,
    directives: DirectiveStore | None = None,
) -> None:  # pragma: no cover - needs the `mcp` runtime + stdio
    """Run the MCP server over stdio until the client disconnects.

    Read-only by default; pass ``write`` to expose the append-only write tools, and/or ``directives``
    to expose the directive intake tools (list_directives / complete_directive).
    """
    import asyncio

    try:
        import mcp.types as types
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError as exc:  # surfaced to the CLI as an install hint
        raise RuntimeError(
            "the MCP server needs the 'mcp' extra — `pip install grandplan[mcp]`"
        ) from exc

    server: Server = Server("grandplan")
    exposed = tools_for(write_enabled=write is not None, directives_enabled=directives is not None)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=tool.name, description=tool.description, inputSchema=tool.input_schema)
            for tool in exposed
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, object]) -> list[types.TextContent]:
        result = route(query, write, name, arguments or {}, directives)
        return [
            types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))
        ]

    async def _serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_serve())
