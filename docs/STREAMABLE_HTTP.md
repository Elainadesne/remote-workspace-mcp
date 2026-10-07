# 标准 MCP Streamable HTTP（0.3.0 候选）

同一个明确授权的远程 workspace 可供多个 AI 编程客户端读取。客户端只是读取者；它们不能选择新的项目根、修改授权、运行命令，或借 clientInfo 获得不同身份。服务按**单操作者、一份只读项目白名单**设计，不提供多租户隔离。

## 启动：先保留在 loopback

Linux / Python 3.11+。建议在独立虚拟环境安装可选依赖，不修改原有 stdio 环境：

```sh
python3 -m venv /absolute/path/to/bridge-http-env
/absolute/path/to/bridge-http-env/bin/python -m pip install '.[http]'
/absolute/path/to/bridge-http-env/bin/python -m bridge.server \
  --config /absolute/path/to/private/config.json --check-config
```

由操作者通过安全的环境注入方式提供专用高熵 `BRIDGE_TOKEN`，再在源码目录启动：

```sh
/absolute/path/to/bridge-http-env/bin/python -m bridge.server \
  --config /absolute/path/to/private/config.json \
  --transport streamable-http --port 8765
```

本项目不生成、写入或保存 token。至少 32、最多 512 个 ASCII bearer 字符；长度检查不代表熵足够。不要复用云服务 API key、登录密码或其他访问凭据。变量缺失或不合法时启动失败。改变或撤销 token 要停止进程、更换操作者提供的环境变量并重启；已下载的数据无法撤回。

只监听 `127.0.0.1`，没有 `--host 0.0.0.0` 选项。默认端口 8765，路径严格是 `/mcp`。这是一份新的 MCP HTTP 服务；旧 `--transport http` 仍然只提供 `/v1/call`，两者不是同一协议。一个端口只能启动一个进程。

远程主机上运行时，可由操作者建立 SSH 本地转发：

```sh
ssh -N -L 8765:127.0.0.1:8765 user@linux-host
```

两端使用相同端口以匹配严格 Host 校验。客户端连接 `http://127.0.0.1:8765/mcp`；跨机器流量由 SSH 加密，HTTP 只留在 loopback。SSH 登录和主机信任由操作者管理。本仓库不安装服务、不开放防火墙、不自动建隧道。不要直接暴露公网或通过随意重写 Host 的代理绕过这些边界。需要公开 HTTPS、OAuth 或跨用户服务时应另做安全设计。

## 协议与兼容矩阵

| 路径/模式 | 支持版本 | 生命周期 |
| --- | --- | --- |
| 现有 stdio | 2024-11-05 | 保持原来的 initialize / initialized 行为 |
| 新 `/mcp` | 2025-03-26、2025-06-18、2025-11-25 | 官方 SDK v1 的 initialize 握手；通知 POST 返回 202 空体 |
| 2026-07-28 | 暂不支持 | 该版本取消握手、使用逐请求元信息；不能仅修改版本号来支持 |
| 旧 `/v1/call` | 私有 REST | 不是任何版本的 MCP HTTP |
| 旧 HTTP+SSE | 不实现 | 无 `/sse` 或独立事件流 |

客户端先发送带 protocolVersion、capabilities、clientInfo 的 initialize 请求。如果请求的版本在三种 HTTP 版本中，则保留；否则回复本服务支持的最新版本 `2025-11-25`，由客户端决定是否继续。然后发送 `notifications/initialized`。后续请求使用协商版本的 `MCP-Protocol-Version`；缺省按规范兼容 `2025-03-26`。未知或不支持的 HTTP 版本头返回 400。

HTTP 使用**无状态、单 JSON 响应**模式：不分配 session ID，不保存 clientInfo，不跟踪跨请求初始化状态，也不向客户端发起请求。客户端仍应完成握手，服务不会把握手当鉴权。所有请求均独立验证 token 和项目白名单；来自不同客户端的 token 拥有完全相同权限。GET/DELETE 返回 405（`Allow: POST`），没有事件重放或通知流。这是规范允许的 Streamable HTTP 子集，名字中的 Streamable 不要求每次返回 SSE。

只支持现代协议的客户端无法接入本版本。支持双协议时代的客户端应根据旧版错误进入 initialize 回退；例如 ZCode 示例明确设为 `legacy`。携带 2026 逐请求元信息或 2026 版本头的请求不会被当成 2025 请求悄悄执行。

### 客户端验证状态

| 客户端 / 方式 | 截至 2026-10-07 的验证 |
| --- | --- |
| ZCode 3.14.4 / Windows 经 SSH 回环 8766 到 Ubuntu | 用户回传合成目录的 `list_projects`、`read_file`、`search_text` 成功结果；未直接采集 ZCode 运行日志 |
| 官方 Python MCP SDK 1.30.0 / localhost HTTP | 自动契约测试直接验证 initialize、工具发现、读取和合成错误/权限/资源边界 |
| ZCode stdio；Claude Code HTTP/stdio | 已核对配置模板，尚无真实客户端接入验收 |

本次 ZCode 反馈不包含握手协议版本原始日志，不能据此增加上方协议矩阵的版本范围。详细返回值、提交和复现入口见[客户端接入记录](CLIENTS.md#zcode-3144-合成目录反馈)。

## 请求与错误契约

- 每次都是 POST `/mcp`、单个 JSON-RPC 2.0 对象；不接受 batch、重复 JSON 键、NaN、非法 UTF-8、非对象 params、无 method 的客户端响应
- 请求 ID 只接受短字符串或安全范围整数；0 与空字符串原样回传，null、布尔值、浮点值无效
- `Content-Type: application/json`，`Accept` 必须明确包含可接受的 `application/json` 和 `text/event-stream`；必须有合法、无歧义的 Content-Length，拒绝压缩与 Transfer-Encoding
- 已接受的通知是 202 空体；请求成功为 200 JSON；未知方法为 JSON-RPC -32601；参数/读取失败使用协议错误或 tools/call 的 isError
- 无效鉴权 401，非法 Origin/Host 403，路径不符 404，方法不支持 405，Accept 不符 406，body 超时 408，body 太大 413，内容类型不符 415，头过大 431，并发忙 503，请求期限超出 504
- SDK 验证细节、异常路径、请求内容与凭据不进入错误文字。协议 ID 仍需原样回传，客户端不要将秘密放在 ID 中
- 不记录访问日志、请求体、token、搜索文本或文件正文；错误消息刻意保持通用。启动失败请先核对配置、版本与环境变量

## 边界与资源限制

每一个到达应用的 HTTP 方法都经过同一 Host/Origin/token 检查。Host 只允许实际端口的 127.0.0.1 与 localhost；拒绝所有 Origin，包括 `null`。无 CORS。应用可见的重复关键头失败关闭；HTTP 解析器可能先合并完全相同的 Content-Length，冲突长度仍拒绝。URL query 不可用于提供 token。`clientInfo`、HTTP 头和 MCP 元数据不能改变项目白名单。

- 请求正文最多 64 KiB，HTTP 头最多 16 KiB，JSON 响应最多 8 MiB
- 进程最多接收 16 个连接、8 个应用请求；超额连接立即关闭
- 每个 TCP 连接绝对存活上限 40 秒（包括不完整请求头），回应后关闭连接；不会因逐字节发送而延长期限
- 正文总读取期限 10 秒；单工具读取等待最多 25 秒，SDK 请求处理最多 27 秒
- 同时最多一个实际 workspace 读取，无无界任务队列；其他工具调用会收到可重试错误

Python 无法安全强杀阻塞中的文件系统读操作。工具超时后，原工作线程仍占用唯一读取名额，直到实际 I/O 结束；新请求不会不断制造后台线程。异常挂载/NFS 可能需要操作者处理底层 I/O 或重启进程。这些限制不是公网抗 DDoS 保证。

## 依赖取舍

stdio 和私有 REST 继续只用 Python 标准库。HTTP 可选依赖为官方 `mcp>=1.30,<2`，配合 `uvicorn>=0.52.1,<0.53`。v1 是受维护的旧协议兼容线，当前上游主版本 v2 支持另一套生命周期；此候选不自动跨大版本升级。使用 SDK 是为了复用协议握手、类型和 HTTP 传输实现，而不是将私有 API 改名冒充 MCP。

最低版本 1.30 包含上游累计安全修补。Streamable HTTP 运行时会拒绝旧于 1.30 或 v2 的 SDK。Uvicorn 的 H11 子类只增加连接数与绝对期限限制，因此将 Uvicorn 钉在已测试次版本范围，并用真实 socket 回归覆盖它。仍需持续检查依赖安全更新；本项目未实现 SDK OAuth 服务，不受益于未配置的 OAuth audience 验证。

## 验证范围

```sh
/absolute/path/to/bridge-http-env/bin/python -m unittest discover -s tests -v
/absolute/path/to/bridge-http-env/bin/python -m compileall -q bridge tests
```

自动测试包含真实 localhost HTTP、官方 Python SDK 客户端 initialize/list/call、通知、错误、权限和超时契约；ZCode 与 Claude Code 配置示例另做自动结构检查。2026-10-07，用户回传 ZCode 3.14.4 经 Windows → SSH 回环 8766 → Ubuntu 的合成目录三项成功结果，记录对应提交 `87f62b360b0f857a07ceb2bc39241c11ca70bc96`。证据是用户回传，而非直接采集的 ZCode 日志。

这次实际接入仅覆盖合成项目列表、README 读取和搜索，不涵盖真实项目、其余工具、当前候选 Codex 历史、实际客户端越权拒绝用例、OAuth 或自动重启；桥接没有写入/命令执行能力。Claude Code 与 ZCode stdio 仍未做真实接入验收，也不据此宣称旧桥接已切换或完成公网部署。

参考：[2025 HTTP 规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[2025 生命周期](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)、[2026 HTTP 变更](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)、[SDK v1.30.0](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v1.30.0)、[SDK 安全公告](https://github.com/modelcontextprotocol/python-sdk/security/advisories)。
