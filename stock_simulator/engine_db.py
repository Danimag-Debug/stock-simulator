"""
选股引擎 - 数据库版本（支持多用户）
"""

import json
import os
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional
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
# 中线选股评分
# ─────────────────────────────────────────────

def score_stock_simple(code: str, name: str, current_price: float, change_pct: float, 
                       volume: int = 0, amount: float = 0, open_price: float = None,
                       high_price: float = None, low_price: float = None) -> Optional[Dict]:
    """
    对单只股票打分（简化版，基于实时行情多维度评分）
    包括：涨幅、量价、K线形态、价格位置
    """
    score = 0
    signals = []
    
    # 1. 涨幅评分（+40）
    if 0 <= change_pct <= 3:
        score += 40
        signals.append(f"涨幅温和({change_pct:.1f}%)")
    elif 3 < change_pct <= 5:
        score += 35
        signals.append(f"涨幅适中({change_pct:.1f}%)")
    elif 5 < change_pct <= 8:
        score += 25
        signals.append(f"涨幅较大({change_pct:.1f}%)")
    elif change_pct < 0:
        score += 30  # 下跌反而可能是机会
        signals.append(f"回调({change_pct:.1f}%)")
    else:
        score += 15
        signals.append(f"涨停附近({change_pct:.1f}%)")
    
    # 2. 价格位置评分（+30）- 基于开盘价/最高价/最低价
    if open_price and high_price and low_price and high_price > low_price:
        price_range = high_price - low_price
        if price_range > 0:
            position = (current_price - low_price) / price_range  # 0=最低，1=最高
            if 0.3 <= position <= 0.7:  # 中间位置，有上升空间又有下跌保护
                score += 30
                signals.append(f"K线中轨({position*100:.0f}%)")
            elif 0.2 <= position < 0.3:  # 接近下轨，可能反弹
                score += 25
                signals.append(f"K线下轨({position*100:.0f}%)")
            elif 0.7 < position <= 0.8:  # 接近上轨，但还没到顶
                score += 20
                signals.append(f"K线上轨({position*100:.0f}%)")
            elif position > 0.8:  # 非常接近最高
                score += 5
                signals.append(f"接近高点({position*100:.0f}%)")
            else:
                score += 15
                signals.append(f"低位({position*100:.0f}%)")
    else:
        # 无日内高低数据时使用价格区间简化评分
        if 5 <= current_price <= 50:
            score += 30
            signals.append(f"价格适中(¥{current_price:.2f})")
        elif current_price < 5:
            score += 25
            signals.append(f"低价区(¥{current_price:.2f})")
        else:
            score += 15
            signals.append(f"高价区(¥{current_price:.2f})")
    
    # 3. 量能评分（+20）- 基于成交额和换手率
    if amount > 0 and current_price > 0:
        # 简单估计换手率（成交额/流通市值，假设市盈率20倍）
        estimated_vol = (amount / current_price / 1e8) * 100 if current_price > 0 else 0
        if 1 <= estimated_vol <= 5:  # 量能适中
            score += 20
            signals.append(f"量能温和({estimated_vol:.1f}%)")
        elif estimated_vol > 5:  # 量能爆发
            score += 15
            signals.append(f"量能爆发({estimated_vol:.1f}%)")
        else:  # 量能不足
            score += 5
            signals.append(f"量能不足({estimated_vol:.1f}%)")
    
    # 4. 成交额评分（+10）
    if amount > 1e8:  # 超过1亿成交额
        score += 10
        signals.append("成交活跃")
    elif amount > 5e7:  # 5000万以上
        score += 5
        signals.append("成交尚可")
    
    # 5. 板块评分（+5）
    if code.startswith('6'):
        score += 5
        signals.append("沪市主板")
    elif code.startswith('0'):
        score += 5
        signals.append("深市主板")
    elif code.startswith('3'):
        score += 3
        signals.append("创业板")
    elif code.startswith('688'):
        score += 3
        signals.append("科创板")
    
    # 确保分数在0-100之间
    score = min(max(score, 0), 100)
    
    # 计算推荐参数
    position_pct = 0.10 if score >= 70 else 0.08 if score >= 50 else 0.05
    buy_price = round(current_price * 1.002, 2)  # 高于当前价0.2%
    stop_loss = round(low_price * 0.98 if low_price else current_price * 0.95, 2)
    take_profit = round(buy_price * 1.12, 2)
    
    return {
        "code": code,
        "name": name,
        "current_price": current_price,
        "change_pct": change_pct,
        "score": score,
        "signals": signals[:3],  # 最多显示3个信号
        "buy_price": buy_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_pct": position_pct,
        "rsi": 50,  # 占位值
        "macd": 0,  # 占位值
        "vol_ratio": 1.0  # 占位值
    }


def score_stock(code: str, name: str, current_price: float, change_pct: float,
                volume: int = 0, amount: float = 0, open_price: float = None,
                high_price: float = None, low_price: float = None) -> Optional[Dict]:
    """对单只股票打分（完整版，优先使用历史数据，降级到简化版）"""
    # 尝试获取历史数据进行完整评分
    try:
        if not TUSHARE_AVAILABLE:
            raise RuntimeError("Tushare 不可用")
        
        hist = get_hist_data(code, days=60)
        if not hist or len(hist) < 30:
            raise RuntimeError(f"历史数据不足: {len(hist) if hist else 0} 条")

        hist = calc_ma(hist)
        hist = calc_macd(hist)
        hist = calc_rsi(hist)
        hist = calc_vol_ratio(hist)

        last = hist[-1]
        prev = hist[-2]

        score = 0
        signals = []

        # 1. 均线多头排列
        if last.get("ma5") and last.get("ma10") and last.get("ma20") and last.get("ma30"):
            if last["ma5"] > last["ma10"] > last["ma20"] > last["ma30"]:
                score += 25
                signals.append("均线多头排列")

            if prev.get("ma5") and prev.get("ma20") and prev["ma5"] <= prev["ma20"] and last["ma5"] > last["ma20"]:
                score += 20
                signals.append("MA5金叉MA20")
            elif last["ma5"] > last["ma20"]:
                score += 10
                signals.append("MA5在MA20上方")

        # 2. MACD
        if prev.get("dif") and prev.get("dea") and last.get("dif") and last.get("dea"):
            if prev["dif"] <= prev["dea"] and last["dif"] > last["dea"]:
                score += 20
                signals.append("MACD金叉")
            elif last["macd"] and last["macd"] > 0 and last["dif"] > 0:
                score += 10
                signals.append("MACD多头")

        # 3. RSI
        rsi = last.get("rsi", 50)
        if 45 <= rsi <= 65:
            score += 15
            signals.append(f"RSI适中({rsi:.1f})")
        elif 35 <= rsi < 45:
            score += 8
            signals.append(f"RSI偏低可建仓({rsi:.1f})")
        elif rsi > 75:
            score -= 10
            signals.append(f"RSI超买({rsi:.1f})")

        # 4. 量比
        vol_ratio = last.get("vol_ratio", 1)
        if 1.5 <= vol_ratio <= 5:
            score += 15
            signals.append(f"量比放大({vol_ratio:.1f}x)")
        elif vol_ratio > 5:
            score += 5
            signals.append(f"量比异常({vol_ratio:.1f}x)")

        # 5. 价格在MA20之上
        if last.get("ma20") and last["close"] > last["ma20"]:
            score += 5
            signals.append("价格在MA20上方")

        # 止损止盈
        ma20 = last.get("ma20", current_price * 0.95)
        buy_price = round(current_price * 1.002, 2)
        stop_loss = round(ma20 * 0.98, 2)
        take_profit = round(buy_price * 1.12, 2)

        if score >= 70:
            position_pct = 0.20
        elif score >= 55:
            position_pct = 0.15
        else:
            position_pct = 0.10

        return {
            "code": code,
            "name": name,
            "current_price": current_price,
            "change_pct": change_pct,
            "score": score,
            "signals": signals,
            "buy_price": buy_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position_pct": position_pct,
            "rsi": round(rsi, 1),
            "macd": round(float(last.get("macd", 0)), 4),
            "vol_ratio": round(float(vol_ratio), 2),
        }

    except Exception as e:
        # 历史数据不可用，降级到简化版
        print(f"[DEBUG] {code} 历史评分失败，使用简化版: {e}")
        return score_stock_simple(code, name, current_price, change_pct, volume, amount, open_price, high_price, low_price)

# ─────────────────────────────────────────────
# 主选股流程
# ─────────────────────────────────────────────

def run_stock_scan(top_n: int = 9) -> List[Dict]:
    """全市场扫描 - 强制真实数据，返回9只推荐股票"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始全市场扫描...")

    stock_list = get_stock_list()
    if not stock_list:
        print("[ERROR] 无法获取真实行情数据")
        return []

    # 先按代码去重（同一只股票只保留一条）
    seen_codes = set()
    deduped = []
    for s in stock_list:
        if s["code"] not in seen_codes:
            seen_codes.add(s["code"])
            deduped.append(s)
    stock_list = deduped
    print(f"[INFO] 去重后共 {len(stock_list)} 只候选股票")

    # 对候选池随机打散（避免每次都分析完全相同的股票），再按成交额排序
    # 按成交额从高到低排序，保证分析流动性好的股票
    stock_list.sort(key=lambda x: x["amount"], reverse=True)

    # 限制分析数量以提高效率
    max_analyze = min(len(stock_list), 800)
    candidates = stock_list[:max_analyze]
    print(f"[INFO] 将分析成交额前 {max_analyze} 只股票...")

    results = []
    seen_result_codes = set()  # 评分结果也去重
    analyzed_count = 0
    for stock in candidates:
        analyzed_count += 1
        if analyzed_count % 100 == 0:
            print(f"[进度] 已分析 {analyzed_count}/{max_analyze} 只股票...")

        # 跳过已经有结果的股票（双重去重保险）
        if stock["code"] in seen_result_codes:
            continue
        
        result = score_stock(
            stock["code"], stock["name"],
            stock["current_price"], stock["change_pct"],
            volume=stock.get("volume", 0),
            amount=stock.get("amount", 0),
            open_price=stock.get("open_price"),
            high_price=stock.get("high_price"),
            low_price=stock.get("low_price"),
        )
        
        if result and result["score"] >= 50:
            results.append(result)
            seen_result_codes.add(stock["code"])

    # 评分相同时加入随机扰动，保证每次推荐有变化
    for r in results:
        r["_sort_key"] = r["score"] + random.uniform(0, 3)
    results.sort(key=lambda x: x["_sort_key"], reverse=True)
    top = results[:top_n]
    # 清除内部排序字段
    for r in top:
        r.pop("_sort_key", None)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描完成，找到 {len(results)} 只候选，返回前 {len(top)} 只推荐股票")

    # 为每个用户计算建议股数
    suggestions = []
    for r in top:
        account_value = 150000.0
        shares = int(account_value * r["position_pct"] / r["buy_price"] // 100 * 100)
        shares = max(shares, 100)
        cost = shares * r["buy_price"]

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