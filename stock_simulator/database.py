"""
SQLite 数据库层，用于多用户支持
Railway/Render 支持持久化卷，SQLite 是合适的选择
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Optional
import hashlib
import secrets

# ── 数据库路径配置 ──
# Railway 每次部署会销毁容器，所以数据库必须放在 Volume 上才能持久化。
#
# Railway Volume 挂载方式（二选一）：
#   方式1: Railway Dashboard → Service → Volumes → 创建卷 → 挂载到 /data
#   方式2: Railway Dashboard → Service → Volumes → 创建卷 → 挂载到 /volume
#
# 代码会自动检测以上挂载路径，无需手动设置环境变量。
# 本地开发时使用 stock_simulator/data/ 目录。

def _detect_db_dir() -> str:
    """自动检测持久化存储目录"""
    # 1. Railway Volume 标准挂载路径（按优先级检测）
    railway_paths = [
        "/data",           # Railway Dashboard 创建 Volume 时推荐的默认路径
        "/volume",         # Railway 另一种常见挂载路径
    ]
    for p in railway_paths:
        if os.path.isdir(p):
            print(f"[数据库] 检测到持久化卷: {p}")
            return p

    # 2. Railway 环境变量（兼容旧配置）
    volume_env = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "")
    if volume_env:
        print(f"[数据库] 使用 RAILWAY_VOLUME_MOUNT_PATH: {volume_env}")
        return volume_env

    # 3. Render 平台持久化路径
    if os.getenv("RENDER"):
        render_dir = "/opt/render/project/src/data"
        os.makedirs(render_dir, exist_ok=True)
        print(f"[数据库] Render 平台: {render_dir}")
        return render_dir

    # 4. 本地开发
    local_dir = os.path.join(os.path.dirname(__file__), "data")
    print(f"[数据库] 本地开发路径: {local_dir}")
    return local_dir


DB_DIR = _detect_db_dir()
DATABASE_PATH = os.path.join(DB_DIR, "stock_simulator.db")

def get_db():
    """获取数据库连接"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # 返回字典形式的结果
    return conn

def init_db():
    """初始化数据库表结构"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 用户表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 账户表（每个用户一个账户）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        cash REAL DEFAULT 150000.0,
        initial_cash REAL DEFAULT 150000.0,
        set_initial_cash REAL DEFAULT 150000.0,
        total_profit REAL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    """)
    
    # 持仓表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS holdings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        stock_code TEXT NOT NULL,
        stock_name TEXT NOT NULL,
        shares INTEGER NOT NULL,
        avg_price REAL NOT NULL,
        buy_price REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, stock_code),
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    """)
    
    # 交易记录表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trade_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        action TEXT NOT NULL,  -- '买入' / '卖出'
        stock_code TEXT NOT NULL,
        stock_name TEXT NOT NULL,
        shares INTEGER NOT NULL,
        price REAL NOT NULL,
        amount REAL NOT NULL,
        profit REAL,
        profit_pct REAL,
        commission REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    """)
    
    # 全局推荐表（所有用户共享的推荐结果）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_code TEXT NOT NULL,
        stock_name TEXT NOT NULL,
        current_price REAL NOT NULL,
        change_pct REAL NOT NULL,
        score INTEGER NOT NULL,
        signals TEXT,  -- JSON 数组
        score_breakdown TEXT,  -- JSON 对象，各维度评分明细
        detail_reasons TEXT,   -- JSON 对象，各维度详细理由
        recommendation_detail TEXT,  -- JSON 对象，完整推荐报告
        buy_price REAL NOT NULL,
        stop_loss REAL NOT NULL,
        take_profit REAL NOT NULL,
        position_pct REAL NOT NULL,
        strategy_note TEXT,
        rsi REAL,
        macd REAL,
        vol_ratio REAL,
        suggested_shares INTEGER NOT NULL,
        estimated_cost REAL NOT NULL,
        action TEXT NOT NULL,  -- '买入' / '加仓'
        already_holding BOOLEAN DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 自动迁移：为旧表添加缺失的列
    new_columns = [
        ("score_breakdown", "TEXT"),
        ("detail_reasons", "TEXT"),
        ("recommendation_detail", "TEXT"),
        ("strategy_note", "TEXT"),
    ]
    for col_name, col_type in new_columns:
        try:
            cursor.execute(f"ALTER TABLE suggestions ADD COLUMN {col_name} {col_type}")
            print(f"[数据库] 已为 suggestions 表添加 {col_name} 列")
        except Exception:
            pass  # 列已存在，忽略

    # 自动迁移：为 accounts 表添加 set_initial_cash 列
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN set_initial_cash REAL DEFAULT 150000.0")
        # 用现有 initial_cash 填充旧数据
        cursor.execute("UPDATE accounts SET set_initial_cash = initial_cash WHERE set_initial_cash IS NULL")
        print("[数据库] 已为 accounts 表添加 set_initial_cash 列")
    except Exception:
        pass  # 列已存在，忽略
    
    # 用户收藏表（每用户独立）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        stock_code TEXT NOT NULL,
        stock_name TEXT NOT NULL,
        note TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, stock_code),
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    """)

    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON accounts(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_user ON trade_logs(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_time ON suggestions(updated_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id)")
    
    conn.commit()
    conn.close()

    # 启动诊断：检查数据库是否已有数据
    _db_health_check()


def _db_health_check():
    """启动时打印数据库健康状态，便于排查持久化问题"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        user_count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        holding_count = cursor.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
        trade_count = cursor.execute("SELECT COUNT(*) FROM trade_logs").fetchone()[0]

        db_size_mb = os.path.getsize(DATABASE_PATH) / (1024 * 1024) if os.path.exists(DATABASE_PATH) else 0

        print(f"[数据库] ✅ 持久化正常 | 路径: {DATABASE_PATH}")
        print(f"[数据库]    用户: {user_count} | 持仓: {holding_count} | 交易记录: {trade_count} | 文件大小: {db_size_mb:.2f}MB")

        if user_count == 0 and os.getenv("RAILWAY_ENVIRONMENT"):
            print("[数据库] ⚠️  警告：数据库为空！如果这不是首次部署，说明 Volume 未正确挂载！")
            print("[数据库]    请在 Railway Dashboard → Service → Volumes 中创建卷并挂载到 /data")

        conn.close()
    except Exception as e:
        print(f"[数据库] ❌ 健康检查失败: {e}")

# 密码哈希函数
def hash_password(password: str) -> str:
    """使用 SHA-256 哈希密码（生产环境应该用 bcrypt/scrypt）"""
    salt = secrets.token_hex(16)
    return hashlib.sha256((password + salt).encode()).hexdigest() + ":" + salt

def verify_password(password: str, hashed_password: str) -> bool:
    """验证密码"""
    if ":" not in hashed_password:
        return False
    stored_hash, salt = hashed_password.split(":")
    return hashlib.sha256((password + salt).encode()).hexdigest() == stored_hash

# 用户管理
def create_user(username: str, password: str) -> Optional[int]:
    """创建新用户"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        password_hash = hash_password(password)
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash)
        )
        user_id = cursor.lastrowid
        
        # 创建对应的账户（使用15万元初始资金）
        cursor.execute(
            "INSERT INTO accounts (user_id, cash, initial_cash, set_initial_cash) VALUES (?, ?, ?, ?)",
            (user_id, 150000.0, 150000.0, 150000.0)
        )
        
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        # 用户名已存在
        return None
    finally:
        conn.close()

def get_user_by_username(username: str) -> Optional[Dict]:
    """根据用户名获取用户"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def verify_user(username: str, password: str) -> Optional[int]:
    """验证用户凭据"""
    user = get_user_by_username(username)
    if user and verify_password(password, user["password_hash"]):
        return user["id"]
    return None

# 账户管理
def get_account(user_id: int) -> Dict:
    """获取用户账户"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM accounts WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    
    # 如果账户不存在，创建新账户（使用15万元初始资金）
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO accounts (user_id, cash, initial_cash, set_initial_cash) VALUES (?, ?, ?, ?)",
        (user_id, 150000.0, 150000.0, 150000.0)
    )
    conn.commit()
    conn.close()
    
    # 重新获取
    return get_account(user_id)

def update_account(user_id: int, cash: float = None, total_profit: float = None):
    """更新用户账户"""
    conn = get_db()
    cursor = conn.cursor()
    
    updates = []
    params = []
    
    if cash is not None:
        updates.append("cash = ?")
        params.append(cash)
    
    if total_profit is not None:
        updates.append("total_profit = ?")
        params.append(total_profit)
    
    if updates:
        params.append(user_id)
        cursor.execute(
            f"UPDATE accounts SET {', '.join(updates)} WHERE user_id = ?",
            params
        )
        conn.commit()
    
    conn.close()


def set_account_capital(user_id: int, new_capital: float) -> Dict:
    """
    设置账户初始资金（仅在无持仓、全仓现金时允许重置）
    
    Args:
        user_id: 用户ID
        new_capital: 新的初始资金金额（1000 ~ 10,000,000）
    
    Returns:
        {"success": bool, "message": str}
    """
    if new_capital < 1000 or new_capital > 10_000_000:
        return {"success": False, "message": "初始资金须在 1,000 至 10,000,000 元之间"}
    
    # 检查是否有持仓
    holdings = get_holdings(user_id)
    if holdings:
        return {"success": False, "message": "账户有持仓时无法修改初始资金，请先卖出所有持仓"}
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """UPDATE accounts
               SET cash = ?, initial_cash = ?, set_initial_cash = ?, total_profit = 0
               WHERE user_id = ?""",
            (new_capital, new_capital, new_capital, user_id)
        )
        conn.commit()
        return {"success": True, "message": f"初始资金已更新为 ¥{new_capital:,.0f}"}
    except Exception as e:
        return {"success": False, "message": f"更新失败: {str(e)}"}
    finally:
        conn.close()

# 持仓管理
def get_holdings(user_id: int) -> List[Dict]:
    """获取用户持仓"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM holdings WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_holding(user_id: int, stock_code: str) -> Optional[Dict]:
    """获取用户特定股票的持仓"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM holdings WHERE user_id = ? AND stock_code = ?",
        (user_id, stock_code)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_holding(user_id: int, stock_code: str, stock_name: str, 
                   shares: int, avg_price: float, buy_price: float):
    """更新或创建持仓"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 检查是否已存在
    existing = get_holding(user_id, stock_code)
    
    if existing:
        # 更新现有持仓
        cursor.execute("""
            UPDATE holdings 
            SET shares = ?, avg_price = ?, buy_price = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND stock_code = ?
        """, (shares, avg_price, buy_price, user_id, stock_code))
    else:
        # 创建新持仓
        cursor.execute("""
            INSERT INTO holdings (user_id, stock_code, stock_name, shares, avg_price, buy_price)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, stock_code, stock_name, shares, avg_price, buy_price))
    
    conn.commit()
    conn.close()

def delete_holding(user_id: int, stock_code: str):
    """删除持仓（全部卖出后）"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM holdings WHERE user_id = ? AND stock_code = ?",
        (user_id, stock_code)
    )
    conn.commit()
    conn.close()

# 交易记录
def add_trade_log(user_id: int, action: str, stock_code: str, stock_name: str,
                  shares: int, price: float, amount: float, profit: float = None,
                  profit_pct: float = None, commission: float = 0):
    """添加交易记录"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO trade_logs 
        (user_id, action, stock_code, stock_name, shares, price, amount, profit, profit_pct, commission)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, action, stock_code, stock_name, shares, price, amount, profit, profit_pct, commission))
    
    conn.commit()
    conn.close()

def get_trade_logs(user_id: int, limit: int = 200) -> List[Dict]:
    """获取用户交易记录"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM trade_logs 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# 收藏管理
def add_watchlist(user_id: int, stock_code: str, stock_name: str, note: str = "") -> Dict:
    """添加股票到收藏"""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, stock_code, stock_name, note) VALUES (?, ?, ?, ?)",
            (user_id, stock_code, stock_name, note)
        )
        conn.commit()
        if cursor.rowcount > 0:
            return {"success": True, "message": f"已收藏 {stock_name}"}
        else:
            return {"success": False, "message": f"{stock_name} 已在收藏中"}
    except Exception as e:
        return {"success": False, "message": f"收藏失败: {str(e)}"}
    finally:
        conn.close()

def remove_watchlist(user_id: int, stock_code: str) -> Dict:
    """取消收藏"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND stock_code = ?",
        (user_id, stock_code)
    )
    conn.commit()
    deleted = cursor.rowcount
    conn.close()
    if deleted > 0:
        return {"success": True, "message": "已取消收藏"}
    else:
        return {"success": False, "message": "该股票未在收藏中"}

def get_watchlist(user_id: int) -> List[Dict]:
    """获取用户收藏列表"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM watchlist WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def is_in_watchlist(user_id: int, stock_code: str) -> bool:
    """检查股票是否已收藏"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM watchlist WHERE user_id = ? AND stock_code = ?",
        (user_id, stock_code)
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None

# 推荐管理
def save_suggestions(suggestions: List[Dict]):
    """保存推荐列表（覆盖旧的，去重保证唯一性）"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 清空旧推荐
    cursor.execute("DELETE FROM suggestions")
    
    # 先去重：同一只股票只保留第一条（按评分排序后的顺序）
    seen_codes = set()
    deduped = []
    for s in suggestions:
        code = s.get("code") or s.get("stock_code", "")
        if code and code not in seen_codes:
            seen_codes.add(code)
            deduped.append(s)
    
    print(f"[INFO] save_suggestions: {len(suggestions)} -> {len(deduped)} (去重)")
    
    # 插入去重后的推荐
    for s in deduped:
        signals_json = json.dumps(s.get("signals", []), ensure_ascii=False)
        breakdown_json = json.dumps(s.get("score_breakdown", {}), ensure_ascii=False)
        detail_reasons_json = json.dumps(s.get("detail_reasons", {}), ensure_ascii=False)
        recommendation_detail_json = json.dumps(s.get("recommendation_detail", {}), ensure_ascii=False)
        
        cursor.execute("""
            INSERT INTO suggestions 
            (stock_code, stock_name, current_price, change_pct, score, signals, score_breakdown,
             detail_reasons, recommendation_detail,
             buy_price, stop_loss, take_profit, position_pct, strategy_note,
             rsi, macd, vol_ratio,
             suggested_shares, estimated_cost, action, already_holding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s["code"], s["name"], s["current_price"], s["change_pct"], s["score"],
            signals_json, breakdown_json, detail_reasons_json, recommendation_detail_json,
            s["buy_price"], s["stop_loss"], s["take_profit"],
            s["position_pct"], s.get("strategy_note", ""),
            s.get("rsi"), s.get("macd"), s.get("vol_ratio"),
            s["suggested_shares"], s["estimated_cost"], s["action"], 
            int(s.get("already_holding", False))
        ))
    
    conn.commit()
    conn.close()

def load_suggestions() -> List[Dict]:
    """加载最新推荐列表"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取最新的 9 条推荐
    cursor.execute("""
        SELECT * FROM suggestions 
        ORDER BY updated_at DESC 
        LIMIT 9
    """)
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in dict_rows(rows):
        row["signals"] = json.loads(row["signals"]) if row.get("signals") else []
        row["score_breakdown"] = json.loads(row["score_breakdown"]) if row.get("score_breakdown") else {}
        row["detail_reasons"] = json.loads(row["detail_reasons"]) if row.get("detail_reasons") else {}
        row["recommendation_detail"] = json.loads(row["recommendation_detail"]) if row.get("recommendation_detail") else {}
        row["already_holding"] = bool(row.get("already_holding", 0))
        # 字段名映射：前端使用 code/name，数据库存的是 stock_code/stock_name
        row["code"] = row.get("stock_code", "")
        row["name"] = row.get("stock_name", "")
        result.append(row)
    
    return result

def get_suggestions_updated_at() -> Optional[str]:
    """获取推荐最后更新时间"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT updated_at FROM suggestions ORDER BY updated_at DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row["updated_at"] if row else None

# 辅助函数
def dict_rows(rows):
    """将 sqlite3.Row 对象转换为字典列表"""
    return [dict(row) for row in rows]

# 初始化数据库
if __name__ == "__main__":
    init_db()
    print("数据库初始化完成")