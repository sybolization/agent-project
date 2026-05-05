"""
SubAgent状态恢复测试

测试SubAgent的状态管理和恢复功能
"""
import json
from pathlib import Path
from datetime import datetime

import pytest

from agent.state import AgentState, AgentPhase


class TestSubAgentStateFields:
    """SubAgent状态字段测试"""

    def test_subagent_state_has_agent_id(self):
        """测试SubAgent状态包含agent_id字段"""
        state = AgentState()
        state.agent_id = "subagent_001"
        state.agent_depth = 1
        state.assigned_task = "执行搜索任务"

        data = state.to_dict()

        assert "agent_id" in data
        assert data["agent_id"] == "subagent_001"
        assert "agent_depth" in data
        assert data["agent_depth"] == 1
        assert "assigned_task" in data
        assert data["assigned_task"] == "执行搜索任务"

    def test_subagent_state_restores_agent_info(self):
        """测试SubAgent状态恢复agent信息"""
        original = AgentState()
        original.agent_id = "subagent_002"
        original.agent_depth = 2
        original.assigned_task = "分析数据"

        data = original.to_dict()
        restored = AgentState.from_dict(data)

        assert restored.agent_id == "subagent_002"
        assert restored.agent_depth == 2
        assert restored.assigned_task == "分析数据"


class TestMultiSubAgentStateIsolation:
    """多SubAgent状态隔离测试"""

    def test_multiple_subagents_have_separate_states(self):
        """测试多个SubAgent有独立的状态"""
        # 主Agent状态
        main_state = AgentState()
        main_state.agent_id = "main"
        main_state.agent_depth = 0
        main_state.phase = AgentPhase.EXECUTE

        # SubAgent 1状态
        sub1_state = AgentState()
        sub1_state.agent_id = "sub_1"
        sub1_state.agent_depth = 1
        sub1_state.assigned_task = "任务A"

        # SubAgent 2状态
        sub2_state = AgentState()
        sub2_state.agent_id = "sub_2"
        sub2_state.agent_depth = 1
        sub2_state.assigned_task = "任务B"

        # 验证状态独立
        assert main_state.agent_id != sub1_state.agent_id
        assert sub1_state.assigned_task != sub2_state.assigned_task

        # 验证序列化后仍然独立
        main_data = main_state.to_dict()
        sub1_data = sub1_state.to_dict()
        sub2_data = sub2_state.to_dict()

        assert main_data["agent_id"] == "main"
        assert sub1_data["agent_id"] == "sub_1"
        assert sub2_data["agent_id"] == "sub_2"

    def test_subagent_todos_isolated(self):
        """测试SubAgent的todos独立"""
        # 主Agent有todos
        main_state = AgentState()
        main_state.agent_id = "main"
        main_state.set_todo_list([
            {"id": "1", "content": "主任务1", "status": "pending"},
            {"id": "2", "content": "主任务2", "status": "pending"}
        ])

        # SubAgent有自己的todos
        sub_state = AgentState()
        sub_state.agent_id = "sub_1"
        sub_state.set_todo_list([
            {"id": "1", "content": "子任务1", "status": "completed"}
        ])

        # 验证独立
        assert len(main_state.todos.items) == 2
        assert len(sub_state.todos.items) == 1
        assert main_state.todos.items[0]["content"] == "主任务1"
        assert sub_state.todos.items[0]["content"] == "子任务1"


class TestSubAgentSessionAssociation:
    """SubAgent与主Session关联测试"""

    def test_subagent_can_be_traced_from_main(self, tmp_path):
        """测试SubAgent可从主Session追溯"""
        session_file = tmp_path / "session_with_subagents.jsonl"

        # 模拟主Agent状态
        main_state = AgentState()
        main_state.agent_id = "main"
        main_state.agent_depth = 0
        # 使用loaded_skills来追踪spawned agents的能力
        main_state.loaded_skills.add("sub_1_skill")
        main_state.loaded_skills.add("sub_2_skill")

        # 写入主Agent状态
        main_event = {
            "event": "state_change",
            "timestamp": datetime.now().isoformat(),
            "data": main_state.to_dict()
        }
        with open(session_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(main_event, ensure_ascii=False) + "\n")

        # 模拟SubAgent状态
        sub_state = AgentState()
        sub_state.agent_id = "sub_1"
        sub_state.agent_depth = 1
        sub_state.assigned_task = "搜索任务"

        sub_event = {
            "event": "subagent_state",
            "timestamp": datetime.now().isoformat(),
            "agent_id": "sub_1",
            "data": sub_state.to_dict()
        }
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(sub_event, ensure_ascii=False) + "\n")

        # 读取并验证关联
        events = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                events.append(json.loads(line))

        # 验证主Agent状态
        main_event = events[0]
        assert main_event["data"]["agent_id"] == "main"
        assert main_event["data"]["agent_depth"] == 0

        # 验证SubAgent知道depth
        sub_event = events[1]
        assert sub_event["data"]["agent_depth"] == 1
        assert sub_event["data"]["assigned_task"] == "搜索任务"

    def test_subagent_action_history_preserved(self):
        """测试SubAgent的动作历史被保留"""
        state = AgentState()
        state.agent_id = "sub_1"

        # 添加动作历史
        state.add_action("opencli", {"command": "ls -la"}, "列出文件成功")
        state.add_action("opencli", {"command": "cat file.txt"}, "读取文件成功")

        # 序列化再反序列化
        data = state.to_dict()
        restored = AgentState.from_dict(data)

        # 验证动作历史
        assert len(restored.action_history) == 2
        assert restored.action_history[0]["tool_name"] == "opencli"
        assert restored.action_history[1]["tool_name"] == "opencli"


class TestSubAgentStateCreation:
    """SubAgent状态创建测试"""

    def test_create_subagent_state_from_parent(self):
        """测试从父Agent创建SubAgent状态"""
        parent_state = AgentState()
        parent_state.agent_id = "main"
        parent_state.agent_depth = 0
        parent_state.phase = AgentPhase.EXECUTE

        # 创建SubAgent状态
        sub_state = parent_state.create_subagent_state(
            agent_id="sub_1",
            assigned_task="执行搜索"
        )

        # 验证SubAgent状态
        assert sub_state.agent_id == "sub_1"
        assert sub_state.agent_depth == 1
        assert sub_state.assigned_task == "执行搜索"
        assert sub_state.is_subagent is True

        # 验证父状态未改变
        assert parent_state.agent_id == "main"
        assert parent_state.agent_depth == 0
        assert parent_state.is_subagent is False

    def test_nested_subagent_depth(self):
        """测试嵌套SubAgent的depth层级"""
        main_state = AgentState()
        main_state.agent_id = "main"
        main_state.agent_depth = 0

        # 创建第一层SubAgent
        sub1_state = main_state.create_subagent_state(
            agent_id="sub_1",
            assigned_task="任务1"
        )

        # 创建第二层SubAgent
        sub2_state = sub1_state.create_subagent_state(
            agent_id="sub_2",
            assigned_task="任务2"
        )

        # 验证depth层级
        assert main_state.agent_depth == 0
        assert sub1_state.agent_depth == 1
        assert sub2_state.agent_depth == 2


class TestSubAgentStateSerialization:
    """SubAgent状态序列化测试"""

    def test_subagent_state_serialization_roundtrip(self):
        """测试SubAgent状态序列化往返"""
        original = AgentState()
        original.agent_id = "sub_test"
        original.agent_depth = 1
        original.assigned_task = "测试任务"
        original.phase = AgentPhase.EXECUTE
        original.iteration_count = 5
        original.completed_steps = 3

        # 添加一些数据
        original.loaded_skills.add("test_skill")
        original.set_todo_list([
            {"id": "1", "content": "待办1", "status": "completed"},
            {"id": "2", "content": "待办2", "status": "pending"}
        ])
        original.add_action("opencli", {"command": "test"}, "测试结果")

        # 序列化
        data = original.to_dict()

        # 反序列化
        restored = AgentState.from_dict(data)

        # 验证所有字段
        assert restored.agent_id == original.agent_id
        assert restored.agent_depth == original.agent_depth
        assert restored.assigned_task == original.assigned_task
        assert restored.phase == original.phase
        assert restored.iteration_count == original.iteration_count
        assert restored.completed_steps == original.completed_steps
        assert restored.loaded_skills == original.loaded_skills
        assert len(restored.todos.items) == len(original.todos.items)
        assert len(restored.action_history) == len(original.action_history)

    def test_subagent_todos_preserved_in_serialization(self):
        """测试SubAgent的todos在序列化中保留"""
        state = AgentState()
        state.agent_id = "sub_1"
        state.agent_depth = 1

        # 设置subagent_todos
        state.set_subagent_todos([
            {"id": "s1", "content": "子任务1", "status": "pending"},
            {"id": "s2", "content": "子任务2", "status": "completed"}
        ])

        # 序列化和反序列化
        data = state.to_dict()
        restored = AgentState.from_dict(data)

        # 验证subagent_todos
        assert len(restored.subagent_todos.items) == 2
        assert restored.subagent_todos.items[0]["content"] == "子任务1"
        assert restored.subagent_todos.items[1]["status"] == "completed"
