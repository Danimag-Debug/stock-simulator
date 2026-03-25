"""
Flask 后端 API 服务
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from engine import (
    run_stock_scan, load_suggestions, get_portfolio_snapshot,
    execute_buy, execute_sell, load_trade_log, load_account
)
import threading
import logging

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
scan_status = {"running": False, "last_run": None, "next_run": None}


def scheduled_scan():
    if scan_status["running"]:
        return
    scan_status["running"] = True
    try:
        from datetime import datetime
        scan_status["last_run"] = datetime.now().isoformat()
        run_stock_scan(top_n=5)
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


@app.route("/")
def index():
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), "templates"), "index.html"
    )


@app.route("/api/suggestions")
def get_suggestions():
    data = load_suggestions()
    return jsonify(data)


@app.route("/api/portfolio")
def get_portfolio():
    try:
        snapshot = get_portfolio_snapshot()
        return jsonify({"success": True, "data": snapshot})
    except Exception as e:
        account = load_account()
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
def buy():
    data = request.json
    result = execute_buy(
        code=data["code"],
        name=data["name"],
        shares=int(data["shares"]),
        price=float(data["price"])
    )
    return jsonify(result)


@app.route("/api/trade/sell", methods=["POST"])
def sell():
    data = request.json
    result = execute_sell(
        code=data["code"],
        shares=int(data["shares"]),
        price=float(data["price"])
    )
    return jsonify(result)


@app.route("/api/logs")
def get_logs():
    logs = load_trade_log()
    return jsonify(logs)


@app.route("/api/scan/trigger", methods=["POST"])
def trigger_scan():
    """手动触发扫描"""
    if scan_status["running"]:
        return jsonify({"success": False, "message": "扫描正在进行中，请稍候"})

    def run():
        scan_status["running"] = True
        try:
            run_stock_scan(top_n=5)
        finally:
            scan_status["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"success": True, "message": "扫描已启动，预计1-3分钟完成"})


@app.route("/api/scan/status")
def scan_status_api():
    return jsonify(scan_status)


if __name__ == "__main__":
    print("启动模拟炒股服务器，端口 5001...")
    app.run(host="0.0.0.0", port=5001, debug=False)
