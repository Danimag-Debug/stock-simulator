"""
动态调仓提醒模块 v1.0
基于持仓状态和市场环境，主动生成调仓建议

提醒类型：
- 🔴 紧急：持仓跌破止损价 → 建议立即止损
- 🟡 警告：持仓达到目标价 → 建议考虑止盈
- 🟡 警告：RSI连续超买 → 建议减仓
- 🔴 紧急：大盘暴跌 → 检查所有持仓
- 🟡 警告：MACD死叉 → 趋势变弱
- 🟢 信息：支撑位附近 → 可能反弹

触发机制：
每次用户打开持仓页面时检查，也可由定时任务触发
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# 全局引用
_ts = None
_analyzer_available = False

def init_alert_system(ts_instance=None, analyzer_available=False):
    """初始化提醒系统"""
    global _ts, _analyzer_available
    _ts = ts_instance
    _analyzer_available = analyzer_available


def check_holdings_alerts(
    holdings: List[Dict],
    real_prices: Dict[str, Dict],
    market_regime: Optional[Dict] = None,
) -> List[Dict]:
    """
    检查持仓并生成调仓提醒
    
    参数:
        holdings: 用户持仓列表
        real_prices: 实时价格字典 {code: {price, change_pct, high, low}}
        market_regime: 大盘环境信息（可选）
    
    返回:
        提醒列表 [{type, level, code, name, message, action}]
    """
    alerts = []
    
    # 1. 大盘环境提醒
    if market_regime:
        regime = market_regime.get("regime", "震荡")
        if regime == "暴跌":
            alerts.append({
                "type": "market",
                "level": "danger",
                "code": "",
                "name": "大盘环境",
                "message": f"大盘暴跌 {market_regime.get('sh_change_pct', 0):+.1f}%，建议检查所有持仓止损",
                "action": "建议空仓观望",
            })
        elif regime == "弱势":
            alerts.append({
                "type": "market",
                "level": "warning",
                "code": "",
                "name": "大盘环境",
                "message": f"大盘偏弱，建议收紧止损，降低仓位",
                "action": "谨慎操作",
            })
    
    # 2. 逐个持仓检查
    for holding in holdings:
        code = holding["stock_code"]
        name = holding["stock_name"]
        shares = holding["shares"]
        avg_price = holding["avg_price"]
        
        if code not in real_prices:
            continue
        
        current = real_prices[code]
        price = current["price"]
        change_pct = current["change_pct"]
        
        if price <= 0:
            continue
        
        hold_pct = (price - avg_price) / avg_price * 100 if avg_price > 0 else 0
        
        # 2a. 止损检查：浮亏超过7%
        if hold_pct <= -7:
            alerts.append({
                "type": "stop_loss",
                "level": "danger",
                "code": code,
                "name": name,
                "message": f"{name}({code}) 浮亏 {abs(hold_pct):.1f}%，建议果断止损",
                "action": "建议止损",
            })
        elif hold_pct <= -5:
            alerts.append({
                "type": "stop_loss",
                "level": "warning",
                "code": code,
                "name": name,
                "message": f"{name}({code}) 浮亏 {abs(hold_pct):.1f}%，关注止损位",
                "action": "考虑止损",
            })
        
        # 2b. 止盈检查：浮盈超过15%
        if hold_pct >= 20:
            alerts.append({
                "type": "take_profit",
                "level": "warning",
                "code": code,
                "name": name,
                "message": f"{name}({code}) 盈利 {hold_pct:.1f}%，建议分批止盈锁定利润",
                "action": "分批止盈",
            })
        elif hold_pct >= 15:
            alerts.append({
                "type": "take_profit",
                "level": "info",
                "code": code,
                "name": name,
                "message": f"{name}({code}) 盈利 {hold_pct:.1f}%，可考虑减仓",
                "action": "考虑减仓",
            })
        
        # 2c. 涨跌幅异常检查
        if change_pct <= -5:
            alerts.append({
                "type": "price_drop",
                "level": "danger",
                "code": code,
                "name": name,
                "message": f"{name} 今日大跌 {abs(change_pct):.1f}%，注意风险",
                "action": "关注支撑位",
            })
        
        # 2d. 今日涨停（利好但追高风险）
        if change_pct >= 9.5:
            alerts.append({
                "type": "limit_up",
                "level": "info",
                "code": code,
                "name": name,
                "message": f"{name} 今日涨停 {change_pct:.1f}%，追高风险大",
                "action": "持有观望",
            })
    
    # 按紧急程度排序：danger > warning > info
    level_order = {"danger": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda x: level_order.get(x["level"], 3))
    
    return alerts
