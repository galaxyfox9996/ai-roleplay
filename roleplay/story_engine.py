from __future__ import annotations

import json
from typing import Any
from urllib import error

from .config import AppConfig
from .prompting import build_prompt
from .providers import ModelProviderError, get_model_provider
from .story_response import fallback_story_response, normalize_story_with_schema


def generate_story(config: AppConfig, session: dict[str, Any], user_text: str) -> dict[str, Any]:
    prompt = build_prompt(session, user_text, config)
    try:
        provider = get_model_provider(config)
        response = provider.generate(prompt)
        response = normalize_story_with_schema(response, session.get("world", {}).get("uiSchema"))
        response["source"] = provider.provider_id
        return response
    except (ModelProviderError, OSError, error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
        response = fallback_story_response(user_text, session["state"], str(exc))
        response["source"] = "fallback"
        return response
