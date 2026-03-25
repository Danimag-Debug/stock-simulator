# 模拟炒股助手 - 项目记忆

## 项目概览
这是一个多用户股票模拟交易网站，支持全市场扫描、中线策略选股、模拟买卖交易。已改造为支持多用户系统，准备部署到 Railway/Render 云平台。

## 技术架构

### 数据层
- **数据库**: SQLite（持久化存储，支持 Railway/Render 卷）
- **用户表**: users (id, username, password_hash, created_at)
- **账户表**: accounts (user_id, cash, initial_cash, total_profit)
- **持仓表**: holdings (user_id, stock_code, stock_name, shares, avg_price, buy_price)
- **交易记录**: trade_logs (user_id, action, stock_code, stock_name, shares, price, amount, profit, commission)
- **全局推荐**: suggestions (stock_code, name, current_price, change_pct, score, signals, buy_price, stop_loss, take_profit, position_pct)

### 后端
- **框架**: Flask 2.3.3
- **认证**: JWT (HS256, 30天有效期)
- **定时任务**: APScheduler (交易日每30分钟扫描)
- **API**: RESTful + JSON
- **跨域**: Flask-CORS

### 前端
- **技术**: 原生 HTML/CSS/JavaScript
- **适配**: 响应式设计（桌面/移动端）
- **样式**: 暗色主题，红色涨/绿色跌（A股习惯）
- **功能**: 实时行情、模拟交易、持仓管理、交易记录

### 数据源
- **主数据**: Tushare Pro API（实时行情）
- **备用**: 模拟数据（Tushare 不可用时）
- **无权限需求**: 使用 `get_realtime_quotes()` 批量拉取，无需高权限

## 改造历史

### 2026-03-25: 多用户改造与上线准备
1. **数据库改造**
   - 弃用 JSON 文件存储，改用 SQLite
   - 设计多用户表结构（用户、账户、持仓、交易记录、推荐）
   - 每个用户独立资金和持仓

2. **用户系统**
   - 添加注册/登录 API (`/api/auth/register`, `/api/auth/login`)
   - JWT Token 认证，有效期30天
   - Token 验证 API (`/api/auth/check`)
   - 密码 SHA-256 加盐哈希存储

3. **API 适配**
   - 私有 API 需要 Bearer Token 认证
   - 公共 API：推荐、健康检查、扫描状态
   - 每个用户独立数据隔离

4. **前端改造**
   - 新增登录/注册页面 (`templates/login.html`)
   - 更新主页面支持多用户 (`templates/index_auth.html`)
   - Token 自动管理（localStorage）
   - 用户信息显示（头像、用户名、退出）

5. **部署配置**
   - `requirements.txt`: Python 依赖包
   - `Procfile`: Railway 启动配置
   - `railway.json`: Railway 详细配置
   - `render.yaml`: Render 平台配置
   - `start.sh`: 本地启动脚本
   - `DEPLOYMENT.md`: 详细部署指南
   - `README.md`: 项目介绍和快速指南

## 部署信息

### 平台选择
1. **Railway**（推荐）:
   - 免费 PostgreSQL（项目用 SQLite）
   - 持续运行（不休眠）
   - 简单易用，自动 HTTPS

2. **Render**（备选）:
   - 免费 Web 服务
   - 15分钟无请求后休眠
   - 自动 SSL，静态出站 IP

### 配置要点
- **环境变量**: `TUSHARE_TOKEN`（可选，用于真实行情）
- **端口**: `$PORT`（云平台自动分配）
- **Web 服务器**: Gunicorn（2 workers, 4 threads）

### 部署步骤
1. Fork 到 GitHub
2. Railway/Render 连接 GitHub 仓库
3. 自动部署（检测 requirements.txt）
4. 访问分配的域名

## 功能特性

### 已实现功能
1. **多用户认证**: 注册、登录、Token 管理
2. **全市场扫描**: 沪深两市约5000只股票筛选
3. **技术分析**: MA、MACD、RSI、量比计算
4. **策略评分**: 中线多因子综合评分（0-100）
5. **模拟交易**: 买入/卖出，含佣金、印花税
6. **持仓管理**: 实时市值、盈亏计算
7. **交易记录**: 完整买卖历史，含盈亏明细
8. **定时任务**: 交易日每30分钟自动扫描

### 待开发功能（可选）
1. 实时 K 线图
2. 多策略并行运行
3. 微信/邮件通知
4. 社交功能（关注、分享）
5. 回测系统

## 安全策略

1. **密码安全**: SHA-256 加盐哈希
2. **API 防护**: JWT Token 认证
3. **数据隔离**: 每个用户独立数据库访问
4. **输入验证**: 服务端参数校验
5. **跨域控制**: 严格 CORS 配置

## 注意事项

### 重要提醒
1. **数据准确性**: 无 Tushare Token 时使用模拟数据（价格随机）
2. **性能考虑**: 全市场扫描耗时1-3分钟，请勿频繁手动触发
3. **存储需求**: SQLite 文件约 1-10MB（随用户数增长）
4. **免费限制**: Railway/Render 免费版有资源限制

### 维护建议
1. **定期备份**: 每周备份 `stock_simulator.db` 文件
2. **监控**: 关注 API 调用额度（Tushare 每天500次免费）
3. **升级**: 定期更新依赖包
4. **日志**: 定期检查服务器日志

## 联系方式

- **项目类型**: 开源学习项目
- **主要用途**: 股票策略学习、模拟交易练习
- **免责声明**: 不构成投资建议，不保证数据准确性
- **更新记录**: 查看 `.workbuddy/memory/` 目录中的每日日志

---
**最后更新**: 2026-03-25
**版本**: v2.0（多用户版）