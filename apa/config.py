import os

from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import McpStdioServerConfig

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# --- API ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- Email / IMAP ---
EMAIL = os.getenv("EMAIL", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
IMAP_HOST = os.getenv("IMAP_HOST", "")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
MAIL_BACKEND = os.getenv("MAIL_BACKEND", "protonmail")
POLL_INTERVAL_SECS = int(os.getenv("POLL_INTERVAL_SECS", "5"))

# --- Browser ---
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
BROWSER_VIEWPORT = os.getenv("BROWSER_VIEWPORT", "1280x720")
BROWSER_EXECUTABLE = os.getenv("BROWSER_EXECUTABLE", "/usr/bin/chromium")

# --- Agent limits ---
MAX_TURNS = int(os.getenv("MAX_TURNS", "50"))
MAX_BUDGET_USD = float(os.getenv("MAX_BUDGET_USD", "5.0"))

# --- RabbitMQ ---
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "email_tasks")

# --- A2A ---
BROWSER_AGENT_URL = os.getenv("BROWSER_AGENT_URL", "http://localhost:8080")
A2A_PORT = int(os.getenv("A2A_PORT", "8080"))

# --- System prompt ---
SYSTEM_PROMPT = """\
You are a web browsing agent. You receive natural language instructions and \
execute them in a real browser using Playwright MCP tools.

## Core Loop: Access → View → Decide → Access

1. **ACCESS**: Navigate to a URL or interact with an element
2. **VIEW**: Use `browser_snapshot` to get the accessibility tree with element refs
3. **DECIDE**: Analyse the snapshot and determine the next action
4. **ACCESS AGAIN**: Perform the next interaction

## Tools

- **`browser_snapshot`** (primary): accessibility tree with refs like `ref="e45"`. Fast, cheap.
- **`browser_take_screenshot`** (secondary): only when visual layout matters.

## Rules

- NEVER call `browser_install` — the browser is already configured.
- You ONLY have Playwright browser tools.
- Dismiss cookie banners / popups before proceeding.
- Retry failed actions up to 2 times, then try an alternative approach.
- Use `browser_navigate_back` to escape dead ends.

## Reporting

When done, summarise: what you did, what you found, any issues.
"""


def get_playwright_mcp() -> McpStdioServerConfig:
    """MCP server config for Playwright."""
    w, h = BROWSER_VIEWPORT.split("x")
    args = ["@playwright/mcp@latest"]
    if BROWSER_HEADLESS:
        args.append("--headless")
    args.extend(
        [
            "--browser",
            "chromium",
            "--executable-path",
            BROWSER_EXECUTABLE,
            "--viewport-size",
            f"{w},{h}",
        ]
    )
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
        mcp_servers={"playwright": get_playwright_mcp()},
        allowed_tools=["mcp__playwright__*"],
        disallowed_tools=[
            "WebSearch",
            "WebFetch",
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            "Agent",
        ],
        permission_mode="bypassPermissions",
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
    )
