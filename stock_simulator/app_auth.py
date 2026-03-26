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
    execute_buy, execute_sell, load_trade_log, init_system
)

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
    try:
        from datetime import datetime
        scan_status["last_run"] = datetime.now().isoformat()
        run_stock_scan(top_n=9)
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

# 全局推荐数据（无需登录）
@app.route("/api/suggestions")
def get_suggestions():
    """获取推荐股票（全局数据）"""
    try:
        data = load_suggestions()
        return jsonify(data)
    except Exception as e:
        # 如果真实数据获取失败，返回空数据
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
            "total_profit": round(account["total_profit"], 2),
            "created_at": account["created_at"]
        }
    })

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

    def run():
        try:
            run_stock_scan(top_n=9)
        except Exception as e:
            print(f"[ERROR] 扫描失败: {e}")
            scan_status["last_error"] = str(e)
        finally:
            scan_status["running"] = False

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