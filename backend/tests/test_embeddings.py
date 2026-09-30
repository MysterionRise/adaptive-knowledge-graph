"""
Tests for the embeddings module.

SentenceTransformer and torch are replaced with fakes, so no model is downloaded
and the device logic is tested independently of the machine running the tests.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.app.nlp import embeddings
from backend.app.nlp.embeddings import EmbeddingModel, get_embedding_model, resolve_device

REPO_ROOT = Path(__file__).resolve().parents[2]


def _fake_torch(cuda: bool, mps: bool | None) -> SimpleNamespace:
    """A stand-in for the torch module; mps=None means torch has no MPS backend."""
    backends = SimpleNamespace()
    if mps is not None:
        backends.mps = SimpleNamespace(is_available=lambda: mps)
    return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda), backends=backends)


@pytest.fixture
def fake_sentence_transformer():
    """Replace the sentence_transformers module with a fake SentenceTransformer class."""
    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = 3
    model.encode.return_value = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    model_cls = MagicMock(return_value=model)

    with patch.dict(
        sys.modules, {"sentence_transformers": SimpleNamespace(SentenceTransformer=model_cls)}
    ):
        yield model_cls, model


@pytest.mark.unit
class TestResolveDevice:
    """EMBEDDING_DEVICE resolution: auto picks cuda -> mps -> cpu."""

    @pytest.mark.parametrize(
        ("requested", "cuda", "mps", "expected"),
        [
            ("auto", True, True, "cuda"),
            ("auto", False, True, "mps"),
            ("auto", False, False, "cpu"),
            (None, False, True, "mps"),
            ("AUTO", False, False, "cpu"),
            ("cuda", True, False, "cuda"),
            ("cuda", False, True, "cpu"),
            ("cuda:1", True, False, "cuda:1"),
            ("mps", False, True, "mps"),
            ("mps", True, False, "cpu"),
            ("cpu", True, True, "cpu"),
            ("tpu", True, True, "cpu"),
        ],
    )
    def test_resolution(self, requested, cuda, mps, expected):
        with patch.dict(sys.modules, {"torch": _fake_torch(cuda, mps)}):
            assert resolve_device(requested) == expected

    def test_torch_without_mps_backend(self):
        with patch.dict(sys.modules, {"torch": _fake_torch(cuda=False, mps=None)}):
            assert resolve_device("auto") == "cpu"

    def test_missing_torch_falls_back_to_cpu(self):
        # A None entry in sys.modules makes `import torch` raise ImportError
        with patch.dict(sys.modules, {"torch": None}):
            assert resolve_device("auto") == "cpu"
            assert resolve_device("cuda") == "cpu"

    def test_cpu_does_not_need_torch(self):
        with patch.dict(sys.modules, {"torch": None}):
            assert resolve_device("cpu") == "cpu"


@pytest.mark.unit
class TestEmbeddingModel:
    """EmbeddingModel with a mocked SentenceTransformer."""

    def test_init_does_not_load_the_model(self, fake_sentence_transformer):
        model_cls, _ = fake_sentence_transformer

        model = EmbeddingModel(model_name="test-model", device="cpu", batch_size=4)

        assert model.model is None
        assert model.device is None
        assert model.requested_device == "cpu"
        assert model.batch_size == 4
        model_cls.assert_not_called()

    def test_default_device_comes_from_settings(self, monkeypatch):
        monkeypatch.setattr(embeddings.settings, "embedding_device", "auto")
        assert EmbeddingModel().requested_device == "auto"

    def test_load_uses_the_resolved_device(self, fake_sentence_transformer):
        model_cls, _ = fake_sentence_transformer

        with patch.dict(sys.modules, {"torch": _fake_torch(cuda=False, mps=True)}):
            model = EmbeddingModel(model_name="test-model", device="auto")
            model.load()

        model_cls.assert_called_once_with("test-model", device="mps")
        assert model.device == "mps"
        assert model.get_embedding_dimension() == 3

    def test_load_falls_back_to_cpu(self, fake_sentence_transformer):
        model_cls, _ = fake_sentence_transformer

        with patch.dict(sys.modules, {"torch": _fake_torch(cuda=False, mps=False)}):
            model = EmbeddingModel(model_name="test-model", device="cuda")
            model.load()

        model_cls.assert_called_once_with("test-model", device="cpu")

    def test_load_errors_propagate(self, fake_sentence_transformer):
        model_cls, _ = fake_sentence_transformer
        model_cls.side_effect = OSError("model not found")

        model = EmbeddingModel(model_name="missing", device="cpu")
        with pytest.raises(OSError, match="model not found"):
            model.load()

    def test_encode_returns_lists_of_floats(self, fake_sentence_transformer):
        _, st_model = fake_sentence_transformer
        model = EmbeddingModel(model_name="m", device="cpu", batch_size=8)
        model.load()

        result = model.encode(["a", "b"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        st_model.encode.assert_called_once_with(
            ["a", "b"],
            batch_size=8,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_tensor=False,
        )

    def test_encode_query_wraps_a_single_text(self, fake_sentence_transformer):
        _, st_model = fake_sentence_transformer
        st_model.encode.return_value = np.array([[1.0, 0.0, 0.0]])
        model = EmbeddingModel(model_name="m", device="cpu")
        model.load()

        assert model.encode_query("question") == [1.0, 0.0, 0.0]
        assert st_model.encode.call_args.args[0] == ["question"]

    def test_encode_batch_shows_progress(self, fake_sentence_transformer):
        _, st_model = fake_sentence_transformer
        model = EmbeddingModel(model_name="m", device="cpu")
        model.load()

        assert len(model.encode_batch(["a", "b"])) == 2
        assert st_model.encode.call_args.kwargs["show_progress_bar"] is True

    def test_encode_requires_load(self):
        with pytest.raises(RuntimeError, match="not loaded"):
            EmbeddingModel(device="cpu").encode("text")

    def test_dimension_requires_load(self):
        with pytest.raises(RuntimeError, match="not loaded"):
            EmbeddingModel(device="cpu").get_embedding_dimension()

    def test_get_embedding_model_is_a_loaded_singleton(
        self, fake_sentence_transformer, monkeypatch
    ):
        model_cls, _ = fake_sentence_transformer
        monkeypatch.setattr(embeddings, "_embedding_model", None)
        monkeypatch.setattr(embeddings.settings, "embedding_device", "cpu")

        first = get_embedding_model()
        second = get_embedding_model()

        assert first is second
        assert first.model is not None
        model_cls.assert_called_once()

    def test_concurrent_first_calls_load_the_model_once(
        self, fake_sentence_transformer, monkeypatch
    ):
        import threading
        import time

        model_cls, model = fake_sentence_transformer

        def slow_load(*args, **kwargs):
            time.sleep(0.05)  # widen the race window
            return model

        model_cls.side_effect = slow_load
        monkeypatch.setattr(embeddings, "_embedding_model", None)
        monkeypatch.setattr(embeddings.settings, "embedding_device", "cpu")
        results: list[EmbeddingModel] = []

        threads = [
            threading.Thread(target=lambda: results.append(get_embedding_model())) for _ in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        model_cls.assert_called_once()
        assert len(results) == 8
        assert all(result is results[0] for result in results)

    def test_failed_load_is_not_cached(self, fake_sentence_transformer, monkeypatch):
        model_cls, _ = fake_sentence_transformer
        model_cls.side_effect = [OSError("download failed"), MagicMock()]
        monkeypatch.setattr(embeddings, "_embedding_model", None)
        monkeypatch.setattr(embeddings.settings, "embedding_device", "cpu")

        with pytest.raises(OSError):
            get_embedding_model()

        assert get_embedding_model().model is not None
        assert model_cls.call_count == 2


@pytest.mark.unit
def test_importing_embeddings_does_not_import_torch():
    """torch and sentence-transformers are only imported when a model is loaded."""
    code = (
        "import sys; import backend.app.nlp.embeddings; "
        "print('torch' in sys.modules, 'sentence_transformers' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=50,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "False False"
