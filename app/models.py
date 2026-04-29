from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from enum import Enum


class Role(str, Enum):
    user = "user"
    assistant = "assistant"


class Message(BaseModel):
    role: Role
    content: str


class PANInspectMode(str, Enum):
    prompt_only   = "prompt_only"    # Send only the latest user message to PAN (default)
    full_history  = "full_history"   # Send the entire conversation history to PAN


class ChatRequest(BaseModel):
    messages: List[Message]
    system: Optional[str] = None
    max_tokens: Optional[int] = 16000
    stream: Optional[bool] = False
    pan_inspect_mode: PANInspectMode = PANInspectMode.prompt_only
    session_id: Optional[str] = None


class PANVerdict(str, Enum):
    allow = "allow"
    block = "block"


class PANScanResult(BaseModel):
    scan_id: Optional[str] = None
    verdict: PANVerdict
    category: Optional[str] = None
    action: Optional[str] = None
    reason: Optional[str] = None
    # Whether the request actually reached PAN (False = fail-open / skipped)
    was_scanned: bool = False
    # Raw response body from PAN for debugging
    raw_response: Optional[Dict[str, Any]] = None
    # Any error detail if the call failed
    error: Optional[str] = None


class PANDetails(BaseModel):
    """Surfaced in ChatResponse so the UI can show full scan context."""
    was_scanned: bool
    verdict: str
    scan_id: Optional[str] = None
    category: Optional[str] = None
    reason: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    response: str
    model: str
    pan: PANDetails


class PANConnectionStatus(str, Enum):
    connected = "connected"
    disabled = "disabled"
    error = "error"


class HealthResponse(BaseModel):
    status: str
    pan_configured: bool
    claude_configured: bool
    model: Optional[str] = None
    pan_status: PANConnectionStatus = PANConnectionStatus.disabled
    pan_url: Optional[str] = None
    pan_profile: Optional[str] = None
    pan_profile_id: Optional[str] = None
    pan_app_name: Optional[str] = None
    pan_error: Optional[str] = None
