"""股票推荐 / 复盘 PDF 生成 (fpdf2 + 思源黑体).

为何不用 reportlab: gh_wx 原版用 simhei.ttf 走 reportlab, 但需要 Windows 系统字体, Mac/Linux 缺失.
本实现用项目内捆绑的思源黑体 SourceHanSansSC-Regular.otf, 跨平台一致.

字体路径优先级:
  1. wechat_native/fonts/SourceHanSansSC-Regular.otf (PyInstaller 打包随 sidecar 走)
  2. 系统字体 (PingFang macOS / Microsoft YaHei Windows / Noto Sans CJK Linux)
  3. fallback Helvetica (无中文, 但不至于崩)

使用方式:
    pdf_bytes = build_recommendation_report(
        recommendations=[{"time", "stock", "sender", "group", "reason"}, ...],
        summary={"total", "valid", "filtered"},
    )
    return Response(pdf_bytes, media_type="application/pdf")
"""

from __future__ import annotations

import io
import os
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from wechat_log import wlog
except Exception:  # pragma: no cover
    def wlog(level: str, message: str) -> None:
        print(f"[wechat:{level}] {message}", file=sys.stderr)


_BUNDLED_FONT_NAME = "SourceHanSansSC-Regular.otf"


def _resource_dir() -> Path:
    """PyInstaller frozen 时取 sys._MEIPASS, 否则取本文件所在目录."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "wechat_native"
    return Path(__file__).resolve().parent


def _find_chinese_font() -> tuple[str, str]:
    """返回 (font_name, font_path). font_name 是 fpdf2 注册名, font_path 是绝对路径.

    没找到则返回 ("Helvetica", "") 表示 fallback 到内置无中文字体.
    """
    bundled = _resource_dir() / "fonts" / _BUNDLED_FONT_NAME
    if bundled.exists():
        return ("SourceHanSans", str(bundled))

    # 系统兜底
    candidates: list[str]
    sysname = platform.system()
    if sysname == "Darwin":
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/Library/Fonts/Songti.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
        ]
    elif sysname == "Windows":
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/simsun.ttc",
        ]
    else:
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        ]
    for c in candidates:
        if os.path.exists(c):
            return ("ChineseSys", c)
    return ("Helvetica", "")


def _create_pdf():
    """延迟导入 fpdf, 避免依赖未装时模块加载失败."""
    try:
        from fpdf import FPDF
    except ImportError as e:
        raise RuntimeError(f"缺少 fpdf2 依赖, 请 pip install fpdf2: {e}") from e

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    font_name, font_path = _find_chinese_font()
    if font_path:
        try:
            pdf.add_font(font_name, "", font_path)
        except Exception as e:
            wlog("warning", f"[pdf_reporter] add_font 失败 {font_path}: {e}, 退回 Helvetica")
            font_name = "Helvetica"
    return pdf, font_name


def _calc_wrap_lines(text: str, col_width_mm: float, char_width_mm: float = 2.5) -> int:
    if not text:
        return 1
    char_per_line = max(1, int((col_width_mm - 2) / char_width_mm))
    return max(1, (len(text) + char_per_line - 1) // char_per_line)


def build_recommendation_report(
    recommendations: list[dict[str, Any]],
    summary: dict[str, Any] | None = None,
    title: str = "股票推荐报告",
) -> bytes:
    """5 列表格 PDF: 时间 / 股票 / 推荐人 / 群组 / 推荐理由."""
    pdf, font_name = _create_pdf()
    summary = summary or {}

    # 标题
    pdf.set_font(font_name, "", 16)
    pdf.cell(0, 10, title, align="C")
    pdf.ln(15)

    # 摘要
    pdf.set_font(font_name, "", 10)
    pdf.cell(0, 8, f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    pdf.ln(8)
    pdf.cell(
        0,
        8,
        f"总处理: {summary.get('total', len(recommendations))} | "
        f"有效推荐: {summary.get('valid', len(recommendations))} | "
        f"已过滤: {summary.get('filtered', 0)}",
    )
    pdf.ln(12)

    # 表头 - 蓝色背景白字 (#1f77b4 = 31,119,180)
    pdf.set_fill_color(31, 119, 180)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(font_name, "", 9)
    col_widths = [30.0, 25.0, 25.0, 30.0, 80.0]
    headers = ["时间", "股票", "推荐人", "群组", "推荐理由"]
    for w, h in zip(col_widths, headers):
        pdf.cell(w, 8, h, 1, 0, "C", True)
    pdf.ln()

    # 数据行
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(font_name, "", 8)
    line_height = 5.0

    for rec in recommendations:
        time_s = str(rec.get("time", ""))[:16]
        stock_s = str(rec.get("stock", ""))
        sender_s = str(rec.get("sender", ""))
        group_s = str(rec.get("group", ""))
        reason_s = str(rec.get("reason", ""))[:200]

        max_lines = max(
            _calc_wrap_lines(stock_s, col_widths[1]),
            _calc_wrap_lines(sender_s, col_widths[2]),
            _calc_wrap_lines(group_s, col_widths[3]),
            _calc_wrap_lines(reason_s, col_widths[4]),
            2,
        )
        row_h = line_height * max_lines
        x0 = pdf.get_x()
        y0 = pdf.get_y()

        if y0 + row_h > pdf.h - 20:
            pdf.add_page()
            x0 = pdf.get_x()
            y0 = pdf.get_y()

        # col 0 时间 (无换行)
        pdf.set_xy(x0, y0)
        pdf.cell(col_widths[0], row_h, time_s, 1, 0, "L")

        offset = col_widths[0]
        for w, text in zip(col_widths[1:], (stock_s, sender_s, group_s, reason_s)):
            xc = x0 + offset
            pdf.set_xy(xc, y0)
            pdf.multi_cell(w, line_height, text, 0, "L")
            pdf.rect(xc, y0, w, row_h)
            offset += w

        pdf.set_xy(x0, y0 + row_h)

    out = pdf.output()  # fpdf2 v2.7+ 返回 bytes
    if isinstance(out, str):  # 兼容老版本
        out = out.encode("latin-1")
    return bytes(out)


def build_kline_review_report(
    stock_code: str,
    stock_name: str,
    kline_summary: dict[str, Any],
    messages: list[dict[str, Any]],
    llm_summary: str = "",
) -> bytes:
    """K 线复盘 PDF: 标题 + K 线摘要 + LLM 分析 + 聊天记录附录."""
    pdf, font_name = _create_pdf()

    pdf.set_font(font_name, "", 18)
    pdf.cell(0, 12, f"{stock_name} ({stock_code}) 复盘报告", align="C")
    pdf.ln(16)

    pdf.set_font(font_name, "", 10)
    pdf.cell(0, 7, f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    pdf.ln(10)

    # K 线摘要
    pdf.set_font(font_name, "", 12)
    pdf.cell(0, 8, "一、行情概览")
    pdf.ln(10)
    pdf.set_font(font_name, "", 10)
    info_lines = [
        f"区间: {kline_summary.get('start_date', '')} ~ {kline_summary.get('end_date', '')}",
        f"区间涨跌幅: {kline_summary.get('change_pct', 0):.2f}%",
        f"区间最高: {kline_summary.get('high', 0):.2f}",
        f"区间最低: {kline_summary.get('low', 0):.2f}",
        f"成交均量: {kline_summary.get('avg_volume', 0):,.0f}",
    ]
    for line in info_lines:
        pdf.cell(0, 6, line)
        pdf.ln(6)

    pdf.ln(4)

    # LLM 分析
    if llm_summary:
        pdf.set_font(font_name, "", 12)
        pdf.cell(0, 8, "二、AI 分析摘要")
        pdf.ln(10)
        pdf.set_font(font_name, "", 10)
        pdf.multi_cell(0, 6, llm_summary)
        pdf.ln(4)

    # 聊天附录
    pdf.set_font(font_name, "", 12)
    pdf.cell(0, 8, "三、关联聊天记录")
    pdf.ln(10)
    pdf.set_font(font_name, "", 9)

    for m in messages[:200]:
        text = f"[{m.get('time', '')}] {m.get('sender', '')} @ {m.get('chat_name', '')}: {m.get('content', '')[:120]}"
        pdf.multi_cell(0, 5, text)
        pdf.ln(1)

    out = pdf.output()
    if isinstance(out, str):
        out = out.encode("latin-1")
    return bytes(out)


def write_pdf_to_file(pdf_bytes: bytes, dest: Path | str) -> Path:
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(pdf_bytes)
    return p


__all__ = ["build_recommendation_report", "build_kline_review_report", "write_pdf_to_file"]
