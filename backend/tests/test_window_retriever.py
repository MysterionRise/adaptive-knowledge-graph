"""
Tests for the window retriever (opt-in NEXT-relationship context expansion).

The Neo4j adapter is mocked; these tests cover window sizing, subject-prefixed
adapters and the complete chunk dicts returned for /ask.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.app.core.subjects import get_default_subject_id
from backend.app.rag import window_retriever as window_module
from backend.app.rag.window_retriever import (
    WindowRetriever,
    clear_window_retrievers,
    get_window_retriever,
)


def _chunk(chunk_id, index, module="m1", title="Module One", section="S1"):
    return {
        "chunk_id": chunk_id,
        "text": f"text {chunk_id}",
        "module_id": module,
        "module_title": title,
        "section": section,
        "chunk_index": index,
    }


def _adapter(windows: dict[str, list[dict]]) -> MagicMock:
    """Mock adapter whose get_chunk_window returns copies of the given windows."""
    adapter = MagicMock()
    adapter.get_chunk_window.side_effect = lambda chunk_id, window_before, window_after: [
        dict(c) for c in windows[chunk_id]
    ]
    return adapter


@pytest.fixture(autouse=True)
def _clear_registry():
    clear_window_retrievers()
    yield
    clear_window_retrievers()


@pytest.mark.unit
class TestWindowSize:
    def test_default_reads_rag_window_size_not_expansion_hops(self, monkeypatch):
        monkeypatch.setattr(window_module.settings, "rag_window_size", 2)
        monkeypatch.setattr(window_module.settings, "rag_kg_expansion_hops", 3)

        assert WindowRetriever().window_size == 2
        assert get_window_retriever().window_size == 2

    def test_zero_override_is_honoured(self):
        adapter = _adapter({"c2": [_chunk("c2", 1)]})
        retriever = WindowRetriever(window_size=1, neo4j_adapter=adapter)

        result = retriever.retrieve_with_window(["c2"], window_size=0)

        adapter.get_chunk_window.assert_called_once_with(
            chunk_id="c2", window_before=0, window_after=0
        )
        assert [c["chunk_id"] for c in result] == ["c2"]

    def test_zero_default_is_honoured(self):
        adapter = _adapter({"c2": [_chunk("c2", 1)]})

        WindowRetriever(window_size=0, neo4j_adapter=adapter).retrieve_window_text(["c2"])

        adapter.get_chunk_window.assert_called_once_with(
            chunk_id="c2", window_before=0, window_after=0
        )

    def test_negative_sizes_rejected(self):
        with pytest.raises(ValueError):
            WindowRetriever(window_size=-1)

        retriever = WindowRetriever(window_size=1, neo4j_adapter=MagicMock())
        with pytest.raises(ValueError):
            retriever.retrieve_with_window(["c1"], window_size=-2)


@pytest.mark.unit
class TestSubjectAdapter:
    def test_adapter_comes_from_the_subject_registry(self):
        adapter = MagicMock()
        with patch.object(window_module, "get_neo4j_adapter", return_value=adapter) as factory:
            retriever = WindowRetriever(subject_id="economics")
            assert retriever.adapter is adapter
            assert retriever.adapter is adapter

        factory.assert_called_once_with("economics")

    def test_get_window_retriever_resolves_default_subject(self):
        retriever = get_window_retriever()

        assert retriever.subject_id == get_default_subject_id()
        assert get_window_retriever(get_default_subject_id()) is retriever
        assert get_window_retriever("economics") is not retriever
        assert get_window_retriever("economics").subject_id == "economics"

    def test_get_window_retriever_unknown_subject(self):
        with pytest.raises(KeyError):
            get_window_retriever("no_such_subject")

    def test_close_does_not_close_the_shared_adapter(self):
        adapter = MagicMock()
        retriever = WindowRetriever(neo4j_adapter=adapter)

        retriever.close()

        adapter.close.assert_not_called()


@pytest.mark.unit
class TestRetrieveWithWindow:
    def test_orders_by_module_then_index_and_marks_hits(self):
        windows = {
            "b_2": [_chunk("b_1", 1, module="b"), _chunk("b_2", 2, module="b")],
            "a_1": [_chunk("a_1", 1, module="a"), _chunk("a_2", 2, module="a")],
        }
        retriever = WindowRetriever(window_size=1, neo4j_adapter=_adapter(windows))

        result = retriever.retrieve_with_window(["b_2", "a_1"])

        assert [c["chunk_id"] for c in result] == ["a_1", "a_2", "b_1", "b_2"]
        assert [c["is_original_hit"] for c in result] == [True, False, False, True]

    def test_missing_module_id_does_not_break_sorting(self):
        windows = {"x": [dict(_chunk("x", 0), module_id=None)], "y": [_chunk("y", 1)]}
        retriever = WindowRetriever(window_size=0, neo4j_adapter=_adapter(windows))

        result = retriever.retrieve_with_window(["x", "y"])

        assert {c["chunk_id"] for c in result} == {"x", "y"}


@pytest.mark.unit
class TestRetrieveWindowText:
    def test_returns_complete_chunk_dicts(self):
        windows = {"m1_2": [_chunk("m1_1", 1), _chunk("m1_2", 2), _chunk("m1_3", 3)]}
        retriever = WindowRetriever(window_size=1, neo4j_adapter=_adapter(windows))

        [result] = retriever.retrieve_window_text(["m1_2"], scores={"m1_2": 0.87})

        assert result == {
            "id": "m1_2",
            "text": "text m1_1\n\ntext m1_2\n\ntext m1_3",
            "module_id": "m1",
            "module_title": "Module One",
            "section": "S1",
            "score": pytest.approx(0.87),
            "chunk_count": 3,
            "original_hit_count": 1,
            "chunk_ids": ["m1_1", "m1_2", "m1_3"],
        }

    def test_score_is_none_without_scores(self):
        retriever = WindowRetriever(window_size=0, neo4j_adapter=_adapter({"c": [_chunk("c", 0)]}))

        [result] = retriever.retrieve_window_text(["c"])

        assert result["score"] is None
        assert result["id"] == "c"

    def test_groups_are_ranked_by_their_best_hit(self):
        windows = {
            "a_1": [_chunk("a_1", 1, module="a")],
            "b_1": [_chunk("b_1", 1, module="b")],
            "b_2": [_chunk("b_2", 2, module="b")],
        }
        retriever = WindowRetriever(window_size=0, neo4j_adapter=_adapter(windows))

        results = retriever.retrieve_window_text(
            ["a_1", "b_1", "b_2"], scores={"a_1": 0.2, "b_1": 0.5, "b_2": 0.9}
        )

        assert [r["module_id"] for r in results] == ["b", "a"]
        assert results[0]["score"] == pytest.approx(0.9)
        assert results[0]["id"] == "b_1"
        assert results[0]["original_hit_count"] == 2

    def test_hit_inside_another_hits_window_still_counts(self):
        windows = {
            "c1": [_chunk("c1", 1), _chunk("c2", 2)],
            "c2": [_chunk("c1", 1), _chunk("c2", 2), _chunk("c3", 3)],
        }
        retriever = WindowRetriever(window_size=1, neo4j_adapter=_adapter(windows))

        [result] = retriever.retrieve_window_text(["c1", "c2"], scores={"c1": 0.4, "c2": 0.8})

        assert result["original_hit_count"] == 2
        assert result["score"] == pytest.approx(0.8)
        assert result["chunk_ids"] == ["c1", "c2", "c3"]
        assert result["chunk_count"] == 3

    def test_missing_module_title_is_none(self):
        windows = {"c": [dict(_chunk("c", 0), module_title=None)]}
        retriever = WindowRetriever(window_size=0, neo4j_adapter=_adapter(windows))

        [result] = retriever.retrieve_window_text(["c"])

        assert result["module_title"] is None

    def test_route_compatible_keys(self):
        """routes/ask.py reads text, module_id, section and chunk_count from each result."""
        windows = {"c": [_chunk("c", 0)]}
        retriever = WindowRetriever(window_size=0, neo4j_adapter=_adapter(windows))

        [result] = retriever.retrieve_window_text(chunk_ids=["c"], window_size=0)

        assert {"text", "module_id", "section", "chunk_count"} <= result.keys()
