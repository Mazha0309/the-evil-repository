"""Observable Agent execution graph derived from the append-only event stream.

The graph records roles, delegation and resource use. It intentionally does
not store or infer private chain-of-thought.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentNode(BaseModel):
    id: str
    parent_id: str | None = None
    role: str = "primary"
    status: Literal["active", "completed", "failed", "cancelled"] = "active"
    first_sequence: int | None = None
    last_sequence: int | None = None
    model_turns: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentEdge(BaseModel):
    source: str
    target: str
    relation: Literal["spawned", "delegated", "reviewed"]
    sequence: int | None = None
    task: str | None = None


class AgentGraph(BaseModel):
    schema_version: int = 1
    execution_mode: Literal["single_agent", "multi_agent"]
    nodes: list[AgentNode]
    edges: list[AgentEdge]


def derive_agent_graph(
    events: list[dict[str, Any]],
    *,
    default_agent_id: str = "candidate/root",
) -> AgentGraph:
    nodes: dict[str, AgentNode] = {
        default_agent_id: AgentNode(id=default_agent_id, role="primary")
    }
    edges: list[AgentEdge] = []

    for event in events:
        kind = str(event.get("kind", ""))
        sequence_value = event.get("sequence")
        sequence = int(sequence_value) if sequence_value is not None else None
        agent_id = str(event.get("agent_id") or default_agent_id)

        if kind == "agent.spawned":
            parent_id = str(event.get("parent_agent_id") or default_agent_id)
            node = nodes.setdefault(
                agent_id,
                AgentNode(
                    id=agent_id,
                    parent_id=parent_id,
                    role=str(
                        event.get("agent_role") or event.get("role") or "worker"
                    ),
                    metadata=dict(event.get("agent_metadata") or {}),
                ),
            )
            node.parent_id = parent_id
            edges.append(
                AgentEdge(
                    source=parent_id,
                    target=agent_id,
                    relation="spawned",
                    sequence=sequence,
                    task=_optional_text(event.get("task")),
                )
            )
        elif kind == "agent.delegated":
            target = str(event.get("target_agent_id") or "")
            if target:
                nodes.setdefault(target, AgentNode(id=target, role="worker"))
                edges.append(
                    AgentEdge(
                        source=agent_id,
                        target=target,
                        relation="delegated",
                        sequence=sequence,
                        task=_optional_text(event.get("task")),
                    )
                )

        if not _is_candidate_agent_event(kind, event):
            continue
        node = nodes.setdefault(
            agent_id,
            AgentNode(
                id=agent_id,
                role=str(event.get("agent_role") or "worker"),
            ),
        )
        if node.first_sequence is None:
            node.first_sequence = sequence
        node.last_sequence = sequence
        if kind == "model.request":
            node.model_turns += 1
        elif kind == "assistant.message":
            node.input_tokens += int(event.get("input_tokens") or 0)
            node.output_tokens += int(event.get("output_tokens") or 0)
        elif kind == "tool.call":
            node.tool_calls += 1
        elif kind in {"agent.completed", "agent.failed", "agent.cancelled"}:
            node.status = kind.removeprefix("agent.")  # type: ignore[assignment]

    ordered_nodes = sorted(nodes.values(), key=lambda node: node.id)
    return AgentGraph(
        execution_mode="multi_agent" if len(ordered_nodes) > 1 else "single_agent",
        nodes=ordered_nodes,
        edges=edges,
    )


def _is_candidate_agent_event(kind: str, event: dict[str, Any]) -> bool:
    if kind.startswith("agent."):
        return True
    if kind in {"model.request", "assistant.message", "tool.call", "tool.result"}:
        return True
    return "agent_id" in event and str(event.get("agent_id", "")).startswith(
        "candidate/"
    )


def _optional_text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None
