from app.scenario.agent_graph import derive_agent_graph


def test_single_agent_events_become_a_one_node_graph() -> None:
    graph = derive_agent_graph(
        [
            {"kind": "model.request", "sequence": 1},
            {
                "kind": "assistant.message",
                "sequence": 2,
                "input_tokens": 120,
                "output_tokens": 30,
            },
            {"kind": "tool.call", "sequence": 3},
        ]
    )

    assert graph.execution_mode == "single_agent"
    assert len(graph.nodes) == 1
    assert graph.nodes[0].id == "candidate/root"
    assert graph.nodes[0].model_turns == 1
    assert graph.nodes[0].tool_calls == 1
    assert graph.nodes[0].input_tokens == 120


def test_spawn_and_delegation_events_form_a_multi_agent_graph() -> None:
    graph = derive_agent_graph(
        [
            {
                "kind": "agent.spawned",
                "sequence": 1,
                "agent_id": "candidate/research-1",
                "parent_agent_id": "candidate/root",
                "agent_role": "research",
                "task": "Inspect Git history",
            },
            {
                "kind": "agent.delegated",
                "sequence": 2,
                "agent_id": "candidate/root",
                "target_agent_id": "candidate/research-1",
                "task": "Falsify the version hypothesis",
            },
            {
                "kind": "tool.call",
                "sequence": 3,
                "agent_id": "candidate/research-1",
            },
            {
                "kind": "agent.completed",
                "sequence": 4,
                "agent_id": "candidate/research-1",
            },
        ]
    )

    assert graph.execution_mode == "multi_agent"
    research = next(
        node for node in graph.nodes if node.id == "candidate/research-1"
    )
    assert research.parent_id == "candidate/root"
    assert research.role == "research"
    assert research.tool_calls == 1
    assert research.status == "completed"
    assert [edge.relation for edge in graph.edges] == ["spawned", "delegated"]
