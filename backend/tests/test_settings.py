"""
Test configuration and settings.
"""

from backend.app.core.settings import Settings


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
