const state = {
  session: null,
  editor: null,
  sessions: [],
  selectedWorldId: "",
  selectedCharacterId: "",
  busy: false,
  activeDrawer: null,
};

const els = {
  messages: document.querySelector("#messages"),
  choices: document.querySelector("#choices"),
  form: document.querySelector("#messageForm"),
  input: document.querySelector("#messageInput"),
  sendBtn: document.querySelector("#sendBtn"),
  retryBtn: document.querySelector("#retryBtn"),
  editLastBtn: document.querySelector("#editLastBtn"),
  deleteLastBtn: document.querySelector("#deleteLastBtn"),
  chapter: document.querySelector("#stateChapter"),
  location: document.querySelector("#stateLocation"),
  time: document.querySelector("#stateTime"),
  mood: document.querySelector("#stateMood"),
  goal: document.querySelector("#stateGoal"),
  dynamicStatePanels: document.querySelector("#dynamicStatePanels"),
  inventory: document.querySelector("#inventory"),
  equipment: document.querySelector("#equipment"),
  skills: document.querySelector("#skills"),
  spells: document.querySelector("#spells"),
  abilities: document.querySelector("#abilities"),
  relationships: document.querySelector("#relationships"),
  objectives: document.querySelector("#objectives"),
  rpgClass: document.querySelector("#rpgClass"),
  rpgLocation: document.querySelector("#rpgLocation"),
  rpgBp: document.querySelector("#rpgBp"),
  rpgLevel: document.querySelector("#rpgLevel"),
  rpgExp: document.querySelector("#rpgExp"),
  rpgGold: document.querySelector("#rpgGold"),
  rpgThreat: document.querySelector("#rpgThreat"),
  statusBadge: document.querySelector("#statusBadge"),
  modelStatus: document.querySelector("#modelStatus"),
  drawerModelStatus: document.querySelector("#drawerModelStatus"),
  worldTitle: document.querySelector("#worldTitle"),
  characterSummary: document.querySelector("#characterSummary"),
  busyStatus: document.querySelector("#busyStatus"),
  worldSelect: document.querySelector("#worldSelect"),
  characterSelect: document.querySelector("#characterSelect"),
  startGameBtn: document.querySelector("#startGameBtn"),
  saveList: document.querySelector("#saveList"),
  saveCharacterBtn: document.querySelector("#saveCharacterBtn"),
  saveWorldBtn: document.querySelector("#saveWorldBtn"),
  saveMemoryBtn: document.querySelector("#saveMemoryBtn"),
  sessionSummary: document.querySelector("#sessionSummary"),
  characterName: document.querySelector("#characterName"),
  characterRole: document.querySelector("#characterRole"),
  characterPersonality: document.querySelector("#characterPersonality"),
  characterSpeechStyle: document.querySelector("#characterSpeechStyle"),
  characterRules: document.querySelector("#characterRules"),
  worldBookTitle: document.querySelector("#worldBookTitle"),
  worldPremise: document.querySelector("#worldPremise"),
  worldTone: document.querySelector("#worldTone"),
  worldFacts: document.querySelector("#worldFacts"),
  drawerOverlay: document.querySelector("#drawerOverlay"),
  drawers: {
    newGame: document.querySelector("#newGameDrawer"),
    saves: document.querySelector("#savesDrawer"),
    character: document.querySelector("#characterDrawer"),
    world: document.querySelector("#worldDrawer"),
    memory: document.querySelector("#memoryDrawer"),
    settings: document.querySelector("#settingsDrawer"),
  },
  nav: {
    newGame: document.querySelector("#newGameNavBtn"),
    saves: document.querySelector("#savesNavBtn"),
    character: document.querySelector("#characterNavBtn"),
    world: document.querySelector("#worldNavBtn"),
    memory: document.querySelector("#memoryNavBtn"),
    settings: document.querySelector("#settingsNavBtn"),
  },
};

const choiceTypeLabels = {
  dialogue: "对话",
  action: "行动",
  observe: "观察",
  leave: "离开",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function setBusy(nextBusy) {
  state.busy = nextBusy;
  els.sendBtn.disabled = nextBusy;
  els.input.disabled = nextBusy;
  els.retryBtn.disabled = nextBusy;
  els.editLastBtn.disabled = nextBusy;
  els.deleteLastBtn.disabled = nextBusy;
  els.startGameBtn.disabled = nextBusy;
  els.saveCharacterBtn.disabled = nextBusy;
  els.saveWorldBtn.disabled = nextBusy;
  els.saveMemoryBtn.disabled = nextBusy;
  els.sessionSummary.disabled = nextBusy;
  els.busyStatus.textContent = nextBusy ? "AI 正在推进剧情..." : "";
  document.querySelectorAll("button").forEach((button) => {
    if (!button.hasAttribute("data-close-drawer")) {
      button.disabled = nextBusy;
    }
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function linesFromText(value) {
  return String(value || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function formatTime(value) {
  if (!value) return "";
  return new Date(Number(value)).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function syncSelectionFromSession() {
  state.selectedWorldId = state.session?.world?.id || state.editor?.activeWorldId || "";
  state.selectedCharacterId = state.session?.character?.id || state.editor?.activeCharacterId || "";
}

function selectedCharacter() {
  return state.editor?.characters?.find((item) => item.id === state.selectedCharacterId)
    || state.session?.character
    || state.editor?.characters?.[0]
    || {};
}

function selectedWorld() {
  return state.editor?.worlds?.find((item) => item.id === state.selectedWorldId)
    || state.session?.world
    || state.editor?.worlds?.[0]
    || {};
}

function fillSelect(select, items, valueKey, labelKey, selectedId) {
  select.innerHTML = "";
  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item[valueKey];
    option.textContent = item[labelKey];
    select.appendChild(option);
  });
  if (selectedId) {
    select.value = selectedId;
  }
}

function openDrawer(name) {
  state.activeDrawer = name;
  Object.entries(els.drawers).forEach(([drawerName, drawer]) => {
    const isOpen = drawerName === name;
    drawer.classList.toggle("open", isOpen);
    drawer.setAttribute("aria-hidden", String(!isOpen));
  });
  els.drawerOverlay.hidden = false;
  els.drawerOverlay.classList.add("open");
}

function closeDrawer() {
  state.activeDrawer = null;
  Object.values(els.drawers).forEach((drawer) => {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
  });
  els.drawerOverlay.classList.remove("open");
  els.drawerOverlay.hidden = true;
}

function renderNewGamePanel() {
  const worlds = state.editor?.worlds || [];
  const characters = state.editor?.characters || [];
  fillSelect(els.worldSelect, worlds, "id", "title", state.selectedWorldId);
  fillSelect(els.characterSelect, characters, "id", "name", state.selectedCharacterId);
}

function renderSaveDrawer() {
  els.saveList.innerHTML = "";
  if (!state.sessions.length) {
    els.saveList.innerHTML = `<div class="save-empty">暂无存档。点击“新游戏”开始第一段剧情。</div>`;
    return;
  }

  state.sessions.forEach((save) => {
    const item = document.createElement("div");
    item.className = `save-row${save.id === state.session?.id ? " active" : ""}`;

    const button = document.createElement("button");
    button.className = "save-item";
    button.type = "button";
    button.innerHTML = `
      <span class="save-title">${escapeHtml(save.worldTitle || save.title)}</span>
      <span class="save-meta">${escapeHtml(save.characterName || "未命名角色")} · ${save.messageCount} 条 · ${formatTime(save.updatedAt)}</span>
    `;
    button.addEventListener("click", () => continueSession(save.id));

    const deleteButton = document.createElement("button");
    deleteButton.className = "save-delete";
    deleteButton.type = "button";
    deleteButton.title = "删除存档";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => deleteSession(save.id, save.worldTitle || save.title));

    item.appendChild(button);
    item.appendChild(deleteButton);
    els.saveList.appendChild(item);
  });
}

function firstValue(source, keys, fallback = "-") {
  for (const key of keys) {
    const value = source?.[key];
    if (value !== undefined && value !== null && value !== "") {
      return value;
    }
  }
  return fallback;
}

function listValues(value) {
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (item && typeof item === "object") {
        return item.title || item.name || item.id || JSON.stringify(item);
      }
      return String(item).trim();
    }).filter(Boolean);
  }
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => `${key}${item ? `: ${item}` : ""}`)
      .filter(Boolean);
  }
  const fullwidthComma = String.fromCharCode(0xff0c);
  const ideographicComma = String.fromCharCode(0x3001);
  return String(value || "")
    .split(new RegExp(`\\r?\\n|,|${fullwidthComma}|${ideographicComma}`, "u"))
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderChips(container, values, emptyText = "-") {
  if (!container) return;
  container.innerHTML = "";
  const items = listValues(values);
  if (!items.length) {
    container.innerHTML = `<span class="muted-inline">${escapeHtml(emptyText)}</span>`;
    return;
  }
  items.forEach((item) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = item;
    container.appendChild(chip);
  });
}

function renderState() {
  const storyState = state.session?.state || {};
  els.chapter.textContent = storyState.chapter ?? "-";
  els.location.textContent = storyState.location || storyState.scene || "-";
  els.time.textContent = storyState.time || "-";
  els.mood.textContent = storyState.mood || "-";
  els.goal.textContent = storyState.mainGoal || "选择世界书和角色卡，开始新的剧情。";

  const modelText = state.session
    ? `${state.session.model.provider}: ${state.session.model.name}`
    : "-";
  els.modelStatus.textContent = modelText;
  els.drawerModelStatus.textContent = modelText;

  const world = state.session?.world || selectedWorld();
  const character = state.session?.character || selectedCharacter();
  els.worldTitle.textContent = world?.title || "AI Roleplay Engine";
  els.characterSummary.textContent = character?.name
    ? `当前角色：${character.name}`
    : "选择世界书和角色卡开始剧情";

  els.inventory.innerHTML = "";
  const inventory = Array.isArray(storyState.inventory) ? storyState.inventory : [];
  if (!inventory.length) {
    els.inventory.innerHTML = `<span class="muted-inline">暂无物品</span>`;
    return;
  }
  inventory.forEach((item) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = item;
    els.inventory.appendChild(chip);
  });
}

function renderRpgState() {
  const storyState = state.session?.state || {};
  const characterClass = firstValue(storyState, ["Class", "class", "job"], "-");
  const level = firstValue(storyState, ["Level", "level"], "-");
  const bp = firstValue(storyState, ["Battle Power", "battlePower", "BattlePower", "BP", "bp"], "-");
  const exp = firstValue(storyState, ["EXP", "exp", "Experience", "experience"], "-");
  const gold = firstValue(storyState, ["Gold", "gold", "money"], "-");
  const threat = firstValue(storyState, ["Threat Level", "Threat level", "threatLevel", "ThreatLevel"], "-");
  const rpgLocation = firstValue(storyState, ["Location", "location", "scene"], "-");

  if (els.statusBadge) {
    els.statusBadge.textContent = characterClass === "-" && bp === "-" ? "Closed" : "Status";
  }
  if (els.rpgClass) els.rpgClass.textContent = characterClass;
  if (els.rpgLocation) els.rpgLocation.textContent = rpgLocation;
  if (els.rpgBp) els.rpgBp.textContent = bp;
  if (els.rpgLevel) els.rpgLevel.textContent = level;
  if (els.rpgExp) els.rpgExp.textContent = exp;
  if (els.rpgGold) els.rpgGold.textContent = gold;
  if (els.rpgThreat) els.rpgThreat.textContent = threat;

  renderChips(els.skills, firstValue(storyState, ["Skills", "skills"], []), "No skills");
  renderChips(els.spells, firstValue(storyState, ["Spells", "spells"], []), "No spells");
  renderChips(els.abilities, firstValue(storyState, ["Abilities", "abilities"], []), "No abilities");
  renderChips(els.equipment, firstValue(storyState, ["Equipment", "equipment"], []), "No equipment");
  renderChips(els.relationships, firstValue(storyState, ["Relationships", "relationships", "relationship"], []), "No relationships");
  renderChips(els.objectives, firstValue(storyState, ["Objectives", "objectives", "activeQuests"], []), "No objectives");
  renderChips(els.inventory, firstValue(storyState, ["Inventory", "inventory", "items"], []), "No items");
}

function schemaFields(uiSchema) {
  const sections = Array.isArray(uiSchema?.sections) ? uiSchema.sections : [];
  return sections.flatMap((section) => Array.isArray(section.fields) ? section.fields : []);
}

function schemaHasFields(uiSchema) {
  return schemaFields(uiSchema).some((field) => field?.key);
}

function valueForField(storyState, field) {
  const keys = [field.key, ...(Array.isArray(field.aliases) ? field.aliases : [])].filter(Boolean);
  return firstValue(storyState, keys, "");
}

function formatFieldValue(value) {
  if (value === undefined || value === null || value === "") return "-";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function meterPercent(value, field) {
  const min = Number(field.min ?? 0);
  const max = Number(field.max ?? 100);
  const current = Number(value);
  if (!Number.isFinite(current) || !Number.isFinite(max) || max <= min) return 0;
  return Math.max(0, Math.min(100, ((current - min) / (max - min)) * 100));
}

function renderDynamicField(field, storyState) {
  const fieldType = String(field.type || "text").toLowerCase();
  const label = field.label || field.key;
  const value = valueForField(storyState, field);

  if (fieldType === "list" || fieldType === "tags") {
    const items = listValues(value);
    return `
      <div class="dynamic-field full">
        <dt>${escapeHtml(label)}</dt>
        <dd class="chips">
          ${
            items.length
              ? items.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("")
              : `<span class="muted-inline">-</span>`
          }
        </dd>
      </div>
    `;
  }

  if (fieldType === "meter") {
    const percent = meterPercent(value, field);
    return `
      <div class="dynamic-field full">
        <dt>${escapeHtml(label)}</dt>
        <dd>
          <div class="meter-row">
            <span>${escapeHtml(formatFieldValue(value))}</span>
            <span>${Math.round(percent)}%</span>
          </div>
          <div class="meter-track"><span style="width: ${percent}%"></span></div>
        </dd>
      </div>
    `;
  }

  if (fieldType === "object" && value && typeof value === "object" && !Array.isArray(value)) {
    return `
      <div class="dynamic-field full">
        <dt>${escapeHtml(label)}</dt>
        <dd class="object-list">
          ${Object.entries(value).map(([key, item]) => `<span>${escapeHtml(key)}: ${escapeHtml(item)}</span>`).join("")}
        </dd>
      </div>
    `;
  }

  return `
    <div class="dynamic-field ${fieldType === "number" ? "numeric" : ""}">
      <dt>${escapeHtml(label)}</dt>
      <dd>${escapeHtml(formatFieldValue(value))}</dd>
    </div>
  `;
}

function renderDynamicStatePanels() {
  const world = state.session?.world || selectedWorld();
  const uiSchema = world?.uiSchema || {};
  const storyState = state.session?.state || {};
  const hasSchema = schemaHasFields(uiSchema);
  setFallbackPanelsVisible(!hasSchema);

  if (!els.dynamicStatePanels) return;
  if (!hasSchema) {
    els.dynamicStatePanels.innerHTML = "";
    els.dynamicStatePanels.hidden = true;
    return;
  }

  els.dynamicStatePanels.hidden = false;
  const sections = Array.isArray(uiSchema.sections) ? uiSchema.sections : [];
  els.dynamicStatePanels.innerHTML = sections
    .map((section) => {
      const fields = Array.isArray(section.fields) ? section.fields.filter((field) => field?.key) : [];
      if (!fields.length) return "";
      return `
        <section class="panel dynamic-panel">
          <div class="panel-title-row">
            <h2>${escapeHtml(section.title || uiSchema.title || "状态")}</h2>
          </div>
          <dl class="dynamic-grid">
            ${fields.map((field) => renderDynamicField(field, storyState)).join("")}
          </dl>
        </section>
      `;
    })
    .join("");
}

function setFallbackPanelsVisible(visible) {
  [
    els.rpgClass,
    els.skills,
    els.spells,
    els.abilities,
    els.equipment,
    els.relationships,
    els.objectives,
  ].forEach((element) => {
    const panel = element?.closest(".panel");
    if (panel) panel.hidden = !visible;
  });
}

function renderEditor() {
  const character = selectedCharacter();
  els.characterName.value = character.name || "";
  els.characterRole.value = character.role || "";
  els.characterPersonality.value = character.personality || "";
  els.characterSpeechStyle.value = character.speechStyle || "";
  els.characterRules.value = Array.isArray(character.rules) ? character.rules.join("\n") : "";

  const world = selectedWorld();
  els.worldBookTitle.value = world.title || "";
  els.worldPremise.value = world.premise || "";
  els.worldTone.value = world.tone || "";
  els.worldFacts.value = Array.isArray(world.facts) ? world.facts.join("\n") : "";
}

function renderMemory() {
  els.sessionSummary.value = state.session?.summary || "";
  els.sessionSummary.disabled = state.busy || !state.session;
  els.saveMemoryBtn.disabled = state.busy || !state.session;
}

function latestAssistantMessage() {
  const messages = state.session?.messages || [];
  return [...messages].reverse().find((message) => message.role === "assistant");
}

function renderChoices() {
  els.choices.innerHTML = "";
  const assistant = latestAssistantMessage();
  const messages = state.session?.messages || [];
  const hasMessages = Boolean(messages.length);
  const lastIsAssistant = messages[messages.length - 1]?.role === "assistant";
  els.retryBtn.disabled = state.busy || !lastIsAssistant;
  els.editLastBtn.disabled = state.busy || !hasMessages;
  els.deleteLastBtn.disabled = state.busy || !hasMessages;
  const choices = assistant?.content?.choices || [
    { id: "start", text: "观察周围环境，确认自己身在何处", type: "observe" },
    { id: "ask", text: "询问身边角色接下来应该怎么做", type: "dialogue" },
    { id: "act", text: "主动寻找第一个可以推进剧情的线索", type: "action" },
  ];

  choices.slice(0, 3).forEach((choice, index) => {
    const button = document.createElement("button");
    button.className = `choice-button ${choice.type || "action"}`;
    button.type = "button";
    button.innerHTML = `
      <span class="choice-index">${String(index + 1).padStart(2, "0")}</span>
      <span class="choice-text">${escapeHtml(choice.text)}</span>
      <span class="choice-type">${choiceTypeLabels[choice.type] || "行动"}</span>
    `;
    button.addEventListener("click", () => submitMessage(choice.text));
    els.choices.appendChild(button);
  });
}

function renderUserMessage(message) {
  return `
    <article class="message user">
      <div class="message-body">
        <div class="message-label">你的行动</div>
        <div class="scene-text">${escapeHtml(message.content.text || "")}</div>
      </div>
    </article>
  `;
}

function renderAssistantMessage(message) {
  const content = message.content || {};
  const dialogue = Array.isArray(content.dialogue) ? content.dialogue : [];
  const dialogueHtml = dialogue.length
    ? `
      <div class="dialogue">
        ${dialogue
          .map(
            (line) => `
              <div class="line">
                <div class="speaker">${escapeHtml(line.speaker || "旁白")}</div>
                <div>${escapeHtml(line.text || "")}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    `
    : "";

  const source = content.source === "fallback" ? "本地 fallback" : "AI 剧情";

  return `
    <article class="message assistant">
      <div class="message-body">
        <div class="message-label">${source}</div>
        <div class="scene-text">${escapeHtml(content.sceneText || "")}</div>
        ${dialogueHtml}
      </div>
    </article>
  `;
}

function renderMessages() {
  const messages = state.session?.messages || [];
  if (!messages.length) {
    const world = selectedWorld();
    const character = selectedCharacter();
    els.messages.innerHTML = `
      <div class="empty">
        <p class="empty-title">准备进入新的故事</p>
        <p>当前世界：${escapeHtml(world.title || "-")}</p>
        <p>当前角色：${escapeHtml(character.name || "-")}</p>
        <p>点击顶部“新游戏”生成开场剧情，或打开“存档”继续旧故事。</p>
      </div>
    `;
    return;
  }

  els.messages.innerHTML = messages
    .map((message) => (message.role === "user" ? renderUserMessage(message) : renderAssistantMessage(message)))
    .join("");
  requestAnimationFrame(() => {
    els.messages.scrollTo({ top: els.messages.scrollHeight, behavior: "smooth" });
  });
}

function renderAll() {
  renderNewGamePanel();
  renderSaveDrawer();
  renderState();
  renderRpgState();
  renderDynamicStatePanels();
  renderEditor();
  renderMemory();
  renderMessages();
  renderChoices();
}

async function refreshData(sessionId = state.session?.id) {
  const sessionPath = sessionId ? `/api/session?id=${encodeURIComponent(sessionId)}` : "/api/session";
  const [session, editor, saves] = await Promise.all([
    api(sessionPath),
    api("/api/editor"),
    api("/api/sessions"),
  ]);
  state.session = session;
  state.editor = editor;
  state.sessions = saves.sessions || [];
  syncSelectionFromSession();
  renderAll();
}

async function refreshEditorAndSaves() {
  const [editor, saves] = await Promise.all([
    api("/api/editor"),
    api("/api/sessions"),
  ]);
  state.editor = editor;
  state.sessions = saves.sessions || [];
  syncSelectionFromSession();
  renderAll();
}

async function startGame() {
  if (state.busy) return;
  setBusy(true);
  try {
    const data = await api("/api/session/start", {
      method: "POST",
      body: JSON.stringify({
        worldId: els.worldSelect.value,
        characterId: els.characterSelect.value,
      }),
    });
    state.session = data.session;
    await refreshData(data.session.id);
    closeDrawer();
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function continueSession(sessionId) {
  if (state.busy) return;
  setBusy(true);
  try {
    await refreshData(sessionId);
    closeDrawer();
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function deleteSession(sessionId, title) {
  if (state.busy) return;
  const confirmed = window.confirm(`确定删除存档「${title || sessionId}」吗？`);
  if (!confirmed) return;

  setBusy(true);
  try {
    const deletingCurrent = sessionId === state.session?.id;
    const data = await api("/api/session/delete", {
      method: "POST",
      body: JSON.stringify({ sessionId }),
    });
    state.sessions = data.sessions || [];
    if (deletingCurrent && state.sessions[0]?.id) {
      await refreshData(state.sessions[0].id);
    } else if (deletingCurrent) {
      state.session = null;
      await refreshEditorAndSaves();
    } else {
      await refreshData(state.session?.id);
    }
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function submitMessage(text) {
  const trimmed = text.trim();
  if (!trimmed || state.busy || !state.session) return;

  setBusy(true);
  try {
    const data = await api("/api/message", {
      method: "POST",
      body: JSON.stringify({
        sessionId: state.session.id,
        text: trimmed,
      }),
    });
    state.session = data.session;
    els.input.value = "";
    const saves = await api("/api/sessions");
    state.sessions = saves.sessions || [];
    renderAll();
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function retryLastMessage() {
  if (state.busy || !state.session) return;

  setBusy(true);
  try {
    const data = await api("/api/message/retry", {
      method: "POST",
      body: JSON.stringify({
        sessionId: state.session.id,
      }),
    });
    state.session = data.session;
    const saves = await api("/api/sessions");
    state.sessions = saves.sessions || [];
    renderAll();
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(false);
  }
}

function latestUserText() {
  const messages = state.session?.messages || [];
  const userMessage = [...messages].reverse().find((message) => message.role === "user");
  return userMessage?.content?.text || "";
}

async function editLastUserMessage() {
  if (state.busy || !state.session) return;
  const nextText = window.prompt("修改上一条用户输入后重新生成：", latestUserText());
  if (nextText === null || !nextText.trim()) return;

  setBusy(true);
  try {
    const data = await api("/api/message/edit-last-user", {
      method: "POST",
      body: JSON.stringify({
        sessionId: state.session.id,
        text: nextText.trim(),
      }),
    });
    state.session = data.session;
    const saves = await api("/api/sessions");
    state.sessions = saves.sessions || [];
    renderAll();
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function deleteLastTurn() {
  if (state.busy || !state.session) return;
  const confirmed = window.confirm("确定撤销上一轮消息吗？");
  if (!confirmed) return;

  setBusy(true);
  try {
    const data = await api("/api/message/delete-last-turn", {
      method: "POST",
      body: JSON.stringify({
        sessionId: state.session.id,
      }),
    });
    state.session = data.session;
    const saves = await api("/api/sessions");
    state.sessions = saves.sessions || [];
    renderAll();
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function saveCharacter() {
  if (state.busy) return;
  setBusy(true);
  try {
    const character = selectedCharacter();
    const data = await api("/api/editor/character", {
      method: "POST",
      body: JSON.stringify({
        id: character.id,
        name: els.characterName.value,
        role: els.characterRole.value,
        personality: els.characterPersonality.value,
        speechStyle: els.characterSpeechStyle.value,
        rules: linesFromText(els.characterRules.value),
      }),
    });
    state.editor = data.editor;
    state.selectedCharacterId = data.character.id;
    await refreshData(state.session?.id);
    window.alert("角色卡已保存，下一轮剧情将使用最新设定。");
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function saveWorld() {
  if (state.busy) return;
  setBusy(true);
  try {
    const world = selectedWorld();
    const data = await api("/api/editor/world", {
      method: "POST",
      body: JSON.stringify({
        id: world.id,
        title: els.worldBookTitle.value,
        premise: els.worldPremise.value,
        tone: els.worldTone.value,
        facts: linesFromText(els.worldFacts.value),
      }),
    });
    state.editor = data.editor;
    state.selectedWorldId = data.world.id;
    await refreshData(state.session?.id);
    window.alert("世界书已保存，新开游戏将使用最新设定。");
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function saveMemory() {
  if (state.busy || !state.session) return;
  setBusy(true);
  try {
    const data = await api("/api/session/summary", {
      method: "POST",
      body: JSON.stringify({
        sessionId: state.session.id,
        summary: els.sessionSummary.value,
      }),
    });
    state.session = data.session;
    const saves = await api("/api/sessions");
    state.sessions = saves.sessions || [];
    renderAll();
    window.alert("长期记忆已保存，下一轮剧情会使用这段摘要。");
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(false);
  }
}

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitMessage(els.input.value);
});

els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    submitMessage(els.input.value);
  }
});

els.worldSelect.addEventListener("change", () => {
  state.selectedWorldId = els.worldSelect.value;
  renderEditor();
  renderMessages();
});

els.characterSelect.addEventListener("change", () => {
  state.selectedCharacterId = els.characterSelect.value;
  renderEditor();
  renderMessages();
});

els.startGameBtn.addEventListener("click", startGame);
els.retryBtn.addEventListener("click", retryLastMessage);
els.editLastBtn.addEventListener("click", editLastUserMessage);
els.deleteLastBtn.addEventListener("click", deleteLastTurn);
els.saveCharacterBtn.addEventListener("click", saveCharacter);
els.saveWorldBtn.addEventListener("click", saveWorld);
els.saveMemoryBtn.addEventListener("click", saveMemory);
els.nav.newGame.addEventListener("click", () => openDrawer("newGame"));
els.nav.saves.addEventListener("click", () => openDrawer("saves"));
els.nav.character.addEventListener("click", () => openDrawer("character"));
els.nav.world.addEventListener("click", () => openDrawer("world"));
els.nav.memory.addEventListener("click", () => openDrawer("memory"));
els.nav.settings.addEventListener("click", () => openDrawer("settings"));
els.drawerOverlay.addEventListener("click", closeDrawer);
document.querySelectorAll("[data-close-drawer]").forEach((button) => {
  button.addEventListener("click", closeDrawer);
});

refreshData().catch((error) => {
  els.messages.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
});
