"""
ClawBot Credential Manager — iOS Credential Request Bridge

Requests credentials from the iOS app via the gateway WebSocket protocol.
When the agent hits a login wall during browser automation, this module
sends a ``credential/request`` event and blocks until the iOS app responds
with credentials from its Keychain, or the request times out.

Security:
  - NEVER logs credential values (usernames, passwords)
  - Logs only domain name and credential count
  - Callers MUST nil credential references immediately after use
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CredentialManager:
    """Request credentials from iOS via gateway WebSocket.

    Usage::

        manager = CredentialManager(gateway_client=gateway)
        creds = await manager.request_credentials("accounts.google.com", "Login for flights")
        if creds:
            username, password = creds[0]["username"], creds[0]["password"]
            # ... inject into browser ...
            creds = None  # nil reference immediately
    """

    def __init__(self, gateway_client: Any = None) -> None:
        self._gateway = gateway_client

    def set_gateway_client(self, client: Any) -> None:
        """Post-init wiring (gateway created after tools).

        Follows the same pattern as CreateCardTool and RequestApprovalTool.
        """
        self._gateway = client

    async def request_credentials(
        self,
        domain: str,
        reason: str,
        timeout: float = 30.0,
    ) -> list[dict[str, str]] | None:
        """Request credentials from the iOS user for the given domain.

        Sends a ``credential/request`` event via the gateway and blocks
        until the iOS app responds or the timeout expires (default 30s,
        matching the gateway's ``CREDENTIAL_TIMEOUT_MS``).

        Args:
            domain: The domain needing authentication (e.g., "accounts.google.com").
            reason: Human-readable reason shown to user on iOS
                (e.g., "Login required for flight search on United.com").
            timeout: Seconds to wait before giving up.

        Returns:
            List of ``{"username": str, "password": str}`` dicts on success.
            ``None`` if user denied, no credentials available, or timeout.

        SECURITY: Return value contains plaintext credentials.
        Callers MUST nil the reference immediately after use.
        """
        if self._gateway is None:
            logger.warning(
                "CredentialManager: no gateway client, cannot request credentials"
            )
            return None

        try:
            result = await self._gateway.request_credentials(
                domain, reason, timeout,
            )
        except Exception as e:
            logger.warning(
                "Credential request failed for domain=%s: %s",
                domain, type(e).__name__,
            )
            return None

        if result is None:
            return None

        credentials = result.get("credentials")
        if not credentials or not isinstance(credentials, list):
            return None

        # Log only that credentials were received, never the values
        logger.info(
            "Credentials received for domain=%s count=%d",
            domain, len(credentials),
        )
        return credentials
