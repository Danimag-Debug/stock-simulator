"""
专业技术分析模块 v1.0
从专业交易员视角实现多维度技术指标体系

核心指标体系：
1. 趋势类: MA均线系统（5/10/20/60日）、EMA、趋势线、布林带
2. 动量类: MACD、RSI、KDJ、威廉指标（WR）、随机振荡器
3. 波动类: ATR（真实波幅）、布林带宽度、标准差
4. 成交量类: OBV（能量潮）、VWAP（成交量加权均价）、量价背离
5. 形态识别: 双底、头肩底、突破、缩量回调等

评分哲学（来自专业交易员视角）：
- 趋势为王：首要判断当前趋势方向
- 确认强弱：量价配合才是真实信号
- 动量优先：动量因子对短中期涨跌预测力强
- 多时间框架：短期+中期趋势共振才加大权重
"""

import math
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────
# 基础技术指标计算函数
# ─────────────────────────────────────────────

def calc_ema(prices: List[float], period: int) -> List[float]:
    """指数移动平均线"""
    k = 2 / (period + 1)
    result = [prices[0]]
    for i in range(1, len(prices)):
        result.append(prices[i] * k + result[-1] * (1 - k))
    return result


def calc_ma(prices: List[float], period: int) -> List[Optional[float]]:
    """简单移动平均"""
    result = [None] * len(prices)
    for i in range(len(prices)):
        if i >= period - 1:
            result[i] = sum(prices[i - period + 1:i + 1]) / period
    return result


def calc_macd(data: List[Dict]) -> List[Dict]:
    """
    MACD指标（标准参数 12/26/9）
    添加: dif, dea, macd_bar（柱状）, macd_cross（金叉/死叉信号）
    """
    closes = [d["close"] for d in data]
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    dea = calc_ema(dif, 9)
    macd_bar = [(dif[i] - dea[i]) * 2 for i in range(len(dif))]

    for i in range(len(data)):
        data[i]["dif"] = round(dif[i], 4)
        data[i]["dea"] = round(dea[i], 4)
        data[i]["macd"] = round(macd_bar[i], 4)
        # 金叉/死叉信号
        if i > 0:
            if dif[i - 1] <= dea[i - 1] and dif[i] > dea[i]:
                data[i]["macd_cross"] = "golden"   # 金叉
            elif dif[i - 1] >= dea[i - 1] and dif[i] < dea[i]:
                data[i]["macd_cross"] = "dead"     # 死叉
            else:
                data[i]["macd_cross"] = None
        else:
            data[i]["macd_cross"] = None
    return data


def calc_rsi(data: List[Dict], period: int = 14) -> List[Dict]:
    """RSI相对强弱指标"""
    closes = [d["close"] for d in data]
    delta = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    delta = [0] + delta

    for i in range(len(data)):
        if i < period:
            data[i]["rsi"] = 50.0
        else:
            gains = [max(delta[j], 0) for j in range(i - period + 1, i + 1)]
            losses = [abs(min(delta[j], 0)) for j in range(i - period + 1, i + 1)]
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period if sum(losses) > 0 else 1e-9
            rs = avg_gain / avg_loss
            data[i]["rsi"] = round(100 - 100 / (1 + rs), 1)
    return data


def calc_kdj(data: List[Dict], n: int = 9, m1: int = 3, m2: int = 3) -> List[Dict]:
    """
    KDJ随机振荡器（A股常用参数9/3/3）
    K：快速随机指标，D：K的移动平均，J：超买超卖信号
    J > 100 超买，J < 0 超卖
    """
    length = len(data)
    
    # RSV：原始随机值
    rsv = []
    for i in range(length):
        start = max(0, i - n + 1)
        highs = [data[j]["high"] for j in range(start, i + 1)]
        lows = [data[j]["low"] for j in range(start, i + 1)]
        hn = max(highs)
        ln = min(lows)
        c = data[i]["close"]
        if hn == ln:
            rsv.append(50.0)
        else:
            rsv.append((c - ln) / (hn - ln) * 100)
    
    # K = 2/3 * K_prev + 1/3 * RSV
    k_val = [50.0]
    for i in range(1, length):
        k_val.append(k_val[-1] * (1 - 1/m1) + rsv[i] * (1/m1))
    
    # D = 2/3 * D_prev + 1/3 * K
    d_val = [50.0]
    for i in range(1, length):
        d_val.append(d_val[-1] * (1 - 1/m2) + k_val[i] * (1/m2))
    
    for i in range(length):
        j = 3 * k_val[i] - 2 * d_val[i]
        data[i]["k"] = round(k_val[i], 1)
        data[i]["d"] = round(d_val[i], 1)
        data[i]["j"] = round(j, 1)
    
    return data


def calc_bollinger(data: List[Dict], period: int = 20, std_mult: float = 2.0) -> List[Dict]:
    """
    布林带（Bollinger Bands）
    上轨/中轨/下轨 + 带宽（衡量波动性）
    价格跌破下轨=超跌信号，突破上轨=强势信号
    带宽收窄后扩大 = 方向性突破信号
    """
    closes = [d["close"] for d in data]
    
    for i in range(len(data)):
        if i < period - 1:
            data[i]["boll_mid"] = None
            data[i]["boll_up"] = None
            data[i]["boll_dn"] = None
            data[i]["boll_width"] = None
        else:
            window = closes[i - period + 1:i + 1]
            mid = sum(window) / period
            std = math.sqrt(sum((x - mid) ** 2 for x in window) / period)
            up = mid + std_mult * std
            dn = mid - std_mult * std
            width = (up - dn) / mid * 100  # 带宽百分比
            data[i]["boll_mid"] = round(mid, 3)
            data[i]["boll_up"] = round(up, 3)
            data[i]["boll_dn"] = round(dn, 3)
            data[i]["boll_width"] = round(width, 2)
    
    return data


def calc_williams_r(data: List[Dict], period: int = 14) -> List[Dict]:
    """
    威廉指标（WR）
    范围 -100 到 0
    WR > -20 超买，WR < -80 超卖
    """
    for i in range(len(data)):
        if i < period - 1:
            data[i]["wr"] = -50.0
        else:
            highs = [data[j]["high"] for j in range(i - period + 1, i + 1)]
            lows = [data[j]["low"] for j in range(i - period + 1, i + 1)]
            highest = max(highs)
            lowest = min(lows)
            c = data[i]["close"]
            if highest == lowest:
                data[i]["wr"] = -50.0
            else:
                wr = (highest - c) / (highest - lowest) * (-100)
                data[i]["wr"] = round(wr, 1)
    return data


def calc_atr(data: List[Dict], period: int = 14) -> List[Dict]:
    """
    ATR真实波幅（衡量波动性，用于动态止损）
    ATR大 = 波动大 = 止损位应更宽
    """
    for i in range(len(data)):
        if i == 0:
            data[i]["tr"] = data[i]["high"] - data[i]["low"]
            data[i]["atr"] = data[i]["tr"]
        else:
            high = data[i]["high"]
            low = data[i]["low"]
            prev_close = data[i - 1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            data[i]["tr"] = round(tr, 3)
    
    # ATR: 指数移动平均
    for i in range(len(data)):
        if i < period:
            data[i]["atr"] = sum(d["tr"] for d in data[:i+1]) / (i + 1)
        else:
            data[i]["atr"] = data[i-1]["atr"] * (period - 1) / period + data[i]["tr"] / period
        data[i]["atr"] = round(data[i]["atr"], 3)
    
    return data


def calc_obv(data: List[Dict]) -> List[Dict]:
    """
    OBV能量潮（On Balance Volume）
    量价关系判断：OBV持续上升=主力积累，OBV与价格背离=趋势反转信号
    """
    if not data:
        return data
    
    data[0]["obv"] = data[0]["volume"]
    
    for i in range(1, len(data)):
        if data[i]["close"] > data[i-1]["close"]:
            data[i]["obv"] = data[i-1]["obv"] + data[i]["volume"]
        elif data[i]["close"] < data[i-1]["close"]:
            data[i]["obv"] = data[i-1]["obv"] - data[i]["volume"]
        else:
            data[i]["obv"] = data[i-1]["obv"]
    
    return data


def calc_vol_ratio(data: List[Dict], period: int = 10) -> List[Dict]:
    """量比（当前成交量相对于过去N日均量的比例）"""
    for i in range(len(data)):
        if i >= period - 1:
            vol_avg = sum(d["volume"] for d in data[i - period + 1:i + 1]) / period
            data[i]["vol_ratio"] = round(data[i]["volume"] / vol_avg, 2) if vol_avg > 0 else 1.0
        else:
            data[i]["vol_ratio"] = 1.0
    return data


def calc_vwap(data: List[Dict]) -> List[Dict]:
    """
    VWAP成交量加权平均价（专业机构参考的基准价格）
    价格高于VWAP=多方强势，低于VWAP=空方强势
    """
    cumulative_pv = 0
    cumulative_vol = 0
    for d in data:
        typical_price = (d["high"] + d["low"] + d["close"]) / 3
        cumulative_pv += typical_price * d["volume"]
        cumulative_vol += d["volume"]
        d["vwap"] = round(cumulative_pv / cumulative_vol, 3) if cumulative_vol > 0 else d["close"]
    return data


def calc_momentum(data: List[Dict], period: int = 10) -> List[Dict]:
    """
    动量因子（Momentum）
    过去N日的价格变化率，动量因子是量化选股最有效的因子之一
    """
    closes = [d["close"] for d in data]
    for i in range(len(data)):
        if i >= period:
            mom = (closes[i] - closes[i - period]) / closes[i - period] * 100
            data[i]["momentum"] = round(mom, 2)
        else:
            data[i]["momentum"] = 0.0
    return data


def calc_all_indicators(data: List[Dict]) -> List[Dict]:
    """
    一次性计算所有技术指标
    """
    if not data or len(data) < 2:
        return data
    
    data = calc_macd(data)
    data = calc_rsi(data)
    data = calc_kdj(data)
    data = calc_bollinger(data)
    data = calc_williams_r(data)
    data = calc_atr(data)
    data = calc_obv(data)
    data = calc_vol_ratio(data)
    data = calc_vwap(data)
    data = calc_momentum(data)
    
    # MA均线体系
    closes = [d["close"] for d in data]
    for period in [5, 10, 20, 60]:
        ma_vals = calc_ma(closes, period)
        for i in range(len(data)):
            data[i][f"ma{period}"] = round(ma_vals[i], 3) if ma_vals[i] else None
    
    return data


# ─────────────────────────────────────────────
# 专业K线形态识别
# ─────────────────────────────────────────────

def detect_candlestick_patterns(data: List[Dict]) -> List[str]:
    """
    识别经典K线形态（基于最近3-5根K线）
    返回识别到的形态列表
    """
    patterns = []
    n = len(data)
    if n < 5:
        return patterns
    
    last = data[-1]
    prev = data[-2]
    prev2 = data[-3] if n >= 3 else None
    prev3 = data[-4] if n >= 4 else None
    prev4 = data[-5] if n >= 5 else None
    
    close = last["close"]
    open_ = last["open"]
    high = last["high"]
    low = last["low"]
    
    # 实体大小
    body = abs(close - open_)
    upper_shadow = high - max(close, open_)
    lower_shadow = min(close, open_) - low
    candle_range = high - low if high > low else 0.001
    
    body_pct = body / candle_range  # 实体占总范围比例
    
    # ── 单根K线形态 ──
    # 大阳线（强势看涨）
    if close > open_ and body_pct > 0.7 and body / close > 0.03:
        patterns.append("大阳线(强势)")
    
    # 十字星（变盘信号）
    if body_pct < 0.1 and candle_range > 0:
        if lower_shadow > 2 * body:
            patterns.append("墓碑十字(顶部风险)")
        elif upper_shadow > 2 * body:
            patterns.append("蜻蜓十字(底部支撑)")
        else:
            patterns.append("十字星(变盘信号)")
    
    # 锤子线（底部反转信号）
    if (lower_shadow > 2 * body and upper_shadow < 0.3 * body and 
            body_pct < 0.4 and prev and prev["close"] < prev["open"]):
        patterns.append("锤子线(底部反转信号)")
    
    # 射击之星（顶部反转信号）
    if (upper_shadow > 2 * body and lower_shadow < 0.3 * body and 
            body_pct < 0.4 and prev and prev["close"] > prev["open"]):
        patterns.append("射击之星(顶部风险)")
    
    # ── 双根K线形态 ──
    if prev:
        prev_body = abs(prev["close"] - prev["open"])
        
        # 吞没形态
        if (prev["close"] < prev["open"] and close > open_ and 
                open_ <= prev["close"] and close >= prev["open"]):
            patterns.append("看涨吞没(强烈买入信号)")
        
        if (prev["close"] > prev["open"] and close < open_ and 
                open_ >= prev["close"] and close <= prev["open"]):
            patterns.append("看跌吞没(卖出信号)")
    
    # ── 三根K线形态 ──
    if prev2:
        # 晨星（底部三根）
        prev2_bearish = prev2["close"] < prev2["open"]
        prev_small = abs(prev["close"] - prev["open"]) < abs(prev2["close"] - prev2["open"]) * 0.3
        last_bullish = close > open_
        
        if (prev2_bearish and prev_small and last_bullish and 
                close > (prev2["open"] + prev2["close"]) / 2):
            patterns.append("晨星形态(底部强烈反转)")
        
        # 三根阳线
        if (close > open_ and prev["close"] > prev["open"] and prev2["close"] > prev2["open"] and
                close > prev["close"] > prev2["close"]):
            patterns.append("三连阳(强势多头)")
    
    return patterns


def detect_trend_signals(data: List[Dict]) -> List[str]:
    """
    识别中期趋势信号（基于均线和MACD）
    """
    signals = []
    if len(data) < 30:
        return signals
    
    last = data[-1]
    prev = data[-2]
    
    close = last["close"]
    
    # ── 均线多空排列 ──
    ma5 = last.get("ma5")
    ma10 = last.get("ma10")
    ma20 = last.get("ma20")
    ma60 = last.get("ma60")
    
    if all(v is not None for v in [ma5, ma10, ma20, ma60]):
        if ma5 > ma10 > ma20 > ma60:
            signals.append("四线多头排列(强势上涨趋势)")
        elif ma5 > ma10 > ma20:
            signals.append("均线多头排列(上升趋势)")
        elif ma5 < ma10 < ma20 < ma60:
            signals.append("均线空头排列(下降趋势)")
        elif ma5 < ma20:
            signals.append("短期均线下方(注意风险)")
    
    # 价格与均线关系
    if ma20 and close > ma20 * 1.05:
        signals.append(f"远超MA20(+{(close/ma20-1)*100:.1f}%, 可能超涨)")
    elif ma20 and close > ma20:
        signals.append(f"站上MA20({(close/ma20-1)*100:.1f}%)")
    elif ma20 and close < ma20 * 0.95:
        signals.append(f"大幅跌破MA20(-{(1-close/ma20)*100:.1f}%)")
    
    # ── MACD信号 ──
    if last.get("macd_cross") == "golden":
        dif = last.get("dif", 0)
        if dif and dif > 0:
            signals.append("MACD零轴上方金叉(最强信号)")
        else:
            signals.append("MACD金叉(看多)")
    elif last.get("macd_cross") == "dead":
        signals.append("MACD死叉(看空)")
    elif last.get("dif", 0) > 0 and last.get("macd", 0) > 0:
        signals.append("MACD双线正值区(多头动能)")
    
    # MACD背离
    if len(data) >= 20:
        recent = data[-20:]
        # 找最近价格高点和MACD高点
        price_highs = [i for i in range(1, len(recent)-1) 
                       if recent[i]["close"] > recent[i-1]["close"] and 
                       recent[i]["close"] > recent[i+1]["close"]]
        if len(price_highs) >= 2:
            h1, h2 = price_highs[-2], price_highs[-1]
            if (recent[h2]["close"] > recent[h1]["close"] and
                recent[h2].get("macd", 0) < recent[h1].get("macd", 0)):
                signals.append("MACD顶背离(谨慎!)")
    
    # ── 布林带信号 ──
    boll_up = last.get("boll_up")
    boll_dn = last.get("boll_dn")
    boll_mid = last.get("boll_mid")
    boll_width = last.get("boll_width")
    
    if boll_up and boll_dn and boll_mid:
        if close > boll_up:
            signals.append(f"突破布林上轨(强势, 注意超买)")
        elif close < boll_dn:
            signals.append(f"跌破布林下轨(超跌, 关注反弹)")
        elif close > boll_mid and prev.get("boll_mid") and prev["close"] < prev["boll_mid"]:
            signals.append("突破布林中轨(多头信号)")
    
    if boll_width and boll_width < 5:
        signals.append("布林带收窄(蓄势待发)")
    
    return signals


def detect_volume_price_signals(data: List[Dict]) -> List[str]:
    """
    量价关系分析（成交量是价格的先行指标）
    """
    signals = []
    if len(data) < 10:
        return signals
    
    last = data[-1]
    prev = data[-2]
    recent5 = data[-5:]
    recent10 = data[-10:]
    
    close = last["close"]
    vol = last["volume"]
    vol_ratio = last.get("vol_ratio", 1.0)
    obv = last.get("obv")
    vwap = last.get("vwap")
    
    # ── 量比信号 ──
    if vol_ratio >= 3.0:
        if close > prev["close"]:
            signals.append(f"大幅放量上涨({vol_ratio:.1f}x, 主力进场)")
        else:
            signals.append(f"大幅放量下跌({vol_ratio:.1f}x, 注意出货)")
    elif vol_ratio >= 1.8:
        if close > prev["close"]:
            signals.append(f"温和放量上涨({vol_ratio:.1f}x)")
    elif vol_ratio <= 0.4:
        signals.append(f"成交量极度萎缩({vol_ratio:.1f}x, 观望)")
    elif vol_ratio <= 0.7 and close > prev["close"]:
        signals.append(f"缩量上涨({vol_ratio:.1f}x, 可能无力)")
    
    # ── OBV信号（量价同向验证）──
    if obv is not None and len(data) >= 10:
        obv_start = data[-10].get("obv")
        price_start = data[-10]["close"]
        if obv_start is not None:
            obv_change = (obv - obv_start) / abs(obv_start) * 100 if obv_start != 0 else 0
            price_change = (close - price_start) / price_start * 100
            
            if price_change > 3 and obv_change > 5:
                signals.append("OBV量价齐升(主力积累)")
            elif price_change > 2 and obv_change < -5:
                signals.append("OBV量价背离(谨慎, 主力撤退)")
    
    # ── VWAP信号 ──
    if vwap:
        deviation = (close - vwap) / vwap * 100
        if deviation > 3:
            signals.append(f"价格高于VWAP+{deviation:.1f}%(多方强势)")
        elif deviation < -3:
            signals.append(f"价格低于VWAP{deviation:.1f}%(空方强势)")
    
    return signals


def detect_momentum_signals(data: List[Dict]) -> List[str]:
    """
    动量指标信号（KDJ、WR、RSI综合）
    """
    signals = []
    if len(data) < 14:
        return signals
    
    last = data[-1]
    prev = data[-2]
    
    rsi = last.get("rsi", 50)
    k = last.get("k", 50)
    d = last.get("d", 50)
    j = last.get("j", 50)
    wr = last.get("wr", -50)
    momentum = last.get("momentum", 0)
    
    prev_k = prev.get("k", 50)
    prev_d = prev.get("d", 50)
    
    # ── RSI信号 ──
    if rsi >= 80:
        signals.append(f"RSI={rsi:.0f}严重超买(强势但高风险)")
    elif rsi >= 70:
        signals.append(f"RSI={rsi:.0f}超买区(谨慎追高)")
    elif 45 <= rsi <= 60:
        signals.append(f"RSI={rsi:.0f}健康区间(中性偏多)")
    elif 30 < rsi < 45:
        signals.append(f"RSI={rsi:.0f}弱势区(观察)")
    elif rsi <= 30:
        signals.append(f"RSI={rsi:.0f}超卖区(反弹机会)")
    elif rsi <= 20:
        signals.append(f"RSI={rsi:.0f}极度超卖(强烈反弹信号)")
    
    # ── KDJ信号 ──
    if j >= 100:
        signals.append(f"KDJ-J超买({j:.0f}, 短期回调风险)")
    elif j <= 0:
        signals.append(f"KDJ-J超卖({j:.0f}, 短期反弹机会)")
    
    # KDJ金叉/死叉
    if prev_k <= prev_d and k > d and k < 80:
        signals.append(f"KDJ金叉({k:.0f}, 看多)")
    elif prev_k >= prev_d and k < d and k > 20:
        signals.append(f"KDJ死叉({k:.0f}, 看空)")
    
    # ── 威廉指标 ──
    if wr >= -20:
        signals.append(f"WR={wr:.0f}超买(追高风险)")
    elif wr <= -80:
        signals.append(f"WR={wr:.0f}超卖(低吸机会)")
    
    # ── 动量因子 ──
    if momentum >= 15:
        signals.append(f"10日动量+{momentum:.1f}%(强势上涨趋势)")
    elif momentum >= 5:
        signals.append(f"10日动量+{momentum:.1f}%(上涨趋势)")
    elif momentum <= -10:
        signals.append(f"10日动量{momentum:.1f}%(下跌趋势)")
    
    return signals


# ─────────────────────────────────────────────
# 主评分函数（专业版）
# ─────────────────────────────────────────────

def score_technical_professional(
    data: List[Dict],
    current_price: float,
    change_pct: float,
    amount: float
) -> Tuple[int, List[str], Dict]:
    """
    专业技术面综合评分（0-40分）
    
    评分框架（来自专业交易员视角）：
    ① 趋势判断（0-15分）: 均线系统 + MACD + 趋势形态
    ② 动量强弱（0-10分）: RSI + KDJ + WR + 动量因子
    ③ 量价关系（0-10分）: OBV + 量比 + VWAP + 量价背离
    ④ 波动性评估（0-5分）: 布林带位置 + ATR分析
    
    返回: (总分, 信号列表, 详细指标字典)
    """
    
    score = 0
    signals = []
    
    if not data or len(data) < 20:
        # 数据不足时用实时行情评分
        return _score_technical_simple(current_price, change_pct, amount)
    
    # 计算所有指标
    data = calc_all_indicators(data)
    last = data[-1]
    prev = data[-2]
    
    # 提取关键指标
    rsi = last.get("rsi", 50)
    k = last.get("k", 50)
    d = last.get("d", 50)
    j = last.get("j", 50)
    wr = last.get("wr", -50)
    momentum = last.get("momentum", 0)
    macd_val = last.get("macd", 0)
    dif = last.get("dif", 0)
    dea = last.get("dea", 0)
    vol_ratio = last.get("vol_ratio", 1.0)
    obv = last.get("obv")
    vwap = last.get("vwap")
    atr = last.get("atr", 0)
    boll_up = last.get("boll_up")
    boll_dn = last.get("boll_dn")
    boll_mid = last.get("boll_mid")
    boll_width = last.get("boll_width", 10)
    ma5 = last.get("ma5")
    ma10 = last.get("ma10")
    ma20 = last.get("ma20")
    ma60 = last.get("ma60")
    
    # ═══════════════════════════════════
    # ① 趋势判断（0-15分）
    # ═══════════════════════════════════
    trend_score = 0
    trend_signals = []
    
    # 均线多空排列（最重要的趋势判断）
    if all(v is not None for v in [ma5, ma10, ma20, ma60]):
        if ma5 > ma10 > ma20 > ma60:
            trend_score += 8
            trend_signals.append("四线多头排列")
        elif ma5 > ma10 > ma20:
            trend_score += 6
            trend_signals.append("均线多头排列")
        elif ma5 > ma20:
            trend_score += 4
            trend_signals.append("短线突破MA20")
        elif ma5 < ma10 < ma20:
            trend_score -= 2
            trend_signals.append("均线空头排列")
    elif all(v is not None for v in [ma5, ma10, ma20]):
        if ma5 > ma10 > ma20:
            trend_score += 6
            trend_signals.append("均线多头排列")
        elif ma5 > ma20:
            trend_score += 3
        elif ma5 < ma10 < ma20:
            trend_score -= 2
    
    # MACD信号
    if last.get("macd_cross") == "golden":
        if dif and dif > 0:
            trend_score += 7
            trend_signals.append("MACD零轴上金叉")
        else:
            trend_score += 5
            trend_signals.append("MACD金叉")
    elif macd_val > 0 and dif > 0:
        trend_score += 3
        trend_signals.append("MACD多头区")
    elif last.get("macd_cross") == "dead":
        trend_score -= 3
        trend_signals.append("MACD死叉")
    elif macd_val < 0 and dif < 0:
        trend_score -= 1
    
    # MACD柱状变化（动能加速/减速）
    prev_macd = prev.get("macd", 0)
    if macd_val > 0 and macd_val > prev_macd:
        trend_score += 2
        trend_signals.append("MACD动能加速")
    elif macd_val > 0 and macd_val < prev_macd and macd_val < 0.02:
        trend_score -= 1
        trend_signals.append("MACD动能衰减")
    
    # K线形态
    patterns = detect_candlestick_patterns(data)
    for p in patterns:
        if "反转" in p or "看涨" in p or "三连阳" in p or "晨星" in p:
            trend_score += 2
            trend_signals.append(p)
        elif "风险" in p or "看跌" in p or "背离" in p:
            trend_score -= 2
            trend_signals.append(p)
        else:
            trend_signals.append(p)
    
    trend_score = max(0, min(trend_score, 15))
    score += trend_score
    signals.extend(trend_signals[:3])
    
    # ═══════════════════════════════════
    # ② 动量强弱（0-10分）
    # ═══════════════════════════════════
    momentum_score = 0
    momentum_signals = []
    
    # RSI动量（最权威的动量指标）
    if 50 <= rsi <= 65:
        momentum_score += 4
        momentum_signals.append(f"RSI={rsi:.0f}强势健康")
    elif 40 <= rsi < 50:
        momentum_score += 2
        momentum_signals.append(f"RSI={rsi:.0f}中性")
    elif 65 < rsi <= 75:
        momentum_score += 3
        momentum_signals.append(f"RSI={rsi:.0f}强势偏高")
    elif rsi > 75:
        momentum_score += 1
        momentum_signals.append(f"RSI={rsi:.0f}超买谨慎")
    elif 30 <= rsi < 40:
        momentum_score += 3
        momentum_signals.append(f"RSI={rsi:.0f}超卖反弹区")
    elif rsi < 30:
        momentum_score += 4
        momentum_signals.append(f"RSI={rsi:.0f}极度超卖")
    else:
        momentum_score += 1
    
    # KDJ动量
    prev_k = prev.get("k", 50)
    prev_d = prev.get("d", 50)
    
    if prev_k <= prev_d and k > d and 20 <= k <= 80:
        momentum_score += 3
        momentum_signals.append(f"KDJ金叉(J={j:.0f})")
    elif j <= 20:
        momentum_score += 3
        momentum_signals.append(f"KDJ超卖(J={j:.0f})")
    elif j >= 90:
        momentum_score += 0
        momentum_signals.append(f"KDJ超买(J={j:.0f})")
    elif 40 <= k <= 60 and k > d:
        momentum_score += 2
        momentum_signals.append(f"KDJ中枢向上(K={k:.0f})")
    
    # 威廉指标
    if -80 <= wr <= -60:
        momentum_score += 2
        momentum_signals.append(f"WR={wr:.0f}超卖区")
    elif wr < -80:
        momentum_score += 3
        momentum_signals.append(f"WR={wr:.0f}极度超卖")
    
    # 10日动量因子
    if momentum >= 10:
        momentum_score += 3
        momentum_signals.append(f"10日动量+{momentum:.1f}%")
    elif momentum >= 5:
        momentum_score += 2
        momentum_signals.append(f"动量向上+{momentum:.1f}%")
    elif momentum >= 0:
        momentum_score += 1
    elif momentum <= -10:
        momentum_score -= 2
    
    momentum_score = max(0, min(momentum_score, 10))
    score += momentum_score
    signals.extend(momentum_signals[:2])
    
    # ═══════════════════════════════════
    # ③ 量价关系（0-10分）
    # ═══════════════════════════════════
    volume_score = 0
    volume_signals = []
    
    # 量比（核心量能指标）
    if 1.5 <= vol_ratio <= 3.5:
        if current_price >= prev["close"]:
            volume_score += 5
            volume_signals.append(f"温和放量上涨({vol_ratio:.1f}x)")
        else:
            volume_score += 1
            volume_signals.append(f"放量下跌({vol_ratio:.1f}x,注意)")
    elif vol_ratio > 3.5:
        if current_price >= prev["close"]:
            volume_score += 4
            volume_signals.append(f"大幅放量({vol_ratio:.1f}x)")
        else:
            volume_score -= 1
            volume_signals.append(f"放量暴跌({vol_ratio:.1f}x,危险)")
    elif vol_ratio < 0.5:
        volume_score += 0
        volume_signals.append(f"成交萎缩({vol_ratio:.1f}x)")
    elif 0.8 <= vol_ratio < 1.5 and current_price > prev["close"]:
        volume_score += 2
        volume_signals.append(f"缩量上涨({vol_ratio:.1f}x)")
    
    # OBV量价背离
    if obv and len(data) >= 10:
        obv_10_ago = data[-10].get("obv")
        if obv_10_ago and obv_10_ago != 0:
            obv_chg = (obv - obv_10_ago) / abs(obv_10_ago) * 100
            price_chg = (last["close"] - data[-10]["close"]) / data[-10]["close"] * 100
            
            if price_chg > 0 and obv_chg > 0:
                volume_score += 3
                volume_signals.append("OBV量价同向上升")
            elif price_chg > 0 and obv_chg < -5:
                volume_score -= 2
                volume_signals.append("OBV量价背离(主力撤退信号)")
    
    # VWAP关系
    if vwap and vwap > 0:
        vwap_dev = (current_price - vwap) / vwap * 100
        if 0 < vwap_dev <= 3:
            volume_score += 2
            volume_signals.append(f"价格高于VWAP+{vwap_dev:.1f}%")
        elif vwap_dev > 3:
            volume_score += 1
            volume_signals.append(f"远超VWAP(可能超涨)")
        elif vwap_dev < 0:
            volume_score += 0
    
    # 成交额绝对量
    if amount >= 3e8:        # 3亿以上
        volume_score += 2
        volume_signals.append(f"成交额充裕({amount/1e8:.1f}亿)")
    elif amount >= 1e8:
        volume_score += 1
    
    volume_score = max(0, min(volume_score, 10))
    score += volume_score
    signals.extend(volume_signals[:2])
    
    # ═══════════════════════════════════
    # ④ 波动性评估（0-5分）
    # ═══════════════════════════════════
    volatility_score = 0
    volatility_signals = []
    
    # 布林带位置
    if boll_up and boll_dn and boll_mid:
        boll_range = boll_up - boll_dn
        if boll_range > 0:
            boll_pos = (current_price - boll_dn) / boll_range
            
            if 0.35 <= boll_pos <= 0.65:
                volatility_score += 2
                volatility_signals.append("布林带中轨附近(均衡)")
            elif boll_pos < 0.2:
                volatility_score += 3
                volatility_signals.append("接近布林下轨(超跌反弹区)")
            elif boll_pos > 0.85:
                volatility_score += 1
                volatility_signals.append("接近布林上轨(注意压力)")
            elif 0.65 < boll_pos <= 0.85:
                volatility_score += 2
                volatility_signals.append("布林带上半区(偏强)")
    
    # 布林带宽度（波动性）
    if boll_width:
        if boll_width < 4:
            volatility_score += 2
            volatility_signals.append("布林带极度收窄(蓄势突破)")
        elif boll_width < 7:
            volatility_score += 1
            volatility_signals.append("布林带收窄(整理蓄势)")
    
    # ATR动态止损评估
    if atr and current_price > 0:
        atr_pct = atr / current_price * 100
        if atr_pct <= 2:
            volatility_score += 1
            volatility_signals.append(f"ATR低波动({atr_pct:.1f}%,稳健)")
        elif atr_pct >= 5:
            volatility_signals.append(f"ATR高波动({atr_pct:.1f}%,注意)")
    
    volatility_score = max(0, min(volatility_score, 5))
    score += volatility_score
    signals.extend(volatility_signals[:1])
    
    # ── 汇总关键指标 ──
    indicators = {
        "rsi": rsi,
        "k": round(k, 1),
        "d": round(d, 1),
        "j": round(j, 1),
        "wr": wr,
        "macd": round(macd_val, 4),
        "dif": round(dif, 4),
        "dea": round(dea, 4),
        "vol_ratio": vol_ratio,
        "momentum_10d": round(momentum, 2),
        "atr": atr,
        "atr_pct": round(atr / current_price * 100, 2) if atr and current_price > 0 else 0,
        "boll_position": round((current_price - boll_dn) / (boll_up - boll_dn) * 100, 1) if (boll_up and boll_dn and boll_up > boll_dn) else 50,
        "boll_width": boll_width or 0,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "vwap": vwap,
        "obv_trend": "上升" if (obv and len(data) >= 5 and obv > data[-5].get("obv", obv)) else "下降",
        "score_breakdown": {
            "趋势": trend_score,
            "动量": momentum_score,
            "量价": volume_score,
            "波动": volatility_score
        }
    }
    
    total_score = max(0, min(score, 40))
    return total_score, signals[:6], indicators


def _score_technical_simple(current_price: float, change_pct: float, amount: float) -> Tuple[int, List[str], Dict]:
    """降级方案：纯实时行情技术评分"""
    score = 0
    signals = []
    
    # 涨幅质量
    if 0.5 <= change_pct <= 3.0:
        score += 12
        signals.append(f"温和上涨({change_pct:.1f}%)")
    elif 3.0 < change_pct <= 6.0:
        score += 10
        signals.append(f"强势上涨({change_pct:.1f}%)")
    elif -1.5 <= change_pct < 0:
        score += 10
        signals.append(f"小幅回调({change_pct:.1f}%)")
    elif -4 <= change_pct < -1.5:
        score += 6
        signals.append(f"回调中({change_pct:.1f}%)")
    elif change_pct > 6:
        score += 7
        signals.append(f"大涨({change_pct:.1f}%,追高谨慎)")
    else:
        score += 4
        signals.append(f"较大跌幅({change_pct:.1f}%)")
    
    # 成交额
    if amount >= 5e8:
        score += 10
        signals.append(f"成交活跃({amount/1e8:.1f}亿)")
    elif amount >= 1e8:
        score += 7
    elif amount >= 5e7:
        score += 4
    
    # 价格区间
    if 10 <= current_price <= 200:
        score += 8
    elif 5 <= current_price < 10 or 200 < current_price <= 500:
        score += 5
    else:
        score += 3
    
    score = min(score, 40)
    return score, signals, {
        "rsi": 50, "k": 50, "d": 50, "j": 50, "wr": -50,
        "macd": 0, "vol_ratio": 1.0, "momentum_10d": 0,
        "atr_pct": 0, "boll_position": 50, "boll_width": 10,
        "score_breakdown": {"趋势": score//3, "动量": score//4, "量价": score//4, "波动": score//6}
    }


def calc_dynamic_stop_loss(data: List[Dict], current_price: float, score: int) -> Tuple[float, float, float]:
    """
    基于ATR的动态止损止盈计算
    专业交易员常用: 止损=1.5*ATR, 止盈=2.5~3*ATR
    
    返回: (买入价, 止损价, 止盈价)
    """
    buy_price = round(current_price * 1.001, 2)  # 微高于市价入场
    
    if data and len(data) >= 14:
        last = data[-1]
        atr = last.get("atr")
        
        if atr and atr > 0:
            # ATR止损：1.5倍ATR（专业方法）
            atr_stop = buy_price - 1.5 * atr
            
            # 结合评分的止盈倍数
            if score >= 75:
                take_mult = 3.0   # 高分股，追求更高收益
            elif score >= 60:
                take_mult = 2.5
            else:
                take_mult = 2.0
            
            atr_take = buy_price + take_mult * atr
            
            # 止损不超过5%（防止ATR过大）
            max_stop = buy_price * 0.95
            stop_loss = max(atr_stop, max_stop)
            
            return buy_price, round(stop_loss, 2), round(atr_take, 2)
    
    # 降级：固定比例
    if score >= 75:
        stop_pct, take_pct = 0.05, 0.20
    elif score >= 60:
        stop_pct, take_pct = 0.05, 0.15
    else:
        stop_pct, take_pct = 0.05, 0.10
    
    return buy_price, round(buy_price * (1 - stop_pct), 2), round(buy_price * (1 + take_pct), 2)
