"""Integration tests for the configured LiteLLM endpoint.

These tests make a real API request and therefore must be enabled explicitly:

    $env:RUN_LLM_INTEGRATION_TESTS="1"
    uv run pytest tests/test_llm_integration.py -v
"""

import os
from pathlib import Path
from urllib.parse import urlparse

import litellm
import pytest

from app.core.config import settings
from app.services.llm import LLMService

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = PROJECT_ROOT / ".env"
RUN_LLM_INTEGRATION_TESTS = os.getenv("RUN_LLM_INTEGRATION_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


@pytest.mark.llm_integration
@pytest.mark.skipif(
    not RUN_LLM_INTEGRATION_TESTS,
    reason="set RUN_LLM_INTEGRATION_TESTS=1 to call the configured LLM endpoint",
)
class TestLLMIntegration:
    """Validate the .env configuration and make a real LiteLLM request."""

    @pytest.fixture
    def service(self) -> LLMService:
        return LLMService()

    def test_configuration_from_dotenv(self, service: LLMService) -> None:
        """The values consumed by LLMService should be complete and usable."""
        assert DOTENV_PATH.is_file(), f"missing configuration file: {DOTENV_PATH}"
        assert service.provider == settings.ai_provider
        assert service.model == settings.ai_model
        assert service.base_url == settings.ai_base_url
        assert service.api_key == settings.ai_api_key

        assert service.provider and service.provider != "mock", "AI provider is not enabled"
        assert service.model.strip(), "AI model is empty"
        assert service.api_key.strip(), "AI API key is empty"
        assert service.enabled, "LLMService is disabled by the current configuration"
        assert service.timeout > 0, "AI timeout must be greater than zero"
        assert service.max_retries >= 0, "AI max retries cannot be negative"
        assert callable(litellm.completion)

        parsed_base_url = urlparse(service.base_url)
        assert parsed_base_url.scheme in {"http", "https"}, "AI base URL must use HTTP(S)"
        assert parsed_base_url.netloc, "AI base URL must include a host"

    def test_litellm_completion_is_available(self, service: LLMService) -> None:
        """A minimal real completion verifies endpoint, model and credentials together."""
        service.max_retries = 0
        error_message = ""
        try:
            response = service.extract_raw_json(
                [
                    {
                        "role": "system",
                        "content": "Reply with only the text SQUIRREL_LLM_OK.",
                    },
                    {"role": "user", "content": "Connectivity check."},
                ]
            )
        except Exception as exc:
            error_message = f"LiteLLM request failed ({type(exc).__name__}): {exc}"

        if error_message:
            pytest.fail(error_message, pytrace=False)

        assert response, "LiteLLM returned an empty response"
        assert "SQUIRREL_LLM_OK" in response, f"unexpected LiteLLM response: {response!r}"
