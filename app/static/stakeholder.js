/* =========================================================================
 * Stakeholder portal.
 * Manage organization profile + the problem statements participants solve.
 * ========================================================================= */
(function () {
  "use strict";

  const state = { me: window.PORTAL_ME || null, profile: null, teams: [], meta: {} };

  // ---- HTTP ---------------------------------------------------------------
  async function api(path, method = "GET", body) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    if (res.status === 401) { window.location.href = "/"; throw new Error("Session expired."); }
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok || data.ok === false) throw new Error(data.message || `Request failed (${res.status})`);
    return data;
  }

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let toastTimer;
  function toast(msg, kind = "ok") {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.className = "fixed bottom-6 right-6 z-[60] px-4 py-3 rounded-xl shadow-xl text-sm font-medium border " +
      (kind === "ok" ? "bg-slate-900 text-white border-slate-700" : "bg-rose-600 text-white border-rose-400");
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 3200);
  }

  const REQ_BADGE = {
    DRAFT: "bg-slate-700 text-slate-300",
    OPEN: "bg-emerald-500/20 text-emerald-300",
    ADDRESSED: "bg-brand-500/20 text-brand-200",
    CLOSED: "bg-rose-500/15 text-rose-300",
  };
  const PRIORITY = { 1: ["High", "bg-rose-500/20 text-rose-300"], 2: ["Medium", "bg-amber-500/20 text-amber-300"], 3: ["Low", "bg-slate-700 text-slate-300"] };

  // ---- Bootstrap ----------------------------------------------------------
  async function boot() {
    const d = await api("/api/portal/bootstrap");
    state.profile = d.profile;
    state.teams = d.interested_teams || [];
    state.meta = d.meta || {};
    render();
  }
  async function refresh() {
    const d = await api("/api/portal/bootstrap");
    state.profile = d.profile;
    state.teams = d.interested_teams || [];
    render();
  }

  // ---- Render -------------------------------------------------------------
  function render() {
    renderIntro();
    renderProfileForm();
    renderRequirements();
    renderTeams();
  }

  function renderIntro() {
    const p = state.profile;
    const host = document.getElementById("intro");
    const complete = p && p.is_complete;
    host.innerHTML = `
      <div class="surface border rounded-2xl p-5 flex flex-col sm:flex-row sm:items-center gap-4">
        <div class="h-12 w-12 rounded-2xl bg-brand-500/15 border border-brand-500/30 flex items-center justify-center text-brand-200 text-lg font-bold shrink-0">${esc(initials(p && p.organization || state.me.display_name))}</div>
        <div class="min-w-0 flex-1">
          <p class="text-lg font-bold text-white truncate">${esc(p && p.organization || "Welcome, " + state.me.display_name)}</p>
          <p class="text-xs text-slate-500">${p && p.industry ? esc(p.industry) + " · " : ""}${esc((p && p.hackathon_status) || "")}</p>
        </div>
        ${!complete ? `<span class="text-[11px] font-semibold text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-1.5">Complete your profile to get started</span>` : `<span class="text-[11px] font-semibold text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-3 py-1.5">${p.open_requirement_count} live problem${p.open_requirement_count === 1 ? "" : "s"}</span>`}
      </div>`;
  }

  function field(label, name, value, attrs = "", type = "text") {
    return `<label class="block mb-3">
      <span class="text-xs font-semibold text-slate-400">${label}</span>
      <input name="${name}" type="${type}" value="${esc(value || "")}" ${attrs}
        class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none" /></label>`;
  }

  function renderProfileForm() {
    const p = state.profile || {};
    const industries = (state.meta.industries || []).map((n) => `<option value="${esc(n)}"></option>`).join("");
    const statuses = (state.meta.hackathon_statuses || []).map((s) =>
      `<option value="${s.key}" ${s.key === p.hackathon_status_key ? "selected" : ""}>${esc(s.label)}</option>`).join("");
    document.getElementById("profile-form").innerHTML = `
      <form onsubmit="SP.saveProfile(event)">
        ${field("Organization", "organization", p.organization, "placeholder='Your company / institution'")}
        <label class="block mb-3">
          <span class="text-xs font-semibold text-slate-400">Industry</span>
          <input name="industry" list="ind-list" value="${esc(p.industry || "")}" placeholder="e.g. Healthcare"
            class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 focus:ring-2 focus:ring-brand-500 outline-none" />
          <datalist id="ind-list">${industries}</datalist>
        </label>
        <label class="block mb-3">
          <span class="text-xs font-semibold text-slate-400">Status to the hackathon</span>
          <select name="hackathon_status" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">${statuses}</select>
        </label>
        ${field("Website", "website", p.website, "placeholder='https://'")}
        ${field("Contact phone", "contact_phone", p.contact_phone)}
        <label class="block mb-3">
          <span class="text-xs font-semibold text-slate-400">About your organization</span>
          <textarea name="about" rows="3" placeholder="What does your organization do?"
            class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 focus:ring-2 focus:ring-brand-500 outline-none">${esc(p.about || "")}</textarea>
        </label>
        <button type="submit" class="w-full rounded-lg bg-brand-500 hover:bg-brand-400 text-white font-semibold py-2.5 text-sm">Save profile</button>
      </form>`;
  }

  function renderRequirements() {
    const reqs = (state.profile && state.profile.requirements) || [];
    const host = document.getElementById("req-list");
    if (!reqs.length) {
      host.innerHTML = `<p class="text-sm text-slate-500 text-center py-6">No problem statements yet. Add the first challenge for participants to solve.</p>`;
      return;
    }
    host.innerHTML = reqs.map((r) => {
      const badge = REQ_BADGE[r.status_key] || "bg-slate-700 text-slate-300";
      const prio = PRIORITY[r.priority] || PRIORITY[2];
      return `
      <div class="rounded-xl border border-slate-800 surface-2 p-4">
        <div class="flex items-start justify-between gap-2">
          <p class="text-sm font-semibold text-slate-100">${esc(r.title)}</p>
          <span class="shrink-0 text-[10px] font-bold px-2 py-0.5 rounded ${badge} uppercase">${esc(r.status)}</span>
        </div>
        <div class="flex flex-wrap items-center gap-1.5 mt-1.5">
          ${r.industry ? `<span class="text-[10px] text-brand-200 bg-brand-500/15 rounded px-1.5 py-0.5">${esc(r.industry)}</span>` : ""}
          <span class="text-[10px] font-semibold px-1.5 py-0.5 rounded ${prio[1]}">${prio[0]} priority</span>
          ${r.team_count ? `<span class="text-[10px] text-slate-400">· ${r.team_count} team${r.team_count === 1 ? "" : "s"} interested</span>` : ""}
        </div>
        ${r.problem ? `<p class="text-xs text-slate-400 mt-2 line-clamp-2">${esc(r.problem)}</p>` : ""}
        <div class="flex justify-end gap-1 mt-2">
          <button onclick="SP.openRequirement(${r.id})" class="text-[11px] text-slate-400 hover:text-brand-200 px-2 py-1">Edit</button>
          <button onclick="SP.deleteRequirement(${r.id})" class="text-[11px] text-rose-400 hover:text-rose-300 px-2 py-1">Delete</button>
        </div>
      </div>`;
    }).join("");
  }

  function renderTeams() {
    const host = document.getElementById("teams-list");
    if (!state.teams.length) {
      host.innerHTML = `<p class="text-sm text-slate-500 text-center py-3">No teams have picked your problems yet.</p>`;
      return;
    }
    host.innerHTML = state.teams.map((t) => `
      <div class="rounded-xl border border-slate-800 surface-2 px-3 py-2.5 flex items-center justify-between">
        <div class="min-w-0">
          <p class="text-sm font-semibold text-slate-100 truncate">${esc(t.name)}</p>
          <p class="text-[11px] text-slate-500 truncate">${t.target_requirement ? esc(t.target_requirement.title) : ""}</p>
        </div>
        <span class="text-[11px] text-slate-400 shrink-0">${t.size} member${t.size === 1 ? "" : "s"}</span>
      </div>`).join("");
  }

  // ---- Actions ------------------------------------------------------------
  async function saveProfile(e) {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {}; fd.forEach((v, k) => { body[k] = v; });
    try { await api("/api/portal/stakeholder/profile", "PATCH", body); toast("Profile saved."); await refresh(); }
    catch (err) { toast(err.message, "err"); }
  }

  function openRequirement(id) {
    const reqs = (state.profile && state.profile.requirements) || [];
    const r = id != null ? reqs.find((x) => x.id === id) : null;
    const statuses = (state.meta.requirement_statuses || []).map((s) =>
      `<option value="${s.key}" ${r && s.key === r.status_key ? "selected" : (!r && s.key === "OPEN" ? "selected" : "")}>${esc(s.label)}</option>`).join("");
    const industries = (state.meta.industries || []).map((n) => `<option value="${esc(n)}"></option>`).join("");
    const card = document.getElementById("modal-card");
    card.innerHTML = `
      <form onsubmit="SP.submitRequirement(event, ${r ? r.id : "null"})">
        <h3 class="text-lg font-bold text-white mb-1">${r ? "Edit problem" : "New problem statement"}</h3>
        <p class="text-xs text-slate-500 mb-4">Be specific — clear problems attract stronger teams.</p>
        ${field("Title", "title", r && r.title, "required placeholder='e.g. Manual clinic appointment scheduling'")}
        <label class="block mb-3">
          <span class="text-xs font-semibold text-slate-400">Industry</span>
          <input name="industry" list="req-ind" value="${esc((r && r.industry) || (state.profile && state.profile.industry) || "")}"
            class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 focus:ring-2 focus:ring-brand-500 outline-none" />
          <datalist id="req-ind">${industries}</datalist>
        </label>
        <div class="grid grid-cols-2 gap-3">
          <label class="block mb-3">
            <span class="text-xs font-semibold text-slate-400">Priority</span>
            <select name="priority" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">
              <option value="1" ${r && r.priority === 1 ? "selected" : ""}>High</option>
              <option value="2" ${!r || r.priority === 2 ? "selected" : ""}>Medium</option>
              <option value="3" ${r && r.priority === 3 ? "selected" : ""}>Low</option>
            </select>
          </label>
          <label class="block mb-3">
            <span class="text-xs font-semibold text-slate-400">Visibility</span>
            <select name="status" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">${statuses}</select>
          </label>
        </div>
        <label class="block mb-3">
          <span class="text-xs font-semibold text-slate-400">The problem</span>
          <textarea name="problem" rows="3" placeholder="What's broken or painful today?"
            class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 focus:ring-2 focus:ring-brand-500 outline-none">${esc(r && r.problem || "")}</textarea>
        </label>
        <label class="block mb-4">
          <span class="text-xs font-semibold text-slate-400">What should be automated / the ideal outcome</span>
          <textarea name="desired_outcome" rows="3" placeholder="Describe the solution you'd love to see."
            class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 focus:ring-2 focus:ring-brand-500 outline-none">${esc(r && r.desired_outcome || "")}</textarea>
        </label>
        <div class="flex justify-end gap-2">
          <button type="button" onclick="SP.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Cancel</button>
          <button type="submit" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">${r ? "Save" : "Publish"}</button>
        </div>
      </form>`;
    document.getElementById("modal-host").classList.remove("hidden");
  }

  async function submitRequirement(e, id) {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {}; fd.forEach((v, k) => { body[k] = v; });
    body.priority = parseInt(body.priority, 10);
    try {
      if (id == null) await api("/api/portal/stakeholder/requirements", "POST", body);
      else await api(`/api/portal/stakeholder/requirements/${id}`, "PATCH", body);
      toast("Problem saved."); closeModal(); await refresh();
    } catch (err) { toast(err.message, "err"); }
  }

  async function deleteRequirement(id) {
    if (!window.confirm("Delete this problem statement?")) return;
    try { await api(`/api/portal/stakeholder/requirements/${id}`, "DELETE"); toast("Deleted."); await refresh(); }
    catch (err) { toast(err.message, "err"); }
  }

  function closeModal() {
    document.getElementById("modal-host").classList.add("hidden");
    document.getElementById("modal-card").innerHTML = "";
  }

  async function logout() {
    try { await fetch("/auth/logout", { method: "POST" }); } catch (_) {}
    window.location.href = "/";
  }

  const initials = (n) => String(n || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

  window.SP = {
    saveProfile, openRequirement, submitRequirement, deleteRequirement, closeModal, logout,
  };

  boot().catch((err) => toast("Failed to load: " + err.message, "err"));
})();
