# wx_official_cli

`wx_official_cli` 是给本地 agent 使用的微信公众号缓存文章导出工具。目标很窄：用户输入公众号名字，CLI 自动检测 Windows 微信缓存路径，必要时从已登录且正在运行的微信进程中提取本地数据库解密 key，然后把本机缓存里的公众号文章导出到本地目录。

这个工具只处理本机已经登录、已经缓存到本地的微信数据。它不是微信账号密码破解工具，也不能绕过登录或获取本机没有缓存过的文章。

## 安装

```bash
git clone https://github.com/Hedicx2020/wx_official_cli.git
cd wx_official_cli
uv sync
```

本地开发时直接用：

```bash
uv run wx-official-cli --help
```

安装 wheel 后用：

```bash
wx-official-cli --help
```

## 给 Agent 的最短流程

1. 让用户在 Windows 上打开并登录 PC 微信，确认目标公众号文章已经出现在本机消息缓存里。
2. 检查路径和 key 状态：

```bash
uv run wx-official-cli status
```

3. 按公众号名字导出：

```bash
uv run wx-official-cli export "公众号名字" --limit 100 --output-dir ./wechat_articles
```

`crawl` 是 `export` 的等价别名，方便 agent 按自然任务名调用：

```bash
uv run wx-official-cli crawl "公众号名字" --limit 100 --output-dir ./wechat_articles
```

4. 需要机器可审计的验收报告时运行：

```bash
uv run wx-official-cli verify "公众号名字" --strict --save verify-wechat-cache-windows.json
```

`verify` 会实际运行导出流程，并检查微信缓存路径、数据库 key、文章数量和 HTML 文件写出情况。`--strict` 会在任一要求不满足时返回非零退出码。

## Agent Manifest

```bash
uv run wx-official-cli manifest
```

manifest 只暴露公众号导出相关命令：

- `wx-official-cli status`
- `wx-official-cli export <ACCOUNT_NAME>`
- `wx-official-cli crawl <ACCOUNT_NAME>`
- `wx-official-cli verify <ACCOUNT_NAME> --strict --save <VERIFY_JSON>`

## Windows 自动检测范围

CLI 会优先自动检测常见 Windows 微信目录，包括：

- `%USERPROFILE%\Documents\WeChat Files`
- `%APPDATA%\Tencent\WeChat\WeChat Files`
- `%USERPROFILE%\xwechat_files`
- 注册表里记录的 WeChat/Weixin 数据保存路径
- 重定向后的 Documents 路径

如果用户把微信缓存放在非常规位置，可以先设置环境变量再运行：

```powershell
$env:WECHAT_FILES_DIR="D:\WeChat Files"
uv run wx-official-cli verify "公众号名字" --strict --save verify-wechat-cache-windows.json
```

## 输出

导出目录会包含：

- `index.json`: 机器可读的文章清单。
- `index.csv`: Excel 可打开的文章清单，UTF-8 BOM 编码。
- `001-标题.html` 等文章 HTML 文件。

如果缓存里只有标题、摘要和原文链接，CLI 会写出占位 HTML，保留可追溯链接；不会伪造正文。

## 当前完成标准

在 macOS 或 CI 上只能证明 CLI 入口、打包和单元测试可用。完整目标必须在真实 Windows 机器上证明：

```powershell
uv run wx-official-cli verify "公众号名字" --strict --save verify-wechat-cache-windows.json
```

当报告里 `ok=true` 且 `goal_evidence.wechat_cache_verified=true` 时，才说明真实 Windows 微信缓存导出链路完成。
