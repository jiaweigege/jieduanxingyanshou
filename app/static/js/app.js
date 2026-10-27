const state = {
  user: null,
  materials: [],
  query: "",
  knowledgeResults: [],
  knowledgeQuery: "",
};

const elements = {
  authenticatedActions: document.getElementById("authenticated-actions"),
  authenticatedContent: document.getElementById("authenticated-content"),
  userChip: document.getElementById("user-chip"),
  logoutButton: document.getElementById("logout-button"),
  themeToggle: document.getElementById("theme-toggle"),
  viewToggle: document.getElementById("view-toggle"),
  commandButton: document.getElementById("open-command-palette"),
  searchInput: document.getElementById("material-search"),
  materialsContainer: document.getElementById("materials-container"),
  knowledgeSearchForm: document.getElementById("knowledge-search-form"),
  knowledgeSearchInput: document.getElementById("knowledge-search-input"),
  knowledgeSearchSubmit: document.getElementById("knowledge-search-submit"),
  knowledgeSearchStatus: document.getElementById("knowledge-search-status"),
  knowledgeSearchResults: document.getElementById("knowledge-search-results"),
  knowledgeSearchTab: document.getElementById("knowledge-search-tab"),
  knowledgeQaTab: document.getElementById("knowledge-qa-tab"),
  knowledgeSearchPanel: document.getElementById("knowledge-search-panel"),
  knowledgeQaPanel: document.getElementById("knowledge-qa-panel"),
  knowledgeQaForm: document.getElementById("knowledge-qa-form"),
  knowledgeQaKey: document.getElementById("knowledge-qa-key"),
  knowledgeQaQuestion: document.getElementById("knowledge-qa-question"),
  knowledgeQaSubmit: document.getElementById("knowledge-qa-submit"),
  knowledgeQaStatus: document.getElementById("knowledge-qa-status"),
  knowledgeQaResults: document.getElementById("knowledge-qa-results"),
  uploadPanel: document.getElementById("upload-panel"),
  showUpload: document.getElementById("show-upload"),
  uploadForm: document.getElementById("upload-form"),
  uploadProgressTrack: document.getElementById("upload-progress-track"),
  uploadProgressBar: document.getElementById("upload-progress-bar"),
  materialDialog: document.getElementById("material-dialog"),
  materialDetail: document.getElementById("material-detail"),
  commandPalette: document.getElementById("command-palette"),
  commandInput: document.getElementById("command-input"),
  commandResults: document.getElementById("command-results"),
  toastContainer: document.getElementById("toast-container"),
};

function appendHighlightedText(container, passage, query) {
  const source = String(passage || "");
  const needle = String(query || "").trim();
  if (!needle) {
    container.appendChild(document.createTextNode(source));
    return;
  }
  const lowerSource = source.toLocaleLowerCase();
  const lowerNeedle = needle.toLocaleLowerCase();
  let cursor = 0;
  while (cursor < source.length) {
    const matchAt = lowerSource.indexOf(lowerNeedle, cursor);
    if (matchAt < 0) {
      container.appendChild(document.createTextNode(source.slice(cursor)));
      break;
    }
    container.appendChild(document.createTextNode(source.slice(cursor, matchAt)));
    const mark = document.createElement("mark");
    mark.textContent = source.slice(matchAt, matchAt + needle.length);
    container.appendChild(mark);
    cursor = matchAt + needle.length;
  }
}

function setKnowledgeStatus(message, focus = false) {
  if (!elements.knowledgeSearchStatus) return;
  const className = elements.knowledgeSearchStatus.dataset.className;
  elements.knowledgeSearchStatus.textContent = className
    ? `${message} · 检索范围：${className}`
    : message;
  if (focus) elements.knowledgeSearchStatus.focus();
}

function renderKnowledgeResults() {
  if (!elements.knowledgeSearchResults) return;
  elements.knowledgeSearchResults.replaceChildren();
  for (const result of state.knowledgeResults) {
    const card = document.createElement("article");
    card.className = "knowledge-result";

    const title = document.createElement("h3");
    title.textContent = result.material_title;

    const source = document.createElement("p");
    source.className = "knowledge-result-source";
    source.textContent = `来源行 ${result.start_line}–${result.end_line}`;

    const passage = document.createElement("p");
    passage.className = "knowledge-result-passage";
    appendHighlightedText(passage, result.passage, state.knowledgeQuery);

    const actions = document.createElement("div");
    actions.className = "knowledge-result-actions";
    const detail = document.createElement("a");
    detail.className = "secondary-button";
    detail.href = result.detail_url;
    detail.textContent = "查看详情";
    detail.addEventListener("click", (event) => {
      event.preventDefault();
      openMaterial(result.material_id);
    });
    const file = document.createElement("button");
    file.type = "button";
    file.className = "secondary-button";
    file.textContent = "原始文件";
    file.addEventListener("click", () => {
      downloadMaterial(result.file_url, result.material_title);
    });
    actions.append(detail, file);

    card.append(title, source, passage, actions);
    elements.knowledgeSearchResults.appendChild(card);
  }
}

async function searchKnowledge(event) {
  event.preventDefault();
  const query = elements.knowledgeSearchInput.value.trim();
  state.knowledgeQuery = query;
  state.knowledgeResults = [];
  renderKnowledgeResults();
  if (!query) {
    setKnowledgeStatus("请输入知识检索词。", true);
    return;
  }

  elements.knowledgeSearchForm.setAttribute("aria-busy", "true");
  elements.knowledgeSearchSubmit.disabled = true;
  setKnowledgeStatus("正在检索本班知识正文…");
  try {
    const url = new URL("/api/knowledge/search", window.location.origin);
    url.searchParams.set("q", query);
    const response = await CampusAuth.authenticatedFetch(url);
    const data = await response.json();
    if (response.status === 400 && data.error === "invalid_query") {
      setKnowledgeStatus("请输入有效的知识检索词。", true);
      return;
    }
    if (response.status === 503 && data.error === "retrieval_unavailable") {
      setKnowledgeStatus("知识索引暂时不可用，请稍后重试。", true);
      return;
    }
    if (!response.ok) throw new Error("knowledge search failed");
    state.knowledgeResults = data.results;
    renderKnowledgeResults();
    setKnowledgeStatus(
      data.results.length ? `找到 ${data.results.length} 条本班结果。` : "未找到匹配内容。",
      true,
    );
  } catch {
    setKnowledgeStatus("无法完成知识检索，请稍后重试。", true);
  } finally {
    elements.knowledgeSearchForm.removeAttribute("aria-busy");
    elements.knowledgeSearchSubmit.disabled = false;
  }
}

function selectKnowledgeMode(mode, focus = false) {
  const useQa = mode === "qa";
  if (!elements.knowledgeSearchTab || !elements.knowledgeQaTab) return;
  elements.knowledgeSearchTab.setAttribute("aria-selected", String(!useQa));
  elements.knowledgeQaTab.setAttribute("aria-selected", String(useQa));
  elements.knowledgeSearchTab.tabIndex = useQa ? -1 : 0;
  elements.knowledgeQaTab.tabIndex = useQa ? 0 : -1;
  elements.knowledgeSearchTab.classList.toggle("active", !useQa);
  elements.knowledgeQaTab.classList.toggle("active", useQa);
  elements.knowledgeSearchPanel.hidden = useQa;
  elements.knowledgeQaPanel.hidden = !useQa;
  if (focus) (useQa ? elements.knowledgeQaTab : elements.knowledgeSearchTab).focus();
}

function handleKnowledgeTabKeydown(event) {
  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  const next = elements.knowledgeSearchTab.getAttribute("aria-selected") === "true"
    ? "qa"
    : "search";
  selectKnowledgeMode(next, true);
}

function setKnowledgeQaStatus(message, focus = false) {
  if (!elements.knowledgeQaStatus) return;
  elements.knowledgeQaStatus.textContent = message;
  if (focus) elements.knowledgeQaStatus.focus();
}

function appendSourceActions(container, source) {
  const actions = document.createElement("div");
  actions.className = "knowledge-result-actions";
  const detail = document.createElement("button");
  detail.type = "button";
  detail.className = "secondary-button";
  detail.textContent = "查看详情";
  detail.addEventListener("click", () => openMaterial(source.material_id));
  const file = document.createElement("button");
  file.type = "button";
  file.className = "secondary-button";
  file.textContent = "原始文件";
  file.addEventListener("click", () => downloadMaterial(source.file_url, source.material_title));
  actions.append(detail, file);
  container.appendChild(actions);
}

function renderKnowledgeAnswer(data) {
  if (!elements.knowledgeQaResults) return;
  elements.knowledgeQaResults.replaceChildren();

  const question = document.createElement("article");
  question.className = "knowledge-qa-question";
  const questionLabel = document.createElement("strong");
  questionLabel.textContent = "你";
  const questionText = document.createElement("p");
  questionText.textContent = data.question;
  question.append(questionLabel, questionText);

  const answer = document.createElement("article");
  answer.className = "knowledge-qa-answer";
  const heading = document.createElement("h3");
  heading.textContent = data.generated ? "依据资料回答" : "知识库未命中";
  const answerText = document.createElement("p");
  answerText.className = "knowledge-qa-answer-text";
  answerText.textContent = data.answer;
  answer.append(heading, answerText);

  if (Array.isArray(data.sources) && data.sources.length) {
    const sources = document.createElement("div");
    sources.className = "knowledge-qa-sources";
    for (const source of data.sources) {
      const card = document.createElement("article");
      card.className = "knowledge-qa-source";
      const title = document.createElement("h4");
      title.textContent = `[${source.number}] ${source.material_title}`;
      const meta = document.createElement("div");
      meta.className = "knowledge-result-source";
      meta.textContent = `来源行 ${source.start_line}–${source.end_line}`;
      const passage = document.createElement("p");
      passage.textContent = source.passage;
      card.append(title, meta, passage);
      appendSourceActions(card, source);
      sources.appendChild(card);
    }
    answer.appendChild(sources);
  }
  elements.knowledgeQaResults.append(question, answer);
}

async function askKnowledgeQuestion(event) {
  event.preventDefault();
  let apiKey = elements.knowledgeQaKey.value.trim();
  const question = elements.knowledgeQaQuestion.value.trim();
  if (!apiKey) {
    setKnowledgeQaStatus("请输入你的智谱 API Key。", true);
    return;
  }
  if (!question) {
    setKnowledgeQaStatus("请输入问题。", true);
    return;
  }

  elements.knowledgeQaResults.replaceChildren();
  elements.knowledgeQaForm.setAttribute("aria-busy", "true");
  elements.knowledgeQaSubmit.disabled = true;
  setKnowledgeQaStatus("正在检索本班资料并生成回答…");
  try {
    const response = await CampusAuth.authenticatedFetch("/api/knowledge/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ question, api_key: apiKey }),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) return;
    if (response.status === 400 && data.error === "invalid_question") {
      setKnowledgeQaStatus("请输入有效且不过长的问题。", true);
      return;
    }
    if (response.status === 400 && data.error === "invalid_api_key") {
      setKnowledgeQaStatus("请输入有效的智谱 API Key。", true);
      return;
    }
    if (response.status === 422 && data.error === "provider_auth_failed") {
      setKnowledgeQaStatus("智谱拒绝了这个 API Key，请检查后重试。", true);
      return;
    }
    if (response.status === 503 && data.error === "retrieval_unavailable") {
      setKnowledgeQaStatus("知识索引暂时不可用，请稍后重试。", true);
      return;
    }
    if (response.status === 503 && data.error === "ai_unavailable") {
      setKnowledgeQaStatus("智谱服务暂时不可用或响应异常，请稍后重试。", true);
      return;
    }
    if (!response.ok) throw new Error("knowledge answer failed");
    renderKnowledgeAnswer(data);
    setKnowledgeQaStatus(
      data.generated ? `已依据 ${data.sources.length} 条本班来源生成回答。` : data.answer,
      true,
    );
  } catch {
    setKnowledgeQaStatus("无法完成知识问答，请稍后重试。", true);
  } finally {
    apiKey = "";
    elements.knowledgeQaForm.removeAttribute("aria-busy");
    elements.knowledgeQaSubmit.disabled = false;
  }
}

function toast(message, type = "success") {
  if (!elements.toastContainer) return;
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.textContent = message;
  elements.toastContainer.appendChild(node);
  setTimeout(() => node.remove(), 3500);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("class-knowledge-theme", theme);
}

function applyView(view) {
  document.body.dataset.view = view;
  localStorage.setItem("class-knowledge-view", view);
}

async function fetchMaterials(query = "") {
  const url = new URL("/api/materials", window.location.origin);
  if (query) url.searchParams.set("q", query);
  const response = await CampusAuth.authenticatedFetch(url);
  if (!response.ok) throw new Error("无法加载资料");
  const data = await response.json();
  state.materials = data.materials;
  renderMaterials();
}

function renderMaterials() {
  if (!elements.materialsContainer) return;
  elements.materialsContainer.replaceChildren();
  if (state.materials.length === 0) {
    const empty = document.createElement("p");
    empty.className = "material-summary";
    empty.textContent = "暂无资料。";
    elements.materialsContainer.appendChild(empty);
    return;
  }
  for (const material of state.materials) {
    const card = document.createElement("article");
    card.className = "material-card";
    card.tabIndex = 0;

    const title = document.createElement("h3");
    title.textContent = material.title;

    const meta = document.createElement("div");
    meta.className = "material-meta";
    meta.textContent = `${material.uploader} · ${new Date(material.created_at).toLocaleString()} · ${material.filename}`;

    const summary = document.createElement("p");
    summary.className = "material-summary";
    summary.textContent = material.summary || "";

    card.append(title, meta, summary);
    card.addEventListener("click", () => openMaterial(material.id));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter") openMaterial(material.id);
    });
    elements.materialsContainer.appendChild(card);
  }
}

async function openMaterial(id) {
  const response = await CampusAuth.authenticatedFetch(`/api/materials/${id}`);
  if (!response.ok) {
    toast("无法打开资料", "error");
    return;
  }
  const data = await response.json();
  elements.materialDetail.innerHTML = `
    <h1></h1>
    <div class="material-meta"></div>
    <div class="markdown-body"></div>
    <button type="button" class="secondary-button material-download">下载原始文件</button>
  `;
  elements.materialDetail.querySelector("h1").textContent = data.title;
  elements.materialDetail.querySelector(".material-meta").textContent =
    `${data.uploader} · ${data.class} · ${new Date(data.created_at).toLocaleString()}`;
  elements.materialDetail.querySelector(".markdown-body").innerHTML = data.body_html;
  elements.materialDetail.querySelector(".material-download").addEventListener(
    "click",
    () => downloadMaterial(`/api/materials/${id}/file`, data.filename),
  );
  elements.materialDialog.showModal();
}

function responseFilename(response, fallback) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encoded) {
    try { return decodeURIComponent(encoded[1]); } catch {}
  }
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  return plain ? plain[1] : fallback;
}

async function downloadMaterial(url, fallbackFilename = "material") {
  try {
    const response = await CampusAuth.authenticatedFetch(url);
    if (!response.ok) {
      toast(response.status === 403 ? "无权下载该资料" : "无法下载资料", "error");
      return;
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = responseFilename(response, fallbackFilename);
    link.click();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  } catch {
    toast("无法下载资料", "error");
  }
}

function uploadMaterial(event) {
  event.preventDefault();
  const token = CampusAuth.getToken();
  if (!token) {
    CampusAuth.redirectToLogin();
    return;
  }
  const form = new FormData(elements.uploadForm);
  const xhr = new XMLHttpRequest();
  elements.uploadProgressTrack.hidden = false;
  elements.uploadProgressBar.style.width = "0%";

  xhr.upload.addEventListener("progress", (progressEvent) => {
    if (!progressEvent.lengthComputable) return;
    const percent = Math.round((progressEvent.loaded / progressEvent.total) * 100);
    elements.uploadProgressBar.style.width = `${percent}%`;
  });

  xhr.addEventListener("load", () => {
    elements.uploadProgressTrack.hidden = true;
    if (xhr.status === 201) {
      toast("上传完成");
      elements.uploadForm.reset();
      elements.uploadPanel.hidden = true;
      fetchMaterials(state.query);
    } else if (xhr.status === 401) {
      CampusAuth.clearToken();
      CampusAuth.redirectToLogin();
    } else {
      let message = "上传失败";
      try { message = JSON.parse(xhr.responseText).error || message; } catch {}
      toast(message, "error");
    }
  });

  xhr.addEventListener("error", () => {
    elements.uploadProgressTrack.hidden = true;
    toast("上传失败", "error");
  });

  xhr.open("POST", "/api/materials/upload");
  xhr.setRequestHeader("Authorization", `Bearer ${token}`);
  xhr.send(form);
}

function commandItems(query) {
  const actions = [
    { label: "切换主题", action: () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark") },
    { label: "切换列表/网格视图", action: () => applyView(document.body.dataset.view === "list" ? "grid" : "list") },
  ];
  if (state.user?.role === "teacher") {
    actions.unshift({ label: "上传资料", action: () => elements.uploadPanel?.removeAttribute("hidden") });
  }
  const materialItems = state.materials.map((material) => ({
    label: material.title,
    action: () => openMaterial(material.id),
  }));
  const all = [...materialItems, ...actions];
  if (!query) return all.slice(0, 8);
  const lower = query.toLowerCase();
  return all.filter((item) => item.label.toLowerCase().includes(lower)).slice(0, 8);
}

function renderCommandResults(query = "") {
  const items = commandItems(query);
  elements.commandResults.replaceChildren();
  items.forEach((item, index) => {
    const node = document.createElement("div");
    node.className = `command-item${index === 0 ? " active" : ""}`;
    node.textContent = item.label;
    node.addEventListener("click", () => {
      elements.commandPalette.close();
      item.action();
    });
    elements.commandResults.appendChild(node);
  });
}

async function bootstrapAuthenticatedPage() {
  if (!elements.authenticatedContent) return;
  if (!CampusAuth.getToken()) {
    CampusAuth.redirectToLogin();
    return;
  }
  try {
    const response = await CampusAuth.authenticatedFetch("/api/me");
    if (!response.ok) return;
    state.user = await response.json();
    elements.userChip.textContent = `${state.user.username} · ${state.user.role === "teacher" ? "教师" : "学生"} · ${state.user.class.name}`;
    elements.userChip.hidden = false;
    elements.authenticatedActions.hidden = false;
    elements.authenticatedContent.hidden = false;
    elements.showUpload.hidden = state.user.role !== "teacher";
    elements.knowledgeSearchStatus.dataset.className = state.user.class.name;
    setKnowledgeStatus("请输入检索词");
    setKnowledgeQaStatus("请输入个人智谱 API Key 和问题。", false);
    await fetchMaterials();
  } catch {
    if (CampusAuth.getToken()) toast("无法加载当前用户", "error");
  }
}

function init() {
  const savedTheme = localStorage.getItem("class-knowledge-theme") || "light";
  const savedView = localStorage.getItem("class-knowledge-view") || "list";
  applyTheme(savedTheme);
  applyView(savedView);

  elements.themeToggle?.addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
  elements.viewToggle?.addEventListener("click", () => {
    applyView(document.body.dataset.view === "list" ? "grid" : "list");
  });
  elements.showUpload?.addEventListener("click", () => {
    elements.uploadPanel?.removeAttribute("hidden");
  });
  elements.logoutButton?.addEventListener("click", () => {
    if (elements.knowledgeQaKey) elements.knowledgeQaKey.value = "";
    if (elements.knowledgeQaQuestion) elements.knowledgeQaQuestion.value = "";
    if (elements.knowledgeQaResults) elements.knowledgeQaResults.replaceChildren();
    CampusAuth.logout();
  });
  elements.uploadForm?.addEventListener("submit", uploadMaterial);
  elements.knowledgeSearchForm?.addEventListener("submit", searchKnowledge);
  elements.knowledgeQaForm?.addEventListener("submit", askKnowledgeQuestion);
  elements.knowledgeSearchTab?.addEventListener("click", () => selectKnowledgeMode("search"));
  elements.knowledgeQaTab?.addEventListener("click", () => selectKnowledgeMode("qa"));
  elements.knowledgeSearchTab?.addEventListener("keydown", handleKnowledgeTabKeydown);
  elements.knowledgeQaTab?.addEventListener("keydown", handleKnowledgeTabKeydown);
  elements.searchInput?.addEventListener("input", () => {
    state.query = elements.searchInput.value.trim();
    fetchMaterials(state.query).catch(() => toast("搜索失败", "error"));
  });
  elements.commandButton?.addEventListener("click", () => {
    if (!elements.commandPalette) return;
    elements.commandPalette.showModal();
    elements.commandInput.focus();
    renderCommandResults();
  });
  elements.commandInput?.addEventListener("input", () => {
    renderCommandResults(elements.commandInput.value.trim());
  });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      if (!elements.commandPalette) return;
      event.preventDefault();
      elements.commandPalette.showModal();
      elements.commandInput.focus();
      renderCommandResults();
    }
  });

  bootstrapAuthenticatedPage();
}

document.addEventListener("DOMContentLoaded", init);
