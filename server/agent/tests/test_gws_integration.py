"""Real-token integration tests for gws CLI.

These tests hit live Google APIs and require:
  - gws binary installed (run inside agent container)
  - CLAWBOT_TEST_GOOGLE_TOKEN env var set to a valid OAuth access token

Run inside container:
    docker exec clawbot-agent pytest /app/server/agent/tests/test_gws_integration.py -v

Run only @integration tests:
    docker exec -e CLAWBOT_TEST_GOOGLE_TOKEN=ya29.xxx clawbot-agent \
        pytest /app/server/agent/tests/test_gws_integration.py -v -m integration
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

# ── Skip markers ─────────────────────────────────────────────

SKIP_NO_GWS = pytest.mark.skipif(
    shutil.which("gws") is None,
    reason="gws CLI not installed (run inside agent container)",
)

SKIP_NO_TOKEN = pytest.mark.skipif(
    not os.environ.get("CLAWBOT_TEST_GOOGLE_TOKEN"),
    reason="CLAWBOT_TEST_GOOGLE_TOKEN not set — skip live API tests",
)

integration = pytest.mark.integration


# ── Helpers ──────────────────────────────────────────────────

def _gws_env() -> dict[str, str]:
    """Subprocess env with GOOGLE_WORKSPACE_CLI_TOKEN from test env var."""
    token = os.environ.get("CLAWBOT_TEST_GOOGLE_TOKEN", "")
    return {**os.environ, "GOOGLE_WORKSPACE_CLI_TOKEN": token}


def _run_gws(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a gws command and return the completed process."""
    return subprocess.run(
        ["gws", *args],
        capture_output=True,
        text=True,
        env=env or _gws_env(),
        timeout=60,
    )


def _delete_drive_file(file_id: str) -> None:
    """Delete a Drive file by ID (cleanup helper)."""
    result = _run_gws([
        "drive", "files", "delete",
        "--params", json.dumps({"fileId": file_id}),
    ])
    if result.returncode != 0:
        print(f"Cleanup warning: failed to delete {file_id}: {result.stderr}")


# ── Enhanced 1b: Dry-run and security tests ──────────────────


@SKIP_NO_GWS
class TestGwsDryRun:
    """Tests that work with --dry-run (no real API calls, but need gws binary)."""

    def test_dry_run_authorization_header(self):
        """Dry-run output includes Authorization header with the token."""
        token = "test-token-for-header-check"
        env = {**os.environ, "GOOGLE_WORKSPACE_CLI_TOKEN": token}

        result = _run_gws([
            "drive", "files", "list",
            "--params", '{"pageSize":1}',
            "--dry-run",
        ], env=env)

        assert result.returncode == 0, f"dry-run failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert output.get("dry_run") is True

        # Authorization header should contain the token
        headers = output.get("headers", {})
        auth_header = headers.get("Authorization", "")
        assert f"Bearer {token}" in auth_header, (
            f"Expected 'Bearer {token}' in Authorization header, got: {auth_header}"
        )

    def test_token_not_in_stderr(self):
        """Token value does not leak into stderr output."""
        token = "ya29.sensitive-token-value-xyz"
        env = {**os.environ, "GOOGLE_WORKSPACE_CLI_TOKEN": token}

        result = _run_gws([
            "drive", "files", "list",
            "--params", '{"pageSize":1}',
            "--dry-run",
        ], env=env)

        assert result.returncode == 0
        # Token must not appear in stderr (log output)
        assert token not in result.stderr, (
            f"Token leaked in stderr: {result.stderr}"
        )


# ── 1c-1g: Live API tests ────────────────────────────────────


@SKIP_NO_GWS
@SKIP_NO_TOKEN
@integration
class TestGwsDriveList:
    """1c: List Drive files."""

    def test_drive_files_list(self):
        result = _run_gws([
            "drive", "files", "list",
            "--params", json.dumps({"pageSize": 1}),
        ])

        assert result.returncode == 0, f"gws drive list failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert "files" in data, f"Expected 'files' key in response: {data}"
        assert isinstance(data["files"], list)


@SKIP_NO_GWS
@SKIP_NO_TOKEN
@integration
class TestGwsSheetsCrud:
    """1d: Create, write, read, delete a spreadsheet."""

    def test_sheets_create_write_read_delete(self):
        # Create
        result = _run_gws([
            "sheets", "spreadsheets", "create",
            "--json", json.dumps({
                "properties": {"title": "ClawBot Test Sheet"},
            }),
        ])
        assert result.returncode == 0, f"sheets create failed: {result.stderr}"
        sheet = json.loads(result.stdout)
        sheet_id = sheet["spreadsheetId"]

        try:
            # Write
            result = _run_gws([
                "sheets", "spreadsheets.values", "update",
                "--params", json.dumps({
                    "spreadsheetId": sheet_id,
                    "range": "Sheet1!A1:B2",
                    "valueInputOption": "RAW",
                }),
                "--json", json.dumps({
                    "values": [["Name", "Score"], ["Alice", "100"]],
                }),
            ])
            assert result.returncode == 0, f"sheets write failed: {result.stderr}"

            # Read back
            result = _run_gws([
                "sheets", "spreadsheets.values", "get",
                "--params", json.dumps({
                    "spreadsheetId": sheet_id,
                    "range": "Sheet1!A1:B2",
                }),
            ])
            assert result.returncode == 0, f"sheets read failed: {result.stderr}"
            values = json.loads(result.stdout)
            assert values["values"] == [["Name", "Score"], ["Alice", "100"]]

        finally:
            # Cleanup: delete via Drive API
            _delete_drive_file(sheet_id)


@SKIP_NO_GWS
@SKIP_NO_TOKEN
@integration
class TestGwsGmailSearch:
    """1e: Search Gmail inbox."""

    def test_gmail_messages_list(self):
        result = _run_gws([
            "gmail", "users.messages", "list",
            "--params", json.dumps({
                "userId": "me",
                "q": "is:inbox",
                "maxResults": 1,
            }),
        ])

        assert result.returncode == 0, f"gmail search failed: {result.stderr}"
        data = json.loads(result.stdout)
        # Response should have messages array (may be empty)
        assert isinstance(data.get("messages", []), list)
        assert "resultSizeEstimate" in data


@SKIP_NO_GWS
@SKIP_NO_TOKEN
@integration
class TestGwsCalendarList:
    """1f: List calendar events."""

    def test_calendar_events_list(self):
        result = _run_gws([
            "calendar", "events", "list",
            "--params", json.dumps({
                "calendarId": "primary",
                "maxResults": 1,
            }),
        ])

        assert result.returncode == 0, f"calendar list failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert "items" in data or "kind" in data, (
            f"Expected calendar response structure: {data}"
        )


@SKIP_NO_GWS
@SKIP_NO_TOKEN
@integration
class TestGwsDocsCreate:
    """1g: Create and delete a Google Doc."""

    def test_docs_create_and_delete(self):
        # Create
        result = _run_gws([
            "docs", "documents", "create",
            "--json", json.dumps({
                "title": "ClawBot Test Doc",
            }),
        ])
        assert result.returncode == 0, f"docs create failed: {result.stderr}"
        doc = json.loads(result.stdout)
        doc_id = doc["documentId"]
        assert doc_id, "Expected documentId in response"

        try:
            assert doc.get("title") == "ClawBot Test Doc"
        finally:
            # Cleanup: delete via Drive API
            _delete_drive_file(doc_id)
