# 使用官方隧道连接 ChatGPT

本页记录 **tunnel-client v0.0.15 + Linux stdio** 的已实测路径。桥接不自带隧道、不自动创建凭据、不安装持久服务。官方组件的版本、页面和权限可能变化；遇到差异先核对所装版本的 `--help` 与[官方文档](https://github.com/openai/tunnel-client/tree/v0.0.15)。

## 1. 先准备本地桥接

完成 README 快速开始和 `--check-config`。请先只授权一个已审阅项目、保持 Codex disabled，等文件验证成功后再按需添加会话。

目标路径必须在运行 tunnel-client 的 Linux 机器上可访问。隧道会启动一个 stdio 子进程，无需额外打开 8765 端口，也不使用本桥接的 HTTP token。

## 2. 操作者准备隧道与最小权限

从 [OpenAI Tunnels 管理页](https://platform.openai.com/settings/organization/tunnels)创建或选择自己有权使用的隧道，并通过官方提供的安装/下载方式取得匹配平台的 **完整 tunnel-client**。本页的 init/doctor 子命令不是仅运行型 runtime 二进制的界面。按官方校验方式验证下载文件；不要从第三方粘贴未审阅安装脚本。

```sh
tunnel-client --version
tunnel-client help quickstart
```

使用[运行 API keys 页面](https://platform.openai.com/settings/organization/api-keys)创建专用 runtime key，限定到所需组织/项目及隧道访问，不使用管理用的 Admin key。已验证界面采用 Restricted → Tunnels=Use 的单选项，其他资源为 None；隧道的用户/组授权也必须匹配。不同界面可能分别显示 Read 与 Use，以当前官方权限说明为准，不能为了排错直接改成 All。

创建凭据和授权持续访问应由操作者明确确认。密钥只在本地输入，不贴进聊天、仓库、截图或 issue。密钥过期、撤销或权限不匹配时连接会失败。

## 3. 创建可审阅 profile

以下全为占位符。替换桥接目录、配置路径和 tunnel ID；路径若含空格，需要在 `--mcp-command` 字符串内正确加引号。

```sh
tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile vm-bridge \
  --tunnel-id YOUR_TUNNEL_ID \
  --control-plane-api-key-ref env:CONTROL_PLANE_API_KEY \
  --health-listen-addr 127.0.0.1:0 \
  --mcp-command 'env -C /absolute/path/to/vm-codex-mcp-bridge python3 -m bridge.server --config /absolute/path/to/config.json --transport stdio'
```

先审阅生成的 profile，确认命令指向自己的源码和配置，密钥是环境变量引用而非字面值，健康检查只绑定 loopback。Profile 含本机路径与 tunnel ID，不要提交到仓库。不要把这个命令替换为 embedded demo，否则只会看到演示工具。

## 4. 在当前 Bash 终端前台运行

```bash
read -r -s -p 'Tunnel runtime key: ' CONTROL_PLANE_API_KEY
printf '\n'
export CONTROL_PLANE_API_KEY
tunnel-client doctor --profile vm-bridge --explain
tunnel-client run --profile vm-bridge
unset CONTROL_PLANE_API_KEY
```

只在 doctor 检查符合预期后运行。运行期间保留终端和前台进程；Ctrl+C 停止后执行 unset。没有设置开机自启、后台守护或系统服务。请不要同时为同一 tunnel ID 启动多个 stdio 实例；更新或重连时先停旧实例。

网络要求通过已有代理访问时，可由操作者替换成自己的本地代理端口：

```sh
tunnel-client run --profile vm-bridge --control-plane.http-proxy http://127.0.0.1:YOUR_PROXY_PORT
```

v0.0.15 支持 HTTPS_PROXY；不要假定 ALL_PROXY 生效。代理仅用于本机已有且可信的网络配置；不要为连接成功关闭证书校验或泄露密钥。doctor 若也需要代理，请检查其对应帮助参数。

## 5. 在 ChatGPT 中添加并验证

在有该入口的 ChatGPT 中进入“插件 → 添加 → 创建自定义 MCP”，选择“隧道”，选中同一个 tunnel。此桥接没有实现额外 OAuth 登录，因此该 MCP 的额外身份验证选择无；这不意味着隧道本身没有访问控制。操作者应审阅并确认工具权限。

保持前台进程运行，再逐项验收：

1. 工具发现只应出现 README 中八个只读工具
2. `list_projects` 只返回预期项目别名
3. `list_files` 和 `read_file` 返回已知测试文件
4. 需要会话时再配置白名单、重启、调用 `read_thread` 并检查分页
5. 停掉前台进程后连接应不可用；下次使用需重新启动

不要把“profile 已生成”或“UI 已添加”当成接通证据，以真实工具调用结果为准。UI 不显示入口时，检查当前账户/工作区是否提供此功能；不要把本地 `/v1/call` 地址当作替代 MCP URL。

参考：[官方 onboarding](https://github.com/openai/tunnel-client/blob/v0.0.15/docs/onboarding.md)、[权限](https://github.com/openai/tunnel-client/blob/v0.0.15/docs/permissions.md)、[配置](https://github.com/openai/tunnel-client/blob/v0.0.15/docs/configuration.md)。
