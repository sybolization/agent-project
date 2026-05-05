"""Handler 分发机制单元测试 - 验证重构后的 phases 模块"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.phases.result import PhaseResult
from agent.phases.handlers import (
    ToolResultHandler, ToolResultFormatter,
    DefaultHandler, DefaultFormatter,
    ExecuteCommandHandler, ExecuteCommandFormatter,
    LoadSkillHandler, LoadSkillFormatter,
    LoadReferenceHandler, LoadReferenceFormatter,
    LoadSkillCategoryHandler, LoadSkillCategoryFormatter,
    UpdateTodoHandler, UpdateTodoFormatter,
    SpawnAgentsHandler, SpawnAgentsFormatter,
    TaskCompleteHandler,
    CdpConnectHandler, CdpConnectFormatter,
    CdpExecuteHandler, CdpExecuteFormatter,
    CdpGetStateHandler, CdpGetStateFormatter,
    CdpEditHelpersHandler, CdpEditHelpersFormatter,
)


class MockState:
    """模拟 AgentState"""
    def __init__(self):
        self.completed_steps = 0
        self.loaded_skills = set()
        self.skill_contents = {}
        self.reference_contents = {}
        self.loaded_references = set()
        self._categories = {}

    def add_skill(self, name, content):
        self.loaded_skills.add(name)
        self.skill_contents[name] = content

    def add_reference(self, skill_name, ref_name, content):
        key = f"{skill_name}/{ref_name}"
        self.loaded_references.add(key)
        self.reference_contents[key] = content

    def add_category(self, name, content):
        self._categories[name] = content

    def get_todo_progress(self):
        return {"total": 0, "completed": 0}


def test_handler_interface():
    """测试 Handler 抽象接口"""
    handler = DefaultHandler()
    assert handler.tool_name == "default"
    result = handler.handle({"type": "unknown"}, MockState())
    assert isinstance(result, PhaseResult)
    assert result.status == "error"
    print("[PASS] test_handler_interface")


def test_formatter_interface():
    """测试 Formatter 抽象接口"""
    formatter = DefaultFormatter()
    assert formatter.tool_name == "default"
    text = formatter.format({"type": "unknown"})
    assert isinstance(text, str)
    assert "工具执行结果" in text
    print("[PASS] test_formatter_interface")


def test_execute_command_handler():
    """测试 execute_command Handler"""
    state = MockState()
    handler = ExecuteCommandHandler(action_label="命令执行")
    assert handler.tool_name == "execute_command"

    result = handler.handle({
        "type": "command_executed",
        "command": "test_cmd",
        "result": {"success": True, "output": "hello"}
    }, state)
    assert result.status == "continue"
    assert state.completed_steps == 1
    assert "命令执行成功" in result.message

    handler2 = ExecuteCommandHandler(action_label="命令验证")
    result2 = handler2.handle({
        "type": "command_executed",
        "command": "test_cmd",
        "result": {"success": True, "output": "hello"}
    }, MockState())
    assert "命令验证成功" in result2.message
    print("[PASS] test_execute_command_handler")


def test_execute_command_formatter():
    """测试 execute_command Formatter"""
    formatter = ExecuteCommandFormatter()

    text = formatter.format({
        "type": "command_executed",
        "command": "test_cmd",
        "result": {"success": True, "output": "hello world"},
    })
    assert "成功" in text
    assert "test_cmd" in text

    text_error = formatter.format({
        "type": "command_executed",
        "command": "test_cmd",
        "result": {"success": False, "error": "boom"},
    })
    assert "失败" in text_error or "错误" in text_error
    print("[PASS] test_execute_command_formatter")


def test_load_skill_handler():
    """测试 load_skill Handler"""
    state = MockState()
    handler = LoadSkillHandler()
    assert handler.tool_name == "load_skill"

    result = handler.handle({
        "type": "skill_loaded",
        "skill_name": "test-skill",
        "content": "skill content here"
    }, state)
    assert result.status == "continue"
    assert "test-skill" in state.loaded_skills
    assert "skill content here" in state.skill_contents["test-skill"]

    result_fail = handler.handle({
        "type": "error",
        "message": "not found"
    }, state)
    assert result_fail.status == "error"
    print("[PASS] test_load_skill_handler")


def test_load_reference_handler():
    """测试 load_reference Handler"""
    state = MockState()
    handler = LoadReferenceHandler()
    assert handler.tool_name == "load_reference"

    result = handler.handle({
        "type": "reference_loaded",
        "skill_name": "skill1",
        "reference_name": "ref1",
        "content": "ref content"
    }, state)
    assert result.status == "continue"
    assert "skill1/ref1" in state.loaded_references

    result_fail = handler.handle({"type": "error", "message": "not found"}, state)
    assert result_fail.status == "error"
    print("[PASS] test_load_reference_handler")


def test_load_skill_category_handler():
    """测试 load_skill_category Handler"""
    state = MockState()
    handler = LoadSkillCategoryHandler()
    assert handler.tool_name == "load_skill_category"

    result = handler.handle({
        "type": "category_loaded",
        "category_name": "search",
        "content": "category content"
    }, state)
    assert result.status == "continue"

    result_fail = handler.handle({"type": "error", "message": "not found"}, state)
    assert result_fail.status == "error"
    print("[PASS] test_load_skill_category_handler")


def test_update_todo_handler_default_phase():
    """测试 update_todo Handler - DefaultPhase 模式"""
    handler = UpdateTodoHandler(on_all_completed_status="complete")
    assert handler.tool_name == "update_todo"

    result = handler.handle({
        "type": "todo_updated",
        "progress": {"total": 3, "completed": 3},
        "message": "all done"
    }, MockState())
    assert result.status == "complete"
    assert result.next_phase is None
    print("[PASS] test_update_todo_handler_default_phase")


def test_update_todo_handler_execute_phase():
    """测试 update_todo Handler - ExecutePhase 模式"""
    handler = UpdateTodoHandler(
        on_all_completed_status="transition",
        on_all_completed_next_phase="REPORT"
    )

    result = handler.handle({
        "type": "todo_updated",
        "progress": {"total": 3, "completed": 3},
        "message": "all done"
    }, MockState())
    assert result.status == "transition"
    assert result.next_phase == "REPORT"

    result_partial = handler.handle({
        "type": "todo_updated",
        "progress": {"total": 3, "completed": 1},
        "message": "updated"
    }, MockState())
    assert result_partial.status == "continue"

    result_error = handler.handle({
        "type": "error",
        "message": "fail"
    }, MockState())
    assert result_error.status == "continue"
    print("[PASS] test_update_todo_handler_execute_phase")


def test_spawn_agents_handler():
    """测试 spawn_agents Handler"""
    handler = SpawnAgentsHandler()
    assert handler.tool_name == "spawn_agents"

    result = handler.handle({
        "type": "agents_spawned",
        "total_agents": 2,
        "completed": 2,
        "failed": 0,
        "results": []
    }, MockState())
    assert result.status == "continue"

    result_fail = handler.handle({"type": "error", "message": "fail"}, MockState())
    assert result_fail.status == "continue"
    print("[PASS] test_spawn_agents_handler")


def test_task_complete_handler_default():
    """测试 task_complete Handler - DefaultPhase"""
    handler = TaskCompleteHandler(completion_status="complete")
    assert handler.tool_name == "task_complete"

    result = handler.handle({}, MockState())
    assert result.status == "complete"
    assert result.next_phase is None
    print("[PASS] test_task_complete_handler_default")


def test_task_complete_handler_execute():
    """测试 task_complete Handler - ExecutePhase"""
    handler = TaskCompleteHandler(
        completion_status="transition",
        completion_next_phase="REPORT"
    )

    result = handler.handle({}, MockState())
    assert result.status == "transition"
    assert result.next_phase == "REPORT"
    print("[PASS] test_task_complete_handler_execute")


def test_cdp_handlers():
    """测试 CDP 系列 Handler"""
    state = MockState()

    connect_handler = CdpConnectHandler()
    result = connect_handler.handle({"type": "cdp_connected", "target_id": "abc"}, state)
    assert result.status == "continue"

    result_already = connect_handler.handle({"type": "cdp_already_connected", "target_id": "abc"}, state)
    assert result_already.status == "continue"

    result_fail = connect_handler.handle({"type": "error", "message": "fail"}, state)
    assert result_fail.status == "error"

    execute_handler = CdpExecuteHandler()
    result_exec = execute_handler.handle({"type": "cdp_result", "function": "click", "result": "ok"}, state)
    assert result_exec.status == "continue"

    result_missing = execute_handler.handle({"type": "missing_function", "missing_function": "foo", "available_functions": []}, state)
    assert result_missing.status == "continue"

    get_state_handler = CdpGetStateHandler()
    result_state = get_state_handler.handle({"type": "cdp_state", "formatted": "state info"}, state)
    assert result_state.status == "continue"

    edit_handler = CdpEditHelpersHandler()
    result_edit = edit_handler.handle({"type": "helpers_updated", "function_name": "new_func", "available_functions": ["new_func"]}, state)
    assert result_edit.status == "continue"

    print("[PASS] test_cdp_handlers")


def test_phase_imports():
    """测试 Phase 类可以正常导入和实例化"""
    from agent.phases import BasePhase, PhaseResult, CollectPhase, PlanPhase, ExecutePhase, ReportPhase, DefaultPhase
    from agent.state import AgentState, AgentPhase

    assert BasePhase is not None
    assert PhaseResult is not None
    assert CollectPhase is not None
    assert PlanPhase is not None
    assert ExecutePhase is not None
    assert ReportPhase is not None
    assert DefaultPhase is not None
    print("[PASS] test_phase_imports")


def test_base_phase_handler_registry():
    """测试 BasePhase 的 Handler 注册和分发机制"""
    from agent.phases.base import BasePhase
    from agent.state import AgentState, AgentPhase

    state = AgentState()
    state.phase = AgentPhase.DEFAULT

    class TestPhase(BasePhase):
        @property
        def phase_name(self):
            return "TEST"

        @property
        def available_tools(self):
            return []

        async def execute(self, user_input, context, original_request):
            return PhaseResult(status="continue")

    phase = TestPhase(
        llm=None,
        tool_executor=None,
        prompt_builder=None,
        state=state,
    )

    assert hasattr(phase, '_handlers')
    assert hasattr(phase, '_formatters')
    assert hasattr(phase, '_dispatch_tool_result')
    assert hasattr(phase, '_dispatch_format_result')
    assert hasattr(phase, '_handle_llm_error')
    assert hasattr(phase, '_check_command_loop')
    assert hasattr(phase, '_build_no_tool_reminder')
    assert hasattr(phase, 'execute_multi_round')

    phase.register_handler(LoadSkillHandler())
    phase.register_formatter(LoadSkillFormatter())

    result = phase._dispatch_tool_result("load_skill", {
        "type": "skill_loaded",
        "skill_name": "test",
        "content": "content"
    })
    assert result.status == "continue"
    assert "test" in state.loaded_skills

    text = phase._dispatch_format_result("load_skill", {
        "type": "skill_loaded",
        "skill_name": "test",
        "content": "content"
    })
    assert isinstance(text, str)
    assert "test" in text

    default_result = phase._dispatch_tool_result("unknown_tool", {"type": "whatever"})
    assert default_result.status == "error"

    print("[PASS] test_base_phase_handler_registry")


def test_default_phase_registers_handlers():
    """测试 DefaultPhase 注册了正确的 Handler"""
    from agent.phases.default_phase import DefaultPhase
    from agent.state import AgentState, AgentPhase

    state = AgentState()
    state.phase = AgentPhase.DEFAULT

    phase = DefaultPhase(
        llm=None,
        tool_executor=None,
        prompt_builder=None,
        state=state,
    )

    expected_handlers = [
        "execute_command", "load_skill", "load_reference",
        "load_skill_category", "update_todo", "spawn_agents",
        "task_complete", "cdp_connect", "cdp_execute",
        "cdp_get_state", "cdp_edit_helpers", "default"
    ]
    for name in expected_handlers:
        assert name in phase._handlers, f"Missing handler: {name}"

    expected_formatters = [
        "execute_command", "load_skill", "load_reference",
        "load_skill_category", "update_todo", "spawn_agents",
        "cdp_connect", "cdp_execute", "cdp_get_state",
        "cdp_edit_helpers", "default"
    ]
    for name in expected_formatters:
        assert name in phase._formatters, f"Missing formatter: {name}"

    result = phase._dispatch_tool_result("task_complete", {})
    assert result.status == "complete"

    result = phase._dispatch_tool_result("update_todo", {
        "type": "todo_updated",
        "progress": {"total": 2, "completed": 2},
        "message": "done"
    })
    assert result.status == "complete"

    print("[PASS] test_default_phase_registers_handlers")


def test_execute_phase_registers_handlers():
    """测试 ExecutePhase 注册了正确的 Handler"""
    from agent.phases.execute_phase import ExecutePhase
    from agent.state import AgentState, AgentPhase

    state = AgentState()
    state.phase = AgentPhase.EXECUTE

    phase = ExecutePhase(
        llm=None,
        tool_executor=None,
        prompt_builder=None,
        state=state,
    )

    assert "task_complete" in phase._handlers
    assert "update_todo" in phase._handlers

    result = phase._dispatch_tool_result("task_complete", {})
    assert result.status == "transition"
    assert result.next_phase == "REPORT"

    result = phase._dispatch_tool_result("update_todo", {
        "type": "todo_updated",
        "progress": {"total": 2, "completed": 2},
        "message": "done"
    })
    assert result.status == "transition"
    assert result.next_phase == "REPORT"

    print("[PASS] test_execute_phase_registers_handlers")


def test_collect_phase_registers_handlers():
    """测试 CollectPhase 注册了正确的 Handler"""
    from agent.phases.collect_phase import CollectPhase
    from agent.state import AgentState, AgentPhase

    state = AgentState()
    state.phase = AgentPhase.COLLECT

    phase = CollectPhase(
        llm=None,
        tool_executor=None,
        prompt_builder=None,
        state=state,
    )

    expected_handlers = [
        "execute_command", "load_skill", "load_reference",
        "load_skill_category", "default"
    ]
    for name in expected_handlers:
        assert name in phase._handlers, f"Missing handler: {name}"

    result = phase._dispatch_tool_result("execute_command", {
        "type": "command_executed",
        "command": "test",
        "result": {"success": True, "output": "ok"}
    })
    assert result.status == "continue"
    assert "命令验证成功" in result.message

    print("[PASS] test_collect_phase_registers_handlers")


def main():
    print("=" * 70)
    print("Handler 分发机制单元测试")
    print("=" * 70)

    tests = [
        test_handler_interface,
        test_formatter_interface,
        test_execute_command_handler,
        test_execute_command_formatter,
        test_load_skill_handler,
        test_load_reference_handler,
        test_load_skill_category_handler,
        test_update_todo_handler_default_phase,
        test_update_todo_handler_execute_phase,
        test_spawn_agents_handler,
        test_task_complete_handler_default,
        test_task_complete_handler_execute,
        test_cdp_handlers,
        test_phase_imports,
        test_base_phase_handler_registry,
        test_default_phase_registers_handlers,
        test_execute_phase_registers_handlers,
        test_collect_phase_registers_handlers,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    print(f"测试结果: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
