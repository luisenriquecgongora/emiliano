"""MCP (Model Context Protocol) host: gives Emiliano's own agent the tools of configured MCP servers."""

from .client import McpError, McpHttpClient, McpStdioClient
from .manager import McpManager, McpServerStatus, McpTool, acp_server_list, qualify

__all__ = ["McpError", "McpHttpClient", "McpStdioClient", "McpManager", "McpServerStatus", "McpTool", "acp_server_list", "qualify"]
