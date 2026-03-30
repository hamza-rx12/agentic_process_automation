import sys
import anyio
from config import ANTHROPIC_API_KEY
from browser_agent import run_single_task, run_conversational


def main():
    if not ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY is not set in .env")
        sys.exit(1)

    if len(sys.argv) > 1:
        instruction = " ".join(sys.argv[1:])
        anyio.run(run_single_task, instruction)
    else:
        anyio.run(run_conversational)


if __name__ == "__main__":
    main()
