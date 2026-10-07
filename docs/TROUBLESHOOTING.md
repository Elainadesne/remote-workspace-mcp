# 故障排除

先记录 Python、Codex CLI、tunnel-client 的版本，再分层检查：配置 → 文件工具 → Codex → 隧道 → 客户端。不要为排错扩大项目白名单、关闭 TLS 校验或改为全权限 key。

## 启动与文件

| 现象 | 检查 |
| --- | --- |
| `No module named bridge` | 是否从源码根目录启动？客户端可用 Linux `env -C /源码目录 python3 -m bridge.server ...` |
| `Configuration error` | 运行 `--check-config`；JSON 无注释/尾逗号；字段拼写、类型、绝对路径正确；不使用 `~` 或 `$HOME` |
| `Configure project roots on Linux` | 原生 Windows/macOS 不支持本项目文件安全实现；在 Linux VM/受控 Linux 环境运行 |
| 根目录被拒绝 | 用 `pwd -P` 查规范绝对路径，选窄项目目录，不要共享 HOME、隐藏/凭据目录或符号链接路径 |
| stdio 服务启动后没有输出 | 正常，它在等待 MCP JSON-RPC 输入；不要向 stdout 加调试日志 |
| 文件未出现在列表中 | 检查隐藏/敏感名称、符号链接和依赖/构建目录过滤，不要为了绕过保护改名共享秘密 |
| `Read failed` | 文件是否消失、不可读、不是 UTF-8、超 256 KiB 或是特殊文件？错误刻意不返回本机私密路径 |
| 搜索没结果/结果不全 | 搜索区分大小写且为字面量；缩小 path；检查 `truncated`；二进制/超大/不可读文件会跳过 |
| 改配置没生效 | 先停止桥接/隧道旧进程，再校验配置和启动；没有热重载 |

## Codex 历史

1. 文件工具正常后，再启用 Codex。明确填写可信二进制、已有 Codex home、线程与项目映射
2. 在同一 Unix 账号自行检查 `codex --version`。已实测 0.159.2；其他版本须重新验证。桥接不会自行安装、登录或开始模型任务
3. 运行带 `--config`、`--project`、`--thread-id` 的 `diagnose_history.py`。它只检查一页，打印计数，不打印内容

| 错误 | 安全的下一步 |
| --- | --- |
| `Thread not allowed` | 核对明确授权的 ID 与项目映射；不要把全部账号历史加入白名单 |
| `Codex history is disabled` | 按需设 enabled=true 并重启；或使用已审阅导入 |
| `Cannot start configured Codex App Server` | 检查 binary 是否存在、可执行、依赖解释器可用，是否为正确用户的官方安装 |
| `Codex read failed` | 核对版本、用户环境、已有账号状态和线程 ID；错误详情被隐藏以免泄露会话内容 |
| `outside allowed project` / `identity mismatch` | 检查会话真实 cwd 与项目对应关系；不要为了通过而授权 HOME 或撤掉检查 |
| `no verifiable project directory` / `Unsupported ...` | 当前 App Server 数据格式不兼容；保留错误类别与版本，使用合成复现报告 |
| `response exceeds 32 MiB` | 单轮内容也可能过大。不会退回全量会话；请自行审阅并导入需要的节选 |
| `timed out` | 检查本机负载与 App Server 状态；后续请求会重新启动 App Server，可在问题解决后重试 |
| `messages=[]`, `has_more=true` | 本轮可能只有工具操作，保留 project/thread_id 并传回 next_cursor 继续读取 |

桥接不遍历隐藏会话文件、不恢复/改写原会话、不绕过额度、权限或存储限制。不要把 App Server 的全部调试日志贴到公开渠道。

## 隧道与 ChatGPT

- **init 不识别选项**：核对是否使用完整 tunnel-client v0.0.15，而非只有 run 的 runtime 版本；查看本机 `init --help`
- **只能看到演示工具**：检查 profile 的 mcp-command 是否为 bridge.server；不要使用 embedded stub
- **401/403/permission denied**：检查当前终端是否输入 runtime key、正确组织/项目、Tunnels 使用权限及 tunnel 用户/组授权；不要换成 Admin key 来运行
- **网络超时**：检查已有代理是否适用于该进程。v0.0.15 可用 `--control-plane.http-proxy` / HTTPS_PROXY，不能假定 ALL_PROXY 生效；不要关闭证书校验
- **进程运行但发现工具失败**：确认同一 tunnel ID 只有一个 stdio 实例；先停旧进程再重启，检查配置和子进程命令
- **工具消失或突然离线**：终端关闭、Ctrl+C、主机休眠、网络断开、密钥撤销/过期都会影响连接；先验证前台进程和实际工具调用
- **UI 没有隧道入口**：功能可能受账户/工作区可用性影响；查官方帮助/管理员。不能填入本地 HTTP API 代替 MCP 服务
- **想贴日志求助**：先人工删除 key、Authorization、tunnel ID、项目路径、thread ID、聊天内容。最好只贴版本、错误类别和合成复现

## HTTP API

401 表示 bearer token 不匹配；403 表示 Origin 或 Host 不允许；404 表示路径不为 `/v1/call`；400/413 表示请求格式或大小不符合要求。HTTP 客户端需正确的 JSON Content-Type、Content-Length 与 `Host: 127.0.0.1:端口` 或 `localhost:端口`。不要在浏览器脚本中调用或通过伪造 header 绕过保护。
