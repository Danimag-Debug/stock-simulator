"""
选股引擎 - 数据库版本（支持多用户）
多维度智能评分系统：技术面 + 基本面 + 新闻情报 + 行业热度
"""

import json
import os
import sys
import random
import concurrent.futures
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
try:
    import database
except ImportError:
    from . import database

# 尝试加载 Tushare
TUSHARE_AVAILABLE = False
try:
    import tushare as ts
    import os
    
    # 优先从环境变量读取 Tushare Token
    token_from_env = os.getenv("TUSHARE_TOKEN")
    
    if token_from_env and token_from_env.strip():
        ts.set_token(token_from_env)
        TUSHARE_AVAILABLE = True
        print("[INFO] Tushare 已启用（环境变量），使用真实行情数据")
    else:
        # 尝试从配置文件读取
        try:
            # 使用绝对导入路径
            import sys
            import os
            sys.path.insert(0, os.path.dirname(__file__))
            from tushare_config import TUSHARE_TOKEN
            if TUSHARE_TOKEN and TUSHARE_TOKEN != "你的Tushare Token粘贴在这里":
                ts.set_token(TUSHARE_TOKEN)
                TUSHARE_AVAILABLE = True
                print("[INFO] Tushare 已启用（配置文件），使用真实行情数据")
            else:
                print("[WARN] Tushare Token 未配置，无法获取真实行情数据")
        except ImportError as e:
            print(f"[WARN] 未找到 tushare_config.py，无法获取真实行情数据: {e}")
            print(f"[DEBUG] Current dir: {os.getcwd()}, __file__: {__file__}")
except ImportError:
    print("[WARN] 未安装 tushare，无法获取真实行情数据")

# ─── 加载辅助分析模块 ───
try:
    import news_analyzer
    import fundamental_analyzer
    if TUSHARE_AVAILABLE:
        fundamental_analyzer.set_pro_api(ts.pro_api())
    ANALYSIS_MODULES_AVAILABLE = True
    print("[INFO] 辅助分析模块加载成功（新闻+基本面）")
except Exception as _e:
    ANALYSIS_MODULES_AVAILABLE = False
    print(f"[WARN] 辅助分析模块加载失败: {_e}")

# 模拟股票池（降级用）- 包含真实参考价格
# 详细的高质量模拟股票数据（包含真实参考价格）
MOCK_STOCK_DETAILS = [
    ("600519", "贵州茅台", 1850.0),
    ("300750", "宁德时代", 210.0),
    ("601318", "中国平安", 57.8),
    ("600030", "中信证券", 24.5),
    ("300059", "东方财富", 15.2),
    ("603259", "药明康德", 45.6),
    ("000858", "五粮液", 148.0),
    ("002475", "立讯精密", 32.8),
    ("601888", "中国中免", 78.5),
    ("300760", "迈瑞医疗", 280.0),
    ("600887", "伊利股份", 28.3),
    ("000333", "美的集团", 68.9),
    ("002594", "比亚迪", 245.0),
    ("601012", "隆基绿能", 18.7),
    ("300124", "汇川技术", 65.4),
    ("600690", "海尔智家", 26.8),
    ("002271", "东方雨虹", 18.2),
    ("603986", "兆易创新", 78.9),
    ("688981", "中芯国际", 45.6),
    ("002142", "宁波银行", 22.3),
    ("000651", "格力电器", 38.7),
    ("000725", "京界面A", 4.2),
    ("600276", "恒瑞医药", 42.8),
    ("002415", "海康威视", 34.5),
    ("300142", "沃森生物", 28.9),
    ("600009", "上海机场", 36.7),
    ("002601", "龙佰集团", 19.8),
    ("300274", "阳光电源", 85.6),
    ("600036", "招商银行", 33.2),
    ("002032", "苏泊尔", 52.4),
    ("601166", "兴业银行", 16.8),
    ("600031", "三一重工", 14.5),
    ("000568", "泸州老窖", 189.0),
    ("000002", "万科A", 12.5),
    ("601398", "工商银行", 5.3),
    ("601939", "建设银行", 6.8),
    ("601288", "农业银行", 3.9),
    ("601988", "中国银行", 4.2),
    ("601628", "中国人寿", 34.8),
    ("601601", "中国太保", 26.7),
]

# 保持向后兼容
MOCK_STOCKS = [(code, name) for code, name, _ in MOCK_STOCK_DETAILS]

INITIAL_CASH = 150000.0  # 调整为15万元

# ─────────────────────────────────────────────
# 行情获取（真实 + 模拟双支持）
# ─────────────────────────────────────────────

def _build_all_market_codes() -> List[str]:
    """
    构建全市场 A 股代码列表（沪深两市全部股票）
    沪市：600000-605999, 688000-688999（科创板）
    深市：000001-004999, 300000-301000（创业板）
    """
    ranges = [
        # 沪市主板 (600xxx)
        range(600000, 606000),
        # 科创板 (688xxx)
        range(688000, 689000),
        # 深市主板 (000xxx, 001xxx, 002xxx)
        range(1, 5000),      # 000001-0004999
        range(2000, 3000),   # 002000-002999 (中小板)
        # 创业板 (300xxx)
        range(300000, 301000),
        # 深市其他主板 (001xxx)
        range(1000, 2000),
    ]
    codes = []
    for r in ranges:
        for n in r:
            codes.append(str(n).zfill(6))
    print(f"[INFO] 全市场代码池构建完成，共 {len(codes)} 只股票代码")
    return codes

def get_stock_list() -> List[Dict]:
    """
    获取全市场实时行情（强制使用真实数据）
    """
    import pandas as pd
    
    # 检查 Tushare 是否可用
    if not TUSHARE_AVAILABLE:
        print(f"[WARN] Tushare 不可用，无法获取真实行情数据。TUSHARE_AVAILABLE={TUSHARE_AVAILABLE}")
        # 尝试检查环境变量
        token_from_env = os.getenv("TUSHARE_TOKEN")
        print(f"[DEBUG] TUSHARE_TOKEN from env: {'已设置' if token_from_env else '未设置'}")
        return []  # 返回空列表而不是抛异常
    
    try:
        all_codes = _build_all_market_codes()
        print(f"[INFO] 全市场扫描启动，代码池共 {len(all_codes)} 只股票...")

        all_quotes = []
        batch_size = 80  # Tushre API 单次最大数量
        total_batches = (len(all_codes) + batch_size - 1) // batch_size
        success_batches = 0
        failed_batches = 0
        
        print(f"[INFO] 开始批量获取行情数据，共 {total_batches} 个批次...")
        
        for i in range(0, len(all_codes), batch_size):
            batch = all_codes[i:i + batch_size]
            batch_num = i // batch_size + 1
            
            try:
                df_rt = ts.get_realtime_quotes(batch)
                if df_rt is not None and not df_rt.empty:
                    # 只保留有实际价格的行
                    df_valid = df_rt[
                        df_rt['price'].apply(lambda x: str(x).strip() not in ('', '0', '0.00', 'nan'))
                    ]
                    if not df_valid.empty:
                        all_quotes.append(df_valid)
                        success_batches += 1
                        print(f"[进度] 批次 {batch_num}/{total_batches} 成功，获取 {len(df_valid)} 只股票")
                    else:
                        failed_batches += 1
                else:
                    failed_batches += 1
            except Exception as e:
                failed_batches += 1
                print(f"[WARN] 批次 {batch_num}/{total_batches} 失败: {e}")

        if not all_quotes:
            raise RuntimeError(f"全市场实时行情拉取全部失败！{success_batches} 成功/{failed_batches} 失败")
        
        df_all = pd.concat(all_quotes, ignore_index=True)
        print(f"[INFO] 获取到原始行情 {len(df_all)} 条（{success_batches}/{total_batches} 批次成功）")

        result = []
        for _, row in df_all.iterrows():
            try:
                code = str(row['code']).zfill(6)
                name = str(row['name']).strip()

                # 过滤无名、ST、退市
                if not name or 'ST' in name or '退' in name or name == 'nan':
                    continue

                price_str = str(row['price']).strip()
                pre_close_str = str(row['pre_close']).strip()
                if not price_str or not pre_close_str:
                    continue

                current_price = float(price_str)
                pre_close = float(pre_close_str)

                if current_price <= 0 or pre_close <= 0:
                    continue

                change_pct = round((current_price - pre_close) / pre_close * 100, 2)

                open_str = str(row.get('open', '0')).strip()
                high_str = str(row.get('high', '0')).strip()
                low_str = str(row.get('low', '0')).strip()
                volume_str = str(row.get('volume', '0')).strip()
                amount_str = str(row.get('amount', '0')).strip()
                volume = int(float(volume_str)) if volume_str else 0
                amount = float(amount_str) if amount_str else 0
                open_price = float(open_str) if open_str and float(open_str) > 0 else None
                high_price = float(high_str) if high_str and float(high_str) > 0 else None
                low_price = float(low_str) if low_str and float(low_str) > 0 else None

                # ── 筛选条件（针对中线策略）──
                if not (-2 <= change_pct <= 8):      # 排除异常涨跌
                    continue
                if current_price < 3 or current_price > 800:  # 价格区间
                    continue
                if amount < 5e7:                      # 成交额至少5000万
                    continue

                result.append({
                    "code": code,
                    "name": name,
                    "current_price": current_price,
                    "change_pct": change_pct,
                    "volume": volume,
                    "amount": amount,
                    "open_price": open_price,
                    "high_price": high_price,
                    "low_price": low_price,
                })
            except (ValueError, TypeError):
                continue

        # 随机打乱后排序
        random.shuffle(result)
        result.sort(key=lambda x: x["change_pct"], reverse=True)
        print(f"[INFO] 全市场筛选完成，共 {len(result)} 只候选股票")
        return result
    except Exception as e:
        print(f"[ERROR] 获取股票列表失败: {e}")
        return []

def get_stock_name_tushare(code: str) -> Optional[str]:
    """通过 Tushare 获取股票名称"""
    try:
        pro = ts.pro_api()
        ts_code = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
        df = pro.daily_basic(ts_code=ts_code, fields='ts_code,name')
        if not df.empty:
            return df.iloc[0]['name']
    except:
        pass

    # 本地映射
    for c, name, _ in MOCK_STOCK_DETAILS:
        if c == code:
            return name
    return None

def get_hist_data(code: str, days: int = 60) -> Optional[List[Dict]]:
    """获取历史日线数据（强制使用真实数据）"""
    
    if not TUSHARE_AVAILABLE:
        raise RuntimeError("Tushare 不可用，无法获取历史数据！")

    try:
        pro = ts.pro_api()
        ts_code = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime('%Y%m%d')

        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if df.empty:
            print(f"[WARN] 股票 {code} 无历史数据")
            return None

        df = df.sort_values('trade_date').tail(days)
        result = []
        for _, row in df.iterrows():
            result.append({
                "date": datetime.strptime(row['trade_date'], '%Y%m%d'),
                "open": float(row['open']),
                "close": float(row['close']),
                "high": float(row['high']),
                "low": float(row['low']),
                "volume": int(row['vol']),
                "amount": float(row['amount']) * 1000
            })
        return result
    except Exception as e:
        print(f"[ERROR] Tushare 获取 {code} 历史数据失败: {e}")
        raise RuntimeError(f"获取股票 {code} 历史数据失败: {e}")

# ─────────────────────────────────────────────
# 技术指标计算
# ─────────────────────────────────────────────

def calc_ma(data: List[Dict], windows=[5, 10, 20, 30]) -> List[Dict]:
    for w in windows:
        closes = [d["close"] for d in data]
        for i in range(len(data)):
            if i >= w - 1:
                avg = sum(closes[i - w + 1:i + 1]) / w
                data[i][f"ma{w}"] = round(avg, 3)
            else:
                data[i][f"ma{w}"] = None
    return data

def calc_macd(data: List[Dict], fast=12, slow=26, signal=9) -> List[Dict]:
    closes = [d["close"] for d in data]

    def ema(arr, period):
        k = 2 / (period + 1)
        result = [arr[0]]
        for i in range(1, len(arr)):
            result.append(arr[i] * k + result[-1] * (1 - k))
        return result

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    dea = ema(dif, signal)
    macd = [(dif[i] - dea[i]) * 2 for i in range(len(dif))]

    for i in range(len(data)):
        data[i]["dif"] = round(dif[i], 4)
        data[i]["dea"] = round(dea[i], 4)
        data[i]["macd"] = round(macd[i], 4)

    return data

def calc_rsi(data: List[Dict], period=14) -> List[Dict]:
    closes = [d["close"] for d in data]
    delta = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    delta = [0] + delta

    for i in range(len(data)):
        if i < period:
            data[i]["rsi"] = 50
        else:
            gains = [max(delta[j], 0) for j in range(i - period + 1, i + 1)]
            losses = [abs(min(delta[j], 0)) for j in range(i - period + 1, i + 1)]
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period if sum(losses) > 0 else 1e-9
            rs = avg_gain / avg_loss
            data[i]["rsi"] = round(100 - 100 / (1 + rs), 1)

    return data

def calc_vol_ratio(data: List[Dict], period=10) -> List[Dict]:
    for i in range(len(data)):
        if i >= period - 1:
            vol_avg = sum(d["volume"] for d in data[i - period + 1:i + 1]) / period
            data[i]["vol_ratio"] = round(data[i]["volume"] / vol_avg, 2)
        else:
            data[i]["vol_ratio"] = 1.0
    return data

# ─────────────────────────────────────────────
# 多维度智能选股评分系统（v3.0）
# 维度1: 技术面（量价行为）     权重 40%
# 维度2: 基本面（PE/PB/市值）   权重 25%  
# 维度3: 新闻情报（公告/情绪）  权重 20%
# 维度4: 行业热度（板块热点）   权重 15%
# ─────────────────────────────────────────────

def _score_technical(code: str, current_price: float, change_pct: float,
                     volume: int, amount: float, open_price: Optional[float],
                     high_price: Optional[float], low_price: Optional[float]) -> Tuple[int, List[str], float, float, float]:
    """
    技术面评分（0-40分）
    返回：(分数, 信号列表, rsi值, macd值, vol_ratio值)
    
    首先尝试基于历史K线的高精度分析，失败则降级到纯实时行情分析
    """
    rsi_val = 50.0
    macd_val = 0.0
    vol_ratio_val = 1.0
    signals = []
    score = 0

    # ── 尝试历史K线分析（需要Tushare Pro权限）──
    hist_score = 0
    if TUSHARE_AVAILABLE:
        try:
            hist = get_hist_data(code, days=60)
            if hist and len(hist) >= 30:
                hist = calc_ma(hist)
                hist = calc_macd(hist)
                hist = calc_rsi(hist)
                hist = calc_vol_ratio(hist)

                last = hist[-1]
                prev = hist[-2]
                rsi_val = float(last.get("rsi", 50))
                macd_val = float(last.get("macd", 0))
                vol_ratio_val = float(last.get("vol_ratio", 1))

                # 均线系统（0-15分）
                if all(last.get(f"ma{w}") for w in [5, 10, 20, 30]):
                    if last["ma5"] > last["ma10"] > last["ma20"] > last["ma30"]:
                        hist_score += 15
                        signals.append("均线多头排列")
                    elif last["ma5"] > last["ma20"]:
                        # 判断金叉
                        if prev.get("ma5") and prev["ma5"] <= prev.get("ma20", prev["ma5"]):
                            hist_score += 13
                            signals.append("MA5金叉MA20")
                        else:
                            hist_score += 8
                            signals.append("短线上方")

                # MACD（0-12分）
                dif = last.get("dif", 0)
                dea = last.get("dea", 0)
                prev_dif = prev.get("dif", 0)
                prev_dea = prev.get("dea", 0)
                if prev_dif is not None and dif is not None:
                    if prev_dif <= (prev_dea or 0) and dif > (dea or 0):
                        hist_score += 12
                        signals.append("MACD金叉")
                    elif macd_val > 0 and dif > 0:
                        hist_score += 6
                        signals.append("MACD多头区")
                    elif macd_val > 0:
                        hist_score += 3
                        signals.append("MACD柱翻红")

                # RSI（0-8分）
                if 40 <= rsi_val <= 60:
                    hist_score += 8
                    signals.append(f"RSI健康({rsi_val:.0f})")
                elif 35 <= rsi_val < 40:
                    hist_score += 6
                    signals.append(f"RSI超卖反弹区({rsi_val:.0f})")
                elif rsi_val > 75:
                    hist_score -= 5
                    signals.append(f"RSI超买风险({rsi_val:.0f})")
                elif rsi_val < 30:
                    hist_score += 4
                    signals.append(f"RSI极度超卖({rsi_val:.0f})")
                else:
                    hist_score += 3

                # 量比（0-5分）
                if 1.5 <= vol_ratio_val <= 4:
                    hist_score += 5
                    signals.append(f"温和放量({vol_ratio_val:.1f}x)")
                elif vol_ratio_val > 4:
                    hist_score += 3
                    signals.append(f"大幅放量({vol_ratio_val:.1f}x)")
                elif vol_ratio_val < 0.5:
                    hist_score -= 2
                    signals.append(f"量能萎缩({vol_ratio_val:.1f}x)")
                else:
                    hist_score += 1

                score = min(max(hist_score, 0), 40)
                return score, signals, rsi_val, macd_val, vol_ratio_val
        except Exception as _e:
            pass  # 降级到纯实时分析

    # ── 降级：基于实时行情的技术分析（0-40分）──
    # A. 涨幅质量（0-15分）
    if 0.5 <= change_pct <= 3.0:
        score += 15
        signals.append(f"温和上涨({change_pct:.1f}%)")
    elif 3.0 < change_pct <= 5.5:
        score += 12
        signals.append(f"强势上涨({change_pct:.1f}%)")
    elif -1.5 <= change_pct < 0:
        score += 10
        signals.append(f"小幅回调({change_pct:.1f}%,可建仓)")
    elif -4 <= change_pct < -1.5:
        score += 7
        signals.append(f"回调({change_pct:.1f}%)")
    elif 5.5 < change_pct <= 8:
        score += 8
        signals.append(f"大涨({change_pct:.1f}%,追高谨慎)")
    elif change_pct > 8:
        score += 3
        signals.append(f"接近涨停({change_pct:.1f}%)")
    else:
        score += 5
        signals.append(f"较大跌幅({change_pct:.1f}%)")

    # B. 日内K线形态（0-12分）
    if open_price and high_price and low_price and high_price > low_price:
        price_range = high_price - low_price
        position = (current_price - low_price) / price_range  # 0=最低，1=最高
        
        # 实体长度（volatility）
        body_pct = abs(current_price - open_price) / open_price * 100
        
        if 0.3 <= position <= 0.65 and body_pct < 3:
            score += 12
            signals.append(f"K线实体健康")
        elif position < 0.25 and change_pct < 0:
            # 下影线长，有支撑
            lower_shadow = (current_price - low_price) / current_price * 100
            if lower_shadow > 1:
                score += 10
                signals.append(f"下影线支撑")
            else:
                score += 6
        elif position > 0.8 and change_pct > 3:
            score += 5
            signals.append(f"上方阻力大")
        else:
            score += 7
            signals.append(f"K线位置({position*100:.0f}%)")

    # C. 成交量质量（0-13分）
    if amount >= 5e8:        # 5亿以上
        score += 13
        signals.append(f"成交量活跃({amount/1e8:.1f}亿)")
    elif amount >= 1e8:      # 1亿以上
        score += 10
        signals.append(f"成交量良好({amount/1e8:.1f}亿)")
    elif amount >= 5e7:      # 5000万以上
        score += 6
        signals.append(f"成交量尚可")
    else:
        score += 2
        signals.append(f"成交量偏低")

    score = min(max(score, 0), 40)
    return score, signals, rsi_val, macd_val, vol_ratio_val


def _score_fundamental_wrapper(code: str, name: str, current_price: float) -> Tuple[int, List[str]]:
    """
    基本面评分（0-25分）
    调用 fundamental_analyzer 模块，按比例缩放到 0-25
    """
    if not ANALYSIS_MODULES_AVAILABLE:
        # 无模块时按价格和代码做基础评估
        signals = []
        score = 12  # 默认中间分
        if 5 <= current_price <= 100:
            signals.append(f"价格区间合理(¥{current_price:.2f})")
        elif current_price < 5:
            signals.append(f"低价股(¥{current_price:.2f})")
            score = 8
        return score, signals

    try:
        raw_score, reasons = fundamental_analyzer.score_fundamental(code, name, current_price)
        # fundamental_analyzer 返回 0-30 分，按比例缩放到 0-25
        scaled = int(raw_score * 25 / 30)
        return min(scaled, 25), reasons
    except Exception as e:
        print(f"[WARN] 基本面评分失败 {code}: {e}")
        return 10, ["基本面分析中"]


def _score_news_sector_wrapper(code: str, name: str) -> Tuple[int, List[str]]:
    """
    新闻情报 + 行业热度评分（0-35分）
    调用 news_analyzer 模块，按比例缩放到 0-35
    其中：新闻情绪 0-20分，行业热度 0-15分
    """
    if not ANALYSIS_MODULES_AVAILABLE:
        # 无模块时用代码前缀做基础行业评估
        signals = []
        score = 10  # 默认中间分
        if code.startswith("688"):
            signals.append("科创板")
            score = 12
        elif code.startswith("300"):
            signals.append("创业板成长")
            score = 11
        elif code.startswith("6"):
            signals.append("沪市主板")
            score = 12
        else:
            signals.append("深市主板")
            score = 11
        return score, signals

    try:
        raw_score, reasons = news_analyzer.score_news_and_sector(code, name)
        # news_analyzer 返回 0-30 分，按比例缩放到 0-35
        scaled = int(raw_score * 35 / 30)
        return min(scaled, 35), reasons
    except Exception as e:
        print(f"[WARN] 新闻行业评分失败 {code}: {e}")
        return 12, ["情报分析中"]


def score_stock(code: str, name: str, current_price: float, change_pct: float,
                volume: int = 0, amount: float = 0, open_price: float = None,
                high_price: float = None, low_price: float = None,
                enable_deep_analysis: bool = True) -> Optional[Dict]:
    """
    多维度综合评分（v3.0）
    
    评分体系：
    ┌─────────────────────────────────────────┐
    │ 维度          │ 满分 │ 说明              │
    ├─────────────────────────────────────────┤
    │ 技术面         │  40  │ 量价行为/K线形态  │
    │ 基本面         │  25  │ PE/PB/市值/换手率 │
    │ 新闻情报       │  20  │ 近期公告/情绪分析 │
    │ 行业热度       │  15  │ 当前热点板块      │
    └─────────────────────────────────────────┘
    总分上限：100分
    """
    all_signals = []
    score_breakdown = {}

    # ── 维度1：技术面（40分）──
    tech_score, tech_signals, rsi_val, macd_val, vol_ratio_val = _score_technical(
        code, current_price, change_pct, volume, amount, open_price, high_price, low_price
    )
    score_breakdown["技术面"] = tech_score
    all_signals.extend(tech_signals)

    # ── 维度2：基本面（25分，可选深度分析）──
    if enable_deep_analysis:
        fund_score, fund_signals = _score_fundamental_wrapper(code, name, current_price)
    else:
        fund_score, fund_signals = 12, []
    score_breakdown["基本面"] = fund_score
    all_signals.extend(fund_signals[:2])  # 最多2条

    # ── 维度3+4：新闻情报+行业热度（35分，可选）──
    if enable_deep_analysis:
        news_score, news_signals = _score_news_sector_wrapper(code, name)
    else:
        news_score, news_signals = 12, []
    score_breakdown["新闻行业"] = news_score
    all_signals.extend(news_signals[:2])  # 最多2条

    # ── 综合得分 ──
    total_score = tech_score + fund_score + news_score
    total_score = min(max(total_score, 0), 100)

    # ── 止损止盈计算 ──
    buy_price = round(current_price * 1.002, 2)
    # 止损：取日内最低价的97%（如有），否则用当前价的95%
    if low_price and low_price > 0:
        stop_loss = round(min(low_price * 0.97, current_price * 0.95), 2)
    else:
        stop_loss = round(current_price * 0.95, 2)
    
    # 止盈：根据评分动态设置（高分股票设更高目标）
    if total_score >= 75:
        take_profit = round(buy_price * 1.18, 2)   # 18%
        position_pct = 0.15
    elif total_score >= 60:
        take_profit = round(buy_price * 1.12, 2)   # 12%
        position_pct = 0.12
    elif total_score >= 50:
        take_profit = round(buy_price * 1.10, 2)   # 10%
        position_pct = 0.08
    else:
        take_profit = round(buy_price * 1.08, 2)   # 8%
        position_pct = 0.05

    return {
        "code": code,
        "name": name,
        "current_price": current_price,
        "change_pct": change_pct,
        "score": total_score,
        "score_breakdown": score_breakdown,  # 各维度明细
        "signals": all_signals[:5],           # 最多显示5个信号
        "buy_price": buy_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_pct": position_pct,
        "rsi": round(rsi_val, 1),
        "macd": round(macd_val, 4),
        "vol_ratio": round(vol_ratio_val, 2),
    }


# 保持向后兼容
def score_stock_simple(code: str, name: str, current_price: float, change_pct: float,
                       volume: int = 0, amount: float = 0, open_price: float = None,
                       high_price: float = None, low_price: float = None) -> Optional[Dict]:
    """保持向后兼容的接口，调用新版 score_stock（禁用深度分析以提速）"""
    return score_stock(code, name, current_price, change_pct, volume, amount,
                       open_price, high_price, low_price, enable_deep_analysis=False)

# ─────────────────────────────────────────────
# 主选股流程
# ─────────────────────────────────────────────

def run_stock_scan(top_n: int = 9) -> List[Dict]:
    """
    全市场扫描 v3.0 - 多维度智能推荐
    
    流程：
    1. 拉取全市场实时行情，初步筛选
    2. 按成交额排序，取前500只候选
    3. 并发进行多维度分析（技术+基本面+新闻）
    4. 按综合评分排序，随机扰动保证多样性
    5. 返回前 top_n 只
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始全市场扫描（多维度分析 v3.0）...")

    stock_list = get_stock_list()
    if not stock_list:
        print("[ERROR] 无法获取真实行情数据")
        return []

    # ── 先按代码去重 ──
    seen_codes = set()
    deduped = []
    for s in stock_list:
        if s["code"] not in seen_codes:
            seen_codes.add(s["code"])
            deduped.append(s)
    stock_list = deduped
    print(f"[INFO] 去重后共 {len(stock_list)} 只候选股票")

    # ── 按成交额排序，取前 N 只进行深度分析 ──
    stock_list.sort(key=lambda x: x["amount"], reverse=True)
    max_analyze = min(len(stock_list), 500)
    candidates = stock_list[:max_analyze]
    print(f"[INFO] 将对成交额前 {max_analyze} 只股票进行多维度深度分析...")

    # ── 并发分析（使用线程池，每个股票独立分析）──
    results = []
    seen_result_codes = set()

    def _analyze_one(stock: Dict) -> Optional[Dict]:
        """分析单只股票"""
        try:
            result = score_stock(
                stock["code"], stock["name"],
                stock["current_price"], stock["change_pct"],
                volume=stock.get("volume", 0),
                amount=stock.get("amount", 0),
                open_price=stock.get("open_price"),
                high_price=stock.get("high_price"),
                low_price=stock.get("low_price"),
                enable_deep_analysis=ANALYSIS_MODULES_AVAILABLE,
            )
            return result
        except Exception as e:
            print(f"[WARN] 分析 {stock['code']} 失败: {e}")
            return None

    # 线程池并发分析（最多 8 线程）
    max_workers = 8
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_stock = {executor.submit(_analyze_one, s): s for s in candidates}
        
        for future in concurrent.futures.as_completed(future_to_stock):
            completed += 1
            if completed % 50 == 0:
                print(f"[进度] 已完成 {completed}/{max_analyze} 只股票分析...")
            
            result = future.result()
            stock = future_to_stock[future]
            
            if result and result["score"] >= 45 and stock["code"] not in seen_result_codes:
                results.append(result)
                seen_result_codes.add(stock["code"])

    print(f"[INFO] 分析完成，共 {len(results)} 只股票评分 >= 45 分")

    # ── 加入随机扰动排序（相同分数区间内保证多样性）──
    for r in results:
        r["_sort_key"] = r["score"] + random.uniform(0, 4)
    results.sort(key=lambda x: x["_sort_key"], reverse=True)
    top = results[:top_n]
    for r in top:
        r.pop("_sort_key", None)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描完成，返回前 {len(top)} 只推荐")

    # ── 构建推荐列表 ──
    suggestions = []
    for r in top:
        account_value = 150000.0
        shares = int(account_value * r["position_pct"] / r["buy_price"] // 100 * 100)
        shares = max(shares, 100)
        cost = shares * r["buy_price"]

        # 格式化评分维度说明（添加到 signals）
        breakdown = r.get("score_breakdown", {})
        if breakdown:
            breakdown_str = " | ".join([f"{k}:{v}" for k, v in breakdown.items()])
            print(f"  [{r['name']}({r['code']})] 总分:{r['score']} ({breakdown_str})")

        suggestions.append({
            **r,
            "suggested_shares": shares,
            "estimated_cost": round(cost, 2),
            "action": "买入",
            "already_holding": False,
            "updated_at": datetime.now().isoformat()
        })

    # 保存到数据库
    database.save_suggestions(suggestions)
    return suggestions

def load_suggestions() -> Dict:
    """加载推荐列表，并用实时行情刷新当前价格"""
    suggestions = database.load_suggestions()
    updated_at = database.get_suggestions_updated_at()

    # 如果 Tushare 可用且有推荐，实时刷新 current_price 和 change_pct
    if TUSHARE_AVAILABLE and suggestions:
        try:
            codes = [s["stock_code"] for s in suggestions]
            df_rt = ts.get_realtime_quotes(codes)
            if df_rt is not None and not df_rt.empty:
                price_map = {}
                for _, row in df_rt.iterrows():
                    code = str(row.get("code", "")).zfill(6)
                    try:
                        price = float(str(row.get("price", "0")).strip())
                        pre_close = float(str(row.get("pre_close", "0")).strip())
                        if price > 0 and pre_close > 0:
                            change_pct = round((price - pre_close) / pre_close * 100, 2)
                            price_map[code] = {"price": price, "change_pct": change_pct}
                    except (ValueError, TypeError):
                        pass
                # 用实时价格覆盖数据库中的旧价格
                for s in suggestions:
                    code = s.get("stock_code", "")
                    if code in price_map:
                        s["current_price"] = price_map[code]["price"]
                        s["change_pct"] = price_map[code]["change_pct"]
                        # 同步刷新建议买入价（取实时价微涨0.2%）
                        s["buy_price"] = round(price_map[code]["price"] * 1.002, 2)
                print(f"[INFO] 推荐列表实时价格已刷新，共 {len(price_map)} 只")
        except Exception as e:
            print(f"[WARN] 推荐列表实时价格刷新失败，返回上次扫描价格: {e}")

    return {
        "updated_at": updated_at,
        "items": suggestions
    }

# ─────────────────────────────────────────────
# 用户相关功能（使用数据库）
# ─────────────────────────────────────────────

def execute_buy(user_id: int, code: str, name: str, shares: int, price: float) -> Dict:
    """执行模拟买入"""
    account = database.get_account(user_id)
    cost = shares * price
    commission = max(cost * 0.0003, 5)
    total_cost = cost + commission

    if total_cost > account["cash"]:
        return {"success": False, "message": f"资金不足，需要 {total_cost:.2f} 元，当前现金 {account['cash']:.2f} 元"}

    # 更新账户现金
    new_cash = account["cash"] - total_cost
    database.update_account(user_id, cash=new_cash)

    # 更新持仓
    holding = database.get_holding(user_id, code)
    if holding:
        total_shares = holding["shares"] + shares
        avg_price = (holding["shares"] * holding["avg_price"] + shares * price) / total_shares
        database.update_holding(user_id, code, name, total_shares, avg_price, price)
    else:
        database.update_holding(user_id, code, name, shares, price, price)

    # 记录交易
    database.add_trade_log(
        user_id=user_id,
        action="买入",
        stock_code=code,
        stock_name=name,
        shares=shares,
        price=price,
        amount=total_cost,
        profit=None,
        profit_pct=None,
        commission=commission
    )

    return {"success": True, "message": f"成功买入 {name}({code}) {shares}股，均价 {price} 元，花费 {total_cost:.2f} 元（含佣金 {commission:.2f}）"}

def execute_sell(user_id: int, code: str, shares: int, price: float) -> Dict:
    """执行模拟卖出"""
    holding = database.get_holding(user_id, code)
    if not holding:
        return {"success": False, "message": f"未持有 {code}"}

    if shares > holding["shares"]:
        shares = holding["shares"]

    revenue = shares * price
    commission = max(revenue * 0.0003, 5)
    stamp_tax = revenue * 0.001
    net_revenue = revenue - commission - stamp_tax

    profit = net_revenue - shares * holding["avg_price"]
    profit_pct = profit / (shares * holding["avg_price"]) * 100 if shares * holding["avg_price"] > 0 else 0

    # 更新账户现金
    account = database.get_account(user_id)
    new_cash = account["cash"] + net_revenue
    new_total_profit = account["total_profit"] + profit
    database.update_account(user_id, cash=new_cash, total_profit=new_total_profit)

    # 更新或删除持仓
    remaining = holding["shares"] - shares
    if remaining <= 0:
        database.delete_holding(user_id, code)
    else:
        database.update_holding(user_id, code, holding["stock_name"], remaining, holding["avg_price"], holding["buy_price"])

    # 记录交易
    database.add_trade_log(
        user_id=user_id,
        action="卖出",
        stock_code=code,
        stock_name=holding["stock_name"],
        shares=shares,
        price=price,
        amount=net_revenue,
        profit=profit,
        profit_pct=profit_pct,
        commission=commission + stamp_tax
    )

    profit_str = f"盈利 {profit:.2f} 元 (+{profit_pct:.2f}%)" if profit >= 0 else f"亏损 {abs(profit):.2f} 元 ({profit_pct:.2f}%)"
    return {"success": True, "message": f"成功卖出 {holding['stock_name']}({code}) {shares}股，均价 {price} 元，{profit_str}"}

def get_portfolio_snapshot(user_id: int) -> Dict:
    """获取用户账户快照（带实时价格）"""
    account = database.get_account(user_id)
    holdings = database.get_holdings(user_id)

    holdings_detail = []
    total_market_value = account["cash"]
    total_cost = 0

    # 批量获取持仓股票的实时价格
    real_prices = {}
    if holdings and TUSHARE_AVAILABLE:
        try:
            codes = [h["stock_code"] for h in holdings]
            df_rt = ts.get_realtime_quotes(codes)
            if df_rt is not None and not df_rt.empty:
                for _, row in df_rt.iterrows():
                    code = str(row['code']).zfill(6)
                    try:
                        price = float(str(row['price']).strip())
                        pre_close = float(str(row['pre_close']).strip())
                        if price > 0 and pre_close > 0:
                            real_prices[code] = {
                                "price": price,
                                "change_pct": round((price - pre_close) / pre_close * 100, 2)
                            }
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            print(f"[WARN] 获取持仓实时价格失败: {e}")

    # 计算每个持仓的市值和盈亏
    for holding in holdings:
        code = holding["stock_code"]
        
        # 优先使用实时价格
        if code in real_prices:
            current_price = real_prices[code]["price"]
            change_pct = real_prices[code]["change_pct"]
        else:
            current_price = holding["avg_price"]  # 降级到成本价
            change_pct = 0
        
        market_value = holding["shares"] * current_price
        cost_value = holding["shares"] * holding["avg_price"]
        profit = market_value - cost_value
        profit_pct = profit / cost_value * 100 if cost_value > 0 else 0

        holdings_detail.append({
            "code": code,
            "name": holding["stock_name"],
            "shares": holding["shares"],
            "avg_price": holding["avg_price"],
            "current_price": current_price,
            "change_pct": change_pct,
            "market_value": round(market_value, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2)
        })

        total_market_value += market_value
        total_cost += cost_value

    total_profit = total_market_value - account["initial_cash"]
    total_profit_pct = total_profit / account["initial_cash"] * 100

    return {
        "cash": round(account["cash"], 2),
        "initial_cash": account["initial_cash"],
        "total_market_value": round(total_market_value, 2),
        "total_profit": round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "holdings": holdings_detail,
        "snapshot_time": datetime.now().isoformat()
    }

def load_account(user_id: int) -> Dict:
    """获取用户账户"""
    return database.get_account(user_id)

def load_trade_log(user_id: int) -> List:
    """获取用户交易记录"""
    return database.get_trade_logs(user_id)

# ─────────────────────────────────────────────
# 初始化
# ─────────────────────────────────────────────

def init_system():
    """初始化系统"""
    database.init_db()
    print("[系统] 数据库初始化完成")