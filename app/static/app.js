/* =========================================================================
 * Hackathon — single-page Platform (dark, high-contrast).
 * Auth-aware. Talks to the Flask JSON API.
 * ========================================================================= */
(function () {
  "use strict";

  const META = window.OPS_META || {
    taskStates: [], stakeholderRoles: [], stakeholderRoleGroups: [], stakeholderStatuses: [], userRoles: [], me: null,
  };

  const state = {
    me: META.me,
    projects: [],
    users: [],
    docs: [],
    currentProjectId: null,
    currentSprintId: null,
    stakeholderFilter: "",
    view: "board",
    section: null,            // null = epic board; else program view key
    community: null,          // cached /api/community snapshot
    participantFilter: "",
    participantSearch: "",
  };

  // ---- HTTP helpers -------------------------------------------------------
  async function api(path, method = "GET", body) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    if (res.status === 401) { window.location.href = "/"; throw new Error("Session expired."); }
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok || data.ok === false) {
      throw new Error(data.message || `Request failed (${res.status})`);
    }
    return data;
  }

  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const isAdmin = () => !!(state.me && state.me.is_admin);

  // ---- Toast --------------------------------------------------------------
  let toastTimer;
  function toast(msg, kind = "ok") {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.className =
      "fixed bottom-6 right-6 z-[60] px-4 py-3 rounded-xl shadow-xl text-sm font-medium border " +
      (kind === "ok"
        ? "bg-slate-900 text-white border-slate-700"
        : "bg-rose-600 text-white border-rose-400");
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 3400);
  }

  // ---- Derived getters ----------------------------------------------------
  const currentProject = () =>
    state.projects.find((p) => p.id === state.currentProjectId) || null;

  const currentSprint = () => {
    const p = currentProject();
    if (!p) return null;
    return p.sprints.find((s) => s.id === state.currentSprintId) || null;
  };

  const initials = (n) =>
    String(n || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

  // ---- Bootstrap ----------------------------------------------------------
  async function bootstrap() {
    const data = await api("/api/bootstrap");
    state.me = data.me;
    state.projects = data.projects;
    state.users = data.users;
    state.docs = data.docs || [];
    if (!state.currentProjectId && state.projects.length) {
      selectProject(state.projects[0].id, false);
    }
    renderAll();
  }

  async function refresh() {
    const data = await api("/api/bootstrap");
    state.me = data.me;
    state.projects = data.projects;
    state.users = data.users;
    state.docs = data.docs || [];
    renderAll();
  }

  // ---- Selection ----------------------------------------------------------
  function selectProject(id, render = true) {
    state.section = null;
    state.currentProjectId = id;
    const p = currentProject();
    state.currentSprintId = (p && p.sprints[0]) ? p.sprints[0].id : null;
    state.stakeholderFilter = "";
    if (render) renderAll();
  }

  function selectSprint(id) {
    state.section = null;
    state.currentSprintId = id;
    renderMain();
  }

  async function logout() {
    try { await fetch("/auth/logout", { method: "POST" }); } catch (_) {}
    window.location.href = "/";
  }

  // ===================== RENDER ===========================================
  function renderAll() {
    renderProjects();
    renderMain();
    const label = document.getElementById("team-label");
    if (label) label.textContent = isAdmin() ? "Manage team" : "Team";
    document.getElementById("team-count").textContent =
      `${state.users.length} member${state.users.length === 1 ? "" : "s"}`;
  }

  function renderProjects() {
    const host = document.getElementById("project-list");
    if (!state.projects.length) {
      host.innerHTML = `<p class="text-xs text-slate-600 px-3 py-4">No epics yet. Create one to begin.</p>`;
      return;
    }
    host.innerHTML = state.projects.map((p) => {
      const active = p.id === state.currentProjectId;
      return `
      <button onclick="OPS.selectProject(${p.id})"
        class="w-full text-left px-3 py-2.5 rounded-xl transition ${active ? "bg-brand-500/15 ring-1 ring-brand-500/40" : "hover:bg-slate-800/60"}">
        <div class="flex items-center justify-between">
          <span class="text-sm font-semibold ${active ? "text-brand-200" : "text-slate-200"}">${esc(p.name)}</span>
          ${p.has_blocked_tasks ? `<span class="h-2 w-2 rounded-full bg-rose-400" title="Has blocked tasks"></span>` : ""}
        </div>
        <p class="text-[11px] text-slate-500 mt-0.5">${p.sprints.length} sprint${p.sprints.length === 1 ? "" : "s"}${p.owner ? " · " + esc(p.owner.display_name) : ""}</p>
      </button>`;
    }).join("");
  }

  function renderMain() {
    const p = currentProject();
    const title = document.getElementById("project-title");
    const subtitle = document.getElementById("project-subtitle");
    const gear = document.getElementById("epic-edit-btn");

    highlightSectionNav();
    if (state.section) {
      renderProgramSection();
      return;
    }
    // Restore epic chrome when leaving a program section.
    const epicActions = document.getElementById("epic-actions");
    if (epicActions) epicActions.classList.remove("hidden");
    document.getElementById("program-view").classList.add("hidden");

    if (!p) {
      title.textContent = "Select an epic";
      subtitle.textContent = "—";
      if (gear) gear.classList.add("hidden");
      document.getElementById("sprint-tabs").innerHTML = "";
      document.getElementById("kanban").innerHTML = "";
      document.getElementById("overview-view").innerHTML = "";
      document.getElementById("blocked-banner").classList.add("hidden");
      return;
    }
    title.textContent = p.name;
    subtitle.textContent = p.description || "Internal operations epic";
    if (gear) gear.classList.remove("hidden");

    const blockedCount = p.sprints.reduce((n, s) => n + s.tasks.filter((t) => t.is_blocked).length, 0);
    const banner = document.getElementById("blocked-banner");
    if (blockedCount > 0) {
      banner.classList.remove("hidden"); banner.classList.add("flex");
      document.getElementById("blocked-count").textContent = blockedCount;
    } else {
      banner.classList.add("hidden"); banner.classList.remove("flex");
    }

    updateViewToggle();
    const boardControls = document.getElementById("board-controls");
    const boardView = document.getElementById("board-view");
    const overviewView = document.getElementById("overview-view");
    if (state.view === "overview") {
      boardControls.classList.add("hidden");
      boardView.classList.add("hidden");
      overviewView.classList.remove("hidden");
      renderOverview(p);
    } else {
      boardControls.classList.remove("hidden");
      boardView.classList.remove("hidden");
      overviewView.classList.add("hidden");
      renderSprintTabs(p);
      renderStakeholderFilter(p);
      renderKanban();
    }
  }

  function setView(view) {
    state.section = null;
    state.view = view;
    renderMain();
  }

  function updateViewToggle() {
    const b = document.getElementById("view-board");
    const o = document.getElementById("view-overview");
    if (!b || !o) return;
    const on = "px-3 py-1.5 rounded-md text-xs font-semibold bg-brand-500 text-white";
    const off = "px-3 py-1.5 rounded-md text-xs font-semibold text-slate-400 hover:text-slate-200";
    b.className = state.view === "board" ? on : off;
    o.className = state.view === "overview" ? on : off;
  }

  function renderSprintTabs(p) {
    const host = document.getElementById("sprint-tabs");
    host.innerHTML = p.sprints.map((s) => {
      const sel = s.id === state.currentSprintId;
      return `
      <button onclick="OPS.selectSprint(${s.id})"
        class="px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap flex items-center gap-2 ${sel ? "bg-brand-500 text-white shadow" : "text-slate-400 hover:bg-slate-800/70"}">
        ${esc(s.name)}
        <span class="text-[11px] opacity-70">${s.task_count}</span>
      </button>`;
    }).join("");
  }

  function renderStakeholderFilter(p) {
    const sel = document.getElementById("stakeholder-filter");
    sel.innerHTML = `<option value="">All stakeholders</option>` +
      p.stakeholders.map((s) =>
        `<option value="${s.id}" ${String(s.id) === state.stakeholderFilter ? "selected" : ""}>${esc(s.name)}</option>`
      ).join("");
  }

  function renderKanban() {
    const sprint = currentSprint();
    const board = document.getElementById("kanban");
    const empty = document.getElementById("empty-state");
    if (!sprint) {
      board.innerHTML = ""; board.classList.add("hidden");
      empty.classList.remove("hidden"); empty.classList.add("flex");
      return;
    }
    board.classList.remove("hidden");
    empty.classList.add("hidden"); empty.classList.remove("flex");

    let tasks = sprint.tasks;
    if (state.stakeholderFilter) {
      tasks = tasks.filter((t) => String(t.stakeholder_id) === state.stakeholderFilter);
    }

    board.innerHTML = META.taskStates.map((col) => {
      const colTasks = tasks.filter((t) => t.state_key === col.key);
      return `
      <div class="kanban-col flex-1 min-w-0 flex flex-col surface border rounded-2xl h-full"
           ondragover="OPS.dragOver(event)" ondragleave="OPS.dragLeave(event)" ondrop="OPS.drop(event,'${col.key}')">
        <div class="px-4 py-3 flex items-center justify-between border-b border-slate-800/70">
          <span class="text-sm font-semibold text-slate-200">${esc(col.label)}</span>
          <span class="text-xs font-medium text-slate-400 bg-slate-800 rounded-full px-2 py-0.5">${colTasks.length}</span>
        </div>
        <div class="flex-1 overflow-y-auto scroll-thin p-3 space-y-3">
          ${colTasks.map(taskCard).join("") || `<p class="text-xs text-slate-600 text-center py-6">Empty</p>`}
        </div>
      </div>`;
    }).join("");
  }

  function taskCard(t) {
    const prio = { 1: ["High", "bg-rose-500/20 text-rose-300"], 2: ["Med", "bg-amber-500/20 text-amber-300"], 3: ["Low", "bg-slate-700 text-slate-300"] }[t.priority] || ["—", "bg-slate-700 text-slate-300"];
    return `
    <div draggable="true" ondragstart="OPS.dragStart(event,${t.id})"
      class="rounded-xl border ${t.is_blocked ? "border-rose-500/50 bg-rose-500/5" : "border-slate-800 surface-2"} p-3 shadow-sm hover:border-brand-500/50 transition cursor-grab active:cursor-grabbing">
      <div onclick="OPS.openTask(${t.id})" class="cursor-pointer">
        <div class="flex items-start justify-between gap-2">
          <p class="text-sm font-semibold text-slate-100 leading-snug hover:text-brand-200">${esc(t.title)}</p>
          <span class="shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded ${prio[1]}">${prio[0]}</span>
        </div>
        ${t.description ? `<p class="text-xs text-slate-500 mt-1 line-clamp-2">${esc(stripHtml(t.description))}</p>` : ""}
        ${t.stakeholder ? `<div class="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-brand-200 bg-brand-500/15 rounded-md px-2 py-0.5">⛓ Partner: ${esc(t.stakeholder.name)}</div>` : ""}
        ${t.is_blocked ? `<div class="mt-2 text-[11px] font-semibold text-rose-300 flex items-center gap-1">⚠ Blocked${t.blocked_reason ? ": " + esc(t.blocked_reason) : ""}</div>` : ""}
      </div>
      <div class="mt-3 flex items-center justify-between">
        ${assigneeAvatars(t)}
        <div class="flex items-center gap-1">
          <button onclick="OPS.openTask(${t.id})" class="text-[11px] text-slate-500 hover:text-brand-200 px-1">Open</button>
          <button onclick="OPS.toggleBlock(${t.id}, ${t.is_blocked})" class="text-[11px] ${t.is_blocked ? "text-emerald-400" : "text-rose-400"} hover:underline px-1">${t.is_blocked ? "Unblock" : "Block"}</button>
        </div>
      </div>
    </div>`;
  }

  const stripHtml = (s) => {
    const tmp = document.createElement("div");
    tmp.innerHTML = String(s || "");
    return (tmp.textContent || tmp.innerText || "").replace(/\s+/g, " ").trim();
  };

  // ===================== DRAG & DROP ======================================
  let dragTaskId = null;
  function dragStart(e, id) { dragTaskId = id; e.dataTransfer.effectAllowed = "move"; }
  function dragOver(e) { e.preventDefault(); e.currentTarget.classList.add("drag-over"); }
  function dragLeave(e) { e.currentTarget.classList.remove("drag-over"); }
  async function drop(e, stateKey) {
    e.preventDefault();
    e.currentTarget.classList.remove("drag-over");
    if (dragTaskId == null) return;
    await transition(dragTaskId, stateKey);
    dragTaskId = null;
  }

  async function transition(taskId, stateKey) {
    try {
      await api(`/api/tasks/${taskId}/transition`, "POST", { state: stateKey });
      toast("Task moved.");
      await refresh();
    } catch (err) { toast(err.message, "err"); }
  }

  // ----- Sprint reordering (drag to sort within the Sprints list) ----------
  let dragSprintId = null;
  function sprintDragStart(e, id) {
    dragSprintId = id;
    e.dataTransfer.effectAllowed = "move";
    e.currentTarget.classList.add("opacity-60");
  }
  function sprintDragEnd(e) { e.currentTarget.classList.remove("opacity-60"); }
  function sprintDragOver(e) { e.preventDefault(); e.currentTarget.classList.add("drag-over"); }
  function sprintDragLeave(e) { e.currentTarget.classList.remove("drag-over"); }
  async function sprintDrop(e, targetId) {
    e.preventDefault();
    e.currentTarget.classList.remove("drag-over");
    const moved = dragSprintId;
    dragSprintId = null;
    if (moved == null || moved === targetId) return;
    const ids = currentProject().sprints.map((s) => s.id);
    const from = ids.indexOf(moved);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    try {
      await Promise.all(ids.map((id, idx) => api(`/api/sprints/${id}`, "PATCH", { sequence: idx })));
      toast("Sprints reordered.");
      await refresh();
      openModal("sprintManage");
    } catch (err) { toast(err.message, "err"); }
  }

  async function toggleBlock(taskId, currentlyBlocked) {
    let reason = null;
    if (!currentlyBlocked) {
      reason = window.prompt("Reason for blocking (escalation email will be sent):", "");
      if (reason === null) return;
    }
    try {
      await api(`/api/tasks/${taskId}/block`, "POST", { blocked: !currentlyBlocked, reason });
      toast(currentlyBlocked ? "Unblocked." : "Blocked · escalation dispatched.", currentlyBlocked ? "ok" : "err");
      await refresh();
    } catch (err) { toast(err.message, "err"); }
  }

  function applyFilter() {
    state.stakeholderFilter = document.getElementById("stakeholder-filter").value;
    renderKanban();
  }

  // ===================== MODALS ===========================================
  const MODAL_WIDTH = { taskDetail: "max-w-3xl", team: "max-w-2xl", manageStakeholders: "max-w-2xl", stakeholderForm: "max-w-2xl", sprintManage: "max-w-2xl", docs: "max-w-2xl", docEdit: "max-w-3xl" };
  let taskDetailEditor = null;
  let createTaskEditor = null;
  let docEditor = null;
  const assigneePickerState = {};

  function destroyTaskEditor() {
    // Quill has no destroy(); dropping the references lets the cleared modal
    // DOM be garbage-collected.
    taskDetailEditor = null;
    createTaskEditor = null;
    docEditor = null;
  }

  function openModal(kind, arg) {
    const needsProject = !["project", "team", "docs", "docEdit"].includes(kind);
    if (needsProject && !currentProject()) { toast("Create or select an epic first.", "err"); return; }
    destroyTaskEditor();
    const card = document.getElementById("modal-card");
    card.className =
      "relative surface border rounded-2xl shadow-2xl w-full p-6 max-h-[90vh] overflow-y-auto scroll-thin text-slate-200 " +
      (MODAL_WIDTH[kind] || "max-w-lg");
    card.innerHTML = MODALS[kind](arg);
    if (kind === "taskDetail") {
      initializeTaskDetailEditor(arg);
      const found = findTask(arg);
      initializeAssigneePicker("td", found ? assigneeIds(found.task) : []);
    }
    if (kind === "task") {
      initializeCreateTaskEditor();
      initializeAssigneePicker("ct", []);
    }
    if (kind === "docEdit") initializeDocEditor(arg);
    document.getElementById("modal-host").classList.remove("hidden");
  }
  function closeModal() {
    destroyTaskEditor();
    document.getElementById("modal-host").classList.add("hidden");
    document.getElementById("modal-card").innerHTML = "";
    Object.keys(assigneePickerState).forEach((key) => delete assigneePickerState[key]);
    editingUserId = null; editingStakeholderId = null; editingDocId = null;
  }

  function findTask(id) {
    for (const p of state.projects)
      for (const s of p.sprints) {
        const t = s.tasks.find((x) => x.id === id);
        if (t) return { task: t, sprint: s, project: p };
      }
    return null;
  }
  function openTask(id) { openModal("taskDetail", id); }

  function mountQuill(elId, initialHTML) {
    const el = document.getElementById(elId);
    if (!el) return null;
    if (!window.Quill) {
      el.innerHTML = `<textarea id="${elId}-fallback" rows="8" class="w-full rounded-xl surface-2 border border-slate-700 px-3 py-2.5 text-sm text-slate-100 outline-none"></textarea>`;
      if (initialHTML) document.getElementById(`${elId}-fallback`).value = initialHTML;
      return null;
    }
    const q = new window.Quill(el, {
      theme: "snow",
      placeholder: "Write a detailed description\u2026",
      modules: { toolbar: [
        [{ header: [1, 2, 3, false] }],
        ["bold", "italic", "underline", "strike"],
        [{ list: "ordered" }, { list: "bullet" }],
        ["blockquote", "code-block"],
        ["link"],
        ["clean"],
      ]},
    });
    if (initialHTML && initialHTML.trim()) {
      q.clipboard.dangerouslyPasteHTML(initialHTML);
    }
    return q;
  }
  function quillHTML(q, fallbackId) {
    if (q) {
      const text = q.getText().replace(/\s+$/, "").trim();
      const html = q.root.innerHTML;
      if (!text && !/<(img|a|iframe|pre)\b/i.test(html)) return "";
      return window.DOMPurify ? window.DOMPurify.sanitize(html) : html;
    }
    const fb = document.getElementById(fallbackId);
    return fb ? fb.value : "";
  }
  function initializeTaskDetailEditor(taskId) {
    const found = findTask(taskId);
    if (!found) return;
    taskDetailEditor = mountQuill("td-editor", found.task.description || "");
  }
  function initializeCreateTaskEditor() {
    createTaskEditor = mountQuill("ct-editor", "");
  }
  function getTaskDetailHTML() { return quillHTML(taskDetailEditor, "td-editor-fallback"); }
  function getCreateTaskHTML() { return quillHTML(createTaskEditor, "ct-editor-fallback"); }
  function initializeDocEditor(docId) {
    const doc = docId != null ? state.docs.find((d) => d.id === docId) : null;
    docEditor = mountQuill("doc-editor", doc ? doc.content || "" : "");
  }
  function getDocHTML() { return quillHTML(docEditor, "doc-editor-fallback"); }

  // ---- Form primitives (dark) --------------------------------------------
  const field = (label, name, attrs = "", type = "text") => `
    <label class="block mb-3">
      <span class="text-xs font-semibold text-slate-400">${label}</span>
      <input name="${name}" type="${type}" ${attrs}
        class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none" />
    </label>`;
  const area = (label, name, ph = "") => `
    <label class="block mb-3">
      <span class="text-xs font-semibold text-slate-400">${label}</span>
      <textarea name="${name}" rows="2" placeholder="${ph}"
        class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none"></textarea>
    </label>`;
  const head = (title, sub) =>
    `<h3 class="text-lg font-bold text-white mb-1">${title}</h3>${sub ? `<p class="text-xs text-slate-500 mb-4">${sub}</p>` : `<div class="mb-4"></div>`}`;
  const footer = (label) => `
    <div class="flex justify-end gap-2 mt-5">
      <button type="button" onclick="OPS.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Cancel</button>
      <button type="submit" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">${label}</button>
    </div>`;

  function userOptions(selected) {
    return `<option value="">— none —</option>` +
      state.users.map((u) => `<option value="${u.id}" ${u.id === selected ? "selected" : ""}>${esc(u.display_name)}</option>`).join("");
  }

  function assigneeIds(task) {
    if (Array.isArray(task.assigned_user_ids) && task.assigned_user_ids.length) {
      return task.assigned_user_ids;
    }
    if (task.assigned_to != null) return [task.assigned_to];
    return [];
  }

  function assigneesForTask(task) {
    if (Array.isArray(task.assignees) && task.assignees.length) {
      return task.assignees;
    }
    if (task.assignee) return [task.assignee];
    return [];
  }

  function selectedAssigneeIdsFromPicker(key) {
    const store = assigneePickerState[key];
    if (!store) return [];
    return Array.from(store.selected);
  }

  function assigneePickerMarkup(key, label, help) {
    return `
      <div class="block mb-3">
        <div class="flex items-center justify-between mb-1">
          <span class="text-xs font-semibold text-slate-400">${esc(label)}</span>
          <button type="button" onclick="OPS.assigneePickerClear('${key}')" class="text-[11px] font-semibold text-slate-500 hover:text-slate-300">Clear</button>
        </div>
        <div class="rounded-xl surface-2 border border-slate-700 p-2.5">
          <div id="${key}-assignees-chips" class="flex flex-wrap gap-1.5 mb-2"></div>
          <input id="${key}-assignees-search" type="text" placeholder="Search members..."
            oninput="OPS.assigneePickerSearch('${key}', this.value)"
            class="w-full rounded-lg border border-slate-700 bg-slate-900/70 px-2.5 py-2 text-sm text-slate-100 placeholder-slate-500 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none" />
          <div id="${key}-assignees-list" class="mt-2 max-h-44 overflow-y-auto scroll-thin space-y-1"></div>
        </div>
        ${help ? `<p class="mt-1 text-[11px] text-slate-500">${esc(help)}</p>` : ""}
      </div>`;
  }

  function renderAssigneePicker(key) {
    const store = assigneePickerState[key];
    if (!store) return;
    const chipHost = document.getElementById(`${key}-assignees-chips`);
    const listHost = document.getElementById(`${key}-assignees-list`);
    if (!chipHost || !listHost) return;

    const usersById = new Map(state.users.map((u) => [u.id, u]));
    const selectedUsers = Array.from(store.selected)
      .map((id) => usersById.get(id))
      .filter(Boolean);

    chipHost.innerHTML = selectedUsers.length
      ? selectedUsers.map((u, idx) => `
        <span class="inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-semibold ${idx === 0 ? "bg-brand-500/25 text-brand-200 border border-brand-500/40" : "bg-slate-800 text-slate-300 border border-slate-700"}">
          <span class="h-5 w-5 rounded-full bg-brand-500 text-white text-[10px] font-bold flex items-center justify-center">${esc(initials(u.display_name))}</span>
          ${esc(u.display_name)}
          ${idx === 0 ? `<span class="text-[10px] uppercase tracking-wide text-brand-100/90">Primary</span>` : ""}
          <button type="button" onclick="OPS.assigneePickerToggle('${key}', ${u.id})" class="text-slate-300 hover:text-white leading-none">&times;</button>
        </span>`).join("")
      : `<span class="text-[11px] text-slate-500">No assignees selected</span>`;

    const q = (store.query || "").trim().toLowerCase();
    const filteredUsers = q
      ? state.users.filter((u) => u.display_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q))
      : state.users;

    listHost.innerHTML = filteredUsers.length
      ? filteredUsers.map((u) => {
        const active = store.selected.has(u.id);
        return `
          <button type="button" onclick="OPS.assigneePickerToggle('${key}', ${u.id})"
            class="w-full text-left rounded-lg px-2.5 py-2 flex items-center justify-between gap-2 border ${active ? "border-brand-500/60 bg-brand-500/10" : "border-slate-700 hover:border-slate-600 hover:bg-slate-800/60"}">
            <span class="min-w-0 flex items-center gap-2">
              <span class="h-7 w-7 rounded-full bg-brand-500 text-white text-[10px] font-bold flex items-center justify-center shrink-0">${esc(initials(u.display_name))}</span>
              <span class="min-w-0">
                <span class="block text-sm font-semibold ${active ? "text-brand-200" : "text-slate-100"} truncate">${esc(u.display_name)}</span>
                <span class="block text-[11px] text-slate-500 truncate">${esc(u.email)}</span>
              </span>
            </span>
            <span class="text-xs font-semibold ${active ? "text-brand-300" : "text-slate-500"}">${active ? "Assigned" : "Add"}</span>
          </button>`;
      }).join("")
      : `<p class="text-[11px] text-slate-500 text-center py-3">No team members match.</p>`;
  }

  function initializeAssigneePicker(key, selectedIds) {
    const normalized = [];
    for (const raw of selectedIds || []) {
      const id = parseInt(raw, 10);
      if (!Number.isNaN(id) && !normalized.includes(id)) normalized.push(id);
    }
    assigneePickerState[key] = {
      selected: new Set(normalized),
      query: "",
    };
    renderAssigneePicker(key);
  }

  function assigneePickerToggle(key, userId) {
    const store = assigneePickerState[key];
    if (!store) return;
    const id = parseInt(userId, 10);
    if (Number.isNaN(id)) return;
    if (store.selected.has(id)) {
      store.selected.delete(id);
    } else {
      store.selected.add(id);
    }
    renderAssigneePicker(key);
  }

  function assigneePickerSearch(key, query) {
    const store = assigneePickerState[key];
    if (!store) return;
    store.query = query || "";
    renderAssigneePicker(key);
  }

  function assigneePickerClear(key) {
    const store = assigneePickerState[key];
    if (!store) return;
    store.selected = new Set();
    renderAssigneePicker(key);
  }

  function assigneeAvatars(task) {
    const people = assigneesForTask(task);
    if (!people.length) {
      return `<span class="text-[11px] text-slate-600">Unassigned</span>`;
    }
    const avatarLimit = 3;
    const visible = people.slice(0, avatarLimit);
    const extra = people.length - visible.length;
    return `<div class="flex items-center">${visible.map((u, i) =>
      `<span class="h-6 w-6 rounded-full bg-brand-500 text-white text-[10px] font-bold flex items-center justify-center ${i ? "-ml-2 ring-2 ring-slate-900" : ""}" title="${esc(u.display_name)}">${esc(initials(u.display_name))}</span>`
    ).join("")}${extra > 0 ? `<span class="h-6 min-w-6 px-1 rounded-full bg-slate-700 text-slate-200 text-[10px] font-bold flex items-center justify-center -ml-2 ring-2 ring-slate-900" title="${extra} more assignee${extra === 1 ? "" : "s"}">+${extra}</span>` : ""}</div>`;
  }

  function assigneeSummary(task) {
    const people = assigneesForTask(task);
    if (!people.length) return "Unassigned";
    const names = people.map((u) => u.display_name);
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  }

  let editingUserId = null;
  let editingStakeholderId = null;
  let editingDocId = null;
  let editingSprintId = null;
  const PRIORITY_LABEL = { 1: "High", 2: "Medium", 3: "Low" };

  const STATUS_BADGE = {
    PENDING: "bg-amber-500/20 text-amber-300",
    CONFIRMED: "bg-emerald-500/20 text-emerald-300",
    REJECTED: "bg-rose-500/20 text-rose-300",
  };
  const USER_STATUS_BADGE = {
    invited: "bg-amber-500/20 text-amber-300",
    active: "bg-emerald-500/20 text-emerald-300",
    disabled: "bg-slate-700 text-slate-400",
  };

  function roleCheckboxes(name, selectedKeys) {
    const sel = new Set(selectedKeys || []);
    const groups = (META.stakeholderRoleGroups && META.stakeholderRoleGroups.length)
      ? META.stakeholderRoleGroups
      : [{ label: "", roles: META.stakeholderRoles }];
    return groups.map((g) => `
      <div class="mt-2">
        ${g.label ? `<p class="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">${esc(g.label)}</p>` : ""}
        <div class="grid grid-cols-2 gap-2">
          ${g.roles.map((r) => `
            <label class="flex items-center gap-2 text-sm text-slate-300 surface-2 border border-slate-700 rounded-lg px-2.5 py-1.5 cursor-pointer hover:border-brand-500/60">
              <input type="checkbox" name="${name}" value="${r.key}" ${sel.has(r.key) ? "checked" : ""} class="rounded border-slate-600 bg-slate-800 text-brand-500 focus:ring-brand-500" />
              ${esc(r.label)}
            </label>`).join("")}
        </div>
      </div>`).join("");
  }

  const MODALS = {
    project: () => `
      <form onsubmit="OPS.submitProject(event)">
        ${head("New Epic")}
        ${field("Epic name", "name", "required placeholder='e.g. Venue & Logistics'")}
        ${area("Description", "description")}
        <label class="block mb-3">
          <span class="text-xs font-semibold text-slate-400">Owner / Scrum Master</span>
          <select name="owner_id" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">${userOptions(null)}</select>
        </label>
        ${footer("Create epic")}
      </form>`,

    // ----- Docs (workspace knowledge base) --------------------------------
    docs: () => {
      const rows = state.docs.length
        ? state.docs.map((d) => `
          <div class="flex items-center justify-between gap-3 rounded-xl surface-2 border border-slate-700 px-4 py-3">
            <button onclick="OPS.openDoc(${d.id})" class="min-w-0 flex-1 text-left group">
              <p class="text-sm font-semibold text-slate-100 truncate group-hover:text-brand-200">${esc(d.title)}</p>
              <p class="text-[11px] text-slate-500 mt-0.5">Updated ${d.updated_at ? esc(new Date(d.updated_at).toLocaleString()) : "\u2014"}${d.author ? " \u00b7 " + esc(d.author.display_name) : ""}</p>
            </button>
            <div class="flex items-center gap-1 shrink-0">
              <button onclick="OPS.openDoc(${d.id})" class="px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-300 hover:bg-slate-800/70 border border-slate-700">Open</button>
              <button onclick="OPS.deleteDoc(${d.id})" class="px-2.5 py-1.5 rounded-lg text-xs font-medium text-rose-300 hover:bg-rose-500/10 border border-rose-500/30">Delete</button>
            </div>
          </div>`).join("")
        : `<p class="text-sm text-slate-500 py-6 text-center">No docs yet. Create one to capture important information.</p>`;
      return `
        ${head("Docs", "Important reference documents for the team.")}
        <div class="space-y-2 mb-5">${rows}</div>
        <div class="flex justify-end gap-2 pt-4 border-t border-slate-800">
          <button type="button" onclick="OPS.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Done</button>
          <button type="button" onclick="OPS.newDoc()" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">+ New doc</button>
        </div>`;
    },

    docEdit: (id) => {
      const doc = id != null ? state.docs.find((d) => d.id === id) : null;
      const isEdit = !!doc;
      return `
        <form onsubmit="OPS.submitDoc(event)">
          ${head(isEdit ? "Edit doc" : "New doc", isEdit ? "Update this document." : "Capture an important document in rich text.")}
          ${field("Title", "title", `required value="${doc ? esc(doc.title) : ""}" placeholder='e.g. Event-day runbook'`)}
          <label class="block mb-3">
            <span class="text-xs font-semibold text-slate-400">Content</span>
            <div class="mt-1"><div id="doc-editor"></div></div>
          </label>
          <div class="flex items-center justify-between gap-2 mt-5">
            <div>${isEdit ? `<button type="button" onclick="OPS.deleteDoc(${doc.id})" class="px-4 py-2 rounded-lg text-sm font-medium text-rose-300 hover:bg-rose-500/10 border border-rose-500/30">Delete</button>` : ""}</div>
            <div class="flex gap-2">
              <button type="button" onclick="OPS.openModal('docs')" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Back</button>
              <button type="submit" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">${isEdit ? "Save" : "Create"}</button>
            </div>
          </div>
        </form>`;
    },

    // ----- Team management ------------------------------------------------
    team: () => {
      const admin = isAdmin();
      const rows = state.users.length
        ? state.users.map((u) => (admin && editingUserId === u.id ? userEditRow(u) : userViewRow(u))).join("")
        : `<p class="text-sm text-slate-500 py-4 text-center">No team members yet.</p>`;
      const inviteBlock = admin ? `
        <div class="pt-4 border-t border-slate-800">
          <p class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-3">Invite member</p>
          <form onsubmit="OPS.submitInvite(event)">
            <div class="grid grid-cols-2 gap-3">
              ${field("Email", "email", "required placeholder='member@letstechclub.org'", "email")}
              <label class="block mb-3">
                <span class="text-xs font-semibold text-slate-400">Role</span>
                <select name="role" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">
                  ${META.userRoles.map((r) => `<option value="${r.key}" ${r.key === "MEMBER" ? "selected" : ""}>${esc(r.label)}</option>`).join("")}
                </select>
              </label>
            </div>
            <label class="flex items-center gap-2 mb-3 text-sm text-slate-300">
              <input type="checkbox" name="is_scrum_master" class="rounded border-slate-600 bg-slate-800 text-brand-500 focus:ring-brand-500" />
              Scrum Master (receives escalations)
            </label>
            <div class="flex justify-end gap-2">
              <button type="button" onclick="OPS.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Done</button>
              <button type="submit" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">Send invite</button>
            </div>
          </form>
        </div>`
        : `<p class="text-[11px] text-slate-500 pt-4 border-t border-slate-800">Only admins can invite or remove members.</p>`;
      return `${head("Team", admin ? "Invite members, assign roles, manage access." : "Your hackathon organizing team.")}
        <div class="space-y-2 mb-5">${rows}</div>${inviteBlock}`;
    },

    sprintManage: () => {
      const p = currentProject();
      const rows = p.sprints.length
        ? p.sprints.map((s) => (editingSprintId === s.id ? sprintEditRow(s) : sprintViewRow(s))).join("")
        : `<p class="text-sm text-slate-500 py-4 text-center">No sprints yet.</p>`;
      return `
        ${head("Sprints", "Group milestones into phases. Only one sprint can be active at a time.")}
        <div class="space-y-2 mb-5">${rows}</div>
        <div class="pt-4 border-t border-slate-800">
          <p class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-3">New sprint</p>
          <form onsubmit="OPS.submitSprint(event)">
            ${field("Sprint name", "name", "required placeholder='Phase 1: Venue Freeze'")}
            ${area("Goal", "goal")}
            <div class="grid grid-cols-2 gap-3">
              ${field("Start date", "start_date", "", "date")}
              ${field("End date", "end_date", "", "date")}
            </div>
            <div class="flex justify-end gap-2 mt-2">
              <button type="button" onclick="OPS.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Done</button>
              <button type="submit" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">Create sprint</button>
            </div>
          </form>
        </div>`;
    },

    epicEdit: () => {
      const p = currentProject();
      if (!p) return `<p class="text-sm text-slate-400">No epic selected.</p>`;
      return `
        <form onsubmit="OPS.updateEpic(event, ${p.id})">
          ${head("Epic settings")}
          ${field("Epic name", "name", `required value="${esc(p.name)}"`)}
          <label class="block mb-3">
            <span class="text-xs font-semibold text-slate-400">Description</span>
            <textarea name="description" rows="2" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">${esc(p.description || "")}</textarea>
          </label>
          <label class="block mb-3">
            <span class="text-xs font-semibold text-slate-400">Owner / Scrum Master</span>
            <select name="owner_id" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">${userOptions(p.owner_id)}</select>
          </label>
          <div class="flex items-center justify-between mt-5 pt-4 border-t border-slate-800">
            <button type="button" onclick="OPS.deleteEpic(${p.id})" class="text-sm font-medium text-rose-400 hover:text-rose-300">Delete epic</button>
            <div class="flex gap-2">
              <button type="button" onclick="OPS.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Cancel</button>
              <button type="submit" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">Save</button>
            </div>
          </div>
        </form>`;
    },

    // ----- Stakeholder management -----------------------------------------
    manageStakeholders: () => {
      const p = currentProject();
      const list = p.stakeholders.length
        ? p.stakeholders.map((s) => (editingStakeholderId === s.id ? stakeholderEditRow(s) : stakeholderViewRow(s))).join("")
        : `<p class="text-sm text-slate-500 py-4 text-center">No stakeholders registered yet.</p>`;
      return `
        ${head("Stakeholder Matrix", "Sponsors, judges, mentors, speakers and guests. One stakeholder can hold multiple roles.")}
        <div class="space-y-2 mb-5">${list}</div>
        <div class="flex justify-end gap-2 pt-4 border-t border-slate-800">
          <button type="button" onclick="OPS.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Done</button>
          <button type="button" onclick="OPS.openModal('stakeholderForm')" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">+ Add stakeholder</button>
        </div>`;
    },

    // ----- Stakeholder registration (own modal) ---------------------------
    stakeholderForm: () => {
      return `
        <form onsubmit="OPS.submitStakeholder(event)">
          ${head("Add stakeholder", "Add a sponsor, judge, mentor, speaker or guest. One stakeholder can hold multiple roles.")}
          <div class="grid grid-cols-2 gap-3">
            ${field("Name", "name", "required placeholder='AYA Bank / Dr. Thiri'")}
            ${field("Organization", "organization", "placeholder='Company / Institution'")}
          </div>
          <span class="text-xs font-semibold text-slate-400">Roles</span>
          ${roleCheckboxes("roles", [])}
          <div class="grid grid-cols-3 gap-3 mt-3">
            <label class="block">
              <span class="text-xs font-semibold text-slate-400">Status</span>
              <select name="status" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-2 py-2 text-sm text-slate-100">
                ${META.stakeholderStatuses.map((s) => `<option value="${s.key}">${esc(s.label)}</option>`).join("")}
              </select>
            </label>
            ${field("Contact email", "contact_email", "", "email")}
            ${field("Contact phone", "contact_phone")}
          </div>
          ${area("Notes", "notes")}
          <div class="flex justify-between gap-2 mt-2">
            <button type="button" onclick="OPS.openModal('manageStakeholders')" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Back</button>
            <button type="submit" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">Register</button>
          </div>
        </form>`;
    },

    task: () => {
      const p = currentProject();
      return `
      <form onsubmit="OPS.submitTask(event)">
        ${head("New Task")}
        ${field("Title", "title", "required placeholder='Confirm main stage power supply'")}
        <div class="mb-3">
          <span class="text-xs font-semibold text-slate-400">Description</span>
          <div id="ct-editor" class="mt-1 rounded-lg border border-slate-700 overflow-hidden"></div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <label class="block mb-3">
            <span class="text-xs font-semibold text-slate-400">Sprint</span>
            <select name="sprint_id" required class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">
              ${p.sprints.map((s) => `<option value="${s.id}" ${s.id === state.currentSprintId ? "selected" : ""}>${esc(s.name)}</option>`).join("")}
            </select>
          </label>
          <label class="block mb-3">
            <span class="text-xs font-semibold text-slate-400">Priority</span>
            <select name="priority" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">
              <option value="1">High</option><option value="2" selected>Medium</option><option value="3">Low</option>
            </select>
          </label>
        </div>
        <div class="grid grid-cols-2 gap-3">
          ${assigneePickerMarkup("ct", "Assignees", "Click members to add/remove. First selected becomes primary assignee.")}
          <label class="block mb-3">
            <span class="text-xs font-semibold text-slate-400">Stakeholder</span>
            <select name="stakeholder_id" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">
              <option value="">— none —</option>
              ${p.stakeholders.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}
            </select>
          </label>
        </div>
        ${footer("Create task")}
      </form>`;
    },

    taskDetail: (id) => {
      const found = findTask(id);
      if (!found) return `<p class="text-sm text-slate-400">Task not found.</p>`;
      const { task: t, sprint, project: p } = found;
      return `
        <div class="flex items-start justify-between gap-3 mb-1">
          <input id="td-title" value="${esc(t.title)}"
            class="flex-1 text-lg font-bold text-white rounded-lg px-2 py-1 -ml-2 bg-transparent hover:bg-slate-800/50 focus:bg-slate-900 focus:ring-2 focus:ring-brand-500 outline-none border border-transparent focus:border-brand-500" />
          <button onclick="OPS.closeModal()" class="text-slate-500 hover:text-slate-200 text-xl leading-none px-1">&times;</button>
        </div>
        <p class="text-xs text-slate-500 mb-4">${esc(p.name)} · ${esc(sprint.name)}</p>

        <div class="grid grid-cols-3 gap-3 mb-5">
          <label class="block">
            <span class="text-[11px] font-semibold text-slate-400">Status</span>
            <select onchange="OPS.detailSetState(${t.id}, this.value)" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100">
              ${META.taskStates.map((s) => `<option value="${s.key}" ${s.key === t.state_key ? "selected" : ""}>${esc(s.label)}</option>`).join("")}
            </select>
          </label>
          ${assigneePickerMarkup("td", "Assignees", assigneeSummary(t))}
          <label class="block">
            <span class="text-[11px] font-semibold text-slate-400">Stakeholder</span>
            <select onchange="OPS.detailLink(${t.id}, this.value)" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100">
              <option value="">— none —</option>
              ${p.stakeholders.map((s) => `<option value="${s.id}" ${s.id === t.stakeholder_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}
            </select>
          </label>
        </div>

        <div class="flex items-center gap-2 mb-3">
          <label class="flex items-center gap-2">
            <span class="text-[11px] font-semibold text-slate-400">Priority</span>
            <select id="td-priority" class="rounded-lg surface-2 border border-slate-700 px-2 py-1 text-sm text-slate-100">
              ${[1,2,3].map((n) => `<option value="${n}" ${n === t.priority ? "selected" : ""}>${PRIORITY_LABEL[n]}</option>`).join("")}
            </select>
          </label>
          <button onclick="OPS.toggleBlock(${t.id}, ${t.is_blocked}); OPS.closeModal();"
            class="ml-auto text-xs font-semibold px-3 py-1.5 rounded-lg ${t.is_blocked ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300"} hover:opacity-80">
            ${t.is_blocked ? "Unblock task" : "Flag blocked"}
          </button>
        </div>
        ${t.is_blocked ? `<div class="mb-3 text-xs font-semibold text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-lg px-3 py-2">⚠ Blocked${t.blocked_reason ? ": " + esc(t.blocked_reason) : ""}</div>` : ""}

        <div class="mb-2 flex items-center justify-between">
          <span class="text-[11px] font-bold uppercase tracking-wider text-slate-500">Description</span>
          <span class="text-[11px] text-slate-600">Rich text editor</span>
        </div>
        <div id="td-editor" class="rounded-xl border border-slate-700 overflow-hidden"></div>

        <div class="flex items-center justify-between mt-5 pt-4 border-t border-slate-800">
          <button onclick="OPS.deleteTask(${t.id})" class="text-sm font-medium text-rose-400 hover:text-rose-300">Delete task</button>
          <div class="flex gap-2">
            <button onclick="OPS.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Close</button>
            <button onclick="OPS.saveTaskDetail(${t.id})" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">Save</button>
          </div>
        </div>`;
    },
  };

  // ----- Team row renderers ------------------------------------------------
  function userViewRow(u) {
    const admin = isAdmin();
    const isSelf = state.me && u.id === state.me.id;
    return `
      <div class="flex items-center justify-between rounded-xl border border-slate-800 surface-2 px-3 py-2.5">
        <div class="flex items-center gap-3 min-w-0">
          <span class="h-8 w-8 rounded-full bg-brand-500 text-white text-[11px] font-bold flex items-center justify-center shrink-0">${esc(initials(u.display_name))}</span>
          <div class="min-w-0">
            <p class="text-sm font-semibold text-slate-100 truncate">
              ${esc(u.display_name)}
              <span class="text-[10px] font-bold ${u.is_admin ? "text-brand-200 bg-brand-500/20" : "text-slate-400 bg-slate-700"} rounded px-1.5 py-0.5 ml-1 uppercase">${esc(u.role)}</span>
              <span class="text-[10px] font-bold ${USER_STATUS_BADGE[u.status] || "bg-slate-700 text-slate-300"} rounded px-1.5 py-0.5 ml-1 uppercase">${esc(u.status)}</span>
            </p>
            <p class="text-xs text-slate-500 truncate">${esc(u.email)}${u.is_scrum_master ? " · scrum master" : ""}</p>
          </div>
        </div>
        ${admin ? `
        <div class="flex items-center gap-1 shrink-0">
          <button onclick="OPS.startEditUser(${u.id})" class="text-xs text-slate-400 hover:text-brand-200 px-2 py-1">Edit</button>
          ${isSelf ? "" : `<button onclick="OPS.deleteUser(${u.id})" class="text-xs text-rose-400 hover:text-rose-300 px-2 py-1">Remove</button>`}
        </div>` : ""}
      </div>`;
  }

  function userEditRow(u) {
    return `
      <form onsubmit="OPS.saveUser(event, ${u.id})" class="rounded-xl border border-brand-500/50 bg-brand-500/5 px-3 py-3">
        <p class="text-sm font-semibold text-slate-100 mb-2">${esc(u.display_name)} <span class="text-xs text-slate-500">${esc(u.email)}</span></p>
        <div class="grid grid-cols-2 gap-2 mb-2">
          <label class="block">
            <span class="text-[11px] text-slate-400">Role</span>
            <select name="role" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100">
              ${META.userRoles.map((r) => `<option value="${r.key}" ${r.label.toLowerCase() === u.role ? "selected" : ""}>${esc(r.label)}</option>`).join("")}
            </select>
          </label>
          <label class="block">
            <span class="text-[11px] text-slate-400">Status</span>
            <select name="status" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100">
              ${["active","invited","disabled"].map((s) => `<option value="${s}" ${s === u.status ? "selected" : ""}>${s[0].toUpperCase()+s.slice(1)}</option>`).join("")}
            </select>
          </label>
        </div>
        <label class="flex items-center gap-2 text-sm text-slate-300 mb-2">
          <input type="checkbox" name="is_scrum_master" ${u.is_scrum_master ? "checked" : ""} class="rounded border-slate-600 bg-slate-800 text-brand-500" /> Scrum Master
        </label>
        <div class="flex justify-end gap-2">
          <button type="button" onclick="OPS.cancelEdit()" class="text-xs font-medium text-slate-400 px-3 py-1.5 hover:bg-slate-800/70 rounded-lg">Cancel</button>
          <button type="submit" class="text-xs font-semibold text-white bg-brand-500 px-3 py-1.5 rounded-lg hover:bg-brand-400">Save</button>
        </div>
      </form>`;
  }

  // ----- Stakeholder row renderers -----------------------------------------
  function stakeholderViewRow(s) {
    const tags = s.roles.map((r) => `<span class="text-[10px] font-semibold text-brand-200 bg-brand-500/15 rounded px-1.5 py-0.5">${esc(r.label)}</span>`).join(" ");
    return `
      <div class="flex items-center justify-between rounded-xl border border-slate-800 surface-2 px-3 py-2.5">
        <div class="min-w-0">
          <p class="text-sm font-semibold text-slate-100 truncate">
            ${esc(s.name)}
            <span class="text-[10px] font-bold ${STATUS_BADGE[s.status_key] || "bg-slate-700 text-slate-300"} rounded px-1.5 py-0.5 ml-1 uppercase">${esc(s.status)}</span>
          </p>
          <div class="flex flex-wrap items-center gap-1 mt-1">${tags || `<span class="text-[11px] text-slate-600">no roles</span>`}</div>
          <p class="text-xs text-slate-500 truncate mt-1">${esc(s.organization || s.contact_email || "—")} · ${s.open_task_count} open</p>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          <button onclick="OPS.startEditStakeholder(${s.id})" class="text-xs text-slate-400 hover:text-brand-200 px-2 py-1">Edit</button>
          <button onclick="OPS.deleteStakeholder(${s.id})" class="text-xs text-rose-400 hover:text-rose-300 px-2 py-1">Delete</button>
        </div>
      </div>`;
  }

  function stakeholderEditRow(s) {
    return `
      <form onsubmit="OPS.saveStakeholder(event, ${s.id})" class="rounded-xl border border-brand-500/50 bg-brand-500/5 px-3 py-3">
        <div class="grid grid-cols-2 gap-2 mb-2">
          <input name="name" value="${esc(s.name)}" required class="rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" />
          <input name="organization" value="${esc(s.organization || "")}" placeholder="organization" class="rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" />
        </div>
        <span class="text-[11px] text-slate-400">Roles</span>
        ${roleCheckboxes("roles", s.role_keys)}
        <div class="grid grid-cols-3 gap-2 mt-2 mb-2">
          <select name="status" class="rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100">
            ${META.stakeholderStatuses.map((st) => `<option value="${st.key}" ${st.key === s.status_key ? "selected" : ""}>${esc(st.label)}</option>`).join("")}
          </select>
          <input name="contact_email" type="email" value="${esc(s.contact_email || "")}" placeholder="email" class="rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" />
          <input name="contact_phone" value="${esc(s.contact_phone || "")}" placeholder="phone" class="rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" />
        </div>
        <div class="flex justify-end gap-2">
          <button type="button" onclick="OPS.cancelEdit()" class="text-xs font-medium text-slate-400 px-3 py-1.5 hover:bg-slate-800/70 rounded-lg">Cancel</button>
          <button type="submit" class="text-xs font-semibold text-white bg-brand-500 px-3 py-1.5 rounded-lg hover:bg-brand-400">Save</button>
        </div>
      </form>`;
  }

  // ----- Sprint row renderers ----------------------------------------------
  function sprintViewRow(s) {
    return `
      <div draggable="true"
           ondragstart="OPS.sprintDragStart(event,${s.id})" ondragend="OPS.sprintDragEnd(event)"
           ondragover="OPS.sprintDragOver(event)" ondragleave="OPS.sprintDragLeave(event)" ondrop="OPS.sprintDrop(event,${s.id})"
           class="rounded-xl border border-slate-800 surface-2 px-3 py-2.5 cursor-move">
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2 min-w-0">
            <span class="text-slate-600 select-none shrink-0" title="Drag to reorder">&#x2807;</span>
            <div class="min-w-0">
              <p class="text-sm font-semibold text-slate-100 truncate">
                ${esc(s.name)}
              </p>
              <p class="text-xs text-slate-500 truncate">${s.task_count} task${s.task_count === 1 ? "" : "s"}${s.start_date ? ` · ${esc(s.start_date)} → ${esc(s.end_date || "?")}` : ""}</p>
            </div>
          </div>
          <div class="flex items-center gap-1 shrink-0">
            <button onclick="OPS.startEditSprint(${s.id})" class="text-xs text-slate-400 hover:text-brand-200 px-2 py-1">Edit</button>
            <button onclick="OPS.deleteSprint(${s.id})" class="text-xs text-rose-400 hover:text-rose-300 px-2 py-1">Delete</button>
          </div>
        </div>
      </div>`;
  }

  function sprintEditRow(s) {
    return `
      <form onsubmit="OPS.saveSprint(event, ${s.id})" class="rounded-xl border border-brand-500/50 bg-brand-500/5 px-3 py-3">
        <input name="name" value="${esc(s.name)}" required class="w-full rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100 mb-2" />
        <textarea name="goal" rows="2" placeholder="Goal" class="w-full rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100 mb-2">${esc(s.goal || "")}</textarea>
        <div class="grid grid-cols-2 gap-2 mb-2">
          <input name="start_date" type="date" value="${s.start_date || ""}" class="rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" />
          <input name="end_date" type="date" value="${s.end_date || ""}" class="rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-sm text-slate-100" />
        </div>
        <div class="flex justify-end gap-2">
          <button type="button" onclick="OPS.cancelEditSprint()" class="text-xs font-medium text-slate-400 px-3 py-1.5 hover:bg-slate-800/70 rounded-lg">Cancel</button>
          <button type="submit" class="text-xs font-semibold text-white bg-brand-500 px-3 py-1.5 rounded-lg hover:bg-brand-400">Save</button>
        </div>
      </form>`;
  }

  // ======================= OVERVIEW (Mission Control) =====================
  const EVENT_DATE = new Date("2026-07-17T00:00:00");
  const STATUS_SELECT_CLASS = {
    PENDING: "surface-2 border-amber-500/40 text-amber-300",
    CONFIRMED: "surface-2 border-emerald-500/40 text-emerald-300",
    REJECTED: "surface-2 border-rose-500/40 text-rose-300",
  };

  function daysToEvent() {
    const ms = EVENT_DATE - new Date();
    return Math.ceil(ms / 86400000);
  }
  function stakeholdersInRoles(p, roleKeys) {
    const want = new Set(roleKeys);
    return p.stakeholders.filter((s) => s.role_keys.some((k) => want.has(k)));
  }
  function statusSelect(s) {
    return `<select onchange="OPS.setStakeholderStatus(${s.id}, this.value)"
      class="text-xs rounded-md border px-2 py-1 ${STATUS_SELECT_CLASS[s.status_key] || "surface-2 border-slate-700 text-slate-300"}">
      ${META.stakeholderStatuses.map((st) => `<option value="${st.key}" ${st.key === s.status_key ? "selected" : ""}>${esc(st.label)}</option>`).join("")}
    </select>`;
  }
  function progressBar(done, total, color = "bg-brand-500") {
    const pct = total ? Math.round((done / total) * 100) : 0;
    return `<div class="h-2 rounded-full bg-slate-800 overflow-hidden"><div class="h-full ${color}" style="width:${pct}%"></div></div>`;
  }
  function overviewStakeholderCard(s) {
    const tags = s.roles.map((r) => `<span class="text-[10px] font-semibold text-brand-200 bg-brand-500/15 rounded px-1.5 py-0.5">${esc(r.label)}</span>`).join(" ");
    return `
      <div class="rounded-xl border border-slate-800 surface-2 p-3">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="text-sm font-semibold text-slate-100 truncate">${esc(s.name)}</p>
            ${s.organization ? `<p class="text-[11px] text-slate-500 truncate">${esc(s.organization)}</p>` : ""}
          </div>
          ${statusSelect(s)}
        </div>
        <div class="flex flex-wrap gap-1 mt-2">${tags || `<span class="text-[11px] text-slate-600">no roles</span>`}</div>
        <div class="flex items-center justify-between mt-2">
          <span class="text-[11px] text-slate-500 truncate">${s.contact_email ? esc(s.contact_email) : "no contact"}${s.open_task_count ? ` · ${s.open_task_count} open` : ""}</span>
          <button onclick="OPS.startEditStakeholder(${s.id})" class="text-[11px] text-slate-400 hover:text-brand-200 shrink-0">Edit</button>
        </div>
      </div>`;
  }
  function statCard(label, value, sub, accent) {
    return `
      <div class="surface border rounded-2xl p-4">
        <p class="text-[11px] font-bold uppercase tracking-wider text-slate-500">${esc(label)}</p>
        <p class="text-2xl font-extrabold ${accent || "text-white"} mt-1">${value}</p>
        <p class="text-[11px] text-slate-500 mt-0.5">${sub || ""}</p>
      </div>`;
  }
  function rolePanel(p, group, withProgress) {
    const list = stakeholdersInRoles(p, group.roles.map((r) => r.key));
    const confirmed = list.filter((s) => s.status_key === "CONFIRMED").length;
    const pending = list.filter((s) => s.status_key === "PENDING").length;
    return `
      <div class="surface border rounded-2xl p-4">
        <div class="flex items-center justify-between mb-3">
          <h4 class="text-sm font-bold text-white">${esc(group.label)}</h4>
          <span class="text-[11px] text-slate-500">${confirmed} confirmed · ${pending} pending</span>
        </div>
        ${withProgress ? `<div class="mb-3">${progressBar(confirmed, list.length, "bg-emerald-500")}<p class="text-[11px] text-slate-500 mt-1">${confirmed} of ${list.length || 0} secured</p></div>` : ""}
        <div class="grid grid-cols-1 gap-2">
          ${list.length ? list.map(overviewStakeholderCard).join("") : `<p class="text-xs text-slate-600 text-center py-3">None yet</p>`}
        </div>
      </div>`;
  }

  function renderOverview(p) {
    const host = document.getElementById("overview-view");
    const allTasks = p.sprints.flatMap((s) => s.tasks);
    const total = allTasks.length;
    const done = allTasks.filter((t) => t.state_key === "DONE").length;
    const blocked = allTasks.filter((t) => t.is_blocked);
    const essential = stakeholdersInRoles(p, ["MAIN_SPONSOR", "VENUE_SPONSOR"]);
    const essentialConfirmed = essential.filter((s) => s.status_key === "CONFIRMED").length;
    const d = daysToEvent();

    const groups = META.stakeholderRoleGroups || [];
    const sponsorGroups = groups.filter((g) => g.key === "ESSENTIAL_SPONSORS" || g.key === "SUPPORTING_SPONSORS");
    const programGroups = groups.filter((g) => g.key !== "ESSENTIAL_SPONSORS" && g.key !== "SUPPORTING_SPONSORS");

    host.innerHTML = `
      <div class="max-w-6xl mx-auto space-y-6">
        <!-- Stat row -->
        <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
          ${statCard("Days to event", d >= 0 ? d : "—", d >= 0 ? "Jul 17, 2026" : "Event passed", d <= 14 ? "text-amber-300" : "text-white")}
          ${statCard("Task progress", `${total ? Math.round((done / total) * 100) : 0}%`, `${done}/${total} done`, "text-brand-300")}
          ${statCard("Essential sponsors", `${essentialConfirmed}/${essential.length}`, "confirmed (must-have)", essentialConfirmed >= essential.length && essential.length ? "text-emerald-300" : "text-amber-300")}
          ${statCard("Roadblocks", blocked.length, blocked.length ? "need attention" : "all clear", blocked.length ? "text-rose-300" : "text-emerald-300")}
          ${statCard("Phases", p.sprints.length, p.sprints.length === 1 ? "sprint" : "sprints", "text-white")}
        </div>

        <!-- Sponsorship -->
        <div>
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-bold uppercase tracking-wider text-slate-400">Sponsorship</h3>
            <button onclick="OPS.openModal('manageStakeholders')" class="text-xs font-semibold text-brand-300 hover:text-brand-200">+ Add partner</button>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            ${sponsorGroups.map((g) => rolePanel(p, g, true)).join("")}
          </div>
        </div>

        <!-- Program & guests -->
        <div>
          <h3 class="text-sm font-bold uppercase tracking-wider text-slate-400 mb-3">Program & Guests</h3>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            ${programGroups.map((g) => rolePanel(p, g, false)).join("")}
          </div>
        </div>

        <!-- Phases + roadblocks -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div class="surface border rounded-2xl p-4">
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-sm font-bold text-white">Phase progress</h3>
              <button onclick="OPS.openModal('sprintManage')" class="text-xs font-semibold text-brand-300 hover:text-brand-200">Manage</button>
            </div>
            <div class="space-y-3">
              ${p.sprints.length ? p.sprints.map((s) => {
                const td = s.tasks.filter((t) => t.state_key === "DONE").length;
                return `
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <span class="text-sm text-slate-200">${esc(s.name)}</span>
                    <span class="text-[11px] text-slate-500">${td}/${s.task_count}</span>
                  </div>
                  ${progressBar(td, s.task_count)}
                </div>`;
              }).join("") : `<p class="text-xs text-slate-600 text-center py-3">No sprints yet</p>`}
            </div>
          </div>

          <div class="surface border rounded-2xl p-4">
            <h3 class="text-sm font-bold text-white mb-3">Roadblocks ${blocked.length ? `<span class='text-[11px] text-rose-300'>(${blocked.length})</span>` : ""}</h3>
            <div class="space-y-2">
              ${blocked.length ? blocked.map((t) => `
                <div class="rounded-xl border border-rose-500/30 bg-rose-500/5 px-3 py-2 flex items-center justify-between gap-2">
                  <div class="min-w-0">
                    <p class="text-sm font-semibold text-slate-100 truncate">${esc(t.title)}</p>
                    <p class="text-[11px] text-rose-300 truncate">${t.blocked_reason ? esc(t.blocked_reason) : "Blocked"}</p>
                  </div>
                  <div class="flex items-center gap-1 shrink-0">
                    <button onclick="OPS.openTask(${t.id})" class="text-[11px] text-slate-400 hover:text-brand-200 px-1">Open</button>
                    <button onclick="OPS.toggleBlock(${t.id}, true)" class="text-[11px] text-emerald-300 hover:underline px-1">Unblock</button>
                  </div>
                </div>`).join("") : `<p class="text-xs text-slate-600 text-center py-3">No blocked tasks. 🎉</p>`}
            </div>
          </div>
        </div>
      </div>`;
  }


  const formData = (e) => {
    const fd = new FormData(e.target);
    const obj = {};
    fd.forEach((v, k) => { if (k !== "roles") obj[k] = v === "" ? null : v; });
    return obj;
  };
  const gatherRoles = (form) =>
    Array.from(form.querySelectorAll('input[name="roles"]:checked')).map((c) => c.value);

  async function submitProject(e) {
    e.preventDefault();
    const d = formData(e);
    if (d.owner_id) d.owner_id = parseInt(d.owner_id, 10);
    try {
      const r = await api("/api/projects", "POST", d);
      toast("Epic created."); await refresh(); selectProject(r.project.id); closeModal();
    } catch (err) { toast(err.message, "err"); }
  }

  // ----- Team CRUD ---------------------------------------------------------
  async function submitInvite(e) {
    e.preventDefault();
    const d = formData(e);
    d.is_scrum_master = !!new FormData(e.target).get("is_scrum_master");
    try {
      await api("/api/users", "POST", d);
      toast("Invitation sent."); await refresh(); openModal("team");
    } catch (err) { toast(err.message, "err"); }
  }
  function startEditUser(id) { editingUserId = id; openModal("team"); }
  function startEditStakeholder(id) { editingStakeholderId = id; openModal("manageStakeholders"); }
  function cancelEdit() {
    const wasUser = editingUserId !== null;
    editingUserId = null; editingStakeholderId = null;
    openModal(wasUser ? "team" : "manageStakeholders");
  }
  async function saveUser(e, id) {
    e.preventDefault();
    const d = formData(e);
    d.is_scrum_master = !!new FormData(e.target).get("is_scrum_master");
    try {
      await api(`/api/users/${id}`, "PATCH", d);
      editingUserId = null; toast("Member updated."); await refresh(); openModal("team");
    } catch (err) { toast(err.message, "err"); }
  }
  async function deleteUser(id) {
    if (!window.confirm("Remove this team member?")) return;
    try { await api(`/api/users/${id}`, "DELETE"); toast("Member removed."); await refresh(); openModal("team"); }
    catch (err) { toast(err.message, "err"); }
  }

  // ----- Stakeholder CRUD --------------------------------------------------
  async function submitStakeholder(e) {
    e.preventDefault();
    const d = formData(e);
    d.roles = gatherRoles(e.target);
    if (!d.roles.length) { toast("Select at least one role.", "err"); return; }
    try {
      await api(`/api/projects/${state.currentProjectId}/stakeholders`, "POST", d);
      toast("Stakeholder added."); await refresh(); openModal("manageStakeholders");
    } catch (err) { toast(err.message, "err"); }
  }
  async function saveStakeholder(e, id) {
    e.preventDefault();
    const d = formData(e);
    d.roles = gatherRoles(e.target);
    if (!d.roles.length) { toast("Select at least one role.", "err"); return; }
    try {
      await api(`/api/stakeholders/${id}`, "PATCH", d);
      editingStakeholderId = null; toast("Stakeholder updated."); await refresh(); openModal("manageStakeholders");
    } catch (err) { toast(err.message, "err"); }
  }
  async function deleteStakeholder(id) {
    if (!window.confirm("Delete this stakeholder? Linked tasks will be unlinked.")) return;
    try { await api(`/api/stakeholders/${id}`, "DELETE"); toast("Stakeholder deleted."); await refresh(); openModal("manageStakeholders"); }
    catch (err) { toast(err.message, "err"); }
  }

  async function submitSprint(e) {
    e.preventDefault();
    const d = formData(e);
    try {
      const r = await api(`/api/projects/${state.currentProjectId}/sprints`, "POST", d);
      toast("Sprint created.");
      await refresh();
      if (!state.currentSprintId && r.sprint) state.currentSprintId = r.sprint.id;
      openModal("sprintManage");
    } catch (err) { toast(err.message, "err"); }
  }

  // ----- Sprint CRUD -------------------------------------------------------
  function startEditSprint(id) { editingSprintId = id; openModal("sprintManage"); }
  function cancelEditSprint() { editingSprintId = null; openModal("sprintManage"); }
  async function saveSprint(e, id) {
    e.preventDefault();
    const d = formData(e);
    try {
      await api(`/api/sprints/${id}`, "PATCH", d);
      editingSprintId = null; toast("Sprint updated."); await refresh(); openModal("sprintManage");
    } catch (err) { toast(err.message, "err"); }
  }
  async function deleteSprint(id) {
    if (!window.confirm("Delete this sprint and all its tasks?")) return;
    try {
      await api(`/api/sprints/${id}`, "DELETE");
      toast("Sprint deleted.");
      if (state.currentSprintId === id) state.currentSprintId = null;
      await refresh();
      const p = currentProject();
      if (p && !state.currentSprintId && p.sprints[0]) state.currentSprintId = p.sprints[0].id;
      openModal("sprintManage");
    } catch (err) { toast(err.message, "err"); }
  }

  // ----- Epic CRUD ---------------------------------------------------------
  async function updateEpic(e, id) {
    e.preventDefault();
    const d = formData(e);
    if (d.owner_id) d.owner_id = parseInt(d.owner_id, 10);
    try {
      await api(`/api/projects/${id}`, "PATCH", d);
      toast("Epic updated."); await refresh(); closeModal();
    } catch (err) { toast(err.message, "err"); }
  }
  async function deleteEpic(id) {
    if (!window.confirm("Delete this epic and ALL its sprints and tasks? This cannot be undone.")) return;
    try {
      await api(`/api/projects/${id}`, "DELETE");
      toast("Epic deleted.");
      closeModal();
      state.currentProjectId = null;
      await refresh();
      if (state.projects.length) selectProject(state.projects[0].id);
    } catch (err) { toast(err.message, "err"); }
  }

  // ----- Stakeholder status (inline from overview) -------------------------
  async function setStakeholderStatus(id, status) {
    try {
      await api(`/api/stakeholders/${id}`, "PATCH", { status });
      toast("Partner status updated."); await refresh();
    } catch (err) { toast(err.message, "err"); }
  }

  async function submitTask(e) {
    e.preventDefault();
    const d = formData(e);
    d.assigned_user_ids = selectedAssigneeIdsFromPicker("ct");
    delete d.assigned_to;
    d.description = getCreateTaskHTML();
    d.sprint_id = parseInt(d.sprint_id, 10);
    d.priority = parseInt(d.priority, 10);
    if (d.stakeholder_id) d.stakeholder_id = parseInt(d.stakeholder_id, 10);
    try { await api(`/api/sprints/${d.sprint_id}/tasks`, "POST", d); toast("Task created."); await refresh(); closeModal(); }
    catch (err) { toast(err.message, "err"); }
  }

  // ----- Task detail handlers ----------------------------------------------
  async function saveTaskDetail(id) {
    const title = document.getElementById("td-title").value.trim();
    const description = getTaskDetailHTML();
    const priority = parseInt(document.getElementById("td-priority").value, 10);
    const assigneeIds = selectedAssigneeIdsFromPicker("td");
    if (!title) { toast("Title cannot be empty.", "err"); return; }
    try {
      await api(`/api/tasks/${id}`, "PATCH", { title, description, priority });
      await api(`/api/tasks/${id}/assign`, "POST", { user_ids: assigneeIds });
      toast("Task saved.");
      await refresh();
      openModal("taskDetail", id);
    }
    catch (err) { toast(err.message, "err"); }
  }
  async function detailSetState(id, stateKey) {
    try { await api(`/api/tasks/${id}/transition`, "POST", { state: stateKey }); toast("Status updated."); await refresh(); openModal("taskDetail", id); }
    catch (err) { toast(err.message, "err"); await refresh(); openModal("taskDetail", id); }
  }
  async function detailLink(id, value) {
    const sid = value === "" ? null : parseInt(value, 10);
    try { await api(`/api/tasks/${id}/stakeholder`, "POST", { stakeholder_id: sid }); toast("Partner link updated."); await refresh(); openModal("taskDetail", id); }
    catch (err) { toast(err.message, "err"); }
  }
  async function deleteTask(id) {
    if (!window.confirm("Delete this task permanently?")) return;
    try { await api(`/api/tasks/${id}`, "DELETE"); toast("Task deleted."); await refresh(); closeModal(); }
    catch (err) { toast(err.message, "err"); }
  }

  // ----- Docs CRUD ---------------------------------------------------------
  function newDoc() { editingDocId = null; openModal("docEdit"); }
  function openDoc(id) { editingDocId = id; openModal("docEdit", id); }
  async function submitDoc(e) {
    e.preventDefault();
    const d = formData(e);
    d.content = getDocHTML();
    if (!d.title) { toast("Title is required.", "err"); return; }
    try {
      if (editingDocId == null) {
        await api("/api/docs", "POST", d);
        toast("Doc created.");
      } else {
        await api(`/api/docs/${editingDocId}`, "PATCH", d);
        toast("Doc saved.");
      }
      editingDocId = null;
      await refresh();
      openModal("docs");
    } catch (err) { toast(err.message, "err"); }
  }
  async function deleteDoc(id) {
    if (!window.confirm("Delete this doc permanently?")) return;
    try { await api(`/api/docs/${id}`, "DELETE"); toast("Doc deleted."); editingDocId = null; await refresh(); openModal("docs"); }
    catch (err) { toast(err.message, "err"); }
  }

  // ===================== PROGRAM SECTIONS =================================
  // Milestones (epic timeline), Participants, Teams, Stakeholders.
  const SECTION_META = {
    milestones: ["Milestones", "Epic-by-epic delivery timeline"],
    participants: ["Participants", "Applications & the selection funnel"],
    teams: ["Teams", "Formed teams & the problems they're tackling"],
    partners: ["Stakeholders", "Stakeholder matrix and portal access"],
  };

  function highlightSectionNav() {
    document.querySelectorAll(".section-btn").forEach((b) => {
      const on = b.getAttribute("data-section") === state.section;
      b.classList.toggle("bg-brand-500/15", on);
      b.classList.toggle("text-brand-200", on);
      b.classList.toggle("text-slate-400", !on);
    });
  }

  function openSection(name) {
    state.section = name;
    renderProjects();      // refresh epic active state (none active now)
    renderMain();
  }

  async function ensureCommunity(force) {
    if (state.community && !force) return state.community;
    state.community = await api("/api/community");
    return state.community;
  }
  async function refreshCommunity() {
    await ensureCommunity(true);
    if (state.section) renderProgramSection();
  }

  function renderProgramSection() {
    const epicActions = document.getElementById("epic-actions");
    if (epicActions) epicActions.classList.add("hidden");
    const gear = document.getElementById("epic-edit-btn");
    if (gear) gear.classList.add("hidden");
    document.getElementById("board-controls").classList.add("hidden");
    document.getElementById("board-view").classList.add("hidden");
    document.getElementById("overview-view").classList.add("hidden");
    const blocked = document.getElementById("blocked-banner");
    blocked.classList.add("hidden"); blocked.classList.remove("flex");
    const host = document.getElementById("program-view");
    host.classList.remove("hidden");

    const [t, sub] = SECTION_META[state.section] || ["", ""];
    document.getElementById("project-title").textContent = t;
    document.getElementById("project-subtitle").textContent = sub;

    if (state.section === "milestones") return renderMilestones(host);

    if (!state.community) {
      host.innerHTML = `<div class="text-center text-slate-500 py-16 text-sm">Loading…</div>`;
      ensureCommunity().then(() => { if (state.section && state.section !== "milestones") renderProgramSection(); })
        .catch((err) => { host.innerHTML = `<p class="text-rose-300 text-sm">${esc(err.message)}</p>`; });
      return;
    }
    if (state.section === "participants") return renderParticipants(host);
    if (state.section === "teams") return renderTeams(host);
    if (state.section === "partners") return renderPartners(host);
  }

  // ----- Milestones (derived from epics + sprints + tasks) -----------------
  function milestoneStats(p) {
    const tasks = p.sprints.reduce((acc, s) => acc.concat(s.tasks), []);
    const total = tasks.length;
    const done = tasks.filter((t) => t.state_key === "DONE").length;
    const inProgress = tasks.filter((t) => t.state_key === "IN_PROGRESS").length;
    const blocked = tasks.filter((t) => t.is_blocked).length;
    const pct = total ? Math.round((done / total) * 100) : 0;
    return { total, done, inProgress, blocked, pct };
  }

  function renderMilestones(host) {
    if (!state.projects.length) {
      host.innerHTML = `<p class="text-sm text-slate-500 text-center py-16">No epics yet. Create one to populate the timeline.</p>`;
      return;
    }

    const all = state.projects.map(milestoneStats);
    const totals = all.reduce((a, s) => ({ total: a.total + s.total, done: a.done + s.done, blocked: a.blocked + s.blocked }), { total: 0, done: 0, blocked: 0 });
    const overall = totals.total ? Math.round((totals.done / totals.total) * 100) : 0;
    const completeMilestones = all.filter((s) => s.total > 0 && s.pct === 100).length;
    const activeMilestones = all.filter((s) => s.inProgress > 0).length;

    const stageMeta = (s) => {
      if (s.total > 0 && s.pct === 100) {
        return {
          label: "Complete",
          badge: "text-emerald-300 bg-emerald-500/15 border-emerald-500/30",
          dot: "bg-emerald-500",
          bar: "bg-emerald-500",
          pct: "text-emerald-300",
        };
      }
      if (s.inProgress > 0 || s.done > 0) {
        return {
          label: "Active",
          badge: "text-brand-200 bg-brand-500/15 border-brand-500/30",
          dot: "bg-brand-500",
          bar: "bg-brand-500",
          pct: "text-brand-200",
        };
      }
      return {
        label: "Planned",
        badge: "text-slate-300 bg-slate-700/40 border-slate-600/40",
        dot: "bg-slate-500",
        bar: "bg-slate-600",
        pct: "text-slate-300",
      };
    };

    const rows = state.projects.map((p, i) => {
      const s = all[i];
      const m = stageMeta(s);
      const ownerText = p.owner ? p.owner.display_name : "No owner";
      const sprintText = `${p.sprints.length} sprint${p.sprints.length === 1 ? "" : "s"}`;
      return `
        <li>
          <button onclick="OPS.gotoEpic(${p.id})" class="group w-full text-left px-4 py-3.5 hover:bg-slate-900/50 transition">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="h-2 w-2 rounded-full ${m.dot}"></span>
                  <p class="text-sm font-semibold text-slate-100 group-hover:text-brand-200 truncate">${esc(p.name)}</p>
                  <span class="text-[10px] font-semibold border rounded-full px-2 py-0.5 ${m.badge}">${m.label}</span>
                </div>
                <p class="text-[11px] text-slate-500 mt-0.5">${sprintText} · Owner: ${esc(ownerText)}</p>
                <div class="mt-2 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                  <div class="h-full ${m.bar} rounded-full" style="width:${s.pct}%"></div>
                </div>
                <div class="mt-2 flex items-center gap-3 text-[11px]">
                  <span class="text-slate-400">${s.done}/${s.total} tasks done</span>
                  <span class="text-slate-400">${s.inProgress} in progress</span>
                  ${s.blocked ? `<span class="text-rose-300 font-semibold">${s.blocked} blocked</span>` : `<span class="text-emerald-300/80">No blockers</span>`}
                </div>
              </div>
              <div class="text-right shrink-0">
                <p class="text-lg font-bold ${m.pct}">${s.pct}%</p>
                <p class="text-[11px] text-slate-500">progress</p>
              </div>
            </div>
          </button>
        </li>`;
    }).join("");

    host.innerHTML = `
      <div class="max-w-5xl">
        <div class="mb-4">
          <div class="flex items-center justify-between gap-3 flex-wrap">
            <p class="text-sm font-bold text-white">Overall program progress</p>
            <p class="text-sm font-bold text-brand-200">${overall}%</p>
          </div>
          <div class="mt-2 h-2 rounded-full bg-slate-800 overflow-hidden">
            <div class="h-full bg-brand-500 rounded-full" style="width:${overall}%"></div>
          </div>
          <div class="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
            <span class="rounded-full border border-slate-700 px-2 py-0.5 text-slate-400">${state.projects.length} milestone${state.projects.length === 1 ? "" : "s"}</span>
            <span class="rounded-full border border-slate-700 px-2 py-0.5 text-slate-400">${totals.done}/${totals.total} tasks complete</span>
            <span class="rounded-full border px-2 py-0.5 ${completeMilestones ? "border-emerald-500/30 text-emerald-300" : "border-slate-700 text-slate-400"}">${completeMilestones} complete</span>
            <span class="rounded-full border px-2 py-0.5 ${activeMilestones ? "border-brand-500/30 text-brand-200" : "border-slate-700 text-slate-400"}">${activeMilestones} active</span>
            <span class="rounded-full border px-2 py-0.5 ${totals.blocked ? "border-rose-500/30 text-rose-300" : "border-emerald-500/30 text-emerald-300/80"}">${totals.blocked ? `${totals.blocked} blocked` : "No blockers"}</span>
          </div>
        </div>

        <ol class="border border-slate-800 rounded-2xl divide-y divide-slate-800 overflow-hidden">
          ${rows}
        </ol>

        <p class="mt-3 text-[11px] text-slate-600">Tip: click a milestone row to jump straight to that epic board.</p>
      </div>`;
  }

  function gotoEpic(id) { selectProject(id); }

  // ----- Participants (selection funnel) -----------------------------------
  const SEL_BADGE = {
    APPLIED: "bg-slate-700 text-slate-300",
    INTERVIEWING: "bg-amber-500/20 text-amber-300",
    SELECTED: "bg-emerald-500/20 text-emerald-300",
    WAITLISTED: "bg-brand-500/20 text-brand-200",
    REJECTED: "bg-rose-500/15 text-rose-300",
  };

  function renderParticipants(host) {
    const c = state.community;
    const parts = c.participants || [];
    const statuses = (META.communityMeta && META.communityMeta.selection_statuses) || [];
    const counts = {};
    parts.forEach((p) => { counts[p.selection_status_key] = (counts[p.selection_status_key] || 0) + 1; });
    const cap = c.selection_cap, selected = c.selected_count;
    const capPct = cap ? Math.min(100, Math.round((selected / cap) * 100)) : 0;

    let list = parts.slice();
    if (state.participantFilter) list = list.filter((p) => p.selection_status_key === state.participantFilter);
    if (state.participantSearch) {
      const q = state.participantSearch.toLowerCase();
      list = list.filter((p) => (p.full_name + " " + (p.email || "") + " " + (p.skills || "") + " " + (p.school_or_org || "")).toLowerCase().includes(q));
    }

    const chips = statuses.map((s) =>
      `<button onclick="OPS.filterParticipants('${s.key}')" class="px-2.5 py-1 rounded-lg text-[11px] font-semibold border ${state.participantFilter === s.key ? "border-brand-500 bg-brand-500/15 text-brand-200" : "border-slate-700 text-slate-400 hover:text-slate-200"}">${esc(s.label)} ${counts[s.key] ? `· ${counts[s.key]}` : ""}</button>`
    ).join("");

    const rows = list.length ? list.map((p) => {
      const badge = SEL_BADGE[p.selection_status_key] || "bg-slate-700 text-slate-300";
      const opts = statuses.map((s) => `<option value="${s.key}" ${s.key === p.selection_status_key ? "selected" : ""}>${esc(s.label)}</option>`).join("");
      return `
        <div class="surface border rounded-xl p-3 flex items-center gap-3">
          <span class="h-9 w-9 rounded-full bg-brand-500 text-white text-[11px] font-bold flex items-center justify-center shrink-0">${esc(initials(p.full_name))}</span>
          <div class="min-w-0 flex-1">
            <p class="text-sm font-semibold text-slate-100 truncate">${esc(p.full_name)} <span class="text-[10px] font-bold ${badge} rounded px-1.5 py-0.5 ml-1 uppercase">${esc(p.selection_status)}</span></p>
            <p class="text-[11px] text-slate-500 truncate">${esc(p.email || "")}${p.school_or_org ? " · " + esc(p.school_or_org) : ""}${p.experience_level ? " · " + esc(p.experience_level) : ""}</p>
            ${p.skills ? `<p class="text-[11px] text-slate-600 truncate mt-0.5">${esc(p.skills)}</p>` : ""}
          </div>
          ${p.team ? `<span class="text-[10px] text-brand-200 bg-brand-500/15 rounded px-1.5 py-0.5 shrink-0" title="Team">${esc(p.team.name)}</span>` : ""}
          <select onchange="OPS.setSelection(${p.id}, this.value)" class="shrink-0 rounded-lg surface-2 border border-slate-700 px-2 py-1.5 text-xs text-slate-100">${opts}</select>
          <button onclick="OPS.openNotes(${p.id})" class="shrink-0 text-[11px] text-slate-400 hover:text-brand-200 px-2 py-1" title="Interview notes">📝</button>
        </div>`;
    }).join("") : `<p class="text-sm text-slate-500 text-center py-10">No participants match.</p>`;

    host.innerHTML = `
      <div class="max-w-4xl">
        <div class="surface border rounded-2xl p-5 mb-5">
          <div class="flex items-center justify-between mb-2">
            <p class="text-sm font-bold text-white">Selected cohort</p>
            <p class="text-sm font-bold ${selected >= cap ? "text-rose-300" : "text-emerald-300"}">${selected} / ${cap}</p>
          </div>
          <div class="h-2.5 rounded-full bg-slate-800 overflow-hidden">
            <div class="h-full ${selected >= cap ? "bg-rose-500" : "bg-emerald-500"} rounded-full" style="width:${capPct}%"></div>
          </div>
          <p class="text-[11px] text-slate-500 mt-2">${parts.length} total applicant${parts.length === 1 ? "" : "s"}${selected >= cap ? " · cap reached" : ` · ${cap - selected} spots left`}</p>
        </div>
        <div class="flex flex-wrap items-center gap-2 mb-3">
          <button onclick="OPS.filterParticipants('')" class="px-2.5 py-1 rounded-lg text-[11px] font-semibold border ${!state.participantFilter ? "border-brand-500 bg-brand-500/15 text-brand-200" : "border-slate-700 text-slate-400 hover:text-slate-200"}">All · ${parts.length}</button>
          ${chips}
        </div>
        <input id="part-search" oninput="OPS.searchParticipants(this.value)" value="${esc(state.participantSearch)}" placeholder="Search name, email, skills…"
          class="w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:ring-2 focus:ring-brand-500 outline-none mb-4" />
        <div class="space-y-2">${rows}</div>
      </div>`;
    const s = document.getElementById("part-search");
    if (s && state.participantSearch) { s.focus(); s.selectionStart = s.value.length; }
  }

  function filterParticipants(key) { state.participantFilter = key; renderProgramSection(); }
  function searchParticipants(v) { state.participantSearch = v; renderProgramSection(); }

  async function setSelection(profileId, status) {
    try {
      await api(`/api/participants/${profileId}`, "PATCH", { selection_status: status });
      toast("Selection updated.");
      await refreshCommunity();
    } catch (err) { toast(err.message, "err"); await refreshCommunity(); }
  }

  function openNotes(profileId) {
    const p = (state.community.participants || []).find((x) => x.id === profileId);
    if (!p) return;
    programModal(`
      <h3 class="text-lg font-bold text-white mb-1">Interview notes</h3>
      <p class="text-xs text-slate-500 mb-4">${esc(p.full_name)} · ${esc(p.email || "")}</p>
      <textarea id="notes-area" rows="6" class="w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" placeholder="Private notes for the organizing team…">${esc(p.interview_notes || "")}</textarea>
      <div class="flex justify-end gap-2 mt-4">
        <button onclick="OPS.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Cancel</button>
        <button onclick="OPS.saveNotes(${profileId})" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">Save notes</button>
      </div>`);
  }

  async function saveNotes(profileId) {
    const notes = document.getElementById("notes-area").value;
    try {
      await api(`/api/participants/${profileId}`, "PATCH", { interview_notes: notes });
      toast("Notes saved."); closeModal(); await refreshCommunity();
    } catch (err) { toast(err.message, "err"); }
  }

  // ----- Teams -------------------------------------------------------------
  function renderTeams(host) {
    const teams = state.community.teams || [];
    if (!teams.length) {
      host.innerHTML = `<p class="text-sm text-slate-500 text-center py-16">No teams formed yet. Selected participants can create teams from their portal.</p>`;
      return;
    }
    host.innerHTML = `
      <div class="max-w-4xl">
        <p class="text-[11px] text-slate-500 mb-4">${teams.length} team${teams.length === 1 ? "" : "s"} formed</p>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          ${teams.map((t) => `
            <div class="surface border rounded-2xl p-4">
              <div class="flex items-start justify-between gap-2">
                <p class="text-sm font-bold text-slate-100">${esc(t.name)}</p>
                <span class="text-[10px] text-slate-400 bg-slate-800 rounded px-1.5 py-0.5 shrink-0">${t.size} member${t.size === 1 ? "" : "s"}</span>
              </div>
              ${t.pitch ? `<p class="text-xs text-slate-400 mt-1">${esc(t.pitch)}</p>` : ""}
              ${t.target_requirement ? `<div class="mt-2 inline-flex items-center gap-1 text-[11px] text-brand-200 bg-brand-500/15 rounded px-2 py-0.5">🎯 ${esc(t.target_requirement.title)}</div>` : `<p class="mt-2 text-[11px] text-amber-300/80">No problem focus yet</p>`}
              <div class="mt-3 pt-3 border-t border-slate-800 flex flex-wrap gap-1.5">
                ${t.members.map((m) => `<span class="inline-flex items-center gap-1 text-[11px] ${m.is_lead ? "text-brand-200 bg-brand-500/15" : "text-slate-300 bg-slate-800"} rounded-full px-2 py-0.5" title="${esc(m.email || "")}"><span class="h-4 w-4 rounded-full bg-brand-500 text-white text-[8px] font-bold flex items-center justify-center">${esc(initials(m.display_name))}</span>${esc(m.display_name)}${m.is_lead ? " ★" : ""}</span>`).join("")}
              </div>
            </div>`).join("")}
        </div>
      </div>`;
  }

  function normalizeEmail(value) {
    return String(value || "").trim().toLowerCase();
  }

  // ----- Stakeholders (merged with portal access) -------------------------
  function renderPartners(host) {
    const project = currentProject();
    if (!project) {
      host.innerHTML = `<p class="text-sm text-slate-500 text-center py-16">Select an epic to manage stakeholders.</p>`;
      return;
    }

    const stakeholders = project.stakeholders || [];
    const partnerAccounts = (state.community && state.community.partners) || [];
    const accountById = new Map();
    partnerAccounts.forEach((p) => {
      if (p && p.id != null && !accountById.has(p.id)) accountById.set(p.id, p);
    });

    const cards = stakeholders.length ? stakeholders.map((s) => {
      const account = accountById.get(s.id) || null;
      const roles = (s.roles || []).map((r) =>
        `<span class="text-[10px] font-semibold text-brand-200 bg-brand-500/15 rounded px-1.5 py-0.5">${esc(r.label)}</span>`
      ).join(" ");
      const reqs = account ? (account.requirements || []) : [];
      const loginStatus = account
        ? (account.portal_enabled
          ? `<span class="text-[10px] text-emerald-300 bg-emerald-500/15 rounded px-1.5 py-0.5">Portal login enabled</span>`
          : `<button onclick="OPS.enablePartnerLogin(${s.id})" class="text-[11px] font-semibold text-brand-200 hover:text-brand-100">Enable portal login</button>`)
        : (s.contact_email || s.email)
          ? `<button onclick="OPS.enablePartnerLogin(${s.id})" class="text-[11px] font-semibold text-brand-200 hover:text-brand-100">Enable portal login</button>`
          : `<span class="text-[10px] text-slate-500">Add a contact email to enable login</span>`;

      return `
        <div class="surface border rounded-2xl p-4">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="text-sm font-bold text-slate-100 truncate">
                ${esc(s.name)}
                <span class="text-[10px] font-bold ${STATUS_BADGE[s.status_key] || "bg-slate-700 text-slate-300"} rounded px-1.5 py-0.5 ml-1 uppercase">${esc(s.status)}</span>
              </p>
              <p class="text-[11px] text-slate-500 truncate">${esc(s.organization || s.contact_email || "No organization")}</p>
            </div>
            <span class="text-[10px] text-slate-300 bg-slate-800 rounded px-1.5 py-0.5 shrink-0">${s.open_task_count} open task${s.open_task_count === 1 ? "" : "s"}</span>
          </div>
          <div class="flex flex-wrap items-center gap-1 mt-2">${roles || `<span class="text-[11px] text-slate-600">No stakeholder roles</span>`}</div>
          <div class="mt-3 pt-3 border-t border-slate-800">
            <div class="flex items-center justify-between gap-2">
              <p class="text-[11px] font-semibold text-slate-500">${reqs.length} problem statement${reqs.length === 1 ? "" : "s"}</p>
              ${loginStatus}
            </div>
            <div class="space-y-1 mt-1">
              ${reqs.slice(0, 4).map((r) => `<p class="text-[11px] text-slate-400 truncate">• ${esc(r.title)} <span class="text-slate-600">(${esc(r.status)})</span></p>`).join("") || `<p class="text-[11px] text-slate-600">No problem statements yet</p>`}
            </div>
          </div>
        </div>`;
    }).join("") : `<p class="text-sm text-slate-500 text-center py-10">No stakeholders yet. Add one to start planning.</p>`;

    const linkedIds = new Set(stakeholders.map((s) => s.id));
    const unlinkedAccounts = partnerAccounts.filter((p) => {
      return p && p.id != null && !linkedIds.has(p.id);
    });

    const unlinkedBlock = unlinkedAccounts.length ? `
      <div class="mt-6 surface border rounded-2xl p-4">
        <p class="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Portal accounts not linked to the shared stakeholder matrix</p>
        <div class="space-y-1">
          ${unlinkedAccounts.map((p) => `<p class="text-[11px] text-slate-400 truncate">• ${esc(p.organization || p.display_name || p.email)}${p.email ? ` (${esc(p.email)})` : ""}</p>`).join("")}
        </div>
        <p class="text-[11px] text-slate-600 mt-2">Use Add stakeholder to include them in the shared stakeholder matrix.</p>
      </div>` : "";

    host.innerHTML = `
      <div class="max-w-5xl">
        <div class="flex items-center justify-between gap-2 mb-4 flex-wrap">
          <p class="text-[11px] text-slate-500">${stakeholders.length} shared stakeholder${stakeholders.length === 1 ? "" : "s"} (program-wide)</p>
          <div class="flex items-center gap-2">
            <button onclick="OPS.openModal('manageStakeholders')" class="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-300 border border-slate-700 hover:bg-slate-800/70">Manage matrix</button>
            <button onclick="OPS.openModal('stakeholderForm')" class="px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-brand-500 hover:bg-brand-400">+ Add stakeholder</button>
          </div>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">${cards}</div>
        ${unlinkedBlock}
      </div>`;
  }

  async function enablePartnerLogin(stakeholderId) {
    const stakeholder = state.projects.flatMap((p) => p.stakeholders || []).find((s) => s.id === stakeholderId);
    if (!stakeholder) { toast("Stakeholder not found.", "err"); return; }
    const email = stakeholder.contact_email || stakeholder.email || null;
    if (!email) {
      toast("Add a contact email first, then enable login.", "err");
      return;
    }
    try {
      await api("/api/industry-partners/invite", "POST", {
        email,
        name: stakeholder.name,
        organization: stakeholder.organization,
      });
      toast("Portal login enabled for this stakeholder.");
      await refreshCommunity();
    } catch (err) {
      toast(err.message, "err");
    }
  }

  function invitePartner() {
    const industries = (META.communityMeta && META.communityMeta.industries || []).map((n) => `<option value="${esc(n)}"></option>`).join("");
    programModal(`
      <form onsubmit="OPS.submitInvitePartner(event)">
        <h3 class="text-lg font-bold text-white mb-1">Invite a stakeholder</h3>
        <p class="text-xs text-slate-500 mb-4">They'll be added to the shared stakeholder matrix and can sign in with just their email — no passcode needed.</p>
        <label class="block mb-3"><span class="text-xs font-semibold text-slate-400">Email</span>
          <input name="email" type="email" required placeholder="partner@company.com" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" /></label>
        <label class="block mb-3"><span class="text-xs font-semibold text-slate-400">Contact name</span>
          <input name="name" placeholder="e.g. Daw Hla" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" /></label>
        <div class="grid grid-cols-2 gap-3">
          <label class="block mb-3"><span class="text-xs font-semibold text-slate-400">Organization</span>
            <input name="organization" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" /></label>
          <label class="block mb-3"><span class="text-xs font-semibold text-slate-400">Industry</span>
            <input name="industry" list="inv-ind" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" />
            <datalist id="inv-ind">${industries}</datalist></label>
        </div>
        <div class="flex justify-end gap-2 mt-2">
          <button type="button" onclick="OPS.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Cancel</button>
          <button type="submit" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">Send invite</button>
        </div>
      </form>`);
  }

  async function submitInvitePartner(e) {
    e.preventDefault();
    const fd = new FormData(e.target); const body = {}; fd.forEach((v, k) => { if (v) body[k] = v; });
    try {
      await api("/api/industry-partners/invite", "POST", body);
      toast("Stakeholder invited.");
      closeModal();
      state.community = null;
      await refresh();
      await refreshCommunity();
    }
    catch (err) { toast(err.message, "err"); }
  }

  function programModal(html, width) {
    destroyTaskEditor();
    const card = document.getElementById("modal-card");
    card.className = "relative surface border rounded-2xl shadow-2xl w-full p-6 max-h-[90vh] overflow-y-auto scroll-thin text-slate-200 " + (width || "max-w-lg");
    card.innerHTML = html;
    document.getElementById("modal-host").classList.remove("hidden");
  }

  // ---- Public surface -----------------------------------------------------
  window.OPS = {
    selectProject, selectSprint, openModal, closeModal, applyFilter, logout, setView,
    dragStart, dragOver, dragLeave, drop,
    sprintDragStart, sprintDragEnd, sprintDragOver, sprintDragLeave, sprintDrop,
    toggleBlock, openTask,
    submitProject, submitInvite, submitSprint, submitStakeholder, submitTask,
    startEditUser, deleteUser, saveUser,
    startEditStakeholder, deleteStakeholder, saveStakeholder, cancelEdit,
    startEditSprint, cancelEditSprint, saveSprint, deleteSprint,
    updateEpic, deleteEpic, setStakeholderStatus,
    saveTaskDetail, deleteTask, detailSetState, detailLink,
    assigneePickerToggle, assigneePickerSearch, assigneePickerClear,
    newDoc, openDoc, submitDoc, deleteDoc,
    openSection, gotoEpic,
    filterParticipants, searchParticipants, setSelection, openNotes, saveNotes,
    invitePartner, submitInvitePartner, enablePartnerLogin,
  };

  bootstrap().catch((err) => toast("Failed to load: " + err.message, "err"));
})();
