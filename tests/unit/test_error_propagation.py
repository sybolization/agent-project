"""递归式异常传播测试 — 验证 AgentError 层级体系和持久化"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from agent.errors import (
    AgentError,
    ToolError,
    CommandExecutionError,
    CdpExecutionError,
    SubagentExecutionError,
    HarnessError,
    PhaseExecutionError,
    SessionError,
    LogPersistenceError,
    ContainerStartupError,
    ContainerStateError,
)
from agent.session.logger import InteractionLogger


def test_1_agent_error_add_context():
    """测试 AgentError.add_context() 链式调用"""
    err = AgentError("测试异常", agent_id="test-1", layer="tool", fatal=True)
    err.add_context("key1", "value1").add_context("key2", 42)
    assert err.context == {"key1": "value1", "key2": 42}


def test_2_agent_error_str_output():
    """测试 AgentError.__str__() 人类可读输出"""
    err = CommandExecutionError(
        "命令执行超时",
        tool_name="execute_command",
        arguments={"command": "opencli xiaohongshu search"},
        agent_id="agent-1",
        fatal=True,
    )
    str_output = str(err)
    assert "[TOOL]" in str_output
    assert "CommandExecutionError" in str_output
    assert "命令执行超时" in str_output
    assert "tool_name" in str_output
    assert "fatal: True" in str_output


def test_3_exception_chain():
    """测试 raise ... from 建立异常因果链"""
    try:
        try:
            raise ValueError("原始错误")
        except ValueError as orig:
            raise CommandExecutionError(
                "命令失败",
                tool_name="test_tool",
                agent_id="test-1",
                fatal=True,
            ) from orig
    except CommandExecutionError as e:
        assert e.__cause__ is not None
        assert isinstance(e.__cause__, ValueError)
        assert str(e.__cause__) == "原始错误"


def test_4_exception_chain_wrapping():
    """测试 ToolError → HarnessError 包装链"""
    try:
        try:
            raise ValueError("底层错误")
        except ValueError as orig:
            tool_err = CommandExecutionError(
                "命令失败",
                tool_name="test_tool",
                agent_id="test-1",
                fatal=True,
            )
            tool_err.__cause__ = orig
            raise tool_err
    except CommandExecutionError as tool_err:
        harness_err = PhaseExecutionError(
            "阶段执行失败",
            agent_id="main",
            iteration=3,
            phase="EXECUTE",
            fatal=True,
        )
        harness_err.__cause__ = tool_err
        assert harness_err.__cause__ is tool_err
        assert isinstance(harness_err.__cause__.__cause__, ValueError)


def test_5_agent_error_to_dict():
    """测试 AgentError.to_dict() 序列化"""
    try:
        raise ValueError("底层错误")
    except ValueError as orig:
        err = CommandExecutionError(
            "命令失败",
            tool_name="test",
            agent_id="a1",
            fatal=True,
        )
        err.__cause__ = orig

    d = err.to_dict()
    assert d["error_type"] == "CommandExecutionError"
    assert d["error_message"] == "命令失败"
    assert d["agent_id"] == "a1"
    assert d["layer"] == "tool"
    assert d["fatal"] is True
    assert "tool_name" in d["context"]
    assert len(d["error_chain"]) == 1
    assert d["error_chain"][0]["error_type"] == "ValueError"


def test_6_non_fatal_flag():
    """测试 fatal=False 异常不标记为致命"""
    err = CdpExecutionError(
        "CDP 状态获取失败",
        tool_name="cdp_get_state",
        agent_id="test-1",
        fatal=False,
    )
    assert err.fatal is False
    str_output = str(err)
    assert "fatal: True" not in str_output


def test_7_emit_error_jsonl_structure():
    """测试 InteractionLogger.emit_error() 输出的 JSONL 结构"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = InteractionLogger(log_dir=tmpdir, enable=True)

        err = CommandExecutionError(
            "测试错误", tool_name="test_tool", agent_id="a1", fatal=True
        )

        event_id = logger.emit_error(err)
        assert event_id != ""

        events = logger.get_events(event_type="error")
        assert len(events) == 1

        event = events[0]
        data = event["data"]
        assert data["error_type"] == "CommandExecutionError"
        assert data["error_message"] == "测试错误"
        assert data["agent_id"] == "a1"
        assert "error_chain" in data
        assert "context" in data

        logger._close_jsonl_file()


def test_8_emit_error_non_agent_error():
    """测试 emit_error() 处理非 AgentError"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = InteractionLogger(log_dir=tmpdir, enable=True)

        err = RuntimeError("普通异常")
        event_id = logger.emit_error(err)
        assert event_id != ""

        events = logger.get_events(event_type="error")
        assert len(events) == 1
        assert events[0]["data"]["error_type"] == "RuntimeError"

        logger._close_jsonl_file()


def test_9_notify_does_not_silently_swallow():
    """测试 _notify() 中订阅者异常不静默吞掉"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = InteractionLogger(log_dir=tmpdir, enable=True)

        def bad_callback(event):
            raise RuntimeError("订阅者崩溃")

        logger.subscribe(bad_callback)

        logger.emit("test_event", {"key": "value"})

        logger._close_jsonl_file()


def test_10_container_error_hierarchy():
    """测试容器异常层级"""
    startup_err = ContainerStartupError(
        "daemon 启动失败",
        container_id="c1",
        agent_id="a1",
        fatal=True,
    )
    assert isinstance(startup_err, AgentError)
    assert startup_err.layer == "tool"
    assert startup_err.fatal is True
    assert startup_err.context["container_id"] == "c1"

    state_err = ContainerStateError(
        "容器状态异常",
        container_id="c2",
        agent_id="a2",
        fatal=True,
    )
    assert isinstance(state_err, AgentError)


if __name__ == "__main__":
    tests = [
        test_1_agent_error_add_context,
        test_2_agent_error_str_output,
        test_3_exception_chain,
        test_4_exception_chain_wrapping,
        test_5_agent_error_to_dict,
        test_6_non_fatal_flag,
        test_7_emit_error_jsonl_structure,
        test_8_emit_error_non_agent_error,
        test_9_notify_does_not_silently_swallow,
        test_10_container_error_hierarchy,
    ]

    passed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS: {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {test.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR: {test.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{passed}/{len(tests)} 测试通过")
