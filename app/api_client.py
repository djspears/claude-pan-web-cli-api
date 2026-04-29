"""
Python client for the Claude + PAN AI Security proxy API.

Used for programmatic access, testing, and red teaming operations.

Example usage:

    from api_client import ClaudePANClient

    client = ClaudePANClient("http://127.0.0.1:8080")

    # Check health
    health = await client.health()
    print(f"PAN status: {health['pan_status']}")

    # Send a single message
    response = await client.chat("What is SQL injection?")
    print(f"Response: {response['response']}")
    print(f"PAN verdict: {response['pan']['verdict']}")

    # Multi-turn conversation
    session_id = "test-session-001"
    resp1 = await client.chat("Hello", session_id=session_id)
    resp2 = await client.chat("Tell me about prompt injection", session_id=session_id)
"""

import httpx
from typing import Optional, List, Dict, Any, Literal
import uuid


class ClaudePANClient:
    """Client for interacting with the Claude + PAN AI Security proxy."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        timeout: float = 120.0,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the client.

        Args:
            base_url: Base URL of the proxy service
            timeout: Request timeout in seconds (default: 120s for LLM responses)
            headers: Optional additional headers (e.g., X-User-ID for tracking)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = headers or {}

    async def health(self) -> Dict[str, Any]:
        """
        Check service health and PAN connection status.

        Returns:
            Health response with PAN status, model info, etc.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/health", headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 16000,
        pan_inspect_mode: Literal["prompt_only", "full_history"] = "prompt_only",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a message to Claude via the PAN-protected proxy.

        Args:
            message: The user message/prompt to send
            session_id: Optional session ID for multi-turn conversations
            system: Optional system prompt
            max_tokens: Maximum tokens in response (default: 16000)
            pan_inspect_mode: "prompt_only" (default) or "full_history"
            conversation_history: Optional list of prior messages [{"role": "user"|"assistant", "content": "..."}]
            user_id: Optional user ID for PAN tracking (sent as X-User-ID header)

        Returns:
            Response dict with:
                - response: str (Claude's response text)
                - model: str (model used)
                - pan: dict (PAN scan details: was_scanned, verdict, scan_id, category, etc.)
        """
        # Build message history
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        payload = {
            "messages": messages,
            "pan_inspect_mode": pan_inspect_mode,
        }

        if session_id:
            payload["session_id"] = session_id
        if system:
            payload["system"] = system
        if max_tokens:
            payload["max_tokens"] = max_tokens

        headers = self.headers.copy()
        if user_id:
            headers["X-User-ID"] = user_id

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def chat_with_history(
        self,
        messages: List[Dict[str, str]],
        session_id: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 16000,
        pan_inspect_mode: Literal["prompt_only", "full_history"] = "prompt_only",
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a full conversation history directly.

        Args:
            messages: List of message dicts with "role" and "content" keys
            session_id: Optional session ID
            system: Optional system prompt
            max_tokens: Maximum tokens in response
            pan_inspect_mode: "prompt_only" or "full_history"
            user_id: Optional user ID for PAN tracking

        Returns:
            Response dict (same format as chat())
        """
        payload = {
            "messages": messages,
            "pan_inspect_mode": pan_inspect_mode,
        }

        if session_id:
            payload["session_id"] = session_id
        if system:
            payload["system"] = system
        if max_tokens:
            payload["max_tokens"] = max_tokens

        headers = self.headers.copy()
        if user_id:
            headers["X-User-ID"] = user_id

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()


class ConversationSession:
    """
    Helper class for managing multi-turn conversations.

    Example:
        async with ConversationSession(client) as session:
            r1 = await session.send("Hello")
            r2 = await session.send("What is prompt injection?")
            print(session.get_history())
    """

    def __init__(
        self,
        client: ClaudePANClient,
        session_id: Optional[str] = None,
        system: Optional[str] = None,
        pan_inspect_mode: Literal["prompt_only", "full_history"] = "prompt_only",
        user_id: Optional[str] = None,
    ):
        self.client = client
        self.session_id = session_id or str(uuid.uuid4())
        self.system = system
        self.pan_inspect_mode = pan_inspect_mode
        self.user_id = user_id
        self.history: List[Dict[str, str]] = []
        self.scan_results: List[Dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def send(self, message: str, max_tokens: int = 16000) -> Dict[str, Any]:
        """Send a message in this conversation session."""
        response = await self.client.chat(
            message=message,
            session_id=self.session_id,
            system=self.system,
            max_tokens=max_tokens,
            pan_inspect_mode=self.pan_inspect_mode,
            conversation_history=self.history.copy(),
            user_id=self.user_id,
        )

        # Update history
        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": response["response"]})

        # Track scan results
        self.scan_results.append({
            "prompt": message,
            "pan": response["pan"],
        })

        return response

    def get_history(self) -> List[Dict[str, str]]:
        """Get the full conversation history."""
        return self.history.copy()

    def get_scan_results(self) -> List[Dict[str, Any]]:
        """Get all PAN scan results from this session."""
        return self.scan_results.copy()

    def clear(self):
        """Clear the conversation history."""
        self.history = []
        self.scan_results = []
