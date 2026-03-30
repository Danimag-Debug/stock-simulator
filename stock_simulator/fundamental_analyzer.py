"""
基本面分析模块
利用 Tushare 免费接口获取股票基本面数据（市盈率、市净率、ROE等）
并进行多维度基本面评分
"""

import logging
from typing import Dict, Optional, Tuple, List

logger = logging.getLogger(__name__)

# 全局 Tushare Pro 实例（由外部传入）
_pro = None

def set_pro_api(pro_instance):
    """设置 Tushare Pro API 实例"""
    global _pro
    _pro = pro_instance


# ─── 缓存机制 ───
_fundamental_cache = {}
_CACHE_TTL = 7200  # 基本面数据 2 小时缓存

import time as _time


def _get_cached(code: str) -> Optional[Dict]:
    """获取缓存的基本面数据"""
    if code in _fundamental_cache:
        cached = _fundamental_cache[code]
        if _time.time() - cached["ts"] < _CACHE_TTL:
            return cached["data"]
    return None


def _set_cache(code: str, data: Dict):
    """缓存基本面数据"""
    _fundamental_cache[code] = {"data": data, "ts": _time.time()}


def _ts_code(code: str) -> str:
    """转换为 Tushare ts_code 格式"""
    if code.startswith("6"):
        return f"{code}.SH"
    return f"{code}.SZ"


def get_daily_basic(code: str) -> Optional[Dict]:
    """
    获取股票每日基本面指标（PE、PB、总市值、换手率等）
    使用 Tushare daily_basic 接口（低权限可用）
    """
    if not _pro:
        return None
    
    cached = _get_cached(code)
    if cached:
        return cached
    
    try:
        ts_c = _ts_code(code)
        # 获取最近 5 个交易日的数据，取最新的
        df = _pro.daily_basic(
            ts_code=ts_c,
            fields="ts_code,trade_date,close,pe,pe_ttm,pb,ps_ttm,total_mv,circ_mv,turnover_rate,turnover_rate_f,volume_ratio"
        )
        if df is not None and not df.empty:
            df = df.sort_values("trade_date", ascending=False)
            row = df.iloc[0].to_dict()
            _set_cache(code, row)
            return row
    except Exception as e:
        logger.debug(f"[fundamental] get_daily_basic {code} 失败: {e}")
    
    return None


def get_income_growth(code: str) -> Optional[Dict]:
    """
    获取利润表数据，计算同比增长率（需要一定积分，可能失败）
    失败时返回 None，不影响主流程
    """
    if not _pro:
        return None
    
    try:
        ts_c = _ts_code(code)
        # 获取最近 2 期财报
        df = _pro.income(
            ts_code=ts_c,
            fields="ts_code,ann_date,end_date,revenue,n_income,n_income_attr_p",
            limit=4
        )
        if df is None or df.empty or len(df) < 2:
            return None
        
        df = df.sort_values("end_date", ascending=False)
        latest = df.iloc[0]
        prev_year = df[df["end_date"].str[:4] == str(int(latest["end_date"][:4]) - 1)]
        
        if prev_year.empty:
            return None
        
        prev = prev_year.iloc[0]
        
        # 计算同比增长
        def yoy_growth(curr, prev):
            if prev and float(prev) != 0:
                return (float(curr) - float(prev)) / abs(float(prev)) * 100
            return None
        
        revenue_growth = yoy_growth(latest.get("revenue"), prev.get("revenue"))
        income_growth = yoy_growth(latest.get("n_income_attr_p"), prev.get("n_income_attr_p"))
        
        return {
            "revenue_growth": round(revenue_growth, 1) if revenue_growth is not None else None,
            "income_growth": round(income_growth, 1) if income_growth is not None else None,
            "latest_income": float(latest.get("n_income_attr_p", 0) or 0),
        }
    except Exception as e:
        logger.debug(f"[fundamental] get_income_growth {code} 失败: {e}")
        return None


def score_fundamental(code: str, name: str, current_price: float) -> Tuple[int, List[str]]:
    """
    基本面综合评分
    返回 (基本面评分 0-30, 理由列表)
    
    评分维度：
    - PE 市盈率合理性（0-10分）
    - PB 市净率合理性（0-5分）
    - 总市值/流通市值（0-5分）
    - 换手率（0-5分）
    - 利润增长（0-5分，需要高级接口，可选）
    """
    score = 0
    reasons = []
    
    # 获取基本面数据
    basic = get_daily_basic(code)
    
    if not basic:
        # 无法获取数据时给默认分
        reasons.append("基本面数据获取中")
        return 10, reasons
    
    # ── 1. PE 市盈率评分（0-10分）──
    pe = basic.get("pe_ttm") or basic.get("pe")
    try:
        pe = float(pe) if pe else None
        if pe and pe > 0:
            if 10 <= pe <= 25:
                score += 10
                reasons.append(f"PE合理({pe:.1f}x)")
            elif 25 < pe <= 40:
                score += 7
                reasons.append(f"PE偏高({pe:.1f}x)")
            elif 5 <= pe < 10:
                score += 8
                reasons.append(f"PE低估({pe:.1f}x)")
            elif pe < 5:
                score += 6
                reasons.append(f"PE极低({pe:.1f}x,需谨慎)")
            elif pe > 80:
                score += 2
                reasons.append(f"PE极高({pe:.1f}x,泡沫风险)")
            elif pe > 40:
                score += 4
                reasons.append(f"PE高估({pe:.1f}x)")
        elif pe and pe < 0:
            score += 0
            reasons.append(f"⚠️亏损股(PE负值)")
        else:
            score += 5  # 无数据给基础分
    except (ValueError, TypeError):
        score += 5
    
    # ── 2. PB 市净率评分（0-5分）──
    pb = basic.get("pb")
    try:
        pb = float(pb) if pb else None
        if pb and pb > 0:
            if 1 <= pb <= 3:
                score += 5
                reasons.append(f"PB合理({pb:.1f}x)")
            elif pb < 1:
                score += 4
                reasons.append(f"PB破净({pb:.1f}x,资产低估)")
            elif 3 < pb <= 6:
                score += 3
                reasons.append(f"PB偏高({pb:.1f}x)")
            else:
                score += 1
                reasons.append(f"PB极高({pb:.1f}x)")
        else:
            score += 2
    except (ValueError, TypeError):
        score += 2
    
    # ── 3. 市值评估（0-5分）──
    total_mv = basic.get("total_mv")  # 单位：万元
    circ_mv = basic.get("circ_mv")
    try:
        total_mv = float(total_mv) if total_mv else None
        circ_mv = float(circ_mv) if circ_mv else None
        
        if total_mv:
            total_mv_yi = total_mv / 10000  # 转换为亿元
            
            if 50 <= total_mv_yi <= 500:
                score += 5
                reasons.append(f"市值适中({total_mv_yi:.0f}亿)")
            elif 500 < total_mv_yi <= 2000:
                score += 4
                reasons.append(f"大市值({total_mv_yi:.0f}亿)")
            elif 20 <= total_mv_yi < 50:
                score += 3
                reasons.append(f"小市值({total_mv_yi:.0f}亿)")
            elif total_mv_yi > 2000:
                score += 3
                reasons.append(f"超大市值({total_mv_yi:.0f}亿)")
            else:
                score += 2
                reasons.append(f"微盘股({total_mv_yi:.0f}亿,流动性差)")
    except (ValueError, TypeError):
        score += 2
    
    # ── 4. 换手率（0-5分）──
    turnover = basic.get("turnover_rate_f") or basic.get("turnover_rate")
    try:
        turnover = float(turnover) if turnover else None
        if turnover:
            if 1 <= turnover <= 5:
                score += 5
                reasons.append(f"换手率适中({turnover:.1f}%)")
            elif 5 < turnover <= 10:
                score += 3
                reasons.append(f"换手率较高({turnover:.1f}%)")
            elif turnover > 10:
                score += 2
                reasons.append(f"换手率异常({turnover:.1f}%,博弈加剧)")
            else:
                score += 1
                reasons.append(f"换手率低({turnover:.1f}%,活跃度不足)")
        else:
            score += 2
    except (ValueError, TypeError):
        score += 2
    
    # ── 5. 量比（如果有的话）──
    vol_ratio = basic.get("volume_ratio")
    try:
        vol_ratio = float(vol_ratio) if vol_ratio else None
        if vol_ratio and 1.5 <= vol_ratio <= 5:
            score += 5
            reasons.append(f"量比放大({vol_ratio:.1f}x)")
        elif vol_ratio and vol_ratio > 5:
            score += 3
            reasons.append(f"量比异常({vol_ratio:.1f}x)")
        elif vol_ratio:
            score += 1
    except (ValueError, TypeError):
        pass
    
    # 尝试获取利润增长（可选，可能失败）
    try:
        growth = get_income_growth(code)
        if growth:
            ig = growth.get("income_growth")
            if ig is not None:
                if ig > 30:
                    score += 5
                    reasons.append(f"净利润同比+{ig:.0f}%")
                elif ig > 10:
                    score += 3
                    reasons.append(f"净利润同比+{ig:.0f}%")
                elif ig > 0:
                    score += 1
                    reasons.append(f"净利润微增{ig:.0f}%")
                elif ig < -20:
                    score -= 3
                    reasons.append(f"⚠️净利润同比{ig:.0f}%")
    except Exception:
        pass
    
    return min(score, 30), reasons
