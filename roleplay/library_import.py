from __future__ import annotations

import base64
import json
import re
import sqlite3
import struct
import uuid
import zlib
from pathlib import Path
from typing import Any

from .config import CHARACTER_DIRS, WORLD_BOOK_DIRS
from .utils import now_ms


def import_library_files(conn: sqlite3.Connection) -> dict[str, int]:
    imported = {"characters": 0, "worlds": 0}
    for directory in CHARACTER_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
        for path in iter_library_files(directory, {".json", ".png"}):
            if path.suffix.lower() == ".json":
                card = read_character_json(path)
            elif path.suffix.lower() == ".png":
                card = read_character_png(path)
            else:
                continue
            if card:
                upsert_character(conn, path, card)
                imported["characters"] += 1

    for directory in WORLD_BOOK_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
        for path in iter_library_files(directory, {".json"}):
            world = read_world_book_json(path)
            if world:
                upsert_world(conn, path, world)
                imported["worlds"] += 1
    return imported


def iter_library_files(directory: Path, suffixes: set[str]) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    )


def stable_file_id(kind: str, path: Path) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ai-roleplay-engine:{kind}:{path.resolve()}"))


def read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def normalize_entry_keys(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def split_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def normalize_opening_options(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    options = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not title or not prompt:
            continue
        option_id = str(item.get("id") or "").strip() or slugify_opening_id(title, index)
        if option_id in seen_ids:
            option_id = f"{option_id}-{index + 1}"
        seen_ids.add(option_id)
        patch = item.get("initialStatePatch")
        options.append(
            {
                "id": option_id,
                "title": title,
                "description": str(item.get("description") or "").strip(),
                "prompt": prompt,
                "initialStatePatch": patch if isinstance(patch, dict) else {},
                "tags": split_lines(item.get("tags")),
            }
        )
    return options


def slugify_opening_id(title: str, index: int) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return ascii_slug or f"opening-{index + 1}"


def read_character_json(path: Path) -> dict[str, Any] | None:
    data = read_json_file(path)
    if not data:
        return None
    return normalize_character_payload(data, path.stem)


def read_character_png(path: Path) -> dict[str, Any] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None

    position = 8
    while position + 12 <= len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        chunk_type = data[position + 4 : position + 8]
        chunk = data[position + 8 : position + 8 + length]
        position += length + 12

        payload = decode_png_text_chunk(chunk_type, chunk)
        if not payload:
            continue
        key, value = payload
        if key not in {"chara", "ccv3"}:
            continue
        try:
            decoded = base64.b64decode(value).decode("utf-8")
            data_json = json.loads(decoded)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        return normalize_character_payload(data_json, path.stem)
    return None


def decode_png_text_chunk(chunk_type: bytes, chunk: bytes) -> tuple[str, str] | None:
    try:
        if chunk_type == b"tEXt":
            key, value = chunk.split(b"\x00", 1)
            return key.decode("latin1"), value.decode("latin1")
        if chunk_type == b"zTXt":
            key, rest = chunk.split(b"\x00", 1)
            if not rest:
                return None
            value = zlib.decompress(rest[1:]).decode("utf-8")
            return key.decode("latin1"), value
        if chunk_type == b"iTXt":
            parts = chunk.split(b"\x00", 5)
            if len(parts) < 6:
                return None
            key = parts[0].decode("latin1")
            compression_flag = parts[1]
            text = parts[5]
            value = zlib.decompress(text).decode("utf-8") if compression_flag == b"\x01" else text.decode("utf-8")
            return key, value
    except (ValueError, UnicodeDecodeError, zlib.error):
        return None
    return None


def normalize_character_payload(data: dict[str, Any], fallback_name: str) -> dict[str, Any] | None:
    card = data.get("data") if isinstance(data.get("data"), dict) else data
    name = str(card.get("name") or data.get("name") or fallback_name).strip()
    if not name:
        return None

    description = str(card.get("description") or card.get("role") or "").strip()
    personality = str(card.get("personality") or "").strip()
    scenario = str(card.get("scenario") or "").strip()
    first_message = str(card.get("first_mes") or "").strip()
    examples = str(card.get("mes_example") or "").strip()
    creator_notes = str(card.get("creator_notes") or "").strip()
    tags = card.get("tags") if isinstance(card.get("tags"), list) else data.get("tags")
    card_type = normalize_card_type(
        card.get("cardType")
        or card.get("card_type")
        or data.get("cardType")
        or data.get("card_type")
        or infer_card_type(description, personality, scenario, creator_notes)
    )

    rules = []
    for label, value in [
        ("Scenario", scenario),
        ("First message", first_message),
        ("Example dialogue", examples),
        ("Creator notes", creator_notes),
    ]:
        if value:
            rules.append(f"{label}: {value}")

    return localize_known_character(
        {
            "name": name,
            "role": description,
            "personality": personality,
            "speechStyle": "",
            "scenario": scenario,
            "firstMessage": first_message,
            "exampleDialogue": examples,
            "creatorNotes": creator_notes,
            "tags": [str(tag).strip() for tag in tags if str(tag).strip()] if isinstance(tags, list) else [],
            "cardType": card_type,
            "rules": rules,
        },
        fallback_name,
    )


def normalize_card_type(value: Any) -> str:
    card_type = str(value or "").strip().lower()
    if card_type in {"player", "protagonist", "pc", "user"}:
        return "player"
    if card_type in {"npc", "character", "assistant", "ai"}:
        return "npc"
    return "npc"


def infer_card_type(*values: str) -> str:
    text = "\n".join(str(value or "") for value in values)
    player_markers = [
        "用户扮演",
        "用户就是",
        "用户可以代入",
        "用户可以扮演",
        "AI 不扮演",
        "AI只负责",
        "AI 只负责",
        "user plays",
        "player character",
    ]
    return "player" if any(marker.lower() in text.lower() for marker in player_markers) else "npc"


def localize_known_character(card: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    if card["name"].lower() != "seraphina" and fallback_name.lower() != "default_seraphina":
        return card

    return {
        "name": "瑟拉菲娜",
        "role": "艾尔多利亚森林圣地的守护者，擅长治疗、庇护与自然魔法。",
        "personality": "温柔、怜悯、警觉且富有保护欲。她会照看受伤的旅人，也会在黑暗逼近时坚定守住圣地边界。",
        "speechStyle": "语气柔和、关切，常用安抚性的短句；面对暗影獠牙时会变得谨慎而坚定。",
        "rules": [
            "你是瑟拉菲娜，艾尔多利亚森林圣地的守护者。",
            "用户在森林中遭到怪物袭击后醒来，你已用魔法治疗了用户的伤势。",
            "圣地被古老魔法保护，暗影獠牙无法轻易进入。",
            "艾尔多利亚曾是旅人与商人的安全乐土，如今大部分地区被暗影獠牙污染。",
            "不要替用户做决定，只描述你的行动、感受、提醒和回应。",
        ],
    }


def localize_known_world(world: dict[str, Any]) -> dict[str, Any]:
    if world["title"].lower() != "eldoria":
        return world

    return {
        "title": "艾尔多利亚",
        "premise": "艾尔多利亚曾是充满奇迹的森林国度，如今被暗影獠牙的诅咒侵蚀。用户在森林深处受袭后，被守护者瑟拉菲娜救回一处受古老魔法庇护的林间圣地。",
        "tone": "奇幻、治愈、危机潜伏、黑暗森林冒险",
        "facts": [
            "艾尔多利亚曾拥有辽阔草甸、清澈湖泊和高耸山脉，是旅人与商人的安全乐土。",
            "暗影獠牙是被黑暗腐化的怪物，会以痛苦为食，并把无辜生物扭曲成冷酷的野兽。",
            "瑟拉菲娜守护的林间圣地被古老魔法庇护，恶意之物和暗影野兽难以进入。",
            "瑟拉菲娜拥有治疗、守护和自然魔法，能够安抚伤者、修复创伤并守夜驱散危险。",
            "艾尔多利亚仍有少数光明尚存的避难地，但森林深处已经遍布诅咒、怪物和失落的道路。",
        ],
    }


def read_world_book_json(path: Path) -> dict[str, Any] | None:
    data = read_json_file(path)
    if not data:
        return None

    entries = data.get("entries")
    if isinstance(entries, dict):
        entry_values = list(entries.values())
    elif isinstance(entries, list):
        entry_values = entries
    elif isinstance(data.get("world_info"), list):
        entry_values = data["world_info"]
    else:
        return None

    facts = []
    normalized_entries = []
    tones = []
    for index, entry in enumerate(entry_values):
        if not isinstance(entry, dict) or entry.get("disable"):
            continue
        content = str(entry.get("content") or "").strip()
        if content:
            facts.append(content)
            normalized_entries.append(
                {
                    "keys": normalize_entry_keys(entry.get("key")),
                    "content": content,
                    "order": int(entry.get("order") or (100 - index)),
                    "constant": bool(entry.get("constant")),
                    "enabled": not bool(entry.get("disable")),
                }
            )
        keys = entry.get("key")
        if isinstance(keys, list) and keys:
            tones.append(", ".join(str(item) for item in keys[:5]))

    if not facts:
        return None

    title = str(data.get("title") or data.get("name") or path.stem).strip()
    return localize_known_world({
        "title": title,
        "premise": facts[0][:1200],
        "tone": " | ".join(tones[:3]) or "Imported lorebook",
        "facts": facts,
        "entries": normalized_entries,
        "uiSchema": data.get("uiSchema") if isinstance(data.get("uiSchema"), dict) else {},
        "initialState": data.get("initialState") if isinstance(data.get("initialState"), dict) else {},
        "openingScene": str(data.get("openingScene") or "").strip(),
        "openingOptions": normalize_opening_options(data.get("openingOptions")),
    })


def upsert_character(conn: sqlite3.Connection, path: Path, card: dict[str, Any]) -> None:
    timestamp = now_ms()
    card_id = stable_file_id("character", path)
    conn.execute(
        """
        INSERT INTO character_cards (
            id, name, role, personality, speech_style, scenario, first_message,
            example_dialogue, creator_notes, tags_json, card_type, rules_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            role = excluded.role,
            personality = excluded.personality,
            speech_style = excluded.speech_style,
            scenario = excluded.scenario,
            first_message = excluded.first_message,
            example_dialogue = excluded.example_dialogue,
            creator_notes = excluded.creator_notes,
            tags_json = excluded.tags_json,
            card_type = excluded.card_type,
            rules_json = excluded.rules_json,
            updated_at = excluded.updated_at
        """,
        (
            card_id,
            card["name"],
            card["role"],
            card["personality"],
            card["speechStyle"],
            card.get("scenario", ""),
            card.get("firstMessage", ""),
            card.get("exampleDialogue", ""),
            card.get("creatorNotes", ""),
            json.dumps(card.get("tags", []), ensure_ascii=False),
            normalize_card_type(card.get("cardType")),
            json.dumps(card["rules"], ensure_ascii=False),
            timestamp,
            timestamp,
        ),
    )


def upsert_world(conn: sqlite3.Connection, path: Path, world: dict[str, Any]) -> None:
    timestamp = now_ms()
    world_id = stable_file_id("world", path)
    conn.execute(
        """
        INSERT INTO world_books (
            id, title, premise, tone, facts_json, ui_schema_json,
            initial_state_json, opening_scene, opening_options_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            premise = excluded.premise,
            tone = excluded.tone,
            facts_json = excluded.facts_json,
            ui_schema_json = excluded.ui_schema_json,
            initial_state_json = excluded.initial_state_json,
            opening_scene = excluded.opening_scene,
            opening_options_json = excluded.opening_options_json,
            updated_at = excluded.updated_at
        """,
        (
            world_id,
            world["title"],
            world["premise"],
            world["tone"],
            json.dumps(world["facts"], ensure_ascii=False),
            json.dumps(world.get("uiSchema", {}), ensure_ascii=False),
            json.dumps(world.get("initialState", {}), ensure_ascii=False),
            str(world.get("openingScene") or ""),
            json.dumps(normalize_opening_options(world.get("openingOptions")), ensure_ascii=False),
            timestamp,
            timestamp,
        ),
    )
    upsert_world_entries(conn, world_id, world)


def upsert_world_entries(conn: sqlite3.Connection, world_id: str, world: dict[str, Any]) -> None:
    timestamp = now_ms()
    entries = world.get("entries") if isinstance(world.get("entries"), list) else []
    if not entries:
        entries = entries_from_facts(world)

    conn.execute("DELETE FROM world_entries WHERE world_book_id = ?", (world_id,))
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        entry_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"ai-roleplay-engine:world-entry:{world_id}:{index}:{content[:80]}",
            )
        )
        conn.execute(
            """
            INSERT INTO world_entries (
                id, world_book_id, keys_json, content, position, enabled, constant, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                world_id,
                json.dumps(normalize_entry_keys(entry.get("keys")), ensure_ascii=False),
                content,
                int(entry.get("order") or (100 - index)),
                1 if entry.get("enabled", True) else 0,
                1 if entry.get("constant") else 0,
                timestamp,
                timestamp,
            ),
        )


def entries_from_facts(world: dict[str, Any]) -> list[dict[str, Any]]:
    facts = world.get("facts") if isinstance(world.get("facts"), list) else []
    title = str(world.get("title") or "")
    inferred_keys = infer_world_keys(title, facts)
    return [
        {
            "keys": inferred_keys[index] if index < len(inferred_keys) else [],
            "content": str(fact),
            "order": 100 - index,
            "constant": index == 0,
            "enabled": True,
        }
        for index, fact in enumerate(facts)
        if str(fact).strip()
    ]


def infer_world_keys(title: str, facts: list[Any]) -> list[list[str]]:
    if "Eldoria" in title or "艾尔多利亚" in title:
        return [
            ["Eldoria", "艾尔多利亚", "forest", "森林", "glade", "圣地"],
            ["Shadowfang", "暗影獠牙", "beast", "monster", "怪物"],
            ["Seraphina", "瑟拉菲娜", "healing", "magic", "治疗", "魔法"],
            ["glade", "safe haven", "refuge", "圣地", "避难地"],
        ]
    return [[] for _ in facts]
