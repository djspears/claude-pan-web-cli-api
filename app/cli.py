#!/usr/bin/env python3
"""
Claude + PAN AI Security — interactive command-line client.

Provides the same functionality as the web UI:
  • Prompts are scanned by PAN AIRS before being sent to Claude
  • Full scan details are shown after each message
  • Session management and inspect-mode toggle

Usage (from inside the container):
  python cli.py

Usage (via docker exec):
  docker exec -it claude-pan-proxy python cli.py

Commands:
  /new      Start a new session (clears conversation history)
  /mode     Toggle PAN inspect mode (prompt_only ↔ full_history)
  /status   Show PAN connection status
  /clear    Clear the screen
  /history  Show conversation history for this session
  /help     Show this help
  /quit     Exit
"""

import asyncio
import os
import sys
import uuid
import json
import textwrap
from datetime import datetime

from claude_client import ClaudeClient
from pan_client import PANClient
from models import Message, Role, PANVerdict

# ── ANSI colours ────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"

BLACK   = "\033[30m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
WHITE   = "\033[37m"

BG_RED    = "\033[41m"
BG_GREEN  = "\033[42m"
BG_YELLOW = "\033[43m"
BG_BLUE   = "\033[44m"

def c(colour, text):
    """Wrap text in an ANSI colour code."""
    return f"{colour}{text}{RESET}"

def banner():
    print()
    print(c(BOLD + MAGENTA, "  ╔══════════════════════════════════════════╗"))
    print(c(BOLD + MAGENTA, "  ║   Claude + PAN AI Security  —  CLI       ║"))
    print(c(BOLD + MAGENTA, "  ╚══════════════════════════════════════════╝"))
    print()

def hr(char="─", width=60, colour=DIM):
    print(c(colour, char * width))

def print_help():
    print()
    hr()
    print(c(BOLD, "  Commands"))
    hr()
    cmds = [
        ("/new",     "Start a new session (clears conversation history)"),
        ("/mode",    "Toggle PAN inspect mode (prompt_only ↔ full_history)"),
        ("/status",  "Show PAN connection status"),
        ("/history", "Show conversation history for this session"),
        ("/clear",   "Clear the screen"),
        ("/help",    "Show this help"),
        ("/quit",    "Exit  (Ctrl+C also works)"),
    ]
    for cmd, desc in cmds:
        print(f"  {c(CYAN, cmd):<28} {c(DIM, desc)}")
    hr()
    print()

def print_scan_result(scan, inspect_mode: str):
    """Pretty-print a PAN scan result block."""
    hr("─", 60, DIM + BLUE)
    print(c(BOLD + BLUE, "  🛡  AIRS Scan Result"))
    hr("─", 60, DIM + BLUE)

    # Inspect mode
    mode_label = (
        c(MAGENTA, "📋 Full conversation history")
        if inspect_mode == "full_history"
        else c(WHITE, "💬 Latest prompt only")
    )
    print(f"  {c(DIM, 'Mode    ')}  {mode_label}")

    # Was scanned?
    if scan.was_scanned:
        print(f"  {c(DIM, 'Inspected')} {c(GREEN, 'Yes — real AIRS scan')}")
    else:
        reason = scan.reason or "unknown"
        print(f"  {c(DIM, 'Inspected')} {c(YELLOW, f'No — {reason}')}")

    # Verdict
    if scan.verdict == PANVerdict.block:
        verdict_str = c(BOLD + RED, "✕  BLOCKED")
    else:
        verdict_str = c(BOLD + GREEN, "✓  ALLOWED")
    print(f"  {c(DIM, 'Verdict  ')} {verdict_str}")

    # Optional fields
    if scan.scan_id:
        print(f"  {c(DIM, 'Scan ID  ')} {c(MAGENTA, scan.scan_id)}")
    if scan.category:
        print(f"  {c(DIM, 'Category ')} {c(YELLOW, scan.category)}")
    if scan.reason and not scan.was_scanned:
        print(f"  {c(DIM, 'Reason   ')} {c(DIM, scan.reason)}")
    if scan.error:
        print(f"  {c(DIM, 'Error    ')} {c(RED, scan.error)}")

    # Raw response (collapsed by default, shown with --verbose)
    if scan.raw_response and os.getenv("PAN_CLI_VERBOSE", "").lower() == "true":
        print(f"  {c(DIM, 'Raw JSON ')} {c(DIM, json.dumps(scan.raw_response, indent=2))}")

    hr("─", 60, DIM + BLUE)
    print()

def print_status(pan: PANClient, claude: ClaudeClient, inspect_mode: str, session_id: str):
    print()
    hr()
    print(c(BOLD, "  Connection Status"))
    hr()
    if pan.enabled:
        print(f"  {c(DIM, 'PAN URL    ')}  {c(CYAN, pan.base_url)}")
        print(f"  {c(DIM, 'PAN Profile')}  {c(CYAN, pan.profile_name)}")
        print(f"  {c(DIM, 'PAN Key    ')}  {c(GREEN, '●  configured')}")
    else:
        print(f"  {c(DIM, 'PAN        ')}  {c(YELLOW, '⚠  PAN_API_KEY not set — fail-open')}")
    print(f"  {c(DIM, 'Claude     ')}  {c(GREEN, f'●  {claude.model}')}")
    hr()
    print(c(BOLD, "  Session"))
    hr()
    print(f"  {c(DIM, 'Session ID ')}  {c(MAGENTA, session_id[:8])}  {c(DIM, f'({session_id})')}")
    mode_label = (
        c(MAGENTA, "full_history  📋  PAN inspects entire conversation")
        if inspect_mode == "full_history"
        else c(WHITE,   "prompt_only   💬  PAN inspects latest message only")
    )
    print(f"  {c(DIM, 'PAN Mode   ')}  {mode_label}")
    print(c(DIM, "             Use /mode to toggle"))
    hr()
    print()

def print_session_header(session_id: str, inspect_mode: str):
    short = session_id[:8]
    mode  = (c(MAGENTA, "full_history") if inspect_mode == "full_history"
             else c(WHITE, "prompt_only"))
    print()
    print(c(DIM, f"  ┌─ Session: {c(MAGENTA, short)}  │  PAN mode: {mode}"))
    print(c(DIM,  "  │  Type /help for commands, /new to start a fresh session"))
    print(c(DIM,  "  └" + "─" * 50))
    print()

def wrap_response(text: str, width: int = 72, indent: str = "  ") -> str:
    """Word-wrap Claude's response for the terminal."""
    lines = text.split("\n")
    wrapped = []
    for line in lines:
        if len(line) <= width:
            wrapped.append(indent + line)
        else:
            wrapped.extend(
                textwrap.wrap(line, width=width, initial_indent=indent,
                              subsequent_indent=indent)
            )
    return "\n".join(wrapped)

async def run():
    # ── Init clients ──────────────────────────────────────────────────────
    try:
        claude = ClaudeClient()
    except RuntimeError as e:
        print(c(RED, f"\n  ✕  {e}\n"))
        sys.exit(1)

    pan = PANClient()

    # Test PAN once at startup
    if pan.enabled:
        print(c(DIM, "\n  Checking PAN connection…"), end="", flush=True)
        ok, msg = await pan.test_connection()
        if ok:
            print(c(GREEN, f"  ✓  Connected ({pan.base_url})"))
        else:
            print(c(YELLOW, f"  ⚠  {msg}  (fail-open)"))
    else:
        print(c(YELLOW, "\n  ⚠  PAN_API_KEY not set — inspection disabled (fail-open)"))

    banner()

    # ── Session state ──────────────────────────────────────────────────────
    history:       list[Message] = []
    session_id:    str = str(uuid.uuid4())
    inspect_mode:  str = "prompt_only"   # prompt_only | full_history
    scan_stats:    dict = {"allow": 0, "block": 0, "skip": 0}

    print_session_header(session_id, inspect_mode)

    # ── REPL ───────────────────────────────────────────────────────────────
    while True:
        try:
            user_input = input(c(BOLD + CYAN, "  You › ") + RESET).strip()
        except (EOFError, KeyboardInterrupt):
            print(c(DIM, "\n\n  Goodbye!\n"))
            break

        if not user_input:
            continue

        # ── Commands ──
        cmd = user_input.lower()

        if cmd in ("/quit", "/exit", "/q"):
            print(c(DIM, "\n  Goodbye!\n"))
            break

        if cmd == "/help":
            print_help()
            continue

        if cmd == "/clear":
            os.system("clear" if os.name == "posix" else "cls")
            print_session_header(session_id, inspect_mode)
            continue

        if cmd == "/status":
            print_status(pan, claude, inspect_mode, session_id)
            continue

        if cmd in ("/new", "/session"):
            history    = []
            session_id = str(uuid.uuid4())
            short      = session_id[:8]
            print()
            print(c(BOLD + MAGENTA, f"  🔄  New session started  —  ID: {short}"))
            print(c(DIM,             "  Conversation history cleared."))
            print_session_header(session_id, inspect_mode)
            continue

        if cmd in ("/mode", "/toggle"):
            if inspect_mode == "prompt_only":
                inspect_mode = "full_history"
                print(c(MAGENTA, "\n  📋  Mode → full_history  "
                                 "(PAN inspects the entire conversation)\n"))
            else:
                inspect_mode = "prompt_only"
                print(c(WHITE,   "\n  💬  Mode → prompt_only  "
                                 "(PAN inspects only the latest message)\n"))
            continue

        if cmd == "/history":
            print()
            hr()
            print(c(BOLD, "  Conversation history"))
            hr()
            if not history:
                print(c(DIM, "  (empty)"))
            for i, m in enumerate(history, 1):
                role_str = (c(CYAN, "You    ") if m.role == Role.user
                            else c(BLUE, "Claude "))
                preview  = m.content[:120].replace("\n", " ")
                if len(m.content) > 120:
                    preview += "…"
                print(f"  {c(DIM, str(i)+'.')}  {role_str}  {preview}")
            hr()
            print()
            continue

        # ── Regular message ──────────────────────────────────────────────
        history.append(Message(role=Role.user, content=user_input))

        # Build PAN scan text
        if inspect_mode == "full_history":
            pan_text = "\n".join(
                f"[{m.role.value}]: {m.content}" for m in history
            )
        else:
            pan_text = user_input

        # Step 1: PAN scan
        print(c(DIM, "\n  Scanning with PAN AIRS…"), end="", flush=True)
        scan = await pan.scan_prompt(
            prompt=pan_text,
            conversation_id=session_id,
        )

        # Tally stats
        if not scan.was_scanned:
            scan_stats["skip"] += 1
        elif scan.verdict == PANVerdict.block:
            scan_stats["block"] += 1
        else:
            scan_stats["allow"] += 1

        print("\r" + " " * 40 + "\r", end="")  # clear "Scanning…" line

        print_scan_result(scan, inspect_mode)

        if scan.verdict == PANVerdict.block:
            print(c(BOLD + RED, "  🚫  Prompt blocked by PAN security policy."))
            if scan.category:
                print(c(RED, f"  Category: {scan.category}"))
            print()
            # Remove the blocked message from history so it doesn't cascade
            history.pop()
            continue

        # Step 2: Claude
        print(c(DIM, "  Claude is thinking…"), end="", flush=True)
        try:
            response_text = await claude.chat(
                messages=history,
                max_tokens=4096,
            )
        except Exception as e:
            print("\r" + " " * 40 + "\r", end="")
            print(c(RED, f"\n  ✕  Claude error: {e}\n"))
            history.pop()
            continue

        print("\r" + " " * 40 + "\r", end="")  # clear "thinking…" line

        # Save assistant turn
        history.append(Message(role=Role.assistant, content=response_text))

        # Print response
        print(c(BOLD + BLUE, "  Claude ›"))
        print()
        print(wrap_response(response_text))
        print()

        # Mini stats line
        short   = session_id[:8]
        total   = sum(scan_stats.values())
        s_allow = c(GREEN,  f"✓{scan_stats['allow']}")
        s_block = c(RED,    f"✕{scan_stats['block']}")
        s_skip  = c(YELLOW, f"⚠{scan_stats['skip']}")
        print(c(DIM, f"  [{short}]  Scans this session: {total}  "
                     f"({s_allow}  {s_block}  {s_skip}{c(DIM, ')  ')}"))
        print()


if __name__ == "__main__":
    asyncio.run(run())
