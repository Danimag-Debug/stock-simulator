"""
大盘环境判断模块 v2.0
从专业交易员视角判断当前市场环境，指导选股策略和仓位管理

v2.0 改动：
- 移除对 Tushare Pro 的依赖
- 改用东方财富免费 API 获取上证指数实时和历史K线数据
- 不再需要 set_tushare()，完全独立运行

核心逻辑：
不看大盘做选股，等于闭眼开车。
大盘暴跌时再好的技术形态也会被拖下水。

环境分级：
- 牛市(强势): MA5 > MA20 > MA60，近期放量上涨 → 正常选股，放大仓位
- 震荡(中性): 均线交织，涨跌互现 → 正常选股，标准仓位
- 弱势(偏空): MA5 < MA20，成交量萎缩 → 收紧筛选，降低仓位上限
- 暴跌(危险): 单日跌幅>2%或连续3日大跌 → 停止推荐，建议观望

输入数据来源：
1. 上证指数(000001.SH) 历史K线（东方财富 push2 API）
2. 涨跌幅、成交量从K线数据计算
"""

import logging
import time as _time
import urllib.request
import urllib.error
import json as _json
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ─── 缓存 ───
_market_cache = {}
_CACHE_TTL = 1800  # 30分钟（盘中每30分钟更新）


def analyze_market_regime() -> Dict:
    """
    分析当前大盘环境
    
    返回:
    {
        "regime": str,          # "强势"/"震荡"/"弱势"/"暴跌"
        "regime_score": float,  # 0-100，越高越适合做多
        "sh_change_pct": float, # 上证今日涨跌幅
        "sh_price": float,      # 上证当前点位
        "ma5_vs_ma20": float,   # MA5相对MA20偏离%
        "ma20_vs_ma60": float,  # MA20相对MA60偏离%
        "volume_trend": str,    # "放量"/"缩量"/"正常"
        "advance_decline": str, # "普涨"/"分化"/"普跌"
        "description": str,     # 环境描述
        "position_limit": float,# 建议最大仓位比例(0-1)
        "score_threshold": int, # 建议最低评分门槛
        "advice": str,          # 操作建议
    }
    """
    # 检查缓存
    now = _time.time()
    if _market_cache.get("data") and now - _market_cache.get("ts", 0) < _CACHE_TTL:
        return _market_cache["data"]
    
    result = _calculate_regime()
    _market_cache["data"] = result
    _market_cache["ts"] = now
    
    logger.info(f"[大盘环境] {result['regime']} | 上证 {result.get('sh_price', 0):.0f} | {result.get('sh_change_pct', 0):+.2f}% | 建议: {result['advice']}")
    return result


# 兼容旧代码（不再需要，但保留空实现以防其他地方调用）
def set_tushare(ts_instance):
    """保留空实现以兼容旧代码"""
    pass


def _fetch_sh_index_daily(days: int = 120) -> Optional[list]:
    """
    通过东方财富 API 获取上证指数日K线数据
    
    返回: list of dict，每个 dict 含 date, close, volume, open, high, low
    按日期升序排列（旧→新）
    """
    try:
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days + 30)).strftime('%Y%m%d')  # 多取30天缓冲
        
        # 东方财富日K线API
        # secid=1.000001 (1=沪市, 000001=上证指数)
        # klt=101 (日线)
        # fqt=0 (不复权)
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid=1.000001"
            f"&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101&fqt=0&beg={start_date}&end={end_date}&lmt={days + 30}"
        )
        
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
        })
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode('utf-8'))
        
        if not data or data.get("rc") != 0 or not data.get("data"):
            logger.warning("[大盘环境] 东方财富API返回异常")
            return None
        
        klines = data["data"].get("klines", [])
        if not klines:
            return None
        
        # 解析K线: "日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率"
        result = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            result.append({
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]) if len(parts) > 6 else 0,
                "change_pct": float(parts[8]) if len(parts) > 8 else 0,
                "change_amt": float(parts[9]) if len(parts) > 9 else 0,
            })
        
        # 取最近 N 天
        return result[-days:] if len(result) > days else result
    
    except urllib.error.URLError as e:
        logger.error(f"[大盘环境] 东方财富API网络错误: {e}")
        return None
    except Exception as e:
        logger.error(f"[大盘环境] 获取上证指数数据失败: {e}")
        return None


def _calculate_regime() -> Dict:
    """计算大盘环境（内部函数）"""
    
    # 默认返回（数据不可用时）
    default = {
        "regime": "震荡",
        "regime_score": 50.0,
        "sh_change_pct": 0,
        "sh_price": 0,
        "ma5_vs_ma20": 0,
        "ma20_vs_ma60": 0,
        "volume_trend": "正常",
        "advance_decline": "分化",
        "description": "无法获取大盘数据，按中性环境处理",
        "position_limit": 0.6,
        "score_threshold": 62,
        "advice": "数据获取中，建议谨慎操作"
    }
    
    # 获取上证指数日K线数据
    klines = _fetch_sh_index_daily(120)
    if not klines or len(klines) < 30:
        logger.warning(f"[大盘环境] 获取到 {len(klines) if klines else 0} 天数据，不足30天，使用默认值")
        return default
    
    closes = [k["close"] for k in klines]
    volumes = [k["volume"] for k in klines]
    
    # ── 核心指标计算 ──
    last_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else last_close
    sh_change_pct = klines[-1].get("change_pct", 0)
    
    # MA5, MA20, MA60
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    
    ma5_vs_ma20 = round((ma5 - ma20) / ma20 * 100, 2)
    ma20_vs_ma60 = round((ma20 - ma60) / ma60 * 100, 2)
    
    # 近5日涨跌幅
    chg_5d = round((last_close - closes[-6]) / closes[-6] * 100, 2) if len(closes) >= 6 else 0
    
    # 成交量趋势（对比近5日均量 vs 前20日均量）
    vol_5d_avg = sum(volumes[-5:]) / 5
    vol_20d_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else vol_5d_avg
    vol_ratio = vol_5d_avg / vol_20d_avg if vol_20d_avg > 0 else 1.0
    
    if vol_ratio > 1.3:
        volume_trend = "放量"
    elif vol_ratio < 0.7:
        volume_trend = "缩量"
    else:
        volume_trend = "正常"
    
    # 涨跌家数（通过涨跌幅推断）
    advance_decline = "分化"
    if abs(sh_change_pct) > 1.0:
        advance_decline = "普涨" if sh_change_pct > 0 else "普跌"
    
    # ═══════════════════════════════════
    # 综合评分（0-100）
    # ═══════════════════════════════════
    regime_score = 50.0
    
    # 1. 均线多头排列（+30分）
    if ma5 > ma20 > ma60:
        regime_score += 25
    elif ma5 > ma20 and ma20 > ma60:
        regime_score += 18
    elif ma5 > ma20:
        regime_score += 8
    elif ma5 < ma20 < ma60:
        regime_score -= 20
    elif ma5 < ma20:
        regime_score -= 10
    
    # 2. 近期涨跌（±15分）
    if chg_5d > 3:
        regime_score += 12
    elif chg_5d > 1:
        regime_score += 6
    elif chg_5d < -3:
        regime_score -= 18
    elif chg_5d < -1:
        regime_score -= 8
    
    # 3. 成交量配合（±10分）
    if volume_trend == "放量" and chg_5d > 0:
        regime_score += 8  # 放量上涨
    elif volume_trend == "缩量" and chg_5d > 0:
        regime_score += 2  # 缩量上涨（弱）
    elif volume_trend == "放量" and chg_5d < 0:
        regime_score -= 12  # 放量下跌（危险）
    elif volume_trend == "缩量" and chg_5d < 0:
        regime_score -= 5  # 缩量下跌
    
    # 4. 今日涨跌幅（±10分）
    if sh_change_pct > 1.5:
        regime_score += 8
    elif sh_change_pct > 0.5:
        regime_score += 4
    elif sh_change_pct < -2.0:
        regime_score -= 15  # 大跌日重罚
    elif sh_change_pct < -1.0:
        regime_score -= 8
    
    # 5. 价格在MA20上/下（±5分）
    if last_close > ma20 * 1.02:
        regime_score += 4
    elif last_close < ma20 * 0.98:
        regime_score -= 5
    
    regime_score = max(0, min(100, regime_score))
    
    # ═══════════════════════════════════
    # 环境分级
    # ═══════════════════════════════════
    if regime_score >= 70:
        regime = "强势"
        position_limit = 0.8
        score_threshold = 60
        advice = "大盘强势，可积极操作，适当放大仓位"
        description = f"上证{last_close:.0f}点，均线多头排列，成交量放大，市场情绪积极"
    elif regime_score >= 50:
        regime = "震荡"
        position_limit = 0.6
        score_threshold = 62
        advice = "大盘震荡，精选个股，只推荐优质标的，控制仓位在60%以内"
        description = f"上证{last_close:.0f}点，方向不明确，严格筛选高分优质股票"
    elif regime_score >= 30:
        regime = "弱势"
        position_limit = 0.35
        score_threshold = 68
        advice = "大盘偏弱，收紧选股条件，降低仓位，只做最强个股"
        description = f"上证{last_close:.0f}点，均线偏空，量能不足，谨慎参与"
    else:
        regime = "暴跌"
        position_limit = 0.1
        score_threshold = 75
        advice = "大盘暴跌，停止推荐新股票，建议空仓观望"
        description = f"上证{last_close:.0f}点大幅下跌，系统性风险高，建议观望等待企稳"
    
    # 暴跌日特殊处理：单日跌超2%直接判为暴跌
    if sh_change_pct <= -2.0:
        regime = "暴跌"
        position_limit = 0.1
        score_threshold = 75
        advice = "今日大盘暴跌，停止买入，检查持仓止损"
        description = f"上证今日跌{abs(sh_change_pct):.1f}%，系统性风险释放中，不要抄底"
    
    return {
        "regime": regime,
        "regime_score": round(regime_score, 1),
        "sh_change_pct": sh_change_pct,
        "sh_price": round(last_close, 2),
        "ma5_vs_ma20": ma5_vs_ma20,
        "ma20_vs_ma60": ma20_vs_ma60,
        "volume_trend": volume_trend,
        "advance_decline": advance_decline,
        "description": description,
        "position_limit": position_limit,
        "score_threshold": score_threshold,
        "advice": advice,
    }
