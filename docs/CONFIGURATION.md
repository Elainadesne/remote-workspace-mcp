# 配置参考

配置是操作者维护的本地 UTF-8 JSON 文件，不是远程客户端可修改的参数。使用绝对路径传入 `--config`，大小不超过 64 KiB；重复 JSON 键、未知字段和错误类型会使启动失败。无需网络即可运行 `--check-config`。

## 最小配置

```json
{
  "projects": {"demo": "/absolute/path/to/reviewed-project"},
  "codex": {"enabled": false, "threads": {}, "imports": {}}
}
```

`codex` 可整个省略。没有自动发现项目、自动授权会话或默认导入文件。

## 字段

| 字段 | 含义 |
| --- | --- |
| `projects` | 必需，非空对象，别名映射到现有目录绝对路径 |
| 项目别名 | 1–64 个 ASCII 字母、数字、下划线或连字符，首字符需为字母或数字；别名对客户端可见 |
| `codex.enabled` | 布尔值，默认 false，仅控制实际 Codex App Server 读取 |
| `codex.binary` | enabled=true 时必需，现有可信可执行文件的绝对路径，不接受命令和额外参数 |
| `codex.home` | enabled=true 时必需，已存在的 Codex 用户数据目录绝对路径 |
| `codex.threads` | 默认空对象，明确的会话 ID → 项目别名；不扫描历史补全 |
| `codex.imports` | 默认空对象，导入别名 → `{ "project": "demo", "path": "chat-exports/reviewed.json" }` |

所有字符串最长 4096 字符。thread ID 与 import 别名不能重复；映射的项目必须存在。`binary`、`home` 若显式填写，即使 enabled=false 也必须是绝对路径。`enabled=false` 时会话 ID 可仍显示在 `list_threads` 中，但读取会明确报“disabled”；导入文件不依赖 Codex enabled。

不展开配置中的 `~` 或 `$HOME`，请自己填写正确绝对路径。项目根必须为规范路径，不能经过符号链接或 `..`，不能是 `/`、当前 HOME 或常见系统根目录，也不能包含隐藏/常见敏感名称组件。配置了 Codex home 时，它与任何项目根不能互相包含。保护不是完整敏感路径清单，操作者仍必须选择真正的项目目录。

配置改动后重启桥接或前台隧道进程，不会动态热加载。配置含本机路径和会话 ID，建议保存在源码目录之外并限制本地读取权限，绝不提交到 Git。`.gitignore` 是误提交防护，不是安全访问控制。

## 审阅后的导入文件

在已授权项目内创建 `chat-exports/reviewed.json`，其格式为：

```json
{
  "messages": [
    {"role": "user", "text": "A reviewed question"},
    {"role": "assistant", "text": "A reviewed public answer"}
  ]
}
```

对应配置：

```json
{
  "projects": {"demo": "/absolute/path/to/reviewed-project"},
  "codex": {
    "enabled": false,
    "threads": {},
    "imports": {
      "reviewed-example": {"project": "demo", "path": "chat-exports/reviewed.json"}
    }
  }
}
```

仓库的 `examples/reviewed.json` 是合成样例，需主动复制到自己的授权项目并配置才可读取。路径必须为允许的相对文件路径。导入与普通文件一样限制为 256 KiB；仅保留 role 为 user/assistant 且 text 为字符串的条目，其他角色不返回。格式错误会拒绝读取，不静默更换数据来源。

注意：授权整个项目目录意味着导入文件也可能被 `read_file` 原样读取，绕过 `read_thread` 的角色筛选/尽力遮蔽。因此导入文件自身必须事先清理，只放准备共享的公开文字；不要把原始全量对话导出放入共享项目。

## 工具参数与限制

- `list_projects`：无参数
- `list_files`：必需 project；path 默认空字符串（根目录）
- `read_file`：必需 project、path
- `search_text`：必需 project、query；path 默认根目录。字面量、区分大小写，不执行正则；query 为 1–200 字符
- `list_threads`：必需 project
- `read_thread`：必需 project、thread_id；cursor 可选，仅 Codex 分页接受

不接受额外参数。所有参数必须为字符串且最长 4096 字符。文件路径使用 `/` 分隔，不接受反斜杠、绝对路径、`..`、空中间组件、隐藏项或符号链接。

搜索最多访问 200 个目录、500 个文件、100 个命中，深度最多 8 层。单个结果行最多返回 500 字符，`truncated=true` 表示范围或结果限额达到，应用更窄的路径继续搜索。不可读、非 UTF-8、二进制和过大文件会在搜索时跳过，所以未找到结果不证明内容不存在。

单层目录最多 10000 项；文件最大 256 KiB；stdin/HTTP 请求最大 64 KiB；App Server 单条协议响应最大 32 MiB；每页公开文字最多 2000 条或 1000000 字符。超限明确失败，不自动读取全部历史或更换成隐藏目录读取。

## 本地 HTTP API

这不是 MCP HTTP 端点。HTTP 仅绑定 `127.0.0.1`，单进程串行处理，适合单人受控集成，不是公网、多用户网关。

用 Bash 静默输入自己生成的足够随机的本地令牌（至少 32 字符），只存当前终端环境：

```bash
read -r -s -p 'Local bridge token: ' BRIDGE_TOKEN
printf '\n'
export BRIDGE_TOKEN
python3 -m bridge.server --config /absolute/path/to/config.json --transport http --port 8765
unset BRIDGE_TOKEN
```

Ctrl+C 退出后执行 unset。HTTP token 与隧道 runtime key 是不同凭据；stdio 不使用 BRIDGE_TOKEN。不要把真正令牌写成命令字面量，也不要让带令牌请求进入共享日志。

调用方发送 `POST http://127.0.0.1:8765/v1/call`，包含 `Authorization: Bearer <token>`、`Content-Type: application/json`、正确 Content-Length，正文例如：

```json
{"name":"list_files","arguments":{"project":"demo"}}
```

成功返回 `{"result": ...}`；错误返回带错误状态码的 `{"error": ...}`。拒绝浏览器 Origin、非本地 Host、分块传输和未认证请求。不要通过改 host、代理 header 或无认证转发绕过这些边界。
