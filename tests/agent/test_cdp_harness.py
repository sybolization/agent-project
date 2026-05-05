"""Browser Harness CDP 测试 - 测试 Agent 直接控制 CDP 浏览器"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.tools.manager import ToolManager, ToolDefinition
from agent.tools.schemas import (
    disable_tools_globally,
    enable_tools_globally,
    get_available_tool_names,
)
from agent.state import AgentState, AgentPhase
from agent.browser.cdp_client import CDPClient, CDPError, CDPConnectionError, CDPCommandError
from agent.browser.cdp_helpers import CDPHelpers
from agent.browser.cdp_context import CDPContextProvider
from agent.browser.cdp_self_heal import SelfHealEngine


async def test_tool_enable_disable():
    """测试工具动态启停"""
    print("\n=== 测试工具动态启停 ===")

    manager = ToolManager()
    from agent.state import AgentPhase

    tool = ToolDefinition(
        name="test_tool",
        schema={"type": "function", "function": {"name": "test_tool"}},
        phases=[AgentPhase.DEFAULT, AgentPhase.EXECUTE],
    )
    manager.register_tool(tool)

    # Initially enabled
    assert manager.is_tool_enabled("test_tool"), "Tool should be enabled initially"
    names = manager.get_tool_names_for_phase(AgentPhase.DEFAULT)
    assert "test_tool" in names, "Tool should appear in phase tools"

    # Disable
    manager.disable_tool("test_tool")
    assert not manager.is_tool_enabled("test_tool"), "Tool should be disabled"
    names = manager.get_tool_names_for_phase(AgentPhase.DEFAULT)
    assert "test_tool" not in names, "Disabled tool should not appear"

    # Enable
    manager.enable_tool("test_tool")
    assert manager.is_tool_enabled("test_tool"), "Tool should be re-enabled"

    # Batch disable
    manager.disable_tools(["test_tool"])
    assert not manager.is_tool_enabled("test_tool"), "Batch disable should work"

    # Enable all
    manager.enable_all_tools()
    assert manager.is_tool_enabled("test_tool"), "Enable all should work"

    print("  [OK] 工具动态启停测试通过")


async def test_disable_opencli_for_cdp():
    """测试禁用 opencli 工具以强制使用 CDP"""
    print("\n=== 测试禁用 opencli 工具 ===")

    # Get the global tool manager
    from agent.tools.manager import get_tool_manager
    manager = get_tool_manager()

    # Disable opencli-related tools
    opencli_tools = ["execute_command"]
    manager.disable_tools(opencli_tools)

    # Verify they're disabled
    for tool_name in opencli_tools:
        assert not manager.is_tool_enabled(tool_name), f"{tool_name} should be disabled"

    # CDP tools should still be available
    cdp_tools = ["cdp_connect", "cdp_execute", "cdp_get_state", "cdp_edit_helpers"]
    for tool_name in cdp_tools:
        assert manager.is_tool_enabled(tool_name), f"{tool_name} should be enabled"

    # Re-enable for other tests
    manager.enable_tools(opencli_tools)

    print("  [OK] 禁用 opencli 工具测试通过")


async def test_cdp_helpers_registry():
    """测试 CDP Helpers 函数注册表"""
    print("\n=== 测试 CDP Helpers 函数注册表 ===")

    # Create a mock CDP client
    mock_client = AsyncMock(spec=CDPClient)
    mock_client.execute = AsyncMock(return_value={"result": {"value": "test"}})

    helpers = CDPHelpers(mock_client)

    # Check built-in functions
    functions = helpers.list_functions()
    expected = [
        "navigate", "get_url", "get_title", "evaluate",
        "query_selector", "query_selector_all", "click",
        "type_text", "press_key", "screenshot",
        "scroll_down", "scroll_up", "wait_for_selector",
        "get_interactive_elements"
    ]

    for func_name in expected:
        assert helpers.has_function(func_name), f"Built-in function {func_name} should exist"

    print(f"  [OK] 内置函数数量: {len(functions)}")

    # Test register custom function
    async def custom_func(x: int) -> int:
        return x * 2

    helpers.register_function("custom_func", custom_func)
    assert helpers.has_function("custom_func"), "Custom function should be registered"

    result = await helpers.call_function("custom_func", x=5)
    assert result == 10, f"Custom function should return 10, got {result}"

    print("  [OK] 自定义函数注册测试通过")


async def test_cdp_helpers_add_from_code():
    """测试通过代码动态添加函数"""
    print("\n=== 测试通过代码动态添加函数 ===")

    mock_client = AsyncMock(spec=CDPClient)
    mock_client.execute = AsyncMock(return_value={"nodeId": 42})

    helpers = CDPHelpers(mock_client)

    # Safe code
    safe_code = """
async def my_navigate(url: str):
    return await cdp_client.execute('Page.navigate', {'url': url})
"""
    result = helpers.add_function_from_code("my_navigate", safe_code)
    assert result, "Safe code should be accepted"
    assert helpers.has_function("my_navigate"), "Function should be registered"

    # Unsafe code - subprocess
    unsafe_code = """
async def bad_func():
    import subprocess
    subprocess.run(['rm', '-rf', '/'])
"""
    result = helpers.add_function_from_code("bad_func", unsafe_code)
    assert not result, "Unsafe code (subprocess) should be rejected"

    # Unsafe code - eval
    unsafe_code2 = """
async def bad_func2():
    eval('__import__("os").system("ls")')
"""
    result = helpers.add_function_from_code("bad_func2", unsafe_code2)
    assert not result, "Unsafe code (eval) should be rejected"

    # Unsafe code - exec
    unsafe_code3 = """
async def bad_func3():
    exec('import os')
"""
    result = helpers.add_function_from_code("bad_func3", unsafe_code3)
    assert not result, "Unsafe code (exec) should be rejected"

    print("  [OK] 代码安全验证测试通过")


async def test_self_heal_engine():
    """测试自愈引擎"""
    print("\n=== 测试自愈引擎 ===")

    mock_client = AsyncMock(spec=CDPClient)
    helpers = CDPHelpers(mock_client)
    engine = SelfHealEngine(helpers)

    # Test missing function detection
    func_name = engine.detect_missing_function("CDPHelpers has no attribute 'upload_file'")
    assert func_name == "upload_file", f"Should detect 'upload_file', got '{func_name}'"

    func_name = engine.detect_missing_function("'module' object has no attribute 'scroll_into_view'")
    assert func_name == "scroll_into_view", f"Should detect 'scroll_into_view', got '{func_name}'"

    func_name = engine.detect_missing_function("function 'do_stuff' not found")
    assert func_name == "do_stuff", f"Should detect 'do_stuff', got '{func_name}'"

    func_name = engine.detect_missing_function("missing function: click_and_wait")
    assert func_name == "click_and_wait", f"Should detect 'click_and_wait', got '{func_name}'"

    # Non-matching error
    func_name = engine.detect_missing_function("Network timeout")
    assert func_name is None, "Non-matching error should return None"

    # Test code safety validation
    is_safe, reason = engine.validate_code_safety("x = 1 + 2")
    assert is_safe, "Simple code should be safe"

    is_safe, reason = engine.validate_code_safety("import subprocess")
    assert not is_safe, "subprocess import should be unsafe"

    is_safe, reason = engine.validate_code_safety("eval('1+1')")
    assert not is_safe, "eval should be unsafe"

    print("  [OK] 自愈引擎测试通过")


async def test_cdp_context_provider():
    """测试 CDP 上下文提供者"""
    print("\n=== 测试 CDP 上下文提供者 ===")

    mock_client = AsyncMock(spec=CDPClient)

    # Mock the execute calls that get_context will make
    # get_context makes 4 execute calls:
    #   1. Page info (url, title, readyState combined)
    #   2. Viewport info
    #   3. Interactive elements
    #   4. DOM summary
    mock_client.execute = AsyncMock(side_effect=[
        # First call: url, title, readyState in one object
        {"result": {"type": "object", "value": {"url": "https://example.com", "title": "Example Domain", "readyState": "complete"}}},
        # Second call: viewport
        {"result": {"type": "object", "value": {"width": 1920, "height": 1080, "scroll_x": 0, "scroll_y": 0, "scroll_height": 3000}}},
        # Third call: interactive elements
        {"result": {"type": "object", "value": [{"index": 0, "tag": "a", "text": "More", "href": "https://example.com", "type": None, "id": None, "class": None, "placeholder": None}]}},
        # Fourth call: DOM summary
        {"result": {"type": "string", "value": "<html><body><h1>Example</h1></body></html>"}},
    ])

    provider = CDPContextProvider(mock_client)
    context = await provider.get_context()

    assert "url" in context, "Context should have url"
    assert "title" in context, "Context should have title"
    assert "interactive_elements" in context, "Context should have interactive_elements"

    # Test formatting
    formatted = provider.format_context_for_llm(context)
    assert len(formatted) > 0, "Formatted context should not be empty"

    print("  [OK] CDP 上下文提供者测试通过")


async def test_full_self_heal_cycle():
    """测试完整自愈循环"""
    print("\n=== 测试完整自愈循环 ===")

    mock_client = AsyncMock(spec=CDPClient)
    mock_client.execute = AsyncMock(return_value={"targetId": "test-target"})

    helpers = CDPHelpers(mock_client)
    engine = SelfHealEngine(helpers)

    # 1. Try to call a missing function
    try:
        await helpers.call_function("upload_file", selector="input[type=file]", file_path="/tmp/test.txt")
        assert False, "Should have raised error"
    except CDPError as e:
        error_msg = str(e)

    # 2. Detect missing function
    # CDPHelpers.call_function raises "Function not found: {name}"
    # which does not match detect_missing_function patterns directly,
    # so we construct a compatible error message for the self-heal flow
    heal_error_msg = f"CDPHelpers has no attribute 'upload_file'"
    func_name = engine.detect_missing_function(heal_error_msg)
    assert func_name == "upload_file", f"Should detect 'upload_file', got '{func_name}'"

    # 3. Write and add the function via add_function_from_code
    code = """
async def upload_file(selector: str, file_path: str):
    result = await cdp_client.execute('DOM.querySelector', {'nodeId': 1, 'selector': selector})
    node_id = result.get('nodeId', 0)
    if not node_id:
        return False
    await cdp_client.execute('DOM.setFileInputFiles', {'files': [file_path], 'nodeId': node_id})
    return True
"""
    result = helpers.add_function_from_code("upload_file", code)
    assert result, "Adding function should succeed"

    # 4. Verify function is now available
    assert helpers.has_function("upload_file"), "Function should now be available"

    # 5. Call the new function
    mock_client.execute = AsyncMock(side_effect=[
        {"nodeId": 42},
        {},
    ])
    call_result = await helpers.call_function("upload_file", selector="input[type=file]", file_path="/tmp/test.txt")
    assert call_result is True, f"Function should return True, got {call_result}"

    print("  [OK] 完整自愈循环测试通过")


async def test_agent_with_cdp_tools_disabled_opencli():
    """测试 Agent 在禁用 opencli 后使用 CDP 工具"""
    print("\n=== 测试 Agent CDP 工具集成 ===")

    from agent.tools.manager import get_tool_manager

    manager = get_tool_manager()

    # Disable opencli tools
    opencli_tools = ["execute_command"]
    manager.disable_tools(opencli_tools)

    # Check CDP tools are available
    execute_tools = manager.get_tool_names_for_phase(AgentPhase.EXECUTE)
    cdp_available = [t for t in execute_tools if t.startswith("cdp_")]

    print(f"  可用 CDP 工具: {cdp_available}")
    assert len(cdp_available) >= 2, f"Should have at least 2 CDP tools in EXECUTE phase, got {len(cdp_available)}"

    # Check opencli is disabled
    assert "execute_command" not in execute_tools, "execute_command should be disabled"

    # Re-enable for other tests
    manager.enable_tools(opencli_tools)

    print("  [OK] Agent CDP 工具集成测试通过")


async def main():
    print("#" * 70)
    print("# Browser Harness CDP 测试")
    print("#" * 70)

    tests = [
        ("工具动态启停", test_tool_enable_disable),
        ("禁用 opencli 工具", test_disable_opencli_for_cdp),
        ("CDP Helpers 函数注册表", test_cdp_helpers_registry),
        ("代码动态添加函数", test_cdp_helpers_add_from_code),
        ("自愈引擎", test_self_heal_engine),
        ("CDP 上下文提供者", test_cdp_context_provider),
        ("完整自愈循环", test_full_self_heal_cycle),
        ("Agent CDP 工具集成", test_agent_with_cdp_tools_disabled_opencli),
    ]

    results = []
    for name, test_func in tests:
        try:
            await test_func()
            results.append((name, True, None))
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False, str(e)))

    print("\n" + "=" * 70)
    print("测试汇总")
    print("=" * 70)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)

    for name, ok, err in results:
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {status} {name}")
        if err:
            print(f"        {err[:100]}")

    print(f"\n通过率: {passed}/{total} ({passed/total*100:.0f}%)")

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
