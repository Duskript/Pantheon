from __future__ import annotations

from gods.graph_client import EDGE_CONTRADICTS, GraphClient


def make_graph(tmp_path):
    graph = GraphClient(db_path=str(tmp_path / "graph.db"))
    graph.connect()
    return graph


def test_register_fact_detects_same_subject_predicate_different_value(tmp_path):
    graph = make_graph(tmp_path)
    try:
        first_id = graph.register_fact(
            "Konan favorite editor",
            "is",
            "Vivaldi notes",
            codex="Codex-User",
            source="old-session",
        )

        conflicts = graph.find_conflicts_for_fact(
            "Konan favorite editor",
            "is",
            "Obsidian",
            codex="Codex-User",
        )
        assert [c["id"] for c in conflicts] == [first_id]
    finally:
        graph.close()


def test_register_fact_links_contradicts_edges(tmp_path):
    graph = make_graph(tmp_path)
    try:
        first_id = graph.register_fact("Gateway", "status", "healthy", codex="Codex-Pantheon")
        second_id = graph.register_fact("Gateway", "status", "critical", codex="Codex-Pantheon")

        edges = graph.get_edges(node_id=second_id, type_=EDGE_CONTRADICTS, direction="out")
        assert len(edges) == 1
        assert edges[0]["source_id"] == second_id
        assert edges[0]["target_id"] == first_id
        assert edges[0]["metadata"]["new_value"] == "critical"
        assert edges[0]["metadata"]["existing_value"] == "healthy"
    finally:
        graph.close()


def test_resolved_fact_is_not_reported_as_conflict(tmp_path):
    graph = make_graph(tmp_path)
    try:
        graph.register_fact(
            "Athenaeum backlog",
            "count",
            "3000",
            codex="Codex-Pantheon",
            metadata={"conflict_status": "resolved"},
        )
        conflicts = graph.find_conflicts_for_fact(
            "Athenaeum backlog",
            "count",
            "2000",
            codex="Codex-Pantheon",
        )
        assert conflicts == []
    finally:
        graph.close()
