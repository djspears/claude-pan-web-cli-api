"""
Claude + Palo Alto Networks AI Security proxy service.

Request flow:
  1. Client sends prompt to POST /chat
  2. Prompt is scanned by PAN AI Runtime Security
  3. If approved, prompt is forwarded to Claude
  4. Claude's response is optionally scanned by PAN
  5. Full scan details are returned alongside the response

NOTE: PAN connectivity is tested ONCE at startup and the result is cached.
      The /health endpoint returns the cached status — it never calls PAN,
      so Docker health checks do not generate spurious AIRS log entries.
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from typing import Optional
from claude_client import ClaudeClient
from models import (
    ChatRequest, ChatResponse, HealthResponse,
    PANConnectionStatus, PANDetails, PANInspectMode, PANVerdict,
)
from pan_client import PANClient

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SCAN_RESPONSES = os.getenv("PAN_SCAN_RESPONSES", "false").lower() == "true"

claude: Optional[ClaudeClient] = None
pan: Optional[PANClient] = None

# Cached at startup — never re-tested on health checks
_pan_status: PANConnectionStatus = PANConnectionStatus.disabled
_pan_error:  Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global claude, pan, _pan_status, _pan_error

    # ── Init Claude ──
    pan = PANClient()
    try:
        claude = ClaudeClient()
        logger.info("Claude client initialized (model=%s)", claude.model)
    except RuntimeError as exc:
        logger.error("Failed to initialize Claude client: %s", exc)
        claude = None

    # ── Test PAN once at startup, cache result ──
    if pan.enabled:
        ok, msg = await pan.test_connection()
        if ok:
            _pan_status = PANConnectionStatus.connected
            _pan_error  = None
            logger.info("PAN connection OK — %s (profile=%s)", msg, pan.profile_name)
        else:
            _pan_status = PANConnectionStatus.error
            _pan_error  = msg
            logger.warning("PAN connection FAILED — %s", msg)
    else:
        _pan_status = PANConnectionStatus.disabled
        _pan_error  = None
        logger.warning("PAN inspection DISABLED — set PAN_API_KEY to enable")

    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Claude + PAN AI Security Proxy",
    description="Forwards prompts to Claude after inspection by Palo Alto Networks AI Runtime Security.",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/health", response_model=HealthResponse)
async def health():
    """
    Returns cached PAN connection status from startup.
    Does NOT call the PAN API — prevents Docker health checks
    from flooding Prisma AIRS logs with 'connection test' entries.
    """
    return HealthResponse(
        status="ok",
        pan_configured=bool(pan and pan.enabled),
        claude_configured=bool(claude),
        model=claude.model if claude else None,
        pan_status=_pan_status,
        pan_url=pan.base_url if pan else None,
        pan_profile=pan.profile_name if pan else None,
        pan_profile_id=pan.profile_id if pan else None,
        pan_app_name=pan.app_name if pan else None,
        pan_error=_pan_error,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest):
    if not claude:
        raise HTTPException(
            status_code=503,
            detail="Claude client not configured — check ANTHROPIC_API_KEY",
        )

    # Use session_id from client if provided, otherwise generate one
    conversation_id = body.session_id or str(uuid.uuid4())
    user_id = request.headers.get("X-User-ID")

    # Build the text sent to PAN based on the inspect mode
    if body.pan_inspect_mode == PANInspectMode.full_history:
        # Send full conversation so PAN can detect multi-turn attacks
        prompt_text = "\n".join(
            f"[{m.role.value}]: {m.content}" for m in body.messages
        )
        logger.info(
            "PAN inspect mode=full_history (%d messages, session=%s)",
            len(body.messages), conversation_id,
        )
    else:
        # Send only the latest user message — prevents blocked history cascading
        last_user = next(
            (m.content for m in reversed(body.messages) if m.role.value == "user"),
            "",
        )
        prompt_text = last_user
        logger.info(
            "PAN inspect mode=prompt_only (session=%s)", conversation_id,
        )

    # ── Step 1: PAN prompt inspection ──────────────────────────────────────
    logger.info("Scanning prompt (conversation_id=%s)", conversation_id)
    scan_result = await pan.scan_prompt(
        prompt=prompt_text,
        user_id=user_id,
        conversation_id=conversation_id,
    )

    if scan_result.verdict == PANVerdict.block:
        logger.warning(
            "Prompt BLOCKED by PAN (scan_id=%s category=%s reason=%s)",
            scan_result.scan_id, scan_result.category, scan_result.reason,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "prompt_blocked",
                "message": "Your prompt was blocked by the security policy.",
                "category": scan_result.category,
                "scan_id": scan_result.scan_id,
                "pan": {
                    "was_scanned":  scan_result.was_scanned,
                    "verdict":      scan_result.verdict,
                    "scan_id":      scan_result.scan_id,
                    "category":     scan_result.category,
                    "reason":       scan_result.reason,
                    "error":        scan_result.error,
                    "raw_response": scan_result.raw_response,
                },
            },
        )

    logger.info(
        "Prompt %s by PAN (was_scanned=%s scan_id=%s)",
        "APPROVED" if scan_result.was_scanned else "PASSED-THROUGH (fail-open)",
        scan_result.was_scanned,
        scan_result.scan_id,
    )

    # ── Step 2: Forward to Claude ───────────────────────────────────────────
    if body.system:
        logger.info("Using system prompt (length=%d chars)", len(body.system))
    try:
        response_text = await claude.chat(
            messages=body.messages,
            system=body.system,
            max_tokens=body.max_tokens or 16000,
        )
    except Exception as exc:
        logger.error("Claude API error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc

    # ── Step 3: Optionally scan Claude's response ───────────────────────────
    if SCAN_RESPONSES:
        resp_scan = await pan.scan_response(
            response_text=response_text,
            scan_id=scan_result.scan_id,
        )
        if resp_scan.verdict == PANVerdict.block:
            logger.warning(
                "Response BLOCKED by PAN (scan_id=%s category=%s)",
                resp_scan.scan_id, resp_scan.category,
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "error":    "response_blocked",
                    "message":  "The model response was blocked by the security policy.",
                    "category": resp_scan.category,
                    "scan_id":  resp_scan.scan_id,
                },
            )

    return ChatResponse(
        response=response_text,
        model=claude.model,
        pan=PANDetails(
            was_scanned=scan_result.was_scanned,
            verdict=scan_result.verdict.value,
            scan_id=scan_result.scan_id,
            category=scan_result.category,
            reason=scan_result.reason,
            error=scan_result.error,
            raw_response=scan_result.raw_response,
        ),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
