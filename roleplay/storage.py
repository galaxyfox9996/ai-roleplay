from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any

from .config import DB_PATH, DATA_DIR, AppConfig
from .defaults import DEFAULT_CHARACTER, DEFAULT_STATE, DEFAULT_WORLD
from .library_import import import_library_files
from .providers import get_model_metadata
from .story_response import apply_state_patch_with_schema
from .utils import deep_merge, now_ms

CHARACTER_ONLY_WORLD_ID = "__character_only__"


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                state_json TEXT NOT NULL,
                summary_text TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        ensure_session_columns(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS character_cards (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                personality TEXT NOT NULL,
                speech_style TEXT NOT NULL,
                scenario TEXT NOT NULL DEFAULT '',
                first_message TEXT NOT NULL DEFAULT '',
                example_dialogue TEXT NOT NULL DEFAULT '',
                creator_notes TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                card_type TEXT NOT NULL DEFAULT 'npc',
                rules_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        ensure_character_columns(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS world_books (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                premise TEXT NOT NULL,
                tone TEXT NOT NULL,
                facts_json TEXT NOT NULL,
                ui_schema_json TEXT NOT NULL DEFAULT '{}',
                initial_state_json TEXT NOT NULL DEFAULT '{}',
                opening_scene TEXT NOT NULL DEFAULT '',
                opening_options_json TEXT NOT NULL DEFAULT '[]',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        ensure_world_columns(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS world_entries (
                id TEXT PRIMARY KEY,
                world_book_id TEXT NOT NULL,
                keys_json TEXT NOT NULL,
                content TEXT NOT NULL,
                position INTEGER NOT NULL,
                enabled INTEGER NOT NULL,
                constant INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (world_book_id) REFERENCES world_books(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        ensure_editor_defaults(conn)
        import_library_files(conn)
        ensure_session_bindings(conn)
        conn.commit()


def ensure_session_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "character_card_id" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN character_card_id TEXT")
    if "world_book_id" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN world_book_id TEXT")
    if "summary_text" not in columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN summary_text TEXT NOT NULL DEFAULT ''")


def ensure_character_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(character_cards)").fetchall()}
    for column_name, definition in {
        "scenario": "TEXT NOT NULL DEFAULT ''",
        "first_message": "TEXT NOT NULL DEFAULT ''",
        "example_dialogue": "TEXT NOT NULL DEFAULT ''",
        "creator_notes": "TEXT NOT NULL DEFAULT ''",
        "tags_json": "TEXT NOT NULL DEFAULT '[]'",
        "card_type": "TEXT NOT NULL DEFAULT 'npc'",
    }.items():
        if column_name not in columns:
            conn.execute(f"ALTER TABLE character_cards ADD COLUMN {column_name} {definition}")


def ensure_world_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(world_books)").fetchall()}
    if "ui_schema_json" not in columns:
        conn.execute("ALTER TABLE world_books ADD COLUMN ui_schema_json TEXT NOT NULL DEFAULT '{}'")
    if "initial_state_json" not in columns:
        conn.execute("ALTER TABLE world_books ADD COLUMN initial_state_json TEXT NOT NULL DEFAULT '{}'")
    if "opening_scene" not in columns:
        conn.execute("ALTER TABLE world_books ADD COLUMN opening_scene TEXT NOT NULL DEFAULT ''")
    if "opening_options_json" not in columns:
        conn.execute("ALTER TABLE world_books ADD COLUMN opening_options_json TEXT NOT NULL DEFAULT '[]'")


def ensure_session_bindings(conn: sqlite3.Connection) -> None:
    character_id = get_setting(conn, "active_character_id")
    world_id = get_setting(conn, "active_world_id")
    if character_id:
        conn.execute(
            "UPDATE sessions SET character_card_id = ? WHERE character_card_id IS NULL OR character_card_id = ''",
            (character_id,),
        )
    if world_id:
        conn.execute(
            "UPDATE sessions SET world_book_id = ? WHERE world_book_id IS NULL OR world_book_id = ''",
            (world_id,),
        )


def ensure_editor_defaults(conn: sqlite3.Connection) -> None:
    timestamp = now_ms()
    character_count = conn.execute("SELECT COUNT(*) AS count FROM character_cards").fetchone()["count"]
    if character_count == 0:
        character_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO character_cards (
                id, name, role, personality, speech_style, rules_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                character_id,
                DEFAULT_CHARACTER["name"],
                DEFAULT_CHARACTER["role"],
                DEFAULT_CHARACTER["personality"],
                DEFAULT_CHARACTER["speechStyle"],
                json.dumps(DEFAULT_CHARACTER["rules"], ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        set_setting(conn, "active_character_id", character_id)

    world_count = conn.execute("SELECT COUNT(*) AS count FROM world_books").fetchone()["count"]
    if world_count == 0:
        world_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO world_books (
                id, title, premise, tone, facts_json, ui_schema_json,
                initial_state_json, opening_scene, opening_options_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                world_id,
                DEFAULT_WORLD["title"],
                DEFAULT_WORLD["premise"],
                DEFAULT_WORLD["tone"],
                json.dumps(DEFAULT_WORLD["facts"], ensure_ascii=False),
                json.dumps(DEFAULT_WORLD.get("uiSchema", {}), ensure_ascii=False),
                json.dumps(DEFAULT_WORLD.get("initialState", {}), ensure_ascii=False),
                str(DEFAULT_WORLD.get("openingScene") or ""),
                json.dumps(DEFAULT_WORLD.get("openingOptions", []), ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        set_setting(conn, "active_world_id", world_id)

    if not get_setting(conn, "active_character_id"):
        row = conn.execute("SELECT id FROM character_cards ORDER BY updated_at DESC LIMIT 1").fetchone()
        if row:
            set_setting(conn, "active_character_id", row["id"])

    if not get_setting(conn, "active_world_id"):
        row = conn.execute("SELECT id FROM world_books ORDER BY updated_at DESC LIMIT 1").fetchone()
        if row:
            set_setting(conn, "active_world_id", row["id"])


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO app_settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def split_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def normalize_character_card(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(data.get("name") or DEFAULT_CHARACTER["name"]).strip(),
        "role": str(data.get("role") or "").strip(),
        "personality": str(data.get("personality") or "").strip(),
        "speechStyle": str(data.get("speechStyle") or data.get("speech_style") or "").strip(),
        "scenario": str(data.get("scenario") or "").strip(),
        "firstMessage": str(data.get("firstMessage") or data.get("first_message") or "").strip(),
        "exampleDialogue": str(data.get("exampleDialogue") or data.get("example_dialogue") or "").strip(),
        "creatorNotes": str(data.get("creatorNotes") or data.get("creator_notes") or "").strip(),
        "tags": split_lines(data.get("tags")),
        "cardType": normalize_card_type(data.get("cardType") or data.get("card_type")),
        "rules": split_lines(data.get("rules")),
    }


def normalize_card_type(value: Any) -> str:
    card_type = str(value or "").strip().lower()
    if card_type in {"player", "protagonist", "pc", "user"}:
        return "player"
    if card_type in {"npc", "character", "assistant", "ai"}:
        return "npc"
    return "npc"


def normalize_world_book(data: dict[str, Any]) -> dict[str, Any]:
    facts = split_lines(data.get("facts"))
    return {
        "title": str(data.get("title") or DEFAULT_WORLD["title"]).strip(),
        "premise": str(data.get("premise") or "").strip(),
        "tone": str(data.get("tone") or "").strip(),
        "facts": facts,
        "entries": normalize_world_entries(data.get("entries"), facts),
        "uiSchema": data.get("uiSchema") if isinstance(data.get("uiSchema"), dict) else {},
        "initialState": data.get("initialState") if isinstance(data.get("initialState"), dict) else {},
        "openingScene": str(data.get("openingScene") or "").strip(),
        "openingOptions": normalize_opening_options(data.get("openingOptions")),
    }


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


def normalize_world_entries(value: Any, fallback_facts: list[str]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        entries = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            entries.append(
                {
                    "keys": split_lines(item.get("keys")),
                    "content": content,
                    "position": int(item.get("position") or item.get("order") or (100 - index)),
                    "enabled": bool(item.get("enabled", True)),
                    "constant": bool(item.get("constant")),
                }
            )
        if entries:
            return entries

    return [
        {
            "keys": [],
            "content": fact,
            "position": 100 - index,
            "enabled": True,
            "constant": index == 0,
        }
        for index, fact in enumerate(fallback_facts)
    ]


def row_to_character_card(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "role": row["role"],
        "personality": row["personality"],
        "speechStyle": row["speech_style"],
        "scenario": row["scenario"],
        "firstMessage": row["first_message"],
        "exampleDialogue": row["example_dialogue"],
        "creatorNotes": row["creator_notes"],
        "tags": json.loads(row["tags_json"]),
        "cardType": row["card_type"] if "card_type" in row.keys() else "npc",
        "rules": json.loads(row["rules_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def row_to_world_book(row: sqlite3.Row) -> dict[str, Any]:
    entries = []
    if "entries_json" in row.keys() and row["entries_json"]:
        entries = json.loads(row["entries_json"])
    return {
        "id": row["id"],
        "title": row["title"],
        "premise": row["premise"],
        "tone": row["tone"],
        "facts": json.loads(row["facts_json"]),
        "uiSchema": json.loads(row["ui_schema_json"]) if "ui_schema_json" in row.keys() else {},
        "initialState": json.loads(row["initial_state_json"]) if "initial_state_json" in row.keys() else {},
        "openingScene": row["opening_scene"] if "opening_scene" in row.keys() else "",
        "openingOptions": (
            json.loads(row["opening_options_json"]) if "opening_options_json" in row.keys() else []
        ),
        "entries": entries,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def character_only_world(character: dict[str, Any] | None = None) -> dict[str, Any]:
    character_name = str((character or {}).get("name") or DEFAULT_CHARACTER["name"]).strip()
    return {
        "id": CHARACTER_ONLY_WORLD_ID,
        "title": "仅角色卡模式",
        "premise": f"本局只加载角色卡「{character_name}」，不加载任何世界书条目、世界书开场或世界书状态 schema。",
        "tone": "由角色卡决定",
        "facts": [],
        "uiSchema": {},
        "initialState": {},
        "openingScene": "",
        "openingOptions": [],
        "entries": [],
        "createdAt": 0,
        "updatedAt": 0,
    }


def get_world_entries_in_conn(conn: sqlite3.Connection, world_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM world_entries
        WHERE world_book_id = ?
        ORDER BY constant DESC, position DESC, updated_at DESC
        """,
        (world_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "keys": json.loads(row["keys_json"]),
            "content": row["content"],
            "position": row["position"],
            "enabled": bool(row["enabled"]),
            "constant": bool(row["constant"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def get_character_card_by_id(conn: sqlite3.Connection, character_id: str | None) -> dict[str, Any] | None:
    if not character_id:
        return None
    row = conn.execute("SELECT * FROM character_cards WHERE id = ?", (character_id,)).fetchone()
    return row_to_character_card(row) if row else None


def get_world_book_by_id(conn: sqlite3.Connection, world_id: str | None) -> dict[str, Any] | None:
    if not world_id:
        return None
    row = conn.execute("SELECT * FROM world_books WHERE id = ?", (world_id,)).fetchone()
    if not row:
        return None
    world = row_to_world_book(row)
    world["entries"] = get_world_entries_in_conn(conn, world["id"])
    return world


def get_active_character_card_in_conn(conn: sqlite3.Connection) -> dict[str, Any]:
    active_id = get_setting(conn, "active_character_id")
    card = get_character_card_by_id(conn, active_id)
    if card:
        return card
    row = conn.execute("SELECT * FROM character_cards ORDER BY updated_at DESC LIMIT 1").fetchone()
    return row_to_character_card(row)


def get_active_world_book_in_conn(conn: sqlite3.Connection) -> dict[str, Any]:
    active_id = get_setting(conn, "active_world_id")
    world = get_world_book_by_id(conn, active_id)
    if world:
        return world
    row = conn.execute("SELECT * FROM world_books ORDER BY updated_at DESC LIMIT 1").fetchone()
    world = row_to_world_book(row)
    world["entries"] = get_world_entries_in_conn(conn, world["id"])
    return world


def get_active_character_card() -> dict[str, Any]:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return get_active_character_card_in_conn(conn)


def get_active_world_book() -> dict[str, Any]:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return get_active_world_book_in_conn(conn)


def get_editor_payload() -> dict[str, Any]:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        active_character_id = get_setting(conn, "active_character_id")
        active_world_id = get_setting(conn, "active_world_id")
        characters = [
            row_to_character_card(row)
            for row in conn.execute("SELECT * FROM character_cards ORDER BY updated_at DESC").fetchall()
        ]
        worlds = []
        for row in conn.execute("SELECT * FROM world_books ORDER BY updated_at DESC").fetchall():
            world = row_to_world_book(row)
            world["entries"] = get_world_entries_in_conn(conn, world["id"])
            worlds.append(world)

    return {
        "activeCharacterId": active_character_id,
        "activeWorldId": active_world_id,
        "characters": characters,
        "worlds": worlds,
    }


def save_active_character_card(data: dict[str, Any]) -> dict[str, Any]:
    init_db()
    timestamp = now_ms()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        card_id = str(data.get("id") or get_setting(conn, "active_character_id") or uuid.uuid4())
        existing_row = conn.execute("SELECT * FROM character_cards WHERE id = ?", (card_id,)).fetchone()
        merged_data = dict(data)
        if existing_row:
            existing_card = row_to_character_card(existing_row)
            preserve_keys = [
                "name",
                "role",
                "personality",
                "speechStyle",
                "scenario",
                "firstMessage",
                "exampleDialogue",
                "creatorNotes",
                "tags",
                "cardType",
                "rules",
            ]
            for key in preserve_keys:
                if key not in merged_data:
                    merged_data[key] = existing_card.get(key)

        card = normalize_character_card(merged_data)
        if existing_row:
            conn.execute(
                """
                UPDATE character_cards
                SET
                    name = ?,
                    role = ?,
                    personality = ?,
                    speech_style = ?,
                    scenario = ?,
                    first_message = ?,
                    example_dialogue = ?,
                    creator_notes = ?,
                    tags_json = ?,
                    card_type = ?,
                    rules_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    card["name"],
                    card["role"],
                    card["personality"],
                    card["speechStyle"],
                    card["scenario"],
                    card["firstMessage"],
                    card["exampleDialogue"],
                    card["creatorNotes"],
                    json.dumps(card["tags"], ensure_ascii=False),
                    card["cardType"],
                    json.dumps(card["rules"], ensure_ascii=False),
                    timestamp,
                    card_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO character_cards (
                    id, name, role, personality, speech_style, scenario, first_message,
                    example_dialogue, creator_notes, tags_json, card_type, rules_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    card["name"],
                    card["role"],
                    card["personality"],
                    card["speechStyle"],
                    card["scenario"],
                    card["firstMessage"],
                    card["exampleDialogue"],
                    card["creatorNotes"],
                    json.dumps(card["tags"], ensure_ascii=False),
                    card["cardType"],
                    json.dumps(card["rules"], ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        set_setting(conn, "active_character_id", card_id)
        conn.commit()
        row = conn.execute("SELECT * FROM character_cards WHERE id = ?", (card_id,)).fetchone()
    return row_to_character_card(row)


def save_active_world_book(data: dict[str, Any]) -> dict[str, Any]:
    init_db()
    timestamp = now_ms()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        world_id = str(data.get("id") or get_setting(conn, "active_world_id") or uuid.uuid4())
        existing_row = conn.execute("SELECT * FROM world_books WHERE id = ?", (world_id,)).fetchone()
        merged_data = dict(data)
        if existing_row:
            existing_world = row_to_world_book(existing_row)
            existing_world["entries"] = get_world_entries_in_conn(conn, existing_world["id"])
            preserve_keys = [
                "title",
                "premise",
                "tone",
                "facts",
                "entries",
                "uiSchema",
                "initialState",
                "openingScene",
                "openingOptions",
            ]
            for key in preserve_keys:
                if key not in merged_data:
                    merged_data[key] = existing_world.get(key)

        world = normalize_world_book(merged_data)
        if existing_row:
            conn.execute(
                """
                UPDATE world_books
                SET title = ?, premise = ?, tone = ?, facts_json = ?,
                    ui_schema_json = ?, initial_state_json = ?, opening_scene = ?,
                    opening_options_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    world["title"],
                    world["premise"],
                    world["tone"],
                    json.dumps(world["facts"], ensure_ascii=False),
                    json.dumps(world["uiSchema"], ensure_ascii=False),
                    json.dumps(world["initialState"], ensure_ascii=False),
                    world["openingScene"],
                    json.dumps(world["openingOptions"], ensure_ascii=False),
                    timestamp,
                    world_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO world_books (
                    id, title, premise, tone, facts_json, ui_schema_json,
                    initial_state_json, opening_scene, opening_options_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    world_id,
                    world["title"],
                    world["premise"],
                    world["tone"],
                    json.dumps(world["facts"], ensure_ascii=False),
                    json.dumps(world["uiSchema"], ensure_ascii=False),
                    json.dumps(world["initialState"], ensure_ascii=False),
                    world["openingScene"],
                    json.dumps(world["openingOptions"], ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        set_setting(conn, "active_world_id", world_id)
        replace_world_entries(conn, world_id, world["entries"])
        conn.commit()
        row = conn.execute("SELECT * FROM world_books WHERE id = ?", (world_id,)).fetchone()
        saved_world = row_to_world_book(row)
        saved_world["entries"] = get_world_entries_in_conn(conn, saved_world["id"])
    return saved_world


def replace_world_entries(conn: sqlite3.Connection, world_id: str, entries: list[dict[str, Any]]) -> None:
    timestamp = now_ms()
    conn.execute("DELETE FROM world_entries WHERE world_book_id = ?", (world_id,))
    for index, entry in enumerate(entries):
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        conn.execute(
            """
            INSERT INTO world_entries (
                id, world_book_id, keys_json, content, position, enabled, constant, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                world_id,
                json.dumps(split_lines(entry.get("keys")), ensure_ascii=False),
                content,
                int(entry.get("position") or (100 - index)),
                1 if entry.get("enabled", True) else 0,
                1 if entry.get("constant") else 0,
                timestamp,
                timestamp,
            ),
        )


def row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": json.loads(row["content_json"]),
        "createdAt": row["created_at"],
    }


def create_session(config: AppConfig) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    timestamp = now_ms()
    world = get_active_world_book()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, title, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                "雨夜旧城",
                json.dumps(DEFAULT_STATE, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (world.get("title") or DEFAULT_WORLD["title"], session_id),
        )
        conn.commit()
    return get_session(config, session_id)


def get_latest_session_id() -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id FROM sessions ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return row["id"] if row else None


def get_session(config: AppConfig, session_id: str | None = None) -> dict[str, Any]:
    init_db()
    session_id = session_id or get_latest_session_id()
    if not session_id:
        return create_session(config)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        session = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not session:
            return create_session(config)

        messages = conn.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()

    return {
        "id": session["id"],
        "title": session["title"],
        "state": json.loads(session["state_json"]),
        "character": get_active_character_card(),
        "world": get_active_world_book(),
        "messages": [row_to_message(row) for row in messages],
        "model": get_model_metadata(config),
        "createdAt": session["created_at"],
        "updatedAt": session["updated_at"],
    }


def save_message(session_id: str, role: str, content: dict[str, Any]) -> dict[str, Any]:
    message = {
        "id": str(uuid.uuid4()),
        "role": role,
        "content": content,
        "createdAt": now_ms(),
    }
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO messages (id, session_id, role, content_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                message["id"],
                session_id,
                role,
                json.dumps(content, ensure_ascii=False),
                message["createdAt"],
            ),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (message["createdAt"], session_id),
        )
        conn.commit()
    return message


def delete_message(session_id: str, message_id: str) -> bool:
    if not session_id or not message_id:
        return False

    timestamp = now_ms()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "DELETE FROM messages WHERE session_id = ? AND id = ?",
            (session_id, message_id),
        )
        if cursor.rowcount == 0:
            return False
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (timestamp, session_id),
        )
        conn.commit()
    return True


def update_session_state(session_id: str, state: dict[str, Any]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE sessions
            SET state_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(state, ensure_ascii=False), now_ms(), session_id),
        )
        conn.commit()


def clamp_summary_text(summary_text: str, max_chars: int = 4000) -> str:
    summary_text = str(summary_text or "").strip()
    if max_chars <= 0 or len(summary_text) <= max_chars:
        return summary_text

    lines = [line.strip() for line in summary_text.splitlines() if line.strip()]
    kept: list[str] = []
    current_length = 0
    for line in reversed(lines):
        next_length = current_length + len(line) + (1 if kept else 0)
        if next_length > max_chars:
            break
        kept.append(line)
        current_length = next_length

    if kept:
        return "\n".join(reversed(kept))
    return summary_text[-max_chars:].lstrip()


def update_session_summary(session_id: str, summary_text: str, max_chars: int = 4000) -> dict[str, Any]:
    summary = clamp_summary_text(summary_text, max_chars)
    timestamp = now_ms()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise ValueError("session not found")
        conn.execute(
            """
            UPDATE sessions
            SET summary_text = ?, updated_at = ?
            WHERE id = ?
            """,
            (summary, timestamp, session_id),
        )
        conn.commit()
    return {
        "sessionId": session_id,
        "summary": summary,
        "updatedAt": timestamp,
    }


def append_session_memory_notes(session_id: str, notes: list[str], max_chars: int = 4000) -> str:
    clean_notes = []
    for note in notes:
        clean_note = str(note).strip()
        if clean_note:
            clean_notes.append(clean_note[2:].strip() if clean_note.startswith("- ") else clean_note)
    if not clean_notes:
        return ""

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT summary_text FROM sessions WHERE id = ?", (session_id,)).fetchone()
        current_summary = row["summary_text"] if row else ""
        existing_lines = [line.strip() for line in current_summary.splitlines() if line.strip()]
        seen = {line[2:].strip() if line.startswith("- ") else line for line in existing_lines}
        next_lines = existing_lines[:]
        for note in clean_notes:
            if note in seen:
                continue
            next_lines.append(f"- {note}")
            seen.add(note)
        next_summary = clamp_summary_text("\n".join(next_lines), max_chars)
        conn.execute(
            """
            UPDATE sessions
            SET summary_text = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_summary, now_ms(), session_id),
        )
        conn.commit()
    return next_summary


def contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def initial_goal_for_world(title: str, premise: str) -> str:
    if premise and contains_cjk(premise):
        goal = premise[:80].strip()
        return f"{goal}..." if len(premise) > 80 else goal
    return f"探索「{title}」的核心线索"


def initial_mood_for_world(tone: str) -> str:
    if tone and contains_cjk(tone):
        return tone
    return "待探索"


def build_initial_state(world: dict[str, Any], character: dict[str, Any]) -> dict[str, Any]:
    title = str(world.get("title") or DEFAULT_WORLD["title"]).strip()
    premise = str(world.get("premise") or "").strip()
    tone = str(world.get("tone") or "").strip()
    character_name = str(character.get("name") or DEFAULT_CHARACTER["name"]).strip()
    facts = world.get("facts") if isinstance(world.get("facts"), list) else []

    goal = initial_goal_for_world(title, premise)

    world_state = {
        "chapter": 1,
        "scene": title,
        "location": title,
        "time": "开场",
        "mainGoal": goal,
        "mood": initial_mood_for_world(tone),
        "flags": {
            "worldInitialized": True,
        },
        "relationship": {
            character_name: {
                "trust": 1,
                "tension": 1,
                "affection": 0,
            }
        },
        "inventory": [],
        "activeQuests": [
            {
                "id": "world_intro",
                "title": goal,
                "status": "active",
            }
        ],
    }

    if facts:
        world_state["flags"]["firstWorldFact"] = str(facts[0])[:160]

    # Let explicitly authored world-book state override the automatic defaults.
    initial_state = world.get("initialState")
    if isinstance(initial_state, dict):
        world_state = deep_merge(world_state, initial_state)

    return world_state


def create_session(
    config: AppConfig,
    character_id: str | None = None,
    world_id: str | None = None,
    initial_state_patch: dict[str, Any] | None = None,
    character_only: bool = False,
) -> dict[str, Any]:
    init_db()
    session_id = str(uuid.uuid4())
    timestamp = now_ms()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        character = get_character_card_by_id(conn, character_id) or get_active_character_card_in_conn(conn)
        world = character_only_world(character) if character_only else (
            get_world_book_by_id(conn, world_id) or get_active_world_book_in_conn(conn)
        )
        initial_state = build_initial_state(world, character)
        if isinstance(initial_state_patch, dict) and initial_state_patch:
            initial_state = apply_state_patch_with_schema(
                initial_state,
                initial_state_patch,
                world.get("uiSchema"),
            )
        conn.execute(
            """
            INSERT INTO sessions (
                id, title, state_json, created_at, updated_at, character_card_id, world_book_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                world["title"],
                json.dumps(initial_state, ensure_ascii=False),
                timestamp,
                timestamp,
                character["id"],
                CHARACTER_ONLY_WORLD_ID if character_only else world["id"],
            ),
        )
        set_setting(conn, "active_character_id", character["id"])
        if not character_only:
            set_setting(conn, "active_world_id", world["id"])
        conn.commit()
    return get_session(config, session_id)


def list_sessions() -> list[dict[str, Any]]:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                s.id,
                s.title,
                s.created_at,
                s.updated_at,
                s.character_card_id,
                s.world_book_id,
                c.name AS character_name,
                w.title AS world_title,
                COUNT(m.id) AS message_count
            FROM sessions s
            LEFT JOIN character_cards c ON c.id = s.character_card_id
            LEFT JOIN world_books w ON w.id = s.world_book_id
            LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            """
        ).fetchall()

    return [
        {
            "id": row["id"],
            "title": row["title"],
            "characterId": row["character_card_id"],
            "characterName": row["character_name"] or "",
            "worldId": row["world_book_id"],
            "worldTitle": row["world_title"] or row["title"],
            "messageCount": row["message_count"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def delete_session(session_id: str) -> bool:
    init_db()
    if not session_id:
        return False

    with sqlite3.connect(DB_PATH) as conn:
        existing = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not existing:
            return False

        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    return True


def get_session(config: AppConfig, session_id: str | None = None) -> dict[str, Any]:
    init_db()
    session_id = session_id or get_latest_session_id()
    if not session_id:
        return create_session(config)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        session = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not session:
            return create_session(config)

        messages = conn.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()

        character = (
            get_character_card_by_id(conn, session["character_card_id"])
            or get_active_character_card_in_conn(conn)
        )
        if session["world_book_id"] == CHARACTER_ONLY_WORLD_ID:
            world = character_only_world(character)
        else:
            world = get_world_book_by_id(conn, session["world_book_id"]) or get_active_world_book_in_conn(conn)

    return {
        "id": session["id"],
        "title": session["title"],
        "state": json.loads(session["state_json"]),
        "summary": session["summary_text"],
        "character": character,
        "world": world,
        "messages": [row_to_message(row) for row in messages],
        "model": get_model_metadata(config),
        "createdAt": session["created_at"],
        "updatedAt": session["updated_at"],
    }
