# SillyTavern 功能差距执行方案

## 执行状态

更新时间：2026-06-08

- [x] 文档拆分完成
- [x] 阶段 1：世界书条目化与关键词触发
- [x] 阶段 2：Prompt 预算与上下文裁剪配置
- [x] 阶段 3：消息编辑、删除、重生成增强
- [x] 阶段 4：角色卡字段兼容增强
- [x] 阶段 5：长期摘要记忆

## 当前定位

当前项目是一个轻量 AI 互动叙事引擎，重点是本地可运行、剧情推进、状态保存和简化编辑器。

SillyTavern 是完整角色聊天平台，核心优势包括角色卡兼容、世界书触发、Prompt 预设、上下文/token 管理、消息分支、扩展生态和多模型配置。

本方案不试图一次性复刻 SillyTavern，而是按“最影响剧情质量和长期可玩性”的顺序补齐功能。

## 阶段 1：世界书条目化与关键词触发

状态：已完成

完成记录：

- 新增 `world_entries` 表。
- SillyTavern 世界书导入时会同步条目。
- `/api/editor` 和 `/api/session` 返回的 world 会包含 `entries`。
- Prompt 构造会生成 `selectedWorldEntries`。
- 已验证输入“暗影獠牙”能命中相关世界书条目。

目标：

- 将世界书从 `facts[]` 升级为 `entries[]`。
- 支持每条世界书条目的关键词、启用状态、优先级、常驻状态。
- 每轮 Prompt 只注入命中的世界书条目，而不是无差别塞入全部 facts。

任务：

- 新增 SQLite 表 `world_entries`。
- 导入 SillyTavern `entries` 时保留 `key`、`content`、`order`、`constant`、`disable`。
- `/api/editor` 返回世界书时带上 `entries`。
- 保存世界书时，如果没有显式 entries，则由 facts 生成 entries。
- `prompting.py` 根据用户输入、最近对话和当前状态选择相关条目。

验收：

- `worldbooks/Eldoria.json` 导入后能生成多条 `world_entries`。
- Prompt 中出现 `selectedWorldEntries`。
- 输入命中关键词时，相关世界书条目进入 Prompt。
- 没命中关键词时，常驻条目或前几条基础条目可作为兜底。

## 阶段 2：Prompt 预算与上下文裁剪配置

状态：已完成

完成记录：

- 新增 `.env` 配置：`PROMPT_RECENT_MESSAGE_LIMIT`、`PROMPT_WORLD_ENTRY_LIMIT`、`PROMPT_MAX_CHARS`。
- `build_prompt()` 支持按配置裁剪最近消息、世界书条目和总字符数。
- `/health` 返回当前 prompt 配置。
- 已验证 `PROMPT_MAX_CHARS=1200` 时 Prompt 会被截断。

目标：

- 不再固定最近 8 条消息。
- 改为按粗略 token/字符预算裁剪角色卡、世界书条目、历史消息。

任务：

- 增加 `.env` 配置：`PROMPT_RECENT_MESSAGE_LIMIT`、`PROMPT_WORLD_ENTRY_LIMIT`、`PROMPT_MAX_CHARS`。
- Prompt 构造时按预算截断长文本。
- 在 `/health` 或设置面板展示当前 prompt 配置。

验收：

- 长存档不会导致 prompt 无限增长。
- 用户可以通过 `.env` 调整最近消息数量和世界书条目数量。

## 阶段 3：消息编辑、删除、重生成增强

状态：已完成

完成记录：

- 新增 `/api/message/delete-last-turn`。
- 新增 `/api/message/edit-last-user`。
- 前端行动区新增“编辑上一轮”“撤销上一轮”。
- 已验证编辑上一条用户输入后可重新生成，撤销上一轮后消息清空。

目标：

- 接近 SillyTavern 的基础消息操作能力。

任务：

- 支持删除最后一轮。
- 支持编辑上一条用户输入后重新生成。
- 支持删除任意消息后的状态重建策略。
- 前端给消息卡片增加操作菜单。

验收：

- 用户能修改上一条输入并重新生成 AI 回复。
- 删除消息后界面和数据库一致。
- 重生成不会重复堆叠失败回复。

## 阶段 4：角色卡字段兼容增强

状态：已完成

完成记录：

- `character_cards` 增加 scenario、first_message、example_dialogue、creator_notes、tags_json。
- PNG/JSON 角色卡导入时保留 SillyTavern 常用字段。
- `/api/editor` 返回角色卡时包含新增字段。

目标：

- 更完整地兼容 SillyTavern 角色卡。

任务：

- 增加字段：description、scenario、first_mes、mes_example、creator_notes、tags、avatar_path。
- PNG/JSON 导入时保留原始字段。
- Prompt 中分层注入角色卡字段。
- 编辑器提供高级字段折叠区。

验收：

- 默认 Seraphina 角色卡可保留 first message、scenario、example dialogue。
- Prompt 中能区分角色描述、场景、示例对话。

## 阶段 5：长期摘要记忆

状态：已完成

完成记录：

- 复用 `sessions.summary_text` 作为会话级长期摘要字段，并保留旧存档 fallback。
- 新增 `SUMMARY_UPDATE_INTERVAL`、`SUMMARY_MAX_CHARS` 配置，`/health` 会返回当前摘要配置。
- AI 回复保存时会写入模型返回的 `memoryNotes`，并每隔配置轮数追加本地压缩摘要。
- Prompt 输入资料新增 `longTermSummary`，用于跨越最近消息窗口保持连续性。
- 新增 `/api/session/summary`，支持手动保存当前会话摘要。
- 前端新增“记忆”抽屉，可查看和编辑长期摘要。
- 重试、撤销、编辑上一轮时会恢复 `_previousSummary`，避免被删除回复污染长期记忆。

目标：

- 解决当前“数据库保存全部，但模型只看最近几轮”的长期连续性问题。

任务：

- 新增 session summary 字段或表。
- 每 N 轮自动生成/更新剧情摘要。
- Prompt 中注入摘要。
- 支持手动查看和编辑摘要。

验收：

- 运行 30 轮后，模型仍能知道早期关键事件。
- 摘要不会无限增长。
- 已验证 Prompt 中出现 `longTermSummary`，摘要会按 `SUMMARY_MAX_CHARS` 裁剪。
- 已验证长期记忆 UI、`/api/session/summary` 和 `/health` 摘要配置可用。

## 执行规则

- 每完成一个阶段，更新本文件执行状态。
- 每阶段都要运行基础验证。
- 优先保持现有 API 兼容。
- 任何会破坏旧存档的数据迁移都要保留 fallback 读取逻辑。
