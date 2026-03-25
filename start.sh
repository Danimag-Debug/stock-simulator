#!/bin/bash
# 启动脚本，用于本地开发和部署

echo "初始化股票模拟系统..."

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "错误：未找到 Python3，请先安装 Python 3.8+"
    exit 1
fi

# 检查依赖
echo "检查依赖..."
pip install -r requirements.txt

# 初始化数据库
echo "初始化数据库..."
cd stock_simulator
python3 -c "
from database import init_db
init_db()
print('数据库初始化完成')
"

# 启动服务
echo "启动服务..."
if [[ -z "$PORT" ]]; then
    PORT=5001
fi

echo "服务器将在 http://localhost:$PORT 启动"
echo "按 Ctrl+C 停止服务"
echo ""
echo "访问地址："
echo "  - 主页面: http://localhost:$PORT"
echo "  - API 健康检查: http://localhost:$PORT/api/health"
echo "  - 登录页面: http://localhost:$PORT/login.html"
echo ""
echo "首次使用请先注册账号"

gunicorn app_auth:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120