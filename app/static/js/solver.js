(function () {
  "use strict";
  const root = document.getElementById("solver-page");
  if (!root) return;
  const el = (id) => document.getElementById(id);
  const status = (message) => { el("solver-status").textContent = message; };
  let skills = [];
  let sessionId = null;
  let busy = false;

  async function api(path, options = {}) {
    const response = await CampusAuth.authenticatedFetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || String(response.status));
    return data;
  }
  function addOption(select, value, text) {
    const node = document.createElement("option");
    node.value = String(value);
    node.textContent = text;
    select.appendChild(node);
  }
  function renderSources(container, sources) {
    container.replaceChildren();
    for (const source of sources) {
      const card = document.createElement("article");
      card.className = "knowledge-qa-source";
      const label = document.createElement("strong");
      label.textContent = "[" + source.number + "] " + source.material_title
        + " · " + source.start_line + "–" + source.end_line + " 行";
      const passage = document.createElement("p");
      passage.textContent = source.passage;
      const detail = document.createElement("button");
      detail.type = "button";
      detail.className = "secondary-button";
      detail.textContent = "查看来源";
      detail.addEventListener("click", async () => {
        try {
          const response = await CampusAuth.authenticatedFetch(source.detail_url);
          if (!response.ok) throw new Error();
          const data = await response.json();
          const body = el("material-detail");
          body.replaceChildren();
          const title = document.createElement("h2");
          title.textContent = data.title;
          const content = document.createElement("div");
          content.innerHTML = data.body_html;
          body.append(title, content);
          el("material-dialog").showModal();
        } catch { status("无法打开来源。"); }
      });
      card.append(label, passage, detail);
      container.appendChild(card);
    }
  }
  function renderMessage(role, content, sources = []) {
    const card = document.createElement("article");
    card.className = "solver-message";
    const label = document.createElement("strong");
    label.textContent = role === "student" ? "你" : "解题引导";
    const text = document.createElement("p");
    text.textContent = content;
    const sourceList = document.createElement("div");
    sourceList.className = "knowledge-qa-sources";
    renderSources(sourceList, sources);
    card.append(label, text, sourceList);
    el("solver-history").appendChild(card);
    return { card, text, sourceList };
  }
  async function loadSkills() {
    skills = (await api("/api/solver/skills")).skills;
    el("solver-skill-select").replaceChildren();
    el("solver-student-skill").replaceChildren();
    for (const skill of skills) {
      addOption(el("solver-skill-select"), skill.id, skill.name);
      addOption(el("solver-student-skill"), skill.id, skill.name);
    }
    showSkill();
  }
  function showSkill() {
    const skill = skills.find((item) => String(item.id) === el("solver-skill-select").value);
    if (!skill) return;
    el("solver-skill-name").value = skill.name;
    el("solver-skill-prompt").value = skill.prompt;
  }
  async function loadSessions(selected = sessionId) {
    const sessions = (await api("/api/solver/sessions")).sessions;
    const select = el("solver-session-list");
    select.replaceChildren();
    addOption(select, "", "选择会话");
    for (const session of sessions) {
      addOption(select, session.id, "会话 " + session.id + " · " + session.skill_name);
    }
    if (selected) select.value = String(selected);
    await openSession();
  }
  async function openSession() {
    sessionId = Number(el("solver-session-list").value) || null;
    el("solver-history").replaceChildren();
    if (!sessionId) return;
    const session = await api("/api/solver/sessions/" + sessionId);
    for (const message of session.messages) {
      renderMessage(message.role, message.content, message.sources);
    }
  }
  function parseEvent(block) {
    const lines = block.split("\n");
    const event = lines.find((line) => line.startsWith("event: "));
    const data = lines.find((line) => line.startsWith("data: "));
    return event && data ? { type: event.slice(7), data: JSON.parse(data.slice(6)) } : null;
  }
  async function send(event) {
    event.preventDefault();
    if (busy || !sessionId) { status("请先新建或选择会话。"); return; }
    const content = el("solver-content").value.trim();
    const apiKey = el("solver-key").value.trim();
    if (!content || !apiKey) { status("请输入问题和个人 API Key。"); return; }
    busy = true;
    el("solver-send").disabled = true;
    const questionCard = renderMessage("student", content);
    const answerCard = renderMessage("assistant", "");
    let complete = false;
    try {
      const response = await CampusAuth.authenticatedFetch(
        "/api/solver/sessions/" + sessionId + "/messages", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          cache: "no-store",
          body: JSON.stringify({ content, api_key: apiKey }),
        },
      );
      if (!response.ok || !response.body) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || String(response.status));
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      status("正在读取本班资料并生成引导…");
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        let end;
        while ((end = buffer.indexOf("\n\n")) >= 0) {
          const parsed = parseEvent(buffer.slice(0, end));
          buffer = buffer.slice(end + 2);
          if (!parsed) continue;
          if (parsed.type === "sources") {
            renderSources(answerCard.sourceList, parsed.data.sources);
          } else if (parsed.type === "delta") {
            answerCard.text.textContent += parsed.data.text;
          } else if (parsed.type === "done") {
            complete = true;
            status("引导已完成。");
          } else if (parsed.type === "error") {
            throw new Error(parsed.data.error);
          }
        }
        if (done) break;
      }
      if (!complete) throw new Error("流未完成");
      el("solver-content").value = "";
    } catch (error) {
      questionCard.card.remove();
      answerCard.card.remove();
      status("生成失败：" + error.message);
    } finally {
      busy = false;
      el("solver-send").disabled = false;
    }
  }
  document.addEventListener("DOMContentLoaded", async () => {
    if (!CampusAuth.getToken()) { CampusAuth.redirectToLogin(); return; }
    try {
      const me = await api("/api/me");
      root.hidden = false;
      el("authenticated-actions").hidden = false;
      el("user-chip").textContent = me.username + " · " + me.class.name;
      el("user-chip").hidden = false;
      await loadSkills();
      if (me.role === "teacher") {
        el("solver-teacher").hidden = false;
      } else {
        el("solver-student").hidden = false;
        await loadSessions();
      }
    } catch (error) { status("无法加载解题助手：" + error.message); }
  });
  el("solver-skill-select").addEventListener("change", showSkill);
  el("solver-skill-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = el("solver-skill-select").value;
    try {
      await api("/api/solver/skills/" + id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: el("solver-skill-name").value,
          prompt: el("solver-skill-prompt").value,
        }),
      });
      await loadSkills();
      el("solver-skill-select").value = id;
      showSkill();
      status("技能已保存。");
    } catch (error) { status("保存失败：" + error.message); }
  });
  el("solver-skill-create").addEventListener("click", async () => {
    try {
      const skill = await api("/api/solver/skills", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: el("solver-skill-name").value,
          prompt: el("solver-skill-prompt").value,
        }),
      });
      await loadSkills();
      el("solver-skill-select").value = String(skill.id);
      showSkill();
      status("新技能已创建。");
    } catch (error) { status("创建失败：" + error.message); }
  });
  el("solver-new-session").addEventListener("click", async () => {
    try {
      const session = await api("/api/solver/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill_id: Number(el("solver-student-skill").value) }),
      });
      await loadSessions(session.id);
      status("会话已创建，可以提问。");
    } catch (error) { status("创建会话失败：" + error.message); }
  });
  el("solver-session-list").addEventListener("change", openSession);
  el("solver-message-form").addEventListener("submit", send);
  el("logout-button").addEventListener("click", () => {
    el("solver-key").value = "";
    CampusAuth.logout();
  });
})();
