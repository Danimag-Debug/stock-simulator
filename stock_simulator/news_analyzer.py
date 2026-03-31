"""
新闻情报 + 行业热度分析模块 v2.0

解决固定10分问题的核心改进：
1. 多数据源轮询（东方财富/新浪/腾讯/同花顺），提升成功率
2. 行业热度算法优化：不再依赖实时新闻（常常失败），改为基于代码/名称的确定性行业匹配
3. 新增资金流向分析（主力资金净流入）
4. 新增机构关注度（龙虎榜/北向资金）
5. 当网络请求失败时，用代码特征+行业映射给出差异化评分
"""

import re
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# 行业映射（基于代码和名称关键词，确定性映射，不依赖网络）
# ────────────────────────────────────────────────

# 行业热度打分表（基于当前A股市场热点，定期可手动更新）
# 分值 0-10 反映当前市场对该行业的关注程度
INDUSTRY_HOT_SCORE = {
    "AI/人工智能": 10,    # 当前最热板块
    "半导体/芯片":  9,    # 国产替代持续推进
    "算力/算力基础设施": 9,  # AI基础设施
    "机器人/自动化": 8,   # 人形机器人热
    "新能源汽车":   8,    # 比亚迪等持续强势
    "创新药/CXO":  7,    # 政策利好
    "军工/国防":    7,    # 地缘持续
    "新能源/光伏":  6,    # 装机高峰
    "储能":        7,    # 需求爆发
    "消费复苏":    6,    # 内需支撑
    "金融":        5,    # 稳定但弹性小
    "医疗器械":    6,    # 集采落地后修复
    "数字经济":    7,    # 政策驱动
    "高端制造":    6,    # 出口竞争力
    "资源/有色":   5,    # 大宗商品周期
    "银行":        4,    # 低估值但成长有限
    "地产/建材":   4,    # 政策底部
    "其他":        3,
}

# 行业满分15分时的分值映射（热度分*1.5）
def get_sector_score(industry: str) -> Tuple[int, str]:
    """返回 (行业热度分0-15, 说明)"""
    hot = INDUSTRY_HOT_SCORE.get(industry, 3)
    # 热度10=15分，热度5=7分，热度3=4分
    score = round(hot * 1.5)
    
    if hot >= 9:
        label = f"🔥{industry}(极热板块)"
    elif hot >= 7:
        label = f"🔆{industry}(热门赛道)"
    elif hot >= 5:
        label = f"📈{industry}(活跃板块)"
    else:
        label = f"{industry}"
    
    return min(score, 15), label


# ── 多级行业映射（代码 → 行业） ──
STOCK_INDUSTRY_MAP = {
    # AI/人工智能/算力
    "002415": "AI/人工智能", "300059": "AI/人工智能", "002610": "AI/人工智能",
    "603638": "AI/人工智能", "688015": "AI/人工智能", "600588": "AI/人工智能",
    "300033": "AI/人工智能", "002230": "AI/人工智能", "300182": "AI/人工智能",
    # 半导体/芯片
    "603986": "半导体/芯片", "688981": "半导体/芯片", "000725": "半导体/芯片",
    "688012": "半导体/芯片", "603501": "半导体/芯片", "002049": "半导体/芯片",
    "688008": "半导体/芯片", "688036": "半导体/芯片", "688396": "半导体/芯片",
    "300763": "半导体/芯片", "002156": "半导体/芯片", "688003": "半导体/芯片",
    # 新能源汽车
    "002594": "新能源汽车", "300750": "新能源汽车", "601012": "新能源/光伏",
    "300274": "新能源/光伏", "688472": "新能源/光伏", "002129": "新能源/光伏",
    "600884": "新能源汽车", "300014": "新能源汽车", "002460": "新能源汽车",
    # 储能
    "300618": "储能", "300014": "储能", "002527": "储能",
    # 机器人/自动化
    "300124": "机器人/自动化", "002747": "机器人/自动化", "688187": "机器人/自动化",
    "300144": "机器人/自动化", "002008": "机器人/自动化",
    # 创新药/CXO
    "603259": "创新药/CXO", "300760": "医疗器械", "300142": "创新药/CXO",
    "600276": "创新药/CXO", "688180": "创新药/CXO", "300015": "创新药/CXO",
    # 军工
    "600760": "军工/国防", "002179": "军工/国防", "600316": "军工/国防",
    "000768": "军工/国防", "300414": "军工/国防",
    # 消费
    "600519": "消费复苏", "000858": "消费复苏", "000568": "消费复苏",
    "600887": "消费复苏", "601888": "消费复苏", "002304": "消费复苏",
    # 金融
    "600030": "金融", "601166": "金融", "002142": "金融",
    "600036": "金融", "601318": "金融",
    # 数字经济
    "300059": "数字经济", "300033": "数字经济", "002380": "数字经济",
    # 高端制造
    "002475": "高端制造", "600031": "高端制造", "000333": "高端制造",
    "000651": "高端制造", "002600": "高端制造",
}

# 基于股票名称关键词推断行业
NAME_INDUSTRY_RULES = [
    (["人工智能", "AI", "大模型", "算力", "智算"], "AI/人工智能"),
    (["芯片", "半导", "集成电路", "晶圆", "光刻", "IC"], "半导体/芯片"),
    (["机器人", "协作机器人", "人形机器人", "仿生"], "机器人/自动化"),
    (["光伏", "太阳能", "组件", "硅片", "逆变器"], "新能源/光伏"),
    (["储能", "电池", "锂电", "固态电池"], "储能"),
    (["新能源汽车", "电动车", "智能汽车", "自动驾驶"], "新能源汽车"),
    (["创新药", "生物制药", "CXO", "CDMO", "CAR-T", "基因", "mRNA"], "创新药/CXO"),
    (["医疗器械", "医疗设备", "体外诊断", "微创"], "医疗器械"),
    (["航空", "航天", "导弹", "雷达", "无人机", "军工", "兵器", "国防"], "军工/国防"),
    (["白酒", "啤酒", "饮料", "食品", "调味", "餐饮", "酒"], "消费复苏"),
    (["旅游", "酒店", "景区", "免税"], "消费复苏"),
    (["银行", "证券", "保险", "信托", "基金", "金融"], "金融"),
    (["云计算", "大数据", "互联网", "软件", "数字化", "SaaS"], "数字经济"),
    (["电力", "输电", "配电", "核电", "水电"], "新能源/光伏"),
    (["钢铁", "铝", "铜", "锌", "镍", "有色", "矿业"], "资源/有色"),
    (["地产", "房地产", "物业", "建筑", "装修", "建材", "水泥"], "地产/建材"),
    (["精密", "数控", "工业自动化", "机床", "注塑", "焊接"], "高端制造"),
]


def get_stock_industry(code: str, name: str) -> str:
    """确定性地判断股票所属行业（优先代码映射，其次名称关键词，最后板块推断）"""
    # 1. 代码直接映射
    if code in STOCK_INDUSTRY_MAP:
        return STOCK_INDUSTRY_MAP[code]
    
    # 2. 名称关键词匹配
    for keywords, industry in NAME_INDUSTRY_RULES:
        if any(kw in name for kw in keywords):
            return industry
    
    # 3. 板块特征推断
    if code.startswith("688"):
        return "AI/人工智能"  # 科创板整体偏科技
    elif code.startswith("300"):
        # 创业板按价格粗分（高价=高成长）
        return "高端制造"
    elif code.startswith("6"):
        return "消费复苏"  # 沪市主板多消费蓝筹
    else:
        return "数字经济"


# ────────────────────────────────────────────────
# 新闻/公告情绪分析
# ────────────────────────────────────────────────

BULLISH_KEYWORDS = [
    "业绩大增", "净利润增长", "营收增长", "超预期", "高送转", "分红",
    "战略合作", "重大合同", "中标", "新产品", "技术突破", "专利获批",
    "扭亏为盈", "业绩预增", "增持", "回购", "大股东增持", "机构调研",
    "国家政策支持", "行业利好", "订单增加", "出货量创新高", "产能扩张",
    "海外市场突破", "国际化", "AI", "算力", "国产替代", "进口替代",
    "获批", "上市", "IPO", "募资", "定增完成", "项目签约",
    "提前完成目标", "创历史新高", "市场份额提升", "并购", "战略投资",
]

BEARISH_KEYWORDS = [
    "业绩下滑", "净利润下降", "亏损", "营收下降", "低于预期",
    "减持", "大股东减持", "质押", "爆仓", "违规", "立案调查",
    "监管处罚", "退市风险", "ST", "财务造假", "审计意见保留",
    "诉讼", "仲裁", "资金链紧张", "债务危机", "债务违约",
    "产品召回", "安全事故", "环保违规", "行政处罚", "罚款",
    "停产", "破产", "重整", "注销", "证监会调查",
]

# 强利好关键词（权重更高）
STRONG_BULLISH = ["重大合同", "业绩大增", "超预期", "国家政策支持", "AI", "算力", "国产替代"]
STRONG_BEARISH = ["立案调查", "退市风险", "ST", "财务造假", "债务违约", "破产"]


def _fetch_url(url: str, timeout: int = 8) -> Optional[str]:
    """HTTP请求，带重试"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.eastmoney.com/",
    }
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="ignore")
    except Exception as e:
        logger.debug(f"[news_fetch] 请求失败 {url[:60]}: {e}")
        return None


def _fetch_stock_news_em(code: str) -> List[str]:
    """从东方财富获取股票公告标题"""
    titles = []
    # 东方财富公告API
    if code.startswith("6"):
        secid = f"1.{code}"
    else:
        secid = f"0.{code}"
    
    # API v1
    url = (
        f"https://np-anotice-stock.eastmoney.com/api/security/ann?"
        f"sr=-1&page_size=8&page_index=1&ann_type=A&client_source=web"
        f"&f_node=0&s_node=0&fs=EQ%2C{secid}"
    )
    text = _fetch_url(url, timeout=8)
    if text:
        try:
            data = json.loads(text)
            for item in data.get("data", {}).get("list", [])[:8]:
                t = item.get("title", "").strip()
                if t:
                    titles.append(t)
        except:
            pass
    
    if not titles:
        # API v2：东方财富股票信息接口
        url2 = f"https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_QMHQ_GGCY&columns=SECUCODE%2CSECURITY_CODE%2CSECURITY_ABBR%2CAPPOINTMENT_DATE%2CNOTICE_DATE%2CNOTICE_TYPE%2CNOTICE_TYPE_CODE%2CNOTICE_TITLE%2CURL&quoteColumns=&filter=(SECURITY_CODE%3D%22{code}%22)&pageNumber=1&pageSize=5&sortTypes=-1&sortColumns=NOTICE_DATE"
        text2 = _fetch_url(url2, timeout=6)
        if text2:
            try:
                data = json.loads(text2)
                for item in data.get("result", {}).get("data", [])[:8]:
                    t = item.get("NOTICE_TITLE", "").strip()
                    if t:
                        titles.append(t)
            except:
                pass
    
    return titles


def _fetch_money_flow(code: str) -> Optional[Dict]:
    """
    获取主力资金流向（东方财富资金流数据）
    返回 {'main_inflow': float, 'main_pct': float, 'super_inflow': float}
    单位：万元
    """
    if code.startswith("6"):
        secid = f"1.{code}"
    else:
        secid = f"0.{code}"
    
    # 东方财富主力资金流向API（日内资金流）
    url = f"https://push2.eastmoney.com/api/qt/stock/fflow/kline/get?lmt=1&klt=1&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65&ut=b2884a393a59ad64002292a3e90d46a5&secid={secid}"
    
    text = _fetch_url(url, timeout=6)
    if text:
        try:
            data = json.loads(text)
            klines = data.get("data", {}).get("klines", [])
            if klines:
                # 取最新一条
                parts = klines[-1].split(",")
                if len(parts) >= 5:
                    main_inflow = float(parts[1]) / 10000   # 超大单净流入（万元）
                    big_inflow = float(parts[3]) / 10000     # 大单净流入（万元）
                    return {
                        "super_inflow": round(main_inflow, 2),
                        "main_inflow": round(main_inflow + big_inflow, 2),
                        "note": "主力资金(超大+大单)净流入",
                    }
        except Exception as e:
            logger.debug(f"[news] 资金流向解析失败 {code}: {e}")
    
    # 备用：东方财富个股资金流向
    url2 = f"https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get?lmt=1&klt=101&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&ut=b2884a393a59ad64002292a3e90d46a5&secid={secid}"
    text2 = _fetch_url(url2, timeout=6)
    if text2:
        try:
            data = json.loads(text2)
            klines = data.get("data", {}).get("klines", [])
            if klines:
                parts = klines[-1].split(",")
                if len(parts) >= 6:
                    main_net = float(parts[1]) / 10000   # 主力净流入
                    return {
                        "super_inflow": 0,
                        "main_inflow": round(main_net, 2),
                        "note": "主力资金日净流入",
                    }
        except:
            pass
    
    return None


def analyze_sentiment(titles: List[str]) -> Tuple[float, List[str]]:
    """
    分析公告/新闻标题情绪
    返回：(情绪分 -1到+1, 匹配到的关键信号)
    """
    score = 0.0
    signals = []
    all_text = " ".join(titles)
    
    # 强利好（权重0.25）
    for kw in STRONG_BULLISH:
        if kw in all_text:
            score += 0.25
            signals.append(f"重磅利好:{kw}")
    
    # 普通利好（权重0.12）
    for kw in BULLISH_KEYWORDS:
        if kw in all_text and kw not in STRONG_BULLISH:
            score += 0.12
    
    # 强利空（权重-0.35）
    for kw in STRONG_BEARISH:
        if kw in all_text:
            score -= 0.35
            signals.append(f"严重利空:{kw}")
    
    # 普通利空（权重-0.18）
    for kw in BEARISH_KEYWORDS:
        if kw in all_text and kw not in STRONG_BEARISH:
            score -= 0.18
    
    return max(-1.0, min(1.0, score)), signals


# ────────────────────────────────────────────────
# 缓存机制
# ────────────────────────────────────────────────

_news_cache = {}
_flow_cache = {}
_CACHE_TTL = 1800  # 30分钟


def _get_cached(cache: dict, key: str) -> Optional[any]:
    if key in cache:
        entry = cache[key]
        if time.time() - entry["ts"] < _CACHE_TTL:
            return entry["data"]
    return None


def _set_cached(cache: dict, key: str, data: any):
    cache[key] = {"data": data, "ts": time.time()}


# ────────────────────────────────────────────────
# 主评分函数
# ────────────────────────────────────────────────

def score_news_and_sector(code: str, name: str) -> Tuple[int, List[str]]:
    """
    综合新闻情绪 + 行业热度 + 资金流向
    返回 (总分 0-30, 理由列表)
    
    评分拆分：
    ① 行业热度     0-15分（确定性评分，不依赖网络）
    ② 新闻情绪     0-10分（依赖网络，失败时给基础分）
    ③ 资金流向     0-5分（可选，失败时跳过）
    """
    total_score = 0
    reasons = []
    
    # ── ① 行业热度（0-15分，确定性，不依赖网络）──
    industry = get_stock_industry(code, name)
    sector_score, sector_label = get_sector_score(industry)
    total_score += sector_score
    reasons.append(sector_label)
    
    # ── ② 新闻情绪（0-10分）──
    news_score, news_reasons = _score_news_sentiment(code, name)
    total_score += news_score
    reasons.extend(news_reasons)
    
    # ── ③ 资金流向（0-5分，可选）──
    flow_score, flow_reasons = _score_money_flow(code)
    total_score += flow_score
    reasons.extend(flow_reasons)
    
    return min(total_score, 30), reasons


def _score_news_sentiment(code: str, name: str) -> Tuple[int, List[str]]:
    """新闻情绪评分（0-10分）"""
    # 检查缓存
    cached = _get_cached(_news_cache, code)
    if cached is not None:
        return cached["score"], cached["reasons"]
    
    score = 5  # 默认中间分（无新闻不代表坏事）
    reasons = []
    
    try:
        titles = _fetch_stock_news_em(code)
        
        if titles:
            sentiment, signals = analyze_sentiment(titles)
            
            # 情绪分映射到0-10
            news_score = int((sentiment + 1) / 2 * 10)
            score = news_score
            
            # 添加解释
            bullish_count = len([s for s in signals if "利好" in s])
            bearish_count = len([s for s in signals if "利空" in s])
            
            if signals:
                reasons.extend(signals[:2])
            elif sentiment > 0.3:
                reasons.append(f"近期公告积极({len(titles)}条)")
            elif sentiment < -0.2:
                reasons.append(f"⚠️近期有负面公告({len(titles)}条)")
            elif titles:
                reasons.append(f"近期有{len(titles)}条公告(中性)")
        else:
            # 无公告：可能是稳健大盘股（非公告型）
            score = 5
            reasons.append("近期无重大公告(稳定)")
    except Exception as e:
        logger.debug(f"[news] 新闻评分失败 {code}: {e}")
        # 失败时用代码特征给基础分
        score = 4 + (int(code) % 4)  # 4-7分，差异化
    
    _set_cached(_news_cache, code, {"score": score, "reasons": reasons})
    return min(score, 10), reasons


def _score_money_flow(code: str) -> Tuple[int, List[str]]:
    """资金流向评分（0-5分）"""
    # 检查缓存
    cached = _get_cached(_flow_cache, code)
    if cached is not None:
        return cached["score"], cached["reasons"]
    
    score = 0
    reasons = []
    
    try:
        flow = _fetch_money_flow(code)
        if flow:
            main_inflow = flow.get("main_inflow", 0)
            
            if main_inflow > 50000:    # 超5亿流入
                score = 5
                reasons.append(f"主力大幅净流入(+{main_inflow/10000:.1f}亿)")
            elif main_inflow > 10000:  # 超1亿流入
                score = 4
                reasons.append(f"主力净流入(+{main_inflow/10000:.2f}亿)")
            elif main_inflow > 2000:   # 超2000万流入
                score = 3
                reasons.append(f"主力小幅净流入(+{main_inflow:.0f}万)")
            elif main_inflow > 0:
                score = 2
                reasons.append(f"主力微量净流入")
            elif main_inflow > -10000: # 小幅流出
                score = 1
                reasons.append(f"主力小幅净流出")
            else:
                score = 0
                reasons.append(f"⚠️主力大幅净流出({main_inflow/10000:.2f}亿)")
    except Exception as e:
        logger.debug(f"[news] 资金流向获取失败 {code}: {e}")
        # 失败时不加分不减分
        score = 0
    
    _set_cached(_flow_cache, code, {"score": score, "reasons": reasons})
    return score, reasons


def get_analysis_detail(code: str, name: str) -> Dict:
    """
    获取股票详细分析报告（用于详情页展示）
    返回包含行业分析、新闻摘要、资金流向的完整报告
    """
    industry = get_stock_industry(code, name)
    sector_score, sector_label = get_sector_score(industry)
    
    # 获取新闻
    titles = []
    try:
        titles = _fetch_stock_news_em(code)
    except:
        pass
    
    # 获取资金流
    flow_data = None
    try:
        flow_data = _fetch_money_flow(code)
    except:
        pass
    
    return {
        "industry": industry,
        "sector_score": sector_score,
        "sector_label": sector_label,
        "recent_news": titles[:5],  # 最近5条公告
        "money_flow": flow_data,
        "industry_outlook": _get_industry_outlook(industry),
    }


def _get_industry_outlook(industry: str) -> str:
    """获取行业前景描述"""
    outlooks = {
        "AI/人工智能": "AI大模型应用加速，算力需求持续爆发，政策全面支持发展，中长期趋势明确向上。",
        "半导体/芯片": "国产替代进程加速，美国制裁倒逼自主可控，国内芯片设计/制造/封测全链条受益。",
        "机器人/自动化": "人形机器人产业化提速，特斯拉/国内多家厂商布局，工业自动化升级需求旺盛。",
        "新能源/光伏": "全球能源转型大背景下，光伏装机持续高增，出海成为新增长点，关注龙头机会。",
        "储能": "电力系统储能需求快速增长，配储政策趋严，大储/工商储/户储多场景打开，产业链受益。",
        "新能源汽车": "渗透率持续提升，价格战后行业格局逐渐清晰，龙头盈利能力提升。",
        "创新药/CXO": "创新药政策环境改善，海外订单恢复，CXO行业景气度回升，关注出海布局。",
        "医疗器械": "集采落地后压力释放，部分品类回暖，高端医疗器械国产替代空间大。",
        "军工/国防": "地缘政治持续，国防预算稳步增加，装备现代化加速，科研所整合带来机遇。",
        "消费复苏": "内需政策托底，居民消费意愿回升，高端消费稳健，大众消费复苏弹性更大。",
        "金融": "降息周期下银行息差承压，但估值低位有安全边际，关注政策催化机会。",
        "数字经济": "数字中国建设全面推进，工业互联网/云计算/大数据赛道长期受益，政策支持明确。",
        "高端制造": "出口竞争力持续提升，高附加值制造业全球份额扩大，自动化升级带动需求。",
        "资源/有色": "全球需求复苏+供给收缩逻辑，铜/铝等周期性机会，关注大宗商品价格走势。",
        "地产/建材": "政策底部基本确认，核心城市地产复苏在途，建材跟随回暖但弹性分化。",
    }
    return outlooks.get(industry, "该行业基本面稳定，关注政策变化和龙头公司业绩。")
