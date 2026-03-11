# Changelog

## [2.0.0] — 2026-03-06

### Added
- **Bash Execute Tool** — Shell access for the agent with security blocklist, approval triggers, environment filtering, timeout enforcement, and output truncation
- **SearXNG Integration** — Zero-config web search fallback (no API keys needed)
- **Persistent Workspace** — `/workspace` Docker volume with `memory/`, `scripts/`, `data/` subdirectories
- **Integration Tests** — 12 end-to-end tests covering bash+SearXNG pipelines, workspace operations, and security
- **Scheduler System** — Cron-based watch execution for autonomous price/listing/odds monitoring

### Changed
- **Web Search Tool** — Provider cascade: Mock → SerpAPI → SearXNG (was: Mock → SerpAPI only)
- **Price Monitor Skill** — Rewritten for bash-first workflows (curl/jq over structured HTTP tool)
- **Docker Compose** — Added SearXNG and workspace volume services

### Fixed
- Registry tests unpacking tuple from `create_registry()` return value
- Test expected tool counts updated for new bash_execute and schedule tools
