"""真实环境测试 - 小红书卷发棒搜索（困难测试用例）"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.agent_loop import AgentLoop
from agent.state import AgentState, AgentPhase


def _event_handler(event: dict):
    """订阅Handler - 实时输出思考/回复/工具调用"""
    event_type = event.get("event", "")
    data = event.get("data", {})

    if event_type == "llm_response":
        reasoning = data.get("reasoning_content", "")
        content = data.get("content", "")
        tcs = data.get("tool_calls", [])
        rnd = data.get("iteration", "?")
        if reasoning:
            print(f"\n{'─' * 60}")
            print(f"[思考] Round {rnd}:")
            print(f"{reasoning[:2000]}{'...(truncated)' if len(reasoning) > 2000 else ''}")
        if content:
            print(f"\n{'─' * 60}")
            print(f"[回复] Round {rnd}:")
            print(f"{content[:2000]}{'...(truncated)' if len(content) > 2000 else ''}")
        if tcs:
            print(f"\n{'─' * 60}")
            print(f"[工具调用] Round {rnd} ({len(tcs)} calls):")
            for tc in tcs:
                name = tc.get("name", tc.get("function", {}).get("name", "?"))
                args = tc.get("arguments", tc.get("function", {}).get("arguments", "{}"))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                args_str = json.dumps(args, ensure_ascii=False, indent=2)[:500]
                print(f"  -> {name}: {args_str}")

    elif event_type == "tool_result":
        tr = data.get("result", {})
        tool_name = data.get("tool_name", "?")
        ttype = tr.get("type", "unknown") if isinstance(tr, dict) else "?"
        summary = tr.get("result_summary", tr.get("message", ""))[:200] if isinstance(tr, dict) else str(tr)[:200]
        print(f"\n[结果] {tool_name}: [{ttype}] {summary}")


class FirstRoundContextCapture:
    """第一轮上下文捕获器"""
    
    def __init__(self):
        self.first_round_context = None
        self.first_round_system_prompt = None
        self.first_round_tools = None
        self._captured = False
    
    def capture_from_agent(self, agent: AgentLoop):
        """从 agent 实例捕获第一轮上下文"""
        if self._captured:
            return
        
        self.first_round_context = agent._context.copy() if hasattr(agent, '_context') else []
        if hasattr(agent, 'prompt_builder') and agent.prompt_builder:
            self.first_round_system_prompt = agent.prompt_builder.build(phase="DEFAULT")
        if hasattr(agent, 'state') and agent.state:
            self.first_round_tools = agent.state.available_tools
        self._captured = True
    
    def export(self, output_dir: str = "./context_exports", session_id: str = None) -> str | None:
        """导出上下文到文件"""
        if not self.first_round_context:
            print("  无上下文可导出")
            return None
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"first_round_context_{session_id or 'unknown'}.json"
        export_file = output_path / filename
        
        export_data = {
            "context_messages": self.first_round_context,
            "context_count": len(self.first_round_context),
            "system_prompt": self.first_round_system_prompt,
            "system_prompt_length": len(self.first_round_system_prompt) if self.first_round_system_prompt else 0,
            "tools": self.first_round_tools,
            "tools_count": len(self.first_round_tools) if self.first_round_tools else 0,
        }
        
        with open(export_file, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        print(f"  第一轮上下文已导出至: {export_file}")
        return str(export_file)
    
    def print_summary(self):
        """打印上下文摘要"""
        if not self.first_round_context:
            print("  无上下文")
            return
        
        print(f"\n  上下文消息数: {len(self.first_round_context)}")
        for i, msg in enumerate(self.first_round_context):
            role = msg.get("role", "?")
            content = msg.get("content", "")
            preview = content[:100] + "..." if len(content) > 100 else content
            print(f"  [{i}] {role}: {preview}")
        
        if self.first_round_system_prompt:
            print(f"\n  System Prompt 长度: {len(self.first_round_system_prompt)}")
            print(f"  System Prompt 预览: {self.first_round_system_prompt[:200]}...")
        
        if self.first_round_tools:
            print(f"\n  工具数量: {len(self.first_round_tools)}")
            tool_names = [t.get("function", {}).get("name", t.get("name", "?")) for t in self.first_round_tools]
            print(f"  工具列表: {tool_names}")


def _export_first_round_context(log_path: str, output_dir: str = "./context_exports"):
    """导出第一轮上下文到文件"""
    if not log_path:
        print("  无日志文件")
        return None

    log_file = Path(log_path)
    if not log_file.exists():
        print(f"  日志文件不存在: {log_path}")
        return None

    first_round_context = None
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                event_type = event.get("event_type", "")
                if event_type == "iteration" and event.get("data", {}).get("iteration") == 1:
                    first_round_context = event.get("data", {}).get("context_messages", [])
                    break
            except json.JSONDecodeError:
                continue

    if not first_round_context:
        print("  未找到第一轮上下文")
        return None

    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 导出上下文
    export_file = output_path / f"first_round_context_{log_file.stem}.json"
    with open(export_file, "w", encoding="utf-8") as f:
        json.dump(first_round_context, f, ensure_ascii=False, indent=2)

    print(f"  第一轮上下文已导出至: {export_file}")
    return str(export_file)


def _print_subagent_log_summary(log_path: str):
    """读取并打印subagent日志摘要"""
    if not log_path:
        print("  无日志文件")
        return

    log_file = Path(log_path)
    if not log_file.exists():
        print(f"  日志文件不存在: {log_path}")
        return

    subagent_events = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                event_type = event.get("event_type", "")
                if event_type.startswith("subagent_"):
                    subagent_events.append(event)
            except json.JSONDecodeError:
                continue

    if not subagent_events:
        print("  无subagent事件记录")
        return

    print(f"\n  发现 {len(subagent_events)} 个subagent事件:")
    print(f"  {'─' * 50}")

    for event in subagent_events:
        event_type = event.get("event_type", "")
        data = event.get("data", {})
        event_id = event.get("event_id", "")

        if event_type == "subagent_created":
            print(f"  [{event_id}] subagent_created:")
            print(f"    agent_id: {data.get('agent_id')}")
            print(f"    task: {data.get('task', '')[:100]}...")
            print(f"    loaded_skills: {data.get('loaded_skills', [])}")
            print(f"    parent_action_history_count: {data.get('parent_action_history_count', 0)}")
            print(f"    parent_agent_depth: {data.get('parent_agent_depth', 0)}")

        elif event_type == "subagent_context":
            print(f"  [{event_id}] subagent_context:")
            print(f"    available_tools: {data.get('available_tools', [])}")
            print(f"    parent_action_history_count: {data.get('parent_action_history_count', 0)}")
            print(f"    parent_action_history entries: {len(data.get('parent_action_history', []))}")
            skill_keys = list(data.get('parent_skill_contents', {}).keys())
            print(f"    skill_contents keys: {skill_keys}")
            print(f"    system_prompt length: {len(data.get('system_prompt', ''))}")

        elif event_type == "subagent_iteration":
            print(f"  [{event_id}] subagent_iteration:")
            print(f"    iteration: {data.get('iteration')}")
            print(f"    context_messages_count: {data.get('context_messages_count', 0)}")
            print(f"    action_history_count: {data.get('action_history_count', 0)}")

        elif event_type == "subagent_completed":
            print(f"  [{event_id}] subagent_completed:")
            print(f"    agent_id: {data.get('agent_id')}")
            print(f"    status: {data.get('status')}")
            print(f"    total_iterations: {data.get('total_iterations', 0)}")
            print(f"    actions_count: {data.get('actions_count', 0)}")
            print(f"    summary: {data.get('summary', '')[:200]}...")
            print(f"    final_todos: {data.get('final_todos', [])}")

        elif event_type == "subagent_failed":
            print(f"  [{event_id}] subagent_failed:")
            print(f"    agent_id: {data.get('agent_id')}")
            print(f"    reason: {data.get('reason')}")
            print(f"    error: {data.get('error', '')[:200]}")
            print(f"    action_history_count: {data.get('action_history_count', 0)}")

    print(f"  {'─' * 50}")


async def test_xiaohongshu_hard_case():
    """测试小红书卷发棒搜索（困难测试用例）"""
    
    print("=" * 70)
    print("真实环境测试：小红书卷发棒搜索（困难测试用例）")
    print("=" * 70)
    
    test_input = "先在小红书上寻找卷发棒的信息，然后根据价格，品牌，在我的飞书中创建一张表格，我建议你使用subagent负载一部分任务，并且使用opencli完成所有网页任务。"
    test_website_query = "看看这个网页文章在说什么：https://mp.weixin.qq.com/s/mQUeL-NIPurEcAV7w7kILg，并给我详细的信息"
    print(f"\n测试输入: {test_website_query}")
    print(f"预期行为:")
    print(f"   - 成功加载 smart-search skill")
    print(f"   - 执行搜索相关命令")
    print(f"   - 筛选和总结结果")
    print(f"   - 返回推荐列表，包含产品名称、价格、评价")
    print(f"   - 多轮迭代完成复杂任务")
    print("-" * 70)
    
    agent = AgentLoop(max_iterations=30, enable_logging=True, mode="default")
    agent._interaction_logger.subscribe(_event_handler)
    
    context_capture = FirstRoundContextCapture()
    
    try:
        print("\n开始执行...")
        response = await agent.run(test_website_query, reset=True)
        
        context_capture.capture_from_agent(agent)
        
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
        print("第一轮上下文")
        print("=" * 70)
        context_capture.print_summary()
        context_capture.export(session_id=agent._interaction_logger.session_id)

        print("\n" + "=" * 70)
        print("Subagent 日志数据")
        print("=" * 70)
        _print_subagent_log_summary(log_path)
        
        print("\n" + "=" * 70)
        print("验证结果")
        print("=" * 70)
        
        validations = {
            "smart-search技能加载": "smart-search" in loaded_skills,
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


async def test_multiple_cases():
    """测试多个测试用例"""
    
    test_cases = [
        {
            "name": "小红书卷发棒搜索（困难）",
            "input": "帮我看看小红书上有哪些卷发棒值得购买",
            "expected_skill": "smart-search",
        },
        {
            "name": "B站热门视频（简单）",
            "input": "看看B站的热门视频有什么",
            "expected_skill": "smart-search",
        },
        {
            "name": "知乎热门话题（简单）",
            "input": "知乎上现在有什么热门话题",
            "expected_skill": "smart-search",
        },
    ]
    
    print("=" * 70)
    print("多测试用例真实环境测试")
    print("=" * 70)
    
    results = []
    
    for case in test_cases:
        print(f"\n{'='*70}")
        print(f"测试: {case['name']}")
        print(f"输入: {case['input']}")
        print("=" * 70)
        
        agent = AgentLoop(max_iterations=8, enable_logging=True, mode="default")
        agent._interaction_logger.subscribe(_event_handler)
        
        try:
            response = await agent.run(case['input'], reset=True)
            loaded_skills = agent.get_loaded_skills()
            state = agent.state
            
            skill_loaded = case['expected_skill'] in loaded_skills
            status = "[OK]" if skill_loaded else "[FAIL]"
            
            print(f"\n{status} 结果: 技能加载={skill_loaded}")
            print(f"   迭代次数: {state.iteration_count}, 响应长度: {len(response) if response else 0}")
            
            results.append({
                "name": case['name'],
                "success": skill_loaded,
                "iterations": state.iteration_count,
                "response_length": len(response) if response else 0,
            })
            
        except Exception as e:
            print(f"\n执行出错: {e}")
            results.append({
                "name": case['name'],
                "success": False,
                "error": str(e),
            })
    
    print("\n" + "=" * 70)
    print("测试汇总")
    print("=" * 70)
    
    passed = sum(1 for r in results if r['success'])
    total = len(results)
    
    for r in results:
        status = "[OK]" if r['success'] else "[FAIL]"
        print(f"{status} {r['name']}")
    
    print(f"\n通过率: {passed}/{total} ({passed/total*100:.0f}%)")
    
    return results


async def main():
    print("#" * 70)
    print("# Prompt架构重构 - 真实环境测试")
    print("#" * 70)
    
    print("\n### 测试1: 单个测试用例 ###")
    await test_xiaohongshu_hard_case()
    
    # print("\n### 测试2: 多个测试用例 ###")
    # await test_multiple_cases()


if __name__ == "__main__":
    asyncio.run(main())
