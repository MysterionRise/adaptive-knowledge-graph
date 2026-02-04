"""
Test configuration and settings.
"""

from backend.app.core.settings import Settings


def test_settings_defaults():
    """Test that settings load with default values."""
    settings = Settings()
    assert settings.app_name == "Adaptive Professional Certifications"
    assert settings.app_version == "0.2.0"
    assert settings.neo4j_uri == "bolt://localhost:7687"
    assert settings.opensearch_host == "localhost"
    assert settings.llm_mode in ["local", "remote", "hybrid"]
    assert settings.privacy_local_only is True
    # New settings
    assert settings.api_key == ""  # Empty by default (dev mode)
    assert settings.rate_limit_enabled is True


def test_settings_attribution():
    """Test that OpenStax attribution is present."""
    settings = Settings()
    assert "OpenStax" in settings.attribution_openstax
    assert "CC BY 4.0" in settings.attribution_openstax


def test_llm_configuration():
    """Test LLM configuration options."""
    settings = Settings()
    assert settings.llm_local_backend in ["ollama", "llamacpp"]
    assert settings.llm_max_context > 0
    assert 0 <= settings.llm_temperature <= 1.0
