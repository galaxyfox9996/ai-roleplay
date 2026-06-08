from __future__ import annotations

import json
import re
from typing import Any

from .defaults import FALLBACK_CHOICES


def parse_model_json(raw_text: str) -> dict[str, Any]:
    try:
        return normalize_story_response(json.loads(raw_text))
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
        if not match:
            raise
        return normalize_story_response(json.loads(match.group(0)))


def normalize_story_response(data: dict[str, Any]) -> dict[str, Any]:
    scene_text = str(data.get("sceneText") or data.get("narration") or "").strip()
    dialogue = data.get("dialogue") if isinstance(data.get("dialogue"), list) else []
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    state_patch = data.get("statePatch") if isinstance(data.get("statePatch"), dict) else {}
    memory_notes = data.get("memoryNotes") if isinstance(data.get("memoryNotes"), list) else []
    state_patch = merge_missing_state(state_patch, extract_status_panel(scene_text))

    normalized_choices = []
    for index, choice in enumerate(choices[:3], start=1):
        if not isinstance(choice, dict):
            continue
        text = str(choice.get("text") or choice.get("label") or "").strip()
        if not text:
            continue
        normalized_choices.append(
            {
                "id": str(choice.get("id") or f"choice_{index}"),
                "text": text,
                "type": str(choice.get("type") or "action"),
            }
        )

    while len(normalized_choices) < 3:
        normalized_choices.append(FALLBACK_CHOICES[len(normalized_choices)])

    if not scene_text:
        scene_text = "雨声压低了房间里的沉默，新的线索正在等待你确认。"

    return {
        "sceneText": scene_text,
        "dialogue": [
            {
                "speaker": str(item.get("speaker", "旁白")),
                "text": str(item.get("text", "")),
            }
            for item in dialogue
            if isinstance(item, dict) and item.get("text")
        ],
        "choices": normalized_choices,
        "statePatch": state_patch,
        "memoryNotes": [str(note) for note in memory_notes if str(note).strip()],
    }


def normalize_story_with_schema(story: dict[str, Any], ui_schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ui_schema, dict) or not ui_schema:
        return story

    normalized = dict(story)
    state_patch = normalized.get("statePatch") if isinstance(normalized.get("statePatch"), dict) else {}
    schema_patch = normalize_state_patch_with_schema(state_patch, ui_schema)
    schema_patch = merge_missing_state(
        schema_patch,
        extract_status_panel_with_schema(str(normalized.get("sceneText") or ""), ui_schema),
    )
    normalized["statePatch"] = schema_patch
    return normalized


def iter_schema_fields(ui_schema: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for section in ui_schema.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        for field in section.get("fields", []) or []:
            if isinstance(field, dict) and field.get("key"):
                fields.append(field)
    return fields


def schema_alias_map(ui_schema: dict[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for field in iter_schema_fields(ui_schema):
        key = str(field["key"])
        aliases[key.lower()] = key
        label = field.get("label")
        if label:
            aliases[str(label).lower()] = key
        for alias in field.get("aliases", []) or []:
            aliases[str(alias).lower()] = key
    return aliases


def schema_field_map(ui_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(field["key"]): field for field in iter_schema_fields(ui_schema)}


def normalize_state_patch_with_schema(state_patch: dict[str, Any], ui_schema: dict[str, Any]) -> dict[str, Any]:
    aliases = schema_alias_map(ui_schema)
    fields = schema_field_map(ui_schema)
    normalized: dict[str, Any] = {}
    for raw_key, value in state_patch.items():
        key = aliases.get(str(raw_key).lower(), str(raw_key))
        normalized[key] = normalize_schema_value(value, fields.get(key, {}))
    return normalized


def normalize_schema_value(value: Any, field: dict[str, Any]) -> Any:
    field_type = str(field.get("type") or "").lower()
    if field_type in {"list", "tags"}:
        if isinstance(value, list):
            return value
        return parse_status_list(str(value))
    if field_type in {"number", "meter"}:
        if isinstance(value, (int, float)):
            return value
        return parse_status_number(str(value))
    return value


def extract_status_panel_with_schema(text: str, ui_schema: dict[str, Any]) -> dict[str, Any]:
    fields = schema_field_map(ui_schema)
    labels: list[tuple[str, str]] = []
    for field in fields.values():
        key = str(field["key"])
        labels.append((key, key))
        if field.get("label"):
            labels.append((str(field["label"]), key))
        for alias in field.get("aliases", []) or []:
            labels.append((str(alias), key))

    extracted: dict[str, Any] = {}
    for label, key in labels:
        pattern = re.compile(rf"^\s*{re.escape(label)}\s*[:：]\s*(.+?)\s*$", flags=re.IGNORECASE | re.MULTILINE)
        match = pattern.search(text)
        if match:
            extracted[key] = normalize_schema_value(match.group(1).strip(), fields.get(key, {}))
    return extracted


def apply_state_patch_with_schema(
    base: dict[str, Any],
    patch: dict[str, Any],
    ui_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = json.loads(json.dumps(base, ensure_ascii=False))
    if not isinstance(ui_schema, dict) or not ui_schema:
        return merge_dicts(merged, patch)

    fields = schema_field_map(ui_schema)
    normalized_patch = normalize_state_patch_with_schema(patch, ui_schema)
    for key, value in normalized_patch.items():
        field = fields.get(key, {})
        if field.get("merge") == "appendUnique":
            existing = merged.get(key, [])
            merged[key] = append_unique(existing, value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_dicts(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(base, ensure_ascii=False))
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def append_unique(existing: Any, incoming: Any) -> list[Any]:
    values = existing if isinstance(existing, list) else parse_status_list(str(existing))
    additions = incoming if isinstance(incoming, list) else parse_status_list(str(incoming))
    result = list(values)
    seen = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in result}
    for item in additions:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if marker not in seen:
            result.append(item)
            seen.add(marker)
    return result


def merge_missing_state(base: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    if not extracted:
        return base
    merged = dict(base)
    for key, value in extracted.items():
        if key not in merged:
            merged[key] = value
    return merged


def extract_status_panel(text: str) -> dict[str, Any]:
    if not text:
        return {}

    label_map = {
        "class": "class",
        "职业": "class",
        "level": "level",
        "等级": "level",
        "battle power": "bp",
        "bp": "bp",
        "战力": "bp",
        "skills": "skills",
        "技能": "skills",
        "spells": "spells",
        "法术": "spells",
        "abilities": "abilities",
        "能力": "abilities",
        "inventory": "inventory",
        "物品": "inventory",
        "equipment": "equipment",
        "装备": "equipment",
        "gold": "gold",
        "金币": "gold",
        "reputation": "reputation",
        "声望": "reputation",
        "relationships": "relationships",
        "关系": "relationships",
        "objectives": "objectives",
        "目标": "objectives",
        "location": "location",
        "地点": "location",
        "threat level": "threatLevel",
        "威胁等级": "threatLevel",
    }
    list_keys = {"skills", "spells", "abilities", "inventory", "equipment"}
    number_keys = {"level", "bp", "gold", "reputation"}

    extracted: dict[str, Any] = {}
    pattern = re.compile(
        r"^\s*(Class|职业|Level|等级|Battle Power|BP|战力|Skills|技能|Spells|法术|"
        r"Abilities|能力|Inventory|物品|Equipment|装备|Gold|金币|Reputation|声望|"
        r"Relationships|关系|Objectives|目标|Location|地点|Threat Level|威胁等级)\s*[:：]\s*(.+?)\s*$",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    for match in pattern.finditer(text):
        key = label_map.get(match.group(1).strip().lower())
        if not key:
            continue
        value_text = match.group(2).strip()
        if key in list_keys:
            extracted[key] = parse_status_list(value_text)
        elif key in number_keys:
            extracted[key] = parse_status_number(value_text)
        else:
            extracted[key] = value_text
    return extracted


def parse_status_list(value: str) -> list[str]:
    if not value or value.lower() in {"none", "null", "无", "暂无"}:
        return []
    return [item.strip() for item in re.split(r"[,，、/]+", value) if item.strip()]


def parse_status_number(value: str) -> int | str:
    match = re.search(r"-?\d+", value)
    if not match:
        return value
    number = int(match.group(0))
    return number if value.strip() == match.group(0) else value


def fallback_story_response(user_text: str, state: dict[str, Any], reason: str) -> dict[str, Any]:
    location = state.get("location") or state.get("Location") or "当前场景"
    scene_text = (
        f"你选择了：{user_text}\n\n"
        f"{location} 的空气短暂地安静下来，剧情主持暂时接管了这一轮。"
        "外部模型没有返回可用的结构化剧情，因此系统先用本地回复保持流程继续。"
    )
    return {
        "sceneText": scene_text,
        "dialogue": [
            {
                "speaker": "旁白",
                "text": "先继续推进这一幕。等外部模型恢复稳定后，后续剧情会重新由 AI 生成。",
            }
        ],
        "choices": FALLBACK_CHOICES,
        "statePatch": {
            "mood": "警觉",
        },
        "memoryNotes": [f"本轮使用 fallback 回复，原因：{reason}"],
    }
