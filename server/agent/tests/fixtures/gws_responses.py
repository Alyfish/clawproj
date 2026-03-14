"""Sample gws CLI JSON responses for testing.

These mirror the actual output format of the gws binary.
Used by agent behavior tests and as reference for integration tests.
"""

DRIVE_FILES_LIST = {
    "files": [
        {
            "id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
            "name": "Project Notes",
            "mimeType": "application/vnd.google-apps.document",
            "modifiedTime": "2026-03-12T15:30:00.000Z",
        },
    ],
    "nextPageToken": None,
}

SHEETS_CREATE = {
    "spreadsheetId": "1dZy8Z5qT0qR4x5gH7nK2mL9pW3vC6bF",
    "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/1dZy8Z5qT0qR4x5gH7nK2mL9pW3vC6bF",
    "properties": {
        "title": "Test Sheet",
        "locale": "en_US",
    },
}

SHEETS_VALUES_UPDATE = {
    "spreadsheetId": "1dZy8Z5qT0qR4x5gH7nK2mL9pW3vC6bF",
    "updatedRange": "Sheet1!A1:B2",
    "updatedRows": 2,
    "updatedColumns": 2,
    "updatedCells": 4,
}

SHEETS_VALUES_GET = {
    "range": "Sheet1!A1:B2",
    "majorDimension": "ROWS",
    "values": [["Name", "Score"], ["Alice", "100"]],
}

GMAIL_MESSAGES_LIST = {
    "messages": [
        {"id": "18e1a2b3c4d5e6f7", "threadId": "18e1a2b3c4d5e6f7"},
    ],
    "resultSizeEstimate": 1,
}

CALENDAR_EVENTS_LIST = {
    "kind": "calendar#events",
    "items": [
        {
            "id": "evt_abc123",
            "summary": "Team Standup",
            "start": {"dateTime": "2026-03-13T10:00:00-07:00"},
            "end": {"dateTime": "2026-03-13T10:30:00-07:00"},
        },
    ],
}

DOCS_CREATE = {
    "documentId": "1xK7mN2pQ3rS4tU5vW6xY7zA8bC9dE0f",
    "title": "Test Document",
    "body": {"content": []},
}

DRIVE_DELETE = {}  # 204 No Content equivalent

# Dry-run output includes the full request that would be sent
DRY_RUN_DRIVE_LIST = {
    "dry_run": True,
    "method": "GET",
    "url": "https://www.googleapis.com/drive/v3/files?pageSize=1",
    "headers": {
        "Authorization": "Bearer {token}",
        "Content-Type": "application/json",
    },
}

# Error responses
AUTH_ERROR_401 = {
    "error": {
        "code": 401,
        "message": "Request had invalid authentication credentials.",
        "status": "UNAUTHENTICATED",
    },
}

AUTH_ERROR_STDERR = (
    "Error: 401 Unauthorized - Request had invalid authentication credentials. "
    "Expected OAuth 2 access token, login cookie or other valid authentication credential."
)
