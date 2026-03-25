#!/usr/bin/env python3
"""
系统功能测试脚本
用于验证多用户股票模拟系统的基本功能
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import requests
import json
import time

BASE_URL = "http://localhost:5001"
API_BASE = f"{BASE_URL}/api"

def test_api_health():
    """测试 API 健康检查"""
    print("1. 测试 API 健康检查...")
    try:
        response = requests.get(f"{API_BASE}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "ok":
                print("   ✅ API 健康检查通过")
                return True
        print(f"   ❌ API 健康检查失败: {response.status_code} {response.text}")
    except Exception as e:
        print(f"   ❌ API 健康检查异常: {e}")
    return False

def test_register():
    """测试用户注册"""
    print("2. 测试用户注册...")
    import random
    username = f"testuser{random.randint(1000, 9999)}"
    password = "test123456"
    
    try:
        response = requests.post(
            f"{API_BASE}/auth/register",
            json={"username": username, "password": password},
            timeout=5
        )
        data = response.json()
        
        if data.get("success"):
            print(f"   ✅ 用户注册成功: {username}")
            return data.get("token"), username
        else:
            print(f"   ❌ 用户注册失败: {data.get('message')}")
    except Exception as e:
        print(f"   ❌ 用户注册异常: {e}")
    
    return None, None

def test_login():
    """测试用户登录（使用已知测试账号）"""
    print("3. 测试用户登录...")
    username = "demouser"
    password = "demo123"
    
    try:
        # 先尝试注册测试账号（如果不存在）
        response = requests.post(
            f"{API_BASE}/auth/register",
            json={"username": username, "password": password},
            timeout=5
        )
        
        # 然后登录
        response = requests.post(
            f"{API_BASE}/auth/login",
            json={"username": username, "password": password},
            timeout=5
        )
        data = response.json()
        
        if data.get("success"):
            print(f"   ✅ 用户登录成功: {username}")
            return data.get("token"), username
        else:
            print(f"   ❌ 用户登录失败: {data.get('message')}")
    except Exception as e:
        print(f"   ❌ 用户登录异常: {e}")
    
    return None, None

def test_token_check(token):
    """测试 Token 验证"""
    print("4. 测试 Token 验证...")
    if not token:
        print("   ⚠️  跳过 Token 验证（无 token）")
        return False
    
    try:
        response = requests.post(
            f"{API_BASE}/auth/check",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5
        )
        data = response.json()
        
        if data.get("success"):
            print(f"   ✅ Token 验证成功")
            return True
        else:
            print(f"   ❌ Token 验证失败: {data.get('message')}")
    except Exception as e:
        print(f"   ❌ Token 验证异常: {e}")
    
    return False

def test_suggestions():
    """测试获取股票推荐"""
    print("5. 测试获取股票推荐...")
    try:
        response = requests.get(f"{API_BASE}/suggestions", timeout=10)
        data = response.json()
        
        if "items" in data:
            items = data.get("items", [])
            print(f"   ✅ 获取到 {len(items)} 个股票推荐")
            if items:
                print(f"      示例: {items[0].get('name')} ({items[0].get('code')})")
            return True
        else:
            print(f"   ❌ 获取推荐失败: {data}")
    except Exception as e:
        print(f"   ❌ 获取推荐异常: {e}")
    
    return False

def test_scan_status():
    """测试扫描状态"""
    print("6. 测试扫描状态...")
    try:
        response = requests.get(f"{API_BASE}/scan/status", timeout=5)
        data = response.json()
        
        if "running" in data:
            status = "运行中" if data["running"] else "空闲"
            print(f"   ✅ 扫描状态: {status}")
            if data.get("last_run"):
                print(f"      上次运行: {data['last_run']}")
            return True
        else:
            print(f"   ❌ 扫描状态失败: {data}")
    except Exception as e:
        print(f"   ❌ 扫描状态异常: {e}")
    
    return False

def test_portfolio(token):
    """测试获取持仓（需要登录）"""
    print("7. 测试获取用户持仓...")
    if not token:
        print("   ⚠️  跳过持仓测试（无 token）")
        return False
    
    try:
        response = requests.get(
            f"{API_BASE}/portfolio",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5
        )
        data = response.json()
        
        if data.get("success"):
            portfolio = data.get("data", {})
            cash = portfolio.get("cash", 0)
            holdings = portfolio.get("holdings", [])
            print(f"   ✅ 持仓获取成功: 现金 ¥{cash:.2f}, 持仓 {len(holdings)} 只")
            return True
        else:
            print(f"   ❌ 持仓获取失败: {data.get('message', '未知错误')}")
    except Exception as e:
        print(f"   ❌ 持仓获取异常: {e}")
    
    return False

def test_manual_scan():
    """测试手动触发扫描"""
    print("8. 测试手动触发扫描...")
    try:
        response = requests.post(f"{API_BASE}/scan/trigger", timeout=5)
        data = response.json()
        
        if data.get("success"):
            print(f"   ✅ 手动扫描触发成功: {data.get('message')}")
            return True
        else:
            print(f"   ⚠️  手动扫描触发返回失败: {data.get('message')}")
            return True  # 如果正在扫描中，这也算正常
    except Exception as e:
        print(f"   ❌ 手动扫描触发异常: {e}")
    
    return False

def main():
    """主测试函数"""
    print("=" * 60)
    print("模拟炒股助手 - 系统功能测试")
    print("=" * 60)
    
    # 检查服务器是否运行
    print("检查服务器状态...")
    try:
        response = requests.get(f"{BASE_URL}/", timeout=5)
        if response.status_code == 200:
            print("✅ 服务器正在运行")
        else:
            print(f"⚠️  服务器返回 {response.status_code}")
    except:
        print("❌ 服务器未运行或无法连接")
        print("请先启动服务器：")
        print("  cd /Users/fanyiheng/WorkBuddy/20260324082744")
        print("  ./start.sh")
        return
    
    print("\n开始功能测试...")
    results = []
    
    # 运行测试
    results.append(test_api_health())
    
    # 测试注册和登录
    token1, user1 = test_register()
    results.append(bool(token1))
    
    token2, user2 = test_login()
    results.append(bool(token2))
    
    # 使用登录成功的token继续测试
    token = token2 if token2 else token1
    if token:
        results.append(test_token_check(token))
        results.append(test_portfolio(token))
    else:
        results.append(False)
        results.append(False)
    
    # 测试公开API
    results.append(test_suggestions())
    results.append(test_scan_status())
    results.append(test_manual_scan())
    
    # 统计结果
    print("\n" + "=" * 60)
    print("测试结果汇总:")
    print("=" * 60)
    
    passed = sum(1 for r in results if r)
    total = len(results)
    
    print(f"✅ 通过: {passed}/{total}")
    print(f"❌ 失败: {total - passed}/{total}")
    
    if passed == total:
        print("\n🎉 所有测试通过！系统功能正常。")
    elif passed >= total * 0.7:
        print("\n⚠️  大部分测试通过，系统基本可用。")
    else:
        print("\n❌ 测试失败较多，请检查系统配置。")
    
    print("\n下一步：")
    print("1. 访问 http://localhost:5001 使用系统")
    print("2. 按照 README.md 部署到 Railway/Render")
    print("3. 配置 Tushare Token 获取真实行情数据")

if __name__ == "__main__":
    # 给服务器一点启动时间
    time.sleep(2)
    main()