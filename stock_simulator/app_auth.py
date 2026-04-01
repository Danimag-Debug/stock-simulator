"""
Flask 后端 API 服务 - 多用户版本
支持注册/登录/JWT鉴权，每个用户独立账户
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import threading
import logging
import jwt
import datetime
from functools import wraps

import database
from engine_db import (
    run_stock_scan, load_suggestions, get_portfolio_snapshot,
    execute_buy, execute_sell, load_trade_log, init_system,
    query_stock_score, search_stock_by_name
)

# 加载新模块
try:
    import market_regime_analyzer
    import alert_system
    import portfolio_risk
    NEW_MODULES_AVAILABLE = True
except ImportError:
    NEW_MODULES_AVAILABLE = False

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# JWT 配置
app.config['SECRET_KEY'] = 'stock-simulator-secret-key-change-in-production'
app.config['JWT_ALGORITHM'] = 'HS256'

# 定时扫描
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
scan_status = {"running": False, "last_run": None, "next_run": None}

def scheduled_scan():
    if scan_status["running"]:
        return
    scan_status["running"] = True
    scan_status.pop("last_error", None)
    scan_status.pop("skip_reason", None)
    scan_status.pop("skip_detail", None)
    scan_status.pop("summary", None)
    try:
        from datetime import datetime
        scan_status["last_run"] = datetime.now().isoformat()
        result = run_stock_scan(top_n=9)
        if isinstance(result, dict):
            if result.get("skip_reason"):
                scan_status["skip_reason"] = result["skip_reason"]
                scan_status["skip_detail"] = result.get("skip_detail", "")
            elif result.get("summary"):
                scan_status["summary"] = result["summary"]
    except Exception as e:
        scan_status["last_error"] = str(e)
    finally:
        scan_status["running"] = False

# 每30分钟扫描一次（交易时间内）
scheduler.add_job(
    scheduled_scan,
    "cron",
    day_of_week="mon-fri",
    hour="9-14",
    minute="0,30",
    id="stock_scan"
)
scheduler.start()

# 鉴权装饰器
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # 从请求头获取 token
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        
        if not token:
            return jsonify({"success": False, "message": "Token 缺失"}), 401
        
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=[app.config['JWT_ALGORITHM']])
            current_user_id = data['user_id']
        except jwt.ExpiredSignatureError:
            return jsonify({"success": False, "message": "Token 已过期"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"success": False, "message": "Token 无效"}), 401
        
        return f(current_user_id, *args, **kwargs)
    
    return decorated

# 生成 JWT token
def generate_token(user_id: int):
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=30)  # 30天有效期
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm=app.config['JWT_ALGORITHM'])

# ─────────────────────────────────────────────
# 公开路由（无需鉴权）
# ─────────────────────────────────────────────

@app.route("/")
def index():
    """主页面 - 直接返回主应用页面，鉴权由前端JS负责"""
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "templates"), "index_auth.html"
    )

@app.route("/login")
@app.route("/login.html")
def login_page():
    """登录页面"""
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "templates"), "login.html"
    )

@app.route("/api/auth/register", methods=["POST"])
def register():
    """用户注册"""
    data = request.json
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({"success": False, "message": "请提供用户名和密码"}), 400
    
    username = data['username'].strip()
    password = data['password']
    
    if len(username) < 3 or len(username) > 20:
        return jsonify({"success": False, "message": "用户名长度需在 3-20 字符之间"}), 400
    
    if len(password) < 6:
        return jsonify({"success": False, "message": "密码长度至少 6 位"}), 400
    
    user_id = database.create_user(username, password)
    if user_id is None:
        return jsonify({"success": False, "message": "用户名已存在"}), 400
    
    token = generate_token(user_id)
    return jsonify({
        "success": True,
        "message": "注册成功",
        "token": token,
        "user_id": user_id,
        "username": username
    })

@app.route("/api/auth/login", methods=["POST"])
def login():
    """用户登录"""
    data = request.json
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({"success": False, "message": "请提供用户名和密码"}), 400
    
    username = data['username'].strip()
    password = data['password']
    
    user_id = database.verify_user(username, password)
    if user_id is None:
        return jsonify({"success": False, "message": "用户名或密码错误"}), 401
    
    token = generate_token(user_id)
    return jsonify({
        "success": True,
        "message": "登录成功",
        "token": token,
        "user_id": user_id,
        "username": username
    })

@app.route("/api/auth/check", methods=["POST"])
def check_token():
    """验证 token"""
    token = None
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
    
    if not token:
        return jsonify({"success": False, "message": "Token 缺失"}), 401
    
    try:
        data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=[app.config['JWT_ALGORITHM']])
        user_id = data['user_id']
        
        # 验证用户是否存在
        conn = database.get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return jsonify({"success": False, "message": "用户不存在"}), 401
        
        return jsonify({
            "success": True,
            "message": "Token 有效",
            "user_id": user_id,
            "username": user["username"]
        })
    except jwt.ExpiredSignatureError:
        return jsonify({"success": False, "message": "Token 已过期"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"success": False, "message": "Token 无效"}), 401

# 全局推荐数据（无需登录，登录后可按个人资金量计算建议）
@app.route("/api/suggestions")
def get_suggestions():
    """获取推荐股票（全局数据）
    
    已登录用户：根据账户资金量重新计算每只股票的建议股数/预估成本
    未登录用户：使用默认 15 万元资金计算
    """
    try:
        data = load_suggestions()
        
        # 尝试从 Token 中获取用户 ID，按个人资金重新计算建议股数
        user_capital = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            try:
                token_data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=[app.config['JWT_ALGORITHM']])
                user_id = token_data.get('user_id')
                if user_id:
                    account = database.get_account(user_id)
                    # 用可用现金（而非 initial_cash）来计算实际可买入数量
                    user_capital = account.get("cash", 150000.0)
            except Exception:
                pass  # Token 无效或过期，忽略，使用默认值
        
        # 若获取到用户资金，动态重算每只推荐股票的建议股数
        if user_capital is not None and data.get("items"):
            for item in data["items"]:
                buy_price = float(item.get("buy_price") or item.get("current_price") or 1.0)
                position_pct = float(item.get("position_pct") or 0.08)
                if buy_price > 0:
                    raw_shares = int(user_capital * position_pct / buy_price // 100 * 100)
                    shares = max(raw_shares, 100)
                    item["suggested_shares"] = shares
                    item["estimated_cost"] = round(shares * buy_price, 2)
                    item["user_capital"] = round(user_capital, 2)
        
        return jsonify(data)
    except Exception as e:
        print(f"[ERROR] 获取推荐数据失败: {e}")
        return jsonify({
            "updated_at": None,
            "items": []
        })

@app.route("/api/scan/status")
def scan_status_api():
    """获取扫描状态"""
    return jsonify(scan_status)

# ─────────────────────────────────────────────
# 股票查询（需要登录）
# ─────────────────────────────────────────────

@app.route("/api/stock/query", methods=["GET"])
@token_required
def query_stock(current_user_id):
    """查询任意股票的评分详情
    
    参数：keyword - 股票代码（如 600519）或名称关键字（如 茅台）
    """
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify({"success": False, "message": "请输入股票代码或名称"}), 400
    
    if len(keyword) < 1 or len(keyword) > 20:
        return jsonify({"success": False, "message": "关键词长度需在 1-20 字符之间"}), 400
    
    try:
        result = query_stock_score(keyword)
        if result is None:
            return jsonify({"success": False, "message": f"未找到匹配 '{keyword}' 的股票，请检查代码或名称"})
        # 停牌股票返回提示
        if result.get("_inactive"):
            return jsonify({"success": False, "message": result.get("inactive_reason", "该股票当前未交易")})
        
        # 按用户资金计算建议买入股数（与推荐逻辑一致）
        try:
            import database as db
            conn = db.get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT cash FROM accounts WHERE user_id = ?", (current_user_id,))
            row = cursor.fetchone()
            if row:
                user_cash = row[0]
                buy_price = result.get("buy_price") or result.get("current_price", 0)
                position_pct = result.get("position_pct", 0.08)
                if buy_price > 0 and user_cash > 0:
                    shares = int(user_cash * position_pct / buy_price // 100 * 100)
                    shares = max(shares, 100)
                    result["suggested_shares"] = shares
                    result["estimated_cost"] = round(shares * buy_price, 2)
                    result["user_capital"] = user_cash
        except Exception as e:
            print(f"[WARN] 查询结果计算建议股数失败: {e}")
        
        return jsonify({"success": True, "data": result})
    except Exception as e:
        print(f"[ERROR] 股票查询失败: {e}")
        return jsonify({"success": False, "message": f"查询失败: {str(e)}"}), 500


@app.route("/api/stock/search", methods=["GET"])
@token_required
def search_stock(current_user_id):
    """模糊搜索股票（返回多个匹配结果列表）
    
    参数：keyword - 名称关键字（如 银行、新能源、半导体）
    返回：匹配的股票列表 [{code, name}, ...]（最多20个）
    """
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify({"success": False, "message": "请输入搜索关键字"}), 400
    if len(keyword) < 1 or len(keyword) > 20:
        return jsonify({"success": False, "message": "关键词长度需在 1-20 字符之间"}), 400

    try:
        from engine_db import _STOCK_NAME_CACHE, _load_stock_name_cache
        _load_stock_name_cache()

        if not _STOCK_NAME_CACHE:
            return jsonify({"success": False, "message": "股票数据库未就绪，请稍后再试"})

        # 精确匹配优先
        exact_matches = []
        partial_matches = []
        keyword_lower = keyword.lower()

        for code, name in _STOCK_NAME_CACHE.items():
            if keyword in name or keyword_lower in name.lower():
                # 精确：名称以关键字开头
                if name.startswith(keyword):
                    exact_matches.append({"code": code, "name": name})
                else:
                    partial_matches.append({"code": code, "name": name})

        results = exact_matches + partial_matches
        results = results[:50]  # 最多返回50个

        if not results:
            return jsonify({"success": False, "message": f"未找到包含 '{keyword}' 的股票"})

        return jsonify({"success": True, "data": results, "total": len(results)})
    except Exception as e:
        print(f"[ERROR] 股票搜索失败: {e}")
        return jsonify({"success": False, "message": f"搜索失败: {str(e)}"}), 500

# ─────────────────────────────────────────────
# 收藏功能（需要登录）
# ─────────────────────────────────────────────

@app.route("/api/watchlist", methods=["GET"])
@token_required
def get_watchlist(current_user_id):
    """获取用户收藏列表（附带实时行情）"""
    try:
        watchlist = database.get_watchlist(current_user_id)
        if not watchlist:
            return jsonify({"success": True, "data": [], "items": []})
        
        # 批量获取实时价格
        codes = [item["stock_code"] for item in watchlist]
        code_name_map = {item["stock_code"]: item["stock_name"] for item in watchlist}
        
        try:
            from engine_db import _STOCK_NAME_CACHE
            # 获取实时行情
            import tushare as ts
            df = ts.get_realtime_quotes(codes)
            if df is not None and len(df) > 0:
                price_map = {}
                for _, row in df.iterrows():
                    code = row["code"]
                    price_map[code] = {
                        "current_price": float(row["price"]),
                        "change_pct": round(float(row.get("change", 0)), 2),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "open": float(row.get("open", 0)),
                        "volume": float(row.get("volume", 0)),
                    }
                
                result = []
                for item in watchlist:
                    code = item["stock_code"]
                    info = price_map.get(code, {})
                    result.append({
                        "stock_code": code,
                        "stock_name": item["stock_name"],
                        "note": item.get("note", ""),
                        "created_at": item["created_at"],
                        "current_price": info.get("current_price", 0),
                        "change_pct": info.get("change_pct", 0),
                    })
            else:
                # 无行情数据，返回基本信息
                result = [{"stock_code": item["stock_code"], "stock_name": item["stock_name"],
                           "note": item.get("note", ""), "created_at": item["created_at"],
                           "current_price": 0, "change_pct": 0} for item in watchlist]
        except Exception as e:
            print(f"[ERROR] 获取收藏行情失败: {e}")
            result = [{"stock_code": item["stock_code"], "stock_name": item["stock_name"],
                       "note": item.get("note", ""), "created_at": item["created_at"],
                       "current_price": 0, "change_pct": 0} for item in watchlist]
        
        return jsonify({"success": True, "data": result, "items": result})
    except Exception as e:
        print(f"[ERROR] 获取收藏列表失败: {e}")
        return jsonify({"success": True, "data": [], "items": []})


@app.route("/api/watchlist", methods=["POST"])
@token_required
def add_watchlist(current_user_id):
    """添加收藏"""
    data = request.json
    if not data or 'code' not in data or 'name' not in data:
        return jsonify({"success": False, "message": "参数不全"}), 400
    
    result = database.add_watchlist(
        user_id=current_user_id,
        stock_code=data["code"],
        stock_name=data["name"],
        note=data.get("note", "")
    )
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code


@app.route("/api/watchlist", methods=["DELETE"])
@token_required
def remove_watchlist(current_user_id):
    """取消收藏"""
    data = request.json
    if not data or 'code' not in data:
        return jsonify({"success": False, "message": "参数不全"}), 400
    
    result = database.remove_watchlist(
        user_id=current_user_id,
        stock_code=data["code"]
    )
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code


@app.route("/api/watchlist/check", methods=["GET"])
@token_required
def check_watchlist(current_user_id):
    """检查股票是否已收藏（批量）"""
    codes_str = request.args.get("codes", "")
    if not codes_str:
        return jsonify({"success": True, "watched": {}})
    
    codes = [c.strip() for c in codes_str.split(",") if c.strip()]
    watched = {}
    for code in codes:
        watched[code] = database.is_in_watchlist(current_user_id, code)
    
    return jsonify({"success": True, "watched": watched})


# ─────────────────────────────────────────────
# 需要鉴权的路由（用户私有数据）
# ─────────────────────────────────────────────

@app.route("/api/portfolio", methods=["GET"])
@token_required
def get_portfolio(current_user_id):
    """获取用户持仓"""
    try:
        snapshot = get_portfolio_snapshot(current_user_id)
        return jsonify({"success": True, "data": snapshot})
    except Exception as e:
        account = database.get_account(current_user_id)
        return jsonify({
            "success": True,
            "data": {
                "cash": round(account["cash"], 2),
                "initial_cash": account["initial_cash"],
                "total_market_value": round(account["cash"], 2),
                "total_profit": 0,
                "total_profit_pct": 0,
                "holdings": [],
                "snapshot_time": None
            }
        })

@app.route("/api/trade/buy", methods=["POST"])
@token_required
def buy(current_user_id):
    """执行模拟买入"""
    data = request.json
    if not data or 'code' not in data or 'name' not in data or 'shares' not in data or 'price' not in data:
        return jsonify({"success": False, "message": "参数不全"}), 400
    
    result = execute_buy(
        user_id=current_user_id,
        code=data["code"],
        name=data["name"],
        shares=int(data["shares"]),
        price=float(data["price"])
    )
    return jsonify(result)

@app.route("/api/trade/sell", methods=["POST"])
@token_required
def sell(current_user_id):
    """执行模拟卖出"""
    data = request.json
    if not data or 'code' not in data or 'shares' not in data or 'price' not in data:
        return jsonify({"success": False, "message": "参数不全"}), 400
    
    result = execute_sell(
        user_id=current_user_id,
        code=data["code"],
        shares=int(data["shares"]),
        price=float(data["price"])
    )
    return jsonify(result)

@app.route("/api/logs", methods=["GET"])
@token_required
def get_logs(current_user_id):
    """获取用户交易记录"""
    logs = load_trade_log(current_user_id)
    return jsonify(logs)

@app.route("/api/account", methods=["GET"])
@token_required
def get_account_info(current_user_id):
    """获取用户账户信息"""
    account = database.get_account(current_user_id)
    return jsonify({
        "success": True,
        "data": {
            "cash": round(account["cash"], 2),
            "initial_cash": account["initial_cash"],
            "set_initial_cash": account.get("set_initial_cash", account["initial_cash"]),
            "total_profit": round(account["total_profit"], 2),
            "created_at": account["created_at"]
        }
    })


@app.route("/api/account/capital", methods=["PUT"])
@token_required
def set_capital(current_user_id):
    """设置/重置账户初始资金（须无持仓）"""
    data = request.json
    if not data or "capital" not in data:
        return jsonify({"success": False, "message": "请提供 capital 参数"}), 400
    
    try:
        capital = float(data["capital"])
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "capital 必须是数字"}), 400
    
    result = database.set_account_capital(current_user_id, capital)
    status_code = 200 if result["success"] else 400
    return jsonify(result), status_code

# ─────────────────────────────────────────────
# 市场环境 & 风控 API（公开/半公开）
# ─────────────────────────────────────────────

@app.route("/api/market/regime", methods=["GET"])
def get_market_regime():
    """获取当前大盘环境判断（公开接口）"""
    if not NEW_MODULES_AVAILABLE:
        return jsonify({"success": False, "message": "模块加载中"})
    try:
        regime = market_regime_analyzer.analyze_market_regime()
        return jsonify({"success": True, "data": regime})
    except Exception as e:
        print(f"[ERROR] 获取大盘环境失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/portfolio/alerts", methods=["GET"])
@token_required
def get_portfolio_alerts(current_user_id):
    """获取持仓调仓提醒（需要登录）"""
    if not NEW_MODULES_AVAILABLE:
        return jsonify({"success": True, "data": [], "items": []})
    
    try:
        holdings = database.get_holdings(current_user_id)
        if not holdings:
            return jsonify({"success": True, "data": [], "items": []})
        
        # 获取实时价格
        from engine_db import TUSHARE_AVAILABLE
        real_prices = {}
        if TUSHARE_AVAILABLE:
            try:
                import tushare as ts
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
                                    "change_pct": round((price - pre_close) / pre_close * 100, 2),
                                }
                        except (ValueError, TypeError):
                            continue
            except Exception:
                pass
        
        # 获取大盘环境
        regime = None
        try:
            regime = market_regime_analyzer.analyze_market_regime()
        except:
            pass
        
        # 生成提醒
        alerts = alert_system.check_holdings_alerts(holdings, real_prices, regime)
        
        return jsonify({
            "success": True,
            "data": alerts,
            "items": alerts,
            "has_danger": any(a["level"] == "danger" for a in alerts),
        })
    except Exception as e:
        print(f"[ERROR] 获取调仓提醒失败: {e}")
        return jsonify({"success": True, "data": [], "items": []})


@app.route("/api/portfolio/risk", methods=["GET"])
@token_required
def get_portfolio_risk(current_user_id):
    """获取持仓行业集中度风险评估（需要登录）"""
    if not NEW_MODULES_AVAILABLE:
        return jsonify({"success": False, "message": "模块加载中"})
    
    try:
        holdings = database.get_holdings(current_user_id)
        risk = portfolio_risk.evaluate_portfolio_risk(holdings)
        return jsonify({"success": True, "data": risk})
    except Exception as e:
        print(f"[ERROR] 获取风控评估失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ─────────────────────────────────────────────
# 管理功能（公开）
# ─────────────────────────────────────────────

@app.route("/api/scan/trigger", methods=["POST"])
def trigger_scan():
    """手动触发扫描"""
    if scan_status["running"]:
        return jsonify({"success": False, "message": "扫描正在进行中，请稍候"})

    # 先同步设置 running=True，再启动线程
    # 避免前端轮询时线程还未启动就误判为"已完成"
    scan_status["running"] = True
    scan_status.pop("last_error", None)
    scan_status.pop("skip_reason", None)
    scan_status.pop("skip_detail", None)
    scan_status.pop("summary", None)
    scan_status["scan_start"] = datetime.datetime.now().isoformat()

    def run():
        try:
            from engine_db import TUSHARE_AVAILABLE
            scan_status["_tushare"] = TUSHARE_AVAILABLE
            print(f"[扫描] 手动扫描线程启动，Tushare可用={TUSHARE_AVAILABLE}")
            result = run_stock_scan(top_n=9)
            # 处理新返回格式 {suggestions, skip_reason, skip_detail, summary}
            if isinstance(result, dict):
                if result.get("skip_reason"):
                    scan_status["skip_reason"] = result["skip_reason"]
                    scan_status["skip_detail"] = result.get("skip_detail", "")
                    print(f"[扫描] 扫描跳过: {result['skip_reason']} | {result.get('skip_detail', '')}")
                elif result.get("summary"):
                    scan_status["summary"] = result["summary"]
                    scan_status["last_run"] = datetime.datetime.now().isoformat()
                    print(f"[扫描] 扫描成功: {result['summary']}")
            elif isinstance(result, list):
                # 兼容旧格式
                scan_status["summary"] = f"扫描完成，推荐 {len(result)} 只股票"
                scan_status["last_run"] = datetime.datetime.now().isoformat()
                print(f"[扫描] 扫描完成（旧格式），推荐 {len(result)} 只")
            else:
                scan_status["skip_reason"] = "扫描返回异常"
                scan_status["skip_detail"] = f"返回类型: {type(result)}"
                print(f"[扫描] 扫描返回异常类型: {type(result)}")
        except Exception as e:
            import traceback
            print(f"[ERROR] 扫描失败: {e}")
            print(f"[ERROR] 异常堆栈:\n{traceback.format_exc()}")
            scan_status["last_error"] = str(e)
        finally:
            scan_status["running"] = False
            elapsed = (datetime.datetime.now() - datetime.datetime.fromisoformat(scan_status["scan_start"])).total_seconds()
            print(f"[扫描] 手动扫描线程结束，耗时 {elapsed:.1f} 秒")
            scan_status.pop("scan_start", None)
            scan_status.pop("_tushare", None)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"success": True, "message": "扫描已启动，预计1-3分钟完成"})

# 健康检查
@app.route("/api/health", methods=["GET"])
def health():
    """健康检查"""
    # 最简单的健康检查，确保服务正常
    return jsonify({"status": "ok", "service": "stock-simulator", "timestamp": datetime.datetime.now().isoformat()}), 200

# 系统初始化状态
_system_initialized = False

def initialize_system():
    """初始化系统（惰性初始化）"""
    global _system_initialized
    if not _system_initialized:
        print("[系统] 正在初始化...")
        try:
            init_system()
            _system_initialized = True
            print("[系统] 初始化完成")
        except Exception as e:
            print(f"[系统] 初始化失败: {e}")

# 在第一个请求前初始化
@app.before_request
def before_request():
    """在每个请求前检查并初始化系统"""
    initialize_system()

# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("启动多用户股票模拟服务器，端口 5001...")
    app.run(host="0.0.0.0", port=5001, debug=False)