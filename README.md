# gh_ui_cli

`gh_ui_cli` 是面向本地 agent、脚本和 CI 的命令行工具，**完整覆盖原 `gh_quant_ui` 桌面端的所有后端能力**。

**全模块已独立**：从 v0.3 起，**所有 7 个模块**（wechat / system / data / factor / backtest / ai / remote）的核心子命令都自带本地实现，**不再需要 `gh_quant_ui` 源码或运行中的 sidecar**。

当前能力覆盖：

- 81 个本地 capability（`op:wechat:* / op:system:* / op:data:* / op:factor:* / op:backtest:* / op:ai:* / op:remote:*`）
- 73 条 HTTP route → local capability 映射，`gh-ui` 子命令自动走本地分发
- 283 个测试全部通过（unittest + pytest）

面向普通用户的安装、连接、常用命令和排障说明见 [USER_GUIDE.md](USER_GUIDE.md)；
完整设计与分阶段实施记录见 [docs/superpowers/specs/2026-05-26-wechat-standalone-design.md](docs/superpowers/specs/2026-05-26-wechat-standalone-design.md)。

设计原则:

- 默认输出 JSON，便于 agent 解析。
- 所有模块走本地 `gh_ui_cli/<module>/` 实现，零外部进程依赖。
- 显式 `--api-base` 时回落 HTTP 转发；无 api-base 时优先本地分发。
- 私有依赖（JyPy / gh_backtest）lazy import，缺失时返回结构化错误码 `JYPY_MISSING` / `GH_BACKTEST_MISSING`。
- 路径通过参数或环境变量覆盖，适配 macOS 和 Windows。

## 模块矩阵

| 模块 | 子命令前缀 | 核心能力 | 私有依赖 |
|------|-----------|--------|---------|
| `wechat/` | `gh-ui wechat *` | 配置 / 密钥扫描 / SQLCipher 解密 / 消息检索 / 联系人 / 公众号同步 / 图片解密 / LLM / PDF 报告 / 股票复盘 | 无（pycryptodome / akshare / pyecharts 等公开库） |
| `system/` | `gh-ui health / config / logs / feedback / export / auth` | 健康检查 / 路径配置 / 日志 ring buffer / 反馈本地落盘 / Excel 导出 / hedicxl.cn 认证代理 | 无 |
| `data/` | `gh-ui data query / files / progress / download / update` | 80+ 个 (module, method) → parquet 通用映射 + 通用过滤器 | download / update 需 JyPy |
| `factor/` | `gh-ui factor *` | 本地 factor_info / factors 目录查询 + level1/level2 树 | download 需 sqlalchemy + JYDB |
| `backtest/` | `gh-ui backtest *` | parquet readiness / 组合 CRUD / 任务调度 | run 需 gh_backtest |
| `ai/` | `gh-ui ai *` | 研报复现工作区扫描 / PDF 候选 / codex+claude runner 后台任务 | 需本地 codex / claude CLI 在 PATH |
| `remote/` | `gh-ui remote me / tokens *` | hedicxl.cn 账号 + API Token CRUD | 无（直接 httpx） |

## 安装与运行

推荐使用 `uv`:

```bash
cd /Users/hedi/gh_ui_cli
uv run gh-ui --help
```

首次在干净环境中调用真实业务端点时安装完整依赖:

```bash
uv run gh-ui deps
uv run gh-ui deps --platform win32
uv run --extra full gh-ui doctor
```

如果 `gh_quant_ui` 不在默认位置，显式传入:

```bash
uv run --extra full gh-ui --source-root /path/to/gh_quant_ui doctor
```

常用环境变量:

- `GH_WX_DATA_DIR`: 微信模块本地数据根目录，默认 `~/.gh_ui_cli/wechat`
- `DB_PATH`: 本地 parquet 数据目录，默认 `~/local_data`
- `FACTOR_PATH`: 因子 parquet 数据目录，默认跟随 `DB_PATH`
- `GH_EXPORT_PATH`: Excel 导出目录，默认 `~/Desktop`
- `REPORT_REPRODUCE_PATH`: AI 报告复现工作区，默认 `~/report_reproduce`
- `GH_FACTOR_DB_URL`: 因子 SQL 在线下载，例如 `mysql+pymysql://user:pw@host:port/factor`
- `GH_UI_API_BASE`: 显式指定 sidecar 地址（设置后跳过本地分发走 HTTP），例如 `http://127.0.0.1:8765`
- `GH_API_TOKEN`: 聚源/JYDB 完整 API Token（data download/update 用）
- `GH_ACCESS_TOKEN`: hedicxl.cn 登录后的 access token（remote / auth active-token 用）
- `GH_JYDB_SERVER`: 聚源服务，`primary` 或 `secondary`
- `GH_UI_CLI_PROFILE`: CLI profile 文件路径，默认 `~/.gh_ui_cli/profile.json`
- `GH_QUANT_UI_PATH`（兼容）: 旧 source mode 下指向 `gh_quant_ui` 项目根；独立化后不再需要
- `JYPY_PATH` / `GH_BACKTEST_PATH`（兼容）: 把这两个私有库源码目录加到 `PYTHONPATH` 才能用 data download / backtest run

给 agent 长期调用时，可以把常用 token 和 server 写入本地 profile；显式命令行参数优先，其次环境变量，最后读取 profile。profile 输出会隐藏 token 明文。

```bash
uv run gh-ui profile set --api-token "$GH_API_TOKEN" --access-token "$GH_ACCESS_TOKEN" --server primary
uv run gh-ui profile get
uv run gh-ui profile clear
```

## 快速试用（推荐：不依赖 `gh_quant_ui`）

```bash
# 健康检查（本地分发，不需要 sidecar）
uv run gh-ui health
uv run gh-ui config get-paths

# 微信本地工具
uv run gh-ui wechat config-get
uv run gh-ui wechat password-status

# 本地 parquet 数据
uv run gh-ui data progress
uv run gh-ui data files
uv run gh-ui data query stock stock_code -p market=ashare --limit 5

# 因子库 / 回测 / AI 报告复现
uv run gh-ui factor tables
uv run gh-ui backtest check-data
uv run gh-ui ai status

# 远程账号 (需要 GH_ACCESS_TOKEN 或 profile)
uv run gh-ui remote me
```

需要让 agent 知道有哪些本地能力可调用：

```bash
uv run gh-ui manifest --category cli
uv run gh-ui manifest --category data
uv run gh-ui manifest --category wechat
```

## 兼容旧模式（HTTP / source）

如果桌面端 sidecar 已经在 `127.0.0.1:8765` 运行，显式 `--api-base` 跳过本地分发走 HTTP：

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 smoke --with-data-query
uv run gh-ui --api-base http://127.0.0.1:8765 wechat config-get
```

仍想加载 `gh_quant_ui` 源码做 source-mode 验证：

```bash
uv run --extra full gh-ui --source-root /path/to/gh_quant_ui doctor
uv run --extra full gh-ui --source-root /path/to/gh_quant_ui verify --with-data-query
```

## 跨平台验收工具（保留）

```bash
uv run --extra full gh-ui doctor
uv run --extra full gh-ui routes --prefix /api/wechat
uv run --extra full gh-ui data modules
uv run --extra full gh-ui coverage --summary
uv run --extra full gh-ui verify --with-data-query --windows-deps-preflight
uv run --extra full gh-ui manifest --category data --save data-manifest.json
uv run --extra full gh-ui smoke --with-data-query
```

如果桌面端 sidecar 或 `uvicorn main:app` 已经在 `127.0.0.1:8765` 运行，可以不安装完整业务依赖，直接走 HTTP 调用:

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 smoke --with-data-query
uv run gh-ui --api-base http://127.0.0.1:8765 doctor
uv run gh-ui --api-base http://127.0.0.1:8765 verify --with-data-query
uv run gh-ui --api-base http://127.0.0.1:8765 routes --prefix /api/wechat
uv run gh-ui --api-base http://127.0.0.1:8765 health
uv run gh-ui --api-base http://127.0.0.1:8765 data progress
uv run gh-ui --api-base http://127.0.0.1:8765 feedback submit --content "agent smoke"
uv run gh-ui --api-base http://127.0.0.1:8765 wechat config-get
uv run gh-ui --api-base http://127.0.0.1:8765 wechat articles-account-categories "$MP_ID"
uv run gh-ui --api-base http://127.0.0.1:8765 manifest --category wechat
```

`coverage --summary` 是给 agent 使用的覆盖证明入口。它会同时检查:

- FastAPI 路由操作是否都能通过 `gh-ui api request ...` 触达。
- 每个 manifest/coverage 推荐的 `preferred` 命令是否能被当前 CLI parser 解析，避免 agent 拿到不可执行的推荐命令。
- 通用数据页的动态能力是否逐项可调用，包括 `METHOD_MAP`、`DOWNLOAD_MAP`、`STREAM_DOWNLOAD_MAP` 和 `UPDATE_MAP`。
- `factor_data` 的 15 类因子表是否都具备查询、下载、更新命令。
- 前端 `src/lib/*.ts` 中实际使用的 API 路径是否都能匹配后端路由，避免只覆盖后端、遗漏桌面 UI 已暴露的功能入口。

当前期望结果中 `all_callables` 应为 `true`，`missing_route_operations` 应为空。

`deps` 是 source 模式的依赖预检入口。它不会导入 `gh_quant_ui`，只解析 `api/requirements.txt` 并报告当前平台适用、已安装、缺失和跳过的依赖；如果缺失 `ddddocr`、`pyarrow`、`scipy` 等重依赖，优先考虑走 `--api-base` 复用已运行 sidecar，或预留时间完成 full install。需要在 macOS 上预检 Windows 依赖时使用 `--platform win32`；需要给 CI 或 agent 自动化做硬门禁时加 `--strict`，存在缺失依赖会返回非零退出码。

`verify` 是面向目标验收的总入口，会汇总依赖、CLI 覆盖和 smoke 结果，并额外输出 `completion_ready` 与 `goal_evidence`。在单台 macOS 机器上即使所有本机检查通过，`completion_ready` 仍会保持 `false`，直到 Windows runtime 也在 Windows 环境完成验证；这避免 agent 把本机通过误判成完整跨平台完成。需要让当前检查失败时返回非零退出码用 `--strict`，需要强制完整目标验收用 `--strict-goal`。`--windows-deps-preflight` 只在 source 模式解析 `api/requirements.txt`；HTTP-only 模式不会强制要求本地 `gh_quant_ui` 源码，会把该项标记为 skipped。

`verify-plan` 会输出机器可读的最终验收计划，不导入 `gh_quant_ui` 源码，也不访问 sidecar。agent 可以先读取它，拿到 source 覆盖、agent profile、macOS runtime、Windows runtime 各自需要的证据和平台命令:

```bash
uv run gh-ui verify-plan
```

`verify-bundle` 会把当前 source 报告、`verify-plan.json`、`manifest-cli.json` 和 Windows 续跑说明写到一个交接目录，方便把 macOS 侧证据交给 Windows 机器或 CI 继续补齐:

```bash
uv run --extra full gh-ui verify-bundle verify-bundle --with-data-query --strict
```

`ci-status` 是只读的 GitHub Actions 证据检查入口。它会检查远端是否已经有可 dispatch 的 workflow、成功 run，以及未过期的 Windows artifact，并输出 dispatch、下载 artifact、合并验收报告的命令；远端缺 workflow、缺成功 run、缺 artifact 或 artifact 已过期时会在 `next_actions` 里说明缺口:

```bash
uv run gh-ui ci-status --repo Hedicx2020/ghfe_web --workflow ci.yml --mac-report verify-macos.json --artifact-dir verify-artifacts
```

如果 GitHub artifact 配额导致上传失败，但 workflow 日志里已经打印了 `GH_UI_VERIFY_REPORT_BEGIN` / `GH_UI_VERIFY_REPORT_END` 包裹的报告，可以直接从日志提取 Windows 报告:

```bash
uv run gh-ui ci-log-report <RUN_ID> --repo Hedicx2020/ghfe_web --platform win32 --save verify-windows.json --strict
```

跨平台验收时，让 macOS 和 Windows 各自保存一份 `verify` 报告，再合并判断:

```bash
uv run --extra full gh-ui verify --with-data-query --windows-deps-preflight --strict --save verify-macos.json
uv run gh-ui verify-merge verify-macos.json verify-windows.json --strict-goal
```

`verify-merge` 也可以直接接收报告目录，会递归读取其中的 `*.json`。这适合 GitHub Actions artifact 下载后的目录结构:

```bash
gh run download --name gh-ui-verify-Windows-py3.12 --dir verify-artifacts
uv run gh-ui verify-merge verify-macos.json verify-artifacts --strict-goal
```

合并时会校验证据来源：`windows_runtime_verified` 只接受 `current_platform=win32` 的报告，`mac_runtime_verified` 只接受 `current_platform=darwin` 的报告，完整功能覆盖只接受 source 模式报告，避免把 HTTP-only 或错误平台报告误当成完整验收。输出里的 `evidence_sources` 会列出每个证据项来自哪个输入报告，`completion_requirements` 会逐项给出最终门禁状态；如果仍未完成，`next_actions` 会按缺失门禁给出可执行的下一步命令，便于 agent 做机器审计和续跑。

`completion_requirements.source_cli_coverage` 是由 `route_operations_callable`、`source_dynamic_capabilities_verified`、`frontend_api_references_verified` 和 `preferred_commands_parseable` 组成的 source 模式组合门禁；`agent_profile` 是单独门禁。这样 agent 能区分“CLI 功能覆盖已证明”和“无交互 profile 烟测还未证明”。

Windows 侧如果只有已运行 sidecar，也可以保存 HTTP 模式报告:

```powershell
uv run gh-ui --api-base http://127.0.0.1:8765 verify --with-data-query --strict --save verify-windows.json
```

CI 中会在 macOS / Windows matrix 上安装构建出的 wheel，然后运行 `gh-ui runtime-verify` 启动临时 mock sidecar，生成 `verify-${runner.os}-py${python-version}.json` 并上传 artifact。这个报告可作为 `verify-merge` 的 Windows runtime 证据；完整完成仍需要至少一份 source 模式报告证明动态数据能力和前端 API 引用覆盖。

安装后的 CLI 也内置同样的轻量 runtime 验证入口，不依赖仓库里的 `scripts/` 目录:

```bash
gh-ui runtime-verify verify-runtime.json
```

该命令会临时启动一个 mock API-base sidecar，再调用当前 Python 环境里的 `gh-ui verify --with-data-query --strict --save ...` 生成报告；适合 CI、Windows 机器或 agent 在只安装 wheel 的环境中证明 CLI 入口和 HTTP 调用链路可运行。

`doctor`、`routes`、`coverage`、`manifest`、`smoke` 都支持 `--api-base`。HTTP 模式不会导入 `gh_quant_ui` 源码，而是通过 `/openapi.json` 和 `/api/health` 检查已运行的服务，适合桌面端 sidecar 已启动、agent 只需要远程控制后端的场景。

`smoke` 是给 macOS / Windows 都能执行的一键自检入口。默认检查源项目加载、路由覆盖和 API health；加 `--with-data-query` 后会额外读取一行本地 A 股代码数据，用来证明本地 parquet 查询链路可用。
它也会执行一次临时 profile 的写入、读取和脱敏输出检查，确保 agent 在无交互环境下能复用本地 token/server 配置。

`manifest` 是给 agent 使用的可调用清单。它会输出稳定的 `id`、`category`、`command`、`generic`、`invoke`、`argv`、`generic_argv`、`invoke_argv`、`command_shell`、`generic_shell`、`invoke_shell`、`required_env`、路径参数、OpenAPI 参数、请求体 schema、前端 API 来源文件位置和是否需要替换路径占位符。源码模式下包含动态数据能力、因子表能力和 `src/lib/*.ts` 前端调用来源；`--api-base` 模式下从 `/openapi.json` 派生路由清单，适合复用已启动的桌面 sidecar。

`manifest --category cli` 会暴露本地操作入口，例如 `profile get/set/clear`、`doctor`、`deps`、`coverage --summary`、`smoke`、`verify`、`verify-plan`、`verify-bundle`、`ci-status`、`ci-log-report`、`runtime-verify` 和 `verify-merge`。它不需要导入 `gh_quant_ui` 源码或访问 sidecar，适合作为 agent 初始自检入口。这些条目没有 `invoke_argv`，agent 应直接执行 `argv` 或按平台选择 `command_shell.posix`、`command_shell.powershell`、`command_shell.cmd`。

给程序调用时优先使用 `invoke_argv`、`argv` 或 `generic_argv` 数组，而不是解析 shell 字符串。数组会自动带上当前 manifest 使用的全局参数，例如 `--api-base http://127.0.0.1:8765`，并把 token 统一表示为 `<GH_API_TOKEN>` 或 `<GH_ACCESS_TOKEN>`；调用前读取 `required_env` 就能知道需要准备 `GH_API_TOKEN` 还是 `GH_ACCESS_TOKEN`。如果调用方只能执行 shell 字符串，使用对应字段里的 `posix`、`powershell` 或 `cmd`，它们会分别渲染为 `$GH_API_TOKEN`、`$env:GH_API_TOKEN`、`%GH_API_TOKEN%` 这类平台原生环境变量。

调用具体端点前，agent 可以读取条目的 `parameters` 判断 query/path 参数，读取 `request_body_required`、`request_content_types` 和 `request_body_schema` 生成 JSON body。若 `request_body_schema` 是 `$ref`，对应定义在顶层 `openapi_components.schemas` 中。

源码模式下，route 条目还会包含 `frontend_reference_paths`、`frontend_sources` 和 `frontend_reference_count`。这些字段用于把 CLI 可调用端点反查到桌面 UI 的 TypeScript API 包装器，方便 agent 从用户口中的页面功能定位到稳定 CLI 调用。

HTTP 模式下 `manifest --category data` 会至少暴露动态数据查询、下载、更新入口：`route:GET:/api/{module}/{method}`、`route:POST:/api/download/{module}/{method}`、`route:POST:/api/update/{module}/{method}`；具体 `module` 和 `method` 通过 `-p module=... -p method=...` 传入。HTTP 模式下 `manifest --category factor_data` 也会暴露 `route:GET:/api/factor/db/query/{table}`、`route:POST:/api/factor/db/download/{table}`、`route:POST:/api/factor/db/update/{table}`。源码模式下还会额外展开 `METHOD_MAP`、`DOWNLOAD_MAP`、`UPDATE_MAP` 和具体因子表能力。

`invoke` 是给 agent 的稳定 ID 调用入口，直接接受 manifest 中的 `id`。路径参数和 query 参数都用 `-p KEY=VALUE`，其中路径占位符会自动替换并从 query 参数中移除；需要 JSON body 的端点使用 `--json`、`@file` 或 `-`。例如:

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 invoke route:GET:/api/health
uv run gh-ui --api-base http://127.0.0.1:8765 invoke 'route:GET:/api/wechat/articles/accounts/{mp_id}/categories' -p mp_id=abc
uv run gh-ui --api-base http://127.0.0.1:8765 invoke route:POST:/api/wechat/messages/search --json @wechat_search.json
uv run gh-ui --api-base http://127.0.0.1:8765 wechat articles-fetch "$ARTICLE_ID"
uv run gh-ui --api-base http://127.0.0.1:8765 wechat articles-sync-by-category-preview --category-id 1 --mode incremental
uv run gh-ui --api-base http://127.0.0.1:8765 invoke 'route:GET:/api/{module}/{method}' -p module=stock -p method=stock_code -p market=ashare -p limit=1
uv run gh-ui --api-base http://127.0.0.1:8765 invoke 'route:POST:/api/update/{module}/{method}' -p module=stock -p method=stock_price --token "$GH_API_TOKEN" -p adj_type=forward
uv run gh-ui --api-base http://127.0.0.1:8765 invoke 'route:GET:/api/factor/db/query/{table}' -p table=factor_info -p limit=20
uv run gh-ui invoke data:query:stock/stock_code -p market=ashare -p limit=1
uv run gh-ui invoke data:update:stock/stock_price --token "$GH_API_TOKEN" -p adj_type=forward
uv run gh-ui invoke data:update:stock/stock_price -p adj_type=forward  # 已设置 profile 时可省略 --token/--server
```

## 通用 API 调用

所有 FastAPI 路由都可通过 `api request` 调用:

```bash
uv run --extra full gh-ui health
uv run --extra full gh-ui config get-paths
uv run --extra full gh-ui config set-paths --db-path ~/local_data
uv run --extra full gh-ui data progress
uv run --extra full gh-ui data files
uv run --extra full gh-ui logs --limit 50
uv run --extra full gh-ui export excel --input @export.json --filename export
uv run --extra full gh-ui feedback submit --json @feedback.json
uv run --extra full gh-ui api request GET /api/stock/stock_price \
  -p code=000001 -p start_date=2024-01-01 -p end_date=2024-02-01 -p limit=5
uv run --extra full gh-ui api request POST /api/wechat/messages/search \
  --json '{"start_date":"2026-01-01","end_date":"2026-05-25","keyword":"机器人","limit":20}'
```

含路径参数的路由直接替换花括号占位即可:

```bash
uv run --extra full gh-ui wechat articles-analysis-get 1
uv run --extra full gh-ui backtest result "$TASK_ID"
```

文件上传路由:

```bash
uv run --extra full gh-ui backtest upload portfolio.xlsx
```

## 常用命令

查询本地数据:

```bash
uv run --extra full gh-ui data query stock stock_price \
  -p code=000001 -p start_date=2024-01-01 -p end_date=2024-01-31 --limit 10
```

下载或更新数据:

```bash
uv run --extra full gh-ui data download stock stock_price --token "$GH_API_TOKEN" \
  -p adj_type=forward -p start_date=2020-01-01
uv run --extra full gh-ui data update stock stock_price --token "$GH_API_TOKEN" -p adj_type=forward
uv run --extra full gh-ui data update stock stock_price -p adj_type=forward  # 已设置 profile 时
```

因子与回测:

```bash
uv run --extra full gh-ui factor catalog
uv run --extra full gh-ui factor values "$FACTOR_ID" -p start_date=2024-01-01
uv run --extra full gh-ui factor rank-list -p ind_code=CI005001 -p year=2024
uv run --extra full gh-ui factor rank-detail "$FACTOR_ID" --ind-code CI005001
uv run --extra full gh-ui factor barra-returns -p start_date=2024-01-01 -p end_date=2024-12-31
uv run --extra full gh-ui factor analyze --json @factor_analyze.json
uv run --extra full gh-ui factor query factor_info --limit 20
uv run --extra full gh-ui backtest check-data
uv run --extra full gh-ui backtest upload-json --json @portfolio.json
uv run --extra full gh-ui backtest uploaded-portfolio "$UPLOAD_ID"
uv run --extra full gh-ui backtest run --json @backtest_config.json
uv run --extra full gh-ui backtest monitoring --json @monitoring.json
uv run --extra full gh-ui backtest monitoring-holdings --upload-id "$UPLOAD_ID" --date 2024-01-02
```

认证:

```bash
uv run --extra full gh-ui auth verify --token "$GH_API_TOKEN"
uv run --extra full gh-ui auth login --json @login.json
uv run --extra full gh-ui auth active-token --access-token "$GH_ACCESS_TOKEN"
uv run --extra full gh-ui auth active-token  # 已设置 profile 时
```

远程账户 / API Token:

```bash
uv run --extra full gh-ui remote me --access-token "$GH_ACCESS_TOKEN"
uv run --extra full gh-ui remote tokens --access-token "$GH_ACCESS_TOKEN"
uv run --extra full gh-ui remote token-generate --access-token "$GH_ACCESS_TOKEN" --name agent-token
uv run --extra full gh-ui remote token-revoke "$TOKEN_ID" --access-token "$GH_ACCESS_TOKEN"
uv run --extra full gh-ui remote me  # 已设置 profile 时
```

AI 报告复现:

```bash
uv run --extra full gh-ui ai status
uv run --extra full gh-ui ai pdf-candidates -p workspace="$HOME/report_reproduce"
uv run --extra full gh-ui ai start --json @report_reproduce.json
uv run --extra full gh-ui ai task "$TASK_ID"
uv run --extra full gh-ui ai cancel "$TASK_ID"
```

微信:

```bash
uv run --extra full gh-ui wechat config-get
uv run --extra full gh-ui wechat sessions
uv run --extra full gh-ui wechat search --json @wechat_search.json
uv run --extra full gh-ui wechat stock-picks --json @stock_pick.json
uv run --extra full gh-ui wechat contacts-export
uv run --extra full gh-ui wechat image-list -p month=2026-05 -p limit=20
uv run --extra full gh-ui wechat articles-categories
uv run --extra full gh-ui wechat articles-category-create --name "研究"
uv run --extra full gh-ui wechat articles-account-set-categories "$MP_ID" --category-id 1
uv run --extra full gh-ui wechat articles-sync-by-category --json @sync_by_category.json
```

启动本地 API 服务:

```bash
uv run --extra full gh-ui serve --host 127.0.0.1 --port 8765
```

## 覆盖边界

CLI 覆盖原 `gh_quant_ui` 后端功能的方式:

- **本地分发 (默认)**: 73 条 HTTP route 已映射到 81 个 `op:*` capability，所有 `gh-ui <module> <cmd>` 子命令优先走本地实现，零外部进程依赖。
- **HTTP 转发 (兼容)**: 显式 `--api-base` 时绕过本地分发，对接已运行的 `gh_quant_ui` sidecar。
- **Source mode (兼容)**: 显式 `--source-root` 时加载 `gh_quant_ui/api/main.py` FastAPI app，主要供原项目仓库内的回归测试用。
- **`api request` / `routes` / `coverage` / `manifest`**: 对 agent 高频流程提供稳定子命令；`coverage` / `routes` 仍读 FastAPI app，独立模式下可省略。

**底层平台限制**:
- 微信 macOS 重签名 / Windows pymem 内存扫描：与桌面端权限要求一致。
- `data download/update`：需要 JyPy 私有库 + JYDB Token。无 JyPy 时返回 `JYPY_MISSING` 错误码。
- `backtest run`：需要 gh_backtest 私有库。无 gh_backtest 时返回 `GH_BACKTEST_MISSING` 错误码。
- `factor download`：需要 SQLAlchemy + pymysql + `GH_FACTOR_DB_URL`。
- `ai report-start`：需要本机 `codex` 或 `claude` CLI 在 PATH 中。

凡是不依赖以上私有库 / 外部 CLI 的能力，**都不再需要 `gh_quant_ui` 源码**。

## 跨平台约定

macOS / Linux shell（独立模式优先，私有依赖按需）:

```bash
# 完全独立化：不需要设置 GH_QUANT_UI_PATH
uv run gh-ui health
uv run gh-ui wechat password-status

# 仅在用 data download / backtest run 时才需要私有库
export JYPY_PATH="$HOME/JyPy"
export GH_BACKTEST_PATH="$HOME/gh_backtest/src"
uv run gh-ui data download stock stock_code --token "$GH_API_TOKEN"
```

Windows PowerShell:

```powershell
# 完全独立化
uv run gh-ui health
uv run gh-ui wechat password-status

# 仅 data download / backtest run 时设置
$env:JYPY_PATH = "C:\Users\you\JyPy"
$env:GH_BACKTEST_PATH = "C:\Users\you\gh_backtest\src"
uv run gh-ui data download stock stock_code --token $env:GH_API_TOKEN
```

CLI 自身只使用 `pathlib`、环境变量、FastAPI in-process 调用和可选 HTTP 调用，路径参数都可通过 `--source-root`、`--db-path`、`--factor-path`、`--export-path` 显式传入。平台相关行为仍保留在原后端中：例如 macOS 微信重签名只在 macOS 有意义，Windows 微信密钥扫描依赖 Windows 权限和 `pymem`。

仓库包含 GitHub Actions 轻量矩阵 `.github/workflows/ci.yml`，会在 `macos-latest` 和 `windows-latest` 上覆盖 Python 3.10 / 3.12，验证单元测试、`gh-ui --help`、mock sidecar 集成测试、`uv build` 包构建，以及安装构建出的 wheel 后再次运行 `gh-ui` console script。该集成测试会实际运行 `--api-base manifest`、`invoke`、`smoke --with-data-query` 和 `verify --with-data-query --strict`；安装后 smoke 会跑 `gh-ui deps --requirements tests/fixtures/minimal_requirements.txt --strict`，再跑 `gh-ui runtime-verify ...` 生成可上传的 runtime 报告，证明 wheel 在干净 Python 环境里的入口和基础 HTTP 调用链路可用。真实业务 smoke/verify 依赖私有的 `gh_quant_ui`、JyPy、`gh_backtest` 和本地数据目录，需在有这些路径的机器上运行 `uv run --extra full gh-ui verify --with-data-query --windows-deps-preflight --strict`。
