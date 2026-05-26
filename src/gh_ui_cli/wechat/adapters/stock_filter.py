#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票代码筛选模块（优化版）
从聚源数据库获取A股、港股、美股的股票代码和简称
用于筛选与股票相关的聊天记录

优化策略：
1. 预编译正则表达式
2. 分类处理不同类型的股票代码
3. 使用集合快速查找
4. 主备数据库自动切换
"""

import pymysql
import sys
from typing import List, Tuple, Dict, Set, Optional
import re
from urllib.parse import unquote

try:
    from wechat_log import wlog
except Exception:  # pragma: no cover
    def wlog(level: str, message: str) -> None:
        print(f"[wechat:{level}] {message}", file=sys.stderr)


def _parse_engine_url(url: str) -> Dict:
    """把 ui 项目 JYDB_ENGINES 里的 'user:pass@host:port/db' 解析为 pymysql 连接配置.

    例: 'root:Jydb%404321@3.tcp.cpolar.top:12624/jydb' -> dict.
    支持 URL 编码的密码 (% 转义)。
    """
    try:
        auth, hostpart = url.rsplit("@", 1)
        user, password = auth.split(":", 1)
        password = unquote(password)
        host_port, db = hostpart.split("/", 1)
        host, port = host_port.split(":", 1)
        return {
            "host": host,
            "port": int(port),
            "user": user,
            "password": password,
            "database": db,
            "charset": "utf8mb4",
            "connect_timeout": 10,
            "read_timeout": 30,
        }
    except Exception:
        return {}


class StockFilter:
    """股票代码筛选器（优化版）"""
    
    # 主数据库配置（首选）
    PRIMARY_DB_CONFIG = {
        'host': '6.tcp.vip.cpolar.cn',
        'port': 12624,
        'user': 'root',
        'password': '123456789',
        'database': 'jydb',
        'charset': 'utf8mb4',
        'connect_timeout': 10,
        'read_timeout': 30,
    }
    
    # 备用数据库配置
    BACKUP_DB_CONFIG = {
        'host': '3.tcp.cpolar.top',
        'port': 12624,
        'user': 'guohai',
        'password': 'guohai123',
        'database': 'jydb',
        'charset': 'utf8mb4',
        'connect_timeout': 10,
        'read_timeout': 30,
    }
    
    # 主数据库最大重试次数
    MAX_PRIMARY_RETRIES = 3
    
    # 市场类型
    MARKET_A = 'a_stock'
    MARKET_HK = 'hk_stock'
    MARKET_US = 'us_stock'
    MARKET_ALL = 'all'
    
    def __init__(self, db_config: Optional[Dict] = None):
        # 如果指定了配置则使用指定的，否则使用主数据库
        self._primary_config = db_config or self.PRIMARY_DB_CONFIG
        self._backup_config = self.BACKUP_DB_CONFIG
        self._current_config = self._primary_config
        self._using_backup = False
        self._primary_fail_count = 0
        
        self._stock_cache: Dict[str, List[Tuple[str, str]]] = {}
        # 优化：缓存编译后的匹配器
        self._compiled_matchers: Dict[str, 'StockMatcher'] = {}
        
    def _get_connection(self):
        """
        获取数据库连接（带主备切换）
        主数据库连接失败3次后自动切换到备用数据库
        """
        # 如果已经切换到备用数据库，直接使用备用
        if self._using_backup:
            return pymysql.connect(**self._backup_config)
        
        # 尝试连接主数据库
        try:
            conn = pymysql.connect(**self._primary_config)
            # 连接成功，重置失败计数
            self._primary_fail_count = 0
            return conn
        except Exception as e:
            self._primary_fail_count += 1
            wlog("warning", f"[股票筛选] 主数据库连接失败 ({self._primary_fail_count}/{self.MAX_PRIMARY_RETRIES}): {e}")
            
            # 达到最大重试次数，切换到备用数据库
            if self._primary_fail_count >= self.MAX_PRIMARY_RETRIES:
                wlog("warning", f"[股票筛选] 主数据库连接失败{self.MAX_PRIMARY_RETRIES}次，切换到备用数据库")
                self._using_backup = True
                try:
                    conn = pymysql.connect(**self._backup_config)
                    wlog("info", f"[股票筛选] 备用数据库连接成功")
                    return conn
                except Exception as backup_e:
                    wlog("error", f"[股票筛选] 备用数据库连接也失败: {backup_e}")
                    raise backup_e
            else:
                # 还没达到最大重试次数，继续抛出异常让调用方重试
                raise e
    
    def get_db_status(self) -> Dict:
        """获取数据库连接状态"""
        return {
            'using_backup': self._using_backup,
            'primary_fail_count': self._primary_fail_count,
            'current_host': self._backup_config['host'] if self._using_backup else self._primary_config['host']
        }
    
    def get_a_stocks(self) -> List[Tuple[str, str]]:
        """获取A股股票代码和简称"""
        if self.MARKET_A in self._stock_cache:
            return self._stock_cache[self.MARKET_A]
            
        sql = """
            SELECT SecuCode, SecuAbbr FROM secumain
            WHERE SecuCategory = 1
            AND SecuMarket IN (83, 90, 18)
        """
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(sql)
            results = cursor.fetchall()
            cursor.close()
            conn.close()
            
            self._stock_cache[self.MARKET_A] = results
            return results
        except Exception as e:
            wlog("error", f"[ERROR] 获取A股数据失败: {e}")
            return []
    
    def get_hk_stocks(self) -> List[Tuple[str, str]]:
        """获取港股股票代码和简称"""
        if self.MARKET_HK in self._stock_cache:
            return self._stock_cache[self.MARKET_HK]
            
        sql = """
            SELECT SecuCode, SecuAbbr FROM hk_secumain
            WHERE SecuCategory IN (3, 51)
            AND SecuMarket = 72
        """
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(sql)
            results = cursor.fetchall()
            cursor.close()
            conn.close()
            
            self._stock_cache[self.MARKET_HK] = results
            return results
        except Exception as e:
            wlog("error", f"[ERROR] 获取港股数据失败: {e}")
            return []
    
    def get_us_stocks(self) -> List[Tuple[str, str]]:
        """获取美股股票代码和简称"""
        if self.MARKET_US in self._stock_cache:
            return self._stock_cache[self.MARKET_US]
            
        sql = """
            SELECT SecuCode, SecuAbbr FROM us_secumain
            WHERE SecuCategory IN (55, 62, 74, 75, 78, 101, 201, 202, 203, 204, 205, 206, 207, 208)
            AND SecuMarket IN (76, 77, 78)
        """
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(sql)
            results = cursor.fetchall()
            cursor.close()
            conn.close()
            
            self._stock_cache[self.MARKET_US] = results
            return results
        except Exception as e:
            wlog("error", f"[ERROR] 获取美股数据失败: {e}")
            return []
    
    def get_stocks_by_market(self, market: str) -> List[Tuple[str, str]]:
        """根据市场类型获取股票列表"""
        if market == self.MARKET_A:
            return self.get_a_stocks()
        elif market == self.MARKET_HK:
            return self.get_hk_stocks()
        elif market == self.MARKET_US:
            return self.get_us_stocks()
        elif market == self.MARKET_ALL:
            all_stocks = []
            all_stocks.extend(self.get_a_stocks())
            all_stocks.extend(self.get_hk_stocks())
            all_stocks.extend(self.get_us_stocks())
            return all_stocks
        else:
            return []
    
    def get_stocks_by_markets(self, markets: List[str]) -> List[Tuple[str, str]]:
        """根据多个市场类型获取股票列表"""
        if not markets:
            return []
        
        all_stocks = []
        seen = set()
        
        for market in markets:
            stocks = self.get_stocks_by_market(market)
            for stock in stocks:
                key = (stock[0], stock[1])
                if key not in seen:
                    seen.add(key)
                    all_stocks.append(stock)
        
        return all_stocks
    
    def _get_matcher(self, markets: List[str]) -> 'StockMatcher':
        """获取或创建股票匹配器（带缓存）"""
        cache_key = ','.join(sorted(markets))
        
        if cache_key not in self._compiled_matchers:
            stocks = self.get_stocks_by_markets(markets)
            self._compiled_matchers[cache_key] = StockMatcher(stocks)
            
        return self._compiled_matchers[cache_key]
    
    def filter_messages_by_markets(self, messages: List[Dict], markets: List[str], match_code: bool = False) -> List[Dict]:
        """
        根据多个市场筛选包含股票代码或简称的消息（优化版）
        
        Args:
            messages: 消息列表
            markets: 市场列表
            match_code: 是否匹配数字代码，默认False只匹配名称
        """
        if not markets:
            return messages
        
        matcher = self._get_matcher(markets)
        if not matcher.has_patterns():
            wlog("warning", "[警告] 未获取到股票数据，无法进行筛选，返回空结果")
            return []
        
        wlog("info", f"[股票筛选] 使用匹配器: markets={markets}, "
              f"中文简称(>=4)={len(matcher.cn_names_long)}, "
              f"中文简称(=3)={len(matcher.cn_names_3)}")
        
        # 批量匹配
        filtered = []
        matched_count = 0
        for msg in messages:
            content = msg.get('content', '')
            if content and matcher.match(content, match_code=match_code):
                filtered.append(msg)
                matched_count += 1
                # 打印前几条匹配的消息用于调试
                if matched_count <= 3:
                    matched_name = matcher.get_matched_name(content)
                    wlog("info", f"[股票筛选] 匹配到: '{content[:50]}...' -> 匹配词: {matched_name}")
        
        return filtered
    
    def filter_messages_by_stock(self, messages: List[Dict], market: str, match_code: bool = False) -> List[Dict]:
        """筛选包含股票代码或简称的消息"""
        if market == 'none' or not market:
            return messages
        return self.filter_messages_by_markets(messages, [market], match_code=match_code)
    
    def get_market_stats(self) -> Dict[str, int]:
        """获取各市场股票数量统计"""
        return {
            'a_stock': len(self.get_a_stocks()),
            'hk_stock': len(self.get_hk_stocks()),
            'us_stock': len(self.get_us_stocks())
        }


class StockMatcher:
    """
    高效的股票匹配器
    
    优化策略：
    1. 将股票分为三类：数字代码、英文代码、中文简称
    2. 数字代码：使用集合快速查找
    3. 英文代码：预编译单个正则表达式
    4. 中文简称：使用集合 + 简单字符串查找
    """
    
    def __init__(self, stocks: List[Tuple[str, str]]):
        # 数字代码集合（5-6位）
        self.digit_codes: Set[str] = set()
        # 英文代码集合（用于快速预检）
        self.alpha_codes: Set[str] = set()
        # 中文简称集合（长度>=4）
        self.cn_names_long: Set[str] = set()
        # 中文简称集合（长度=3）
        self.cn_names_3: Set[str] = set()
        self.cn_names_long_sorted: List[str] = []
        self.cn_names_3_sorted: List[str] = []
        self.code_to_name: Dict[str, str] = {}
        self.alpha_code_to_name: Dict[str, str] = {}
        self.name_to_code: Dict[str, str] = {}
        
        # 预编译的英文代码正则（如果有的话）
        self.alpha_regex: Optional[re.Pattern] = None
        
        self._build_patterns(stocks)
    
    def _build_patterns(self, stocks: List[Tuple[str, str]]):
        """构建匹配模式"""
        alpha_patterns = []
        
        for code, name in stocks:
            # 处理股票代码
            if code:
                code = code.strip()
                if code.isdigit() and 5 <= len(code) <= 6:
                    self.digit_codes.add(code)
                    self.code_to_name[code] = name.strip() if name else code
                elif code.isalpha() and code.isupper() and len(code) >= 2:
                    upper_code = code.upper()
                    self.alpha_codes.add(upper_code)
                    self.alpha_code_to_name[upper_code] = name.strip() if name else upper_code
                    alpha_patterns.append(re.escape(code))
            
            # 处理股票简称
            if name:
                name = name.strip()
                if code and name and name not in self.name_to_code:
                    self.name_to_code[name] = code
                name_len = len(name)
                if name_len >= 4:
                    self.cn_names_long.add(name)
                elif name_len == 3:
                    self.cn_names_3.add(name)
        
        # 预编译英文代码正则（使用单个正则匹配所有英文代码）
        if alpha_patterns:
            # 按长度降序排序，优先匹配长的
            alpha_patterns.sort(key=len, reverse=True)
            pattern = r'\b(' + '|'.join(alpha_patterns) + r')\b'
            self.alpha_regex = re.compile(pattern, re.IGNORECASE)

        self.cn_names_long_sorted = sorted(self.cn_names_long, key=lambda x: (-len(x), x))
        self.cn_names_3_sorted = sorted(self.cn_names_3)
        
        wlog("info", f"[股票匹配器] 数字代码: {len(self.digit_codes)}, "
              f"英文代码: {len(self.alpha_codes)}, "
              f"中文简称(>=4): {len(self.cn_names_long)}, "
              f"中文简称(=3): {len(self.cn_names_3)}")
    
    def has_patterns(self) -> bool:
        """检查是否有匹配模式"""
        return bool(self.digit_codes or self.alpha_codes or 
                   self.cn_names_long or self.cn_names_3)
    
    def match(self, text: str, match_code: bool = False) -> bool:
        """
        检查文本是否包含股票代码或简称
        
        Args:
            text: 要匹配的文本
            match_code: 是否匹配数字代码，默认False只匹配名称
        
        优化后的匹配逻辑，按效率从高到低：
        1. 先检查长中文简称（>=4字符，直接in查找）
        2. 检查数字代码（可选，提取文本中的数字序列）
        3. 检查英文代码（可选，预编译正则）
        4. 检查短中文简称（3字符，需要边界检查）
        """
        if not text:
            return False
        
        # 1. 检查长中文简称（最快，直接字符串查找）
        for name in self.cn_names_long:
            if name in text:
                return True
        
        # 2. 检查数字代码（仅当 match_code=True 时）
        if match_code and self.digit_codes:
            # 提取所有5-6位数字序列
            digit_matches = re.findall(r'\d{5,6}', text)
            for d in digit_matches:
                if d in self.digit_codes:
                    return True
        
        # 3. 检查英文代码（仅当 match_code=True 时）
        if match_code and self.alpha_regex:
            if self.alpha_regex.search(text):
                return True
        
        # 4. 检查短中文简称（需要边界检查）
        for name in self.cn_names_3:
            if name in text:
                # 简单的边界检查
                idx = text.find(name)
                while idx != -1:
                    # 检查前后是否有边界
                    before_ok = idx == 0 or not _is_chinese(text[idx-1])
                    after_idx = idx + 3
                    after_ok = after_idx >= len(text) or not _is_chinese(text[after_idx])
                    if before_ok or after_ok:
                        return True
                    idx = text.find(name, idx + 1)
        
        return False
    
    def get_matched_name(self, text: str) -> Optional[str]:
        """获取匹配到的股票名称（用于调试）"""
        matches = self.find_matches(text, match_code=False)
        return matches[0] if matches else None

    def resolve_stock_code(self, name: str) -> str:
        """根据匹配出的股票简称反查代码, 用于补充行业分类等结构化字段。"""
        return self.name_to_code.get(name, "")

    def find_matches(self, text: str, match_code: bool = False) -> List[str]:
        """返回文本中命中的所有股票名称/简称, 保持去重后的稳定顺序。"""
        if not text:
            return []

        matches: List[str] = []
        seen: Set[str] = set()

        def add(name: str | None) -> None:
            if not name or name in seen:
                return
            seen.add(name)
            matches.append(name)

        # 检查长中文简称
        for name in self.cn_names_long_sorted:
            if name in text:
                add(name)

        # 检查数字代码
        if match_code and self.digit_codes:
            for d in re.findall(r'\d{5,6}', text):
                if d in self.digit_codes:
                    add(self.code_to_name.get(d, d))

        # 检查英文代码
        if match_code and self.alpha_regex:
            for hit in self.alpha_regex.findall(text):
                code = hit.upper()
                add(self.alpha_code_to_name.get(code, code))

        # 检查短中文简称
        for name in self.cn_names_3_sorted:
            if name in text:
                idx = text.find(name)
                while idx != -1:
                    before_ok = idx == 0 or not _is_chinese(text[idx-1])
                    after_idx = idx + 3
                    after_ok = after_idx >= len(text) or not _is_chinese(text[after_idx])
                    if before_ok or after_ok:
                        add(name)
                        break
                    idx = text.find(name, idx + 1)

        return matches


def _is_chinese(char: str) -> bool:
    """检查字符是否为中文"""
    return '\u4e00' <= char <= '\u9fff'


# 全局实例
_stock_filter_instance: Optional[StockFilter] = None
_stock_data_loaded: bool = False


def get_stock_filter() -> StockFilter:
    """获取全局股票筛选器实例"""
    global _stock_filter_instance
    if _stock_filter_instance is None:
        _stock_filter_instance = StockFilter()
    return _stock_filter_instance


def preload_stock_data():
    """预加载股票数据（在后台线程中执行）"""
    global _stock_data_loaded
    if _stock_data_loaded:
        return
    
    wlog("info", "[股票筛选] 开始预加载股票数据...")
    try:
        sf = get_stock_filter()
        a_count = len(sf.get_a_stocks())
        hk_count = len(sf.get_hk_stocks())
        us_count = len(sf.get_us_stocks())
        
        # 预编译匹配器
        sf._get_matcher(['a_stock'])
        sf._get_matcher(['hk_stock'])
        sf._get_matcher(['us_stock'])
        sf._get_matcher(['a_stock', 'hk_stock', 'us_stock'])
        
        _stock_data_loaded = True
        wlog("info", f"[股票筛选] 预加载完成: A股 {a_count}, 港股 {hk_count}, 美股 {us_count}")
    except Exception as e:
        wlog("error", f"[股票筛选] 预加载失败: {e}")


def is_stock_data_loaded() -> bool:
    """检查股票数据是否已加载"""
    return _stock_data_loaded


def filter_messages_by_market(messages: List[Dict], market: str, match_code: bool = False) -> List[Dict]:
    """便捷函数：根据市场筛选消息"""
    if market == 'none' or not market:
        return messages
    
    stock_filter = get_stock_filter()
    return stock_filter.filter_messages_by_stock(messages, market, match_code=match_code)


def filter_messages_by_markets(messages: List[Dict], markets: List[str], match_code: bool = False) -> List[Dict]:
    """
    便捷函数：根据多个市场筛选消息（支持多选）

    Args:
        messages: 消息列表
        markets: 市场类型列表
        match_code: 是否匹配数字代码，默认False只匹配股票名称
    """
    if not markets:
        return messages

    stock_filter = get_stock_filter()
    return stock_filter.filter_messages_by_markets(messages, markets, match_code=match_code)


def configure_databases(primary_url: str, backup_url: Optional[str] = None) -> None:
    """用 ui 项目的 JYDB_ENGINES URL 覆盖硬编码的 PRIMARY/BACKUP 配置.

    Args:
        primary_url: 形如 'root:pwd@host:port/jydb', 通常来自 main.JYDB_ENGINES['primary']
        backup_url:  形如同上, 来自 main.JYDB_ENGINES['secondary']
    """
    global _stock_filter_instance
    p = _parse_engine_url(primary_url)
    if p:
        StockFilter.PRIMARY_DB_CONFIG = p
    if backup_url:
        b = _parse_engine_url(backup_url)
        if b:
            StockFilter.BACKUP_DB_CONFIG = b
    # 重置单例以让新配置生效
    _stock_filter_instance = None
