# Changelog

## 0.2.0 — First public candidate (unreleased)

This source snapshot is the first public candidate. No release tag, package publication or deployment is implied. Automated checks and earlier end-to-end integration observations are described separately in README.

- MIT-licensed source with synthetic examples and tests
- Six read-only tools for explicitly selected Linux project files and Codex conversations
- MCP stdio transport and a separate authenticated loopback HTTP JSON API
- One-turn Codex pagination through experimental `thread/turns/list`, with identity and project-directory checks
- Bounded configuration loading, duplicate-key rejection, path validation and `--check-config`
- Fail-closed handling of malformed MCP, JSON and upstream history structures
- App Server deadline, pagination validation, filtered public messages and best-effort secret masking
- Rejection of broad, sensitive or symlink project roots and overlaps with a configured Codex home
- Explicit, single-page diagnostic arguments with content-free result counts
- A non-mutating upgrade helper; reviewed manual upgrade and rollback instructions
- Configuration, tunnel, troubleshooting, security, contribution and maintainer-release documentation
