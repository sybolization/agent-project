"""Test Monitor - Full-flow monitoring for Agent-Loop tests."""

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class PromptLog:
    layer_0: str
    layer_1: str
    full_prompt: str
    token_estimate: int


@dataclass
class ToolCallLog:
    name: str
    arguments: dict
    result: dict
    timing_ms: float


@dataclass
class ModelOutputLog:
    content: str
    tool_calls: list[dict]
    timing_ms: float


@dataclass
class IterationLog:
    iteration: int
    phase: str
    prompt: PromptLog
    tool_calls: list[ToolCallLog]
    model_output: ModelOutputLog
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class MetricsLog:
    total_iterations: int = 0
    total_tool_calls: int = 0
    total_time_ms: float = 0.0
    skills_loaded: list[str] = field(default_factory=list)
    context_tokens_final: int = 0


@dataclass
class SummaryLog:
    success: bool = False
    final_response: str = ""
    issues: list[str] = field(default_factory=list)


@dataclass
class TestLog:
    test_case: dict
    iterations: list[IterationLog] = field(default_factory=list)
    metrics: MetricsLog = field(default_factory=MetricsLog)
    summary: SummaryLog = field(default_factory=SummaryLog)
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None


class TestMonitor:
    """Monitor for recording full-flow Agent-Loop execution."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path("logs/test_monitor")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.current_test: Optional[TestLog] = None
        self._start_time: float = 0

    def start_test(self, test_case: dict) -> None:
        self.current_test = TestLog(test_case=test_case)
        self._start_time = time.time()

    def log_iteration(
        self,
        iteration: int,
        phase: str,
        prompt: dict,
        tool_calls: list[dict],
        model_output: dict,
    ) -> None:
        if self.current_test is None:
            return

        prompt_log = PromptLog(
            layer_0=prompt.get("layer_0", ""),
            layer_1=prompt.get("layer_1", ""),
            full_prompt=prompt.get("full_prompt", ""),
            token_estimate=prompt.get("token_estimate", 0),
        )

        tool_call_logs = [
            ToolCallLog(
                name=tc.get("name", ""),
                arguments=tc.get("arguments", {}),
                result=tc.get("result", {}),
                timing_ms=tc.get("timing_ms", 0.0),
            )
            for tc in tool_calls
        ]

        model_output_log = ModelOutputLog(
            content=model_output.get("content", ""),
            tool_calls=model_output.get("tool_calls", []),
            timing_ms=model_output.get("timing_ms", 0.0),
        )

        iteration_log = IterationLog(
            iteration=iteration,
            phase=phase,
            prompt=prompt_log,
            tool_calls=tool_call_logs,
            model_output=model_output_log,
        )

        self.current_test.iterations.append(iteration_log)
        self.current_test.metrics.total_tool_calls += len(tool_calls)

    def log_skill_loaded(self, skill_name: str) -> None:
        if self.current_test is None:
            return
        if skill_name not in self.current_test.metrics.skills_loaded:
            self.current_test.metrics.skills_loaded.append(skill_name)

    def end_test(
        self,
        success: bool,
        final_response: str,
        issues: Optional[list[str]] = None,
    ) -> Path:
        if self.current_test is None:
            raise RuntimeError("No test in progress")

        end_time = time.time()
        self.current_test.end_time = datetime.now().isoformat()
        self.current_test.metrics.total_iterations = len(self.current_test.iterations)
        self.current_test.metrics.total_time_ms = (end_time - self._start_time) * 1000

        self.current_test.summary.success = success
        self.current_test.summary.final_response = final_response
        if issues:
            self.current_test.summary.issues = issues

        test_name = self.current_test.test_case.get("name", "unknown")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.output_dir / f"{test_name}_{timestamp}.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(self._to_dict(self.current_test), f, ensure_ascii=False, indent=2)

        return output_file

    def _to_dict(self, obj: Any) -> Any:
        if hasattr(obj, "__dataclass_fields__"):
            return {k: self._to_dict(v) for k, v in asdict(obj).items()}
        elif isinstance(obj, list):
            return [self._to_dict(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: self._to_dict(v) for k, v in obj.items()}
        else:
            return obj

    def get_current_test_log(self) -> Optional[TestLog]:
        return self.current_test
