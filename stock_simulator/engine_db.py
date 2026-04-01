"""
选股引擎 - 数据库版本（支持多用户）
专业多因子量化评分系统 v5.0

v5.0 重大升级（专业操盘手视角）：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
新增模块:
1. 大盘环境判断 (market_regime_analyzer)  - 牛市/震荡/弱势/暴跌分级
2. 组合风险管理 (portfolio_risk)           - 行业分散度控制
3. 动态调仓提醒 (alert_system)           - 止损/止盈/减仓提醒
4. 支撑/压力位识别                        - 关键价位止损止盈
5. 顶底背离反哺评分                        - 背离信号直接影响评分
6. 时间维度因子                           - 连续阳线/缩量变盘等
7. 新闻情绪位置上下文                      - 高位利好打折/低位利空打折

评分体系：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
维度           满分    核心指标
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
技术面         40分    布林带/KDJ/MACD/RSI/WR/ATR/OBV/VWAP/动量/背离/时间
基本面         25分    PE/PB/ROE/PEG/股息率/DCF估值/成长性
行业情报       35分    行业热度/资金流向/新闻情绪(含位置上下文)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
总分: 100分

选股流程:
1. 大盘环境判断 → 暴跌日停止推荐
2. 全市场筛选 → 成交额前500只
3. 多维度评分 → 动态评分门槛(大盘弱时提高)
4. 行业分散度控制 → 同行业最多2只
5. 仓位限制 → 受大盘环境约束
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
    import technical_analyzer   # 新增：专业技术分析模块
    import market_regime_analyzer  # 新增：大盘环境判断
    import portfolio_risk       # 新增：组合风险管理
    import alert_system         # 新增：动态调仓提醒
    if TUSHARE_AVAILABLE:
        fundamental_analyzer.set_pro_api(ts.pro_api())
        market_regime_analyzer.set_tushare(ts)
        alert_system.init_alert_system(ts_instance=ts, analyzer_available=True)
    ANALYSIS_MODULES_AVAILABLE = True
    print("[INFO] 辅助分析模块加载成功（新闻+基本面+技术+大盘环境+风控+提醒）")
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

# ─── 全量股票名称缓存（用于名称搜索，避免每次调 API）──
_STOCK_NAME_CACHE = {}  # {code: name, ...}
_STOCK_CACHE_LOADED = False


def _load_stock_name_cache():
    """
    加载沪深两市全部上市股票的代码-名称映射。
    
    优先级：
    1. 静态文件 stock_name_list.py（5400+ 只，瞬时加载）
    2. 东方财富公开 API（网络备份）
    3. 模拟股票池（最终回退）
    """
    global _STOCK_NAME_CACHE, _STOCK_CACHE_LOADED
    if _STOCK_CACHE_LOADED:
        return

    # ── 方式1：静态文件（最可靠、最快速）──
    try:
        stock_list_path = os.path.join(os.path.dirname(__file__), "stock_name_list.py")
        if os.path.exists(stock_list_path):
            import importlib.util
            spec = importlib.util.spec_from_file_location("stock_name_list", stock_list_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            stock_map = getattr(mod, 'STOCK_NAME_MAP', {})
            if stock_map:
                _STOCK_NAME_CACHE.update(stock_map)
                _STOCK_CACHE_LOADED = True
                print(f"[缓存] 股票名称缓存加载完成（静态文件），共 {len(_STOCK_NAME_CACHE)} 只股票")
                return
    except Exception as e:
        print(f"[WARN] 静态股票列表加载失败: {e}")

    # ── 方式2：东方财富 API ──
    try:
        import urllib.request
        total_loaded = 0
        page = 1
        page_size = 1000
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://quote.eastmoney.com/center/gridlist.html#hs_a_board',
        }

        while page <= 8:
            url = (
                f"https://push2.eastmoney.com/api/qt/clist/get?"
                f"pn={page}&pz={page_size}&po=1&np=1&fltt=2&invt=2&fid=f3"
                f"&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
                f"&fields=f12,f14"
            )
            try:
                req = urllib.request.Request(url, headers=headers)
                resp = urllib.request.urlopen(req, timeout=10)
                data = json.loads(resp.read())
                items = data.get('data', {}).get('diff', [])
                for item in items:
                    code = str(item.get('f12', '')).strip()
                    name = str(item.get('f14', '')).strip()
                    if code and name and len(code) == 6:
                        _STOCK_NAME_CACHE[code] = name
                        total_loaded += 1
                total = data.get('data', {}).get('total', 0)
                if total_loaded >= total or not items:
                    break
            except Exception:
                pass
            page += 1
            import time
            time.sleep(1)

        if len(_STOCK_NAME_CACHE) > 100:
            _STOCK_CACHE_LOADED = True
            print(f"[缓存] 股票名称缓存加载完成（东方财富），共 {len(_STOCK_NAME_CACHE)} 只股票")
            return
    except Exception as e:
        print(f"[WARN] 东方财富接口失败: {e}")

    # ── 方式3：模拟股票池回退 ──
    for c, n, _ in MOCK_STOCK_DETAILS:
        _STOCK_NAME_CACHE[c] = n
    _STOCK_CACHE_LOADED = True
    print(f"[缓存] 股票名称缓存使用模拟池，共 {len(_STOCK_NAME_CACHE)} 只股票")


def search_stock_by_name(keyword: str) -> Optional[Tuple[str, str]]:
    """
    按名称关键字搜索股票（全量缓存 + 模拟池回退）
    返回 (code, name) 或 None
    """
    # 确保缓存已加载
    _load_stock_name_cache()

    # 在全量缓存中搜索
    if _STOCK_NAME_CACHE:
        matches = []
        keyword_lower = keyword.lower()
        for code, name in _STOCK_NAME_CACHE.items():
            if keyword in name or keyword_lower in name.lower():
                matches.append((code, name))

        if matches:
            # 如果有精确匹配（名称以关键字开头），优先返回
            exact = [m for m in matches if m[1].startswith(keyword)]
            if exact:
                return exact[0]
            return matches[0]

    # 回退到模拟股票池
    for c, n, _ in MOCK_STOCK_DETAILS:
        if keyword in n:
            return (c, n)

    return None


def get_stock_name(code: str) -> str:
    """根据代码获取股票名称"""
    _load_stock_name_cache()
    if code in _STOCK_NAME_CACHE:
        return _STOCK_NAME_CACHE[code]
    # 回退模拟池
    for c, n, _ in MOCK_STOCK_DETAILS:
        if c == code:
            return n
    return ""


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
                     high_price: Optional[float], low_price: Optional[float]) -> Tuple[int, List[str], Dict]:
    """
    专业技术面评分（0-40分）v4.0
    
    策略：
    1. 优先使用历史K线（Tushare Pro）进行完整专业技术分析
    2. 降级：使用实时行情简化分析
    
    返回：(分数, 信号列表, 指标字典)
    """
    # ── 尝试历史K线分析 ──
    if TUSHARE_AVAILABLE and ANALYSIS_MODULES_AVAILABLE:
        try:
            hist = get_hist_data(code, days=90)  # 获取90天数据，保证指标准确
            if hist and len(hist) >= 30:
                # 使用专业技术分析模块
                score, signals, indicators = technical_analyzer.score_technical_professional(
                    hist, current_price, change_pct, amount
                )
                return score, signals, indicators
        except Exception as _e:
            pass  # 降级到实时行情
    
    # ── 降级：基于实时行情的简化分析 ──
    if ANALYSIS_MODULES_AVAILABLE:
        score, signals, indicators = technical_analyzer._score_technical_simple(
            current_price, change_pct, amount
        )
    else:
        # 完全降级：不依赖任何模块
        score = 0
        signals = []
        
        if 0.5 <= change_pct <= 3.0:
            score += 15
            signals.append(f"温和上涨({change_pct:.1f}%)")
        elif 3.0 < change_pct <= 5.5:
            score += 12
            signals.append(f"强势上涨({change_pct:.1f}%)")
        elif -1.5 <= change_pct < 0:
            score += 10
            signals.append(f"小幅回调({change_pct:.1f}%)")
        elif -4 <= change_pct < -1.5:
            score += 7
            signals.append(f"回调({change_pct:.1f}%)")
        else:
            score += 5
            signals.append(f"涨幅({change_pct:.1f}%)")
        
        if amount >= 5e8:
            score += 13
            signals.append(f"成交活跃({amount/1e8:.1f}亿)")
        elif amount >= 1e8:
            score += 10
        elif amount >= 5e7:
            score += 6
        
        score = min(score, 40)
        indicators = {"rsi": 50, "k": 50, "d": 50, "j": 50, "wr": -50, "macd": 0, "vol_ratio": 1.0, "momentum_10d": 0}
    
    return score, signals, indicators


def _score_fundamental_wrapper(code: str, name: str, current_price: float) -> Tuple[int, List[str]]:
    """
    基本面评分（0-25分）
    调用 fundamental_analyzer 模块，按比例缩放到 0-25
    
    注意：fundamental_analyzer v2.0 已内置降级机制，不会再返回固定默认分。
    当 Tushare 不可用时，会通过规则引擎给出差异化评分。
    """
    if not ANALYSIS_MODULES_AVAILABLE:
        # 无模块时，使用代码规则给差异化基础分（不再是固定分）
        score = 10 + (int(code[-2:]) % 8)  # 10-17分，基于代码最后两位确定性差异化
        reasons = []
        if code.startswith("688"):
            reasons.append("科创板(成长预期高)")
            score = min(score + 3, 25)
        elif code.startswith("300"):
            reasons.append("创业板(高弹性)")
        if 10 <= current_price <= 100:
            reasons.append(f"价格区间健康(¥{current_price:.2f})")
        elif current_price > 100:
            reasons.append(f"高价蓝筹(¥{current_price:.2f})")
        return min(score, 25), reasons

    try:
        raw_score, reasons = fundamental_analyzer.score_fundamental(code, name, current_price)
        # fundamental_analyzer 返回 0-30 分，按比例缩放到 0-25
        scaled = int(raw_score * 25 / 30)
        return min(scaled, 25), reasons
    except Exception as e:
        print(f"[WARN] 基本面评分失败 {code}: {e}")
        # 失败时基于代码给差异化默认分
        fallback = 10 + (int(code) % 8)
        return min(fallback, 20), ["基本面评估中(数据获取延迟)"]


def _score_news_sector_wrapper(code: str, name: str, rsi: float = 50.0) -> Tuple[int, List[str]]:
    """
    新闻情报 + 行业热度 + 资金流向评分（0-35分）v2.1
    
    注意：news_analyzer v2.1 已内置位置上下文：
    - 高位利好 = 利好兑现（打折）
    - 低位利空 = 利空出尽（打折）
    - 行业热度基于静态映射（不依赖网络），永远有效
    """
    if not ANALYSIS_MODULES_AVAILABLE:
        # 无模块时用代码和名称做基础行业评分
        score = 0
        reasons = []
        # 行业热度（确定性）
        if code.startswith("688"):
            score += 14
            reasons.append("🔥科创板(AI/芯片赛道)")
        elif code.startswith("300"):
            score += 12
            reasons.append("🔆创业板成长")
        elif code.startswith("6"):
            score += 11
            reasons.append("沪市主板")
        else:
            score += 10
            reasons.append("深市主板")
        # 新闻情绪（默认中间分）
        score += 5 + (int(code[-2:]) % 4)  # 5-8分差异化
        return min(score, 35), reasons

    try:
        raw_score, reasons = news_analyzer.score_news_and_sector(code, name, rsi=rsi)
        # news_analyzer 返回 0-30 分，按比例缩放到 0-35
        scaled = int(raw_score * 35 / 30)
        return min(scaled, 35), reasons
    except Exception as e:
        print(f"[WARN] 新闻行业评分失败 {code}: {e}")
        # 失败时用代码确定性给差异化基础分
        fallback = 10 + (int(code[-3:]) % 12)  # 10-21分
        return min(fallback, 30), ["行业情报评估中"]


def score_stock(code: str, name: str, current_price: float, change_pct: float,
                volume: int = 0, amount: float = 0, open_price: float = None,
                high_price: float = None, low_price: float = None,
                enable_deep_analysis: bool = True) -> Optional[Dict]:
    """
    多维度综合评分（v3.1）
    
    评分体系：
    ┌────────────────────────────────────────────────────────────────────┐
    │ 维度            │ 满分 │ 核心指标                                   │
    ├────────────────────────────────────────────────────────────────────┤
    │ 技术面           │  40  │ 布林带/KDJ/MACD/RSI/威廉/ATR/OBV/VWAP   │
    │ 基本面           │  25  │ PE/PB/ROE/PEG/股息率/成长性              │
    │ 行业情报         │  35  │ 行业热度+资金流+新闻情绪                  │
    └────────────────────────────────────────────────────────────────────┘
    """
    all_signals = []
    score_breakdown = {}
    detail_reasons = {}

    # ── 维度1：技术面（40分）──
    tech_score, tech_signals, tech_indicators = _score_technical(
        code, current_price, change_pct, volume, amount, open_price, high_price, low_price
    )
    score_breakdown["技术面"] = tech_score
    detail_reasons["技术面"] = tech_signals
    all_signals.extend(tech_signals[:3])

    # 从指标字典提取关键值（向后兼容）
    rsi_val = tech_indicators.get("rsi", 50.0)
    macd_val = tech_indicators.get("macd", 0.0)
    vol_ratio_val = tech_indicators.get("vol_ratio", 1.0)

    # ── 维度2：基本面（25分）──
    if enable_deep_analysis:
        fund_score, fund_signals = _score_fundamental_wrapper(code, name, current_price)
    else:
        fund_score = 10 + (int(code[-2:]) % 6)
        fund_signals = []
    score_breakdown["基本面"] = fund_score
    detail_reasons["基本面"] = fund_signals
    all_signals.extend(fund_signals[:2])

    # ── 维度3+4：新闻情报+行业热度+资金流（35分）──
    if enable_deep_analysis:
        news_score, news_signals = _score_news_sector_wrapper(code, name, rsi=rsi_val)
    else:
        news_score = 12 + (int(code[-2:]) % 8)
        news_signals = []
    score_breakdown["新闻行业"] = news_score
    detail_reasons["新闻行业"] = news_signals
    all_signals.extend(news_signals[:2])

    # ── 综合得分 ──
    total_score = tech_score + fund_score + news_score
    total_score = min(max(total_score, 0), 100)

    # ── 专业止损止盈计算（ATR动态方法）──
    hist_data = None
    if TUSHARE_AVAILABLE and enable_deep_analysis:
        try:
            hist_data = get_hist_data(code, days=30)
        except:
            pass

    if hist_data and ANALYSIS_MODULES_AVAILABLE:
        buy_price, stop_loss, take_profit = technical_analyzer.calc_dynamic_stop_loss(
            hist_data, current_price, total_score
        )
        # 安全校验：确保 stop_loss < buy_price < take_profit
        if stop_loss >= buy_price:
            stop_loss = round(buy_price * 0.95, 2)
        if take_profit <= buy_price:
            take_profit = round(buy_price * 1.12, 2)
    else:
        buy_price = round(current_price * 1.001, 2)
        # stop_loss 必须小于 buy_price（取5%止损，与 low_price 无关）
        if low_price and low_price > 0 and low_price < buy_price:
            # 取近期低点的97%，但不能超过买入价的95%
            stop_loss = round(min(low_price * 0.97, buy_price * 0.95), 2)
        else:
            stop_loss = round(buy_price * 0.95, 2)
        # 再次确保 stop_loss < buy_price
        if stop_loss >= buy_price:
            stop_loss = round(buy_price * 0.95, 2)
        if total_score >= 78:
            take_profit = round(buy_price * 1.20, 2)
        elif total_score >= 65:
            take_profit = round(buy_price * 1.15, 2)
        elif total_score >= 55:
            take_profit = round(buy_price * 1.10, 2)
        else:
            take_profit = round(buy_price * 1.08, 2)

    # ── 仓位管理（基于评分和风险评估 + 大盘环境限制）──
    stop_loss_pct = (buy_price - stop_loss) / buy_price if buy_price > 0 else 0.05

    if total_score >= 78:
        position_pct = min(0.18, 0.01 / max(stop_loss_pct, 0.01))
        position_pct = min(position_pct, 0.18)
        strategy_note = "强势股，分批建仓，目标20%+"
    elif total_score >= 65:
        position_pct = min(0.12, 0.008 / max(stop_loss_pct, 0.01))
        position_pct = min(position_pct, 0.12)
        strategy_note = "优质股，一次性建仓，目标15%"
    elif total_score >= 55:
        position_pct = 0.08
        strategy_note = "普通机会，轻仓参与，目标10%"
    else:
        position_pct = 0.05
        strategy_note = "观察仓位，谨慎参与，止损严格"

    # 大盘环境仓位限制（在score_stock中无法直接获取，由调用方调整）
    # 注意：此处不做限制，限制在 run_stock_scan 的 suggestions 构建时应用

    # ── 生成详情推荐理由文本 ──
    recommendation_detail = _build_recommendation_detail(
        code, name, current_price, change_pct, total_score,
        score_breakdown, detail_reasons, tech_indicators,
        rsi_val, macd_val, vol_ratio_val, amount,
        buy_price, stop_loss, take_profit, position_pct, strategy_note
    )

    return {
        "code": code,
        "name": name,
        "current_price": current_price,
        "change_pct": change_pct,
        "score": total_score,
        "score_breakdown": score_breakdown,
        "detail_reasons": detail_reasons,
        "recommendation_detail": recommendation_detail,
        "signals": all_signals[:5],
        "buy_price": buy_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_pct": position_pct,
        "strategy_note": strategy_note,
        "rsi": round(rsi_val, 1),
        "macd": round(macd_val, 4),
        "vol_ratio": round(vol_ratio_val, 2),
        "tech_indicators": tech_indicators,
    }


def _build_recommendation_detail(
    code: str, name: str, current_price: float, change_pct: float,
    total_score: int, score_breakdown: Dict, detail_reasons: Dict,
    tech_indicators: Dict,
    rsi: float, macd: float, vol_ratio: float, amount: float,
    buy_price: float, stop_loss: float, take_profit: float,
    position_pct: float, strategy_note: str
) -> Dict:
    """
    构建专业推荐报告（v4.0）
    整合所有技术指标和基本面信息，生成专业级分析报告
    """
    # 推荐等级
    if total_score >= 78:
        grade = "A+"
        grade_desc = "强烈推荐"
        grade_color = "#e63946"
    elif total_score >= 65:
        grade = "A"
        grade_desc = "推荐"
        grade_color = "#f79239"
    elif total_score >= 55:
        grade = "B"
        grade_desc = "关注"
        grade_color = "#f0a500"
    else:
        grade = "C"
        grade_desc = "观察"
        grade_color = "#8b949e"

    # 各维度数据
    tech_signals = detail_reasons.get("技术面", [])
    tech_score = score_breakdown.get("技术面", 0)
    fund_signals = detail_reasons.get("基本面", [])
    fund_score = score_breakdown.get("基本面", 0)
    news_signals = detail_reasons.get("新闻行业", [])
    news_score = score_breakdown.get("新闻行业", 0)

    # 行业前景
    industry_outlook = ""
    industry = "其他"
    if ANALYSIS_MODULES_AVAILABLE:
        try:
            industry = news_analyzer.get_stock_industry(code, name)
            industry_outlook = news_analyzer._get_industry_outlook(industry)
        except:
            pass

    # 专业技术指标摘要
    j_val = tech_indicators.get("j", 50)
    wr_val = tech_indicators.get("wr", -50)
    momentum = tech_indicators.get("momentum_10d", 0)
    atr_pct = tech_indicators.get("atr_pct", 0)
    boll_pos = tech_indicators.get("boll_position", 50)
    boll_width = tech_indicators.get("boll_width", 10)
    obv_trend = tech_indicators.get("obv_trend", "未知")
    ma20 = tech_indicators.get("ma20")
    ma60 = tech_indicators.get("ma60")
    vwap = tech_indicators.get("vwap")
    
    # 趋势判断
    trend_direction = _judge_trend_direction(tech_indicators, change_pct)
    
    # 风险提示
    risk_notes = []
    if rsi > 75:
        risk_notes.append(f"RSI={rsi:.0f}超买区间，短期有回调风险")
    elif rsi > 70:
        risk_notes.append(f"RSI={rsi:.0f}偏高，谨慎追高")
    if j_val > 90:
        risk_notes.append(f"KDJ-J={j_val:.0f}超买，注意短期回调")
    if change_pct > 7:
        risk_notes.append("今日涨幅较大，追高风险需注意，建议等待回踩")
    if change_pct < -5:
        risk_notes.append("今日跌幅较大，需确认止跌信号后再入场")
    stop_loss_pct_val = (buy_price - stop_loss) / buy_price * 100
    if stop_loss_pct_val > 7:
        risk_notes.append(f"止损空间{stop_loss_pct_val:.1f}%较大，建议控制仓位")
    if atr_pct > 4:
        risk_notes.append(f"ATR波动率{atr_pct:.1f}%较高，持仓须承受较大波动")
    if not risk_notes:
        risk_notes.append("当前无明显风险信号，注意跟踪市场变化")

    # 盈亏比计算
    profit_pct = (take_profit - buy_price) / buy_price * 100
    loss_pct = (buy_price - stop_loss) / buy_price * 100
    risk_reward = profit_pct / loss_pct if loss_pct > 0 else 0

    return {
        "grade": grade,
        "grade_desc": grade_desc,
        "grade_color": grade_color,
        "total_score": total_score,
        "trend_direction": trend_direction,
        "score_breakdown": score_breakdown,
        "technical": {
            "score": tech_score,
            "max_score": 40,
            "signals": tech_signals,
            # 核心指标
            "rsi": rsi,
            "macd": round(macd, 4),
            "kdj_k": tech_indicators.get("k", 50),
            "kdj_d": tech_indicators.get("d", 50),
            "kdj_j": j_val,
            "wr": wr_val,
            "vol_ratio": vol_ratio,
            "momentum_10d": momentum,
            "atr_pct": atr_pct,
            "boll_position": boll_pos,
            "boll_width": boll_width,
            "obv_trend": obv_trend,
            "ma20": ma20,
            "ma60": ma60,
            "vwap": vwap,
            "amount_yi": round(amount / 1e8, 2) if amount else 0,
            "summary": _summarize_technical_pro(tech_score, tech_signals, tech_indicators)
        },
        "fundamental": {
            "score": fund_score,
            "max_score": 25,
            "signals": fund_signals,
            "summary": _summarize_fundamental(fund_score, fund_signals)
        },
        "news_sector": {
            "score": news_score,
            "max_score": 35,
            "signals": news_signals,
            "industry": industry,
            "industry_outlook": industry_outlook,
            "summary": _summarize_news(news_score, news_signals)
        },
        "trade_plan": {
            "buy_price": buy_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position_pct": position_pct,
            "position_pct_display": f"{round(position_pct * 100)}%",
            "profit_target_pct": round(profit_pct, 1),
            "stop_loss_pct": round(loss_pct, 1),
            "risk_reward_ratio": round(risk_reward, 2),
            "strategy_note": strategy_note,
        },
        "risk_notes": risk_notes,
        "disclaimer": "以上分析仅供模拟学习参考，不构成真实投资建议。股市有风险，投资需谨慎。"
    }


def _judge_trend_direction(tech_indicators: Dict, change_pct: float) -> str:
    """判断趋势方向（专业视角）"""
    ma5 = tech_indicators.get("ma5")
    ma20 = tech_indicators.get("ma20")
    ma60 = tech_indicators.get("ma60")
    momentum = tech_indicators.get("momentum_10d", 0)
    macd = tech_indicators.get("macd", 0)
    rsi = tech_indicators.get("rsi", 50)
    
    bull_count = 0
    bear_count = 0
    
    if ma5 and ma20:
        if ma5 > ma20:
            bull_count += 2
        else:
            bear_count += 2
    
    if ma20 and ma60:
        if ma20 > ma60:
            bull_count += 1
        else:
            bear_count += 1
    
    if macd > 0:
        bull_count += 1
    else:
        bear_count += 1
    
    if momentum > 0:
        bull_count += 1
    elif momentum < -5:
        bear_count += 1
    
    if rsi > 55:
        bull_count += 1
    elif rsi < 45:
        bear_count += 1
    
    if bull_count >= 4:
        return "强势上涨趋势"
    elif bull_count >= 3:
        return "偏多震荡"
    elif bear_count >= 4:
        return "下降趋势"
    elif bear_count >= 3:
        return "偏空震荡"
    else:
        return "横盘整理"


def _summarize_technical(score: int, signals: List[str], rsi: float, macd: float, vol_ratio: float) -> str:
    """生成技术面总结文字（旧版兼容）"""
    if score >= 32:
        trend = "技术形态强势"
    elif score >= 22:
        trend = "技术面良好"
    elif score >= 14:
        trend = "技术面中性"
    else:
        trend = "技术面偏弱"
    
    parts = [trend]
    if signals:
        parts.append("主要信号：" + "、".join(signals[:3]))
    if rsi > 0:
        if rsi > 70:
            parts.append(f"RSI={rsi:.0f}偏高注意回调")
        elif rsi < 30:
            parts.append(f"RSI={rsi:.0f}超卖有反弹机会")
        else:
            parts.append(f"RSI={rsi:.0f}健康")
    if vol_ratio > 1.5:
        parts.append(f"量比{vol_ratio:.1f}倍放量")
    
    return "，".join(parts) + "。"


def _summarize_technical_pro(score: int, signals: List[str], tech_indicators: Dict) -> str:
    """生成专业技术面总结文字（v4.0）"""
    rsi = tech_indicators.get("rsi", 50)
    j = tech_indicators.get("j", 50)
    wr = tech_indicators.get("wr", -50)
    momentum = tech_indicators.get("momentum_10d", 0)
    boll_pos = tech_indicators.get("boll_position", 50)
    obv_trend = tech_indicators.get("obv_trend", "")
    vol_ratio = tech_indicators.get("vol_ratio", 1.0)
    
    if score >= 32:
        trend = "多指标共振，技术形态强势"
    elif score >= 24:
        trend = "技术面良好，趋势偏多"
    elif score >= 16:
        trend = "技术面中性，震荡整理"
    else:
        trend = "技术面偏弱，注意风险"
    
    key_parts = [trend]
    
    # 核心指标状态
    if rsi > 70:
        key_parts.append(f"RSI={rsi:.0f}超买")
    elif rsi < 35:
        key_parts.append(f"RSI={rsi:.0f}超卖反弹机会")
    else:
        key_parts.append(f"RSI={rsi:.0f}")
    
    if j < 20:
        key_parts.append(f"KDJ超卖(J={j:.0f})")
    elif j > 90:
        key_parts.append(f"KDJ超买(J={j:.0f})")
    
    if momentum > 8:
        key_parts.append(f"10日动量+{momentum:.1f}%上涨趋势")
    elif momentum < -8:
        key_parts.append(f"10日动量{momentum:.1f}%下跌趋势")
    
    if boll_pos < 20:
        key_parts.append("接近布林下轨超跌")
    elif boll_pos > 85:
        key_parts.append("接近布林上轨注意压力")
    
    if obv_trend == "上升" and vol_ratio > 1.5:
        key_parts.append("量价齐升主力积累")
    
    if signals:
        key_parts.append("信号：" + "、".join(signals[:2]))
    
    return "，".join(key_parts) + "。"


def _summarize_fundamental(score: int, signals: List[str]) -> str:
    """生成基本面总结文字"""
    if score >= 20:
        quality = "基本面优质"
    elif score >= 14:
        quality = "基本面良好"
    elif score >= 8:
        quality = "基本面一般"
    else:
        quality = "基本面较弱"
    
    if signals:
        key_points = [s for s in signals if not s.startswith("（") and "数据" not in s]
        if key_points:
            return quality + "，" + "，".join(key_points[:4]) + "。"
    
    return quality + "。（基本面数据参考行业规律评估）"


def _summarize_news(score: int, signals: List[str]) -> str:
    """生成新闻行业总结文字"""
    if score >= 28:
        sentiment = "行业热度极高，市场资金积极布局"
    elif score >= 20:
        sentiment = "行业处于活跃赛道，关注度较高"
    elif score >= 12:
        sentiment = "行业稳健，无明显利空"
    else:
        sentiment = "行业热度偏低，需等待催化剂"
    
    if signals:
        return sentiment + "。信息面：" + "；".join(signals[:3]) + "。"
    return sentiment + "。"


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
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始全市场扫描（多维度分析 v5.0）...")

    # ── 0. 大盘环境判断（v5.0 新增）──
    regime_info = None
    position_limit = 0.6
    score_threshold = 62  # 默认门槛提升到62，避免低质量股票进入推荐
    if ANALYSIS_MODULES_AVAILABLE:
        try:
            regime_info = market_regime_analyzer.analyze_market_regime()
            position_limit = regime_info.get("position_limit", 0.6)
            score_threshold = regime_info.get("score_threshold", 50)
            print(f"[大盘环境] {regime_info['regime']} | 仓位上限{position_limit*100:.0f}% | 评分门槛≥{score_threshold}")
            
            # 暴跌日：停止推荐
            if regime_info["regime"] == "暴跌":
                print("[大盘环境] 当前为暴跌环境，停止推荐新股票！")
                database.save_suggestions([])  # 清空旧推荐
                return {"suggestions": [], "skip_reason": "大盘暴跌", "skip_detail": "当前大盘处于暴跌环境，暂停推荐以规避风险"}
        except Exception as e:
            print(f"[WARN] 大盘环境判断失败: {e}")

    stock_list = get_stock_list()
    if not stock_list:
        print("[ERROR] 无法获取真实行情数据")
        database.save_suggestions([])  # 清空旧推荐
        return {"suggestions": [], "skip_reason": "数据获取失败", "skip_detail": "无法获取市场行情数据，请检查网络或稍后重试"}

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
            
            if result and result["score"] >= score_threshold and stock["code"] not in seen_result_codes:
                results.append(result)
                seen_result_codes.add(stock["code"])

    print(f"[INFO] 分析完成，共 {len(results)} 只股票评分 >= {score_threshold} 分")

    # ── 行业分散度控制（v5.0 新增）──
    if ANALYSIS_MODULES_AVAILABLE:
        try:
            results_before_diversity = len(results)
            results = portfolio_risk.apply_industry_diversification(results)
            if len(results) < results_before_diversity:
                print(f"[行业分散] {results_before_diversity} → {len(results)} 只（去除同行业重复）")
        except Exception as e:
            print(f"[WARN] 行业分散度控制失败: {e}")

    # ── 结果为空时：清空旧推荐，返回提示 ──
    if not results:
        print("[WARN] 没有股票满足当前评分门槛")
        database.save_suggestions([])  # 清空旧推荐
        return {"suggestions": [], "skip_reason": "无满足条件的股票", 
                "skip_detail": f"评分门槛 {score_threshold} 分（大盘{'弱势' if score_threshold > 50 else '震荡'}），无股票达标"}

    # ── 按评分严格排序（高分优先，同分之间小随机保证多样性）──
    for r in results:
        r["_sort_key"] = r["score"] + random.uniform(0, 1.5)
    results.sort(key=lambda x: x["_sort_key"], reverse=True)
    top = results[:top_n]
    for r in top:
        r.pop("_sort_key", None)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描完成，返回前 {len(top)} 只推荐")

    # ── 构建推荐列表 ──
    suggestions = []
    for r in top:
        account_value = 150000.0
        # 应用大盘环境仓位限制
        effective_position = min(r["position_pct"], position_limit)
        shares = int(account_value * effective_position / r["buy_price"] // 100 * 100)
        shares = max(shares, 100)
        cost = shares * r["buy_price"]

        # 格式化评分维度说明（添加到 signals）
        breakdown = r.get("score_breakdown", {})
        if breakdown:
            breakdown_str = " | ".join([f"{k}:{v}" for k, v in breakdown.items()])
            print(f"  [{r['name']}({r['code']})] 总分:{r['score']} ({breakdown_str})")

        # 新增：背离和时间因子信息
        tech_ind = r.get("tech_indicators", {})
        div_info = tech_ind.get("divergence", {})
        time_info = tech_ind.get("time_factors", {})
        
        # 风险标签
        risk_tags = []
        if div_info.get("macd_top"):
            risk_tags.append("MACD顶背离")
        if div_info.get("rsi_top"):
            risk_tags.append("RSI顶背离")
        if time_info.get("consecutive_red", 0) >= 3:
            risk_tags.append("连阴走势")
        if r.get("rsi", 50) > 80:
            risk_tags.append("RSI超买")
        
        # 机会标签
        opp_tags = []
        if div_info.get("macd_bottom"):
            opp_tags.append("MACD底背离")
        if div_info.get("rsi_bottom"):
            opp_tags.append("RSI底背离")
        if time_info.get("consecutive_green", 0) >= 3:
            opp_tags.append("连阳走势")
        if time_info.get("new_high_breakout"):
            opp_tags.append("突破新高")

        suggestions.append({
            **r,
            "position_pct": effective_position,  # 使用环境调整后的仓位
            "suggested_shares": shares,
            "estimated_cost": round(cost, 2),
            "action": "买入",
            "already_holding": False,
            "updated_at": datetime.now().isoformat(),
            # 新增元数据
            "market_regime": regime_info.get("regime", "震荡") if regime_info else "震荡",
            "risk_tags": risk_tags,
            "opportunity_tags": opp_tags,
        })

    # 保存到数据库
    database.save_suggestions(suggestions)
    return {"suggestions": suggestions, "skip_reason": None, 
            "summary": f"扫描完成，共推荐 {len(suggestions)} 只股票"}

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
                        new_price = price_map[code]["price"]
                        s["current_price"] = new_price
                        s["change_pct"] = price_map[code]["change_pct"]
                        # 先保存旧的买入价/止损/止盈，再更新
                        old_buy = float(s.get("buy_price") or new_price)
                        old_stop = float(s.get("stop_loss") or 0)
                        old_profit = float(s.get("take_profit") or 0)
                        # 同步刷新建议买入价（取实时价微涨0.2%）
                        new_buy_price = round(new_price * 1.002, 2)
                        s["buy_price"] = new_buy_price
                        # 按止损/止盈的相对比例同步更新（保持盈亏比不变）
                        if old_buy > 0 and old_stop > 0 and old_stop < old_buy:
                            stop_ratio = old_stop / old_buy  # 旧止损比例
                            s["stop_loss"] = round(new_buy_price * stop_ratio, 2)
                        else:
                            # 旧数据异常（止损>=买入），用5%止损重置
                            s["stop_loss"] = round(new_buy_price * 0.95, 2)
                        if old_buy > 0 and old_profit > 0 and old_profit > old_buy:
                            profit_ratio = old_profit / old_buy  # 旧止盈比例
                            s["take_profit"] = round(new_buy_price * profit_ratio, 2)
                        else:
                            # 旧数据异常，用12%止盈重置
                            s["take_profit"] = round(new_buy_price * 1.12, 2)
                        # 最终安全校验
                        if s.get("stop_loss", 0) >= new_buy_price:
                            s["stop_loss"] = round(new_buy_price * 0.95, 2)
                        if s.get("take_profit", 0) <= new_buy_price:
                            s["take_profit"] = round(new_buy_price * 1.12, 2)
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
    """获取用户账户快照（带实时价格 + 卖出建议）"""
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
                        high = float(str(row.get('high', '0')).strip())
                        low = float(str(row.get('low', '0')).strip())
                        if price > 0 and pre_close > 0:
                            real_prices[code] = {
                                "price": price,
                                "change_pct": round((price - pre_close) / pre_close * 100, 2),
                                "high": high if high > 0 else price,
                                "low": low if low > 0 else price,
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
            day_high = real_prices[code]["high"]
            day_low = real_prices[code]["low"]
        else:
            current_price = holding["avg_price"]  # 降级到成本价
            change_pct = 0
            day_high = current_price
            day_low = current_price

        market_value = holding["shares"] * current_price
        cost_value = holding["shares"] * holding["avg_price"]
        profit = market_value - cost_value
        profit_pct = profit / cost_value * 100 if cost_value > 0 else 0

        # ── 计算卖出建议（动态止损/目标价）──
        sell_advice = _calc_sell_advice(
            code, current_price, holding["avg_price"],
            day_high, day_low, change_pct
        )

        holdings_detail.append({
            "code": code,
            "name": holding["stock_name"],
            "shares": holding["shares"],
            "avg_price": holding["avg_price"],
            "current_price": current_price,
            "change_pct": change_pct,
            "market_value": round(market_value, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "sell_advice": sell_advice,
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


def _calc_sell_advice(code: str, current_price: float, avg_price: float,
                      day_high: float, day_low: float, change_pct: float) -> Dict:
    """
    计算持仓股票的卖出建议（动态止损/目标价/操作建议）

    策略：
    1. 优先用 ATR 动态止损（有历史数据时）
    2. 降级用基于持仓盈亏的阶梯止损法
    3. 给出明确的操作建议文字
    """
    hold_pct = (current_price - avg_price) / avg_price * 100 if avg_price > 0 else 0

    # ── 尝试 ATR 动态止损 ──
    atr_stop = None
    atr_target = None
    if TUSHARE_AVAILABLE and ANALYSIS_MODULES_AVAILABLE:
        try:
            hist = get_hist_data(code, days=30)
            if hist and len(hist) >= 20:
                _, _, indicators = technical_analyzer.score_technical_professional(
                    hist, current_price, change_pct, 0
                )
                atr_pct = indicators.get("atr_pct", 0)
                if atr_pct > 0:
                    # ATR 止损：现价下方 1.5×ATR
                    atr_stop = round(current_price * (1 - atr_pct * 1.5 / 100), 2)
                    # ATR 目标：现价上方 2.5×ATR
                    atr_target = round(current_price * (1 + atr_pct * 2.5 / 100), 2)
        except Exception:
            pass

    # ── 阶梯止损法（降级 / 补充）──
    if hold_pct >= 20:
        # 大赚：跟踪止损保住利润（回撤8%就卖）
        dynamic_stop = round(current_price * 0.92, 2)
        target_price = round(current_price * 1.15, 2)
        action = "持有观望"
        action_color = "#e63946"
        reason = f"盈利{hold_pct:.1f}%，跟踪止盈中，跌破{dynamic_stop:.2f}考虑止盈"
    elif hold_pct >= 10:
        # 中赚：5%跟踪止损
        dynamic_stop = round(current_price * 0.95, 2)
        target_price = round(current_price * 1.10, 2)
        action = "持有止盈"
        action_color = "#f79239"
        reason = f"盈利{hold_pct:.1f}%，可继续持有，跌破{dynamic_stop:.2f}止盈离场"
    elif hold_pct >= 5:
        # 小赚：回到成本价就平
        dynamic_stop = round(avg_price * 1.0, 2)
        target_price = round(avg_price * 1.10, 2)
        action = "持有"
        action_color = "#f0a500"
        reason = f"小幅盈利{hold_pct:.1f}%，回本线{dynamic_stop:.2f}为防守位"
    elif hold_pct >= -3:
        # 小亏：放宽止损，给反弹空间
        dynamic_stop = round(avg_price * 0.92, 2)
        target_price = round(avg_price * 1.08, 2)
        action = "持有观望"
        action_color = "#8b949e"
        reason = f"浮亏{abs(hold_pct):.1f}%，在{dynamic_stop:.2f}附近止损"
    elif hold_pct >= -7:
        # 中亏：严格止损
        dynamic_stop = round(avg_price * 0.93, 2)
        target_price = avg_price
        action = "考虑止损"
        action_color = "#2a9d8f"
        reason = f"浮亏{abs(hold_pct):.1f}%，建议关注{dynamic_stop:.2f}止损位"
    else:
        # 大亏：建议果断止损
        dynamic_stop = round(avg_price * 0.95, 2)
        target_price = avg_price
        action = "建议止损"
        action_color = "#e63946"
        reason = f"浮亏{abs(hold_pct):.1f}%，建议在{dynamic_stop:.2f}附近止损离场"

    # 如果 ATR 止损可用，优先使用
    if atr_stop is not None:
        # 取两者中更严格的止损
        final_stop = max(atr_stop, dynamic_stop) if hold_pct >= 0 else min(atr_stop, dynamic_stop)
        final_target = atr_target if atr_target and atr_target > current_price else target_price
    else:
        final_stop = dynamic_stop
        final_target = target_price

    # 确保安全关系
    if final_stop >= current_price:
        final_stop = round(current_price * 0.95, 2)
    if final_target <= current_price:
        final_target = round(current_price * 1.08, 2)

    # 盈亏比
    upside = (final_target - current_price) / current_price * 100
    downside = (current_price - final_stop) / current_price * 100
    rr_ratio = round(upside / downside, 2) if downside > 0 else 0

    return {
        "action": action,
        "action_color": action_color,
        "reason": reason,
        "stop_loss": final_stop,
        "target_price": final_target,
        "upside_pct": round(upside, 1),
        "downside_pct": round(downside, 1),
        "risk_reward": rr_ratio,
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

# ─────────────────────────────────────────────
# 股票查询功能
# ─────────────────────────────────────────────

def query_stock_score(keyword: str) -> Optional[Dict]:
    """
    查询任意股票的评分详情
    
    支持两种方式：
    1. 精确代码匹配（如 600519）
    2. 名称关键字搜索（如 茅台、比亚迪、宁德）
    
    覆盖范围：沪深两市全部约 5000+ 只上市股票
    """
    if not TUSHARE_AVAILABLE:
        return None

    keyword = keyword.strip()
    code = keyword.zfill(6) if keyword.isdigit() and len(keyword) <= 6 else ""

    # ── 步骤1：确定目标股票 ──
    target_code = None
    target_name = None
    target_price = None
    target_change_pct = None

    if code:
        # 精确代码查询
        target_name = get_stock_name(code)
        try:
            df = ts.get_realtime_quotes([code])
            if df is not None and not df.empty:
                row = df.iloc[0]
                price_str = str(row.get('price', '0')).strip()
                if price_str and price_str not in ('', '0', '0.00', 'nan'):
                    target_price = float(price_str)
                    pre_close = float(str(row.get('pre_close', '0')).strip())
                    target_change_pct = round((target_price - pre_close) / pre_close * 100, 2) if pre_close > 0 else 0
                    target_code = code
                    if not target_name:
                        target_name = str(row.get('name', '')).strip()
                else:
                    # 代码有效但当前未交易（停牌/退市），返回提示
                    name = target_name or str(row.get('name', '')).strip()
                    if name:
                        return {
                            "code": code,
                            "name": name,
                            "current_price": 0,
                            "change_pct": 0,
                            "score": 0,
                            "buy_price": 0,
                            "stop_loss": 0,
                            "take_profit": 0,
                            "query_type": "code",
                            "query_keyword": keyword,
                            "_inactive": True,
                            "inactive_reason": f"{name}({code}) 当前未交易或已停牌"
                        }
        except Exception as e:
            print(f"[WARN] 精确代码查询失败 {code}: {e}")

    if not target_code:
        # 名称关键字搜索
        matched = search_stock_by_name(keyword)
        if matched:
            target_code = matched[0]
            target_name = matched[1]

    if not target_code:
        return None

    # ── 步骤2：获取实时行情 ──
    if target_price is None:
        try:
            df = ts.get_realtime_quotes([target_code])
            if df is not None and not df.empty:
                row = df.iloc[0]
                price_str = str(row.get('price', '0')).strip()
                if price_str and price_str not in ('', '0', '0.00', 'nan'):
                    target_price = float(price_str)
                    pre_close = float(str(row.get('pre_close', '0')).strip())
                    target_change_pct = round((target_price - pre_close) / pre_close * 100, 2) if pre_close > 0 else 0
                    if not target_name:
                        target_name = str(row.get('name', '')).strip()
                else:
                    # 找到了但停牌
                    name = target_name or str(row.get('name', '')).strip()
                    if name:
                        return {
                            "code": target_code,
                            "name": name,
                            "current_price": 0,
                            "change_pct": 0,
                            "score": 0,
                            "buy_price": 0,
                            "stop_loss": 0,
                            "take_profit": 0,
                            "query_type": "name" if not code else "code",
                            "query_keyword": keyword,
                            "_inactive": True,
                            "inactive_reason": f"{name}({target_code}) 当前未交易或已停牌"
                        }
        except Exception as e:
            print(f"[WARN] 获取行情失败 {target_code}: {e}")

    if not target_price or target_price <= 0:
        return None

    # ── 步骤3：完整评分分析 ──
    try:
        result = score_stock(
            code=target_code,
            name=target_name or "未知",
            current_price=target_price,
            change_pct=target_change_pct or 0,
            enable_deep_analysis=ANALYSIS_MODULES_AVAILABLE
        )
        if result:
            result["query_type"] = "code" if code else "name"
            result["query_keyword"] = keyword
        return result
    except Exception as e:
        print(f"[ERROR] 评分分析失败 {target_code}: {e}")
        return None


def init_system():
    """初始化系统"""
    database.init_db()
    print("[系统] 数据库初始化完成")