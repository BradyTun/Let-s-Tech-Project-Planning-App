/* =========================================================================
 * Participant portal.
 * Application status, industry problem catalog, team formation & profile.
 * ========================================================================= */
(function () {
  "use strict";

  const state = {
    me: window.PORTAL_ME || null,
    profile: null, team: null, requirements: [], meta: {},
    selectionCap: 80, selectedCount: 0, maxTeamSize: 12,
    tab: "problems", industryFilter: "", search: "",
  };

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
  const initials = (n) => String(n || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

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

  const SEL_BANNER = {
    APPLIED: ["Application under review", "bg-amber-500/10 border-amber-500/30 text-amber-200", "We're reviewing your application — hang tight!"],
    INTERVIEWING: ["Interview stage", "bg-brand-500/10 border-brand-500/30 text-brand-200", "You're in the interview round. Keep an eye on your email."],
    SELECTED: ["You're in! 🎉", "bg-emerald-500/10 border-emerald-500/30 text-emerald-200", "Congratulations — form or join a team and pick your problem."],
    WAITLISTED: ["Waitlisted", "bg-amber-500/10 border-amber-500/30 text-amber-200", "A spot may open up. We'll let you know."],
    REJECTED: ["Not selected this time", "bg-rose-500/10 border-rose-500/30 text-rose-200", "Thank you for applying — we hope to see you at future events."],
  };
  const PRIORITY = { 1: ["High", "bg-rose-500/20 text-rose-300"], 2: ["Medium", "bg-amber-500/20 text-amber-300"], 3: ["Low", "bg-slate-700 text-slate-300"] };

  const isSelected = () => state.profile && state.profile.selection_status_key === "SELECTED";

  // ---- Bootstrap ----------------------------------------------------------
  async function boot() { await load(); render(); }
  async function load() {
    const d = await api("/api/portal/bootstrap");
    state.profile = d.profile;
    state.team = d.team;
    state.requirements = d.requirements || [];
    state.meta = d.meta || {};
    state.selectionCap = d.selection_cap;
    state.selectedCount = d.selected_count;
    state.maxTeamSize = d.max_team_size;
  }
  async function refresh() { await load(); render(); }

  // ---- Render -------------------------------------------------------------
  function render() {
    renderBanner();
    renderTabs();
    renderTab();
  }

  function renderBanner() {
    const key = state.profile ? state.profile.selection_status_key : "APPLIED";
    const [title, cls, sub] = SEL_BANNER[key] || SEL_BANNER.APPLIED;
    document.getElementById("status-banner").innerHTML = `
      <div class="border rounded-2xl px-5 py-4 ${cls}">
        <div class="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <p class="text-base font-bold">${esc(title)}</p>
            <p class="text-xs opacity-90 mt-0.5">${esc(sub)}</p>
          </div>
          <span class="text-[11px] font-semibold rounded-lg px-3 py-1.5 bg-black/20">Status: ${esc(state.profile ? state.profile.selection_status : "Applied")}</span>
        </div>
      </div>`;
  }

  function renderTabs() {
    document.querySelectorAll(".tab-btn").forEach((b) => {
      const on = b.getAttribute("data-tab") === state.tab;
      b.className = "tab-btn flex-1 sm:flex-none px-4 py-2 rounded-lg text-sm font-semibold " +
        (on ? "bg-brand-500 text-white" : "text-slate-400 hover:text-slate-200");
    });
  }

  function renderTab() {
    if (state.tab === "problems") return renderProblems();
    if (state.tab === "team") return renderTeam();
    if (state.tab === "profile") return renderProfile();
  }

  // ---- Problems -----------------------------------------------------------
  function renderProblems() {
    const industries = Array.from(new Set(state.requirements.map((r) => r.industry).filter(Boolean))).sort();
    let list = state.requirements.slice();
    if (state.industryFilter) list = list.filter((r) => r.industry === state.industryFilter);
    if (state.search) {
      const q = state.search.toLowerCase();
      list = list.filter((r) => (r.title + " " + (r.problem || "") + " " + (r.organization || "")).toLowerCase().includes(q));
    }
    const cards = list.length ? list.map(problemCard).join("") :
      `<p class="text-sm text-slate-500 text-center py-10 surface border rounded-2xl">No matching problems yet. Check back soon!</p>`;
    document.getElementById("tab-content").innerHTML = `
      <div class="flex flex-col sm:flex-row gap-3 mb-4">
        <input id="prob-search" oninput="PP.search(this.value)" value="${esc(state.search)}" placeholder="Search problems, industries, partners…"
          class="flex-1 rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:ring-2 focus:ring-brand-500 outline-none" />
        <select onchange="PP.filterIndustry(this.value)" class="rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-200">
          <option value="">All industries</option>
          ${industries.map((i) => `<option value="${esc(i)}" ${i === state.industryFilter ? "selected" : ""}>${esc(i)}</option>`).join("")}
        </select>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">${cards}</div>`;
    const s = document.getElementById("prob-search");
    if (s) { s.focus(); s.selectionStart = s.value.length; }
  }

  function problemCard(r) {
    const prio = PRIORITY[r.priority] || PRIORITY[2];
    const canTarget = isSelected() && state.team && state.team.lead_user_id === state.me.id;
    const isTarget = state.team && state.team.target_requirement_id === r.id;
    return `
      <div class="surface border rounded-2xl p-4 flex flex-col">
        <div class="flex items-start justify-between gap-2">
          <p class="text-sm font-bold text-slate-100">${esc(r.title)}</p>
          <span class="shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded ${prio[1]}">${prio[0]}</span>
        </div>
        <p class="text-[11px] text-slate-500 mt-1">${esc(r.organization || "Stakeholder")}${r.industry ? " · " + esc(r.industry) : ""}</p>
        ${r.problem ? `<p class="text-xs text-slate-400 mt-2"><span class="font-semibold text-slate-300">Problem:</span> ${esc(r.problem)}</p>` : ""}
        ${r.desired_outcome ? `<p class="text-xs text-slate-400 mt-1.5"><span class="font-semibold text-slate-300">Wanted:</span> ${esc(r.desired_outcome)}</p>` : ""}
        <div class="mt-3 pt-3 border-t border-slate-800 flex items-center justify-between">
          <span class="text-[11px] text-slate-500">${r.team_count || 0} team${r.team_count === 1 ? "" : "s"} on this</span>
          ${canTarget
            ? (isTarget
              ? `<span class="text-[11px] font-semibold text-emerald-300">✓ Your team's focus</span>`
              : `<button onclick="PP.targetProblem(${r.id})" class="text-[11px] font-semibold text-brand-300 hover:text-brand-200">Set as team focus →</button>`)
            : ""}
        </div>
      </div>`;
  }

  // ---- Team ---------------------------------------------------------------
  function renderTeam() {
    const host = document.getElementById("tab-content");
    if (!isSelected()) {
      host.innerHTML = `
        <div class="surface border rounded-2xl p-8 text-center">
          <div class="h-14 w-14 mx-auto rounded-2xl bg-slate-800 border border-slate-700 flex items-center justify-center text-2xl mb-3">🔒</div>
          <p class="text-base font-bold text-white mb-1">Team formation locks until selection</p>
          <p class="text-sm text-slate-400">Once you're selected for the hackathon, you can create or join a team here.</p>
        </div>`;
      return;
    }
    if (state.team) return renderMyTeam(host);

    // No team yet: create or join.
    const targetOptions = state.requirements.map((r) =>
      `<option value="${r.id}">${esc(r.title)}${r.organization ? " · " + esc(r.organization) : ""}</option>`).join("");
    host.innerHTML = `
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="surface border rounded-2xl p-5">
          <h3 class="text-sm font-bold text-white mb-1">Create a team</h3>
          <p class="text-xs text-slate-500 mb-4">You'll be the team lead. Invite up to ${state.maxTeamSize} members with your code.</p>
          <form onsubmit="PP.createTeam(event)">
            <label class="block mb-3"><span class="text-xs font-semibold text-slate-400">Team name</span>
              <input name="name" required placeholder="e.g. Automation Avengers" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" /></label>
            <label class="block mb-3"><span class="text-xs font-semibold text-slate-400">One-line pitch</span>
              <input name="pitch" placeholder="What will you build?" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" /></label>
            <label class="block mb-4"><span class="text-xs font-semibold text-slate-400">Problem focus (optional)</span>
              <select name="target_requirement_id" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">
                <option value="">— pick later —</option>${targetOptions}</select></label>
            <button type="submit" class="w-full rounded-lg bg-brand-500 hover:bg-brand-400 text-white font-semibold py-2.5 text-sm">Create team</button>
          </form>
        </div>
        <div class="surface border rounded-2xl p-5">
          <h3 class="text-sm font-bold text-white mb-1">Join a team</h3>
          <p class="text-xs text-slate-500 mb-4">Got a code from a teammate? Enter it to join.</p>
          <form onsubmit="PP.joinTeam(event)">
            <label class="block mb-4"><span class="text-xs font-semibold text-slate-400">Team code</span>
              <input name="join_code" required placeholder="e.g. K7P2QX" maxlength="12" style="text-transform:uppercase"
                class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 tracking-widest font-semibold outline-none focus:ring-2 focus:ring-brand-500" /></label>
            <button type="submit" class="w-full rounded-lg bg-slate-800 hover:bg-slate-700 text-white font-semibold py-2.5 text-sm border border-slate-700">Join team</button>
          </form>
        </div>
      </div>`;
  }

  function renderMyTeam(host) {
    const t = state.team;
    const isLead = t.lead_user_id === state.me.id;
    host.innerHTML = `
      <div class="surface border rounded-2xl p-5">
        <div class="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <p class="text-lg font-bold text-white">${esc(t.name)}</p>
            ${t.pitch ? `<p class="text-sm text-slate-400 mt-0.5">${esc(t.pitch)}</p>` : ""}
          </div>
          <div class="text-right">
            <p class="text-[11px] text-slate-500 uppercase tracking-wide">Team code</p>
            <p class="text-lg font-bold tracking-widest text-brand-200">${esc(t.join_code)}</p>
          </div>
        </div>
        ${t.target_requirement ? `
          <div class="mt-3 inline-flex items-center gap-2 text-[11px] font-medium text-brand-200 bg-brand-500/15 rounded-lg px-3 py-1.5">
            🎯 ${esc(t.target_requirement.title)}${t.target_requirement.organization ? " · " + esc(t.target_requirement.organization) : ""}
          </div>` : `<p class="mt-3 text-[11px] text-amber-300">No problem focus chosen yet — browse Industry Problems to set one.</p>`}

        <div class="mt-5">
          <p class="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Members (${t.size}/${state.maxTeamSize})</p>
          <div class="space-y-2">
            ${t.members.map((m) => `
              <div class="flex items-center justify-between rounded-xl surface-2 border border-slate-800 px-3 py-2">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="h-7 w-7 rounded-full bg-brand-500 text-white text-[10px] font-bold flex items-center justify-center shrink-0">${esc(initials(m.display_name))}</span>
                  <div class="min-w-0">
                    <p class="text-sm font-semibold text-slate-100 truncate">${esc(m.display_name)}${m.user_id === state.me.id ? " (you)" : ""}</p>
                    <p class="text-[11px] text-slate-500 truncate">${m.experience_level ? esc(m.experience_level) : ""}${m.skills ? " · " + esc(m.skills) : ""}</p>
                  </div>
                </div>
                ${m.is_lead ? `<span class="text-[10px] font-bold text-brand-200 bg-brand-500/20 rounded px-1.5 py-0.5 uppercase shrink-0">Lead</span>` : ""}
              </div>`).join("")}
          </div>
        </div>

        <div class="mt-5 pt-4 border-t border-slate-800 flex items-center justify-between gap-2">
          ${isLead ? `<button onclick="PP.editTeam()" class="text-sm font-semibold text-brand-300 hover:text-brand-200">Edit team</button>` : `<span></span>`}
          <button onclick="PP.leaveTeam()" class="text-sm font-medium text-rose-400 hover:text-rose-300">${isLead ? "Disband / leave" : "Leave team"}</button>
        </div>
      </div>`;
  }

  // ---- Profile ------------------------------------------------------------
  function renderProfile() {
    const p = state.profile || {};
    const levels = (state.meta.experience_levels || []).map((l) =>
      `<option value="${l.key}" ${l.key === p.experience_level_key ? "selected" : ""}>${esc(l.label)}</option>`).join("");
    const industries = (state.meta.industries || []).map((n) => `<option value="${esc(n)}"></option>`).join("");
    document.getElementById("tab-content").innerHTML = `
      <form onsubmit="PP.saveProfile(event)" class="surface border rounded-2xl p-5 max-w-2xl">
        <h3 class="text-sm font-bold text-white mb-4">Your details</h3>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          ${inp("Full name", "full_name", p.full_name, "required")}
          ${inp("Phone", "phone", p.phone)}
          ${inp("School / Organization", "school_or_org", p.school_or_org)}
          <label class="block mb-1"><span class="text-xs font-semibold text-slate-400">Experience level</span>
            <select name="experience_level" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">${levels}</select></label>
          <label class="block mb-1 sm:col-span-2"><span class="text-xs font-semibold text-slate-400">Industry interest</span>
            <input name="industry_interest" list="p-ind" value="${esc(p.industry_interest || "")}" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" />
            <datalist id="p-ind">${industries}</datalist></label>
          <label class="block mb-1 sm:col-span-2"><span class="text-xs font-semibold text-slate-400">Skills</span>
            <input name="skills" value="${esc(p.skills || "")}" placeholder="Python, design, ML…" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" /></label>
          <label class="block mb-1 sm:col-span-2"><span class="text-xs font-semibold text-slate-400">About you</span>
            <textarea name="bio" rows="3" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500">${esc(p.bio || "")}</textarea></label>
        </div>
        <button type="submit" class="mt-4 rounded-lg bg-brand-500 hover:bg-brand-400 text-white font-semibold py-2.5 px-6 text-sm">Save profile</button>
      </form>`;
  }

  function inp(label, name, value, attrs = "") {
    return `<label class="block mb-1"><span class="text-xs font-semibold text-slate-400">${label}</span>
      <input name="${name}" value="${esc(value || "")}" ${attrs} class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" /></label>`;
  }

  // ---- Actions ------------------------------------------------------------
  function setTab(tab) { state.tab = tab; render(); }
  function filterIndustry(v) { state.industryFilter = v; renderProblems(); }
  function search(v) { state.search = v; renderProblems(); }

  async function saveProfile(e) {
    e.preventDefault();
    const fd = new FormData(e.target); const body = {}; fd.forEach((v, k) => { body[k] = v; });
    try { await api("/api/portal/participant/profile", "PATCH", body); toast("Profile saved."); await refresh(); }
    catch (err) { toast(err.message, "err"); }
  }

  async function createTeam(e) {
    e.preventDefault();
    const fd = new FormData(e.target); const body = {}; fd.forEach((v, k) => { body[k] = v === "" ? null : v; });
    if (body.target_requirement_id) body.target_requirement_id = parseInt(body.target_requirement_id, 10);
    try { await api("/api/portal/participant/team", "POST", body); toast("Team created!"); await refresh(); }
    catch (err) { toast(err.message, "err"); }
  }

  async function joinTeam(e) {
    e.preventDefault();
    const fd = new FormData(e.target);
    try { await api("/api/portal/participant/team/join", "POST", { join_code: fd.get("join_code") }); toast("Joined team!"); await refresh(); }
    catch (err) { toast(err.message, "err"); }
  }

  async function leaveTeam() {
    if (!window.confirm("Leave your team?")) return;
    try { await api("/api/portal/participant/team/leave", "POST", {}); toast("You left the team."); await refresh(); }
    catch (err) { toast(err.message, "err"); }
  }

  async function targetProblem(id) {
    try { await api("/api/portal/participant/team", "PATCH", { target_requirement_id: id }); toast("Team focus updated."); await refresh(); }
    catch (err) { toast(err.message, "err"); }
  }

  function editTeam() {
    const t = state.team;
    const targetOptions = state.requirements.map((r) =>
      `<option value="${r.id}" ${t.target_requirement_id === r.id ? "selected" : ""}>${esc(r.title)}</option>`).join("");
    document.getElementById("modal-card").innerHTML = `
      <form onsubmit="PP.submitEditTeam(event)">
        <h3 class="text-lg font-bold text-white mb-4">Edit team</h3>
        <label class="block mb-3"><span class="text-xs font-semibold text-slate-400">Team name</span>
          <input name="name" required value="${esc(t.name)}" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" /></label>
        <label class="block mb-3"><span class="text-xs font-semibold text-slate-400">Pitch</span>
          <input name="pitch" value="${esc(t.pitch || "")}" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-brand-500" /></label>
        <label class="block mb-4"><span class="text-xs font-semibold text-slate-400">Problem focus</span>
          <select name="target_requirement_id" class="mt-1 w-full rounded-lg surface-2 border border-slate-700 px-3 py-2 text-sm text-slate-100">
            <option value="">— none —</option>${targetOptions}</select></label>
        <div class="flex justify-end gap-2">
          <button type="button" onclick="PP.closeModal()" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800/70">Cancel</button>
          <button type="submit" class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-brand-500 hover:bg-brand-400">Save</button>
        </div>
      </form>`;
    document.getElementById("modal-host").classList.remove("hidden");
  }

  async function submitEditTeam(e) {
    e.preventDefault();
    const fd = new FormData(e.target); const body = {}; fd.forEach((v, k) => { body[k] = v === "" ? null : v; });
    if (body.target_requirement_id) body.target_requirement_id = parseInt(body.target_requirement_id, 10);
    try { await api("/api/portal/participant/team", "PATCH", body); toast("Team updated."); closeModal(); await refresh(); }
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

  window.PP = {
    setTab, filterIndustry, search, saveProfile, createTeam, joinTeam, leaveTeam,
    targetProblem, editTeam, submitEditTeam, closeModal, logout,
  };

  boot().catch((err) => toast("Failed to load: " + err.message, "err"));
})();
