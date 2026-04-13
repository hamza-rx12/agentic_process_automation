"""
Tools package with auto-discovery system for MCP tools.

This package automatically discovers and registers MCP tools using convention:
- Tool implementations: standard function names (e.g., math_tool)
- MCP wrappers: functions ending with _mcp suffix (e.g., math_tool_mcp)
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from claude_agent_sdk import SdkMcpTool

logger = logging.getLogger(__name__)


def discover_local_mcp_tools() -> list[SdkMcpTool]:
    """
    Auto-discover all MCP tools in the tools package.

    Scans all modules in app.tools package for SdkMcpTool objects
    that have handler functions ending with '_mcp'.

    Returns:
        List of discovered MCP tool functions
    """
    tools: list[SdkMcpTool] = []

    try:
        import app.tools as tools_package

        for importer, modname, ispkg in pkgutil.iter_modules(tools_package.__path__, tools_package.__name__ + "."):
            if not ispkg:  # Only process files, not subdirectories
                try:
                    module = importlib.import_module(modname)

                    # Look for SdkMcpTool objects with _mcp handler functions
                    for attr_name in dir(module):
                        tool_func = getattr(module, attr_name)

                        # Check if it's a SdkMcpTool with handler ending in _mcp
                        if (isinstance(tool_func, SdkMcpTool) and
                            hasattr(tool_func, 'handler') and
                            callable(tool_func.handler) and
                            tool_func.handler.__name__.endswith('_mcp')):
                            tools.append(tool_func)
                            logger.info("Auto-registered MCP tool: %s.%s (name: %s)",
                                       modname, attr_name, tool_func.name)

                except Exception as e:
                    logger.warning("Failed to load module %s: %s", modname, e)
                    continue

        logger.info("Discovered %d MCP tools in app.tools package", len(tools))
        return tools

    except Exception as e:
        logger.exception("Failed to discover MCP tools")
        return []


def get_tool_names() -> list[str]:
    """
    Get list of discovered tool names in Claude SDK format.

    Returns:
        List of tool names formatted as mcp__local_tools__tool_name
    """
    tools = discover_local_mcp_tools()
    tool_names = []

    for tool in tools:
        # Extract tool name from SdkMcpTool.name attribute
        if isinstance(tool, SdkMcpTool) and hasattr(tool, 'name'):
            tool_names.append(f"mcp__local_tools__{tool.name}")
        else:
            logger.warning("Tool %s is not a valid SdkMcpTool", tool)

    return tool_names


__all__ = [
    "discover_local_mcp_tools",
    "get_tool_names",
]