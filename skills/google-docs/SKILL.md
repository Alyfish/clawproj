---
name: google-docs
description: >-
  Create and manage Google Workspace documents — Docs, Sheets, Forms, and
  Slides — via their REST APIs. Use whenever the user wants to write a
  document, build a spreadsheet, create a survey or form, make a
  presentation, organize messy text into a clean doc, or share any Google
  Workspace file.
tools: [http_request, code_execution, create_card, save_memory, request_approval]
approval_actions: [send, share_personal_info]
version: "1.0.0"
author: ClawBot
tags: [documents, google, workspace, docs, sheets, forms, slides, writing]
---

# Google Docs

## Context

This skill enables ClawBot to create, populate, format, and share Google
Workspace documents using the Google REST APIs.

**When to activate:**
- "create a doc", "write a document", "draft something in Google Docs"
- "make a spreadsheet", "build a table", "track expenses in a sheet"
- "create a form", "make a survey", "build a questionnaire"
- "make a presentation", "create slides", "build a deck"
- "share this doc", "give access to", "make it public"
- User wants to organize messy text or data into a structured document

**Capabilities:**
- Create blank or pre-populated Docs, Sheets, Forms, and Slides
- Insert structured content with heading styles, bold headers, tables
- Share documents with specific people or publicly
- Output DocCard data for the iOS app
- Save document references to memory
- Mock mode when credentials unavailable


## Authentication

OAuth2 Bearer tokens pre-provisioned in the credential store. The agent
does NOT perform the OAuth2 flow.

**Credential key:** `google_workspace` | **Env var:** `CLAWBOT_CRED_GOOGLE_WORKSPACE`

Automatic injection via `http_request` when `credential: "google_workspace"` is set.

### Required Scopes

| Scope | API |
|-------|-----|
| `https://www.googleapis.com/auth/documents` | Docs |
| `https://www.googleapis.com/auth/spreadsheets` | Sheets |
| `https://www.googleapis.com/auth/forms.body` | Forms |
| `https://www.googleapis.com/auth/presentations` | Slides |
| `https://www.googleapis.com/auth/drive` | Drive (sharing, metadata) |

### Credential Check

1. Attempt API call with `credential: "google_workspace"`
2. "Credential not found" -> switch to **Mock Mode**
3. 401 -> token expired, tell user to re-authenticate
4. 403 -> missing scope, tell user which one

### MIME Types

| Type | MIME |
|------|------|
| Doc | `application/vnd.google-apps.document` |
| Sheet | `application/vnd.google-apps.spreadsheet` |
| Form | `application/vnd.google-apps.form` |
| Slides | `application/vnd.google-apps.presentation` |


## API: Google Docs

### Create

```
Tool: http_request
{
  "method": "POST",
  "url": "https://docs.googleapis.com/v1/documents",
  "headers": {"Content-Type": "application/json"},
  "body": {"title": "Meeting Notes — March 1, 2026"},
  "credential": "google_workspace"
}
```

Response: `{ "documentId": "1abc...xyz" }` — save this for all subsequent calls.

### Insert Content (batchUpdate)

Content is NOT set during creation. Use batchUpdate to insert text:

```
Tool: http_request
{
  "method": "POST",
  "url": "https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate",
  "body": {
    "requests": [{
      "insertText": {
        "location": {"index": 1},
        "text": "Meeting Notes\nDate: March 1, 2026\nAttendees: Alice, Bob\n\nAgenda\n1. Q1 Review\n2. Roadmap\n\nAction Items\n- Alice: Prepare demo\n- Bob: Update docs\n"
      }
    }]
  },
  "credential": "google_workspace"
}
```

**Index rules:**
- Body starts at index 1 (index 0 is reserved)
- Insert ALL content as a single text block at index 1, then format separately
- If inserting multiple blocks, go BOTTOM to TOP (insertions shift indices)

### Apply Formatting

After inserting text, apply heading styles in a SEPARATE batchUpdate:

```
Tool: http_request
{
  "method": "POST",
  "url": "https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate",
  "body": {
    "requests": [
      {"updateParagraphStyle": {
        "range": {"startIndex": 1, "endIndex": 15},
        "paragraphStyle": {"namedStyleType": "HEADING_1"},
        "fields": "namedStyleType"
      }},
      {"updateParagraphStyle": {
        "range": {"startIndex": 55, "endIndex": 62},
        "paragraphStyle": {"namedStyleType": "HEADING_2"},
        "fields": "namedStyleType"
      }}
    ]
  },
  "credential": "google_workspace"
}
```

**Named styles:** `TITLE`, `HEADING_1`-`HEADING_6`, `NORMAL_TEXT`

Use `code_execution` to count character positions before building formatting requests.

### Get webViewLink

```
Tool: http_request
{
  "method": "GET",
  "url": "https://www.googleapis.com/drive/v3/files/{documentId}",
  "query_params": {"fields": "webViewLink"},
  "credential": "google_workspace"
}
```

Response: `{ "webViewLink": "https://docs.google.com/document/d/{id}/edit" }`


## API: Google Sheets

### Create

```
Tool: http_request
{
  "method": "POST",
  "url": "https://sheets.googleapis.com/v4/spreadsheets",
  "headers": {"Content-Type": "application/json"},
  "body": {
    "properties": {"title": "Expense Tracker 2026"},
    "sheets": [{"properties": {"title": "Expenses"}}]
  },
  "credential": "google_workspace"
}
```

Response includes `spreadsheetId` and `spreadsheetUrl` (direct link — no Drive API call needed).

### Write Values

```
Tool: http_request
{
  "method": "PUT",
  "url": "https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}/values/Expenses!A1:E4",
  "query_params": {"valueInputOption": "USER_ENTERED"},
  "body": {
    "values": [
      ["Date", "Category", "Description", "Amount", "Running Total"],
      ["2026-03-01", "Food", "Team lunch", "45.00", "=SUM(D$2:D2)"],
      ["2026-03-01", "Transport", "Uber", "18.50", "=SUM(D$2:D3)"],
      ["2026-03-02", "Software", "Figma", "15.00", "=SUM(D$2:D4)"]
    ]
  },
  "credential": "google_workspace"
}
```

- `USER_ENTERED` — parses formulas and dates (default, use this)
- `RAW` — stores as literal strings

### Format Header Row

Use `batchUpdate` with `repeatCell` to bold the header row and add background color,
and `autoResizeDimensions` to auto-fit column widths:

```json
{"requests": [
  {"repeatCell": {
    "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
    "cell": {"userEnteredFormat": {"textFormat": {"bold": true}, "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.95}}},
    "fields": "userEnteredFormat(textFormat,backgroundColor)"}},
  {"autoResizeDimensions": {"dimensions": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 5}}}
]}
```

Send via: `POST /v4/spreadsheets/{spreadsheetId}:batchUpdate` with `credential: "google_workspace"`


## API: Google Forms

### Create

```
Tool: http_request
{
  "method": "POST",
  "url": "https://forms.googleapis.com/v1/forms",
  "headers": {"Content-Type": "application/json"},
  "body": {"info": {"title": "Team Feedback Survey"}},
  "credential": "google_workspace"
}
```

Response: `{ "formId": "...", "responderUri": "https://docs.google.com/forms/d/.../viewform" }`

### Add Questions (batchUpdate)

Each question is a `createItem` request. POST to `/v1/forms/{formId}:batchUpdate`:

```json
{"requests": [
  {"createItem": {"item": {"title": "Rate your satisfaction", "questionItem": {"question": {
    "required": true,
    "scaleQuestion": {"low": 1, "high": 5, "lowLabel": "Poor", "highLabel": "Excellent"}
  }}}, "location": {"index": 0}}},
  {"createItem": {"item": {"title": "Areas to improve?", "questionItem": {"question": {
    "choiceQuestion": {"type": "CHECKBOX", "options": [
      {"value": "Communication"}, {"value": "Timeline"}, {"value": "Quality"}
    ]}
  }}}, "location": {"index": 1}}},
  {"createItem": {"item": {"title": "Comments?", "questionItem": {"question": {
    "textQuestion": {"paragraph": true}
  }}}, "location": {"index": 2}}}
]}
```

Send with `credential: "google_workspace"`.

### Question Types

| Type | Field | Use Case |
|------|-------|----------|
| Multiple choice | `choiceQuestion.type: "RADIO"` | Pick one |
| Checkboxes | `choiceQuestion.type: "CHECKBOX"` | Pick multiple |
| Dropdown | `choiceQuestion.type: "DROP_DOWN"` | Pick from long list |
| Short answer | `textQuestion.paragraph: false` | Brief text |
| Long answer | `textQuestion.paragraph: true` | Paragraph text |
| Scale | `scaleQuestion` | 1-5 or 1-10 rating |


## API: Google Slides

### Create

```
Tool: http_request
{
  "method": "POST",
  "url": "https://slides.googleapis.com/v1/presentations",
  "headers": {"Content-Type": "application/json"},
  "body": {"title": "Q1 Product Review"},
  "credential": "google_workspace"
}
```

Response: `{ "presentationId": "...", "slides": [{"objectId": "p"}] }` — one blank slide.

### Add Slides and Content

POST to `/v1/presentations/{presentationId}:batchUpdate`:

```json
{"requests": [
  {"insertText": {"objectId": "p", "text": "Q1 Product Review\nMarch 2026", "insertionIndex": 0}},
  {"createSlide": {"objectId": "slide_metrics", "insertionIndex": 1,
    "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"}}},
  {"createSlide": {"objectId": "slide_roadmap", "insertionIndex": 2,
    "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"}}}
]}
```

**Layouts:** `BLANK`, `TITLE`, `TITLE_AND_BODY`, `TITLE_AND_TWO_COLUMNS`,
`TITLE_ONLY`, `SECTION_HEADER`, `ONE_COLUMN_TEXT`, `MAIN_POINT`, `BIG_NUMBER`

**Strategy:** Create presentation → `createSlide` with explicit `objectId` per slide → `insertText` to populate. For many slides, use `code_execution` to build the requests array.

**webViewLink:** `GET /drive/v3/files/{presentationId}?fields=webViewLink` with `credential: "google_workspace"`


## Sharing (Drive API)

**Sharing requires user approval** — it sends email notifications and exposes content.

### Share with a Person

**Step 1: Approval**
```
Tool: request_approval
{
  "action": "send",
  "description": "Share 'Meeting Notes' with alice@example.com (editor). Sends email notification.",
  "details": {"document": "Meeting Notes", "recipient": "alice@example.com", "role": "writer"}
}
```

**Step 2: Create permission (after approval)**
```
Tool: http_request
{
  "method": "POST",
  "url": "https://www.googleapis.com/drive/v3/files/{fileId}/permissions",
  "query_params": {"sendNotificationEmail": "true"},
  "body": {"type": "user", "role": "writer", "emailAddress": "alice@example.com"},
  "credential": "google_workspace"
}
```

For multiple people, send a separate permissions request per email.

### Make Public (View Only)

Only when user explicitly asks. No approval needed for "anyone" since no personal info involved, but still request `send` approval.

```json
{"type": "anyone", "role": "reader"}
```

### Roles: `reader` (view) | `commenter` (view + comment) | `writer` (edit)


## Document Creation Patterns

### Messy Text → Structured Doc
**Trigger:** "Clean up these notes", "Turn this into a doc"
Parse raw text with `code_execution` → create Doc → insert structured text at index 1 → apply heading styles → get webViewLink → DocCard

### Data → Spreadsheet
**Trigger:** "Track expenses", "Make a spreadsheet of this"
Identify columns → create Sheet → write headers + data with `USER_ENTERED` → add formulas (SUM, AVERAGE) → format headers → DocCard

### Questions → Form
**Trigger:** "Create a survey", "Make a feedback form"
Extract questions → infer types (yes/no→RADIO, rate→scale, multi→CHECKBOX, open→text) → create Form → add questions → DocCard with responderUri

### Content → Slides
**Trigger:** "Make a presentation", "Build me a deck"
Break into sections (1 per slide) → create presentation → title slide + content slides (bullets, not paragraphs) → DocCard


## Templates

| Template | Type | Structure |
|----------|------|-----------|
| Meeting Notes | Doc | Title → Date/Attendees → Agenda (numbered) → Discussion → Action Items (owner + due date) → Next Meeting |
| Expense Tracker | Sheet | Headers: Date, Category, Description, Amount, Payment Method, Running Total (`=SUM(D$2:D{row})`) + Summary sheet with `SUMIF` per category |
| Feedback Survey | Form | 1. Satisfaction (scale 1-5) 2. What went well? (text) 3. Improvements (checkboxes) 4. Recommend? (RADIO) 5. Comments (text, optional) |
| Executive Summary | Doc | Title → Executive Summary (overview) → Key Findings (numbered) → Recommendations (bullets) → Next Steps (with dates) |
| Comparison Table | Sheet | Row 1: Criteria / Option A / Option B / Option C. Rows: criteria values. Last row: Score or Recommendation |

For Docs, apply HEADING_1 to title, HEADING_2 to section names.


## Card Output

After creating any document, emit a DocCard matching `shared/types/cards.ts`:

```
Tool: create_card
{
  "type": "doc",
  "id": "doc-1abc-xyz",
  "title": "Meeting Notes — March 1, 2026",
  "subtitle": "Google Doc | Just created",
  "createdAt": "2026-03-01T15:30:00Z",
  "docType": "google_doc",
  "previewText": "Date: March 1, 2026. Attendees: Alice, Bob. Agenda: 1. Q1 Review...",
  "url": "https://docs.google.com/document/d/1abc...xyz/edit",
  "mimeType": "application/vnd.google-apps.document",
  "lastModified": "2026-03-01T15:30:00Z",
  "metadata": {},
  "actions": [
    {"id": "open-doc", "label": "Open in Google Docs", "type": "link",
     "url": "https://docs.google.com/document/d/1abc...xyz/edit"},
    {"id": "share-doc", "label": "Share", "type": "custom",
     "payload": {"action": "share_doc", "fileId": "1abc...xyz"}}
  ],
  "source": "Google Workspace"
}
```

### docType Values

| Request | docType | previewText Source |
|---------|---------|-------------------|
| Document | `"google_doc"` | First ~200 chars of inserted text |
| Spreadsheet | `"google_sheet"` | Header row + first data row |
| Form | `"google_form"` | First 2-3 question titles |
| Slides | `"google_slides"` | Title slide text + slide count |


## Mock Mode

When `google_workspace` credential is unavailable, simulate document creation.

**Detection:** First API call returns "Credential not found" → mock mode for session.

**Generate mock URL:**
```python
import uuid
doc_id = uuid.uuid4().hex[:20]
urls = {
    "google_doc": f"https://docs.google.com/document/d/MOCK-{doc_id}/edit",
    "google_sheet": f"https://docs.google.com/spreadsheets/d/MOCK-{doc_id}/edit",
    "google_form": f"https://docs.google.com/forms/d/MOCK-{doc_id}/viewform",
    "google_slides": f"https://docs.google.com/presentation/d/MOCK-{doc_id}/edit",
}
```

Prepend notice: **Demo Mode** — simulated document. Set `CLAWBOT_CRED_GOOGLE_WORKSPACE` for live creation.

Add `[DEMO]` prefix to card title. Still structure content properly to show what would be created.


## Example Interaction

**User:** "Here are my meeting notes: talked to alice and bob about Q1 roadmap. agreed to launch beta march 15. alice will prep demo, bob updates docs. next meeting march 8."

**Agent:** Identifies Pattern 1 (messy text → doc). Checks credential. Creates Doc titled "Meeting Notes — March 1, 2026". Structures content: Attendees → Discussion → Action Items → Next Meeting. Inserts text, formats headings, gets webViewLink, emits DocCard.

"I organized your notes into:
- **Attendees:** Alice, Bob
- **Discussion:** Q1 roadmap — beta launch March 15
- **Action Items:** Alice (prepare demo), Bob (update docs)
- **Next Meeting:** March 8, 2026

Want me to share it with Alice and Bob?"

**User:** "Yes, share with alice@company.com and bob@company.com"

**Agent:** Requests approval (action: "send"). After approval, creates permissions for each email.

"Done — both have editor access and received email notifications."


## Rules

1. **Create before populating.** Docs, Forms, and Slides must be created first, then populated via batchUpdate. Never set body content in the Docs creation request.

2. **Single insertText for Docs.** Insert all content as one block at index 1, then format in a separate batchUpdate. Avoids index complexity.

3. **USER_ENTERED for Sheets.** Always use `valueInputOption=USER_ENTERED` (enables formulas/dates) unless user wants raw values.

4. **Never share without approval.** All sharing goes through `request_approval` with `send`. Include `share_personal_info` when email addresses are involved.

5. **Show links, not IDs.** Present webViewLink URL to the user, never raw documentId.

6. **Generate previewText.** Always include ~200 chars of content summary in the DocCard.

7. **Save to memory.** After creating: `save_memory(key="doc-{docType}-{title}", tags=["google-docs", docType])` with title, URL, type, date, description.

8. **Handle errors.** 401: token expired. 403: missing scope. 429: rate limited, wait and retry once.

9. **Disclose mock data.** Never present mock documents as real. Show demo notice and `[DEMO]` prefix.

10. **Match complexity to intent.** Quick note = simple doc. Quarterly report = full headings and sections.
