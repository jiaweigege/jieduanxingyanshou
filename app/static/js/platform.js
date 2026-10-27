(function () {
  "use strict";
  const el = (id) => document.getElementById(id);
  if (!el("apps-root")) return;
  let applications = [], templates = [], bases = [], skills = [], connections = [], materials = [];
  let currentApp = null, conversationId = null, traceId = null, busy = false, user = null;
  const status = (message) => { el("apps-status").textContent = message; };
  async function api(path, options = {}) {
    const response = await CampusAuth.authenticatedFetch(path, {cache: "no-store", ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error((data.field ? data.field + ": " : "") + (data.error || response.status));
    return data;
  }
  const write = (path, method, data) => api(path, {method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
  function option(select, value, label) { const node = document.createElement("option"); node.value = String(value); node.textContent = label; select.append(node); }
  function fill(id, items, prompt) { const select = el(id); select.replaceChildren(); if (prompt !== undefined) option(select, "", prompt); for (const item of items) option(select, item.id, item.name); }
  function selected(id) { return Array.from(el(id).selectedOptions, (o) => Number(o.value)); }
  function setSelected(id, ids) { for (const o of el(id).options) o.selected = (ids || []).includes(Number(o.value)); }
  function appConfig() { return currentApp?.published?.config || {}; }
  function configureMessage() {
    el("apps-current").textContent = currentApp ? currentApp.name : "选择应用后开始";
    const config = appConfig();
    const template = templates.flatMap(t => t.versions).find(v => v.id === config.template_version_id);
    el("apps-variables").replaceChildren();
    for (const name of template?.variables || []) {
      const label = document.createElement("label"); label.textContent = name;
      const input = document.createElement("input"); input.required = true; input.dataset.variable = name;
      input.id = "apps-variable-" + name; label.htmlFor = input.id;
      el("apps-variables").append(label, input);
    }
    fill("apps-active-skill", skills.flatMap(s => s.versions.map(v => ({id: v.id, name: s.name + " · v" + v.version}))).filter(v => (config.skill_version_ids || []).includes(v.id)), "让模型选择");
  }
  async function refresh() {
    const [catalog, t, b, s] = await Promise.all([api("/api/apps"), api("/api/prompt-templates"), api("/api/knowledge-bases"), api("/api/skill-packages")]);
    applications = catalog.apps; templates = t.templates; bases = b.knowledge_bases; skills = s.skills;
    if (user.role === "teacher") {
      const [c, m] = await Promise.all([api("/api/tool-connections"), api("/api/materials")]);
      connections = c.connections; materials = m.materials;
      fill("apps-edit-model", Object.entries(catalog.models).map(([id, caps]) => ({id, name: id + (caps.tools ? " · 支持工具" : " · 文本")})));
      fill("apps-tool-credential", c.credential_references.map(id => ({id, name: id})), "无需凭据");
      el("apps-tool-hosts").textContent = "部署允许的地址：" + (c.allowed_hosts.join("、") || "尚未配置");
    }
    if (currentApp) currentApp = applications.find(a => a.id === currentApp.id) || null;
    el("apps-catalog").replaceChildren();
    for (const application of applications) {
      const card = document.createElement("button"); card.type = "button"; card.className = "platform-card";
      card.setAttribute("aria-pressed", String(currentApp?.id === application.id));
      const name = document.createElement("strong"); name.textContent = application.name;
      const purpose = document.createElement("span"); purpose.textContent = application.purpose;
      card.append(name, purpose);
      card.addEventListener("click", () => { currentApp = application; conversationId = null; el("apps-history").replaceChildren(); configureMessage(); for (const c of el("apps-catalog").children) c.setAttribute("aria-pressed", String(c === card)); status("已选择 " + application.name + "，点击新建会话开始。"); });
      el("apps-catalog").append(card);
    }
    fill("apps-edit-app", applications); fill("apps-template-select", templates, "新建模板"); fill("apps-base-select", bases, "新建知识库");
    fill("apps-edit-template", templates.flatMap(t => t.versions.map(v => ({id: v.id, name: t.name + " · v" + v.version}))));
    fill("apps-edit-bases", bases); fill("apps-base-materials", materials.map(m => ({id: m.id, name: m.title})));
    fill("apps-edit-skills", skills.flatMap(s => s.versions.map(v => ({id: v.id, name: s.name + " · v" + v.version}))));
    fill("apps-edit-tools", connections.filter(c => c.enabled).flatMap(c => c.definitions.map(d => ({id: d.id, name: c.name + " / " + d.name}))));
    el("apps-skill-list").replaceChildren();
    for (const skill of skills) { const p = document.createElement("p"); p.textContent = skill.name + " · " + skill.source + " · " + skill.versions.length + " 个版本"; el("apps-skill-list").append(p); }
    el("apps-tool-list").replaceChildren();
    for (const connection of connections) {
      const p = document.createElement("p"); p.textContent = connection.name + " · " + (connection.enabled ? "启用" : "停用") + " · " + connection.definitions.length + " 个工具";
      const discover = document.createElement("button"); discover.type = "button"; discover.className = "secondary-button"; discover.textContent = "重新发现";
      discover.addEventListener("click", () => action(async () => { await write(`/api/tool-connections/${connection.id}/discover`, "POST", {}); await refresh(); }, "工具已更新；已有绑定变更时请重新发布。"));
      p.append(discover); el("apps-tool-list").append(p);
    }
    editApplication(); configureMessage(); await loadConversations(); await loadRuns();
  }
  function editApplication() {
    const application = applications.find(a => a.id === Number(el("apps-edit-app").value));
    if (!application) return;
    const c = application.draft || application.published?.config || {};
    el("apps-edit-model").value = c.model || el("apps-edit-model").options[0]?.value || "";
    el("apps-edit-template").value = c.template_version_id || "";
    setSelected("apps-edit-bases", c.knowledge_base_ids); setSelected("apps-edit-skills", c.skill_version_ids); setSelected("apps-edit-tools", c.tool_definition_ids);
    el("apps-temperature").value = c.temperature ?? 0.1; el("apps-max-tokens").value = c.max_tokens || 512;
  }
  async function loadConversations() { const data = await api("/api/app-conversations"); fill("apps-conversations", data.conversations.map(c => ({id: c.id, name: (applications.find(a => a.id === c.application_id)?.name || "应用") + " · 会话 " + c.id})), "选择会话"); if (conversationId) el("apps-conversations").value = conversationId; }
  async function loadRuns() { const data = await api("/api/conversation-runs"); el("apps-runs").replaceChildren(); for (const run of data.runs.slice(0, 15)) { const button = document.createElement("button"); button.type = "button"; button.className = "secondary-button"; button.textContent = run.origin + " · " + run.status + " · " + new Date(run.created_at).toLocaleTimeString(); button.addEventListener("click", () => action(() => showTrace(run.id))); el("apps-runs").append(button); } }
  async function openConversation() {
    conversationId = Number(el("apps-conversations").value) || null; el("apps-history").replaceChildren(); if (!conversationId) return;
    const data = await api("/api/app-conversations/" + conversationId); currentApp = applications.find(a => a.id === data.application_id); configureMessage();
    for (const message of data.messages) {
      const card = document.createElement("article"); card.className = "platform-message";
      const label = document.createElement("strong"); label.textContent = message.role === "user" ? "你" : "助手";
      const text = document.createElement("p"); text.textContent = message.content; card.append(label, text);
      for (const source of message.sources || []) {
        const sourceButton = document.createElement("button"); sourceButton.type = "button"; sourceButton.className = "secondary-button";
        sourceButton.textContent = `[${source.number}] ${source.material_title} · ${source.sent_start_line || source.start_line}–${source.sent_end_line || source.end_line} 行`;
        sourceButton.addEventListener("click", () => action(async () => {
          const response = await CampusAuth.authenticatedFetch(source.file_url); if (!response.ok) throw new Error("来源不可用");
          const file = new Blob([await response.text()], {type: "text/plain;charset=utf-8"}); const url = URL.createObjectURL(file); window.open(url, "_blank", "noopener"); setTimeout(() => URL.revokeObjectURL(url), 60000);
        })); card.append(sourceButton);
      }
      if (message.role === "assistant") { const button = document.createElement("button"); button.type = "button"; button.className = "secondary-button"; button.textContent = "本次调用"; button.addEventListener("click", () => action(() => showTrace(message.run_id))); card.append(button); }
      el("apps-history").append(card);
    }
  }
  function traceSection(title, value) { const details = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = title; const pre = document.createElement("pre"); pre.textContent = JSON.stringify(value, null, 2); details.append(summary, pre); el("apps-trace-content").append(details); }
  async function showTrace(id) {
    const trace = await api("/api/conversation-runs/" + id); traceId = id;
    el("apps-trace-summary").textContent = trace.status + " · " + trace.calls.length + " 次模型调用 · 历史重放：" + (trace.config.history_replayed ? "是" : "否") + (trace.error ? " · " + trace.error : "");
    el("apps-trace-content").replaceChildren(); traceSection("配置版本与最终结果", {config: trace.config, result: trace.result});
    for (const call of trace.calls) { traceSection("调用 " + call.sequence + " · 实际请求", call.request); traceSection("调用 " + call.sequence + " · 原始响应", call.response); traceSection("调用 " + call.sequence + " · 解析结果", call.parsed); }
    traceSection("上下文来源与 Skill / 工具执行顺序", trace.events);
    if (!el("apps-trace-dialog").open) el("apps-trace-dialog").showModal();
  }
  async function action(fn, success) { try { await fn(); if (success) status(success); } catch (error) { status(error.message); } }
  function form(id, fn) { el(id).addEventListener("submit", event => { event.preventDefault(); action(fn); }); }
  el("apps-new").addEventListener("click", () => action(async () => { if (!currentApp) throw new Error("请先选择应用"); const c = await write("/api/app-conversations", "POST", {application_id: currentApp.id}); conversationId = c.id; await loadConversations(); await openConversation(); }, "会话已创建。"));
  el("apps-conversations").addEventListener("change", () => action(openConversation));
  form("apps-message", async () => {
    if (busy) return; if (!conversationId) throw new Error("请先新建会话"); busy = true; el("apps-send").disabled = true;
    const variables = {}; for (const input of el("apps-variables").querySelectorAll("input")) variables[input.dataset.variable] = input.value;
    status("正在处理，可在最近调用中查看执行状态…");
    const poll = setInterval(() => { loadRuns().catch(() => {}); }, 2500);
    try { const result = await write(`/api/app-conversations/${conversationId}/messages`, "POST", {content: el("apps-question").value, api_key: el("apps-key").value, request_id: crypto.randomUUID(), variables, ...(el("apps-active-skill").value ? {skill_version_id: Number(el("apps-active-skill").value)} : {})}); await openConversation(); status(result.generated ? "回答已完成。" : "未检索到相关资料。"); el("apps-question").value = ""; }
    finally { clearInterval(poll); busy = false; el("apps-send").disabled = false; await loadRuns(); }
  });
  el("apps-edit-app").addEventListener("change", editApplication);
  form("apps-config-form", async () => { await write("/api/apps/" + el("apps-edit-app").value, "PATCH", {config: {model: el("apps-edit-model").value, template_version_id: Number(el("apps-edit-template").value), knowledge_base_ids: selected("apps-edit-bases"), skill_version_ids: selected("apps-edit-skills"), tool_definition_ids: selected("apps-edit-tools"), temperature: Number(el("apps-temperature").value), max_tokens: Number(el("apps-max-tokens").value)}}); status("草稿已保存，发布后生效。"); });
  el("apps-publish").addEventListener("click", () => action(async () => { await write(`/api/apps/${el("apps-edit-app").value}/publish`, "POST", {}); await refresh(); }, "应用已发布。"));
  form("apps-create-form", async () => { await write("/api/apps", "POST", {name: el("apps-create-name").value, slug: el("apps-create-slug").value, kind: el("apps-create-kind").value, purpose: el("apps-create-name").value}); await refresh(); status("草稿已创建，请配置模板后发布。"); });
  el("apps-template-select").addEventListener("change", () => { const t = templates.find(t => t.id === Number(el("apps-template-select").value)); const v = t?.versions.at(-1); el("apps-template-name").value = t?.name || ""; el("apps-template-body").value = v?.body || ""; el("apps-template-vars").value = v?.variables.join(", ") || ""; });
  form("apps-template-form", async () => { const id = el("apps-template-select").value; await write("/api/prompt-templates" + (id ? "/" + id : ""), id ? "PATCH" : "POST", {name: el("apps-template-name").value, body: el("apps-template-body").value, variables: el("apps-template-vars").value.split(",").map(s => s.trim()).filter(Boolean)}); await refresh(); status("模板新版本已保存，请在应用中绑定并发布。"); });
  el("apps-base-select").addEventListener("change", () => { const b = bases.find(b => b.id === Number(el("apps-base-select").value)); el("apps-base-name").value = b?.name || ""; setSelected("apps-base-materials", b?.material_ids); });
  form("apps-base-form", async () => { const id = el("apps-base-select").value; await write("/api/knowledge-bases" + (id ? "/" + id : ""), id ? "PATCH" : "POST", {name: el("apps-base-name").value, material_ids: selected("apps-base-materials")}); await refresh(); status("知识库已保存。"); });
  form("apps-skill-form", async () => { const data = new FormData(); data.append("file", el("apps-skill-file").files[0]); await api("/api/skill-packages", {method: "POST", body: data}); await refresh(); status("技能版本已上传，请在应用中绑定。"); });
  el("apps-tool-kind").addEventListener("change", () => { el("apps-http-fields").hidden = el("apps-tool-kind").value !== "http"; });
  form("apps-tool-form", async () => { const kind = el("apps-tool-kind").value; const connection = await write("/api/tool-connections", "POST", {name: el("apps-tool-name").value, kind, url: el("apps-tool-url").value, credential_ref: el("apps-tool-credential").value || null, ...(kind === "http" ? {http_config: {method: el("apps-tool-method").value, tool: JSON.parse(el("apps-tool-schema").value)}} : {})}); await write(`/api/tool-connections/${connection.id}/discover`, "POST", {}); await refresh(); status("连接已验证，请在应用中选择工具并发布。"); });
  el("apps-trace-close").addEventListener("click", () => el("apps-trace-dialog").close());
  el("apps-trace-delete").addEventListener("click", () => action(async () => { await api("/api/conversation-runs/" + traceId, {method: "DELETE"}); el("apps-trace-dialog").close(); await loadRuns(); }, "追踪已删除，会话答案保留。"));
  el("apps-trace-export").addEventListener("click", () => action(async () => { const data = await api(`/api/conversation-runs/${traceId}/export`); const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"})); const a = document.createElement("a"); a.href = url; a.download = "trace-" + traceId + ".json"; a.click(); URL.revokeObjectURL(url); }));
  el("logout-button").addEventListener("click", () => { el("apps-key").value = ""; });
  document.addEventListener("DOMContentLoaded", () => action(async () => { user = await api("/api/me"); el("apps-root").hidden = false; el("authenticated-actions").hidden = false; el("user-chip").hidden = false; el("user-chip").textContent = user.username + " · " + user.class.name; el("apps-management").hidden = user.role !== "teacher"; await refresh(); }));
})();
