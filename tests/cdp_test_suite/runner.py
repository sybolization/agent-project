"""CDP Test Suite Runner - Test Execution Framework

Usage:
    cd "d:\项目\quick capture\web-research-bot"
    uv run python -m tests.cdp_test_suite.runner
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.agent_loop import AgentLoop
from agent.state import AgentPhase
from agent.tools.manager import get_tool_manager
from agent.skills.manager import SkillManager


@dataclass
class TestCase:
    """Test case data class"""
    test_id: str
    name: str
    input: str
    success_criteria: list[str]
    description: str = ""
    expected_tools: list[str] = field(default_factory=list)
    disabled_tools: list[str] = field(default_factory=list)
    disabled_skill_categories: list[str] = field(default_factory=list)
    chrome_profile: Optional[str] = None
    max_iterations: int = 15
    timeout: int = 300
    enable_screenshot: bool = False


@dataclass
class TestResult:
    """Test execution result"""
    test_id: str
    name: str
    success: bool
    iterations: int
    phase: str
    response_length: int
    criteria_results: dict[str, bool]
    loaded_skills: list[str]
    log_path: Optional[str] = None
    error: Optional[str] = None
    chrome_user_data_dir: Optional[str] = None
    execution_time: float = 0.0


class TestRunner:
    """Test execution framework for CDP Browser Harness tests"""

    def __init__(self, test_cases_path: Optional[Path] = None):
        """Initialize test runner

        Args:
            test_cases_path: Path to test_cases.json file
        """
        if test_cases_path is None:
            test_cases_path = Path(__file__).parent / "test_cases.json"
        self.test_cases_path = test_cases_path
        self.results: list[TestResult] = []

    def load_test_cases(self) -> list[TestCase]:
        """Load test cases from test_cases.json

        Returns:
            List of TestCase objects
        """
        if not self.test_cases_path.exists():
            raise FileNotFoundError(f"Test cases file not found: {self.test_cases_path}")

        with open(self.test_cases_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        test_suite = data.get("test_suite", {})
        tests_data = test_suite.get("tests", [])

        test_cases = []
        for test_data in tests_data:
            test_case = TestCase(
                test_id=test_data["test_id"],
                name=test_data["name"],
                input=test_data["input"],
                success_criteria=test_data["success_criteria"],
                description=test_data.get("description", ""),
                expected_tools=test_data.get("expected_tools", []),
                disabled_tools=test_data.get("disabled_tools", []),
                disabled_skill_categories=test_data.get("disabled_skill_categories", []),
                chrome_profile=test_data.get("chrome_profile"),
                max_iterations=test_data.get("max_iterations", 15),
                timeout=test_data.get("timeout", 300),
                enable_screenshot=test_data.get("enable_screenshot", False),
            )
            test_cases.append(test_case)

        return test_cases

    def get_chrome_user_data_dir(self, profile: Optional[str]) -> str:
        """Get Chrome user data directory based on profile configuration

        Chrome 136+ no longer allows --remote-debugging-port on the default
        User Data directory. When profile="default", we copy key session files
        to a temp directory to preserve login state while enabling CDP.

        Args:
            profile: Chrome profile configuration
                - "default": Copy real profile to temp dir (preserves login state)
                - Custom path: Use specified path
                - None: Use temporary directory

        Returns:
            Chrome user data directory path
        """
        if profile == "default":
            real_user_data = Path(os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"))
            temp_dir = tempfile.mkdtemp(prefix="chrome_cdp_profile_")
            print(f"  Copying Chrome profile from {real_user_data}...")

            # 全量复制User Data目录，跳过大型缓存
            ignore_patterns = shutil.ignore_patterns(
                'Cache', 'Code Cache', 'GPUCache', 'DawnCache', 'ShaderCache',
                'Service Worker', 'blob_storage', 'Crashpad', 'GrShaderCache',
                'BrowserMetrics', 'component_crx_cache', 'MediaFoundationWidevineCdm',
                'OptimizationGuidePredictionModelDownloads',
                'Safe Browsing', 'Subresource Filter',
            )
            shutil.copytree(real_user_data, temp_dir, ignore=ignore_patterns, dirs_exist_ok=True)
            print(f"  Profile copied to {temp_dir}")
            return temp_dir
        elif profile is None:
            return tempfile.mkdtemp(prefix="chrome_cdp_test_")
        else:
            return os.path.expandvars(profile)

    @staticmethod
    def _find_chrome_executable() -> Optional[str]:
        """Find Chrome executable on Windows by priority

        Returns:
            Path to Chrome/Edge executable, or None if not found
        """
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate
        return None

    def _ensure_chrome_cdp_ready(self, profile: Optional[str]) -> None:
        """Ensure Chrome is running with CDP on port 9222

        Args:
            profile: Chrome profile configuration

        Raises:
            RuntimeError: If Chrome is not found or CDP port is not ready
        """
        # 1. Check if CDP is already running
        try:
            r = httpx.get("http://localhost:9222/json/version", timeout=3)
            if r.status_code == 200:
                print("Chrome CDP already running on port 9222")
                return
        except Exception:
            pass

        # 2-3. Get user data directory
        user_data_dir = self.get_chrome_user_data_dir(profile)

        # 4. Find Chrome executable
        chrome_path = self._find_chrome_executable()
        if chrome_path is None:
            raise RuntimeError("未找到Chrome或Edge浏览器，请确认已安装")

        # 5. Kill existing Chrome process if any (would block new Chrome with same user-data-dir)
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
        time.sleep(3)
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
        time.sleep(1)

        # 5b. Clean up Chrome lock files to prevent "didn't shut down correctly" dialog
        for lock_file in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
            lock_path = Path(user_data_dir) / lock_file
            if lock_path.exists():
                try:
                    lock_path.unlink()
                except Exception:
                    pass

        # 7. Launch Chrome with CDP via PowerShell (sandbox-safe)
        ps_cmd = (
            f"Start-Process -FilePath '{chrome_path}' "
            f"-ArgumentList '--remote-debugging-port=9222', "
            f"'--user-data-dir={user_data_dir}', "
            f"'--no-first-run', '--no-default-browser-check'"
        )
        subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True,
            timeout=15
        )
        time.sleep(2)

        # 8. Poll for CDP readiness (max 60 seconds, 1 second interval)
        import urllib.request as urllib_request
        for i in range(60):
            try:
                handler = urllib_request.ProxyHandler({})
                opener = urllib_request.build_opener(handler)
                r = opener.open("http://localhost:9222/json/version", timeout=3)
                if r.status == 200:
                    print(f"  Chrome CDP ready on port 9222")
                    return
            except Exception:
                pass
            try:
                r = httpx.get("http://localhost:9222/json/version", timeout=3)
                if r.status_code == 200:
                    print(f"  Chrome CDP ready on port 9222")
                    return
                if i % 5 == 0:
                    print(f"  Waiting for Chrome CDP... (status {r.status_code}, retry {i})")
            except Exception:
                if i % 5 == 0:
                    print(f"  Waiting for Chrome CDP... (retry {i})")
            time.sleep(1)

        # Auto-launch failed. Give user instructions and wait indefinitely
        print(f"\n{'='*60}")
        print(f"无法自动启动Chrome CDP。请手动执行以下命令：")
        print(f"  cd \"{Path(user_data_dir).parent}\"")
        print(f"  & \"{chrome_path}\" --remote-debugging-port=9222 --user-data-dir \"{user_data_dir}\" --no-first-run --no-default-browser-check")
        print(f"")
        print(f"或者用以下PowerShell命令复制你的浏览器数据：")
        print(f"  $src = \"$env:LOCALAPPDATA\\Google\\Chrome\\User Data\"")
        print(f"  $dst = \"{user_data_dir}\"")
        print(f"  Copy-Item -Path $src\\* -Destination $dst -Recurse -Force")
        print(f"  & \"{chrome_path}\" --remote-debugging-port=9222 --user-data-dir \"$dst\" --no-first-run")
        print(f"{'='*60}")
        print(f"")
        print(f"等待用户手动启动Chrome（Ctrl+C 取消）...")
        import urllib.request as urllib_request
        while True:
            try:
                handler = urllib_request.ProxyHandler({})
                opener = urllib_request.build_opener(handler)
                r = opener.open("http://localhost:9222/json/version", timeout=3)
                if r.status == 200:
                    print(f"  Chrome CDP ready on port 9222")
                    return
            except Exception:
                pass
            try:
                r = httpx.get("http://localhost:9222/json/version", timeout=3)
                if r.status_code == 200:
                    print(f"  Chrome CDP ready on port 9222")
                    return
            except Exception:
                pass
            time.sleep(1)

    def _disable_tools_and_categories(
        self,
        disabled_tools: list[str],
        disabled_categories: list[str]
    ) -> tuple:
        """Disable specified tools and skill categories

        Args:
            disabled_tools: List of tool names to disable
            disabled_categories: List of skill category names to disable

        Returns:
            Tuple of (tool_manager, skill_manager, original_disabled_tools, original_disabled_categories)
        """
        tool_manager = get_tool_manager()
        skill_manager = SkillManager()

        # Save original disabled state
        original_disabled_tools = tool_manager.get_disabled_tools().copy()
        original_disabled_categories = skill_manager.get_disabled_categories().copy()

        # Disable specified tools
        if disabled_tools:
            tool_manager.disable_tools(disabled_tools)

        # Disable specified skill categories
        if disabled_categories:
            skill_manager.disable_categories(disabled_categories)

        return tool_manager, skill_manager, original_disabled_tools, original_disabled_categories

    def _restore_tools_and_categories(
        self,
        tool_manager,
        skill_manager,
        original_disabled_tools: list[str],
        original_disabled_categories: list[str]
    ) -> None:
        """Restore original disabled state for tools and skill categories

        Args:
            tool_manager: Tool manager instance
            skill_manager: Skill manager instance
            original_disabled_tools: Original disabled tools list
            original_disabled_categories: Original disabled categories list
        """
        # Enable all tools first
        tool_manager.enable_all_tools()

        # Re-disable original tools
        if original_disabled_tools:
            tool_manager.disable_tools(original_disabled_tools)

        # Enable all categories first
        skill_manager.enable_all_categories()

        # Re-disable original categories
        if original_disabled_categories:
            skill_manager.disable_categories(original_disabled_categories)

    def verify_success_criteria(
        self,
        test_case: TestCase,
        result: dict
    ) -> dict[str, bool]:
        """Verify test result against success criteria

        Args:
            test_case: Test case being verified
            result: Test execution result dictionary

        Returns:
            Dictionary mapping criteria to their pass/fail status
        """
        criteria_results = {}

        response = result.get("response", "")
        iterations = result.get("iterations", 0)
        tool_calls = result.get("tool_calls", [])

        for criterion in test_case.success_criteria:
            criterion_lower = criterion.lower()

            if criterion_lower == "响应不为空":
                criteria_results[criterion] = response is not None and len(response) > 0

            elif criterion_lower == "迭代次数大于0":
                criteria_results[criterion] = iterations > 0

            elif criterion_lower == "未使用execute_command工具":
                criteria_results[criterion] = "execute_command" not in tool_calls

            elif "成功导航到" in criterion_lower:
                # Check if navigation was successful
                criteria_results[criterion] = self._check_navigation_success(response, criterion)

            elif "成功搜索" in criterion_lower:
                # Check if search was successful
                criteria_results[criterion] = self._check_search_success(response, criterion)

            elif "成功进入" in criterion_lower:
                # Check if entered target page
                criteria_results[criterion] = self._check_page_entry_success(response, criterion)

            elif "成功点击" in criterion_lower:
                # Check if click action was successful
                criteria_results[criterion] = self._check_click_success(response, criterion)

            else:
                # Default: check if criterion is mentioned in response
                criteria_results[criterion] = criterion_lower in response.lower() if response else False

        return criteria_results

    def _check_navigation_success(self, response: str, criterion: str) -> bool:
        """Check if navigation was successful based on response content"""
        if not response:
            return False
        response_lower = response.lower()

        # Check for common success indicators
        success_indicators = [
            "成功导航",
            "已导航",
            "导航到",
            "页面已加载",
            "loaded",
            "navigated",
        ]

        # Extract target from criterion
        if "google" in criterion.lower():
            return any(ind in response_lower for ind in success_indicators) and "google" in response_lower
        elif "example" in criterion.lower():
            return any(ind in response_lower for ind in success_indicators) and "example" in response_lower

        return any(ind in response_lower for ind in success_indicators)

    def _check_search_success(self, response: str, criterion: str) -> bool:
        """Check if search was successful"""
        if not response:
            return False
        response_lower = response.lower()

        success_indicators = [
            "搜索成功",
            "搜索结果",
            "已搜索",
            "search results",
            "found",
        ]

        return any(ind in response_lower for ind in success_indicators)

    def _check_page_entry_success(self, response: str, criterion: str) -> bool:
        """Check if successfully entered a page"""
        if not response:
            return False
        response_lower = response.lower()

        # Check for specific targets mentioned in criterion
        if "小红书" in criterion or "xiaohongshu" in criterion.lower():
            return "小红书" in response or "xiaohongshu" in response_lower

        success_indicators = [
            "成功进入",
            "已进入",
            "页面显示",
            "entered",
            "opened",
        ]

        return any(ind in response_lower for ind in success_indicators)

    def _check_click_success(self, response: str, criterion: str) -> bool:
        """Check if click action was successful"""
        if not response:
            return False
        response_lower = response.lower()

        success_indicators = [
            "点击成功",
            "已点击",
            "clicked",
        ]

        # Check for success indicators or if "笔记" is mentioned (for note click tests)
        has_indicator = any(ind in response_lower for ind in success_indicators)
        has_note = "笔记" in response

        return has_indicator or has_note

    async def run_test(self, test_case: TestCase) -> TestResult:
        """Execute a single test case

        Args:
            test_case: Test case to execute

        Returns:
            TestResult object
        """
        print("=" * 70)
        print(f"Test: {test_case.name} ({test_case.test_id})")
        print("=" * 70)

        print(f"\nDescription: {test_case.description}")
        print(f"Input: {test_case.input}")
        print(f"Success Criteria: {test_case.success_criteria}")
        print(f"Disabled Tools: {test_case.disabled_tools}")
        print(f"Disabled Skill Categories: {test_case.disabled_skill_categories}")
        print(f"Max Iterations: {test_case.max_iterations}")
        print(f"Timeout: {test_case.timeout}s")

        # Get Chrome user data directory
        chrome_user_data_dir = self.get_chrome_user_data_dir(test_case.chrome_profile)
        self._ensure_chrome_cdp_ready(test_case.chrome_profile)

        # Disable tools and categories
        tool_manager, skill_manager, orig_tools, orig_categories = self._disable_tools_and_categories(
            test_case.disabled_tools,
            test_case.disabled_skill_categories
        )

        print(f"\nDisabled tools: {tool_manager.get_disabled_tools()}")
        print(f"Disabled categories: {skill_manager.get_disabled_categories()}")

        start_time = datetime.now()

        original_screenshot_env = os.environ.get("CDP_SCREENSHOT_ENABLED", None)
        if test_case.enable_screenshot:
            os.environ["CDP_SCREENSHOT_ENABLED"] = "true"
        else:
            os.environ["CDP_SCREENSHOT_ENABLED"] = "false"

        try:
            # Create agent
            agent = AgentLoop(
                max_iterations=test_case.max_iterations,
                enable_logging=True,
                mode="default",
                skill_manager=skill_manager,
            )
            agent._interaction_logger.subscribe(self._make_event_handler())

            print("\nStarting test execution...")

            # Run agent
            response = await asyncio.wait_for(
                agent.run(test_case.input, reset=True),
                timeout=test_case.timeout
            )

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            # Get execution details
            loaded_skills = agent.get_loaded_skills()
            state = agent.state
            log_path = agent._interaction_logger.save()

            # Build result dictionary
            result = {
                "response": response,
                "iterations": state.iteration_count,
                "phase": state.phase.value,
                "loaded_skills": loaded_skills,
                "tool_calls": self._extract_tool_calls_from_state(state),
            }

            # Verify success criteria
            criteria_results = self.verify_success_criteria(test_case, result)

            print("\n" + "-" * 70)
            print("Test Results")
            print("-" * 70)

            print(f"\nIterations: {state.iteration_count}")
            print(f"Final Phase: {state.phase.value}")
            print(f"Loaded Skills: {loaded_skills}")
            print(f"Response Length: {len(response) if response else 0}")
            print(f"Execution Time: {execution_time:.2f}s")

            print(f"\nResponse Preview:")
            print("-" * 70)
            if response:
                print(response[:1000] if len(response) > 1000 else response)
            else:
                print("No response")

            print(f"\nSuccess Criteria Results:")
            all_passed = True
            for criterion, passed in criteria_results.items():
                status = "[PASS]" if passed else "[FAIL]"
                print(f"  {status} {criterion}")
                if not passed:
                    all_passed = False

            print(f"\nLog saved to: {log_path}")

            return TestResult(
                test_id=test_case.test_id,
                name=test_case.name,
                success=all_passed,
                iterations=state.iteration_count,
                phase=state.phase.value,
                response_length=len(response) if response else 0,
                criteria_results=criteria_results,
                loaded_skills=loaded_skills,
                log_path=log_path,
                chrome_user_data_dir=chrome_user_data_dir,
                execution_time=execution_time,
            )

        except asyncio.TimeoutError:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            print(f"\n[FAIL] Test timed out after {test_case.timeout}s")

            return TestResult(
                test_id=test_case.test_id,
                name=test_case.name,
                success=False,
                iterations=0,
                phase="timeout",
                response_length=0,
                criteria_results={c: False for c in test_case.success_criteria},
                loaded_skills=[],
                error=f"Test timed out after {test_case.timeout}s",
                chrome_user_data_dir=chrome_user_data_dir,
                execution_time=execution_time,
            )

        except Exception as e:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            print(f"\n[FAIL] Test execution error: {e}")
            import traceback
            traceback.print_exc()

            return TestResult(
                test_id=test_case.test_id,
                name=test_case.name,
                success=False,
                iterations=0,
                phase="error",
                response_length=0,
                criteria_results={c: False for c in test_case.success_criteria},
                loaded_skills=[],
                error=str(e),
                chrome_user_data_dir=chrome_user_data_dir,
                execution_time=execution_time,
            )

        finally:
            # Restore original disabled state
            self._restore_tools_and_categories(
                tool_manager, skill_manager, orig_tools, orig_categories
            )
            print(f"\nRestored original tool and category states")

            if original_screenshot_env is not None:
                os.environ["CDP_SCREENSHOT_ENABLED"] = original_screenshot_env
            else:
                os.environ.pop("CDP_SCREENSHOT_ENABLED", None)

    def _make_event_handler(self):
        """创建事件处理器，实时输出思考/回复/工具调用"""
        def handler(event: dict):
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
        return handler

    def _extract_tool_calls_from_state(self, state) -> list[str]:
        """Extract tool call names from agent state

        Args:
            state: AgentState instance

        Returns:
            List of tool names that were called
        """
        tool_calls = []
        for action in state.action_history:
            tool_name = action.get("tool_name", "")
            if tool_name:
                tool_calls.append(tool_name)
        return tool_calls

    async def run_all_tests(
        self,
        test_ids: Optional[list[str]] = None,
        stop_on_failure: bool = False
    ) -> list[TestResult]:
        """Run all test cases or specific tests

        Args:
            test_ids: Optional list of test IDs to run. If None, run all tests.
            stop_on_failure: Whether to stop on first failure

        Returns:
            List of TestResult objects
        """
        test_cases = self.load_test_cases()

        # Filter by test_ids if specified
        if test_ids:
            test_cases = [tc for tc in test_cases if tc.test_id in test_ids]

        print("#" * 70)
        print("# CDP Test Suite Runner")
        print("#" * 70)
        print(f"\nTotal tests to run: {len(test_cases)}")
        print(f"Test IDs: {[tc.test_id for tc in test_cases]}")

        self.results = []

        for i, test_case in enumerate(test_cases, 1):
            print(f"\n{'#' * 70}")
            print(f"# Test {i}/{len(test_cases)}")
            print("#" * 70)

            result = await self.run_test(test_case)
            self.results.append(result)

            if not result.success and stop_on_failure:
                print(f"\n[STOP] Stopping on first failure: {test_case.test_id}")
                break

        # Print summary
        self._print_summary()

        return self.results

    def _print_summary(self) -> None:
        """Print test summary"""
        print("\n" + "=" * 70)
        print("Test Summary")
        print("=" * 70)

        passed = sum(1 for r in self.results if r.success)
        total = len(self.results)

        for result in self.results:
            status = "[PASS]" if result.success else "[FAIL]"
            print(f"  {status} {result.test_id}: {result.name}")
            if result.error:
                print(f"         Error: {result.error}")

        print(f"\nPass Rate: {passed}/{total} ({passed/total*100:.0f}%)")

        total_time = sum(r.execution_time for r in self.results)
        print(f"Total Execution Time: {total_time:.2f}s")

    def save_results(self, output_path: Optional[Path] = None) -> str:
        """Save test results to JSON file

        Args:
            output_path: Optional output path. If None, use default path.

        Returns:
            Path to saved results file
        """
        if output_path is None:
            output_path = Path(__file__).parent / "test_results.json"

        results_data = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(self.results),
            "passed": sum(1 for r in self.results if r.success),
            "failed": sum(1 for r in self.results if not r.success),
            "results": [
                {
                    "test_id": r.test_id,
                    "name": r.name,
                    "success": r.success,
                    "iterations": r.iterations,
                    "phase": r.phase,
                    "response_length": r.response_length,
                    "criteria_results": r.criteria_results,
                    "loaded_skills": r.loaded_skills,
                    "log_path": r.log_path,
                    "error": r.error,
                    "chrome_user_data_dir": r.chrome_user_data_dir,
                    "execution_time": r.execution_time,
                }
                for r in self.results
            ]
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results_data, f, ensure_ascii=False, indent=2)

        print(f"\nResults saved to: {output_path}")
        return str(output_path)


async def main():
    """Main entry point for test runner"""
    import argparse

    parser = argparse.ArgumentParser(description="CDP Test Suite Runner")
    parser.add_argument(
        "--test-ids",
        nargs="+",
        help="Specific test IDs to run"
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop on first test failure"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output path for test results JSON"
    )

    args = parser.parse_args()

    runner = TestRunner()

    output_path = Path(args.output) if args.output else None

    results = await runner.run_all_tests(
        test_ids=args.test_ids,
        stop_on_failure=args.stop_on_failure
    )

    runner.save_results(output_path)

    # Return exit code
    all_passed = all(r.success for r in results)
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
