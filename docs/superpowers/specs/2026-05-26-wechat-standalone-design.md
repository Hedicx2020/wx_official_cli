# 设计：gh_ui_cli 独立微信模块

日期：2026-05-26
作者：自动生成（基于与用户的 8 轮 brainstorming Q&A）

## 1. 目标

把 `gh_ui_cli` 从「`gh_quant_ui` 的命令行 wrapper」改造为**独立、自带后端实现**的 agent-friendly CLI。首期完整交付微信模块（~11000 行原后端代码），后续阶段再扩展数据/因子/回测/AI。

## 2. 决策摘要（用户已确认）

| 维度 | 决策 |
|------|------|
| 独立含义 | 重新实现路由为 CLI 友好直接函数调用；JyPy/gh_backtest 作为可选 runtime 依赖（微信不依赖） |
| 首期范围 | 微信完整 4 子块：A 配置+密钥+解密 / B 消息+会话+联系人 / C 公众号同步与归档 / D 股票复盘+LLM+PDF |
| 现有代码 | 原地改造：保留 cli.py / manifest / profile / invoke / coverage_audit，替换 source.py + api_client.py 入口 |
| 调用形态 | argparse 子命令 + JSON 输出 |
| FastAPI | 删除 fastapi/uvicorn 依赖；`gh-ui serve` 在 0.x 中移除 |
| 测试 | 全面 TDD + fixture；外部 IO 用 fake 替代；实环验证留 smoke |
| 架构 | 分层 services + adapters |

## 3. 非目标

- 数据查询/下载/更新（main.py 1954 行）：保留现有 wrapper 形态，后续阶段迁移
- 因子（1482 行）、回测（1268 行）、AI 报告（414 行）、远程账号（97 行）：同上
- Tauri 桌面壳与 React 前端：完全不动
- 取代 JyPy / gh_backtest 私有数据/回测库
- 保留 FastAPI / uvicorn 依赖

## 4. 架构总览

```
src/gh_ui_cli/
├── cli.py                # 现有，新增 wechat 子命令组挂载
├── manifest.py           # 现有，新增 op:wechat:* 能力源
├── invoke.py             # 现有，调用本地 registry
├── source.py             # 简化为弃用提示 + GH_QUANT_UI_PATH 警告
├── api_client.py         # 保留供数据/回测阶段使用
├── profile.py            # 现有，新增 wechat-specific 字段
└── wechat/               # 新增整个微信本地实现
    ├── __init__.py
    ├── registry.py       # 能力 id -> handler 映射
    ├── cli_handlers.py   # argparse handler -> services 转换
    ├── paths.py          # ~/.gh_quant_ui/config.json 兼容 + 默认数据根
    ├── models.py         # dataclass / TypedDict
    ├── errors.py         # WechatError 基类 + 子类
    ├── services/
    │   ├── __init__.py
    │   ├── config.py     # /config /password/*
    │   ├── messages.py   # /sessions /messages/search /search/stats
    │   ├── contacts.py   # /contacts/export
    │   ├── images.py     # /image/* (.dat 解密与转换)
    │   ├── stock_review.py  # /stock/review /stock/screener /stock/picks
    │   ├── llm.py        # /llm/chat /llm/summarize /llm/batch
    │   ├── pdf_report.py # /report/pdf
    │   └── articles/
    │       ├── __init__.py
    │       ├── login.py        # /articles/login/*
    │       ├── accounts.py     # /articles/accounts/*
    │       ├── categories.py   # /articles/categories/*
    │       ├── fetch.py        # /articles/sync /articles/{id}/fetch
    │       ├── store.py        # 文件 + SQLite 元数据
    │       └── analyze.py      # /articles/llm_analyze
    └── adapters/
        ├── __init__.py
        ├── platform.py   # darwin / win32 分发
        ├── scanner_mac.py  # macOS 内存扫描
        ├── scanner_win.py  # Windows pymem
        ├── crypto.py       # AES-CBC / 微信 db 解密
        ├── weread_client.py  # 公众号 mp.weixin.qq.com HTTP
        ├── llm_client.py     # OpenAI 兼容客户端
        └── _mac_helper.py    # macOS sudo / codesign 辅助
```

## 5. 数据流（以「消息搜索」为例）

```
agent: gh-ui wechat messages-search --json @q.json
        │
        ▼
cli.py argparse → cli_handlers.messages_search(args)
        │
        ▼
services/messages.py: search(query)
        │
        ├──► adapters/platform.get_db_path()
        ├──► adapters/crypto.decrypt_sqlite()  (若尚未解密)
        └──► 读取本地 SQLite / parquet 缓存
        │
        ▼
返回 dataclass → cli_handlers 序列化为 JSON → stdout
```

## 6. 错误处理

`errors.py`：

```python
class WechatError(Exception):
    code: str         # e.g. "WX_KEY_NOT_FOUND"
    message: str
    hint: str | None  # agent-actionable next step

class KeyNotFound(WechatError): ...
class DecryptFailed(WechatError): ...
class PlatformUnsupported(WechatError): ...
class ArticleFetchBlocked(WechatError): ...  # 微信反爬
class LLMAuthFailed(WechatError): ...
```

CLI 层捕获 → 输出 `{"ok": false, "error": {"code": "...", "message": "...", "hint": "..."}}` 到 stdout，退出码非零。与现有 `io.print_json` 风格一致。

## 7. 测试策略

- **TDD 强制**：service 必须先有 `tests/wechat/test_<service>.py`，再有实现。
- **Adapter 隔离**：service 测试通过依赖注入或 monkeypatch 替换 adapter。
- **Adapter 测试**：adapter 用 fake fs / fake socket / fake process 测试，不接真实微信进程。
- **平台标记**：`pytest.mark.darwin / win32`，Windows-only 测试在 macOS 上 skip。
- **CI**：所有非平台 specific 测试都跑；平台 specific 测试本机跑；实环 smoke 不上 CI。
- **smoke**：`gh-ui smoke --with-wechat` 仅在用户本机执行，自带跳过逻辑（缺密钥时跳过）。

## 8. 实施分期

| 阶段 | 内容 | 验收 |
|------|------|------|
| 1 | 骨架（paths/errors/models/registry）+ adapters/platform + services/config + 第一个子命令 `wechat config-get/set` | `gh-ui wechat config-get` 返回 JSON |
| 2 | adapters/crypto + scanner_mac + scanner_win + services/keys（密钥扫描+解密） | `gh-ui wechat password-status` 返回 JSON |
| 3 | services/messages + sessions + contacts | `gh-ui wechat sessions`、`messages-search`、`contacts-export` 通过 fixture 测试 |
| 4 | services/articles 全套 + adapters/weread + article_store | `gh-ui wechat articles-*` 全套通过 fixture 测试 |
| 5 | images + stock_review + llm + pdf_report | `gh-ui wechat image-*` / `stock-review` / `llm-chat` / `report-pdf` 通过 fixture 测试 |

每阶段 1 个独立 commit；每阶段必须 `pytest` 全绿才能进下一阶段。

## 9. 关键权衡

- **manifest ID 改名**：`route:GET:/api/wechat/sessions` → `op:wechat:sessions`。invoke 命令双兼容半年（接受旧 ID 时打 deprecation warning）。
- **配置存储**：读取顺序：`~/.gh_ui_cli/wechat_config.json` > `~/.gh_quant_ui/config.json`（兼容桌面端）。写入只写第一个。
- **私有依赖隔离**：JyPy/gh_backtest 不会被微信模块 import；后续阶段 lazy import + 缺失时友好报错。
- **Windows pymem**：评审环境（macOS）无法实测，需要 Windows 机器手动 smoke + CI 矩阵覆盖。

## 10. 风险

| 风险 | 缓解 |
|------|------|
| 微信解密代码与官方版本变化 | 阶段 2 直接搬运原 crypto.py 逻辑，不重写算法 |
| 公众号反爬策略变更 | weread_client 保留原 `_detect_invalid_mp_page` 检测；加 retry 与 cooldown |
| LLM 客户端 OpenAI 兼容版本漂移 | 用 httpx 直发 + 显式版本测试 fixture |
| 11000 行重写工作量被低估 | 阶段化交付，每阶段独立可用；如阶段 4/5 工作量超预算可单独延后 |

## 11. 后续阶段（非首期）

- 数据模块（main.py）：现有 wrapper 模式继续可用直到迁移；迁移时需要把 JyPy 调用变成 lazy import + 缺失时友好报错。
- 因子/回测：依赖 gh_backtest，同上 lazy import 策略。
- AI 报告复现：独立模块，依赖 LLM + 数据。
