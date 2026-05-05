"""
真实场景测试运行入口

运行所有真实场景测试
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 70)
    print(" 真实场景测试 - 策略级联系统验证")
    print("=" * 70)
    
    results = {}
    
    print("\n[1/2] 测试知乎热榜...")
    from tests.real.test_zhihu_hot import test_zhihu_hot, test_zhihu_hot_api_direct
    results["知乎API直接测试"] = await test_zhihu_hot_api_direct()
    results["知乎策略级联测试"] = await test_zhihu_hot()
    
    print("\n[2/2] 测试B站热门...")
    from tests.real.test_bilibili_hot import test_bilibili_hot, test_bilibili_api_direct
    results["B站API直接测试"] = await test_bilibili_api_direct()
    results["B站策略级联测试"] = await test_bilibili_hot()
    
    print("\n" + "=" * 70)
    print(" 测试结果汇总")
    print("=" * 70)
    
    all_passed = True
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 70)
    if all_passed:
        print(" 🎉 所有测试通过!")
    else:
        print(" ⚠️ 部分测试失败，请检查日志")
    print("=" * 70)
    
    return all_passed


def main():
    """主入口"""
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
