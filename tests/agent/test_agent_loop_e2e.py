"""End-to-End Tests for Agent-Loop with full monitoring."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import pytest

from agent.agent_loop import AgentLoop
from tests.agent.test_cases import TestCase, TEST_CASES, get_test_case
from tests.agent.test_monitor import TestMonitor

logger = logging.getLogger(__name__)


class AgentLoopE2ETest:
    """End-to-end test runner for Agent-Loop."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.monitor = TestMonitor(output_dir or Path("logs/e2e_tests"))

    async def run_test_case(self, test_case: TestCase) -> dict:
        """Run a single test case with full monitoring.

        Args:
            test_case: The test case to run

        Returns:
            Dict containing test results and log file path
        """
        self.monitor.start_test({
            "name": test_case.name,
            "difficulty": test_case.difficulty,
            "user_input": test_case.user_input,
            "expected_tools": test_case.expected_tools,
            "expected_skills": test_case.expected_skills,
            "validation_criteria": test_case.validation_criteria,
        })

        agent = AgentLoop(max_iterations=10)

        issues = []
        iteration_count = 0
        current_phase = "PLAN"

        try:
            result = await asyncio.wait_for(
                self._run_with_monitoring(agent, test_case, issues),
                timeout=test_case.timeout_seconds
            )
            success = True
        except asyncio.TimeoutError:
            result = "测试超时"
            success = False
            issues.append(f"测试超时 ({test_case.timeout_seconds}s)")
        except Exception as e:
            result = f"执行错误: {e}"
            success = False
            issues.append(str(e))

        log_path = self.monitor.end_test(
            success=success,
            final_response=result,
            issues=issues,
        )

        validation_result = self._validate_result(test_case, success, issues)

        return {
            "test_case": test_case.name,
            "success": validation_result["success"],
            "final_response": result,
            "log_path": str(log_path),
            "issues": validation_result["issues"],
            "criteria_met": validation_result["criteria_met"],
        }

    async def _run_with_monitoring(self, agent: AgentLoop, test_case: TestCase) -> str:
        """Run agent with monitoring hooks."""
        print(f"\n{'='*60}")
        print(f"开始测试: {test_case.name}")
        print(f"难度: {test_case.difficulty}")
        print(f"目标: {test_case.user_input}")
        print(f"{'='*60}")

        original_run = agent.run

        async def monitored_run(user_input: str, reset: bool = False) -> str:
            iteration_count = 0

            async def wrapped_run(user_input: str, reset: bool = False) -> str:
                nonlocal iteration_count

                self._log_initial_state(agent, test_case)

                result = await original_run(user_input, reset)

                iteration_count = agent.state.iteration_count
                self._log_final_state(agent, test_case, iteration_count)

                return result

            return await wrapped_run(user_input, reset)

        agent.run = monitored_run
        return await agent.run(test_case.user_input, reset=True)

    def _log_initial_state(self, agent: AgentLoop, test_case: TestCase) -> None:
        """Log initial state before execution."""
        phase_str = agent.state.phase.value
        prompt = {
            "layer_0": "Identity layer",
            "layer_1": f"Phase: {phase_str}",
            "full_prompt": agent.prompt_builder.build(phase_str, {
                "objective": test_case.user_input,
            }),
            "token_estimate": 0,
        }

        self.monitor.log_iteration(
            iteration=0,
            phase=phase_str,
            prompt=prompt,
            tool_calls=[],
            model_output={"content": "", "tool_calls": [], "timing_ms": 0},
        )

    def _log_final_state(
        self,
        agent: AgentLoop,
        test_case: TestCase,
        iteration_count: int,
    ) -> None:
        """Log final state after execution."""
        for skill in agent.state.loaded_skills:
            self.monitor.log_skill_loaded(skill)

    def _validate_result(
        self,
        test_case: TestCase,
        success: bool,
        issues: list[str],
    ) -> dict:
        """Validate test result against criteria."""
        criteria_met = []
        test_log = self.monitor.get_current_test_log()

        if test_log is None:
            return {
                "success": False,
                "issues": ["No test log available"],
                "criteria_met": [],
            }

        skills_loaded = test_log.metrics.skills_loaded
        final_response = test_log.summary.final_response or ""
        final_response_lower = final_response.lower()

        for criterion in test_case.validation_criteria:
            criterion_lower = criterion.lower()
            met = False

            if "加载" in criterion and "skill" in criterion_lower:
                for skill in test_case.expected_skills:
                    if skill in skills_loaded:
                        met = True
                        break
                if not met and len(skills_loaded) > 0:
                    met = True
            elif "执行" in criterion or "命令" in criterion:
                if "opencli" in final_response_lower or "搜索" in final_response_lower or "结果" in final_response_lower:
                    met = True
                elif len(final_response) > 100:
                    met = True
            elif "返回" in criterion or "列表" in criterion:
                if final_response:
                    met = len(final_response) > 50
            elif "多轮" in criterion:
                met = test_log.metrics.total_iterations > 1 or len(final_response) > 200
            elif "筛选" in criterion or "总结" in criterion:
                if "推荐" in final_response or "建议" in final_response or "总结" in final_response:
                    met = True
            elif "对比" in criterion or "分析" in criterion:
                if "对比" in final_response or "分析" in final_response or "比较" in final_response:
                    met = True
                elif len(final_response) > 100:
                    met = True
            else:
                met = success

            criteria_met.append({"criterion": criterion, "met": met})

        all_criteria_met = all(c["met"] for c in criteria_met)

        return {
            "success": success and all_criteria_met,
            "issues": issues,
            "criteria_met": criteria_met,
        }


@pytest.fixture
def e2e_test_runner():
    return AgentLoopE2ETestRunner()


class AgentLoopE2ETestRunner:
    """Test runner for pytest integration."""

    def __init__(self):
        self.output_dir = Path("logs/e2e_tests")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def run_test(self, test_case_name: str) -> dict:
        test_case = get_test_case(test_case_name)
        if test_case is None:
            raise ValueError(f"Test case '{test_case_name}' not found")

        runner = AgentLoopE2ETest(self.output_dir)
        return await runner.run_test_case(test_case)


@pytest.mark.asyncio
async def test_bilibili_hot_videos():
    """Test: B站热门视频获取（简单）"""
    runner = AgentLoopE2ETestRunner()
    result = await runner.run_test("bilibili_hot_videos")
    assert result["success"], f"Test failed: {result['issues']}"


@pytest.mark.asyncio
async def test_zhihu_hot_topics():
    """Test: 知乎热门话题获取（简单）"""
    runner = AgentLoopE2ETestRunner()
    result = await runner.run_test("zhihu_hot_topics")
    assert result["success"], f"Test failed: {result['issues']}"


@pytest.mark.asyncio
async def test_hackernews_top_stories():
    """Test: Hacker News 热门文章（简单）"""
    runner = AgentLoopE2ETestRunner()
    result = await runner.run_test("hackernews_top_stories")
    assert result["success"], f"Test failed: {result['issues']}"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_xiaohongshu_curling_iron():
    """Test: 小红书卷发棒推荐（困难）"""
    runner = AgentLoopE2ETestRunner()
    result = await runner.run_test("xiaohongshu_curling_iron")
    assert result["success"], f"Test failed: {result['issues']}"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_github_python_trending():
    """Test: GitHub Python 热门项目（中等）"""
    runner = AgentLoopE2ETestRunner()
    result = await runner.run_test("github_python_trending")
    assert result["success"], f"Test failed: {result['issues']}"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_multi_platform_comparison():
    """Test: 跨平台对比分析（困难）"""
    runner = AgentLoopE2ETestRunner()
    result = await runner.run_test("multi_platform_comparison")
    assert result["success"], f"Test failed: {result['issues']}"


if __name__ == "__main__":
    import sys

    async def main():
        test_name = sys.argv[1] if len(sys.argv) > 1 else "bilibili_hot_videos"
        runner = AgentLoopE2ETestRunner()
        result = await runner.run_test(test_name)
        print(f"\nTest: {result['test_case']}")
        print(f"Success: {result['success']}")
        print(f"Log: {result['log_path']}")
        if result['issues']:
            print(f"Issues: {result['issues']}")
        print(f"\nCriteria Met:")
        for c in result['criteria_met']:
            status = "✓" if c['met'] else "✗"
            print(f"  {status} {c['criterion']}")

    asyncio.run(main())
