"""
Session恢复真实场景测试

测试完整的session中断恢复流程，包括：
1. 主Agent状态恢复
2. Task数据恢复
3. SubAgent状态恢复（如果支持）
"""
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.state import AgentState, AgentPhase
from agent.tasks.models import TaskRecord, TaskStatus
from agent.session.logger import InteractionLogger


class TestRealSessionRecovery:
    """真实场景Session恢复测试"""

    def test_session_file_format_and_recovery(self, tmp_path):
        """测试session文件格式和恢复流程"""
        session_file = tmp_path / "test_session.jsonl"
        
        # 模拟真实的session事件流
        events = []
        
        # 1. 初始状态
        initial_state = AgentState()
        initial_state.phase = AgentPhase.COLLECT
        initial_state.iteration_count = 1
        events.append({
            "event_type": "state_change",
            "timestamp": datetime.now().isoformat(),
            "data": {"state": initial_state.to_dict()}
        })
        
        # 2. 添加一些工具调用
        events.append({
            "event_type": "tool_call",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "tool_name": "load_skill_category",
                "arguments": {"category_name": "feishu"}
            }
        })
        
        # 3. 阶段转换
        state_after_collect = AgentState()
        state_after_collect.phase = AgentPhase.PLAN
        state_after_collect.iteration_count = 3
        state_after_collect.loaded_categories = {"feishu"}
        state_after_collect.loaded_skills = {"feishu.get_doc"}
        events.append({
            "event_type": "state_change",
            "timestamp": datetime.now().isoformat(),
            "data": {"state": state_after_collect.to_dict()}
        })
        
        # 4. 添加Task
        state_with_task = AgentState()
        state_with_task.phase = AgentPhase.EXECUTE
        state_with_task.iteration_count = 5
        state_with_task.current_task_id = 1
        task = TaskRecord(
            id=1,
            subject="搜索飞书文档",
            description="搜索并获取飞书文档内容",
            status=TaskStatus.IN_PROGRESS,
            owner="main_agent"
        )
        state_with_task.tasks.append(task)
        state_with_task.set_todo_list([
            {"id": "1", "content": "搜索文档", "status": "completed"},
            {"id": "2", "content": "获取内容", "status": "in_progress"}
        ])
        events.append({
            "event_type": "state_change",
            "timestamp": datetime.now().isoformat(),
            "data": {"state": state_with_task.to_dict()}
        })
        
        # 写入session文件
        with open(session_file, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        
        # 模拟wake恢复流程
        loaded_events = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    loaded_events.append(json.loads(line))
        
        # 查找最后的state_change事件
        last_state_data = None
        for event in reversed(loaded_events):
            if event.get("event_type") == "state_change":
                last_state_data = event.get("data", {}).get("state")
                break
        
        assert last_state_data is not None
        
        # 恢复状态
        restored_state = AgentState.from_dict(last_state_data)
        
        # 验证恢复结果
        assert restored_state.phase == AgentPhase.EXECUTE
        assert restored_state.iteration_count == 5
        assert restored_state.current_task_id == 1
        assert len(restored_state.tasks) == 1
        assert restored_state.tasks[0].subject == "搜索飞书文档"
        assert len(restored_state.todos.items) == 2
        assert restored_state.todos.items[0]["status"] == "completed"
        assert restored_state.todos.items[1]["status"] == "in_progress"

    def test_subagent_state_in_session(self, tmp_path):
        """测试SubAgent状态是否被记录到session中"""
        session_file = tmp_path / "session_with_subagent.jsonl"
        
        # 主Agent状态
        main_state = AgentState()
        main_state.agent_id = "main"
        main_state.agent_depth = 0
        main_state.phase = AgentPhase.EXECUTE
        main_state.iteration_count = 3
        
        # 模拟spawn_agents工具调用
        events = [
            {
                "event_type": "state_change",
                "timestamp": datetime.now().isoformat(),
                "data": {"state": main_state.to_dict()}
            },
            {
                "event_type": "tool_call",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "tool_name": "spawn_agents",
                    "arguments": {
                        "agents": [
                            {"task": "搜索文档", "description": "搜索飞书文档"},
                            {"task": "分析内容", "description": "分析文档内容"}
                        ]
                    }
                }
            }
        ]
        
        # SubAgent状态（关键问题：当前是否支持？）
        subagent_state = AgentState()
        subagent_state.agent_id = "subagent_001"
        subagent_state.agent_depth = 1
        subagent_state.assigned_task = "搜索文档"
        subagent_state.phase = AgentPhase.EXECUTE
        subagent_state.set_subagent_todos([
            {"id": "s1", "content": "执行搜索", "status": "in_progress"}
        ])
        
        # 尝试添加SubAgent状态事件
        events.append({
            "event_type": "subagent_state",
            "timestamp": datetime.now().isoformat(),
            "agent_id": "subagent_001",
            "data": {"state": subagent_state.to_dict()}
        })
        
        # 写入session文件
        with open(session_file, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        
        # 读取并验证SubAgent状态
        loaded_events = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    loaded_events.append(json.loads(line))
        
        # 查找SubAgent状态
        subagent_events = [
            e for e in loaded_events 
            if e.get("event_type") == "subagent_state"
        ]
        
        # 验证SubAgent状态被记录
        assert len(subagent_events) == 1
        subagent_data = subagent_events[0]["data"]["state"]
        restored_subagent = AgentState.from_dict(subagent_data)
        
        assert restored_subagent.agent_id == "subagent_001"
        assert restored_subagent.agent_depth == 1
        assert restored_subagent.assigned_task == "搜索文档"
        assert len(restored_subagent.subagent_todos.items) == 1

    def test_multiple_subagents_recovery(self, tmp_path):
        """测试多个SubAgent的恢复"""
        session_file = tmp_path / "multi_subagent_session.jsonl"
        
        # 主Agent状态
        main_state = AgentState()
        main_state.agent_id = "main"
        main_state.phase = AgentPhase.EXECUTE
        
        events = [
            {
                "event_type": "state_change",
                "timestamp": datetime.now().isoformat(),
                "data": {"state": main_state.to_dict()}
            }
        ]
        
        # 创建多个SubAgent状态
        subagent_configs = [
            {"id": "sub_1", "task": "搜索飞书文档", "status": "completed"},
            {"id": "sub_2", "task": "分析文档内容", "status": "in_progress"},
            {"id": "sub_3", "task": "生成报告", "status": "pending"},
        ]
        
        for config in subagent_configs:
            sub_state = AgentState()
            sub_state.agent_id = config["id"]
            sub_state.agent_depth = 1
            sub_state.assigned_task = config["task"]
            sub_state.phase = AgentPhase.EXECUTE
            sub_state.set_subagent_todos([
                {"id": "t1", "content": config["task"], "status": config["status"]}
            ])
            
            events.append({
                "event_type": "subagent_state",
                "timestamp": datetime.now().isoformat(),
                "agent_id": config["id"],
                "data": {"state": sub_state.to_dict()}
            })
        
        # 写入session文件
        with open(session_file, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        
        # 恢复所有SubAgent状态
        loaded_events = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    loaded_events.append(json.loads(line))
        
        subagent_events = [
            e for e in loaded_events 
            if e.get("event_type") == "subagent_state"
        ]
        
        # 验证所有SubAgent都被恢复
        assert len(subagent_events) == 3
        
        restored_subagents = {}
        for event in subagent_events:
            state = AgentState.from_dict(event["data"]["state"])
            restored_subagents[state.agent_id] = state
        
        assert "sub_1" in restored_subagents
        assert "sub_2" in restored_subagents
        assert "sub_3" in restored_subagents
        
        # 验证状态正确
        assert restored_subagents["sub_1"].assigned_task == "搜索飞书文档"
        assert restored_subagents["sub_2"].assigned_task == "分析文档内容"
        assert restored_subagents["sub_3"].assigned_task == "生成报告"


class TestCurrentSubAgentRecoveryLimitation:
    """测试当前SubAgent恢复的限制"""

    def test_current_wake_does_not_recover_subagents(self, tmp_path):
        """测试当前wake方法不恢复SubAgent状态
        
        这是一个负面测试，验证当前实现的限制
        """
        session_file = tmp_path / "session.jsonl"
        
        # 主Agent状态
        main_state = AgentState()
        main_state.agent_id = "main"
        main_state.phase = AgentPhase.EXECUTE
        
        # SubAgent状态
        sub_state = AgentState()
        sub_state.agent_id = "sub_1"
        sub_state.agent_depth = 1
        sub_state.assigned_task = "测试任务"
        
        events = [
            {
                "event_type": "state_change",
                "timestamp": datetime.now().isoformat(),
                "data": {"state": main_state.to_dict()}
            },
            {
                "event_type": "subagent_state",
                "timestamp": datetime.now().isoformat(),
                "agent_id": "sub_1",
                "data": {"state": sub_state.to_dict()}
            }
        ]
        
        with open(session_file, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        
        # 模拟当前wake方法的逻辑
        loaded_events = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    loaded_events.append(json.loads(line))
        
        # 当前wake只查找state_change事件
        last_state_data = None
        for event in reversed(loaded_events):
            if event.get("event_type") == "state_change":
                last_state_data = event.get("data", {}).get("state")
                break
        
        # 验证：只能恢复主Agent状态，SubAgent状态被忽略
        assert last_state_data is not None
        restored_main = AgentState.from_dict(last_state_data)
        assert restored_main.agent_id == "main"
        
        # SubAgent状态存在于文件中，但当前wake方法不会加载它
        subagent_events = [
            e for e in loaded_events 
            if e.get("event_type") == "subagent_state"
        ]
        assert len(subagent_events) == 1  # SubAgent状态在文件中
        
        # 但wake方法不会处理它
        # 这是当前实现的限制，需要改进


class TestImprovedSessionRecovery:
    """改进的Session恢复测试"""

    def test_recover_all_agent_states(self, tmp_path):
        """测试恢复所有Agent状态（主Agent + SubAgents）"""
        session_file = tmp_path / "improved_session.jsonl"
        
        # 创建事件
        events = []
        
        # 主Agent状态
        main_state = AgentState()
        main_state.agent_id = "main"
        main_state.phase = AgentPhase.EXECUTE
        main_state.iteration_count = 5
        
        events.append({
            "event_type": "state_change",
            "timestamp": datetime.now().isoformat(),
            "data": {"state": main_state.to_dict()}
        })
        
        # SubAgent状态
        for i in range(2):
            sub_state = AgentState()
            sub_state.agent_id = f"sub_{i+1}"
            sub_state.agent_depth = 1
            sub_state.assigned_task = f"任务{i+1}"
            
            events.append({
                "event_type": "subagent_state",
                "timestamp": datetime.now().isoformat(),
                "agent_id": f"sub_{i+1}",
                "data": {"state": sub_state.to_dict()}
            })
        
        # 写入文件
        with open(session_file, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        
        # 改进的恢复逻辑：恢复所有Agent状态
        def recover_all_agents(session_file: Path) -> dict:
            """恢复主Agent和所有SubAgent状态"""
            events = []
            with open(session_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
            
            result = {
                "main": None,
                "subagents": {}
            }
            
            for event in events:
                if event.get("event_type") == "state_change":
                    result["main"] = AgentState.from_dict(
                        event["data"]["state"]
                    )
                elif event.get("event_type") == "subagent_state":
                    agent_id = event["agent_id"]
                    result["subagents"][agent_id] = AgentState.from_dict(
                        event["data"]["state"]
                    )
            
            return result
        
        # 执行恢复
        recovered = recover_all_agents(session_file)
        
        # 验证
        assert recovered["main"] is not None
        assert recovered["main"].agent_id == "main"
        assert len(recovered["subagents"]) == 2
        assert "sub_1" in recovered["subagents"]
        assert "sub_2" in recovered["subagents"]
        assert recovered["subagents"]["sub_1"].assigned_task == "任务1"
        assert recovered["subagents"]["sub_2"].assigned_task == "任务2"
