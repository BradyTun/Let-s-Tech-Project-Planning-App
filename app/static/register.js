/* =========================================================================
 * Public participant registration.
 * Posts to /auth/register-participant, then points the user at passcode login.
 * ========================================================================= */
(function () {
  "use strict";

  const META = window.REG_META || { industries: [], experienceLevels: [] };

  function populate() {
    const exp = document.getElementById("reg-exp");
    if (exp) {
      exp.innerHTML = META.experienceLevels
        .map((e, i) => `<option value="${e.key}" ${i === 0 ? "selected" : ""}>${e.label}</option>`)
        .join("");
    }
    const list = document.getElementById("reg-industries");
    if (list) {
      list.innerHTML = META.industries.map((n) => `<option value="${n}"></option>`).join("");
    }
  }

  function showError(msg) {
    const el = document.getElementById("reg-error");
    el.textContent = msg;
    el.classList.remove("hidden");
  }

  function setBusy(busy) {
    const btn = document.getElementById("reg-submit");
    if (!btn) return;
    btn.disabled = busy;
    btn.textContent = busy ? "Submitting…" : "Submit application";
    btn.classList.toggle("opacity-60", busy);
  }

  async function submit(e) {
    e.preventDefault();
    document.getElementById("reg-error").classList.add("hidden");
    setBusy(true);
    const fd = new FormData(e.target);
    const body = {};
    fd.forEach((v, k) => { body[k] = typeof v === "string" ? v.trim() : v; });
    try {
      const res = await fetch("/auth/register-participant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      let data = {};
      try { data = await res.json(); } catch (_) {}
      if (!res.ok || data.ok === false) {
        throw new Error(data.message || `Request failed (${res.status})`);
      }
      document.getElementById("reg-done-email").textContent = data.email || body.email;
      document.getElementById("reg-form").classList.add("hidden");
      document.getElementById("reg-done").classList.remove("hidden");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      showError(err.message);
    } finally {
      setBusy(false);
    }
  }

  window.REG = { submit };
  populate();
})();
