# gh-ui CLI 用户说明书

`gh-ui` 是 `gh_quant_ui` 的命令行工具。安装后也可以用等价命令 `wx-official-cli` 调用同一入口，公众号缓存导出场景推荐用这个名字。它可以让用户或本地 agent 不打开桌面界面，也能查询数据、检查运行环境、调用微信文章、因子、回测等后端能力。

## 适用场景

- 已经有一个运行中的 `gh_quant_ui` 后端服务，希望用命令行直接调用。
- 需要在 macOS 或 Windows 上快速检查 CLI 是否能运行。
- 需要把常用查询、下载、更新、导出动作写进脚本或自动化流程。
- 需要给 agent 提供稳定、机器可读的 JSON 输出。

## 准备工作

本项目使用 Python 3.10+ 和 `uv`。

```bash
cd /Users/hedi/gh_ui_cli
uv run gh-ui --help
uv run wx-official-cli --help
```

如果系统还没有安装 `uv`，先按官方方式安装 `uv`，再回到本目录执行上面的命令。

真实业务数据默认读取本机数据目录：

```bash
~/local_data
```

如需修改数据目录，可以设置环境变量：

```bash
export DB_PATH="$HOME/local_data"
```

## 两种运行方式

### 方式一：连接已运行的后端服务

如果桌面端或 sidecar 已经启动，并监听 `127.0.0.1:8765`，推荐使用这种方式。它不要求 CLI 本地安装完整业务依赖。

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 health
uv run gh-ui --api-base http://127.0.0.1:8765 smoke --with-data-query
uv run gh-ui --api-base http://127.0.0.1:8765 data progress
```

也可以把地址写入环境变量，后续命令可省略 `--api-base`：

```bash
export GH_UI_API_BASE="http://127.0.0.1:8765"
uv run gh-ui health
```

### 方式二：直接加载 `gh_quant_ui` 源码

如果需要让 CLI 直接导入 `gh_quant_ui/api/main.py`，需要安装完整依赖：

```bash
uv run --extra full gh-ui doctor
```

如果 `gh_quant_ui` 不在默认位置，显式传入项目路径：

```bash
uv run --extra full gh-ui --source-root /path/to/gh_quant_ui doctor
```

## 首次自检

建议按顺序执行：

```bash
uv run gh-ui --help
uv run gh-ui deps
uv run gh-ui --api-base http://127.0.0.1:8765 health
uv run gh-ui --api-base http://127.0.0.1:8765 smoke --with-data-query
```

如果走源码模式，再执行：

```bash
uv run --extra full gh-ui doctor
uv run --extra full gh-ui coverage --summary
uv run --extra full gh-ui verify --with-data-query --windows-deps-preflight
```

`verify` 会输出完整 JSON 报告。重点看：

- `ok`: 当前检查是否通过。
- `completion_ready`: 是否满足完整跨平台验收。
- `next_actions`: 如果未完成，下一步该执行什么。

## 配置 Token

部分下载、更新和远程接口需要 Token。可以每次用参数传入：

```bash
uv run gh-ui data update stock stock_price --token "$GH_API_TOKEN" -p adj_type=forward
```

也可以保存到本机 profile，后续自动读取。profile 输出会隐藏 Token 明文。

```bash
uv run gh-ui profile set --api-token "$GH_API_TOKEN" --access-token "$GH_ACCESS_TOKEN" --server primary
uv run gh-ui profile get
uv run gh-ui profile clear
```

常用环境变量：

```bash
export GH_API_TOKEN="your-api-token"
export GH_ACCESS_TOKEN="your-access-token"
export GH_JYDB_SERVER="primary"
```

## 常用命令

### 查看服务健康状态

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 health
```

### 查看本地数据进度

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 data progress
```

### 查询股票代码

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 data query stock stock_code -p market=ashare -p limit=5
```

### 查询股票价格

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 data query stock stock_price \
  -p code=000001 -p start_date=2024-01-01 -p end_date=2024-02-01 -p limit=20
```

### 更新股票价格

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 data update stock stock_price \
  --token "$GH_API_TOKEN" -p adj_type=forward
```

如果已经通过 `profile set` 保存 Token，可以省略 `--token`。

### 查看微信配置

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 wechat config-get
```

### 自动检测微信缓存和解密 key

本地模式可以不启动桌面端后端，直接检查微信缓存路径和本地解密 key 状态：

```bash
uv run gh-ui wechat password-status
uv run gh-ui wechat password-auto
```

`password-auto` 的含义是：在用户已经打开并登录 PC 微信的前提下，扫描本机微信进程内存，提取本地 SQLCipher 数据库解密 key。它不是微信账号登录密码破解，也不能绕过登录。Windows 下会同时尝试 `Weixin.exe` 和旧版 `WeChat.exe` 进程名。

Windows 会自动尝试常见目录，包括：

- `%USERPROFILE%\Documents\WeChat Files`
- `%APPDATA%\Tencent\WeChat\WeChat Files`
- `%USERPROFILE%\xwechat_files`

如果你在微信里把缓存目录移动到了其他盘，CLI 也会尝试读取 Windows 注册表中的 WeChat/Weixin 数据保存路径，以及重定向后的 Documents 路径作为候选。如果仍然检测不到路径，可以先手动保存：

```bash
uv run gh-ui wechat config-set --json '{"wechat_files_path":"C:\\Users\\me\\Documents\\WeChat Files\\wxid_x\\db_storage"}'
```

### 按公众号名字导出本地缓存文章

先确保本机微信已登录。然后输入公众号名字，CLI 会在需要时自动执行 `password-auto` 获取本地数据库解密 key，再扫描已解密消息缓存，导入本地文章库，并用缓存里的 mp.weixin URL 抓取正文 HTML 写到本地目录。公众号名字匹配会容忍空格差异，例如输入 `Alpha研究` 也能匹配缓存中的 `Alpha 研究`：

```bash
uv run gh-ui wechat articles-cache-export "公众号名字" --limit 100 --output-dir ./wechat_articles
```

要生成目标验收报告，使用 `articles-cache-verify`。它会实际运行导出流程，并检查微信路径、数据库 key、文章数量和 HTML 文件是否写出；即使导出失败也会输出 `error` 和 `next_actions`。加 `--strict` 后任何一项不满足都会返回非零退出码：

```bash
uv run gh-ui wechat articles-cache-verify "公众号名字" --strict --save verify-wechat-cache.json
```

如果你已经手动配置好 `database_password`，并且不希望命令自动扫描进程，可以关闭自动获取 key：

```bash
uv run gh-ui wechat articles-cache-export "公众号名字" --no-auto-password
```

如果只想导出缓存里的标题、摘要、链接，不联网抓正文，可以关闭正文抓取：

```bash
uv run gh-ui wechat articles-cache-export "公众号名字" --no-fetch-html
```

输出目录会包含：

- `index.json`: 机器可读的文章清单。
- `index.csv`: Excel 可直接打开的文章清单，UTF-8 BOM 编码。
- `001-标题.html` 等本地 HTML 文件，默认优先保存抓取到的正文 HTML。

如果正文抓取失败，CLI 会生成占位 HTML，保留标题、摘要和微信原文链接；不会伪造正文内容。

### 搜索微信消息

先创建 `wechat_search.json`：

```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-05-25",
  "keyword": "机器人",
  "limit": 20
}
```

再执行：

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 wechat search --json @wechat_search.json
```

### 查询因子表

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 factor query factor_info --limit 20
```

### 运行回测

先准备 `backtest_config.json`，再执行：

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 backtest run --json @backtest_config.json
```

查询回测结果：

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 backtest result "$TASK_ID"
```

### 导出 Excel

先准备 `export.json`，再执行：

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 export excel --input @export.json --filename export
```

## 给 agent 使用

CLI 默认输出 JSON，适合程序解析。

查看当前可调用能力：

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 manifest --category cli
uv run gh-ui --api-base http://127.0.0.1:8765 manifest --category data
uv run gh-ui --api-base http://127.0.0.1:8765 manifest --category wechat
```

用稳定 ID 调用接口：

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 invoke route:GET:/api/health
uv run gh-ui --api-base http://127.0.0.1:8765 invoke 'route:GET:/api/{module}/{method}' \
  -p module=stock -p method=stock_code -p market=ashare -p limit=1
```

## 保存输出

很多命令支持 `--save`，可以把 JSON 结果保存到文件：

```bash
uv run gh-ui --api-base http://127.0.0.1:8765 verify --with-data-query --save verify.json
```

## 常见问题

### 连接失败

先确认后端服务是否已启动：

```bash
curl http://127.0.0.1:8765/api/health
```

如果没有响应，先启动 `gh_quant_ui` 桌面端或 sidecar。

### 提示缺少依赖

如果只是连接已运行的后端，优先使用 `--api-base`。如果必须走源码模式，再安装完整依赖：

```bash
uv run --extra full gh-ui doctor
```

### Token 缺失

下载、更新或远程接口如果提示需要 Token，可以选择传参：

```bash
--token "$GH_API_TOKEN"
```

也可以保存 profile：

```bash
uv run gh-ui profile set --api-token "$GH_API_TOKEN" --server primary
```

### Windows 验证未完成

单台 macOS 机器通过不代表完整跨平台验收完成。需要在 Windows 环境做两类验证。

第一类是 CLI runtime 验证：

```powershell
uv run gh-ui runtime-verify verify-windows.json
```

第二类是真实微信缓存验证。先打开并登录 Windows 微信，确认目标公众号文章已经出现在本机缓存里，然后运行：

```powershell
uv run gh-ui wechat articles-cache-verify "公众号名字" --strict --save verify-wechat-cache-windows.json
```

`verify-wechat-cache-windows.json` 中 `ok` 为 `true`，并且 `requirements.wechat_path_detected`、`requirements.database_key_available`、`requirements.articles_exported`、`requirements.html_files_written` 都为 `true`，才说明真实 Windows 微信缓存链路跑通。如果 `ok` 为 `false`，先看 `error` 和 `next_actions` 判断是路径、`Weixin.exe` / `WeChat.exe` 进程权限、数据库 key、公众号缓存，还是输出目录写入问题。

然后合并 macOS source、Windows runtime 和 Windows 微信缓存报告：

```bash
uv run gh-ui verify-merge verify-macos.json verify-windows.json verify-wechat-cache-windows.json --strict-goal
```

## 推荐日常流程

1. 启动 `gh_quant_ui` 桌面端或 sidecar。
2. 执行 `uv run gh-ui --api-base http://127.0.0.1:8765 health`。
3. 执行 `uv run gh-ui --api-base http://127.0.0.1:8765 smoke --with-data-query`。
4. 保存 Token 到 profile。
5. 使用 `data`、`wechat`、`factor`、`backtest` 等子命令完成具体任务。
