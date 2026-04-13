"""Tool callback implementations for Claude Agent."""

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext
)

from app.common.utils import get_logger

logger = get_logger(__name__)


async def default_callback(
    tool_name: str,
    input_data: dict,
    context: ToolPermissionContext
) -> PermissionResultAllow | PermissionResultDeny:
    """Default callback - allows all tools (current behavior)."""
    logger.debug(f"Default callback allowing tool: {tool_name}")
    return PermissionResultAllow()


async def security_callback(
    tool_name: str,
    input_data: dict,
    context: ToolPermissionContext
) -> PermissionResultAllow | PermissionResultDeny:
    """Security callback - blocks dangerous operations based on available tools."""

    logger.info(f"Security callback evaluating tool: {tool_name}")

    # Always allow read-only operations
    if tool_name in ["Read", "Glob", "Grep", "ListMcpResources", "ReadMcpResource"]:
        logger.debug(f"Allowing read-only tool: {tool_name}")
        return PermissionResultAllow()

    # Block dangerous bash commands
    if tool_name == "Bash":
        command = input_data.get("command", "")
        dangerous_patterns = ["rm -rf", "sudo rm", "chmod 777", "dd if=", "mkfs", "format", "fdisk"]

        for pattern in dangerous_patterns:
            if pattern in command:
                logger.warning(f"Blocking dangerous command in {tool_name}: {pattern}")
                return PermissionResultDeny(message=f"Dangerous command pattern detected: {pattern}")

        logger.debug(f"Allowing safe bash command: {command[:50]}...")
        return PermissionResultAllow()

    # Restrict file operations
    if tool_name in ["Write", "Edit", "MultiEdit"]:
        file_path = input_data.get("file_path", "")

        # Block system directories
        system_dirs = ["/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc"]
        if any(file_path.startswith(sys_dir) for sys_dir in system_dirs):
            logger.warning(f"Blocking system directory write in {tool_name}: {file_path}")
            return PermissionResultDeny(message=f"Cannot modify system directory: {file_path}")

        # Redirect to safe directory if not already safe
        safe_dirs = ["./", "/tmp/", "./safe_workspace/"]
        if not any(file_path.startswith(safe_dir) for safe_dir in safe_dirs):
            safe_path = f"./safe_workspace/{file_path.split('/')[-1]}"
            modified_input = input_data.copy()
            modified_input["file_path"] = safe_path

            logger.warning(f"Redirecting {tool_name} from {file_path} to safe path: {safe_path}")
            return PermissionResultAllow(updated_input=modified_input)

        logger.debug(f"Allowing safe file operation in {tool_name}: {file_path}")
        return PermissionResultAllow()

    # Allow web tools with caution
    if tool_name in ["WebFetch", "WebSearch"]:
        logger.debug(f"Allowing web tool: {tool_name}")
        return PermissionResultAllow()

    # Allow task management tools
    if tool_name in ["TodoWrite", "ExitPlanMode", "BashOutput", "KillBash"]:
        logger.debug(f"Allowing task management tool: {tool_name}")
        return PermissionResultAllow()

    # Allow notebook operations
    if tool_name == "NotebookEdit":
        logger.debug(f"Allowing notebook tool: {tool_name}")
        return PermissionResultAllow()

    # Default allow for unknown tools (but log for monitoring)
    logger.info(f"Allowing unknown tool by default: {tool_name}")
    return PermissionResultAllow()