"""
Test configuration and settings.
"""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.core.settings import PRIVACY_LLM_MODE_ERROR, Settings

REMOVED_SETTINGS = [
    "api_host",
    "api_port",
    "llm_local_backend",
    "llm_max_context",
    "reranker_top_k",
    "rag_final_top_k",
    "student_irt_enabled",
    "student_storage_backend",
    "privacy_no_tracking",
    "graph_compute_centrality",
    "graph_compute_communities",
]


def test_settings_defaults():
    """Test that settings load with expected values."""
    settings = Settings()
    # App name/version can be overridden via .env - just verify they're non-empty
    assert settings.app_name, "app_name should not be empty"
    assert settings.app_version, "app_version should not be empty"
    assert settings.neo4j_uri == "bolt://localhost:7687"
    assert settings.opensearch_host == "localhost"
    assert settings.llm_mode in ["local", "remote", "hybrid"]
    assert settings.privacy_local_only is True
    # New settings
    assert settings.api_key == ""  # Empty by default (dev mode)
    assert settings.rate_limit_enabled is True
    assert settings.trust_proxy_headers is False


def test_settings_attribution():
    """Test that OpenStax attribution is present."""
    settings = Settings()
    assert "OpenStax" in settings.attribution_openstax
    assert "CC BY 4.0" in settings.attribution_openstax


def test_llm_configuration():
    """Test LLM configuration options."""
    settings = Settings()
    assert 0 <= settings.llm_temperature <= 1.0
    assert settings.llm_local_model


@pytest.mark.parametrize("llm_mode", ["local", "remote", "hybrid"])
@pytest.mark.parametrize("privacy_local_only", [True, False])
def test_privacy_requires_local_llm_mode(llm_mode, privacy_local_only):
    """PRIVACY_LOCAL_ONLY=true only starts with LLM_MODE=local (BREAKING for remote/hybrid)."""
    kwargs = {"_env_file": None, "llm_mode": llm_mode, "privacy_local_only": privacy_local_only}

    if privacy_local_only and llm_mode != "local":
        with pytest.raises(ValidationError, match=re.escape(PRIVACY_LLM_MODE_ERROR)):
            Settings(**kwargs)
        return

    settings = Settings(**kwargs)
    assert settings.llm_mode == llm_mode
    assert settings.remote_llm_allowed is (not privacy_local_only and llm_mode != "local")


def test_privacy_error_message_explains_the_fix():
    assert PRIVACY_LLM_MODE_ERROR == (
        "PRIVACY_LOCAL_ONLY=true requires LLM_MODE=local "
        "(set LLM_MODE=local or PRIVACY_LOCAL_ONLY=false)"
    )


def test_privacy_validation_applies_to_environment(monkeypatch):
    monkeypatch.setenv("PRIVACY_LOCAL_ONLY", "true")
    monkeypatch.setenv("LLM_MODE", "hybrid")

    with pytest.raises(ValidationError, match="PRIVACY_LOCAL_ONLY=true requires LLM_MODE=local"):
        Settings(_env_file=None)

    monkeypatch.setenv("PRIVACY_LOCAL_ONLY", "false")
    assert Settings(_env_file=None).remote_llm_allowed is True


def test_privacy_is_on_by_default(monkeypatch):
    monkeypatch.delenv("PRIVACY_LOCAL_ONLY", raising=False)
    monkeypatch.delenv("LLM_MODE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.privacy_local_only is True
    assert settings.llm_mode == "local"
    assert settings.remote_llm_allowed is False


@pytest.mark.parametrize("name", REMOVED_SETTINGS)
def test_unused_settings_removed(name):
    assert name not in Settings.model_fields


def test_embedding_device_defaults_to_auto(monkeypatch):
    monkeypatch.delenv("EMBEDDING_DEVICE", raising=False)
    assert Settings(_env_file=None).embedding_device == "auto"


def test_window_retrieval_settings_are_documented_as_opt_in(monkeypatch):
    monkeypatch.delenv("RAG_WINDOW_SIZE", raising=False)
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    settings = Settings(_env_file=None)
    fields = Settings.model_fields

    assert settings.rag_window_size == 1
    assert settings.vector_backend == "opensearch"
    assert "opt-in" in (fields["rag_window_retrieval"].description or "").lower()
    assert "VECTOR_BACKEND" in (fields["rag_window_retrieval"].description or "")
    assert "window retrieval" in (fields["vector_backend"].description or "")
    assert "0" in (fields["rag_window_size"].description or "")


def test_window_size_cannot_be_negative():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rag_window_size=-1)


def test_opensearch_replicas_default_to_zero(monkeypatch):
    monkeypatch.delenv("OPENSEARCH_NUMBER_OF_REPLICAS", raising=False)
    assert Settings(_env_file=None).opensearch_number_of_replicas == 0

    monkeypatch.setenv("OPENSEARCH_NUMBER_OF_REPLICAS", "1")
    assert Settings(_env_file=None).opensearch_number_of_replicas == 1

    with pytest.raises(ValidationError):
        Settings(_env_file=None, opensearch_number_of_replicas=-1)


def test_concept_validation_is_opt_in(monkeypatch):
    monkeypatch.delenv("STUDENT_VALIDATE_CONCEPTS", raising=False)
    assert Settings(_env_file=None).student_validate_concepts is False
    description = Settings.model_fields["student_validate_concepts"].description or ""
    assert "opt-in" in description.lower()


def test_subjects_config_found_from_another_working_directory(tmp_path, monkeypatch):
    """The __file__-relative fallback finds config/subjects.yaml at the repository root."""
    from backend.app.core import subjects

    repo_root = Path(subjects.__file__).resolve().parents[3]
    monkeypatch.chdir(tmp_path)
    subjects.clear_subjects_cache()
    try:
        assert subjects._find_config_path() == repo_root / "config" / "subjects.yaml"
        assert subjects.get_default_subject_id() in subjects.get_subject_ids()
    finally:
        subjects.clear_subjects_cache()
