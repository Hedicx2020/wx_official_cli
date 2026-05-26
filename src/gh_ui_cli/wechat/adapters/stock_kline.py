#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票K线复盘模块
使用 akshare 获取A股、港股、美股、北交所历史数据，pyecharts 生成带聊天标注的K线图
"""

import akshare as ak
import pandas as pd
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from pyecharts import options as opts
from pyecharts.charts import Kline, Bar, Grid, Line
from pyecharts.commons.utils import JsCode

try:
    from wechat_log import wlog
except Exception:  # pragma: no cover
    def wlog(level: str, message: str) -> None:
        print(f"[wechat:{level}] {message}", file=sys.stderr)


class StockKlineReview:
    """股票K线复盘类 - 使用 akshare 支持多市场"""

    # 市场类型
    MARKET_SH = 'sh'    # 上海A股
    MARKET_SZ = 'sz'    # 深圳A股
    MARKET_BJ = 'bj'    # 北交所
    MARKET_HK = 'hk'    # 港股
    MARKET_US = 'us'    # 美股

    def __init__(self):
        # 缓存股票名称映射
        self._stock_name_cache: Dict[str, str] = {}
        self._a_stock_names: Optional[Dict[str, str]] = None

    def _detect_market(self, code: str) -> str:
        """
        自动识别股票市场

        Args:
            code: 股票代码

        Returns:
            市场标识: 'sh', 'sz', 'bj', 'hk', 'us'
        """
        code = code.strip().upper()

        # 移除可能的市场前缀
        if code.startswith('SH.') or code.startswith('SH'):
            code = code.replace('SH.', '').replace('SH', '')
            return self.MARKET_SH
        if code.startswith('SZ.') or code.startswith('SZ'):
            code = code.replace('SZ.', '').replace('SZ', '')
            return self.MARKET_SZ
        if code.startswith('BJ.') or code.startswith('BJ'):
            return self.MARKET_BJ
        if code.startswith('HK.') or code.startswith('HK'):
            return self.MARKET_HK

        # 纯字母 -> 美股
        if code.isalpha():
            return self.MARKET_US

        # 纯数字代码识别
        if code.isdigit():
            # 先判断港股：5位数字
            if len(code) == 5:
                return self.MARKET_HK
            # 6位数字的A股/北交所
            if code.startswith('6'):
                return self.MARKET_SH
            elif code.startswith('0') or code.startswith('3'):
                return self.MARKET_SZ
            elif code.startswith('8') or code.startswith('4') or code.startswith('9'):
                # 北交所: 8开头(老三板)、4开头(老三板)、9开头(北交所新股)
                return self.MARKET_BJ

        # 默认尝试A股
        return self.MARKET_SH

    def _normalize_code(self, code: str) -> str:
        """
        标准化股票代码（去除市场前缀）
        """
        code = code.strip().upper()
        # 移除常见前缀
        for prefix in ['SH.', 'SZ.', 'BJ.', 'HK.', 'SH', 'SZ', 'BJ', 'HK']:
            if code.startswith(prefix):
                code = code[len(prefix):]
                break
        return code

    def _load_a_stock_names(self) -> Dict[str, str]:
        """加载A股代码名称映射"""
        if self._a_stock_names is not None:
            return self._a_stock_names

        try:
            df = ak.stock_info_a_code_name()
            self._a_stock_names = dict(zip(df['code'].astype(str), df['name']))
            wlog("info", f"[akshare] 加载A股名称映射: {len(self._a_stock_names)} 条")
            return self._a_stock_names
        except Exception as e:
            wlog("warning", f"[akshare] 加载A股名称失败: {e}")
            self._a_stock_names = {}
            return self._a_stock_names

    def get_stock_info(self, code: str) -> Dict:
        """
        获取股票基本信息

        Args:
            code: 股票代码，支持格式: 000001, sh000001, 600000, 00700, AAPL

        Returns:
            {'code': '600000', 'name': '浦发银行', 'market': 'sh'}
        """
        market = self._detect_market(code)
        normalized_code = self._normalize_code(code)
        stock_name = ''

        wlog("info", f"[股票信息] 查询: {code} -> 市场: {market}, 代码: {normalized_code}")

        # 先检查缓存
        cache_key = f"{market}_{normalized_code}"
        if cache_key in self._stock_name_cache:
            stock_name = self._stock_name_cache[cache_key]
            wlog("info", f"[股票信息] 缓存命中: {stock_name}")
        else:
            try:
                if market in [self.MARKET_SH, self.MARKET_SZ]:
                    # A股：从名称映射中查找
                    names = self._load_a_stock_names()
                    stock_name = names.get(normalized_code, '')
                    if not stock_name:
                        # 尝试从实时数据获取
                        df = ak.stock_zh_a_spot_em()
                        match = df[df['代码'] == normalized_code]
                        if not match.empty:
                            stock_name = match.iloc[0]['名称']

                elif market == self.MARKET_BJ:
                    # 北交所 - 优先使用 stock_info_bj_name_code
                    try:
                        df = ak.stock_info_bj_name_code()
                        # 第一列是代码，第二列是名称
                        code_col = df.columns[0]
                        name_col = df.columns[1]
                        match = df[df[code_col].astype(str) == normalized_code]
                        if not match.empty:
                            stock_name = match.iloc[0][name_col]
                    except Exception as e:
                        wlog("warning", f"[股票信息] 北交所名称查询失败: {e}")

                elif market == self.MARKET_HK:
                    # 港股 - 优先新浪接口
                    code_padded = normalized_code.zfill(5)
                    try:
                        import requests
                        url = f'https://hq.sinajs.cn/list=hk{code_padded}'
                        headers = {'Referer': 'https://finance.sina.com.cn'}
                        r = requests.get(url, headers=headers, timeout=5)
                        if r.status_code == 200 and 'hq_str' in r.text:
                            # 解析: var hq_str_hk00700="TENCENT,腾讯控股,..."
                            parts = r.text.split('"')[1].split(',')
                            if len(parts) >= 2 and parts[1]:
                                stock_name = parts[1]
                                wlog("info", f"[股票信息] 港股新浪获取成功: {stock_name}")
                    except Exception as e:
                        wlog("warning", f"[股票信息] 港股新浪查询失败: {e}")

                elif market == self.MARKET_US:
                    # 美股 - 优先新浪接口
                    try:
                        import requests
                        url = f'https://hq.sinajs.cn/list=gb_{normalized_code.lower()}'
                        headers = {'Referer': 'https://finance.sina.com.cn'}
                        r = requests.get(url, headers=headers, timeout=5)
                        if r.status_code == 200 and 'hq_str' in r.text:
                            # 解析: var hq_str_gb_aapl="苹果,..."
                            parts = r.text.split('"')[1].split(',')
                            if len(parts) >= 1 and parts[0]:
                                stock_name = parts[0]
                                wlog("info", f"[股票信息] 美股新浪获取成功: {stock_name}")
                    except Exception as e:
                        wlog("warning", f"[股票信息] 美股新浪查询失败: {e}")

                if stock_name:
                    self._stock_name_cache[cache_key] = stock_name
                    wlog("info", f"[股票信息] 找到: {stock_name}")

            except Exception as e:
                wlog("warning", f"[股票信息] 查询异常: {e}")

        # 如果还是没有名称，使用代码
        if not stock_name:
            stock_name = normalized_code
            wlog("warning", f"[股票信息] 未找到名称，使用代码: {stock_name}")

        return {
            'code': normalized_code,
            'name': stock_name,
            'market': market
        }

    def _get_a_stock_kline(self, code: str, market: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取A股K线 - 优先新浪(stock_zh_a_daily)，失败用东方财富"""
        df = None
        # 构造带市场前缀的代码 (新浪接口需要)
        prefix = 'sh' if market == self.MARKET_SH else 'sz'
        symbol_with_prefix = f"{prefix}{code}"

        # 1. 尝试新浪数据源 (stock_zh_a_daily)
        try:
            wlog("info", f"[K线] A股尝试新浪数据源: {symbol_with_prefix}")
            df = ak.stock_zh_a_daily(
                symbol=symbol_with_prefix,
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust="qfq"
            )
            if df is not None and not df.empty:
                wlog("info", f"[K线] 新浪数据源成功: {len(df)} 条")
                return df
        except Exception as e:
            wlog("warning", f"[K线] 新浪数据源失败: {e}")

        # 2. 尝试东方财富数据源
        try:
            wlog("info", f"[K线] A股尝试东方财富数据源: {code}")
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust="qfq"
            )
            if df is not None and not df.empty:
                wlog("info", f"[K线] 东方财富数据源成功: {len(df)} 条")
                return df
        except Exception as e:
            wlog("warning", f"[K线] 东方财富数据源失败: {e}")

        return df

    def _get_bj_stock_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取北交所K线 - 优先新浪(stock_zh_a_daily)，失败用东方财富"""
        df = None
        # 构造带市场前缀的代码 (新浪接口需要 bj 前缀)
        symbol_with_prefix = f"bj{code}"

        # 1. 尝试新浪数据源 (stock_zh_a_daily 支持北交所)
        try:
            wlog("info", f"[K线] 北交所尝试新浪数据源: {symbol_with_prefix}")
            df = ak.stock_zh_a_daily(
                symbol=symbol_with_prefix,
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust="qfq"
            )
            if df is not None and not df.empty:
                wlog("info", f"[K线] 新浪数据源成功: {len(df)} 条")
                return df
        except Exception as e:
            wlog("warning", f"[K线] 新浪北交所数据源失败: {e}")

        # 2. 尝试东方财富数据源
        try:
            wlog("info", f"[K线] 北交所尝试东方财富数据源: {code}")
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust="qfq"
            )
            if df is not None and not df.empty:
                wlog("info", f"[K线] 东方财富数据源成功: {len(df)} 条")
                return df
        except Exception as e:
            wlog("warning", f"[K线] 东方财富北交所数据源失败: {e}")

        return df

    def _get_hk_stock_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取港股K线 - 优先新浪，失败用东方财富"""
        df = None
        # 1. 尝试新浪数据源
        try:
            wlog("info", f"[K线] 港股尝试新浪数据源: {code}")
            df = ak.stock_hk_daily(
                symbol=code,
                adjust="qfq"
            )
            if df is not None and not df.empty:
                # 新浪数据需要过滤日期范围
                df['date'] = pd.to_datetime(df['date'])
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                if not df.empty:
                    wlog("info", f"[K线] 新浪数据源成功: {len(df)} 条")
                    return df
        except Exception as e:
            wlog("warning", f"[K线] 新浪港股数据源失败: {e}")

        # 2. 尝试东方财富数据源
        try:
            wlog("info", f"[K线] 港股尝试东方财富数据源: {code}")
            df = ak.stock_hk_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust="qfq"
            )
            if df is not None and not df.empty:
                wlog("info", f"[K线] 东方财富数据源成功: {len(df)} 条")
                return df
        except Exception as e:
            wlog("warning", f"[K线] 东方财富港股数据源失败: {e}")

        return df

    def _get_us_stock_kline(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取美股K线 - 优先新浪，失败用东方财富"""
        df = None
        # 1. 尝试新浪数据源
        try:
            wlog("info", f"[K线] 美股尝试新浪数据源: {code}")
            df = ak.stock_us_daily(
                symbol=code,
                adjust="qfq"
            )
            if df is not None and not df.empty:
                # 新浪数据需要过滤日期范围
                df['date'] = pd.to_datetime(df['date'])
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]
                df['date'] = df['date'].dt.strftime('%Y-%m-%d')
                if not df.empty:
                    wlog("info", f"[K线] 新浪数据源成功: {len(df)} 条")
                    return df
        except Exception as e:
            wlog("warning", f"[K线] 新浪美股数据源失败: {e}")

        # 2. 尝试东方财富数据源
        try:
            wlog("info", f"[K线] 美股尝试东方财富数据源: {code}")
            df = ak.stock_us_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust="qfq"
            )
            if df is not None and not df.empty:
                wlog("info", f"[K线] 东方财富数据源成功: {len(df)} 条")
                return df
        except Exception as e:
            wlog("warning", f"[K线] 东方财富美股数据源失败: {e}")

        return df

    def get_kline_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票日K线数据

        Args:
            code: 股票代码
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount, pctChg
        """
        import time

        market = self._detect_market(code)
        normalized_code = self._normalize_code(code)

        wlog("info", f"[K线数据] 查询: {normalized_code}, 市场: {market}, 日期: {start_date} ~ {end_date}")

        df = None
        max_retries = 3
        last_error = None

        for retry in range(max_retries):
            try:
                if retry > 0:
                    wait_time = retry * 2
                    wlog("info", f"[K线数据] 第 {retry + 1} 次重试，等待 {wait_time} 秒...")
                    time.sleep(wait_time)

                if market in [self.MARKET_SH, self.MARKET_SZ]:
                    # A股 - 优先新浪数据源
                    df = self._get_a_stock_kline(normalized_code, market, start_date, end_date)

                elif market == self.MARKET_BJ:
                    # 北交所 - 优先新浪，失败用东方财富
                    df = self._get_bj_stock_kline(normalized_code, start_date, end_date)

                elif market == self.MARKET_HK:
                    # 港股 - 优先新浪，失败用东方财富
                    code_padded = normalized_code.zfill(5)
                    df = self._get_hk_stock_kline(code_padded, start_date, end_date)

                elif market == self.MARKET_US:
                    # 美股 - 优先新浪，失败用东方财富
                    df = self._get_us_stock_kline(normalized_code, start_date, end_date)

                # 成功获取数据，跳出重试循环
                if df is not None and not df.empty:
                    break

            except Exception as e:
                last_error = e
                wlog("warning", f"[K线数据] 第 {retry + 1} 次尝试失败: {e}")
                if retry == max_retries - 1:
                    raise Exception(f"获取K线数据失败（重试{max_retries}次）: {str(last_error)}")

        if df is None or df.empty:
            raise Exception(f"未获取到K线数据 (代码:{normalized_code}, 市场:{market})")

        wlog("info", f"[K线数据] 获取到 {len(df)} 条数据")

        # 标准化列名
        df = self._standardize_columns(df)

        return df

    def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化DataFrame列名"""
        # akshare 返回的列名可能不同，统一处理
        column_mapping = {
            '日期': 'date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
            '涨跌幅': 'pctChg',
            '涨跌额': 'change',
            '换手率': 'turn',
        }

        df = df.rename(columns=column_mapping)

        # 确保必要的列存在
        required_cols = ['date', 'open', 'close', 'high', 'low', 'volume']
        for col in required_cols:
            if col not in df.columns:
                # 尝试从原始列名查找
                for orig, std in column_mapping.items():
                    if std == col and orig in df.columns:
                        df[col] = df[orig]
                        break

        # 转换数据类型
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg', 'turn']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 确保日期格式
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

        return df

    def generate_kline_chart(
        self,
        kline_data: pd.DataFrame,
        messages: List[Dict],
        stock_name: str = "",
        stock_code: str = ""
    ) -> str:
        """
        生成带聊天标注的K线图

        Args:
            kline_data: K线数据 DataFrame
            messages: 聊天记录列表 [{'time': 'YYYY-MM-DD HH:MM:SS', 'content': '...', ...}]
            stock_name: 股票名称
            stock_code: 股票代码

        Returns:
            HTML字符串
        """
        if kline_data.empty:
            return "<div style='text-align:center;padding:50px;color:#999;'>无K线数据</div>"

        # 准备K线数据
        dates = kline_data['date'].tolist()
        kline_values = kline_data[['open', 'close', 'low', 'high']].values.tolist()
        volumes = kline_data['volume'].tolist()

        # 按日期聚合聊天记录
        msg_by_date = self._aggregate_messages_by_date(messages)

        # 准备标记点数据
        mark_points = []
        for date, msgs in msg_by_date.items():
            if date in dates:
                idx = dates.index(date)
                # 获取当日最高价作为标记位置
                high_price = kline_data.iloc[idx]['high']
                # 汇总当日消息
                summary = self._format_message_summary(msgs)
                mark_points.append({
                    'coord': [date, float(high_price)],
                    'value': len(msgs),
                    'name': date,
                    'itemStyle': {'color': '#ff6b6b'},
                    'label': {
                        'show': True,
                        'formatter': str(len(msgs)),
                        'color': '#fff',
                        'fontSize': 10
                    },
                    'summary': summary,
                    'messages': msgs
                })

        # 创建K线图
        kline = (
            Kline()
            .add_xaxis(dates)
            .add_yaxis(
                series_name=f"{stock_name}",
                y_axis=kline_values,
                itemstyle_opts=opts.ItemStyleOpts(
                    color="#ec0000",
                    color0="#00da3c",
                    border_color="#ec0000",
                    border_color0="#00da3c",
                ),
                markpoint_opts=opts.MarkPointOpts(
                    data=[
                        opts.MarkPointItem(
                            coord=mp['coord'],
                            value=mp['value'],
                            symbol='circle',
                            symbol_size=20,
                            itemstyle_opts=opts.ItemStyleOpts(color='#4a9fd8'),
                            label_opts=opts.LabelOpts(
                                is_show=True,
                                formatter=JsCode("function(params){return params.value;}"),
                                color='#fff',
                                font_size=10
                            )
                        )
                        for mp in mark_points
                    ]
                ) if mark_points else None
            )
            .set_global_opts(
                title_opts=opts.TitleOpts(
                    title=f"{stock_name} ({stock_code}) K线复盘",
                    subtitle=f"数据区间: {dates[0]} ~ {dates[-1]}" if dates else "",
                    title_textstyle_opts=opts.TextStyleOpts(
                        font_family="Courier New, monospace",
                        font_size=16,
                        color="#4a9fd8"
                    ),
                    subtitle_textstyle_opts=opts.TextStyleOpts(
                        font_family="Courier New, monospace",
                        font_size=12,
                        color="#666"
                    )
                ),
                xaxis_opts=opts.AxisOpts(
                    type_="category",
                    is_scale=True,
                    boundary_gap=False,
                    axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                    splitline_opts=opts.SplitLineOpts(is_show=False),
                    split_number=20,
                    min_="dataMin",
                    max_="dataMax",
                ),
                yaxis_opts=opts.AxisOpts(
                    is_scale=True,
                    splitarea_opts=opts.SplitAreaOpts(
                        is_show=True,
                        areastyle_opts=opts.AreaStyleOpts(opacity=1)
                    ),
                ),
                tooltip_opts=opts.TooltipOpts(
                    trigger="axis",
                    axis_pointer_type="cross",
                    background_color="rgba(255,255,255,0.95)",
                    border_color="#4a9fd8",
                    border_width=1,
                    textstyle_opts=opts.TextStyleOpts(color="#333"),
                    formatter=JsCode(
                        "function(params){"
                        "var date=params[0].axisValue;"
                        "var r='<b>'+date+'</b><br/>';"
                        "if(params[0]&&params[0].data){"
                        "var d=params[0].data;"
                        "r+='开:'+d[1]+' 收:'+d[2]+'<br/>';"
                        "r+='低:'+d[3]+' 高:'+d[4]+'<br/>';}"
                        "if(window.KLINE_MESSAGES&&window.KLINE_MESSAGES[date]){"
                        "var ms=window.KLINE_MESSAGES[date];"
                        "r+='<br/><b>聊天('+ms.length+'条)</b><br/>';"
                        "for(var i=0;i<Math.min(ms.length,3);i++){"
                        "var m=ms[i];"
                        "var c=m.content.length>30?m.content.substring(0,30)+'...':m.content;"
                        "r+='['+m.sender+']'+c+'<br/>';}}"
                        "return r;}"
                    )
                ),
                datazoom_opts=[
                    opts.DataZoomOpts(
                        is_show=True,
                        type_="inside",
                        xaxis_index=[0, 1],
                        range_start=0,
                        range_end=100,
                    ),
                    opts.DataZoomOpts(
                        is_show=True,
                        xaxis_index=[0, 1],
                        type_="slider",
                        pos_top="90%",
                        range_start=0,
                        range_end=100,
                    ),
                ],
                toolbox_opts=opts.ToolboxOpts(
                    is_show=True,
                    feature={
                        "dataZoom": {"yAxisIndex": "none"},
                        "restore": {},
                        "saveAsImage": {}
                    }
                ),
            )
        )

        # 创建成交量柱状图
        bar = (
            Bar()
            .add_xaxis(dates)
            .add_yaxis(
                series_name="成交量",
                y_axis=volumes,
                xaxis_index=1,
                yaxis_index=1,
                label_opts=opts.LabelOpts(is_show=False),
                itemstyle_opts=opts.ItemStyleOpts(
                    color=JsCode(
                        """function(params) {
                            var colorList;
                            if (params.data >= 0) {
                                colorList = '#ec0000';
                            } else {
                                colorList = '#00da3c';
                            }
                            return colorList;
                        }"""
                    )
                ),
            )
            .set_global_opts(
                xaxis_opts=opts.AxisOpts(
                    type_="category",
                    grid_index=1,
                    axislabel_opts=opts.LabelOpts(is_show=False),
                ),
                yaxis_opts=opts.AxisOpts(
                    grid_index=1,
                    split_number=2,
                    axislabel_opts=opts.LabelOpts(is_show=False),
                    axisline_opts=opts.AxisLineOpts(is_show=False),
                    axistick_opts=opts.AxisTickOpts(is_show=False),
                    splitline_opts=opts.SplitLineOpts(is_show=False),
                ),
                legend_opts=opts.LegendOpts(is_show=False),
            )
        )

        # 组合图表
        grid = (
            Grid(init_opts=opts.InitOpts(
                width="100%",
                height="500px",
                bg_color="#fff"
            ))
            .add(
                kline,
                grid_opts=opts.GridOpts(
                    pos_left="10%",
                    pos_right="8%",
                    pos_top="10%",
                    height="55%"
                ),
            )
            .add(
                bar,
                grid_opts=opts.GridOpts(
                    pos_left="10%",
                    pos_right="8%",
                    pos_top="70%",
                    height="15%"
                ),
            )
        )

        # 渲染为HTML
        html = grid.render_embed()

        # 注入 echarts.min.js CDN (render_embed 默认不带, 在 Tauri iframe srcDoc 中需要自包含)
        # gh_wx 原版主页加载 CDN 后剥离, 这里反过来: 自包含使 iframe 独立可用
        echarts_cdn = '<script src="https://assets.pyecharts.org/assets/v5/echarts.min.js"></script>'
        if 'echarts.min.js' not in html:
            # 优先放到 </head> 之前; 没有 <head> 则放到 <body> 开头
            if '</head>' in html:
                html = html.replace('</head>', f'  {echarts_cdn}\n</head>', 1)
            elif '<body' in html:
                html = html.replace('<body', f'{echarts_cdn}\n<body', 1)
            else:
                html = echarts_cdn + html

        # 添加聊天记录数据的JavaScript（供tooltip使用）
        if msg_by_date:
            msg_data_js = self._generate_message_data_js(msg_by_date, dates)
            # 将消息数据放在图表脚本之前
            html = msg_data_js + html

        return html

    def _aggregate_messages_by_date(self, messages: List[Dict]) -> Dict[str, List[Dict]]:
        """
        按日期聚合聊天记录（已去重）
        """
        msg_by_date = {}
        seen = set()

        for msg in messages:
            time_str = msg.get('time', '')
            if not time_str:
                continue

            # 提取日期部分
            date = time_str.split(' ')[0]

            # 去重: 同一日+聊天对象+发送者+内容
            dedup_key = f"{date}|{msg.get('chat_name', '')}|{msg.get('sender', '')}|{msg.get('content', '')}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            if date not in msg_by_date:
                msg_by_date[date] = []
            msg_by_date[date].append(msg)

        return msg_by_date

    def _format_message_summary(self, messages: List[Dict], max_chars: int = 100) -> str:
        """格式化消息摘要"""
        if not messages:
            return ""

        summaries = []
        for msg in messages[:3]:  # 最多显示3条
            sender = msg.get('sender', '未知')
            content = msg.get('content', '')[:50]
            if len(msg.get('content', '')) > 50:
                content += '...'
            summaries.append(f"[{sender}] {content}")

        result = '\n'.join(summaries)
        if len(messages) > 3:
            result += f"\n... 还有 {len(messages) - 3} 条"

        return result

    def _generate_message_data_js(self, msg_by_date: Dict, dates: List[str]) -> str:
        """生成消息数据的JavaScript代码"""
        import json

        # 转换为JSON安全格式
        safe_data = {}
        for date, msgs in msg_by_date.items():
            if date in dates:
                safe_data[date] = [
                    {
                        'time': m.get('time', ''),
                        'chat_name': m.get('chat_name', ''),
                        'sender': m.get('sender', ''),
                        'content': m.get('content', '')[:200]
                    }
                    for m in msgs
                ]

        js_code = f"""
        <script>
        window.KLINE_MESSAGES = {json.dumps(safe_data, ensure_ascii=False)};
        </script>
        """
        return js_code


# 模块级便捷函数
_instance: Optional[StockKlineReview] = None


def get_kline_reviewer() -> StockKlineReview:
    """获取全局K线复盘实例"""
    global _instance
    if _instance is None:
        _instance = StockKlineReview()
    return _instance


def get_stock_info(code: str) -> Dict:
    """获取股票信息"""
    return get_kline_reviewer().get_stock_info(code)


def get_kline_data(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取K线数据"""
    return get_kline_reviewer().get_kline_data(code, start_date, end_date)


def generate_kline_chart(
    kline_data: pd.DataFrame,
    messages: List[Dict],
    stock_name: str = "",
    stock_code: str = ""
) -> str:
    """生成K线图HTML"""
    return get_kline_reviewer().generate_kline_chart(
        kline_data, messages, stock_name, stock_code
    )
