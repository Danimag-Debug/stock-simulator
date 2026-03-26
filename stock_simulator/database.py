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

# 数据库路径 - Railway 使用持久化卷
# 优先使用环境变量指定的路径，否则使用当前目录
if os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
    # Railway 持久化卷路径
    DB_DIR = os.path.join(os.getenv("RAILWAY_VOLUME_MOUNT_PATH"), "data")
else:
    # 本地开发路径
    DB_DIR = os.path.join(os.path.dirname(__file__), "data")

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
        buy_price REAL NOT NULL,
        stop_loss REAL NOT NULL,
        take_profit REAL NOT NULL,
        position_pct REAL NOT NULL,
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
    
    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON accounts(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_user ON trade_logs(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_time ON suggestions(updated_at)")
    
    conn.commit()
    conn.close()
    print("[数据库] 初始化完成")

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
            "INSERT INTO accounts (user_id, cash, initial_cash) VALUES (?, ?, ?)",
            (user_id, 150000.0, 150000.0)
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
        "INSERT INTO accounts (user_id, cash, initial_cash) VALUES (?, ?, ?)",
        (user_id, 150000.0, 150000.0)
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

# 推荐管理
def save_suggestions(suggestions: List[Dict]):
    """保存推荐列表（覆盖旧的）"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 清空旧推荐
    cursor.execute("DELETE FROM suggestions")
    
    # 插入新推荐
    for s in suggestions:
        signals_json = json.dumps(s.get("signals", []), ensure_ascii=False)
        
        cursor.execute("""
            INSERT INTO suggestions 
            (stock_code, stock_name, current_price, change_pct, score, signals, 
             buy_price, stop_loss, take_profit, position_pct, rsi, macd, vol_ratio,
             suggested_shares, estimated_cost, action, already_holding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s["code"], s["name"], s["current_price"], s["change_pct"], s["score"],
            signals_json, s["buy_price"], s["stop_loss"], s["take_profit"],
            s["position_pct"], s.get("rsi"), s.get("macd"), s.get("vol_ratio"),
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
        row["signals"] = json.loads(row["signals"]) if row["signals"] else []
        row["already_holding"] = bool(row["already_holding"])
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