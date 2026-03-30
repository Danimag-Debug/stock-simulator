"""
新闻情报分析模块
爬取东方财富、新浪财经等平台的股票近期新闻，进行热度和情绪分析
"""

import re
import time
import random
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, quote

logger = logging.getLogger(__name__)

# 利好关键词（出现会加分）
BULLISH_KEYWORDS = [
    "业绩大增", "净利润增长", "营收增长", "超预期", "高送转", "分红",
    "战略合作", "重大合同", "中标", "新产品", "技术突破", "专利", "获批",
    "扭亏为盈", "业绩预增", "增持", "回购", "大股东增持", "机构调研",
    "国家政策支持", "行业利好", "景气度提升", "市场份额提升",
    "订单增加", "出货量创新高", "产能扩张", "海外市场", "国际化",
    "AI", "人工智能", "算力", "数字化转型", "新能源", "绿色",
    "高端制造", "进口替代", "国产替代",
]

# 利空关键词（出现会减分）
BEARISH_KEYWORDS = [
    "业绩下滑", "净利润下降", "亏损", "营收下降", "低于预期",
    "减持", "大股东减持", "质押", "爆仓", "违规", "立案调查",
    "监管处罚", "退市风险", "ST", "财务造假", "审计意见",
    "诉讼", "仲裁", "资金链紧张", "债务危机",
    "产品召回", "安全事故", "环保违规", "行政处罚",
]

# 热点行业关键词（判断当前市场热点）
HOT_SECTOR_KEYWORDS = {
    "AI/人工智能": ["人工智能", "AI", "大模型", "算力", "GPU", "芯片", "ChatGPT", "大语言模型"],
    "新能源": ["新能源", "光伏", "风电", "储能", "电池", "充电桩", "绿色能源"],
    "半导体": ["半导体", "芯片", "集成电路", "晶圆", "EDA", "国产替代"],
    "医药生物": ["医药", "创新药", "生物制药", "医疗器械", "CXO", "新药获批"],
    "消费复苏": ["消费升级", "消费复苏", "白酒", "旅游", "餐饮", "零售"],
    "军工": ["军工", "国防", "航空", "航天", "导弹", "舰船"],
    "数字经济": ["数字经济", "数字化", "工业互联网", "云计算", "大数据"],
}

# 股票代码 -> 行业分类（简化映射，基于常识）
STOCK_INDUSTRY_MAP = {
    # 科技/AI
    "603986": "AI/人工智能", "688981": "半导体", "002415": "AI/人工智能",
    "300059": "数字经济", "603259": "医药生物", "000725": "半导体",
    # 新能源
    "300750": "新能源", "601012": "新能源", "300274": "新能源", "002594": "新能源",
    # 医药
    "600276": "医药生物", "300760": "医药生物", "300142": "医药生物",
    # 消费
    "600519": "消费复苏", "000858": "消费复苏", "000568": "消费复苏",
    "600887": "消费复苏", "000333": "消费复苏", "000651": "消费复苏",
    # 金融
    "600030": "金融", "601166": "金融", "002142": "金融", "600036": "金融",
    # 制造
    "002475": "高端制造", "300124": "高端制造", "600031": "高端制造",
}


def _fetch_url(url: str, timeout: int = 8) -> Optional[str]:
    """简单 HTTP 请求，返回响应文本"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://finance.sina.com.cn/",
    }
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="ignore")
    except (URLError, HTTPError, Exception) as e:
        logger.debug(f"[news_fetch] {url} 请求失败: {e}")
        return None


def fetch_stock_news_eastmoney(code: str, name: str) -> List[Dict]:
    """
    从东方财富获取股票新闻（公告 + 资讯）
    使用东方财富的公开 API 接口
    """
    news_list = []
    
    # 东方财富资讯 API（公开接口）
    # 注意：secid 格式：0.代码（深市）或 1.代码（沪市）
    if code.startswith("6"):
        secid = f"1.{code}"
    elif code.startswith("688"):
        secid = f"1.{code}"
    else:
        secid = f"0.{code}"
    
    url = (
        f"https://np-anotice-stock.eastmoney.com/api/security/ann?"
        f"sr=-1&page_size=5&page_index=1&ann_type=A&client_source=web&f_node=0&s_node=0"
        f"&fs=EQ%2C{quote(secid)}"
    )
    
    text = _fetch_url(url, timeout=6)
    if text:
        try:
            data = json.loads(text)
            items = data.get("data", {}).get("list", [])
            for item in items[:5]:
                title = item.get("title", "")
                if title:
                    news_list.append({
                        "title": title,
                        "source": "东方财富公告",
                        "time": item.get("notice_date", ""),
                    })
        except Exception:
            pass
    
    return news_list


def fetch_hot_market_news() -> List[str]:
    """
    获取当前市场热点新闻标题（从东方财富财经新闻）
    用于判断当前哪些行业/主题处于市场热点中
    """
    headlines = []
    
    # 东方财富财经头条 API
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=20&page_index=1&ann_type=A&client_source=web"
    
    text = _fetch_url(url, timeout=6)
    if text:
        try:
            data = json.loads(text)
            items = data.get("data", {}).get("list", [])
            for item in items[:20]:
                title = item.get("title", "")
                if title:
                    headlines.append(title)
        except Exception:
            pass
    
    # 新浪财经快讯（备用）
    if not headlines:
        url2 = "https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&page=1&page_size=20&type=1"
        text2 = _fetch_url(url2, timeout=5)
        if text2:
            try:
                data = json.loads(text2)
                items = data.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
                for item in items[:20]:
                    content = item.get("rich_text", "") or item.get("text", "")
                    if content:
                        headlines.append(content[:100])
            except Exception:
                pass
    
    return headlines


def analyze_sentiment(text: str) -> Tuple[float, List[str]]:
    """
    分析文本情绪，返回 (情绪分 -1到+1, 匹配到的关键词列表)
    """
    score = 0.0
    matched = []
    
    for kw in BULLISH_KEYWORDS:
        if kw in text:
            score += 0.15
            matched.append(f"利好:{kw}")
    
    for kw in BEARISH_KEYWORDS:
        if kw in text:
            score -= 0.2
            matched.append(f"利空:{kw}")
    
    return max(-1.0, min(1.0, score)), matched


def get_hot_sectors_from_news(headlines: List[str]) -> Dict[str, float]:
    """
    根据新闻标题列表，统计当前市场热点行业及其热度分
    返回 {行业名: 热度分(0-1)}
    """
    sector_counts = {sector: 0 for sector in HOT_SECTOR_KEYWORDS}
    total = max(len(headlines), 1)
    
    all_text = " ".join(headlines)
    for sector, keywords in HOT_SECTOR_KEYWORDS.items():
        for kw in keywords:
            count = all_text.count(kw)
            sector_counts[sector] += count
    
    # 归一化到 0-1
    max_count = max(sector_counts.values()) if sector_counts.values() else 1
    if max_count == 0:
        max_count = 1
    
    result = {}
    for sector, count in sector_counts.items():
        result[sector] = round(count / max_count, 3)
    
    return result


def get_stock_industry(code: str, name: str) -> Optional[str]:
    """
    根据股票代码和名称判断所属行业
    """
    # 先查静态映射
    if code in STOCK_INDUSTRY_MAP:
        return STOCK_INDUSTRY_MAP[code]
    
    # 根据股票名称关键词判断
    name_rules = [
        (["芯片", "半导", "集成电路", "晶圆", "EDA"], "半导体"),
        (["AI", "智能", "机器人", "算力", "云", "互联网", "软件", "数字"], "AI/人工智能"),
        (["光伏", "风电", "储能", "锂电", "充电", "新能源", "电池"], "新能源"),
        (["药", "医疗", "生物", "基因", "CXO", "疫苗", "医院"], "医药生物"),
        (["白酒", "酒", "饮料", "食品", "餐饮", "旅游", "酒店", "零售", "百货"], "消费复苏"),
        (["银行", "证券", "保险", "基金", "信托", "金融"], "金融"),
        (["军工", "国防", "航空", "航天", "武器"], "军工"),
        (["钢铁", "煤炭", "有色", "铜", "铝", "矿"], "资源材料"),
        (["地产", "房地产", "物业", "建筑", "装修"], "地产建筑"),
    ]
    
    for keywords, industry in name_rules:
        for kw in keywords:
            if kw in name:
                return industry
    
    # 按代码前缀粗分
    if code.startswith("688"):
        return "科技创新"
    elif code.startswith("300"):
        return "创业板成长"
    
    return "其他"


# ─── 缓存机制（避免频繁请求） ───
_news_cache = {}
_hot_sectors_cache = {"data": {}, "time": None}
_CACHE_TTL = 1800  # 30分钟缓存


def get_hot_sectors_cached() -> Dict[str, float]:
    """带缓存的热点行业获取"""
    now = datetime.now()
    if _hot_sectors_cache["time"] and (now - _hot_sectors_cache["time"]).seconds < _CACHE_TTL:
        return _hot_sectors_cache["data"]
    
    try:
        headlines = fetch_hot_market_news()
        sectors = get_hot_sectors_from_news(headlines)
        _hot_sectors_cache["data"] = sectors
        _hot_sectors_cache["time"] = now
        logger.info(f"[news] 热点行业更新: {sectors}")
    except Exception as e:
        logger.warning(f"[news] 获取热点行业失败: {e}")
    
    return _hot_sectors_cache.get("data", {})


def score_news_and_sector(code: str, name: str) -> Tuple[int, List[str]]:
    """
    综合新闻情绪 + 行业热度，返回 (新闻行业综合分 0-30, 理由列表)
    """
    total_score = 0
    reasons = []
    
    # 1. 行业热度评分（0-15分）
    try:
        hot_sectors = get_hot_sectors_cached()
        industry = get_stock_industry(code, name)
        
        if industry and industry in hot_sectors:
            heat = hot_sectors[industry]
            if heat >= 0.8:
                sector_score = 15
                reasons.append(f"🔥{industry}(极热)")
            elif heat >= 0.5:
                sector_score = 10
                reasons.append(f"🔆{industry}(热门)")
            elif heat >= 0.2:
                sector_score = 5
                reasons.append(f"📈{industry}(活跃)")
            else:
                sector_score = 2
                reasons.append(f"{industry}")
            total_score += sector_score
        elif industry:
            reasons.append(f"{industry}")
            total_score += 2  # 基础分
    except Exception as e:
        logger.debug(f"[news] 行业评分失败 {code}: {e}")
    
    # 2. 近期公告/新闻情绪（0-15分）
    try:
        cache_key = f"news_{code}"
        if cache_key in _news_cache:
            cached = _news_cache[cache_key]
            if (datetime.now() - cached["time"]).seconds < _CACHE_TTL:
                return total_score + cached["score"], reasons + cached["reasons"]
        
        news_items = fetch_stock_news_eastmoney(code, name)
        
        if news_items:
            all_titles = " ".join([n["title"] for n in news_items])
            sentiment_score, matched_kws = analyze_sentiment(all_titles)
            
            # 情绪分映射到 0-15
            news_score = int((sentiment_score + 1) / 2 * 15)
            total_score += news_score
            
            if sentiment_score > 0.3:
                reasons.append(f"近期公告利好({len([k for k in matched_kws if '利好' in k])}项)")
            elif sentiment_score < -0.2:
                reasons.append(f"⚠️近期有利空信息")
            elif news_items:
                reasons.append(f"近期有{len(news_items)}条公告")
            
            # 缓存
            _news_cache[cache_key] = {
                "score": news_score,
                "reasons": reasons[-1:] if reasons else [],
                "time": datetime.now()
            }
        else:
            # 无公告也给基础分（无公告不代表坏事）
            total_score += 5
    except Exception as e:
        logger.debug(f"[news] 新闻评分失败 {code}: {e}")
        total_score += 3  # 无法获取时给基础分
    
    return min(total_score, 30), reasons
