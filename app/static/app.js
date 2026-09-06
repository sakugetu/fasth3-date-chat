const $ = (selector) => document.querySelector(selector);

const ui = {
  characterName: $("#characterName"), characterTagline: $("#characterTagline"), speakerName: $("#speakerName"),
  subtitle: $("#subtitle"), sceneVideo: $("#sceneVideo"), videoFallback: $("#videoFallback"),
  sceneStatus: $("#sceneStatus"), scenePlay: $("#scenePlayButton"), sound: $("#soundButton"),
  providerBadge: $("#providerBadge"), suggestions: $("#suggestions"), form: $("#chatForm"),
  input: $("#messageInput"), send: $("#sendButton"), thinking: $("#thinking"),
  thinkingText: $("#thinking em"), error: $("#errorBanner"), newSession: $("#newSessionButton"),
  startScreen: $("#startScreen"), startButton: $("#startButton"), startHint: $("#startHint"),
  resetConfirm: $("#resetConfirm"), cancelReset: $("#cancelResetButton"), confirmReset: $("#confirmResetButton"),
  resultScreen: $("#resultScreen"), resultText: $("#resultText"), continueButton: $("#continueButton"),
  resultSettings: $("#resultSettingsButton"), goalCard: $("#goalCard"), goalTitle: $("#goalTitle"),
  goalProgress: $("#goalProgress"), characterList: $("#characterList"), scenarioList: $("#scenarioList"),
  scenarioGoal: $("#scenarioGoal"), lmSettings: $("#lmSettings"), lmBaseUrl: $("#lmBaseUrl"),
  lmModel: $("#lmModel"), lmStatus: $("#lmStatus"), testLm: $("#testLmButton"),
  h3Settings: $("#h3Settings"), h3BaseUrl: $("#h3BaseUrl"), h3Status: $("#h3Status"),
  testH3: $("#testH3Button"), settingsMessage: $("#settingsMessage"),
  referenceImageInput: $("#referenceImageInput"), referencePreview: $("#referencePreview"),
  referencePreviewImage: $("#referencePreviewImage"), referencePreviewText: $("#referencePreviewText"),
  useDefaultReference: $("#useDefaultReferenceButton"), clearReference: $("#clearReferenceButton"),
  characterDescription: $("#characterDescription"), generateCharacter: $("#generateCharacterButton"),
  characterDraft: $("#characterDraft"), characterDraftName: $("#characterDraftName"),
  characterDraftTagline: $("#characterDraftTagline"), characterDraftPersonality: $("#characterDraftPersonality"),
  characterDraftSpeech: $("#characterDraftSpeech"), characterDraftVisual: $("#characterDraftVisual"),
  saveCharacter: $("#saveCharacterButton"), scenarioDescription: $("#scenarioDescription"),
  generateScenario: $("#generateScenarioButton"), scenarioDraft: $("#scenarioDraft"),
  scenarioDraftTitle: $("#scenarioDraftTitle"), scenarioDraftSetup: $("#scenarioDraftSetup"),
  scenarioDraftGoal: $("#scenarioDraftGoal"), saveScenario: $("#saveScenarioButton"),
};

const STORAGE_KEY = "fasth3-date-chat-settings-v2";
const state = {
  settingsData: null, session: null, sending: false, sceneReady: false, soundEnabled: false,
  awaitingPlayback: false, audioContext: null, audioSource: null, audioBuffers: new Map(),
  scenePlaybackToken: 0, revealToken: 0, sceneDialogue: "", started: false, starting: false,
  characterDraft: null, scenarioDraft: null, resultDismissed: false,
  referenceImageId: null,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let data;
  try { data = await response.json(); }
  catch { throw new Error(`サーバーから読めない応答が返りました (${response.status})`); }
  if (!response.ok) throw new Error(data.error || `通信エラー (${response.status})`);
  return data;
}

function showError(message) {
  ui.error.textContent = message;
  ui.error.classList.remove("is-hidden");
}

function clearError() {
  ui.error.textContent = "";
  ui.error.classList.add("is-hidden");
}

function settingMessage(message, isError = false) {
  ui.settingsMessage.textContent = message;
  ui.settingsMessage.classList.toggle("is-error", isError);
}

function selectedValue(name) {
  return document.querySelector(`input[name="${name}"]:checked`)?.value;
}

function selectRadio(name, value) {
  const input = document.querySelector(`input[name="${name}"][value="${CSS.escape(value)}"]`);
  if (input) input.checked = true;
}

function currentConfig() {
  return {
    provider: { type: selectedValue("providerMode") || "demo", base_url: ui.lmBaseUrl.value.trim(), model: ui.lmModel.value.trim() || null },
    video: {
      mode: selectedValue("videoMode") || "none",
      base_url: ui.h3BaseUrl.value.trim(),
      reference_mode: selectedValue("referenceMode") || "omni",
      reference_image_id: state.referenceImageId,
      ref_image_size: "match",
    },
    character_id: document.querySelector('input[name="characterProfile"]:checked')?.value || "default",
    scenario_id: document.querySelector('input[name="scenarioProfile"]:checked')?.value || "night_chat",
  };
}

function saveLocalSettings() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(currentConfig()));
}

function restoreLocalSettings(defaults) {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch { saved = {}; }
  const provider = saved.provider || defaults.provider;
  const video = saved.video || defaults.video;
  selectRadio("providerMode", provider.type || "demo");
  selectRadio("videoMode", video.mode || "none");
  selectRadio("referenceMode", video.reference_mode || "omni");
  ui.lmBaseUrl.value = provider.base_url || defaults.provider.base_url;
  ui.lmModel.value = provider.model || "";
  ui.h3BaseUrl.value = video.base_url || defaults.video.base_url;
  return {
    character_id: saved.character_id || defaults.character_id,
    scenario_id: saved.scenario_id || defaults.scenario_id,
    reference_image_id: video.reference_image_id || null,
  };
}

function setReferenceImage(referenceId, label = "") {
  state.referenceImageId = referenceId || null;
  if (state.referenceImageId) {
    ui.referencePreviewImage.src = `/api/reference-images/${encodeURIComponent(state.referenceImageId)}`;
    ui.referencePreviewImage.classList.remove("is-hidden");
    ui.referencePreview.classList.remove("is-empty");
    ui.referencePreviewText.textContent = label || "参照画像を固定して使います";
    ui.clearReference.classList.remove("is-hidden");
  } else {
    ui.referencePreviewImage.removeAttribute("src");
    ui.referencePreviewImage.classList.add("is-hidden");
    ui.referencePreview.classList.add("is-empty");
    ui.referencePreviewText.textContent = "PNG / JPEG / WebP・12MB以下";
    ui.clearReference.classList.add("is-hidden");
  }
}

async function uploadReferenceImage(file) {
  if (!file) return;
  if (file.size > 12 * 1024 * 1024) {
    settingMessage("参照画像は12MB以下にしてください", true);
    ui.referenceImageInput.value = "";
    return;
  }
  settingMessage("参照画像を保存しています…");
  ui.referenceImageInput.disabled = true;
  try {
    const response = await fetch("/api/reference-images", {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    let data;
    try { data = await response.json(); }
    catch { throw new Error(`サーバーから読めない応答が返りました (${response.status})`); }
    if (!response.ok) throw new Error(data.error || `通信エラー (${response.status})`);
    setReferenceImage(data.id, file.name);
    saveLocalSettings();
    settingMessage("この画像を全ターンのキャラクター参照に使います");
  } catch (error) {
    settingMessage(error.message, true);
  } finally {
    ui.referenceImageInput.disabled = false;
    ui.referenceImageInput.value = "";
  }
}

function profileChoice(kind, item, selectedId) {
  const label = document.createElement("label");
  label.className = kind === "scenario" ? "scenario-choice" : "profile-choice";
  const input = document.createElement("input");
  input.type = "radio";
  input.name = kind === "scenario" ? "scenarioProfile" : "characterProfile";
  input.value = item.id;
  input.checked = item.id === selectedId;
  const content = document.createElement("span");
  content.className = kind === "scenario" ? "scenario-choice-card" : "profile-choice-card";
  content.innerHTML = `<strong></strong><small></small>`;
  content.querySelector("strong").textContent = item.name || item.title;
  content.querySelector("small").textContent = item.tagline || "保存した設定";
  label.append(input, content);
  return label;
}

function renderCharacters(selectedId = "default") {
  ui.characterList.replaceChildren();
  const characters = state.settingsData.characters || [];
  if (!characters.some((item) => item.id === selectedId)) selectedId = "default";
  characters.forEach((item) => ui.characterList.append(profileChoice("character", item, selectedId)));
}

function updateSelectedGoal() {
  const id = document.querySelector('input[name="scenarioProfile"]:checked')?.value;
  const scenario = state.settingsData?.scenarios?.find((item) => item.id === id);
  if (!scenario) return;
  ui.scenarioGoal.innerHTML = "";
  const label = document.createElement("span");
  label.textContent = "GOAL";
  const text = document.createElement("strong");
  text.textContent = scenario.goal;
  ui.scenarioGoal.append(label, text);
}

function renderScenarios(selectedId = "night_chat") {
  ui.scenarioList.replaceChildren();
  const scenarios = state.settingsData.scenarios || [];
  if (!scenarios.some((item) => item.id === selectedId)) selectedId = "night_chat";
  scenarios.forEach((item) => ui.scenarioList.append(profileChoice("scenario", item, selectedId)));
  updateSelectedGoal();
}

function syncSettingVisibility() {
  ui.lmSettings.classList.toggle("is-hidden", selectedValue("providerMode") !== "lmstudio");
  ui.h3Settings.classList.toggle("is-hidden", selectedValue("videoMode") !== "fasth3");
}

function syncSoundControl() {
  ui.sceneVideo.muted = true;
  ui.sound.textContent = state.soundEnabled ? "音 ON" : "音 OFF";
  ui.sound.setAttribute("aria-pressed", String(state.soundEnabled));
  ui.sound.setAttribute("aria-label", state.soundEnabled ? "音声を消す" : "音声を出す");
  ui.sound.title = state.soundEnabled ? "音声を消す" : "音声を出す";
}

function setAwaitingPlayback(awaiting) {
  state.awaitingPlayback = awaiting;
  ui.scenePlay.classList.toggle("is-hidden", !awaiting);
}

function ensureAudioContext() {
  if (!state.audioContext) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("このブラウザは音声の自動継続再生に対応していません");
    state.audioContext = new AudioContextClass();
  }
  return state.audioContext;
}

async function unlockAudio() {
  const context = ensureAudioContext();
  await context.resume();
  if (context.state !== "running") throw new Error("ブラウザの音声を開始できませんでした");
  const silent = context.createBufferSource();
  silent.buffer = context.createBuffer(1, 1, context.sampleRate);
  silent.connect(context.destination);
  silent.start();
}

function stopSceneAudio() {
  if (!state.audioSource) return;
  try { state.audioSource.stop(); } catch { /* already stopped */ }
  state.audioSource.disconnect();
  state.audioSource = null;
}

async function loadSceneAudio(url) {
  if (!state.audioBuffers.has(url)) {
    const loading = (async () => {
      const response = await fetch(url, { cache: "force-cache" });
      if (!response.ok) throw new Error(`音声データを読み込めません (${response.status})`);
      return ensureAudioContext().decodeAudioData(await response.arrayBuffer());
    })();
    state.audioBuffers.set(url, loading);
    loading.catch(() => state.audioBuffers.delete(url));
  }
  return state.audioBuffers.get(url);
}

function startSceneAudio(buffer, offset = 0) {
  stopSceneAudio();
  const source = ensureAudioContext().createBufferSource();
  source.buffer = buffer;
  source.connect(ensureAudioContext().destination);
  source.onended = () => { if (state.audioSource === source) state.audioSource = null; };
  state.audioSource = source;
  source.start(0, Math.min(Math.max(offset, 0), Math.max(buffer.duration - 0.01, 0)));
}

async function playScene({ restart = false, mediaUrl = null } = {}) {
  const token = ++state.scenePlaybackToken;
  const url = mediaUrl || ui.sceneVideo.dataset.url;
  setAwaitingPlayback(false);
  stopSceneAudio();
  if (restart) ui.sceneVideo.currentTime = 0;
  try {
    let buffer = null;
    if (state.soundEnabled) {
      await ensureAudioContext().resume();
      buffer = await loadSceneAudio(url);
      if (token !== state.scenePlaybackToken) return;
    }
    await ui.sceneVideo.play();
    if (token !== state.scenePlaybackToken) return;
    if (buffer && state.soundEnabled) startSceneAudio(buffer, ui.sceneVideo.currentTime);
  } catch (error) {
    if (token !== state.scenePlaybackToken) return;
    setAwaitingPlayback(true);
    ui.sceneStatus.textContent = "再生できません · ボタンで再試行してください";
    console.warn("Scene playback failed", error);
  }
}

function setSending(active) {
  state.sending = active;
  ui.thinking.classList.toggle("is-hidden", !active);
  document.body.classList.toggle("is-waiting", active);
  if (active) {
    ui.thinkingText.textContent = state.session?.runtime?.video?.mode === "fasth3"
      ? "返事を考えて、短い映像を生成しています" : "返事を考えています";
  }
  updateInteractionAvailability();
}

function updateInteractionAvailability() {
  const disabled = state.sending || !state.sceneReady;
  ui.send.disabled = disabled;
  ui.input.disabled = disabled;
  ui.suggestions.querySelectorAll("button").forEach((button) => { button.disabled = disabled; });
}

function setSceneReady(ready) {
  state.sceneReady = ready;
  document.body.classList.toggle("is-watching-scene", !ready);
  updateInteractionAvailability();
}

function latestAssistant() {
  return [...(state.session?.messages || [])].reverse().find((message) => message.role === "assistant");
}

function renderSuggestions(message) {
  ui.suggestions.replaceChildren();
  if (state.sending || !state.sceneReady || !Array.isArray(message?.suggestions)) return;
  message.suggestions.slice(0, 2).forEach((suggestion, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "choice";
    const number = document.createElement("span");
    number.className = "choice-index";
    number.textContent = `0${index + 1}`;
    const text = document.createElement("span");
    text.className = "choice-text";
    text.textContent = suggestion.text;
    button.append(number, text);
    button.addEventListener("click", () => sendMessage(suggestion.text));
    ui.suggestions.append(button);
  });
}

function showResultIfNeeded() {
  if (!state.session?.state?.goal_reached || state.resultDismissed) return;
  ui.resultText.textContent = state.session.scenario?.goal || "今回のゴールを達成しました。";
  ui.resultScreen.classList.remove("is-hidden");
}

function revealAfterPause(message, delay = 1000) {
  const token = ++state.revealToken;
  ui.suggestions.replaceChildren();
  setSceneReady(false);
  window.setTimeout(() => {
    if (token !== state.revealToken || state.sending) return;
    setSceneReady(true);
    renderSuggestions(message);
    ui.sceneStatus.textContent = "選択を待っています";
    showResultIfNeeded();
  }, delay);
}

function setSceneVideo(url, dialogue) {
  state.sceneDialogue = dialogue || "";
  ++state.revealToken;
  if (!url) {
    ++state.scenePlaybackToken;
    stopSceneAudio();
    ui.sceneVideo.pause();
    ui.sceneVideo.removeAttribute("src");
    delete ui.sceneVideo.dataset.url;
    ui.sceneVideo.classList.add("is-hidden");
    ui.videoFallback.classList.remove("is-hidden");
    const referenceId = state.session?.runtime?.video?.reference_image_id;
    if (referenceId) {
      ui.videoFallback.style.backgroundImage = `linear-gradient(180deg, rgba(5,5,8,.08), rgba(5,5,8,.42)), url("/api/reference-images/${encodeURIComponent(referenceId)}")`;
      ui.videoFallback.classList.add("has-reference");
    } else {
      ui.videoFallback.style.removeProperty("background-image");
      ui.videoFallback.classList.remove("has-reference");
    }
    ui.sceneStatus.textContent = "返事を受信しました";
    revealAfterPause(latestAssistant(), 1000);
    return;
  }
  setSceneReady(false);
  stopSceneAudio();
  ui.videoFallback.style.removeProperty("background-image");
  ui.videoFallback.classList.remove("has-reference");
  ui.sceneVideo.dataset.url = url;
  ui.sceneVideo.src = url;
  ui.sceneVideo.load();
  ui.sceneStatus.textContent = "映像を準備中";
  playScene({ mediaUrl: url });
}

function renderGoal() {
  const scenario = state.session?.scenario;
  if (!scenario?.goal) { ui.goalCard.classList.add("is-hidden"); return; }
  ui.goalCard.classList.remove("is-hidden", "is-accepted");
  ui.goalTitle.textContent = scenario.title || "今回のゴール";
  ui.goalProgress.textContent = state.session.state?.goal_progress || scenario.goal;
  if (state.session.state?.goal_reached) ui.goalCard.classList.add("is-accepted");
}

function renderSession() {
  if (!state.session) return;
  const character = state.session.character || {};
  ui.characterName.textContent = character.name || "相手";
  ui.characterTagline.textContent = character.tagline || "会話の相手";
  ui.speakerName.textContent = character.name || "相手";
  const message = latestAssistant();
  ui.subtitle.textContent = message?.content || "";
  ui.suggestions.replaceChildren();
  renderGoal();
  const videoUrl = message?.visual_moment?.video_url || (Number(state.session.state?.turn_count || 0) === 0 ? state.session.opening_video_url : null);
  setSceneVideo(videoUrl, message?.visual_moment?.dialogue || message?.content);
}

async function createSession() {
  const config = currentConfig();
  saveLocalSettings();
  state.session = await api("/api/sessions", { method: "POST", body: JSON.stringify(config) });
  localStorage.setItem("fasth3-date-chat-session", state.session.id);
  state.resultDismissed = false;
  const provider = state.session.runtime?.provider || {};
  ui.providerBadge.textContent = provider.type === "lmstudio" ? (provider.model || "LM Studio") : "デモ";
  renderSession();
}

async function startGame() {
  if (state.starting) return;
  if (selectedValue("videoMode") === "fasth3" && !state.referenceImageId) {
    settingMessage("FastH3を使うにはキャラクターの参照画像を選んでください", true);
    ui.referenceImageInput.focus();
    return;
  }
  state.starting = true;
  clearError();
  settingMessage("");
  ui.startButton.disabled = true;
  ui.startButton.textContent = selectedValue("videoMode") === "fasth3"
    ? "スタート動画を準備しています…" : "準備しています…";
  state.soundEnabled = true;
  syncSoundControl();
  try { await unlockAudio(); }
  catch (error) { state.soundEnabled = false; syncSoundControl(); console.warn("Audio unlock failed", error); }
  try {
    await createSession();
    state.started = true;
    document.body.classList.remove("is-start-screen");
    ui.startScreen.classList.add("is-hidden");
    ui.newSession.classList.remove("is-hidden");
  } catch (error) {
    settingMessage(error.message, true);
  } finally {
    state.starting = false;
    ui.startButton.disabled = false;
    ui.startButton.textContent = "この設定でゲームをはじめる";
  }
}

function openSettings() {
  state.started = false;
  ++state.scenePlaybackToken;
  ++state.revealToken;
  stopSceneAudio();
  ui.sceneVideo.pause();
  setSceneReady(false);
  ui.resultScreen.classList.add("is-hidden");
  ui.resetConfirm.classList.add("is-hidden");
  ui.startScreen.classList.remove("is-hidden");
  ui.newSession.classList.add("is-hidden");
  document.body.classList.add("is-start-screen");
  ui.sceneStatus.textContent = "設定を待っています";
}

async function sendMessage(rawMessage) {
  const message = String(rawMessage || "").trim();
  if (!message || state.sending || !state.sceneReady || !state.session) return;
  clearError();
  setSending(true);
  ui.suggestions.replaceChildren();
  ui.subtitle.textContent = `「${message}」`;
  ui.speakerName.textContent = "あなた";
  ui.input.value = "";
  try {
    state.session = await api("/api/chat", {
      method: "POST", body: JSON.stringify({ session_id: state.session.id, message }),
    });
    renderSession();
  } catch (error) {
    showError(`${error.message}。入力内容は失われていません。`);
    ui.input.value = message;
    ui.speakerName.textContent = state.session.character?.name || "相手";
    setSceneReady(true);
    renderSuggestions(latestAssistant());
  } finally { setSending(false); ui.input.focus(); }
}

async function testConnection(kind) {
  const button = kind === "lmstudio" ? ui.testLm : ui.testH3;
  const output = kind === "lmstudio" ? ui.lmStatus : ui.h3Status;
  button.disabled = true;
  output.textContent = "確認中…";
  output.classList.remove("is-ok", "is-error");
  try {
    const body = kind === "lmstudio"
      ? { kind, base_url: ui.lmBaseUrl.value.trim(), model: ui.lmModel.value.trim() || null }
      : { kind, base_url: ui.h3BaseUrl.value.trim(), reference_mode: selectedValue("referenceMode") || "omni" };
    const result = await api("/api/connections/test", { method: "POST", body: JSON.stringify(body) });
    output.textContent = kind === "lmstudio" ? `接続OK · ${result.model}` : "接続OK · 生成待機中";
    output.classList.add("is-ok");
  } catch (error) {
    output.textContent = `接続できません · ${error.message}`;
    output.classList.add("is-error");
  } finally { button.disabled = false; }
}

function requireLmDescription(textarea) {
  if (selectedValue("providerMode") !== "lmstudio") throw new Error("先に会話エンジンでLM Studioを選んでください");
  const description = textarea.value.trim();
  if (!description) throw new Error("日本語で設定を書いてください");
  return { description, base_url: ui.lmBaseUrl.value.trim(), model: ui.lmModel.value.trim() || null };
}

async function generateCharacter() {
  ui.generateCharacter.disabled = true;
  settingMessage("キャラクター設定を作っています…");
  try {
    const body = requireLmDescription(ui.characterDescription);
    state.characterDraft = (await api("/api/characters/generate", { method: "POST", body: JSON.stringify(body) })).profile;
    ui.characterDraftName.value = state.characterDraft.name;
    ui.characterDraftTagline.value = state.characterDraft.tagline;
    ui.characterDraftPersonality.value = state.characterDraft.personality;
    ui.characterDraftSpeech.value = state.characterDraft.speaking_style;
    ui.characterDraftVisual.value = state.characterDraft.visual_prompt;
    ui.characterDraft.classList.remove("is-hidden");
    settingMessage("設定案ができました。必要なら直して保存してください。");
  } catch (error) { settingMessage(error.message, true); }
  finally { ui.generateCharacter.disabled = false; }
}

async function saveCharacter() {
  if (!state.characterDraft) return;
  const profile = { ...state.characterDraft,
    name: ui.characterDraftName.value, tagline: ui.characterDraftTagline.value,
    personality: ui.characterDraftPersonality.value, speaking_style: ui.characterDraftSpeech.value,
    visual_prompt: ui.characterDraftVisual.value,
  };
  try {
    const saved = await api("/api/characters", { method: "POST", body: JSON.stringify({ profile }) });
    state.settingsData = await api("/api/settings");
    renderCharacters(saved.id);
    ui.characterDraft.classList.add("is-hidden");
    settingMessage(`${saved.name}を保存し、選択しました。`);
  } catch (error) { settingMessage(error.message, true); }
}

async function generateScenario() {
  ui.generateScenario.disabled = true;
  settingMessage("シチュエーションとゴールを作っています…");
  try {
    const body = requireLmDescription(ui.scenarioDescription);
    state.scenarioDraft = (await api("/api/scenarios/generate", { method: "POST", body: JSON.stringify(body) })).profile;
    ui.scenarioDraftTitle.value = state.scenarioDraft.title;
    ui.scenarioDraftSetup.value = state.scenarioDraft.setup;
    ui.scenarioDraftGoal.value = state.scenarioDraft.goal;
    ui.scenarioDraft.classList.remove("is-hidden");
    settingMessage("シナリオ案ができました。必要なら直して保存してください。");
  } catch (error) { settingMessage(error.message, true); }
  finally { ui.generateScenario.disabled = false; }
}

async function saveScenario() {
  if (!state.scenarioDraft) return;
  const profile = { ...state.scenarioDraft,
    title: ui.scenarioDraftTitle.value, setup: ui.scenarioDraftSetup.value, goal: ui.scenarioDraftGoal.value,
  };
  try {
    const saved = await api("/api/scenarios", { method: "POST", body: JSON.stringify({ profile }) });
    state.settingsData = await api("/api/settings");
    renderScenarios(saved.id);
    ui.scenarioDraft.classList.add("is-hidden");
    settingMessage(`${saved.title}を保存し、選択しました。`);
  } catch (error) { settingMessage(error.message, true); }
}

async function initialize() {
  try {
    state.settingsData = await api("/api/settings");
    const selection = restoreLocalSettings(state.settingsData.defaults);
    renderCharacters(selection.character_id);
    renderScenarios(selection.scenario_id);
    setReferenceImage(
      selection.reference_image_id,
      selection.reference_image_id === "default" ? "過去のスタート動画から作った既定画像" : "",
    );
    syncSettingVisibility();
    openSettings();
  } catch (error) { showError(error.message); }
}

document.querySelectorAll('input[name="providerMode"], input[name="videoMode"]').forEach((input) => input.addEventListener("change", syncSettingVisibility));
document.querySelectorAll('input[name="referenceMode"]').forEach((input) => input.addEventListener("change", saveLocalSettings));
ui.referenceImageInput.addEventListener("change", () => uploadReferenceImage(ui.referenceImageInput.files?.[0]));
ui.useDefaultReference.addEventListener("click", () => {
  setReferenceImage("default", "過去のスタート動画から作った既定画像");
  saveLocalSettings();
  settingMessage("同梱の既定画像を全ターンのキャラクター参照に使います");
});
ui.clearReference.addEventListener("click", () => { setReferenceImage(null); saveLocalSettings(); settingMessage("参照画像を解除しました"); });
ui.referencePreviewImage.addEventListener("error", () => {
  if (!state.referenceImageId) return;
  setReferenceImage(null);
  saveLocalSettings();
  settingMessage("保存済みの参照画像が見つかりません。もう一度選んでください", true);
});
ui.characterList.addEventListener("change", saveLocalSettings);
ui.scenarioList.addEventListener("change", () => { updateSelectedGoal(); saveLocalSettings(); });
ui.testLm.addEventListener("click", () => testConnection("lmstudio"));
ui.testH3.addEventListener("click", () => testConnection("fasth3"));
ui.generateCharacter.addEventListener("click", generateCharacter);
ui.saveCharacter.addEventListener("click", saveCharacter);
ui.generateScenario.addEventListener("click", generateScenario);
ui.saveScenario.addEventListener("click", saveScenario);
ui.startButton.addEventListener("click", startGame);
ui.newSession.addEventListener("click", () => { ui.resetConfirm.classList.remove("is-hidden"); ui.confirmReset.focus(); });
ui.cancelReset.addEventListener("click", () => ui.resetConfirm.classList.add("is-hidden"));
ui.confirmReset.addEventListener("click", openSettings);
ui.resultSettings.addEventListener("click", openSettings);
ui.continueButton.addEventListener("click", () => {
  state.resultDismissed = true;
  ui.resultScreen.classList.add("is-hidden");
  setSceneReady(true);
  renderSuggestions(latestAssistant());
});
ui.form.addEventListener("submit", (event) => { event.preventDefault(); sendMessage(ui.input.value); });
ui.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(ui.input.value); }
});

ui.sceneVideo.addEventListener("loadeddata", () => {
  ui.videoFallback.classList.add("is-hidden");
  ui.sceneVideo.classList.remove("is-hidden");
  ui.sceneStatus.textContent = "映像を再生中";
});
ui.sceneVideo.addEventListener("play", () => {
  setAwaitingPlayback(false);
  setSceneReady(false);
  ui.subtitle.textContent = state.sceneDialogue;
  ui.sceneStatus.textContent = "映像を再生中";
});
ui.sceneVideo.addEventListener("ended", () => {
  stopSceneAudio();
  ui.sceneVideo.pause();
  ui.subtitle.textContent = state.sceneDialogue;
  revealAfterPause(latestAssistant(), 1000);
});
ui.sceneVideo.addEventListener("error", () => {
  ++state.scenePlaybackToken;
  stopSceneAudio();
  ui.sceneVideo.classList.add("is-hidden");
  ui.videoFallback.classList.remove("is-hidden");
  revealAfterPause(latestAssistant(), 1000);
});
ui.scenePlay.addEventListener("click", () => playScene({ restart: true }));
ui.sound.addEventListener("click", async () => {
  state.soundEnabled = !state.soundEnabled;
  syncSoundControl();
  if (!state.soundEnabled) { ++state.scenePlaybackToken; stopSceneAudio(); return; }
  try {
    await unlockAudio();
    if (ui.sceneVideo.dataset.url) await playScene({ restart: true });
  } catch (error) { setAwaitingPlayback(true); showError(error.message); }
});

syncSoundControl();
initialize();
