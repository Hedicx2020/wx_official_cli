# wx-official-cli 用户说明

本工具只做一件事：从本机 Windows 微信缓存中导出某个微信公众号的文章到本地目录。

## 前提

- Windows 机器。
- Python 3.10+ 和 `uv`。
- PC 微信已经打开并登录。
- 目标公众号的文章已经出现在这台机器的微信缓存中。

工具会尝试自动检测微信缓存路径，并从已登录微信进程中提取本地数据库解密 key。这里的 key 是本机缓存数据库的解密 key，不是微信账号登录密码。

## 常用命令

检查状态：

```powershell
uv run wx-official-cli status
```

导出文章：

```powershell
uv run wx-official-cli export "公众号名字" --limit 100 --output-dir .\wechat_articles
```

agent 也可以使用等价命令：

```powershell
uv run wx-official-cli crawl "公众号名字" --limit 100 --output-dir .\wechat_articles
```

生成验收报告：

```powershell
uv run wx-official-cli verify "公众号名字" --strict --save verify-wechat-cache-windows.json
```

查看 agent 可调用清单：

```powershell
uv run wx-official-cli manifest
```

## 可选参数

- `--limit 100`: 最多导出多少篇文章。
- `--output-dir .\wechat_articles`: 输出目录。
- `--no-fetch-html`: 不联网抓正文，只写标题、摘要和原文链接。
- `--no-auto-password`: 不自动提取本地数据库解密 key，只使用已有配置。
- `--no-scan`: 不重新扫描微信缓存，只从已导入的本地文章库导出。
- `--save report.json`: 把 JSON 输出保存到文件。
- `--strict`: 仅 `verify` 使用，验证失败时返回非零退出码。

## 输出文件

输出目录包含：

- `index.json`
- `index.csv`
- 多个文章 HTML 文件

如果正文抓取失败，HTML 文件仍会保留标题、摘要和微信原文链接。

## 常见失败

`wechat_path_detected=false`：微信缓存路径没有检测到。先确认 PC 微信已登录，或设置：

```powershell
$env:WECHAT_FILES_DIR="D:\WeChat Files"
```

`database_key_available=false`：没有拿到本机缓存数据库解密 key。确认 `Weixin.exe` 或 `WeChat.exe` 正在运行，并用普通用户权限运行命令。

`articles_exported=false`：没有找到该公众号文章。确认文章已在这台机器的微信里出现过，或使用更完整的公众号名称重试。

`html_files_written=false`：输出目录写入失败。换一个有权限的 `--output-dir`。
