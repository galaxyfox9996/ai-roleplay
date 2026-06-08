from __future__ import annotations

import json
from typing import Any


def recent_messages_for_prompt(messages: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for message in messages[-limit:]:
        content = message["content"]
        if message["role"] == "user":
            compact.append({"role": "user", "text": content.get("text", "")})
        else:
            compact.append(
                {
                    "role": "assistant",
                    "sceneText": truncate_text(content.get("sceneText", ""), 900),
                    "dialogue": content.get("dialogue", []),
                    "statePatch": content.get("statePatch", {}),
                    "memoryNotes": content.get("memoryNotes", []),
                }
            )
    return compact


def select_world_entries(
    world: dict[str, Any],
    user_text: str,
    recent_messages: list[dict[str, Any]],
    state: dict[str, Any],
    limit: int = 6,
) -> list[dict[str, Any]]:
    entries = [entry for entry in world.get("entries", []) if entry.get("enabled", True)]
    if not entries:
        return []

    search_text = build_entry_search_text(user_text, recent_messages, state)
    scored_entries = []
    for entry in entries:
        keys = [str(key).strip() for key in entry.get("keys", []) if str(key).strip()]
        score = int(entry.get("position") or 0)
        if entry.get("constant"):
            score += 10_000
        matched_keys = []
        for key in keys:
            if key.lower() in search_text:
                score += 1_000 + len(key)
                matched_keys.append(key)
        if entry.get("constant") or matched_keys:
            scored_entries.append((score, matched_keys, entry))

    if not scored_entries:
        scored_entries = [
            (int(entry.get("position") or 0), [], entry)
            for entry in entries
            if entry.get("constant")
        ]

    if not scored_entries:
        scored_entries = [(int(entry.get("position") or 0), [], entry) for entry in entries[:2]]

    scored_entries.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "keys": entry.get("keys", []),
            "matchedKeys": matched_keys,
            "content": truncate_text(entry.get("content", ""), 1200),
            "constant": bool(entry.get("constant")),
            "position": entry.get("position", 0),
        }
        for _, matched_keys, entry in scored_entries[:limit]
    ]


def build_entry_search_text(
    user_text: str,
    recent_messages: list[dict[str, Any]],
    state: dict[str, Any],
) -> str:
    parts = [user_text]
    for message in recent_messages[-4:]:
        parts.append(str(message.get("text") or ""))
        parts.append(str(message.get("sceneText") or ""))
        for note in message.get("memoryNotes", []) or []:
            parts.append(str(note))
        for line in message.get("dialogue", []) or []:
            if isinstance(line, dict):
                parts.append(str(line.get("text") or ""))
    parts.extend(
        [
            str(state.get("scene") or ""),
            str(state.get("location") or state.get("Location") or ""),
            str(state.get("mainGoal") or ""),
            str(state.get("mood") or ""),
            str(state.get("Class") or state.get("class") or ""),
            str(state.get("inventory") or state.get("Inventory") or ""),
            str(state.get("Equipment") or state.get("equipment") or ""),
        ]
    )
    return "\n".join(parts).lower()


def compact_world_for_prompt(world: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": world.get("id"),
        "title": world.get("title"),
        "premise": truncate_text(world.get("premise"), 1600),
        "tone": world.get("tone"),
        "factsPreview": [truncate_text(fact, 700) for fact in (world.get("facts") or [])[:3]],
        "uiSchema": world.get("uiSchema") if isinstance(world.get("uiSchema"), dict) else {},
    }


def describe_ui_schema(ui_schema: Any) -> str:
    if not isinstance(ui_schema, dict) or not ui_schema:
        return "当前世界书没有声明 uiSchema。可以使用通用状态字段，但不要创造不必要的状态面板字段。"

    lines = [f"状态 UI 标题：{ui_schema.get('title') or '世界状态'}"]
    for section in ui_schema.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        section_title = section.get("title") or "状态分组"
        lines.append(f"- 分组：{section_title}")
        for field in section.get("fields", []) or []:
            if not isinstance(field, dict):
                continue
            key = field.get("key")
            if not key:
                continue
            label = field.get("label") or key
            field_type = field.get("type") or "text"
            aliases = field.get("aliases") if isinstance(field.get("aliases"), list) else []
            alias_text = f"，别名：{', '.join(str(alias) for alias in aliases)}" if aliases else ""
            lines.append(f"  - {key}（{label}，{field_type}{alias_text}）")
    return "\n".join(lines)


def build_action_hints(user_text: str, state: dict[str, Any], summary: str) -> list[str]:
    action_text = user_text.lower()
    memory_text = summary.lower()
    hints: list[str] = []
    has_status_data = any(key in state for key in ("Class", "class", "BP", "Level", "Skills"))
    if any(keyword in action_text for keyword in ("装备", "物品", "inventory", "equipment", "背包")):
        hints.append(
            "用户本轮是在检查装备或物品，不是在重新打开 Status。直接列出 currentState 中的 Inventory/inventory 与 Equipment/equipment，并给出生存相关判断。"
        )
    if "status" in action_text or "状态" in action_text:
        hints.append(
            "用户本轮是在查看 Status/状态面板，应直接展示面板结果；若 currentState 已有 Class/BP/Level/Skills，则表示面板已经打开过，不要再要求用户说 Status。"
        )
    elif has_status_data:
        hints.append(
            "currentState 已有 Class/BP/Level/Skills，说明 Status 面板已经打开过。除非 userAction 明确要求说 Status，否则不要写用户再次说 Status。"
        )
    if "打开了battle song" in memory_text or "status面板已打开" in memory_text or "职业为" in memory_text:
        hints.append("长期记忆显示 Battle Song/Status 已经打开过，后续剧情应承认这个事实并继续推进。")
    return hints


def truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def trim_prompt(prompt: str, max_chars: int) -> str:
    if max_chars <= 0 or len(prompt) <= max_chars:
        return prompt
    notice = "\n\n[系统提示：Prompt 已按 PROMPT_MAX_CHARS 截断。]"
    return f"{prompt[: max_chars - len(notice)].rstrip()}{notice}"


def build_prompt(session: dict[str, Any], user_text: str, config: Any | None = None) -> str:
    recent_limit = int(getattr(config, "prompt_recent_message_limit", 8))
    entry_limit = int(getattr(config, "prompt_world_entry_limit", 6))
    max_chars = int(getattr(config, "prompt_max_chars", 18000))
    summary_limit = int(getattr(config, "summary_max_chars", 4000))
    long_term_summary = (
        truncate_text(session.get("summary", ""), summary_limit)
        if summary_limit > 0
        else ""
    )
    recent_messages = recent_messages_for_prompt(session["messages"], limit=recent_limit)
    selected_world_entries = select_world_entries(
        session["world"],
        user_text,
        recent_messages,
        session["state"],
        limit=entry_limit,
    )
    # Put continuity-critical fields first so prompt trimming keeps them.
    action_hints = build_action_hints(user_text, session["state"], long_term_summary)
    action_guidance = "\n".join(f"- {hint}" for hint in action_hints) or "- 无特殊提醒。"
    ui_schema = session["world"].get("uiSchema") if isinstance(session["world"].get("uiSchema"), dict) else {}
    ui_schema_guidance = describe_ui_schema(ui_schema)
    prompt_payload = {
        "userAction": user_text,
        "actionHints": action_hints,
        "currentState": session["state"],
        "stateUiSchema": ui_schema,
        "longTermSummary": long_term_summary,
        "recentMessages": recent_messages,
        "selectedWorldEntries": selected_world_entries,
        "character": session["character"],
        "world": compact_world_for_prompt(session["world"]),
    }
    prompt = f"""
你是一个 AI 剧情主持人，负责推进沉浸式角色扮演剧情。

硬性规则：
1. 始终保持角色卡和世界书设定一致。
2. 输出语言使用简体中文。世界书、职业名、地名、技能名等专有名词可以保留英文，但叙述、旁白、选项和普通台词要用中文。
3. userAction 是用户本轮已经选择并正在执行的动作；你必须写出这个动作的结果，不能再要求用户重复同一个动作。
4. 每一轮都必须让剧情前进一步，但不能替用户做决定。
5. 优先使用 selectedWorldEntries 中命中的世界书条目。
6. currentState 和 longTermSummary 是已发生事实。若其中显示某件事已经发生，后续不能重置、遗忘或倒退。
7. recentMessages 里的 statePatch 与 memoryNotes 也是连续性事实，要用来避免重复同一幕。
8. 如果用户查看 Status/Battle Song/状态/装备/物品，直接展示可见结果，并在 statePatch 写入可见面板字段。
9. 如果 stateUiSchema 存在，statePatch 必须优先使用 schema fields 里的 key；不要用别名作为 key。
10. 结尾必须提供 3 个行动选项，且不要把刚刚执行过的 userAction 原样作为选项。
11. 不要改写用户动作：用户说检查装备，就写检查装备的结果；用户没说 Status，就不要写用户说 Status。
12. sceneText 和 dialogue.text 使用普通叙述文本，不要使用 Markdown 标记、项目符号或加粗符号。
13. 输出必须是严格 JSON，不要 Markdown，不要解释文字，不要尾随逗号。
14. statePatch 只能写本轮发生变化或本轮明确揭示的状态。
15. memoryNotes 只写会影响长期连续性的事实、承诺、关系变化或未解线索，最多 3 条。

本轮用户动作：
{user_text}

本轮连续性提醒：
{action_guidance}

状态 UI schema：
{ui_schema_guidance}

输出 JSON 格式：
{{
  "sceneText": "场景叙述，1 到 3 段。",
  "dialogue": [
    {{"speaker": "角色名或旁白", "text": "台词或短句。"}}
  ],
  "choices": [
    {{"id": "choice_1", "text": "用户可执行行动。", "type": "dialogue|action|observe|leave"}},
    {{"id": "choice_2", "text": "用户可执行行动。", "type": "dialogue|action|observe|leave"}},
    {{"id": "choice_3", "text": "用户可执行行动。", "type": "dialogue|action|observe|leave"}}
  ],
  "statePatch": {{
    "schemaFieldKey": "仅填写本轮揭示或变化的状态；有 stateUiSchema 时必须使用 schema 中的 key"
  }},
  "memoryNotes": []
}}

输入资料：
{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}
""".strip()
    return trim_prompt(prompt, max_chars)
