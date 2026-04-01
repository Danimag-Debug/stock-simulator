#!/usr/bin/env python3
"""
测试 Tushare 价格获取功能
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

print("=== 测试 Tushare 价格获取 ===")

# 测试导入 engine_db
try:
    from stock_simulator.engine_db import TUSHARE_AVAILABLE, get_stock_list, score_stock_simple
    print(f"1. TUSHARE_AVAILABLE: {TUSHARE_AVAILABLE}")
    
    if TUSHARE_AVAILABLE:
        print("2. 测试获取股票列表...")
        stocks = get_stock_list()
        print(f"   获取到 {len(stocks)} 只股票")
        
        if stocks:
            print("3. 显示前5只股票信息:")
            for i, stock in enumerate(stocks[:5]):
                print(f"   {i+1}. {stock['code']} {stock['name']}: ¥{stock['current_price']} ({stock['change_pct']}%)")
            
            print("4. 测试评分功能...")
            test_stock = stocks[0]
            score_result = score_stock_simple(
                test_stock['code'], 
                test_stock['name'], 
                test_stock['current_price'], 
                test_stock['change_pct']
            )
            print(f"   评分结果: {score_result['score']}分")
        else:
            print("3. 未获取到股票数据，可能原因:")
            print("   - Tushare API 调用限制")
            print("   - 网络连接问题")
            print("   - 交易时间外（仅交易时间有实时数据）")
    else:
        print("2. Tushare 不可用，无法测试")
        
except Exception as e:
    print(f"测试失败: {e}")
    import traceback
    traceback.print_exc()

print("=== 测试完成 ===")