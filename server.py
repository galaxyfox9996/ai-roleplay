from __future__ import annotations

import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from roleplay.config import STATIC_DIR, load_config
from roleplay.providers import get_model_metadata
from roleplay.storage import (
    append_session_memory_notes,
    create_session,
    delete_message,
    delete_session,
    get_editor_payload,
    get_session,
    init_db,
    list_sessions,
    save_active_character_card,
    save_active_world_book,
    save_message,
    update_session_summary,
    update_session_state,
)
from roleplay.story_engine import generate_story
from roleplay.story_response import apply_state_patch_with_schema


CONFIG = load_config()
INTRO_RETRY_TEXT = (
    "Start a new game. Generate the opening scene, the first interaction, "
    "and three available actions using the current character card and world book."
)
RETRY_USER_TEXT_KEY = "_retryUserText"
CUSTOM_OPENING_MAX_CHARS = 1200


def truncate_inline(value: Any, max_chars: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def latest_user_text(session: dict[str, Any]) -> str:
    for message in reversed(session.get("messages", [])):
        if message.get("role") == "user":
            return str(message.get("content", {}).get("text") or "").strip()
    return ""


def compact_state_changes(state_patch: dict[str, Any]) -> str:
    changes = []
    for key in ("chapter", "scene", "location", "time", "mainGoal", "mood"):
        if key in state_patch:
            changes.append(f"{key}={truncate_inline(state_patch[key], 48)}")
    if "inventory" in state_patch:
        changes.append("inventory 已更新")
    if "activeQuests" in state_patch:
        changes.append("activeQuests 已更新")
    if "relationship" in state_patch:
        changes.append("relationship 已更新")
    return "；".join(changes)


def should_add_interval_summary(next_assistant_turn: int) -> bool:
    interval = max(0, int(CONFIG.summary_update_interval))
    return interval > 0 and next_assistant_turn % interval == 0


def build_interval_memory_note(
    session: dict[str, Any],
    story: dict[str, Any],
    next_assistant_turn: int,
) -> str:
    story_state = session.get("state", {})
    chapter = story_state.get("chapter", "-")
    location = story_state.get("location") or story_state.get("scene") or "未知地点"
    user_text = truncate_inline(latest_user_text(session), 72)
    scene_text = truncate_inline(story.get("sceneText", ""), 120)
    state_changes = compact_state_changes(story.get("statePatch", {}))
    parts = [f"第 {next_assistant_turn} 次 AI 回复后，第 {chapter} 章「{location}」"]
    if user_text:
        parts.append(f"用户行动：{user_text}")
    if scene_text:
        parts.append(f"剧情进展：{scene_text}")
    if state_changes:
        parts.append(f"状态变化：{state_changes}")
    return "；".join(parts)


def memory_notes_for_story(session: dict[str, Any], story: dict[str, Any]) -> list[str]:
    notes = [str(note).strip() for note in story.get("memoryNotes", []) if str(note).strip()]
    next_assistant_turn = (
        sum(1 for message in session.get("messages", []) if message.get("role") == "assistant") + 1
    )
    if should_add_interval_summary(next_assistant_turn):
        notes.append(build_interval_memory_note(session, story, next_assistant_turn))
    return notes


def restore_turn_snapshot(session_id: str, assistant_content: dict[str, Any]) -> None:
    previous_state = assistant_content.get("_previousState")
    if isinstance(previous_state, dict):
        update_session_state(session_id, previous_state)

    previous_summary = assistant_content.get("_previousSummary")
    if isinstance(previous_summary, str):
        update_session_summary(session_id, previous_summary, max_chars=CONFIG.summary_max_chars)


def append_assistant_turn(
    session_id: str,
    story: dict[str, Any],
    retry_user_text: str | None = None,
) -> dict[str, Any]:
    session = get_session(CONFIG, session_id)
    story["_previousState"] = session["state"]
    story["_previousSummary"] = session.get("summary", "")
    if retry_user_text:
        story[RETRY_USER_TEXT_KEY] = retry_user_text
    next_state = apply_state_patch_with_schema(
        session["state"],
        story.get("statePatch", {}),
        session.get("world", {}).get("uiSchema"),
    )
    update_session_state(session_id, next_state)
    append_session_memory_notes(
        session_id,
        memory_notes_for_story(session, story),
        max_chars=CONFIG.summary_max_chars,
    )
    return save_message(session_id, "assistant", story)


def retry_last_assistant_turn(session_id: str) -> dict[str, Any]:
    session = get_session(CONFIG, session_id)
    messages = session.get("messages", [])
    if not messages:
        raise ValueError("no messages to retry")

    last_message = messages[-1]
    if last_message["role"] != "assistant":
        raise ValueError("last message is not an assistant response")

    user_message = next((message for message in reversed(messages[:-1]) if message["role"] == "user"), None)
    retry_user_text = str(last_message.get("content", {}).get(RETRY_USER_TEXT_KEY) or "").strip()
    if not user_message and not retry_user_text and len(messages) == 1:
        retry_user_text = INTRO_RETRY_TEXT
    if not user_message and not retry_user_text:
        raise ValueError("no user message found for retry")

    restore_turn_snapshot(session["id"], last_message.get("content", {}))
    delete_message(session["id"], last_message["id"])

    user_text = retry_user_text or str(user_message.get("content", {}).get("text") or "").strip()
    if not user_text:
        raise ValueError("last user message has no text")

    session = get_session(CONFIG, session["id"])
    story = generate_story(CONFIG, session, user_text)
    assistant_message = append_assistant_turn(session["id"], story, retry_user_text=user_text)
    return {
        "session": get_session(CONFIG, session["id"]),
        "assistantMessage": assistant_message,
    }


def delete_last_turn(session_id: str) -> dict[str, Any]:
    session = get_session(CONFIG, session_id)
    messages = session.get("messages", [])
    if not messages:
        raise ValueError("no messages to delete")

    last_message = messages[-1]
    if last_message["role"] == "assistant":
        restore_turn_snapshot(session["id"], last_message.get("content", {}))
        delete_message(session["id"], last_message["id"])
        messages = messages[:-1]
        if messages and messages[-1]["role"] == "user":
            delete_message(session["id"], messages[-1]["id"])
    elif last_message["role"] == "user":
        delete_message(session["id"], last_message["id"])
    else:
        raise ValueError("unsupported last message role")

    return {"session": get_session(CONFIG, session["id"])}


def edit_last_user_turn(session_id: str, user_text: str) -> dict[str, Any]:
    user_text = user_text.strip()
    if not user_text:
        raise ValueError("text is required")

    session = get_session(CONFIG, session_id)
    messages = session.get("messages", [])
    if not messages:
        raise ValueError("no messages to edit")

    last_message = messages[-1]
    if last_message["role"] == "assistant":
        restore_turn_snapshot(session["id"], last_message.get("content", {}))
        delete_message(session["id"], last_message["id"])
        messages = messages[:-1]

    if not messages or messages[-1]["role"] != "user":
        raise ValueError("last user message not found")

    delete_message(session["id"], messages[-1]["id"])
    user_message = save_message(session["id"], "user", {"text": user_text})
    session = get_session(CONFIG, session["id"])
    story = generate_story(CONFIG, session, user_text)
    assistant_message = append_assistant_turn(session["id"], story, retry_user_text=user_text)

    return {
        "session": get_session(CONFIG, session["id"]),
        "userMessage": user_message,
        "assistantMessage": assistant_message,
    }


def start_session_with_intro(
    character_id: str | None = None,
    world_id: str | None = None,
    world_mode: str | None = None,
    opening_mode: str | None = None,
    opening_option_id: str | None = None,
    custom_opening_text: str | None = None,
) -> dict[str, Any]:
    character_only = str(world_mode or "").strip().lower() in {"characteronly", "character_only", "cardonly"}
    session = create_session(
        CONFIG,
        character_id=character_id,
        world_id=world_id,
        character_only=character_only,
    )
    intro_text, state_patch, warning = resolve_opening_prompt(
        session,
        opening_mode=opening_mode,
        opening_option_id=opening_option_id,
        custom_opening_text=custom_opening_text,
    )
    if state_patch:
        next_state = apply_state_patch_with_schema(
            session.get("state", {}),
            state_patch,
            session.get("world", {}).get("uiSchema"),
        )
        update_session_state(session["id"], next_state)
        session = get_session(CONFIG, session["id"])
    story = generate_story(CONFIG, session, intro_text)
    assistant_message = append_assistant_turn(session["id"], story, retry_user_text=intro_text)
    payload = {
        "session": get_session(CONFIG, session["id"]),
        "assistantMessage": assistant_message,
    }
    if warning:
        payload["warning"] = warning
    return payload


def resolve_opening_prompt(
    session: dict[str, Any],
    opening_mode: str | None = None,
    opening_option_id: str | None = None,
    custom_opening_text: str | None = None,
) -> tuple[str, dict[str, Any], str]:
    world = session.get("world") if isinstance(session.get("world"), dict) else {}
    mode = str(opening_mode or "default").strip().lower()
    option_id = str(opening_option_id or "").strip()
    custom_text = str(custom_opening_text or "").strip()[:CUSTOM_OPENING_MAX_CHARS]

    if mode == "custom" and custom_text:
        return (
            "这是用户自定义开局要求。请严格围绕该要求生成第一幕，同时保持当前世界书、角色卡、"
            f"状态 UI schema 和角色卡模式一致。\n\n用户自定义开局：\n{custom_text}",
            {},
            "",
        )

    if mode == "option":
        options = world.get("openingOptions") if isinstance(world.get("openingOptions"), list) else []
        selected = next((item for item in options if str(item.get("id") or "") == option_id), None)
        if isinstance(selected, dict):
            tags = selected.get("tags") if isinstance(selected.get("tags"), list) else []
            description = str(selected.get("description") or "").strip()
            tag_text = f"\n风格标签：{', '.join(str(tag) for tag in tags)}" if tags else ""
            description_text = f"\n开局简介：{description}" if description else ""
            patch = selected.get("initialStatePatch") if isinstance(selected.get("initialStatePatch"), dict) else {}
            return (
                "这是世界书预设开局。请严格使用该开局作为第一幕起点，不要随机切换到其他起点。"
                f"\n开局标题：{selected.get('title')}"
                f"{description_text}"
                f"{tag_text}"
                f"\n\n开局指令：\n{selected.get('prompt')}",
                patch,
                "",
            )
        return default_opening_prompt(world), {}, "未找到指定开局选项，已回退到默认开局。"

    if mode == "custom" and not custom_text:
        return default_opening_prompt(world), {}, "自定义开局为空，已回退到默认开局。"

    return default_opening_prompt(world), {}, ""


def default_opening_prompt(world: dict[str, Any]) -> str:
    if world.get("id") == "__character_only__":
        return (
            "新游戏开场。仅使用当前角色卡开始，不加载任何世界书条目、世界书开场或世界书状态 schema。"
            "请根据角色卡的人设、scenario、firstMessage、exampleDialogue 和角色卡模式生成第一幕。"
            "如果角色卡是 NPC 型，AI 可以扮演该角色并向用户开启互动；"
            "如果角色卡是主角型，用户扮演该角色，AI 只负责旁白、环境、NPC、敌人和世界反馈。"
            "第一幕要给出明确情境和 3 个行动选项。"
        )
    opening_scene = str(world.get("openingScene") or "").strip()
    return opening_scene or INTRO_RETRY_TEXT


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {format % args}")

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body)

    def do_GET(self) -> None:
        if self.path == "/api/editor":
            self.send_json(200, get_editor_payload())
            return

        if self.path == "/api/sessions":
            self.send_json(200, {"sessions": list_sessions()})
            return

        if self.path.startswith("/api/session"):
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
            self.send_json(200, get_session(CONFIG, params.get("id")))
            return

        if self.path == "/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "model": get_model_metadata(CONFIG),
                    "prompt": {
                        "recentMessageLimit": CONFIG.prompt_recent_message_limit,
                        "worldEntryLimit": CONFIG.prompt_world_entry_limit,
                        "maxChars": CONFIG.prompt_max_chars,
                        "summaryUpdateInterval": CONFIG.summary_update_interval,
                        "summaryMaxChars": CONFIG.summary_max_chars,
                    },
                },
            )
            return

        super().do_GET()

    def do_POST(self) -> None:
        try:
            if self.path == "/api/session/reset":
                self.send_json(200, start_session_with_intro())
                return

            if self.path == "/api/session/start":
                payload = self.read_json()
                self.send_json(
                    200,
                    start_session_with_intro(
                        character_id=str(payload.get("characterId") or ""),
                        world_id=str(payload.get("worldId") or ""),
                        world_mode=str(payload.get("worldMode") or "worldBook"),
                        opening_mode=str(payload.get("openingMode") or "default"),
                        opening_option_id=str(payload.get("openingOptionId") or ""),
                        custom_opening_text=str(payload.get("customOpeningText") or ""),
                    ),
                )
                return

            if self.path == "/api/session/delete":
                payload = self.read_json()
                session_id = str(payload.get("sessionId") or "")
                if not session_id:
                    self.send_json(400, {"error": "sessionId is required"})
                    return
                if not delete_session(session_id):
                    self.send_json(404, {"error": "session not found"})
                    return
                self.send_json(200, {"ok": True, "sessions": list_sessions()})
                return

            if self.path == "/api/session/summary":
                payload = self.read_json()
                session_id = str(payload.get("sessionId") or "")
                if not session_id:
                    self.send_json(400, {"error": "sessionId is required"})
                    return
                update_session_summary(
                    session_id,
                    str(payload.get("summary") or ""),
                    max_chars=CONFIG.summary_max_chars,
                )
                self.send_json(200, {"session": get_session(CONFIG, session_id)})
                return

            if self.path == "/api/editor/character":
                character = save_active_character_card(self.read_json())
                self.send_json(200, {"character": character, "editor": get_editor_payload()})
                return

            if self.path == "/api/editor/world":
                world = save_active_world_book(self.read_json())
                self.send_json(200, {"world": world, "editor": get_editor_payload()})
                return

            if self.path == "/api/message":
                payload = self.read_json()
                session_id = str(payload.get("sessionId") or "")
                user_text = str(payload.get("text") or "").strip()
                if not user_text:
                    self.send_json(400, {"error": "text is required"})
                    return

                session = get_session(CONFIG, session_id)
                user_message = save_message(session["id"], "user", {"text": user_text})
                session = get_session(CONFIG, session["id"])

                story = generate_story(CONFIG, session, user_text)
                assistant_message = append_assistant_turn(session["id"], story, retry_user_text=user_text)

                self.send_json(
                    200,
                    {
                        "session": get_session(CONFIG, session["id"]),
                        "userMessage": user_message,
                        "assistantMessage": assistant_message,
                    },
                )
                return

            if self.path == "/api/message/retry":
                payload = self.read_json()
                session_id = str(payload.get("sessionId") or "")
                if not session_id:
                    self.send_json(400, {"error": "sessionId is required"})
                    return
                self.send_json(200, retry_last_assistant_turn(session_id))
                return

            if self.path == "/api/message/delete-last-turn":
                payload = self.read_json()
                session_id = str(payload.get("sessionId") or "")
                if not session_id:
                    self.send_json(400, {"error": "sessionId is required"})
                    return
                self.send_json(200, delete_last_turn(session_id))
                return

            if self.path == "/api/message/edit-last-user":
                payload = self.read_json()
                session_id = str(payload.get("sessionId") or "")
                user_text = str(payload.get("text") or "")
                if not session_id:
                    self.send_json(400, {"error": "sessionId is required"})
                    return
                self.send_json(200, edit_last_user_turn(session_id, user_text))
                return

            self.send_json(404, {"error": "not found"})
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((CONFIG.host, CONFIG.port), AppHandler)
    model = get_model_metadata(CONFIG)
    print(f"AI Roleplay Engine running at http://{CONFIG.host}:{CONFIG.port}")
    print(f"Model provider: {model['provider']} | model: {model['name']} | url: {model['url']}")
    server.serve_forever()


if __name__ == "__main__":
    main()
