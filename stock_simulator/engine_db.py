"""
选股引擎 - 数据库版本（支持多用户）
"""

import json
import os
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import database

# 尝试加载 Tushare
TUSHARE_AVAILABLE = False
try:
    import tushare as ts
    try:
        from .tushare_config import TUSHARE_TOKEN
        if TUSHARE_TOKEN and TUSHARE_TOKEN != "你的Tushare Token粘贴在这里":
            ts.set_token(TUSHARE_TOKEN)
            TUSHARE_AVAILABLE = True
            print("[INFO] Tushare 已启用，使用真实行情数据")
        else:
            print("[WARN] Tushare Token 未配置，使用模拟数据")
    except ImportError:
        print("[WARN] 未找到 tushare_config.py，使用模拟数据")
except ImportError:
    print("[WARN] 未安装 tushare，使用模拟数据")

# 模拟股票池（降级用）
MOCK_STOCKS = [
    ("600519", "贵州茅台"), ("300750", "宁德时代"), ("601318", "中国平安"),
    ("600030", "中信证券"), ("300059", "东方财富"), ("603259", "药明康德"),
    ("000858", "五粮液"), ("002475", "立讯精密"), ("601888", "中国中免"),
    ("300760", "迈瑞医疗"), ("600887", "伊利股份"), ("000333", "美的集团"),
    ("002594", "比亚迪"), ("601012", "隆基绿能"), ("300124", "汇川技术"),
    ("600690", "海尔智家"), ("002271", "东方雨虹"), ("603986", "兆易创新"),
    ("688981", "中芯国际"), ("002142", "宁波银行"), ("000651", "格力电器"),
    ("000725", "京东方A"), ("600276", "恒瑞医药"), ("002415", "海康威视"),
    ("300142", "沃森生物"), ("600009", "上海机场"), ("002601", "龙佰集团"),
    ("300274", "阳光电源"), ("600036", "招商银行"), ("002032", "苏泊尔"),
    ("601166", "兴业银行"), ("600031", "三一重工"), ("000568", "泸州老窖"),
]

INITIAL_CASH = 10000.0

# ─────────────────────────────────────────────
# 行情获取（真实 + 模拟双支持）
# ─────────────────────────────────────────────

def _build_all_market_codes() -> List[str]:
    """
    构建全市场 A 股代码列表（无需任何接口权限，直接枚举）
    """
    ranges = [
        range(600000, 601000),
        range(601000, 602000),
        range(603000, 604000),
        range(605000, 606000),
        range(1, 1000),
        range(1000, 2000),
        range(2000, 3000),
        range(3000, 4000),
        range(300000, 301000),
        range(301000, 302000),
    ]
    codes = []
    for r in ranges:
        for n in r:
            codes.append(str(n).zfill(6))
    return codes

def get_stock_list() -> List[Dict]:
    """
    获取全市场实时行情（批量拉取，无需高权限）
    """
    import pandas as pd

    if TUSHARE_AVAILABLE:
        all_codes = _build_all_market_codes()
        print(f"[INFO] 全市场扫描启动，代码池共 {len(all_codes)} 只...")

        all_quotes = []
        batch_size = 80
        total_batches = (len(all_codes) + batch_size - 1) // batch_size
        success_batches = 0

        for i in range(0, len(all_codes), batch_size):
            batch = all_codes[i:i + batch_size]
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
            except Exception as e:
                pass  # 静默跳过失败批次

        if not all_quotes:
            print("[ERROR] 全市场实时行情拉取全部失败，降级到模拟数据")
        else:
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

                    volume_str = str(row.get('volume', '0')).strip()
                    amount_str = str(row.get('amount', '0')).strip()
                    volume = int(float(volume_str)) if volume_str else 0
                    amount = float(amount_str) if amount_str else 0

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
                        "amount": amount
                    })
                except (ValueError, TypeError):
                    continue

            # 随机打乱后排序
            random.shuffle(result)
            result.sort(key=lambda x: x["change_pct"], reverse=True)
            print(f"[INFO] 全市场筛选完成，共 {len(result)} 只候选股票")
            return result

    # 降级：使用内置股票池
    print("[WARN] Tushare 不可用，使用内置模拟数据")
    result = []
    for code, name in MOCK_STOCKS:
        base_price = random.uniform(15, 150)
        change_pct = random.uniform(-5, 8)
        current_price = round(base_price * (1 + change_pct / 100), 2)
        amount = random.uniform(1, 50) * 1e8
        volume = int(amount / current_price)
        result.append({
            "code": code, "name": name,
            "current_price": current_price, "change_pct": round(change_pct, 2),
            "volume": volume, "amount": amount
        })
    result.sort(key=lambda x: x["change_pct"], reverse=True)
    return result

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
    for c, name in MOCK_STOCKS:
        if c == code:
            return name
    return None

def get_hist_data(code: str, days: int = 60) -> Optional[List[Dict]]:
    """获取历史日线数据（Tushare 真实 或 模拟）"""

    if TUSHARE_AVAILABLE:
        try:
            pro = ts.pro_api()
            ts_code = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime('%Y%m%d')

            df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df.empty:
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
            print(f"[WARN] Tushare 获取 {code} 历史数据失败: {e}，使用模拟数据")

    # 模拟历史数据
    base_price = random.uniform(15, 150)
    data = []
    price = base_price

    for i in range(days):
        date = datetime.now() - timedelta(days=days - i)
        change = random.uniform(-0.05, 0.05)
        price = max(price * (1 + change), 3)

        volatility = price * 0.03
        open_price = price + random.uniform(-volatility, volatility)
        close_price = price
        high_price = max(open_price, close_price) * random.uniform(1, 1.02)
        low_price = min(open_price, close_price) * random.uniform(0.98, 1)
        volume = int(random.uniform(1, 10) * 1e6)
        amount = volume * close_price

        data.append({
            "date": date,
            "open": round(open_price, 2),
            "close": round(close_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "volume": volume,
            "amount": amount
        })

    return data

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

def score_stock(code: str, name: str, current_price: float, change_pct: float) -> Optional[Dict]:
    """对单只股票打分"""
    hist = get_hist_data(code, days=60)
    if not hist:
        return None

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

# ─────────────────────────────────────────────
# 主选股流程
# ─────────────────────────────────────────────

def run_stock_scan(top_n: int = 5) -> List[Dict]:
    """全市场扫描"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始全市场扫描...")

    stock_list = get_stock_list()
    if not stock_list:
        print("[WARN] 无法获取股票列表")
        return []

    # 取候选股：涨幅居前的300只进行技术分析
    candidates = stock_list[:500] if len(stock_list) >= 500 else stock_list
    import random as _random
    if len(candidates) > 300:
        candidates = _random.sample(candidates, 300)

    results = []
    for stock in candidates:
        result = score_stock(stock["code"], stock["name"], stock["current_price"], stock["change_pct"])
        if result and result["score"] >= 50:
            results.append(result)

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:top_n]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描完成，找到 {len(results)} 只候选，返回前 {len(top)} 只")

    # 为每个用户计算建议股数（全局推荐，但股数根据用户资金计算）
    # 这里我们使用默认资金计算，上线后每个用户会看到不同股数
    suggestions = []
    for r in top:
        # 默认使用 10000 元资金计算
        account_value = 10000.0
        shares = int(account_value * r["position_pct"] / r["buy_price"] // 100 * 100)
        shares = max(shares, 100)
        cost = shares * r["buy_price"]

        suggestions.append({
            **r,
            "suggested_shares": shares,
            "estimated_cost": round(cost, 2),
            "action": "买入",  # 上线后根据用户持仓动态计算
            "already_holding": False,  # 上线后根据用户持仓动态计算
            "updated_at": datetime.now().isoformat()
        })

    # 保存到数据库
    database.save_suggestions(suggestions)
    return suggestions

def load_suggestions() -> Dict:
    """加载推荐列表"""
    suggestions = database.load_suggestions()
    updated_at = database.get_suggestions_updated_at()
    
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
    """获取用户账户快照"""
    account = database.get_account(user_id)
    holdings = database.get_holdings(user_id)

    holdings_detail = []
    total_market_value = account["cash"]
    total_cost = 0

    # 获取当前价格（简化版，实际应该批量获取）
    for holding in holdings:
        code = holding["stock_code"]
        current_price = holding["avg_price"]  # 默认用成本价
        change_pct = 0

        # 这里可以调用 Tushare 获取实时价格，暂时简化
        # 实际部署时可以添加定时任务更新持仓价格
        
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