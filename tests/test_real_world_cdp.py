"""Browser Harness CDP 真实环境测试 - Agent 直接控制 CDP 浏览器

运行方式:
    # 使用原有测试方式
    cd "d:\项目\quick capture\web-research-bot"
    .venv\Scripts\python.exe tests/test_real_world_cdp.py

    # 使用测试集框架运行所有测试
    .venv\Scripts\python.exe tests/test_real_world_cdp.py --use-suite

    # 使用测试集框架运行指定测试
    .venv\Scripts\python.exe tests/test_real_world_cdp.py --use-suite --test-ids cdp-basic-001 cdp-complex-001

    # 列出所有可用测试
    .venv\Scripts\python.exe tests/test_real_world_cdp.py --list-tests

前置条件:
    Chrome 需要以远程调试模式启动:
    "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.cdp_profile"
"""

import argparse
import asyncio
import sys
import socket
import subprocess
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.agent_loop import AgentLoop
from agent.state import AgentState, AgentPhase
from agent.tools.manager import get_tool_manager
from agent.skills.manager import SkillManager
from tests.cdp_test_suite.runner import TestRunner, TestCase, TestResult


CDP_PORT = 9222
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
]


def check_chrome_cdp_available(port: int = CDP_PORT) -> bool:
    """检查 Chrome CDP 是否可用"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('localhost', port))
        sock.close()
        return result == 0
    except Exception:
        return False


def find_chrome_path() -> str | None:
    """查找 Chrome 可执行文件路径"""
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    return None


def start_chrome_cdp(port: int = CDP_PORT) -> subprocess.Popen | None:
    """启动 Chrome 远程调试模式"""
    chrome_path = find_chrome_path()
    if not chrome_path:
        return None
    
    user_data_dir = os.path.expandvars(f"%USERPROFILE%\\.cdp_profile_{port}")
    
    try:
        proc = subprocess.Popen([
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc
    except Exception as e:
        print(f"启动 Chrome 失败: {e}")
        return None


def ensure_chrome_available() -> bool:
    """确保 Chrome CDP 可用，如果不可用则尝试启动"""
    if check_chrome_cdp_available():
        return True
    
    print(f"\n[提示] Chrome CDP 未运行在端口 {CDP_PORT}")
    print("正在尝试启动 Chrome...")
    
    proc = start_chrome_cdp()
    if proc:
        import time
        for _ in range(10):
            time.sleep(1)
            if check_chrome_cdp_available():
                print(f"[OK] Chrome 已启动 (PID: {proc.pid})")
                return True
        print("[失败] Chrome 启动超时")
        return False
    else:
        print("[失败] 无法找到 Chrome，请手动启动:")
        print(f'  "{CHROME_PATHS[0]}" --remote-debugging-port={CDP_PORT} --user-data-dir="%USERPROFILE%\\.cdp_profile"')
        return False


def disable_opencli():
    """禁用 opencli 工具和技能类别"""
    tool_manager = get_tool_manager()
    tool_manager.disable_tools(["execute_command"])
    
    skill_manager = SkillManager()
    skill_manager.disable_category("opencli")
    
    return tool_manager, skill_manager


def enable_opencli(tool_manager, skill_manager):
    """重新启用 opencli 工具和技能类别"""
    tool_manager.enable_tools(["execute_command"])
    skill_manager.enable_category("opencli")


async def test_cdp_direct_control():
    """测试 Agent 使用 CDP 直接控制浏览器（禁用 opencli）"""

    print("=" * 70)
    print("真实环境测试：Agent 使用 CDP 直接控制浏览器")
    print("=" * 70)

    test_input = (
        "使用CDP连接到浏览器，然后导航到 https://example.com，"
        "获取页面标题和所有可交互元素，告诉我页面上有什么内容。"
    )

    print(f"\n测试输入: {test_input}")
    print(f"预期行为:")
    print(f"   - Agent 调用 cdp_connect 连接浏览器")
    print(f"   - Agent 调用 cdp_execute(function='navigate') 导航")
    print(f"   - Agent 调用 cdp_get_state 获取页面状态")
    print(f"   - Agent 调用 cdp_execute(function='get_title') 获取标题")
    print(f"   - Agent 调用 cdp_execute(function='get_interactive_elements') 获取元素")
    print("-" * 70)

    tool_manager, skill_manager = disable_opencli()
    print(f"已禁用 opencli 工具: ['execute_command']")
    print(f"已禁用 opencli 技能类别")
    print(f"CDP 工具状态: {[t for t in tool_manager.get_tool_names_for_phase(AgentPhase.EXECUTE) if t.startswith('cdp_')]}")

    agent = AgentLoop(max_iterations=15, enable_logging=True, mode="default", skill_manager=skill_manager, provider="deepseek")

    # 包装 LLM adapter 以打印每轮详情
    _original_chat = agent.llm._adapter.chat_interleaved
    _iter_counter = [0]

    async def _logged_chat(**kwargs):
        _iter_counter[0] += 1
        i = _iter_counter[0]
        print(f"\n{'='*50}")
        print(f"  LLM 调用 #{i}")
        print(f"{'='*50}")
        result = await _original_chat(**kwargs)
        if result.get("reasoning_content"):
            print(f"  [思考]\n{result['reasoning_content'][:800]}")
        print(f"  [回复]\n{(result.get('content') or '')[:500]}")
        if result.get("tool_calls"):
            for tc in result["tool_calls"]:
                args_str = str(tc.get("arguments", {}))[:200]
                print(f"  [工具调用] {tc.get('name', '?')}({args_str})")
        print(f"{'='*50}")
        return result

    agent.llm._adapter.chat_interleaved = _logged_chat

    try:
        print("\n开始执行...")
        response = await agent.run(test_input, reset=True)

        loaded_skills = agent.get_loaded_skills()
        state = agent.state

        print("\n" + "=" * 70)
        print("测试结果")
        print("=" * 70)

        print(f"\n执行完成")
        print(f"   - 迭代次数: {state.iteration_count}")
        print(f"   - 最终阶段: {state.phase.value}")
        print(f"   - 加载的技能: {loaded_skills}")

        print(f"\n响应预览:")
        print("-" * 70)
        if response:
            print(response[:1000] if len(response) > 1000 else response)
        else:
            print("无响应")

        log_path = agent._interaction_logger.save()
        print(f"\n日志保存至: {log_path}")

        print("\n" + "=" * 70)
        print("验证结果")
        print("=" * 70)

        validations = {
            "有实际响应": response is not None and len(response) > 0,
            "迭代次数合理": state.iteration_count > 0,
            "未使用 execute_command": "execute_command" not in str(agent.tool_executor._execution_log if hasattr(agent.tool_executor, '_execution_log') else ""),
        }

        for check, passed in validations.items():
            status = "[OK]" if passed else "[FAIL]"
            print(f"  {status} {check}")

        all_passed = all(validations.values())
        print(f"\n{'所有验证通过' if all_passed else '部分验证失败'}")

        return {
            "success": all_passed,
            "loaded_skills": loaded_skills,
            "iterations": state.iteration_count,
            "phase": state.phase.value,
            "response_length": len(response) if response else 0,
            "log_path": log_path,
        }

    except Exception as e:
        print(f"\n执行出错: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
        }
    finally:
        enable_opencli(tool_manager, skill_manager)
        print(f"\n已重新启用 opencli 工具和技能类别")


async def test_cdp_self_heal():
    """测试 Agent 使用 CDP 自愈循环（遇到缺失函数时自行编写）"""

    print("\n" + "=" * 70)
    print("真实环境测试：Agent CDP 自愈循环")
    print("=" * 70)

    test_input = (
        "使用CDP连接到浏览器，然后导航到 https://example.com，"
        "获取页面上所有链接的文本和URL。"
        "如果你需要的函数不存在，请使用 cdp_edit_helpers 添加它。"
    )

    print(f"\n测试输入: {test_input}")
    print(f"预期行为:")
    print(f"   - Agent 连接 CDP")
    print(f"   - Agent 导航到页面")
    print(f"   - Agent 尝试获取链接（可能需要自愈）")
    print(f"   - 如果缺失函数，Agent 使用 cdp_edit_helpers 添加")
    print(f"   - Agent 重试并成功")
    print("-" * 70)

    tool_manager, skill_manager = disable_opencli()

    agent = AgentLoop(max_iterations=20, enable_logging=True, mode="default", skill_manager=skill_manager, provider="deepseek")

    # 包装 LLM adapter 以打印每轮详情
    _original_chat = agent.llm._adapter.chat_interleaved
    _iter_counter = [0]

    async def _logged_chat(**kwargs):
        _iter_counter[0] += 1
        i = _iter_counter[0]
        print(f"\n{'='*50}")
        print(f"  LLM 调用 #{i}")
        print(f"{'='*50}")
        result = await _original_chat(**kwargs)
        if result.get("reasoning_content"):
            print(f"  [思考]\n{result['reasoning_content'][:800]}")
        print(f"  [回复]\n{(result.get('content') or '')[:500]}")
        if result.get("tool_calls"):
            for tc in result["tool_calls"]:
                args_str = str(tc.get("arguments", {}))[:200]
                print(f"  [工具调用] {tc.get('name', '?')}({args_str})")
        print(f"{'='*50}")
        return result

    agent.llm._adapter.chat_interleaved = _logged_chat

    try:
        print("\n开始执行...")
        response = await agent.run(test_input, reset=True)

        loaded_skills = agent.get_loaded_skills()
        state = agent.state

        print("\n" + "=" * 70)
        print("测试结果")
        print("=" * 70)

        print(f"\n执行完成")
        print(f"   - 迭代次数: {state.iteration_count}")
        print(f"   - 最终阶段: {state.phase.value}")
        print(f"   - 加载的技能: {loaded_skills}")

        print(f"\n响应预览:")
        print("-" * 70)
        if response:
            print(response[:1500] if len(response) > 1500 else response)
        else:
            print("无响应")

        log_path = agent._interaction_logger.save()
        print(f"\n日志保存至: {log_path}")

        print("\n" + "=" * 70)
        print("验证结果")
        print("=" * 70)

        validations = {
            "有实际响应": response is not None and len(response) > 0,
            "迭代次数合理": state.iteration_count > 0,
        }

        for check, passed in validations.items():
            status = "[OK]" if passed else "[FAIL]"
            print(f"  {status} {check}")

        all_passed = all(validations.values())
        print(f"\n{'所有验证通过' if all_passed else '部分验证失败'}")

        return {
            "success": all_passed,
            "loaded_skills": loaded_skills,
            "iterations": state.iteration_count,
            "phase": state.phase.value,
            "response_length": len(response) if response else 0,
            "log_path": log_path,
        }

    except Exception as e:
        print(f"\n执行出错: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
        }
    finally:
        enable_opencli(tool_manager, skill_manager)
        print(f"\n已重新启用 opencli 工具和技能类别")


async def test_cdp_vs_opencli():
    """对比测试：CDP 直接控制 vs opencli 控制"""

    print("\n" + "=" * 70)
    print("对比测试：CDP 直接控制 vs opencli 控制")
    print("=" * 70)

    test_input = "打开 https://example.com 并告诉我页面标题"

    print(f"\n测试输入: {test_input}")

    results = {}

    for mode_name, use_cdp in [("CDP模式", True), ("opencli模式", False)]:
        print(f"\n{'='*70}")
        print(f"测试模式: {mode_name}")
        print("=" * 70)

        tool_manager = get_tool_manager()
        skill_manager = SkillManager()
        
        if use_cdp:
            tool_manager.disable_tools(["execute_command"])
            skill_manager.disable_category("opencli")

        agent = AgentLoop(max_iterations=10, enable_logging=True, mode="default", skill_manager=skill_manager, provider="deepseek")

        # 包装 LLM adapter 以打印每轮详情
        _original_chat = agent.llm._adapter.chat_interleaved
        _iter_counter = [0]

        async def _logged_chat(**kwargs):
            _iter_counter[0] += 1
            i = _iter_counter[0]
            print(f"\n{'='*50}")
            print(f"  LLM 调用 #{i}")
            print(f"{'='*50}")
            result = await _original_chat(**kwargs)
            if result.get("reasoning_content"):
                print(f"  [思考]\n{result['reasoning_content'][:800]}")
            print(f"  [回复]\n{(result.get('content') or '')[:500]}")
            if result.get("tool_calls"):
                for tc in result["tool_calls"]:
                    args_str = str(tc.get("arguments", {}))[:200]
                    print(f"  [工具调用] {tc.get('name', '?')}({args_str})")
            print(f"{'='*50}")
            return result

        agent.llm._adapter.chat_interleaved = _logged_chat

        try:
            response = await agent.run(test_input, reset=True)
            state = agent.state

            results[mode_name] = {
                "success": response is not None and len(response) > 0,
                "iterations": state.iteration_count,
                "response_length": len(response) if response else 0,
            }

            print(f"\n{mode_name} 结果:")
            print(f"   - 迭代次数: {state.iteration_count}")
            print(f"   - 响应长度: {len(response) if response else 0}")

        except Exception as e:
            print(f"\n{mode_name} 执行出错: {e}")
            results[mode_name] = {"success": False, "error": str(e)}
        finally:
            if use_cdp:
                tool_manager.enable_tools(["execute_command"])
                skill_manager.enable_category("opencli")

    print("\n" + "=" * 70)
    print("对比结果")
    print("=" * 70)

    for mode_name, result in results.items():
        status = "[OK]" if result.get("success") else "[FAIL]"
        print(f"  {status} {mode_name}: {result}")

    return results


def list_available_tests() -> None:
    """列出所有可用的测试用例"""
    runner = TestRunner()
    try:
        test_cases = runner.load_test_cases()
        print("=" * 70)
        print("Available Test Cases")
        print("=" * 70)
        for tc in test_cases:
            print(f"\n  [{tc.test_id}] {tc.name}")
            print(f"    Description: {tc.description}")
            print(f"    Max Iterations: {tc.max_iterations}")
            print(f"    Timeout: {tc.timeout}s")
            print(f"    Success Criteria: {tc.success_criteria}")
    except FileNotFoundError as e:
        print(f"[Error] {e}")
    except Exception as e:
        print(f"[Error] Failed to load test cases: {e}")


async def run_with_suite(test_ids: list[str] | None = None) -> bool:
    """使用测试集框架运行测试

    Args:
        test_ids: 指定要运行的测试ID列表，如果为None则运行所有测试

    Returns:
        是否所有测试都通过
    """
    print("#" * 70)
    print("# Browser Harness CDP Test Suite")
    print("#" * 70)

    if not ensure_chrome_available():
        print("\n[Skip] Chrome CDP not available, skipping tests")
        print("To run tests, please start Chrome first:")
        print('  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\\.cdp_profile"')
        return True

    runner = TestRunner()

    try:
        results = await runner.run_all_tests(test_ids=test_ids)
        runner.save_results()

        all_passed = all(r.success for r in results)
        return all_passed

    except FileNotFoundError as e:
        print(f"\n[Error] {e}")
        return False
    except Exception as e:
        print(f"\n[Error] Failed to run tests: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_legacy_tests() -> bool:
    """使用原有方式运行测试

    Returns:
        是否所有测试都通过
    """
    print("#" * 70)
    print("# Browser Harness CDP 真实环境测试")
    print("#" * 70)

    if not ensure_chrome_available():
        print("\n[跳过] Chrome CDP 不可用，跳过真实环境测试")
        print("如需运行测试，请先启动 Chrome:")
        print('  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\\.cdp_profile"')
        return True

    tests = [
        ("CDP 直接控制", test_cdp_direct_control),
        ("CDP 自愈循环", test_cdp_self_heal),
        ("CDP vs opencli 对比", test_cdp_vs_opencli),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result.get("success", False), result))
        except Exception as e:
            print(f"\n[FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False, {"error": str(e)}))

    print("\n" + "=" * 70)
    print("全部测试汇总")
    print("=" * 70)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)

    for name, ok, _ in results:
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {status} {name}")

    print(f"\n通过率: {passed}/{total} ({passed/total*100:.0f}%)")

    return passed == total


async def main():
    """主入口函数，支持命令行参数"""
    parser = argparse.ArgumentParser(
        description="Browser Harness CDP 真实环境测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 使用原有测试方式
  python tests/test_real_world_cdp.py

  # 使用测试集框架运行所有测试
  python tests/test_real_world_cdp.py --use-suite

  # 使用测试集框架运行指定测试
  python tests/test_real_world_cdp.py --use-suite --test-ids cdp-basic-001 cdp-complex-001

  # 列出所有可用测试
  python tests/test_real_world_cdp.py --list-tests
        """
    )

    parser.add_argument(
        "--use-suite",
        action="store_true",
        help="使用测试集框架运行测试"
    )
    parser.add_argument(
        "--test-ids",
        nargs="+",
        help="指定要运行的测试ID列表（需要配合 --use-suite 使用）"
    )
    parser.add_argument(
        "--list-tests",
        action="store_true",
        help="列出所有可用测试"
    )

    args = parser.parse_args()

    # 列出所有可用测试
    if args.list_tests:
        list_available_tests()
        return True

    # 使用测试集框架运行
    if args.use_suite:
        return await run_with_suite(test_ids=args.test_ids)

    # 使用原有方式运行
    return await run_legacy_tests()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
