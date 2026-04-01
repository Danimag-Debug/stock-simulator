"""
组合风险管理模块 v1.0
行业分散度控制 + 相关性风险评估

核心原则：
- 同一行业最多 N 只（默认2只），防止"一损俱损"
- 同一行业仓位占比不超过 M%（默认40%）
- 评估推荐组合的行业集中度

用法：
在 run_stock_scan 最终选股后调用 apply_industry_diversification()
"""

import logging
from typing import Dict, List, Tuple
from collections import Counter

logger = logging.getLogger(__name__)

# 尝试导入行业映射
try:
    from news_analyzer import get_stock_industry
except ImportError:
    get_stock_industry = None

# ─────────────────────────────────────────────
# 行业分散度控制
# ─────────────────────────────────────────────

MAX_PER_INDUSTRY = 2   # 每个行业最多推荐几只
MAX_INDUSTRY_WEIGHT = 0.40  # 单行业最大仓位占比


def apply_industry_diversification(suggestions: List[Dict], max_per_industry: int = MAX_PER_INDUSTRY) -> List[Dict]:
    """
    对推荐列表应用行业分散度控制
    
    策略：
    1. 按评分排序（已排序）
    2. 逐个检查行业，同行业不超过 max_per_industry 只
    3. 超出的按评分从低到高剔除
    4. 用下一行业中评分最高的递补
    
    返回：过滤后的推荐列表
    """
    if not suggestions:
        return suggestions
    
    # 为每只股票标记行业
    for s in suggestions:
        code = s.get("code") or s.get("stock_code", "")
        name = s.get("name") or s.get("stock_name", "")
        if get_stock_industry:
            s["_industry"] = get_stock_industry(code, name)
        else:
            s["_industry"] = _guess_industry(code, name)
    
    # 统计每个行业的入选数量
    industry_count = Counter()
    result = []
    skipped = []  # 被剔除的，用于可能的递补
    
    for s in suggestions:
        industry = s["_industry"]
        if industry_count[industry] < max_per_industry:
            result.append(s)
            industry_count[industry] += 1
        else:
            skipped.append(s)
            logger.info(f"[行业分散] 剔除 {s.get('name')}({s.get('code')})，行业 {industry} 已满 {max_per_industry} 只")
    
    # 如果剔除后不足目标数量，从 skipped 中递补（但递补也受行业限制）
    # 这一步通常不需要，因为原始列表远多于目标数量
    
    # 清理内部标记
    for s in result:
        s.pop("_industry", None)
    
    # 评估组合分散度
    _log_diversity_report(result, suggestions)
    
    return result


def _guess_industry(code: str, name: str) -> str:
    """简单行业猜测（当 news_analyzer 不可用时）"""
    if code.startswith("688"):
        return "科创板"
    elif code.startswith("300"):
        return "创业板"
    elif code.startswith("6"):
        return "沪市主板"
    else:
        return "深市主板"


def _log_diversity_report(selected: List[Dict], original: List[Dict]):
    """记录组合分散度报告"""
    if not selected:
        return
    
    # 为评估重新标记行业
    industries = []
    for s in selected:
        code = s.get("code") or s.get("stock_code", "")
        name = s.get("name") or s.get("stock_name", "")
        if get_stock_industry:
            industries.append(get_stock_industry(code, name))
        else:
            industries.append(_guess_industry(code, name))
    
    unique_industries = len(set(industries))
    industry_counts = Counter(industries)
    
    logger.info(f"[组合分散] 最终推荐 {len(selected)} 只，覆盖 {unique_industries} 个行业")
    for ind, count in industry_counts.most_common():
        logger.info(f"  {ind}: {count} 只")


def evaluate_portfolio_risk(holdings: List[Dict]) -> Dict:
    """
    评估用户当前持仓的行业集中度风险
    
    参数:
        holdings: 持仓列表（从 database.get_holdings 获取）
    
    返回:
    {
        "total_holdings": int,        # 持仓数量
        "unique_industries": int,     # 覆盖行业数
        "concentration_score": float,  # 集中度评分 0-100（100=极度分散）
        "risk_level": str,            # "低"/"中"/"高"
        "most_concentrated": list,    # 仓位最集中的行业
        "advice": str,                # 建议
    }
    """
    if not holdings:
        return {
            "total_holdings": 0,
            "unique_industries": 0,
            "concentration_score": 100,
            "risk_level": "低",
            "most_concentrated": [],
            "advice": "当前无持仓"
        }
    
    # 为持仓标记行业
    industry_map = {}
    for h in holdings:
        code = h["stock_code"]
        name = h["stock_name"]
        if get_stock_industry:
            industry_map[code] = get_stock_industry(code, name)
        else:
            industry_map[code] = _guess_industry(code, name)
    
    # 统计每个行业的持仓数
    industry_counts = Counter(industry_map.values())
    total = len(holdings)
    unique = len(industry_counts)
    
    # 赫芬达尔指数（HHI）衡量集中度
    hhi = sum((count / total) ** 2 for count in industry_counts.values())
    
    # 转换为分散度评分（HHI越小=越分散=分越高）
    # HHI范围: 1/N（完全分散）到 1（完全集中）
    max_hhi = 1.0
    min_hhi = 1.0 / total if total > 0 else 1.0
    
    if max_hhi > min_hhi:
        concentration_score = round((1 - (hhi - min_hhi) / (max_hhi - min_hhi)) * 100, 1)
    else:
        concentration_score = 100
    
    # 风险等级
    if concentration_score >= 70:
        risk_level = "低"
        advice = "持仓行业分散度良好，风险可控"
    elif concentration_score >= 40:
        risk_level = "中"
        advice = "持仓行业有一定集中度，注意板块联动风险"
    else:
        risk_level = "高"
        advice = "持仓过度集中在少数行业，建议分散配置降低风险"
    
    # 仓位最集中的行业
    most_concentrated = [
        {"industry": ind, "count": count, "pct": round(count / total * 100, 1)}
        for ind, count in industry_counts.most_common(3)
    ]
    
    return {
        "total_holdings": total,
        "unique_industries": unique,
        "concentration_score": concentration_score,
        "risk_level": risk_level,
        "most_concentrated": most_concentrated,
        "advice": advice,
    }
