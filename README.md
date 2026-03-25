# 📈 模拟炒股助手

一个基于量化策略的多用户股票模拟交易网站，支持全市场实时行情扫描、中线策略选股、模拟买卖交易。

## ✨ 功能特点

- **全市场扫描**：实时获取 A 股行情，智能筛选优质股票
- **中线策略**：基于均线、MACD、RSI、量比等多因子评分
- **多用户系统**：每个用户独立账户、持仓和交易记录
- **模拟交易**：支持买入/卖出，含佣金、印花税计算
- **实时推荐**：系统每30分钟自动扫描，推荐潜力股

## 🚀 快速部署

### 方法一：Railway（推荐，简单快速）
1. **Fork 到 GitHub**（右上角 Fork 按钮）
2. **注册 Railway**（https://railway.app，用 GitHub 登录）
3. **创建新项目** → "Deploy from GitHub repo"
4. **等待部署完成**（约2-3分钟）
5. **访问 Railway 分配的域名**

### 方法二：Render（免费但有休眠）
1. **Fork 到 GitHub**
2. **注册 Render**（https://render.com）
3. **创建 Web Service** → 连接 GitHub 仓库
4. **使用默认配置**（已提供 render.yaml）
5. **点击部署**

### 方法三：本地运行
```bash
# 1. 克隆项目
git clone https://github.com/你的用户名/stock-simulator.git
cd stock-simulator

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化数据库
cd stock_simulator
python3 -c "from database import init_db; init_db()"

# 4. 启动服务
cd ..
./start.sh  # 或: python3 -m stock_simulator.app_auth

# 5. 访问 http://localhost:5001
```

## ⚙️ 配置说明

### Tushare Pro API（可选）
为了获取真实股票行情，建议配置 Tushare Pro Token：
1. 访问 https://tushare.pro 注册
2. 获取 API Token
3. 在部署平台设置环境变量：`TUSHARE_TOKEN=你的token`

**没有 Token 也没关系**：系统会自动使用模拟数据，所有功能正常。

## 📊 技术架构

```
前端 (HTML/CSS/JS)
    ↓ HTTP
后端 (Flask + JWT)
    ↓ 业务逻辑
数据层 (SQLite)
    ↓ API 调用
行情数据 (Tushare Pro / 模拟数据)
```

### 主要文件说明
- `stock_simulator/app_auth.py` - Flask 主应用（多用户版）
- `stock_simulator/engine_db.py` - 选股引擎核心逻辑
- `stock_simulator/database.py` - SQLite 数据库操作
- `templates/login.html` - 登录/注册页面
- `templates/index_auth.html` - 主应用页面
- `requirements.txt` - Python 依赖包

## 🔧 开发与扩展

### 添加新策略
修改 `engine_db.py` 中的 `score_stock` 函数：
```python
# 添加新的评分规则
if some_condition:
    score += 10
    signals.append("新信号")
```

### 前端定制
- 主页面：`templates/index_auth.html`
- 样式：`templates/index_auth.html` 中的 `<style>` 部分
- JavaScript：页面底部的 `<script>` 部分

### 添加新 API
在 `app_auth.py` 中添加路由：
```python
@app.route("/api/your-endpoint")
@token_required
def your_endpoint(current_user_id):
    return jsonify({"success": True})
```

## 📱 使用指南

1. **注册账号**
   - 访问网站 → 点击"注册"
   - 输入用户名（3-20字符）和密码（至少6位）

2. **查看推荐**
   - 登录后自动显示今日推荐股票
   - 点击"手动扫描"立即更新推荐

3. **模拟交易**
   - 点击"买入"按钮，确认交易
   - 在"我的持仓"中查看持有的股票
   - 点击"卖出"按钮卖出股票

4. **查看记录**
   - "交易记录"页面显示所有买卖历史
   - 包含盈亏计算

## 🛡️ 安全与隐私

- 密码使用 SHA-256 加盐哈希存储
- 所有 API 请求需要 JWT Token
- 每个用户数据完全隔离
- 不收集任何个人信息

## ⚠️ 免责声明

**本项目仅供技术学习和模拟交易使用**：
- 不构成任何投资建议
- 股票数据可能延迟或不准确
- 模拟交易结果不代表真实投资表现
- 请勿用于真实投资决策

## 📄 许可证

MIT License - 详见 LICENSE 文件

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

## 📞 支持

如有问题，请：
1. 查看 `DEPLOYMENT.md` 中的故障排除
2. 检查部署平台的日志
3. 提交 GitHub Issue

---
**祝您投资愉快！** 🎯

> 提示：投资有风险，入市需谨慎。本工具仅用于学习和模拟。