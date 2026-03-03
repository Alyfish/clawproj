---
name: skill-creator
description: >-
  Create new skills when no existing skill matches the user's request.
  Research APIs, write a SKILL.md, validate it, and use it immediately.
  Activate when user says "create a skill for", "teach yourself to",
  "learn how to", or when no existing skill handles the task.
tools: [web_search, http_request, file_io, code_execution, load_skill]
approval_actions: []
version: "1.0.0"
author: ClawBot
tags: [meta, skill-creation, self-extending, automation]
---

# Skill Creator

## Context

You are ClawBot's meta-skill — the skill that creates other skills. When no existing
skill handles what the user needs, you research APIs, write a new SKILL.md, validate it,
and then immediately use it to fulfill the user's original request.

**Explicit triggers (user asks directly):**
- "Create a skill for ..."
- "Teach yourself to ..."
- "Learn how to ..."
- "Can you add a skill that ..."
- "Build me a ... integration"

**Implicit triggers (no existing skill matches):**
- User requests a capability not covered by any skill in `<available_skills>`
- User asks about a specific API or service ClawBot doesn't know yet
- User wants recurring automation for a new domain

**Non-triggers — do NOT create a skill for:**
- One-off tasks base tools can handle (a single web search, a quick calculation)
- Tasks an existing skill already covers (check `<available_skills>` first)
- Vague requests without a clear domain ("do something cool")
- Tasks that only need `code_execution` with no external API

**Capabilities:**
- Research APIs via `web_search` and `http_request`
- Write complete SKILL.md files with proper frontmatter and all required sections
- Validate structure, security, and quality before saving
- Save to `skills/{name}/SKILL.md` via `file_io`
- Immediately use the new skill in the same conversation
- Improve existing skills when they fall short


## Phase 0: Triage

Before creating anything, classify the request into one of four buckets:

### Decision Tree

1. **Check existing skills.** Scan `<available_skills>` for a match.
   - If a skill covers ≥80% of the request → **USE_EXISTING**
   - If a skill covers 50-79% → **IMPROVE_EXISTING**
   - If no skill covers >50% → proceed to step 2

2. **Check if it's a one-off.** Can base tools handle this without a skill?
   - Simple web search + code processing → **JUST_DO_IT** (use base tools directly)
   - Needs structured API calls, card output, or will recur → **CREATE_NEW**

3. **Check memory.** Use `search_memory` for previous skill creation attempts.
   - If a previous attempt exists, learn from what failed.

### Actions by Bucket

| Bucket | Action |
|--------|--------|
| **USE_EXISTING** | Tell user which skill handles it, then use `load_skill` to activate it |
| **IMPROVE_EXISTING** | Go to "Skill Improvement" section below |
| **CREATE_NEW** | Proceed to Phase 1. **Ask user for confirmation first:** "I don't have a skill for X yet. Want me to create one? This will let me handle X requests going forward." |
| **JUST_DO_IT** | Handle with base tools. No skill needed. |


## Phase 1: Research

Systematic research before writing a single line. Follow all 5 steps.

### Step 1: Find the API

```
Tool: web_search
{"query": "{service name} API documentation REST endpoints"}
```

Look for:
- Official API docs (swagger, redoc, developer portal)
- REST vs GraphQL vs SOAP
- API versioning (use latest stable version)

### Step 2: Check Authentication

Determine the auth method:

| Method | Complexity | Example Services |
|--------|-----------|-----------------|
| None / API key in query | Low | CoinGecko, Open-Meteo, USDA |
| API key in header | Low | NewsAPI, Alpha Vantage |
| Bearer token | Medium | Todoist, Notion, Linear |
| OAuth2 client_credentials | Medium | Amadeus, Spotify |
| OAuth2 authorization_code | High | Gmail, Google Calendar, Slack |
| No public API | Fallback | Use `browser` tool |

### Step 3: Test the Endpoint (if possible)

For APIs with free tiers or no-auth endpoints, make a test call:

```
Tool: http_request
{
  "method": "GET",
  "url": "{discovered_endpoint}",
  "query_params": {"key": "test_param"}
}
```

Verify: Does the response match the documented schema?

### Step 4: Evaluate Viability

Score the API on these criteria:

| Criterion | Good | Acceptable | Poor |
|-----------|------|-----------|------|
| Free tier | Generous (1000+ req/day) | Limited (100/day) | None or pay-only |
| Documentation | OpenAPI spec, examples | Basic docs | Undocumented |
| Rate limits | >100 req/min | >10 req/min | <10 req/min |
| Reliability | Major provider, SLA | Community API | Unknown uptime |
| Response format | JSON, well-structured | JSON, nested | XML, binary |

If the primary API scores "Poor" on 2+ criteria, look for alternatives.

### Step 5: Identify Fallback Strategy

Every skill needs a fallback:

| Scenario | Fallback |
|----------|----------|
| API has free tier | Mock mode with realistic data |
| API requires paid plan | Mock mode + note about credentials |
| No API exists | `browser` tool for web scraping |
| Rate limited | Caching via `save_memory` |

### Research Checklist

Before moving to Phase 2, confirm:
- [ ] Primary API endpoint URL identified
- [ ] Auth method determined
- [ ] Required parameters documented
- [ ] Response schema understood (key field paths)
- [ ] Free tier or test mode available (or mock planned)
- [ ] Fallback strategy decided
- [ ] No show-stoppers found

If you can't check all boxes, be honest with the user: "I found the {service} API but
it requires {blocker}. Here's what I can do instead: {alternative}."


## Phase 2: Write the Skill

Reference the supplementary file `skill-template.md` for the exact structure.

### Writing Rules

1. **Valid YAML frontmatter.** Must parse without errors. Use `code_execution` to validate:
   ```python
   import yaml
   yaml.safe_load(frontmatter_string)
   ```

2. **Kebab-case name.** `crypto-prices`, not `cryptoPrices` or `Crypto Prices`.

3. **Specific description.** The description is what triggers skill activation.
   - Bad: "Handles crypto stuff"
   - Good: "Track cryptocurrency prices, set price alerts, and compare exchange rates. Activate when user asks about Bitcoin, Ethereum, crypto prices, or token values."

4. **Only valid tool names.** Choose from:
   `code_execution`, `file_io`, `http_request`, `web_search`, `create_card`,
   `save_memory`, `search_memory`, `request_approval`, `browser`, `vision`, `load_skill`

5. **Only valid approval actions.** Choose from:
   `pay`, `submit`, `send`, `delete`, `share_personal_info`
   Only include actions the skill actually performs. Most read-only skills need none.

6. **Real endpoint URLs.** Never use placeholder URLs. Include the actual
   API endpoint discovered in Phase 1.

7. **Exact response field paths.** Document how to extract data from the API response.
   Example: `response.data[0].price.grandTotal` not just "the price field."

8. **Mock mode is mandatory.** Every skill must work without credentials for demo/dev.

9. **Card output defined.** Specify which card type (flight, house, pick, doc, or BaseCard)
   and show a complete `create_card` tool call example with all fields.

10. **200-400 lines target.** If content exceeds 400 lines, split reference material into
    separate files in the skill directory (e.g., `api-reference.md`).


## Phase 3: Validate

Run 4 validation layers. Fix and re-validate on any failure.

### Layer 1: Frontmatter Validation

```
Tool: code_execution
```
```python
import yaml

frontmatter = """
name: {name}
description: {description}
tools: [{tools}]
approval_actions: [{actions}]
version: "1.0.0"
author: ClawBot
tags: [{tags}]
"""

VALID_TOOLS = {
    "code_execution", "file_io", "http_request", "web_search",
    "create_card", "save_memory", "search_memory", "request_approval",
    "browser", "vision", "load_skill"
}
VALID_ACTIONS = {"pay", "submit", "send", "delete", "share_personal_info"}

parsed = yaml.safe_load(frontmatter)
errors = []

# Check name is kebab-case
import re
if not re.match(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$', parsed.get('name', '')):
    errors.append(f"Name '{parsed.get('name')}' is not kebab-case")

# Check tools are valid
for tool in parsed.get('tools', []):
    if tool not in VALID_TOOLS:
        errors.append(f"Invalid tool: {tool}")

# Check approval_actions are valid
for action in parsed.get('approval_actions', []):
    if action not in VALID_ACTIONS:
        errors.append(f"Invalid approval action: {action}")

# Check required fields
for field in ['name', 'description', 'tools', 'version']:
    if field not in parsed:
        errors.append(f"Missing required field: {field}")

if errors:
    print("VALIDATION FAILED:")
    for e in errors:
        print(f"  - {e}")
else:
    print("FRONTMATTER OK")
```

### Layer 2: Required Sections

Check the markdown body contains ALL required sections:

| Section | Required | Purpose |
|---------|----------|---------|
| Context | Yes | When to activate, capabilities |
| Authentication | Yes* | How to authenticate (*skip if no-auth API) |
| API Details | Yes | Endpoints, parameters, response parsing |
| Card Output | Yes | create_card example with all fields |
| Mock Mode | Yes | Demo data generation |
| Example Interaction | Yes | User request → agent response flow |
| Rules | Yes | Domain constraints, error handling |

### Layer 3: Quality Checks

| Check | Pass Criteria |
|-------|--------------|
| URLs are real | No `example.com`, no `{placeholder}` in URLs |
| Field paths exist | Response parsing references actual field names |
| Error handling | At least one error scenario documented |
| Mock variety | Mock data has 3+ distinct entries |
| Description triggers | Description includes specific trigger phrases |
| Line count | Between 100 and 500 lines |

### Layer 4: Security Scan

| Rule | What to Check |
|------|--------------|
| No hardcoded keys | No API keys, tokens, or secrets in the content |
| Credential store only | Auth uses `"credential": "{name}"` pattern |
| Financial actions gated | Any pay/submit/send uses `request_approval` |
| No shell injection | No `os.system()`, `subprocess`, or backtick execution |
| No path traversal | File paths stay within `skills/` directory |
| Personal data gated | Sharing user info requires `share_personal_info` approval |

### Auto-Heal

If validation fails on a fixable issue:
1. Identify the specific failure
2. Fix it in the generated content
3. Re-run the failed validation layer
4. Proceed only when all 4 layers pass

If validation fails on an unfixable issue (e.g., API doesn't exist):
1. Report the issue to the user
2. Suggest alternatives
3. Do not save a broken skill


## Phase 4: Save & Register

### Step 1: Write to Disk

```
Tool: file_io
{
  "action": "write",
  "path": "skills/{name}/SKILL.md",
  "content": "{validated_skill_content}"
}
```

The `file_io` tool auto-creates the `skills/{name}/` directory.

### Step 2: Load into Context

```
Tool: file_io
{
  "action": "read",
  "path": "skills/{name}/SKILL.md"
}
```

Reading the skill back loads its full content into the conversation context.
You can now follow its instructions directly.

### Step 3: Confirm to User

Tell the user:
- Skill name and what it does
- Where it's saved (`skills/{name}/SKILL.md`)
- That it will auto-load in future sessions
- That you're about to use it for their original request

### Registration Note

The skill persists on disk. On next agent startup, `SkillLoader.load_all()` discovers
it automatically from the `skills/` directory. No manual registration needed.


## Phase 5: Execute

**Do not stop after creating the skill.** Immediately use it to handle the user's
original request. Follow the new skill's instructions as if it always existed.

1. Parse the user's original request through the new skill's lens
2. Execute the skill's workflow (API calls, data processing, card creation)
3. Present results naturally — the user shouldn't feel like they're testing a new skill
4. If mock mode: show demo results with the standard mock notice


## Skill Improvement

When an existing skill falls short (IMPROVE_EXISTING from Phase 0):

### Step 1: Read Current Skill

```
Tool: file_io
{
  "action": "read",
  "path": "skills/{name}/SKILL.md"
}
```

### Step 2: Identify the Gap

Compare what the user needs vs what the skill provides:
- Missing API endpoint?
- Missing parameter support?
- Incorrect response parsing?
- Missing card fields?
- Missing error handling?

### Step 3: Edit and Save

Write the updated content:

```
Tool: file_io
{
  "action": "write",
  "path": "skills/{name}/SKILL.md",
  "content": "{updated_skill_content}"
}
```

### Step 4: Re-validate

Run Phase 3 validation on the updated skill. Bump the version number
(e.g., "1.0.0" → "1.1.0" for new features, "1.0.1" for fixes).

### Step 5: Log the Change

```
Tool: save_memory
{
  "key": "skill-update-{name}-{date}",
  "content": "Updated {name} skill: {what changed and why}",
  "tags": ["skill-update", "{name}"]
}
```


## Examples

### Example 1: Crypto Prices (Free, No Auth)

**User:** "What's the current price of Bitcoin and Ethereum?"

**Triage:** No crypto skill exists → CREATE_NEW. Ask user first.

**Research:**
- API: CoinGecko `/api/v3/simple/price` (free, no auth, 30 req/min)
- Auth: None required
- Test: `GET https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd`
- Response: `{"bitcoin": {"usd": 67432.00}, "ethereum": {"usd": 3521.00}}`
- Fallback: Mock with realistic prices

**Skill:** `skills/crypto-prices/SKILL.md`
- Tools: `[http_request, code_execution, create_card, save_memory]`
- Approval: `[]` (read-only)
- Card type: `pick` (comparison card)

### Example 2: Todoist Tasks (Bearer Token)

**User:** "Can you manage my Todoist tasks?"

**Triage:** No task management skill → CREATE_NEW.

**Research:**
- API: Todoist REST API v2 `https://api.todoist.com/rest/v2/tasks`
- Auth: Bearer token in `Authorization` header
- Credential key: `todoist`
- Key endpoints: GET/POST/PATCH /tasks, GET /projects
- Fallback: Mock with sample tasks

**Skill:** `skills/todoist-tasks/SKILL.md`
- Tools: `[http_request, code_execution, create_card, save_memory, request_approval]`
- Approval: `[submit, delete]` (creating/deleting tasks)
- Card type: `doc` (task details card)

### Example 3: Restaurant Reservations (No API → Browser)

**User:** "Book me a table at Nobu tonight"

**Triage:** No restaurant skill → CREATE_NEW.

**Research:**
- API: Resy has no public API. OpenTable API is partner-only.
- Fallback: Use `browser` tool to navigate Resy/OpenTable
- Auth: User's Resy account (browser session)

**Skill:** `skills/restaurant-booking/SKILL.md`
- Tools: `[browser, vision, web_search, create_card, request_approval]`
- Approval: `[submit]` (confirming a reservation)
- Card type: `pick` (restaurant options)

### Example 4: Weather Forecasts (Free API Key)

**User:** "What's the weather in Tokyo this week?"

**Triage:** No weather skill → But this is a simple web search task → **JUST_DO_IT**.
Use `web_search` directly. No skill needed for occasional weather checks.

If user says "I check weather daily, can you learn this?" → Then CREATE_NEW with
Open-Meteo API (free, no auth).

### Example 5: Email Summary (Complex OAuth2)

**User:** "Summarize my unread emails"

**Triage:** No email skill → CREATE_NEW.

**Research:**
- API: Gmail API `https://gmail.googleapis.com/gmail/v1/users/me/messages`
- Auth: OAuth2 authorization_code flow (complex — requires redirect URI)
- Fallback: Mock with sample emails

**Honest response:** "Gmail requires OAuth2 with a redirect flow, which I can't fully
handle yet. I can create a skill that works in mock mode for now, and will be ready
when OAuth2 support is added. Want me to proceed?"

**Skill:** `skills/gmail-summary/SKILL.md`
- Tools: `[http_request, code_execution, create_card, save_memory]`
- Note: Mock-only until OAuth2 infrastructure exists


## Rules

1. **Always ask before creating.** Never silently create a skill. Confirm with the user:
   "I don't have a skill for X. Want me to create one?"

2. **No skills for one-offs.** If the user will never need this again, use base tools
   directly. Skills are for recurring capabilities.

3. **YAML must validate.** Run the frontmatter through `yaml.safe_load()` before saving.
   If it fails, fix and retry.

4. **No hardcoded credentials.** All API keys and tokens must use the credential store
   pattern: `"credential": "{name}"` in `http_request` calls. Never embed keys in content.

5. **400-line maximum.** If a skill exceeds 400 lines, split reference material into
   supplementary files (e.g., `api-reference.md`, `endpoints.json`).

6. **Be honest about limitations.** If an API is broken, paywalled, or requires
   unsupported auth, say so. Don't create a skill that will always fail.

7. **Persist to disk.** Always save via `file_io` to `skills/{name}/SKILL.md`.
   Skills survive across sessions via `SkillLoader.load_all()`.

8. **Specific descriptions.** The description field determines when the skill activates.
   Include trigger phrases and domain keywords. Test mentally: "If a user said X,
   would this description match?"

9. **Credential store only.** Reference credentials by name. The user adds them via
   `python -m server.agent.credential_store add`. Document the credential name
   and what permissions are needed.

10. **Log to memory.** After creating or updating a skill, save a memory entry:
    ```
    Tool: save_memory
    {
      "key": "skill-created-{name}",
      "content": "Created {name} skill: {what it does}, API: {api used}, auth: {method}",
      "tags": ["skill-creation", "{name}"]
    }
    ```
