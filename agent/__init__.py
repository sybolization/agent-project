"""Agent module for natural language browser control."""


def __getattr__(name):
    _lazy_map = {
        "AgentLoop": ".agent_loop",
        "SessionMemory": ".session.memory",
        "AgentState": ".state",
        "AgentPhase": ".state",
        "ExecutionContext": ".execution_context",
        "ALL_TOOL_SCHEMAS": ".tools.schemas",
        "get_tools_for_phase": ".tools.schemas",
        "get_available_tool_names": ".tools.schemas",
        "get_phase_tools_description": ".tools.schemas",
        "estimate_tokens": ".context.compression",
        "estimate_context_tokens": ".context.compression",
        "compact_by_rounds": ".context.compression",
        "compress_context": ".context.compression",
        "emergency_compact": ".context.compression",
        "save_transcript": ".context.compression",
        "load_transcript": ".context.compression",
        "compress_opencli_result": ".context.compression",
        "PromptBuilder": ".prompts.builder",
        "SectionCache": ".prompts.builder",
        "format_session_context": ".prompts.templates",
        "format_task_context": ".prompts.templates",
        "ToolExecutor": ".tools.executors",
        "SkillManager": ".skills.manager",
        "WebContentFetcher": ".content.fetcher",
        "InteractionLogger": ".session.logger",
        "TodoTracker": ".session.tracking",
        "LLMInterface": ".llm.interface",
        "get_llm_interface": ".llm.interface",
    }
    if name in _lazy_map:
        import importlib
        module = importlib.import_module(_lazy_map[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AgentLoop",
    "SessionMemory",
    "AgentState",
    "AgentPhase",
    "ExecutionContext",
    "ALL_TOOL_SCHEMAS",
    "get_tools_for_phase",
    "get_available_tool_names",
    "get_phase_tools_description",
    "estimate_tokens",
    "estimate_context_tokens",
    "compact_by_rounds",
    "compress_context",
    "emergency_compact",
    "save_transcript",
    "load_transcript",
    "compress_opencli_result",
    "PromptBuilder",
    "SectionCache",
    "format_session_context",
    "format_task_context",
    "ToolExecutor",
    "SkillManager",
    "WebContentFetcher",
    "InteractionLogger",
    "TodoTracker",
    "LLMInterface",
    "get_llm_interface",
]
