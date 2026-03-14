"""
Tests for CredentialManager — iOS credential request bridge.

Covers:
- Gateway returns credentials → manager returns them
- Gateway returns None (user denied) → manager returns None
- Gateway timeout → None
- No gateway → None
- Gateway exception → None
- set_gateway_client wiring
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from server.agent.tools.credential_manager import CredentialManager


# ── Helpers ──────────────────────────────────────────────────


def _make_gateway(result: dict | None = None, side_effect: Exception | None = None) -> AsyncMock:
    """Create a mock gateway with a request_credentials method."""
    gateway = AsyncMock()
    if side_effect:
        gateway.request_credentials = AsyncMock(side_effect=side_effect)
    else:
        gateway.request_credentials = AsyncMock(return_value=result)
    return gateway


# ── Tests ────────────────────────────────────────────────────


class TestCredentialManager:

    @pytest.mark.asyncio
    async def test_request_credentials_success(self):
        """Gateway returns credentials — manager returns them."""
        payload = {
            "requestId": "abc",
            "domain": "example.com",
            "credentials": [
                {"username": "user@test.com", "password": "secret"},
            ],
        }
        gateway = _make_gateway(result=payload)
        manager = CredentialManager(gateway_client=gateway)

        creds = await manager.request_credentials("example.com", "Login needed")
        assert creds is not None
        assert len(creds) == 1
        assert creds[0]["username"] == "user@test.com"
        assert creds[0]["password"] == "secret"
        gateway.request_credentials.assert_awaited_once_with(
            "example.com", "Login needed", 30.0,
        )

    @pytest.mark.asyncio
    async def test_request_credentials_none_response(self):
        """Gateway returns None (user denied / no creds) → manager returns None."""
        gateway = _make_gateway(result=None)
        manager = CredentialManager(gateway_client=gateway)

        creds = await manager.request_credentials("example.com", "Login needed")
        assert creds is None

    @pytest.mark.asyncio
    async def test_request_credentials_empty_list(self):
        """Gateway returns empty credentials list → None."""
        payload = {"requestId": "abc", "domain": "example.com", "credentials": []}
        gateway = _make_gateway(result=payload)
        manager = CredentialManager(gateway_client=gateway)

        creds = await manager.request_credentials("example.com", "Login needed")
        assert creds is None

    @pytest.mark.asyncio
    async def test_request_credentials_no_gateway(self):
        """No gateway wired → returns None."""
        manager = CredentialManager(gateway_client=None)
        creds = await manager.request_credentials("example.com", "Login needed")
        assert creds is None

    @pytest.mark.asyncio
    async def test_request_credentials_exception(self):
        """Gateway raises exception → returns None."""
        gateway = _make_gateway(side_effect=ConnectionError("lost"))
        manager = CredentialManager(gateway_client=gateway)

        creds = await manager.request_credentials("example.com", "Login needed")
        assert creds is None

    @pytest.mark.asyncio
    async def test_request_credentials_custom_timeout(self):
        """Custom timeout is passed through to gateway."""
        gateway = _make_gateway(result=None)
        manager = CredentialManager(gateway_client=gateway)

        await manager.request_credentials("example.com", "reason", timeout=5.0)
        gateway.request_credentials.assert_awaited_once_with(
            "example.com", "reason", 5.0,
        )

    @pytest.mark.asyncio
    async def test_set_gateway_client_wiring(self):
        """set_gateway_client allows post-init wiring."""
        manager = CredentialManager()  # no gateway initially
        assert await manager.request_credentials("x.com", "reason") is None

        payload = {
            "requestId": "abc",
            "domain": "x.com",
            "credentials": [{"username": "u", "password": "p"}],
        }
        gateway = _make_gateway(result=payload)
        manager.set_gateway_client(gateway)

        creds = await manager.request_credentials("x.com", "reason")
        assert creds is not None
        assert len(creds) == 1

    @pytest.mark.asyncio
    async def test_request_credentials_invalid_format(self):
        """Gateway returns result with invalid credentials format → None."""
        payload = {"requestId": "abc", "domain": "x.com", "credentials": "not-a-list"}
        gateway = _make_gateway(result=payload)
        manager = CredentialManager(gateway_client=gateway)

        creds = await manager.request_credentials("x.com", "reason")
        assert creds is None
