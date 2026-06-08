from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
ENV_PATH = ROOT_DIR / ".env"
CHARACTER_DIRS = [ROOT_DIR / "characters"]
WORLD_BOOK_DIRS = [ROOT_DIR / "worldbooks"]


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    ollama_url: str
    ollama_model: str
    model_provider: str
    model_name: str
    model_base_url: str
    model_api_key: str
    model_timeout_seconds: int
    model_temperature: float
    model_max_tokens: int
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    openai_response_format: str
    deepseek_base_url: str
    deepseek_api_key: str
    deepseek_model: str
    prompt_recent_message_limit: int
    prompt_world_entry_limit: int
    prompt_max_chars: int
    summary_update_interval: int
    summary_max_chars: int


def parse_env_file(path: Path = ENV_PATH) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = strip_inline_comment(value.strip())
        if not key:
            continue
        values[key] = unquote_env_value(value)
    return values


def strip_inline_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            continue
        if char == "#" and quote is None:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()
    return value


def unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return (
        value.replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
        .replace(r"\"", '"')
        .replace(r"\'", "'")
        .replace(r"\\", "\\")
    )


def config_value(values: Mapping[str, str], key: str, default: str = "") -> str:
    return os.environ.get(key, values.get(key, default))


def load_config() -> AppConfig:
    env_file = parse_env_file()
    return AppConfig(
        host=config_value(env_file, "HOST", "127.0.0.1"),
        port=int(config_value(env_file, "PORT", "7860")),
        ollama_url=config_value(env_file, "OLLAMA_URL", "http://localhost:11434/api/generate"),
        ollama_model=config_value(env_file, "OLLAMA_MODEL", "llama3.1"),
        model_provider=config_value(env_file, "MODEL_PROVIDER", "ollama").strip().lower(),
        model_name=config_value(env_file, "MODEL_NAME", "").strip(),
        model_base_url=config_value(env_file, "MODEL_BASE_URL", "").strip(),
        model_api_key=config_value(env_file, "MODEL_API_KEY", ""),
        model_timeout_seconds=int(config_value(env_file, "MODEL_TIMEOUT_SECONDS", "45")),
        model_temperature=float(config_value(env_file, "MODEL_TEMPERATURE", "0.75")),
        model_max_tokens=int(config_value(env_file, "MODEL_MAX_TOKENS", "900")),
        openai_base_url=config_value(env_file, "OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_api_key=config_value(env_file, "OPENAI_API_KEY", ""),
        openai_model=config_value(env_file, "OPENAI_MODEL", ""),
        openai_response_format=config_value(env_file, "OPENAI_RESPONSE_FORMAT", "json_object").strip().lower(),
        deepseek_base_url=config_value(env_file, "DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_api_key=config_value(env_file, "DEEPSEEK_API_KEY", ""),
        deepseek_model=config_value(env_file, "DEEPSEEK_MODEL", "deepseek-chat"),
        prompt_recent_message_limit=int(config_value(env_file, "PROMPT_RECENT_MESSAGE_LIMIT", "8")),
        prompt_world_entry_limit=int(config_value(env_file, "PROMPT_WORLD_ENTRY_LIMIT", "6")),
        prompt_max_chars=int(config_value(env_file, "PROMPT_MAX_CHARS", "18000")),
        summary_update_interval=int(config_value(env_file, "SUMMARY_UPDATE_INTERVAL", "4")),
        summary_max_chars=int(config_value(env_file, "SUMMARY_MAX_CHARS", "4000")),
    )
