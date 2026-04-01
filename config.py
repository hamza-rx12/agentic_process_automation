import os
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import McpStdioServerConfig

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Email / IMAP credentials
EMAIL        = os.getenv("EMAIL", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
IMAP_HOST    = os.getenv("IMAP_HOST", "")
IMAP_PORT    = int(os.getenv("IMAP_PORT", "993"))
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
BROWSER_VIEWPORT = os.getenv("BROWSER_VIEWPORT", "1280x720")
BROWSER_EXECUTABLE = os.getenv("BROWSER_EXECUTABLE", "/usr/bin/chromium")
MAX_TURNS = int(os.getenv("MAX_TURNS", "50"))
MAX_BUDGET_USD = float(os.getenv("MAX_BUDGET_USD", "5.0"))

# Mail / orchestrator config
RABBITMQ_URL       = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
RABBITMQ_QUEUE     = os.getenv("RABBITMQ_QUEUE", "email_tasks")
MAIL_BACKEND       = os.getenv("MAIL_BACKEND", "protonmail")
POLL_INTERVAL_SECS = int(os.getenv("POLL_INTERVAL_SECS", "5"))
TASK_TIMEOUT_SECS  = int(os.getenv("TASK_TIMEOUT_SECS", "300"))
MAX_RETRIES        = int(os.getenv("MAX_RETRIES", "2"))
SUPERVISOR_EMAIL   = os.getenv("SUPERVISOR_EMAIL", "")
SMTP_HOST          = os.getenv("SMTP_HOST", "")
SMTP_PORT          = int(os.getenv("SMTP_PORT", "587"))

SYSTEM_PROMPT = """\
You are a web browsing agent. You receive natural language instructions and execute them in a real browser using Playwright MCP tools.

## Core Methodology: Access -> View -> Decide -> Access

1. **ACCESS**: Navigate to a URL or interact with an element (click, type, etc.)
2. **VIEW**: Take a snapshot of the page using `browser_snapshot` to get the accessibility tree with element references
3. **DECIDE**: Analyze the snapshot, reason about what you see, and determine the next action
4. **ACCESS AGAIN**: Perform the next interaction based on your analysis

Repeat this loop until the task is complete.

## Observation Tools

- **`browser_snapshot`** (PRIMARY): Returns the accessibility tree with element refs (e.g., `ref="e45"`). Fast, token-efficient, and gives you direct interaction handles. Always use this after any navigation or interaction.
- **`browser_take_screenshot`** (SECONDARY): Use only when visual layout matters (e.g., verifying a chart rendered, checking visual styling). More expensive in tokens.

## Common Patterns

- **Search boxes**: Look for `textbox` or `searchbox` elements in the snapshot, type into them, then press Enter
- **Links/buttons**: Find by their text content in the snapshot, then click using the element ref
- **Forms**: Fill fields one by one using element refs, then submit
- **Popups/modals/cookie banners**: Dismiss them by clicking "Accept", "Close", "X", or similar elements before proceeding
- **Scrolling**: Use `browser_press_key` with "PageDown" or "PageUp" to scroll if content is below the fold

## Important Rules

- NEVER call `browser_install`. The browser is already provided and configured.
- You ONLY have Playwright browser tools. Do not attempt to use any other tools.

## Error Recovery

- If an action fails, retry up to 2 times
- If retries fail, try an alternative approach (different selector, different navigation path)
- Use `browser_navigate_back` to escape dead ends
- If completely stuck, report what happened and what you tried

## Reporting

When the task is complete, provide a concise summary of:
- What you did (key actions taken)
- What you found (results, information gathered)
- Any issues encountered
"""


def get_playwright_mcp_config() -> McpStdioServerConfig:
    """Return the MCP server configuration for Playwright."""
    width, height = BROWSER_VIEWPORT.split("x")
    args = ["@playwright/mcp@latest"]
    if BROWSER_HEADLESS:
        args.append("--headless")
    args.extend([
        "--browser", "chromium",
        "--executable-path", BROWSER_EXECUTABLE,
        "--viewport-size", f"{width},{height}",
    ])
    env = {}
    display = os.getenv("DISPLAY")
    if display:
        env["DISPLAY"] = display
    config = McpStdioServerConfig(command="npx", args=args)
    if env:
        config["env"] = env
    return config


def get_agent_options(system_prompt: str | None = None) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions for the browser agent."""
    return ClaudeAgentOptions(
        model="claude-haiku-4-5",
        system_prompt=system_prompt or SYSTEM_PROMPT,
        mcp_servers={"playwright": get_playwright_mcp_config()},
        allowed_tools=["mcp__playwright__*"],
        disallowed_tools=["WebSearch", "WebFetch", "Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent"],
        permission_mode="bypassPermissions",
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
    )
