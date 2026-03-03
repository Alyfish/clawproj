# Skill Template

Copy this skeleton when creating a new SKILL.md. Replace all `{placeholders}` and remove `# RULE` comments before saving.

---

## Frontmatter

```yaml
---
name: {kebab-case-name}
# RULE: Lowercase + hyphens only. Must match ^[a-z0-9][a-z0-9-]*$ (no consecutive hyphens).
# RULE: 2-4 words, matches parent directory name.
# GOOD: crypto-tracker, shopify-orders, email-summary
# BAD: CryptoTracker, my_skill, a

description: {One specific sentence: what it does + when to trigger + what NOT to use it for.}
# RULE: Primary triggering mechanism — be "pushy" to combat under-triggering.
# RULE: Include negative triggers to prevent false matches.
# BAD: "Helps with shopping"
# GOOD: "Search for products on Amazon, compare prices across sellers, track price history, and set up price drop alerts. Use whenever the user mentions online shopping, product comparison, deal hunting, or price tracking. NOT for in-store inventory or grocery lists."

tools: [{comma-separated tools this skill actually uses}]
# VALID: http_request, browser, code_execution, file_io, create_card,
#        save_memory, search_memory, request_approval, web_search, vision, load_skill
# RULE: Only list tools the skill calls. Unused tools waste context.

approval_actions: [{actions requiring human approval before execution}]
# VALID: pay, submit, send, share_personal_info, delete
# RULE: Empty [] if no actions need approval. See approval-safety SKILL.md.

version: "1.0.0"
author: ClawBot
tags: [{domain keywords for discovery}]
# GOOD: [travel, flights, booking]  BAD: [cool, useful, misc]
---
```

---

## Body Sections

````markdown
# {Skill Title}

## Context

{What this skill does in 2-3 sentences. Write in 3rd-person imperative ("Search for...", "Extract the...", NOT "I will..." or "You should...").}

{When the agent should activate this skill. Be specific about triggers.}

### Triggers
- "{example trigger phrase 1}"
- "{example trigger phrase 2}"
- "{example trigger phrase 3}"
- "{example trigger phrase 4}"

---

## Authentication

{How to authenticate with the API. Reference credentials from the credential store.}

- **Credential name:** `{credential-name}`
- **Auth type:** {api_key | oauth2 | bearer | basic | none}
- **How to apply:** {Header: `Authorization: Bearer {token}` | Query param: `?api_key={key}` | Custom header: `X-Api-Key: {key}`}

{If no auth needed: "No authentication required."}

---

## API Details

{Document every API endpoint the skill uses. If the skill uses browser instead of API, rename this section to "## Browser Automation" and document URL patterns + extraction rules.}

### Primary Endpoint

- **Method:** {GET | POST | PUT | DELETE}
- **URL:** `{exact API URL}`
- **Headers:**
  - `{Header-Name}: {value or credential reference}`

**Required Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `{param}` | {string\|number\|boolean} | {what it does} |

**Optional Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `{param}` | {type} | `{default}` | {what it does} |

### Response Structure

```json
{
  "field": "show exact structure",
  "nested": {
    "path": "the agent needs to parse"
  }
}
```

### Key Field Paths

- {Human-readable name}: `response.path.to.field`
- {Human-readable name}: `response.path.to.field`

### Error Handling

| Status | Meaning | Action |
|--------|---------|--------|
| 401 | Credential expired or invalid | Tell user to update credential via `python -m server.agent.credential_store add` |
| 429 | Rate limited | Wait 60s and retry once, then inform user |
| 404 | Resource not found | Inform user, suggest alternative search terms |
| 500 | API server error | Inform user, suggest trying again later |

---

## Process

{Step-by-step instructions the agent follows. Numbered, specific, no ambiguity. Use decision trees: "If X, skip to Step N."}

1. Parse the user's request to extract {key parameters}.
2. Check if credential `{name}` exists. If not, skip to Step {N} (Mock Mode).
3. Call {endpoint} with extracted parameters.
4. Parse response using field paths above.
5. Run {any validation/scoring/filtering} on results.
6. Create card(s) with results using `create_card` tool.
7. Present results to user, sorted by {relevance | price | date}.
8. If user wants to take action, request approval via `request_approval`.

---

## Card Output

**Card type:** {FlightCard | HouseCard | PickCard | DocCard | BaseCard}

{Reference the canonical schema in shared/types/cards.ts. Never redefine card structures inline.}

**Metadata fields:**

| Field | Type | Description |
|-------|------|-------------|
| `{field}` | {type} | {description} |
| `{field}` | {type} | {description} |

**Example card:**

```json
{
  "type": "{card_type}",
  "id": "{prefix}-{unique-id}",
  "title": "{human-readable title}",
  "subtitle": "{summary line}",
  "{domain_field}": "{value}",
  "metadata": {
    "{extra_field}": "{value}"
  },
  "actions": [
    { "label": "{Action Label}", "type": "link", "url": "{url}" }
  ],
  "createdAt": "{ISO 8601}"
}
```

---

## Mock Mode

{Instructions for generating realistic fake data when no API credentials are available.}

If credential `{credential-name}` does not exist:

1. Generate {8-15} realistic results with variety.
2. Include a mix of: {describe variety — e.g., "price ranges, ratings, brands"}.
3. Include {2-3} edge cases: {e.g., "one with missing data, one unusually cheap"}.
4. Prefix results with:

> **Demo Results** — These are simulated for demonstration.
> Connect {Service Name} API for live data: `python -m server.agent.credential_store add`

---

## Example Interaction

{Show a complete realistic conversation flow. Include agent's internal steps.}

**User:** "{realistic user message}"

**Agent:**
> {Step 1 — acknowledge and search}
> {Step 2 — present results with cards}
> {Step 3 — offer follow-up actions}

**User:** "{follow-up message}"

**Agent:**
> {Follow-up action with approval gate if needed}

---

## Rules

{Minimum 3 constraints. These are non-negotiable behaviors.}

1. {Safety constraint — e.g., "Never expose API keys in user-visible output"}
2. {Data constraint — e.g., "Always validate response data before creating cards"}
3. {UX constraint — e.g., "Present results sorted by relevance, not raw API order"}
4. {Memory constraint — e.g., "Save interesting results to memory for future reference"}
5. {Disclosure constraint — e.g., "Always disclose when showing mock/demo data"}
````

---

## Validation Checklist

Run through every item before saving a new skill. All boxes must be checked.

### Frontmatter

- [ ] `name` matches `^[a-z0-9][a-z0-9-]*$` — no uppercase, no underscores, no consecutive hyphens
- [ ] `name` matches the parent directory name
- [ ] `description` is a complete sentence with specific trigger phrases
- [ ] `description` includes negative triggers ("NOT for...") to prevent false matches
- [ ] `tools` contains only valid tool names from the list above
- [ ] `approval_actions` contains only valid action names from the list above
- [ ] `version` is set to `"1.0.0"` for new skills
- [ ] YAML parses without errors (no tabs, correct indentation, strings quoted if needed)

### Required Sections

- [ ] `## Context` — present, includes trigger phrases, written in 3rd-person imperative
- [ ] `## Authentication` — present (even if "no authentication required")
- [ ] `## API Details` — present (or `## Browser Automation` for non-API skills)
- [ ] `## Process` — present, numbered steps, specific, includes decision trees
- [ ] `## Card Output` — present, references `shared/types/cards.ts`, fields defined
- [ ] `## Mock Mode` — present, generates varied realistic data, labels as demo
- [ ] `## Example Interaction` — present, realistic user↔agent flow
- [ ] `## Rules` — present, at least 3 constraints

### Quality (mgechev Trigger Testing)

- [ ] Generate 3 prompts that SHOULD trigger this skill — all match correctly
- [ ] Generate 3 prompts that SHOULD NOT trigger — none match incorrectly
- [ ] API URLs are real and documented (not made-up placeholders)
- [ ] Response field paths verified against actual API documentation
- [ ] Error handling covers 401, 429, 404, 500
- [ ] Mock data is varied and domain-realistic
- [ ] Total skill length: 200-500 lines (use `references/` for overflow)

### Security (SkillForge Scanner Rules)

- [ ] No hardcoded API keys, tokens, passwords, or secrets anywhere
- [ ] Credentials referenced via `{credential:name}` or credential store
- [ ] All financial/destructive actions listed in `approval_actions`
- [ ] No `eval()`, `exec()`, `os.system()`, or dynamic code execution from user input
- [ ] No pipe-to-shell patterns (`curl | sh`, `wget | bash`)
- [ ] No access to sensitive paths (`/etc/passwd`, `~/.ssh`, credential files)
- [ ] No reverse shell patterns (`nc`, `ncat`, `/dev/tcp`)
- [ ] Scripts in `scripts/` use only safe binaries (git, node, python, pip, jq, docker, kubectl)
- [ ] No prompt injection or jailbreak patterns in skill content

### Progressive Disclosure (Keep Context Lean)

- [ ] Main SKILL.md is under 500 lines
- [ ] Large reference docs moved to `references/` subdirectory (one level deep only)
- [ ] SKILL.md includes JiT pointers: "See `references/X.md` for details on Y"
- [ ] No redundant instructions (agent already knows how to do basic operations)
