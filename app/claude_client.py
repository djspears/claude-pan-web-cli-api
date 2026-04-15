"""
Anthropic Claude client wrapper.

Environment variables:
  ANTHROPIC_API_KEY - Your Anthropic API key
  CLAUDE_MODEL      - Model to use (default: claude-haiku-4-5)

Note: adaptive thinking is only supported on claude-opus-4-6 and claude-sonnet-4-6.
      It is automatically enabled for those models and skipped for all others.
"""

import os
import logging
from typing import List, Optional
import anthropic
from models import Message

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")

# Models that support adaptive thinking
THINKING_MODELS = {"claude-opus-4-6", "claude-sonnet-4-6"}


class ClaudeClient:
    def __init__(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = CLAUDE_MODEL

    async def chat(
        self,
        messages: List[Message],
        system: Optional[str] = None,
        max_tokens: int = 16000,
    ) -> str:
        """Send messages to Claude and return the text response."""
        api_messages = [{"role": m.role.value, "content": m.content} for m in messages]

        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": api_messages,
        }

        # Only enable adaptive thinking on supported models
        if self.model in THINKING_MODELS:
            kwargs["thinking"] = {"type": "adaptive"}

        if system:
            kwargs["system"] = system

        response = await self.client.messages.create(**kwargs)

        text_parts = [block.text for block in response.content if block.type == "text"]
        return "\n".join(text_parts)
