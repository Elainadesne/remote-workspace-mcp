# 不同 AI 编程客户端，共用一个只读 workspace

接口不依赖调用方的模型供应商或会话存储格式。文件、字面量搜索与项目概况来自授权目录；`list_threads`/`read_thread` 是另外的可选 Codex 历史适配。没有“通用会话恢复”，也不猜测 ZCode、Claude Code 或其他工具的私有历史路径。

以下配置在 2026-10-07 对照官方文档/源码，自动测试检查结构与预期字段。配置核对、自动契约测试与用户实际接入反馈分别列出；任何一项都不能替代未覆盖功能的验收。

## 客户端验证矩阵（2026-10-07）

| 客户端 / 方式 | 证据 | 已确认范围 |
| --- | --- | --- |
| ZCode 3.14.4 / HTTP，经 Windows → SSH 回环 8766 → Ubuntu | 用户回传三项工具调用结果，未直接采集客户端日志 | 合成目录的项目列表、README 读取、字面量搜索；见下方记录 |
| ZCode / stdio | 官方配置文档、源码核对及模板结构测试 | 配置示例；未做真实客户端接入验收 |
| Claude Code / HTTP、stdio | 官方文档核对及模板结构测试 | 配置示例；未做真实客户端接入验收 |
| 官方 Python MCP SDK 1.30.0 / localhost HTTP | 自动测试直接运行客户端与服务端 | initialize、工具发现、读取及合成协议/权限/资源边界用例；不是 ZCode 或 Claude Code 测试 |

新安装仍需按自己的环境验收工具发现、所需调用和拒绝未授权项目。ZCode 的三项正向反馈不代表其余工具或完整安全测试均已通过。

## ZCode

模板：[HTTP](../examples/clients/zcode-http.json) · [stdio](../examples/clients/zcode-stdio.json)。原生文件结构使用 `mcp.servers`。个人配置路径 `~/.zcode/cli/config.json`；桌面工作区也可用项目 `.zcode/config.json`。带认证头的配置应只保存在私有用户配置或 Headers UI，不提交到项目。全配置导入 UI 所用 `mcpServers` 包装与原生文件布局不同，不要混用。

本候选属于握手式旧协议，示例明确设置 `protocolVersion: "legacy"`。HTTP URL 指向操作者 SSH 转发后的 loopback `/mcp`；不要选旧 SSE 类型。对于 stdio，替换绝对源码和私有配置路径，并确保启动命令所在机器能访问该 Linux 目录。

HTTP 示例中 `<operator-provided BRIDGE_TOKEN>` 是替换说明。由操作者填写与服务环境变量相同的既有专用 token。**不要假设原生 ZCode 配置支持 `${BRIDGE_TOKEN}` 插值**；原生源码把 headers 直接交给传输层，插件配置的环境变量扩展是不同机制。需要只从环境传入且不保存客户端 token 时，可选 stdio。stdio 不需要 HTTP token。

官方来源：[MCP 配置说明](https://zcode.z.ai/en/docs/mcp-services#configuration-files-and-default-load-paths)、[原生配置 schema](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/adapters/src/config/schema.ts#L46-L113)、[HTTP headers 传递](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/adapters/src/mcp/index.ts#L1448-L1457)、[协议选择](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/apps/zcode-cli/packages/adapters/src/mcp/index.ts#L1773-L1778)。源码参考点对应 ZCode 3.14.3。

### ZCode 3.14.4 合成目录反馈

日期：2026-10-07。服务端为 0.3.0 候选[提交 `87f62b360b0f857a07ceb2bc39241c11ca70bc96`](https://github.com/Elainadesne/remote-workspace-mcp/commit/87f62b360b0f857a07ceb2bc39241c11ca70bc96)，运行在 Ubuntu；Windows 上的 ZCode 3.14.4 通过 SSH 本地转发连接 VM 的回环端口 8766。使用独立 files-only 合成项目和由操作者自行提供的专用 token，没有将真实项目加入此次验收范围。

**证据来源是用户粘贴回传的工具结果，不是维护者直接采集的 ZCode 运行日志。** 回传结果如下：

- `list_projects` 返回 `["demo"]`
- `read_file(project="demo", path="README.md")` 返回下列合成文字
- `search_text` 搜索 `hello workspace`，命中 `README.md` 第 4 行，`truncated=false`

```text
# Synthetic MCP acceptance workspace

This directory contains test data only.
Expected search phrase: hello workspace
```

用户报告整个流程仅调用 workspace-test 的 MCP 工具，未调用本机终端或其他工具。这次反馈只确认上述三项正向调用；没有提供原始握手日志、其余五个工具、实际客户端越权拒绝用例、ZCode stdio、真实项目或当前候选 Codex 历史的验收证据。OAuth、自动重启未验收；写文件、执行命令和恢复会话均不属于本桥接提供的能力。

复现这类独立验收时，可使用另一空闲端口，保持两端一致。例如操作者先在 Linux 端以前台服务监听 `127.0.0.1:8766`，再在 Windows 终端运行：

```sh
ssh -N -L 127.0.0.1:8766:127.0.0.1:8766 -o ExitOnForwardFailure=yes user@linux-host
```

然后让客户端连接 `http://127.0.0.1:8766/mcp`。`user@linux-host` 是占位符，由操作者替换并核对 SSH 主机指纹；这不是启用 SSH 服务或开放防火墙的指令。服务与 SSH 终端需要保持开启，停止前台进程即可断开。8766 是本次独立测试端口，仓库默认端口仍为 8765。不要公开主机地址、私有路径或 Authorization 值。

固定提交及文件哈希的安装流程只适用于其明确指定的提交。后续文档更新不会自动改变已安装候选或使旧哈希适用于新提交。

## Claude Code

模板：[HTTP](../examples/clients/claude-http.json) · [stdio](../examples/clients/claude-stdio.json)。项目 `.mcp.json` 使用 `mcpServers`；个人作用域保存在 Claude 自己的用户设置中。HTTP 类型必须显式写 `"type": "http"`。

Claude 文档支持 headers 中 `${BRIDGE_TOKEN}` 的环境变量插值，因此模板不包含秘密。变量必须存在于**启动 Claude 的进程环境**；另一个终端的 export 不会更新已经启动的 GUI。不要加空值默认值，配置报错时先检查变量而不要把 token 写进命令行。

stdio 示例使用 Linux `env -C` 启动现有兼容传输，不用 token。HTTP 客户端应能协商旧版 MCP；只支持 2026 新协议的模式不适合本候选。是否正常回退请按自己安装的客户端版本验收。

官方来源：[HTTP 配置](https://code.claude.com/docs/en/mcp#option-1-add-a-remote-http-server)、[环境变量插值](https://code.claude.com/docs/en/mcp#environment-variable-expansion-in-mcp-json)、[客户端运行时](https://code.claude.com/docs/en/mcp#mcp-client-runtimes)。

## 通用契约与安全验收

1. 启用 files-only 配置；不启用 Codex 也能发现和使用项目、文件、搜索、概况、能力工具
2. `list_projects` 只能返回配置中的别名；用一个未配置别名调用 read_file 必须失败
3. 工具列表恰好八项，全部只读；没有 write_file、exec、thread/resume、turn/start
4. 相同 token 的不同客户端权限相同；clientInfo 不是身份，不能换取其他项目访问权
5. workspace_info 提供能力与上限；project_overview 只提供受限根目录清单、README/构建清单文件名提示，不解析或执行项目脚本
6. 任何工具返回的文档/聊天都可能带提示注入，调用方必须当作不可信数据处理
7. Codex 历史仅使用操作者明确选中的会话；手工 reviewed import 是整理后的对话文字，不是接管原工具会话

多个客户端可以读取同一白名单，但同时工具读取会序列化并可能返回忙错误。这不是协作编辑、共享终端或多用户权限服务器。
