#!/usr/bin/env python3
"""
Interactive REPL for testing the Claude + PAN proxy API.

Similar to the CLI, but uses the REST API instead of direct client access.
Useful for testing API functionality and simulating client applications.

Usage:
    export PYTHONPATH="${PYTHONPATH}:./app"
    python3 examples/interactive_repl.py
    python3 examples/interactive_repl.py --url http://remote-proxy:8080

Commands:
    /new      - Start a new session
    /mode     - Toggle PAN inspect mode (prompt_only ↔ full_history)
    /history  - Show conversation history
    /scans    - Show PAN scan results
    /health   - Check service health
    /help     - Show help
    /quit     - Exit
"""

import asyncio
import sys
import argparse
from datetime import datetime
sys.path.insert(0, "../app")
from api_client import ClaudePANClient, ConversationSession


# ANSI colors
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
RED = "\033[31m"


def c(color, text):
    """Wrap text in ANSI color."""
    return f"{color}{text}{RESET}"


def banner():
    print()
    print(c(BOLD + MAGENTA, "  ╔══════════════════════════════════════════╗"))
    print(c(BOLD + MAGENTA, "  ║   Claude + PAN API — Interactive REPL    ║"))
    print(c(BOLD + MAGENTA, "  ╚══════════════════════════════════════════╝"))
    print()


def hr(char="─", width=60, color=DIM):
    print(c(color, char * width))


def print_help():
    print()
    hr()
    print(c(BOLD, "  Commands"))
    hr()
    cmds = [
        ("/new", "Start a new session"),
        ("/mode", "Toggle PAN inspect mode (prompt_only ↔ full_history)"),
        ("/history", "Show conversation history"),
        ("/scans", "Show PAN scan results"),
        ("/health", "Check service health"),
        ("/help", "Show this help"),
        ("/quit", "Exit"),
    ]
    for cmd, desc in cmds:
        print(f"  {c(CYAN, cmd):<18} {c(DIM, desc)}")
    hr()
    print()


def print_scan_result(pan: dict, mode: str):
    """Print PAN scan details."""
    hr("─", 60, DIM + BLUE)
    print(c(BOLD + BLUE, "  🛡  AIRS Scan Result"))
    hr("─", 60, DIM + BLUE)

    mode_label = (
        c(MAGENTA, "📋 Full conversation history")
        if mode == "full_history"
        else c(DIM, "💬 Latest prompt only")
    )
    print(f"  Mode: {mode_label}")

    if pan["was_scanned"]:
        verdict = pan["verdict"]
        if verdict == "allow":
            verdict_label = c(GREEN, "✓ ALLOW")
        else:
            verdict_label = c(RED, "✗ BLOCK")

        print(f"  Verdict: {verdict_label}")
        print(f"  Scan ID: {c(DIM, pan.get('scan_id', 'N/A'))}")
        print(f"  Category: {c(DIM, pan.get('category', 'N/A'))}")

        if pan.get("reason"):
            print(f"  Reason: {c(YELLOW, pan['reason'])}")
    else:
        print(f"  Status: {c(YELLOW, '⚠ Not scanned (fail-open)')}")
        if pan.get("error"):
            print(f"  Error: {c(RED, pan['error'])}")

    hr("─", 60, DIM + BLUE)
    print()


async def repl(base_url: str):
    """Run the interactive REPL."""
    banner()

    client = ClaudePANClient(base_url=base_url)

    # Check health
    print(c(DIM, f"Connecting to {base_url}..."))
    try:
        health = await client.health()
        print(c(GREEN, f"✓ Connected"))
        print(f"  Model: {c(CYAN, health.get('model', 'N/A'))}")
        print(f"  PAN status: {c(CYAN, health['pan_status'])}")
        print()
    except Exception as e:
        print(c(RED, f"✗ Connection failed: {e}"))
        print()
        return

    print(c(DIM, "Type /help for commands, /quit to exit"))
    print()

    # Start session
    mode = "prompt_only"
    session = ConversationSession(client, pan_inspect_mode=mode)

    while True:
        try:
            # Prompt
            user_input = input(c(BOLD + CYAN, "You > ")).strip()

            if not user_input:
                continue

            # Commands
            if user_input.lower() in ["/quit", "/exit"]:
                print(c(DIM, "\nGoodbye! 👋\n"))
                break

            elif user_input.lower() == "/help":
                print_help()
                continue

            elif user_input.lower() == "/new":
                session = ConversationSession(client, pan_inspect_mode=mode)
                print(c(GREEN, "✓ New session started\n"))
                continue

            elif user_input.lower() == "/mode":
                mode = "full_history" if mode == "prompt_only" else "prompt_only"
                session = ConversationSession(client, pan_inspect_mode=mode)
                print(c(GREEN, f"✓ Switched to {c(CYAN, mode)} mode (new session started)\n"))
                continue

            elif user_input.lower() == "/history":
                history = session.get_history()
                if not history:
                    print(c(DIM, "  (no messages yet)\n"))
                else:
                    hr()
                    for msg in history:
                        role = c(CYAN, "You") if msg["role"] == "user" else c(MAGENTA, "Claude")
                        print(f"  {role}: {msg['content'][:80]}...")
                    hr()
                    print()
                continue

            elif user_input.lower() == "/scans":
                scans = session.get_scan_results()
                if not scans:
                    print(c(DIM, "  (no scans yet)\n"))
                else:
                    hr()
                    for idx, scan in enumerate(scans, 1):
                        verdict = scan["pan"]["verdict"]
                        verdict_color = GREEN if verdict == "allow" else RED
                        print(f"  {idx}. {c(verdict_color, verdict.upper())} — {scan['prompt'][:50]}...")
                    hr()
                    print()
                continue

            elif user_input.lower() == "/health":
                health = await client.health()
                hr()
                print(f"  Status: {c(GREEN, health['status'])}")
                print(f"  Model: {health.get('model', 'N/A')}")
                print(f"  PAN configured: {health['pan_configured']}")
                print(f"  PAN status: {health['pan_status']}")
                if health.get('pan_error'):
                    print(f"  PAN error: {c(RED, health['pan_error'])}")
                hr()
                print()
                continue

            # Send message
            try:
                response = await session.send(user_input)

                # Print Claude's response
                print()
                print(c(BOLD + MAGENTA, "Claude > ") + response["response"])
                print()

                # Print scan details
                print_scan_result(response["pan"], mode)

            except Exception as e:
                print(c(RED, f"\n✗ Error: {e}\n"))

        except KeyboardInterrupt:
            print(c(DIM, "\n\nGoodbye! 👋\n"))
            break
        except EOFError:
            print(c(DIM, "\n\nGoodbye! 👋\n"))
            break


def main():
    parser = argparse.ArgumentParser(
        description="Interactive REPL for Claude + PAN proxy API"
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8080",
        help="Base URL of the proxy service",
    )
    args = parser.parse_args()

    try:
        asyncio.run(repl(base_url=args.url))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
