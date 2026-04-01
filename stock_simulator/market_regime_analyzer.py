"""
大盘环境判断模块 v1.0
从专业交易员视角判断当前市场环境，指导选股策略和仓位管理

核心逻辑：
不看大盘做选股，等于闭眼开车。
大盘暴跌时再好的技术形态也会被拖下水。

环境分级：
- 牛市(强势): MA5 > MA20 > MA60，近期放量上涨 → 正常选股，放大仓位
- 震荡(中性): 均线交织，涨跌互现 → 正常选股，标准仓位
- 弱势(偏空): MA5 < MA20，成交量萎缩 → 收紧筛选，降低仓位上限
- 暴跌(危险): 单日跌幅>2%或连续3日大跌 → 停止推荐，建议观望

输入数据来源：
1. 上证指数(000001.SH)历史日线
2. 沪深两市涨跌家数比
3. 市场成交量趋势
"""

import logging
import time as _time
from typing import Dict, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── 缓存 ───
_market_cache = {}
_CACHE_TTL = 1800  # 30分钟（盘中每30分钟更新）

# 全局 Tushare 引用
_ts = None

def set_tushare(ts_instance):
    """设置 Tushare 实例"""
    global _ts
    _ts = ts_instance


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
    
    logger.info(f"[大盘环境] {result['regime']} | 上证 {result['sh_change_pct']:+.2f}% | 建议: {result['advice']}")
    return result


def _calculate_regime() -> Dict:
    """计算大盘环境（内部函数）"""
    
    # 默认返回（数据不可用时）
    default = {
        "regime": "震荡",
        "regime_score": 50.0,
        "sh_change_pct": 0,
        "sh_price": 3000,
        "ma5_vs_ma20": 0,
        "ma20_vs_ma60": 0,
        "volume_trend": "正常",
        "advance_decline": "分化",
        "description": "无法获取大盘数据，按中性环境处理",
        "position_limit": 0.6,
        "score_threshold": 50,
        "advice": "数据获取中，建议谨慎操作"
    }
    
    if not _ts:
        return default
    
    try:
        # 获取上证指数近90天数据
        pro = _ts.pro_api()
        from datetime import timedelta
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=120)).strftime('%Y%m%d')
        
        df = pro.daily(ts_code='000001.SH', start_date=start_date, end_date=end_date)
        if df is None or df.empty or len(df) < 30:
            return default
        
        df = df.sort_values('trade_date')
        closes = df['close'].astype(float).tolist()
        volumes = df['vol'].astype(float).tolist()
        
        if len(closes) < 30:
            return default
        
        # ── 核心指标计算 ──
        last_close = closes[-1]
        prev_close = closes[-2] if len(closes) >= 2 else last_close
        sh_change_pct = round((last_close - prev_close) / prev_close * 100, 2)
        
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
        # 使用沪深300成分股近似判断
        advance_decline = "分化"
        try:
            # 取近2天数据计算涨跌
            if len(closes) >= 2:
                day_chg = (closes[-1] - closes[-2]) / closes[-2] * 100
                if day_chg > 1.0:
                    advance_decline = "普涨"
                elif day_chg < -1.0:
                    advance_decline = "普跌"
        except:
            pass
        
        # ═══════════════════════════════════
        # 综合评分（0-100）
        # ═══════════════════════════════════
        regime_score = 50.0  # 基准分
        
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
            score_threshold = 48
            advice = "大盘强势，可积极操作，适当放大仓位"
            description = f"上证{last_close:.0f}点，均线多头排列，成交量放大，市场情绪积极"
        elif regime_score >= 50:
            regime = "震荡"
            position_limit = 0.6
            score_threshold = 52
            advice = "大盘震荡，精选个股，控制仓位在60%以内"
            description = f"上证{last_close:.0f}点，方向不明确，建议精选优质标的"
        elif regime_score >= 30:
            regime = "弱势"
            position_limit = 0.35
            score_threshold = 58
            advice = "大盘偏弱，收紧选股条件，降低仓位，只做最强个股"
            description = f"上证{last_close:.0f}点，均线偏空，量能不足，谨慎参与"
        else:
            regime = "暴跌"
            position_limit = 0.1
            score_threshold = 70
            advice = "大盘暴跌，停止推荐新股票，建议空仓观望"
            description = f"上证{last_close:.0f}点大幅下跌，系统性风险高，建议观望等待企稳"
        
        # 暴跌日特殊处理：单日跌超2%直接判为暴跌
        if sh_change_pct <= -2.0:
            regime = "暴跌"
            position_limit = 0.1
            score_threshold = 70
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
        
    except Exception as e:
        logger.error(f"[大盘环境] 分析失败: {e}")
        return default


def get_regime_adjustment() -> Tuple[float, int, str]:
    """
    获取环境调整参数（供选股引擎调用）
    
    返回:
        (position_limit, score_threshold, regime_label)
    """
    regime = analyze_market_regime()
    return (
        regime["position_limit"],
        regime["score_threshold"],
        regime["regime"]
    )
