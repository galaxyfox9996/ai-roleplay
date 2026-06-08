from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from .config import AppConfig
from .story_response import parse_model_json


class ModelProviderError(RuntimeError):
    pass


class ModelProvider:
    provider_id = "base"

    def __init__(self, model_name: str, url: str) -> None:
        self.model_name = model_name
        self.url = url

    def metadata(self) -> dict[str, str]:
        return {
            "provider": self.provider_id,
            "name": self.model_name,
            "url": self.url,
        }

    def generate(self, prompt: str) -> dict[str, Any]:
        raise NotImplementedError


def post_json(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


class OllamaProvider(ModelProvider):
    provider_id = "ollama"

    def __init__(self, config: AppConfig) -> None:
        super().__init__(config.model_name or config.ollama_model, config.ollama_url)
        self.config = config

    def generate(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.config.model_temperature,
                "num_predict": self.config.model_max_tokens,
            },
        }
        data = post_json(self.url, payload, self.config.model_timeout_seconds)
        return parse_model_json(data.get("response", ""))


class OpenAICompatibleProvider(ModelProvider):
    provider_id = "openai-compatible"

    def __init__(
        self,
        config: AppConfig,
        provider_id: str,
        model_name: str,
        base_url: str,
        api_key: str,
        requires_api_key: bool,
    ) -> None:
        super().__init__(model_name, f"{base_url.rstrip('/')}/chat/completions")
        self.config = config
        self.provider_id = provider_id
        self.api_key = api_key
        self.requires_api_key = requires_api_key

    def generate(self, prompt: str) -> dict[str, Any]:
        if not self.model_name:
            raise ModelProviderError("MODEL_NAME is required")
        if self.requires_api_key and not self.api_key:
            raise ModelProviderError("API key is required")

        system_prompt = (
            "Return strict JSON only. Do not include Markdown or explanatory text. "
            "The response must parse with json.loads. Write narration, dialogue, and choices in Simplified Chinese unless the user explicitly asks otherwise."
        )
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.model_temperature,
            "max_tokens": self.config.model_max_tokens,
        }
        if self.config.openai_response_format != "none":
            payload["response_format"] = {"type": self.config.openai_response_format}

        try:
            return self._post_and_parse(payload)
        except json.JSONDecodeError:
            retry_payload = {
                **payload,
                "temperature": min(self.config.model_temperature, 0.25),
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{system_prompt} Do not omit commas, quotes, closing brackets, "
                            "or closing braces."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            }
            return self._post_and_parse(retry_payload)

    def _post_and_parse(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            data = post_json(self.url, payload, self.config.model_timeout_seconds, headers)
        except error.HTTPError:
            if "response_format" not in payload:
                raise
            payload.pop("response_format", None)
            data = post_json(self.url, payload, self.config.model_timeout_seconds, headers)

        choices = data.get("choices", [])
        if not choices:
            raise ModelProviderError("model response has no choices")
        message = choices[0].get("message", {})
        return parse_model_json(str(message.get("content", "")))


class ForcedFallbackProvider(ModelProvider):
    provider_id = "fallback"

    def __init__(self) -> None:
        super().__init__("local-fallback", "local")

    def generate(self, prompt: str) -> dict[str, Any]:
        raise ModelProviderError("fallback provider selected")


def get_model_provider(config: AppConfig) -> ModelProvider:
    provider = config.model_provider
    if provider == "ollama":
        return OllamaProvider(config)
    if provider in {"openai", "gpt"}:
        return OpenAICompatibleProvider(
            config,
            "openai",
            config.model_name or config.openai_model,
            config.model_base_url or config.openai_base_url,
            config.model_api_key or config.openai_api_key,
            True,
        )
    if provider == "deepseek":
        return OpenAICompatibleProvider(
            config,
            "deepseek",
            config.model_name or config.deepseek_model,
            config.model_base_url or config.deepseek_base_url,
            config.model_api_key or config.deepseek_api_key,
            True,
        )
    if provider in {"openai-compatible", "openai_compatible", "compatible"}:
        return OpenAICompatibleProvider(
            config,
            "openai-compatible",
            config.model_name or config.openai_model,
            config.model_base_url or config.openai_base_url,
            config.model_api_key or config.openai_api_key,
            False,
        )
    if provider == "fallback":
        return ForcedFallbackProvider()
    raise ModelProviderError(f"unsupported MODEL_PROVIDER: {config.model_provider}")


def get_model_metadata(config: AppConfig) -> dict[str, str]:
    try:
        return get_model_provider(config).metadata()
    except ModelProviderError as exc:
        return {
            "provider": config.model_provider or "unknown",
            "name": config.model_name or config.openai_model or config.deepseek_model or config.ollama_model,
            "url": str(exc),
        }
