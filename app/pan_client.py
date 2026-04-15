"""
Palo Alto Networks AI Runtime Security (AIRS) client.

Inspects prompts via the PAN AI Security API before forwarding to Claude.
Docs: https://pan.dev/ai-runtime-security/api/

Correct AIRS API payload format:
  POST /v1/scan/sync/request
  {
    "tr_id": "unique-id",
    "profile": { "name": "profile-name" },
    "metadata": { "app_name": "...", "ai_model": "..." },
    "contents": [ { "prompt": "user text" } ]
  }

Environment variables:
  PAN_API_KEY      - Your PAN AI Security API key
  PAN_API_URL      - Base URL e.g. https://service.api.aisecurity.paloaltonetworks.com
  PAN_APP_NAME     - Application name tag (default: claude-proxy)
  PAN_PROFILE_NAME - Security profile name (must exist in your PAN tenant)
"""

import os
import logging
import uuid
import httpx
from typing import Optional, Tuple
from models import PANScanResult, PANVerdict

logger = logging.getLogger(__name__)

PAN_API_KEY      = os.getenv("PAN_API_KEY", "")
PAN_API_URL      = os.getenv("PAN_API_URL", "https://service.api.aisecurity.paloaltonetworks.com").rstrip("/")
PAN_APP_NAME     = os.getenv("PAN_APP_NAME", "claude-proxy")
PAN_PROFILE_NAME = os.getenv("PAN_PROFILE_NAME", "default")
PAN_TIMEOUT      = float(os.getenv("PAN_TIMEOUT", "10"))


class PANClient:
    """Client for Palo Alto Networks AI Runtime Security prompt scanning."""

    def __init__(self) -> None:
        self.api_key      = PAN_API_KEY
        self.base_url     = PAN_API_URL
        self.app_name     = PAN_APP_NAME
        self.profile_name = PAN_PROFILE_NAME
        self.enabled      = bool(self.api_key)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-pan-token": self.api_key,
        }

    def _prompt_payload(self, prompt: str, tr_id: str, extra_meta: Optional[dict] = None) -> dict:
        """Build a correctly structured AIRS prompt scan payload."""
        metadata = {
            "app_name": self.app_name,
            "ai_model": "claude-haiku-4-5",
        }
        if extra_meta:
            metadata.update(extra_meta)

        return {
            "tr_id": tr_id,
            "profile": {"name": self.profile_name},
            "metadata": metadata,
            "contents": [{"prompt": prompt}],
        }

    def _response_payload(self, response_text: str, tr_id: str, extra_meta: Optional[dict] = None) -> dict:
        """Build a correctly structured AIRS response scan payload."""
        metadata = {
            "app_name": self.app_name,
            "ai_model": "claude-haiku-4-5",
        }
        if extra_meta:
            metadata.update(extra_meta)

        return {
            "tr_id": tr_id,
            "profile": {"name": self.profile_name},
            "metadata": metadata,
            "contents": [{"response": response_text}],
        }

    def _parse_response(self, data: dict) -> Tuple[PANVerdict, Optional[str]]:
        """Extract verdict and action from an AIRS scan response."""
        action  = data.get("action", "allow").lower()
        verdict = PANVerdict.block if action == "block" else PANVerdict.allow
        return verdict, action

    async def test_connection(self) -> tuple[bool, str]:
        """
        Lightweight connectivity check using a minimal scan payload.
        Returns (success: bool, message: str).
        """
        if not self.enabled:
            return False, "PAN_API_KEY is not set"

        payload = self._prompt_payload("connection test", tr_id="test-conn-001")
        url = f"{self.base_url}/v1/scan/sync/request"

        try:
            async with httpx.AsyncClient(timeout=PAN_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                if resp.status_code == 401:
                    return False, "Authentication failed — check PAN_API_KEY"
                if resp.status_code == 403:
                    return False, "Forbidden — API key lacks permission or profile not found"
                if resp.status_code == 400:
                    return False, f"Bad request — {resp.text[:200]}"
                resp.raise_for_status()
                return True, f"Connected (HTTP {resp.status_code})"

        except httpx.ConnectError:
            return False, f"Cannot reach {self.base_url} — check PAN_API_URL"
        except httpx.TimeoutException:
            return False, f"Connection timed out after {PAN_TIMEOUT}s"
        except httpx.HTTPStatusError as exc:
            return False, f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        except Exception as exc:
            return False, f"Unexpected error: {exc}"

    async def scan_prompt(
        self,
        prompt: str,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> PANScanResult:
        """
        Send a prompt to PAN AIRS for inspection.
        Returns PANScanResult. was_scanned=True means PAN actually processed it.
        """
        if not self.enabled:
            logger.warning("PAN_API_KEY not set — skipping prompt inspection (fail-open)")
            return PANScanResult(
                verdict=PANVerdict.allow,
                was_scanned=False,
                reason="PAN_API_KEY not configured — inspection skipped",
            )

        tr_id = str(uuid.uuid4())
        extra_meta: dict = {}
        if user_id:
            extra_meta["user_id"] = user_id
        if conversation_id:
            extra_meta["conversation_id"] = conversation_id

        payload = self._prompt_payload(prompt, tr_id=tr_id, extra_meta=extra_meta or None)
        url = f"{self.base_url}/v1/scan/sync/request"

        logger.debug("PAN prompt scan payload: %s", payload)

        try:
            async with httpx.AsyncClient(timeout=PAN_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                logger.debug("PAN raw response [%s]: %s", resp.status_code, resp.text)
                resp.raise_for_status()
                data = resp.json()

            verdict, action = self._parse_response(data)

            logger.info(
                "PAN scan complete — verdict=%s scan_id=%s category=%s tr_id=%s",
                verdict, data.get("scan_id"), data.get("category"), tr_id,
            )

            return PANScanResult(
                scan_id=data.get("scan_id"),
                verdict=verdict,
                category=data.get("category"),
                action=action,
                reason=data.get("reason"),
                was_scanned=True,
                raw_response=data,
            )

        except httpx.HTTPStatusError as exc:
            msg = f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            logger.error("PAN API error: %s", msg)
            return PANScanResult(
                verdict=PANVerdict.allow,
                was_scanned=False,
                reason="PAN API returned an error — fail-open",
                error=msg,
            )

        except httpx.RequestError as exc:
            msg = f"Connection error: {exc}"
            logger.error("PAN unreachable: %s", msg)
            return PANScanResult(
                verdict=PANVerdict.allow,
                was_scanned=False,
                reason="PAN API unreachable — fail-open",
                error=msg,
            )

    async def scan_response(
        self,
        response_text: str,
        scan_id: Optional[str] = None,
    ) -> PANScanResult:
        """Optionally scan Claude's response for data exfiltration / sensitive output."""
        if not self.enabled:
            return PANScanResult(
                verdict=PANVerdict.allow,
                was_scanned=False,
                reason="PAN_API_KEY not configured — inspection skipped",
            )

        tr_id = str(uuid.uuid4())
        extra_meta = {"prompt_scan_id": scan_id} if scan_id else None
        payload = self._response_payload(response_text, tr_id=tr_id, extra_meta=extra_meta)
        url = f"{self.base_url}/v1/scan/sync/request"

        try:
            async with httpx.AsyncClient(timeout=PAN_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()

            verdict, action = self._parse_response(data)

            return PANScanResult(
                scan_id=data.get("scan_id"),
                verdict=verdict,
                category=data.get("category"),
                action=action,
                reason=data.get("reason"),
                was_scanned=True,
                raw_response=data,
            )

        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            msg = str(exc)
            logger.error("PAN response scan error: %s", msg)
            return PANScanResult(
                verdict=PANVerdict.allow,
                was_scanned=False,
                reason="PAN response scan failed — fail-open",
                error=msg,
            )
