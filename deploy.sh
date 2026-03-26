#!/bin/bash

# 部署脚本 - 股票模拟网站部署到Railway
# 使用方法: ./deploy.sh "提交信息"

echo "🎯 股票模拟网站部署脚本"
echo "========================="

# 检查参数
if [ -z "$1" ]; then
    echo "❌ 请提供提交信息，例如: ./deploy.sh \"修复登录bug\""
    exit 1
fi

# 步骤1: 检查Git状态
echo "🔍 检查Git状态..."
git status

# 步骤2: 添加所有更改
echo "📦 添加更改到暂存区..."
git add .

# 步骤3: 提交更改
echo "💾 提交更改..."
git commit -m "$1"

# 步骤4: 推送到GitHub
echo "🚀 推送到GitHub..."
git push origin main

# 步骤5: 显示部署状态
echo "✅ 代码已推送到GitHub！"
echo ""
echo "📊 Railway自动部署进度:"
echo "------------------------"
echo "1. Railway会自动检测GitHub更新"
echo "2. 自动重新构建和部署"
echo "3. 部署完成后访问你的网站:"
echo "   https://stock-simulator-production.up.railway.app"
echo ""
echo "📱 查看部署日志:"
echo "1. 访问 https://railway.app"
echo "2. 选择你的项目"
echo "3. 点击 'Deployments'"
echo "4. 点击最新部署查看日志"
echo ""
echo "🎉 部署完成！网站将在1-3分钟内更新。"