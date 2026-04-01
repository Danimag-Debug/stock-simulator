# 模拟炒股助手 - 项目记忆

## 项目概览
这是一个多用户股票模拟交易网站，支持全市场扫描、中线策略选股、模拟买卖交易。已改造为支持多用户系统，准备部署到 Railway/Render 云平台。

## 技术架构

### 数据层
- **数据库**: SQLite（持久化存储，支持 Railway/Render 卷）
- **用户表**: users (id, username, password_hash, created_at)
- **账户表**: accounts (user_id, cash, initial_cash, set_initial_cash, total_profit)
  - `set_initial_cash`: 用户自定义设置的初始资金，须无持仓时才能修改
  - 新增 API: `PUT /api/account/capital` 用于重置初始资金（1,000~10,000,000 范围）
  - `/api/suggestions` 已支持携带 Token，按用户 cash（可用现金）动态重算建议股数/预估成本
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

### 2026-03-31: 专业多因子量化选股引擎 v4.0 - 职业交易员视角升级
1. **新增 technical_analyzer.py**（1030行专业技术分析模块）：
   - 布林带(Bollinger Bands): 位置/宽度/突破信号
   - KDJ随机振荡器(9/3/3): 金叉/死叉/超买超卖判断
   - 威廉指标(WR): -20超买/-80超卖区间判断
   - ATR真实波幅: 动态止损位计算(1.5×ATR止损，更专业精准)
   - OBV能量潮: 量价同向/背离检测(主力积累信号)
   - VWAP成交量加权均价: 机构参考价偏离判断
   - 动量因子(10日Momentum): A股最有效量化因子之一
   - K线形态识别: 锤子线/射击之星/吞没/晨星/三连阳等
   - 趋势/动量/量价/波动 四维度子评分体系

2. **技术面评分 v4.0**（4维度，共40分）：
   - 趋势（15分）: 均线四线多头排列+MACD金叉死叉+K线形态
   - 动量（10分）: RSI+KDJ+WR+10日动量因子
   - 量价（10分）: OBV背离+量比+VWAP偏离+成交额
   - 波动（5分）: 布林带位置+收窄蓄势信号+ATR评估

3. **仓位管理升级**: ATR动态止损取代固定5%止损，融入止损空间计算简化Kelly公式

4. **趋势判断**: `_judge_trend_direction` 多因子判断（强势上涨/偏多震荡/横盘/偏空/下降）

5. **前端详情弹窗 v4.0**:
   - 8格技术指标面板(RSI/KDJ-J/WR/动量/MACD/布林位置/量比/OBV)
   - 每个指标有颜色状态(红超买/绿超卖/黄中性)
   - 趋势方向标签、MA20/MA60参考线
   - ATR波动率和布林带宽度展示

6. **Commit**: 7d0466f，已推送到GitHub，Railway自动部署

### 2026-03-31: 修复基本面/新闻固定分问题 + 完善详情推荐报告 v3.1
1. **根因分析**: fundamental_analyzer Tushare接口无权限→固定返回10分→缩放后8分；news_analyzer API网络失败→固定返回7分→缩放后10分
2. **fundamental_analyzer v2.0重构**:
   - Tushare不可用时改为规则引擎差异化评分（不再固定8分）
   - 新增ROE/毛利率/负债率/成长性等专业指标
   - 知名股票/板块/价格区间加分机制
3. **news_analyzer v2.0重构**:
   - 行业热度改为静态确定性映射（38+股票代码直接映射，17个行业关键词规则），完全不依赖网络
   - 资金流向新维度：东方财富主力资金净流入API
   - 每个行业有专业前景描述文字（用于详情展示）
4. **详情弹窗全新重写**:
   - 3大维度各自有评分进度条、信号标签、总结文字
   - 行业前景展望段落（每个行业专属文字）
   - 专业交易计划（买入/止损/目标价/仓位建议/盈亏比）
   - 风险提示列表（RSI超买/追高风险等）
5. **测试验证**: 宁德时代80分、海康威视76分、茅台72分、兴业银行50分，各股票分数有明显差异
6. **Commit**: e808376，已推送到GitHub，Railway自动部署


1. **新增 news_analyzer.py**: 爬取东方财富公告/新闻，分析利好/利空情绪，识别热点行业（AI/新能源/半导体等）
2. **新增 fundamental_analyzer.py**: 调用Tushare `daily_basic` 接口获取PE/PB/市值/换手率，进行基本面评分
3. **评分体系重构**（总分100）: 技术面(40) + 基本面(25) + 新闻情报(20) + 行业热度(15)
4. **并发扫描**: ThreadPoolExecutor 8线程并发分析，降低扫描耗时
5. **前端卡片**: 新增评分圆圈（颜色区分推荐等级）+ 各维度条形图
6. **数据库**: suggestions表新增 score_breakdown 列，兼容历史数据自动迁移
7. **Commit**: bc6bd21，已推送到GitHub，Railway自动部署

### 2026-03-26: 修复价格、详情按钮、手动扫描等问题
1. **代码结构修复**: `score_stock`函数有死代码，重命名为`score_stock_simple`，创建完整版`score_stock`（优先历史数据，降级到简化版）
2. **持仓实时价格**: `get_portfolio_snapshot`改为批量调用`ts.get_realtime_quotes()`
3. **详情按钮**: 改用`data-*`属性+`addEventListener`，替代内联JSON onclick
4. **手动扫描**: `triggerScan`增加5秒轮询，自动检测完成并刷新
5. **Tushare导入**: 相对导入改为绝对导入（先将`__file__`目录加入`sys.path`）
6. **状态**: 已提交并推送到GitHub，Railway自动部署中
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