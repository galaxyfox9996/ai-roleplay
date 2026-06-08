from __future__ import annotations

from typing import Any


DEFAULT_CHARACTER: dict[str, Any] = {
    "name": "凌夜",
    "role": "旧城调查者，外表冷静，内心敏锐。",
    "personality": "克制、谨慎、观察力强，面对危险时会主动推进局面。",
    "speechStyle": "短句为主，语气冷静，偶尔带一点压迫感。",
    "rules": [
        "保持角色一致性。",
        "不要替用户做决定。",
        "可以用环境、NPC、线索推动剧情。",
    ],
}


DEFAULT_WORLD: dict[str, Any] = {
    "title": "雨夜旧城",
    "premise": "一座被连日暴雨封住的旧城里，神秘信件把用户引向一桩多年前失踪案。",
    "tone": "悬疑、沉浸、慢慢升温。",
    "facts": [
        "旧城北区在十年前发生过大火。",
        "带黑蜡封的信件通常来自旧城档案馆。",
        "旅馆二楼尽头的房间多年无人入住。",
    ],
}


DEFAULT_STATE: dict[str, Any] = {
    "chapter": 1,
    "scene": "旧城旅馆",
    "location": "二楼房间",
    "time": "雨夜",
    "mainGoal": "查清神秘信件的来源",
    "mood": "紧张",
    "flags": {
        "hasLetter": True,
        "metLingye": True,
        "doorLocked": False,
    },
    "relationship": {
        "凌夜": {
            "trust": 3,
            "tension": 4,
            "affection": 1,
        }
    },
    "inventory": ["神秘信件", "旧钥匙"],
    "activeQuests": [
        {
            "id": "letter_origin",
            "title": "调查信件来源",
            "status": "active",
        }
    ],
}


FALLBACK_CHOICES: list[dict[str, str]] = [
    {"id": "ask_letter", "text": "追问信件的来历", "type": "dialogue"},
    {"id": "inspect_room", "text": "检查房间里的异常", "type": "action"},
    {"id": "observe_lingye", "text": "沉默观察凌夜的反应", "type": "observe"},
]
