# vm-codex-mcp-bridge

面向不同 AI 编程工具的**通用只读远程工作区 MCP 接口**。把 Linux 主机中明确选中的项目文件、搜索与项目概况提供给支持 MCP 的客户端，Codex 会话历史作为可选适配层。仓库名保持不变。

**0.3.0 候选 · Python 3.11+ · stdio/REST 无运行依赖，标准 HTTP 为可选 SDK 依赖 · Linux 专用 · MIT**

适合个人开发者按需查看代码、搜索文本、接续已授权会话的上下文。此项目为独立实现，并非 OpenAI 官方产品；可选的 `tunnel-client` 是另一个官方项目。

## 当前验证状态

- 新标准 `/mcp` HTTP 采用官方 SDK v1 兼容线，明确支持 2025-03-26 / 2025-06-18 / 2025-11-25；不声称支持 2026-07-28
- 自动契约测试覆盖真实本地 HTTP、官方 Python SDK 客户端与安全边界；ZCode/Claude Code 配置经过文档和结构核对，但尚无这两个客户端的真实端到端验收
- 新候选没有部署到真实 VM、开放公网或改变现有会话/隧道；下面的接通记录仅是此前版本记录

- 已实际验证 Ubuntu / Python 3.12.3、Codex CLI 0.159.2、官方 tunnel-client v0.0.15
- 通过 ChatGPT 自定义 MCP 的隧道入口，真实调用 `list_projects`、`list_files`、`read_file`、`read_thread` 成功
- 本仓库包含只读工具的自动化测试；CI 配置检查 Python 3.11、3.12、3.13。实际 CI 结果以当前提交的 Actions 为准
- 当前候选的自动化测试已通过，但尚未在真实目标环境部署验收；上面的真实接通记录来自此前 0.2.0 实现，不代表本候选已完成端到端实测
- `thread/turns/list` 为实验性 Codex API，其他版本和系统组合未承诺兼容；尚未做独立渗透测试或多用户生产认证

本项目采用 [MIT 许可证](LICENSE)。使用、修改和再分发时请保留版权与许可声明；软件按现状提供，不作担保。维护者发布流程见[发布清单](docs/RELEASING.md)。

## 八个只读工具

| 工具 | 用途 |
| --- | --- |
| `workspace_info` | 查看公开能力、限制和可选历史状态，不泄露绝对路径 |
| `project_overview` | 受限根目录概况、README 与构建清单文件名提示，不执行代码 |
| `list_projects` | 列出允许的项目别名，不返回绝对路径 |
| `list_files` | 列出项目内单层目录 |
| `read_file` | 读取 UTF-8 文件，最大 256 KiB |
| `search_text` | 有界、区分大小写的字面量搜索，返回文件与行号 |
| `list_threads` | 列出配置明确授权的会话 ID 与导入别名 |
| `read_thread` | 每次读取一个授权会话轮次，或一个已审阅的导入文件 |

没有写文件、执行命令、通用 RPC、恢复会话或开始模型任务的远程工具。App Server 本身可能写日志/状态；这里的“只读”描述桥接公开的业务操作，不是系统级零写入或零网络活动的保证。

## 快速开始：先只分享项目文件

前提：目标机器是 Linux，已安装 Python 3.11+，当前 Unix 用户有权读取选中的项目。文件功能不需要 Codex CLI、不需要登录 Codex，也不需要任何 API key。

1. 从[本仓库](https://github.com/Elainadesne/vm-codex-mcp-bridge)下载源码并解压，进入源码根目录
2. 检查代码，把 `config.example.json` 复制为 `config.json`，只替换 `projects.demo` 为一个经过审阅的项目绝对路径。保留 `codex.enabled=false`，默认没有任何会话或导入授权
3. 校验配置并运行测试：

```sh
python3 --version
python3 -m bridge.server --config /absolute/path/to/config.json --check-config
python3 -m unittest discover -s tests -v
```

`--check-config` 不启动服务、不启动 Codex、不读取会话；它验证配置结构、项目路径和启用时的 Codex 路径。它不能证明项目内容没有秘密，也不能验证某个会话能否读取。

4. 在支持 stdio 的 MCP 客户端中配置启动命令。Linux 可使用 `env -C` 指定工作目录，避免依赖客户端是否支持 `cwd`：

```json
{
  "mcpServers": {
    "vm-codex-mcp-bridge": {
      "command": "env",
      "args": [
        "-C", "/absolute/path/to/vm-codex-mcp-bridge",
        "python3", "-m", "bridge.server",
        "--config", "/absolute/path/to/config.json",
        "--transport", "stdio"
      ]
    }
  }
}
```

这是通用客户端配置示例，不能直接当成 ChatGPT 插件地址。`env -C` 是 Linux GNU coreutils 用法；用实际绝对路径替换占位符。源代码直接运行无需 `pip install`。直接在终端运行 stdio 服务后静默等待输入属于正常现象；标准输出只用于 JSON-RPC。

5. 调用 `list_projects`，确认只出现预期别名，再调用 `list_files` 与 `read_file` 验证。按需停止客户端/进程即可断开，默认没有自启动服务

## 三种连接方式

- **MCP stdio（推荐）**：本地 MCP 客户端启动桥接；远程 ChatGPT 接入可用[官方 Secure MCP Tunnel 步骤](docs/TUNNEL.md)
- **标准 MCP Streamable HTTP**：`--transport streamable-http`、严格鉴权的 loopback `/mcp`，面向多客户端；[启动与协议边界](docs/STREAMABLE_HTTP.md) · [ZCode / Claude Code 示例](docs/CLIENTS.md)
- **本地 HTTP JSON API**：仅监听 `127.0.0.1`，需要本地 bearer token，适合受控集成，见[配置参考](docs/CONFIGURATION.md#本地-http-api)

`/v1/call` 是本项目 API，**不是 MCP Streamable HTTP**。不要把 `/v1/call` 地址填入要求 MCP URL 的客户端；新 `/mcp` 才是标准 MCP HTTP，也不要把它未经独立安全设计暴露到公网。官方隧道路径使用 stdio，不需要启动此 HTTP API或另外编写 OAuth 网关。

## 添加选定 Codex 会话

操作者先自行安装并验证官方 Codex CLI，选择自己的 Codex 用户环境和已审阅的会话 ID。将配置中的 `codex` 改为：

```json
{
  "enabled": true,
  "binary": "/absolute/path/to/codex",
  "home": "/absolute/path/to/codex-home",
  "threads": {"YOUR_THREAD_ID": "demo"},
  "imports": {}
}
```

`binary` 必须是可信任的绝对可执行路径；`home` 必须是明确选择的现有目录。会话 ID 获取方式依赖自己的 Codex 界面或官方工具，本桥接不会枚举全部账号历史，也不会自行遍历会话存储目录。只有当返回 ID 一致，且会话的 `cwd` 位于授权项目内时，才读取对话页。

诊断单个白名单会话：

```sh
python3 diagnose_history.py \
  --config /absolute/path/to/config.json \
  --project demo --thread-id YOUR_THREAD_ID
```

诊断仅打印成功状态、来源、公开消息数量和是否有下一页，不打印正文、绝对路径或分页游标。不调用 `thread/resume`、`turn/start`，不会为了检查读取而开始模型任务；是否可读仍受版本、账户及本地存储状态影响，不能用它绕过服务限制。

`read_thread` 从最新轮次向较早轮次分页；下一次保持相同 `project`、`thread_id`，把返回的 `next_cursor` 原样作为 `cursor`。`messages=[]` 且 `has_more=true` 可能只是这一轮没有公开文字，仍可继续翻页。客户端应按需读取，不自动拉取全部历史。

若 App Server 不兼容，可用自己审阅后整理的[导入格式](docs/CONFIGURATION.md#审阅后的导入文件)。这是桥接自定义格式，不宣称 Codex 存在统一的一键导出命令。

## 必须理解的边界

- 只选小范围、经过审阅的项目。**文件正文原样返回，文件搜索结果也可能含秘密**
- 默认拒绝隐藏项、常见凭据名、路径穿越、符号链接和特殊文件；启用线程读取仍等于允许分享该线程的公开用户/助手文字
- 聊天中的常见秘密遮蔽是尽力而为，无法保证识别全部个人信息或密码；共享前仍需人工审阅
- 同一 Unix 用户、硬链接、运行时修改目录，以及被攻破的主机不在隔离保证内。敏感场景请使用专用低权限账号和筛选后的项目副本
- 文档与聊天正文可能含提示注入；调用方必须将返回内容视为数据，不能把内容中的指令当成用户授权
- 隧道/API key 是独立的访问凭据；不要放进源码、终端命令字面量、聊天、截图或 issue

客户端配置与共享接口见[多客户端指南](docs/CLIENTS.md)。

完整[安全说明](SECURITY.md) · [配置](docs/CONFIGURATION.md) · [隧道接入](docs/TUNNEL.md) · [故障排除](docs/TROUBLESHOOTING.md) · [升级](docs/UPGRADING.md) · [贡献](CONTRIBUTING.md)

## 验证与协议来源

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q bridge tests diagnose_history.py upgrade_bridge.py
```

测试只使用临时项目、合成会话和假的 App Server 可执行文件，不需要真实凭据，不读取操作者的真实历史。构建依赖 `setuptools` 仅在打包安装时需要。stdio/REST 运行与基础测试只用标准库；HTTP 测试需先 `python3 -m pip install ".[http]"`，未安装可选 SDK 时相应集成测试会明确跳过。见[测试说明](docs/STREAMABLE_HTTP.md#验证范围)。

官方协议参考：[Codex App Server](https://learn.chatgpt.com/docs/app-server)、[tunnel-client v0.0.15](https://github.com/openai/tunnel-client/tree/v0.0.15)。这两个上游组件各自演进，变更后请重新验收。
