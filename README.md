# AI Roleplay Engine

一个本地运行的 AI 剧情角色扮演引擎。它把“角色卡 + 世界书 + 会话记忆 + 状态面板”组合起来，让 AI 扮演旁白、NPC 或指定角色，推动多轮互动剧情。

项目目标是做一个轻量、可改、方便研究角色扮演工作流的本地 Web 应用。

## 功能特性

- 本地 Web 界面，默认运行在 `http://127.0.0.1:7860`
- 支持角色卡和世界书导入
- 支持新建游戏、存档列表、删除会话、重试上一轮、编辑上一轮
- 支持 SQLite 保存会话、消息、状态和长期摘要
- 支持动态状态 UI，世界书可以自定义状态栏字段
- 支持世界书关键词匹配，只把相关条目注入提示词
- 支持多模型后端：Ollama、OpenAI、DeepSeek、OpenAI-compatible API
- 模型不可用时可使用本地 fallback，方便测试流程

## 快速开始

```powershell
cd E:\code\ai-roleplay-engine
.\start.ps1
```

`start.ps1` 会自动：

- 创建 `.venv`
- 安装 `requirements.txt`
- 启动 `server.py`
- 等待服务就绪
- 打开浏览器

也可以手动启动：

```powershell
cd E:\code\ai-roleplay-engine
.\.venv\Scripts\python.exe server.py
```

然后打开：

```text
http://127.0.0.1:7860
```

## 配置模型

复制配置模板：

```powershell
Copy-Item .env.example .env
```

默认使用 Ollama：

```env
MODEL_PROVIDER=ollama
OLLAMA_MODEL=llama3.1
OLLAMA_URL=http://localhost:11434/api/generate
```

使用 DeepSeek：

```env
MODEL_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

使用 OpenAI 或兼容接口：

```env
MODEL_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

```env
MODEL_PROVIDER=openai-compatible
MODEL_NAME=provider-model-name
MODEL_BASE_URL=https://your-provider.example/v1
MODEL_API_KEY=your-api-key-if-needed
```

## 提示词与记忆

每轮请求不会把所有历史和所有世界书都发给模型。默认会发送：

- 当前角色卡
- 当前世界书摘要
- 当前状态 `session.state`
- 最近若干轮对话
- 长期摘要
- 本轮命中的世界书条目
- 世界书声明的动态状态 UI schema

相关预算可在 `.env` 中调整：

```env
PROMPT_RECENT_MESSAGE_LIMIT=8
PROMPT_WORLD_ENTRY_LIMIT=6
PROMPT_MAX_CHARS=18000
SUMMARY_UPDATE_INTERVAL=4
SUMMARY_MAX_CHARS=4000
```

## 资源目录

项目支持从以下目录递归导入资源：

```text
characters/   # 角色卡，支持 JSON 和 SillyTavern PNG
worldbooks/   # 世界书，支持 JSON
```

角色卡可以有两种写法：

- NPC 型：AI 扮演该角色，与用户对话
- 主角型：用户扮演该角色，AI 扮演旁白、环境和 NPC

世界书可以提供 `uiSchema`，用来定义左侧动态状态面板，例如职业、序列、灵性、好感度、线索、物品等。

## 项目结构

```text
ai-roleplay-engine/
  server.py                  # HTTP 服务和 API 路由
  start.ps1                  # Windows PowerShell 启动脚本
  requirements.txt           # Python 依赖
  .env.example               # 配置模板
  roleplay/
    config.py                # 环境变量和配置加载
    providers.py             # 模型提供商适配
    prompting.py             # 提示词构建
    story_engine.py          # 剧情生成入口
    story_response.py        # 结构化回复与状态合并
    storage.py               # SQLite 存储与会话管理
    library_import.py        # 角色卡和世界书导入
  static/
    index.html               # 前端页面
    styles.css               # 样式
    app.js                   # 前端状态和 API 调用
  docs/                      # 设计文档和工作流
  data/
    app.db                   # 运行后自动生成，默认不提交
```

## API 概览

常用接口：

- `GET /health`：健康检查
- `GET /api/session`：读取当前会话
- `POST /api/session/reset`：新建会话
- `POST /api/session/start`：用指定角色卡和世界书开始新会话
- `POST /api/session/delete`：删除存档
- `POST /api/session/summary`：更新会话摘要
- `GET /api/sessions`：列出存档
- `POST /api/message`：发送用户行动或台词
- `POST /api/message/retry`：重试上一轮 AI 回复
- `POST /api/message/delete-last-turn`：删除上一轮
- `POST /api/message/edit-last-user`：编辑上一轮用户输入并重新生成
- `GET /api/editor`：读取角色卡和世界书编辑器数据
- `POST /api/editor/character`：保存当前角色卡
- `POST /api/editor/world`：保存当前世界书