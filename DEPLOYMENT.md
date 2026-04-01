# 模拟炒股助手 - 部署指南

## 项目简介
这是一个基于量化策略的股票模拟交易网站，支持：
- 全市场实时行情扫描
- 中线策略（均线、MACD、RSI、量比）选股评分
- 多用户账户系统（独立持仓和交易记录）
- 模拟买卖交易（含佣金、印花税）

## 技术栈
- **后端**: Flask + SQLite + JWT
- **前端**: HTML + CSS + JavaScript
- **数据**: Tushare Pro API（A股实时行情）
- **部署**: Railway / Render（免费云平台）

## 部署选项

### 选项一：Railway（推荐）
Railway 提供免费的 PostgreSQL 和简单易用的部署流程。

#### 步骤：
1. **Fork 项目到 GitHub**
   - 访问 https://github.com 创建新仓库
   - 将代码推送到 GitHub

2. **注册 Railway**
   - 访问 https://railway.app 用 GitHub 登录
   - 点击 "New Project" → "Deploy from GitHub repo"

3. **配置 Volume（数据持久化 — 必须！）**
   - Railway 每次部署会销毁容器，数据库文件会丢失
   - 必须挂载 Volume 才能保存用户数据和持仓：
   - Railway Dashboard → 你的 Service → **Volumes** 标签 → **Create Volume**
   - **Mount Path 填写**: `/data`
   - 保存后 Railway 会自动重启服务

4. **配置环境变量**
   - 在 Railway Dashboard → Project → Variables 添加：
     ```
     TUSHARE_TOKEN=你的Tushare Pro Token（可选）
     PORT=8000
     ```
   - 如果没有 Tushare Token，系统将使用模拟数据

5. **等待部署完成**
   - Railway 会自动检测 requirements.txt 并构建
   - 构建完成后会显示访问 URL

6. **验证数据持久化**
   - 部署完成后查看 Railway 部署日志
   - 如果看到 `[数据库] ✅ 持久化正常 | 路径: /data/stock_simulator.db` 说明 Volume 已生效
   - 如果看到 `⚠️ 警告：数据库为空！` 说明 Volume 未挂载，需要回到步骤 3

#### Railway 免费套餐限制：
- 每月 $5 额度（足够小型应用）
- 512MB RAM
- 持续运行（不休眠）
- 免费 PostgreSQL 数据库（项目使用 SQLite，更简单）

### 选项二：Render
Render 提供免费 Web 服务和自动 SSL。

#### 步骤：
1. **Fork 到 GitHub**（同上）

2. **注册 Render**
   - 访问 https://render.com 用 GitHub 登录

3. **创建 Web Service**
   - 点击 "New" → "Web Service"
   - 连接 GitHub 仓库
   - 配置：
     - **Runtime**: Python 3
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `gunicorn stock_simulator.app_auth:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
     - **Environment Variables**:
       - `TUSHARE_TOKEN`: 你的Tushare Token（可选）
       - `PYTHON_VERSION`: `3.11.0`

4. **部署**
   - 点击 "Create Web Service"
   - Render 会自动部署

5. **访问网站**
   - 部署完成后会显示类似 `https://your-app.onrender.com` 的 URL

#### Render 免费套餐限制：
- 512MB RAM
- 静态出站 IP
- 自动休眠（15分钟无请求后休眠，唤醒需30秒）
- 每月750小时运行时间（约31天）

### 选项三：本地开发
适合在个人电脑上测试和开发。

#### 步骤：
1. **安装依赖**
   ```bash
   # 确保有 Python 3.8+
   python3 --version
   
   # 安装依赖
   pip install -r requirements.txt
   ```

2. **初始化数据库**
   ```bash
   cd stock_simulator
   python3 -c "from database import init_db; init_db()"
   ```

3. **启动服务器**
   ```bash
   # 方法一：使用启动脚本（推荐）
   ./start.sh
   
   # 方法二：直接运行
   python3 -m stock_simulator.app_auth
   
   # 方法三：使用 gunicorn（生产模式）
   gunicorn stock_simulator.app_auth:app --bind 0.0.0.0:5001 --workers 2
   ```

4. **访问**
   - 打开浏览器访问 http://localhost:5001
   - 首次使用请先注册账号

## 配置 Tushare Pro API（可选但推荐）

为了获取真实的股票行情数据，建议配置 Tushare Pro API：

1. **注册 Tushare Pro**
   - 访问 https://tushare.pro 注册账号
   - 免费用户每天有 500 次 API 调用额度

2. **获取 Token**
   - 登录后，在个人中心获取 API Token
   - Token 格式类似：`ef4c06eabc39dbf6386a32c6135e68f84ed08b55c524e23ae0931068`

3. **配置环境变量**
   - **Railway**: 在 Variables 添加 `TUSHARE_TOKEN`
   - **Render**: 在 Environment Variables 添加 `TUSHARE_TOKEN`
   - **本地**: 创建 `.env` 文件或在启动时设置：
     ```bash
     export TUSHARE_TOKEN=你的token
     ```

4. **没有 Token 会怎样？**
   - 系统自动使用模拟数据
   - 股票价格随机生成
   - 功能完全正常，只是数据不真实

## 功能验证

部署成功后，请验证以下功能：

1. **注册和登录**
   - 访问 `/login.html` 注册新账号
   - 登录后应看到用户头像和用户名

2. **股票推荐**
   - 系统会自动扫描全市场股票
   - 推荐页面应显示5只评分最高的股票

3. **模拟交易**
   - 点击"买入"按钮，输入数量
   - 确认后应看到成功提示
   - 持仓页面应显示买入的股票

4. **API 健康检查**
   - 访问 `/api/health` 应返回 `{"status": "ok"}`

## 故障排除

### 常见问题：

1. **部署失败，提示依赖错误**
   ```bash
   # 确保 requirements.txt 格式正确
   # 尝试简化依赖：
   Flask==2.3.3
   gunicorn==21.2.0
   ```

2. **数据库初始化失败**
   - 检查 `/stock_simulator/data/` 目录是否可写
   - 在 Railway/Render 需要确保有持久化存储

3. **无法获取股票行情**
   - 检查 Tushare Token 是否正确
   - 如果没有 Token，系统会自动使用模拟数据

4. **网站访问慢（Render 免费版）**
   - Render 免费版会在15分钟无请求后休眠
   - 首次访问需要30秒唤醒时间
   - 考虑升级到付费计划或使用 Railway

### 日志查看：
- **Railway**: Project → Deployments → 点击部署 → Logs
- **Render**: Dashboard → 点击服务 → Logs
- **本地**: 终端中直接查看输出

## 维护建议

1. **定期备份**
   - 数据库文件：`stock_simulator/data/stock_simulator.db`
   - 建议每周备份一次

2. **监控**
   - 设置报警：如果连续10分钟无法访问
   - 监控 API 调用额度（Tushare 免费用户每天500次）

3. **升级**
   - 定期更新依赖：`pip install -r requirements.txt --upgrade`
   - 注意 Flask 版本兼容性

## 开发扩展

如果你想进一步开发：

1. **添加新策略**
   - 修改 `engine_db.py` 中的 `score_stock` 函数
   - 添加新的技术指标计算

2. **前端优化**
   - 使用 Vue.js 或 React 重构前端
   - 添加实时图表（K线图、分时图）

3. **功能增强**
   - 添加止损止盈自动提醒
   - 集成微信/邮件通知
   - 多策略并行运行

## 技术支持

如有问题，请检查：
1. 部署平台的官方文档
2. Tushare Pro 官方文档
3. Flask 官方文档

## 免责声明

本项目仅供技术学习和模拟交易使用：
- 不构成投资建议
- 不保证数据准确性
- 不承担任何投资损失责任
- 请遵守当地法律法规

---
**祝您部署顺利！** 🚀

如果遇到问题，请查看日志并根据错误信息进行排查。