"""spawn_agents 工具 - 派生并行子Agent"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from agent.tools.protocol import ToolDefinition
from agent.state import AgentPhase
from agent.phases.result import PhaseResult


class SpawnAgentsArgs(BaseModel):
    """spawn_agents 工具的参数模型"""
    agent_count: int = Field(description="Number of subagents to spawn")
    tasks: Union[str, List[str]] = Field(
        description="Task description(s) to assign to subagents. Single task is assigned to all, or list of tasks for each subagent"
    )
    subagent_todos: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Atomic subtask list, each subtask corresponds to a subagent. Must contain id, content, status fields."
    )
    shared_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional shared context dictionary to pass to all subagents"
    )
    available_tools: Optional[List[str]] = Field(
        default=None,
        description="Optional list of tools available to subagents. Default is ['execute_command', 'task_complete']"
    )
    inherited_skills: Optional[List[str]] = Field(
        default=None,
        description=(
            "RECOMMENDED: Specify ONLY the skills the subagent NEEDS for its task. "
            "Example: for web search subagent, use ['smart-search']. Do NOT include unrelated skills like ['feishu'] for a search task. "
            "This significantly reduces context token usage. If not specified, all parent skills are inherited."
        )
    )
    excluded_skills: Optional[List[str]] = Field(
        default=None,
        description="Optional list of skill names to exclude from inheritance. Only used when inherited_skills is not specified. Subagents will inherit all parent skills except those listed here."
    )


SCHEMA = {
    "type": "function",
    "function": {
        "name": "spawn_agents",
        "description": (
            "Spawn multiple subagents to execute tasks in parallel. "
            "Each subagent will complete the assigned task and submit a result summary. "
            "Maximum depth is 1 - subagents cannot spawn more agents.\n\n"
            "## Prerequisites\n"
            "1. Must have collected necessary information (loaded relevant skills or provided sufficient shared_context)\n"
            "2. Must create subagent_todos (atomic subtask list)\n"
            "3. Each subtask should be different, parallel-executable leaf node tasks\n"
            "4. Subtasks should not have dependencies on each other\n\n"
            "## Task Decomposition Principles\n"
            "1. Identify parallelizable parts: Find parts of the task that can be executed simultaneously\n"
            "2. Create atomic subtasks: Each subtask should be an indivisible leaf node task\n"
            "3. Ensure independence: Subtasks should not have dependencies on each other\n"
            "4. Define clear boundaries: Each subtask should have clear inputs and outputs\n\n"
            "## Correct Usage Example\n"
            "Task: Search for laptops on Taobao\n"
            "Step 1: Load relevant skill (load_skill or load_skill_category)\n"
            "Step 2: Understand search command usage\n"
            "Step 3: Decompose task into non-overlapping subtasks\n"
            "Step 4: Create subagent_todos and spawn subagents\n"
            "spawn_agents(\n"
            "  agent_count=3,\n"
            "  tasks=[\n"
            "    'Search Dyson hair dryers on Taobao, collect top 10 popular products',\n"
            "    'Search Philips hair dryers on Taobao, collect top 10 popular products',\n"
            "    'Search Panasonic hair dryers on Taobao, collect top 10 popular products'\n"
            "  ],\n"
            "  subagent_todos=[\n"
            "    {'id': 'sub1', 'content': 'Search Dyson hair dryers', 'status': 'pending'},\n"
            "    {'id': 'sub2', 'content': 'Search Philips hair dryers', 'status': 'pending'},\n"
            "    {'id': 'sub3', 'content': 'Search Panasonic hair dryers', 'status': 'pending'}\n"
            "  ]\n"
            ")\n\n"
            "## Incorrect Usage\n"
            "- All subagents execute the same high-level task\n"
            "- Spawning subagents without collecting information first\n"
            "- Spawning subagents without creating subagent_todos\n"
            "- Spawning subagents without decomposing the task\n\n"
            "Parameters:\n"
            "- agent_count: Number of subagents to spawn\n"
            "- tasks: Task descriptions list (NOT a single string)\n"
            "- subagent_todos: Atomic subtask list for validation\n"
            "- shared_context: Optional shared context dictionary\n"
            "- available_tools: Optional list of tools for subagents\n"
            "- inherited_skills: **RECOMMENDED**: List of skill names to inherit. Only pass skills the subagent actually needs for its task. Example: if subagent searches websites, use [\"smart-search\"], NOT unrelated skills like [\"feishu\"]. This saves context tokens.\n"
            "- excluded_skills: Optional list of skill names to exclude (only used when inherited_skills is not specified)"
        ),
        "parameters": SpawnAgentsArgs.model_json_schema(),
    },
}


class SpawnAgentsTool:
    def __init__(self, tool_executor=None):
        self._tool_executor = tool_executor

    async def execute(self, call: dict, context) -> dict:
        try:
            args = call.get("arguments", {})
            return await self._tool_executor._execute_spawn_agents(args, context)
        except Exception as e:
            return {"type": "error", "message": str(e)}

    def handle(self, result: dict, state) -> PhaseResult:
        if result.get("type") == "error":
            return PhaseResult(status="continue", message=f"[错误] {result.get('message')}")
        if result.get("type") == "spawn_complete":
            return PhaseResult(
                status="spawn_complete",
                message=result.get("summary", ""),
                subagent_results=result.get("results", []),
            )
        return PhaseResult(status="continue", message=str(result))

    def format(self, result: dict) -> str:
        if result.get("type") == "error":
            return f"[错误] {result.get('message')}"
        if result.get("type") == "spawn_complete":
            return result.get("summary", "")
        return str(result)


tool_definition = ToolDefinition(
    name="spawn_agents",
    schema=SCHEMA,
    phases=[AgentPhase.EXECUTE],
    description="Spawn multiple subagents to execute tasks in parallel",
    usage_hint="spawn_agents(agent_count, tasks, subagent_todos, ...)",
    executor=SpawnAgentsTool(tool_executor=None),
)
