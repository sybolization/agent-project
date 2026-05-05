"""Whiteboard - Shared information space for agent communication."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Whiteboard:
    """Shared information space for main agent and subagents.

    This provides a "whiteboard" pattern where the main agent can share
    context, instructions, and state with subagents, and subagents can
    read from and write to the shared space.

    Attributes:
        task: The task description assigned to subagents
        available_tools: List of tools available to subagents
        parent_agent_id: ID of the parent/main agent
        shared_context: Key-value store for shared data
        instructions: Instructions from the main agent
    """

    task: str = ""
    available_tools: list[str] = field(default_factory=lambda: ["opencli", "task_complete"])
    parent_agent_id: str = "main"
    shared_context: dict[str, Any] = field(default_factory=dict)
    instructions: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from shared context.

        Args:
            key: The key to look up
            default: Default value if key not found

        Returns:
            The value associated with the key, or default
        """
        return self.shared_context.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a value in shared context.

        Args:
            key: The key to set
            value: The value to store
        """
        self.shared_context[key] = value

    def update_context(self, data: dict[str, Any]) -> None:
        """Update shared context with multiple key-value pairs.

        Args:
            data: Dictionary of key-value pairs to update
        """
        self.shared_context.update(data)

    def to_prompt_context(self) -> str:
        """Generate a prompt-friendly string representation.

        Returns:
            Formatted string for use in prompts
        """
        lines = [
            "## Whiteboard Information",
            f"- Task: {self.task}",
            f"- Available Tools: {', '.join(self.available_tools)}",
            f"- Parent Agent: {self.parent_agent_id}",
        ]

        if self.instructions:
            lines.append(f"- Instructions: {self.instructions}")

        if self.shared_context:
            lines.append("- Shared Context:")
            for key, value in self.shared_context.items():
                lines.append(f"  - {key}: {value}")

        return "\n".join(lines)
