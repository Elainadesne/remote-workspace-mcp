# Changelog

## 0.3.0 — 通用只读 workspace 候选

- 新增 workspace_info / project_overview；传输无关工具层与可选 Codex 历史适配分离
- 新增官方 MCP SDK 支撑的标准 Streamable HTTP（2025 协议矩阵），保持原 stdio 与私有 REST 兼容
- 单操作者环境 token、loopback、Host/Origin/JSON/header/size/time/concurrency 边界
- ZCode 与 Claude Code HTTP/stdio 配置模板，迁移与安全文档，真实本地 HTTP 和官方 SDK 客户端契约测试
- 不加入写文件、命令执行、第三方私有历史解析、会话恢复、自动部署或权限扩张
- 未在真实 VM、ZCode 或 Claude Code 部署验收；不宣称 2026-07-28 协议兼容


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
