/* =========================================================================
 * Login / onboarding flow for Hackathon Planning.
 * Email-OTP: request code -> verify -> (first time) choose username -> app.
 * ========================================================================= */
(function () {
  "use strict";

  let email = "";

  async function api(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok || data.ok === false) {
      throw new Error(data.message || `Request failed (${res.status})`);
    }
    return data;
  }

  function showError(msg) {
    const el = document.getElementById("auth-error");
    el.textContent = msg;
    el.classList.remove("hidden");
  }
  function clearError() {
    document.getElementById("auth-error").classList.add("hidden");
  }

  function show(step) {
    ["step-email", "step-code", "step-username"].forEach((id) => {
      document.getElementById(id).classList.toggle("hidden", id !== step);
    });
    clearError();
  }

  async function requestOtp(e) {
    e.preventDefault();
    clearError();
    email = document.getElementById("f-email").value.trim().toLowerCase();
    try {
      const r = await api("/auth/request-otp", { email });
      document.getElementById("sent-to").textContent = email;
      const hint = document.getElementById("dev-hint");
      if (r.dev_code) {
        hint.textContent = `Dev mode: your code is ${r.dev_code}`;
        hint.classList.remove("hidden");
      } else {
        hint.classList.add("hidden");
      }
      show("step-code");
      setTimeout(() => document.getElementById("f-code").focus(), 50);
    } catch (err) { showError(err.message); }
  }

  async function resend() {
    clearError();
    try {
      const r = await api("/auth/request-otp", { email });
      const hint = document.getElementById("dev-hint");
      if (r.dev_code) {
        hint.textContent = `Dev mode: your code is ${r.dev_code}`;
        hint.classList.remove("hidden");
      }
    } catch (err) { showError(err.message); }
  }

  async function verifyOtp(e) {
    e.preventDefault();
    clearError();
    const code = document.getElementById("f-code").value.trim();
    try {
      const r = await api("/auth/verify-otp", { email, code });
      if (r.needs_onboarding) {
        show("step-username");
        setTimeout(() => document.getElementById("f-username").focus(), 50);
      } else {
        window.location.href = "/";
      }
    } catch (err) { showError(err.message); }
  }

  async function setUsername(e) {
    e.preventDefault();
    clearError();
    const username = document.getElementById("f-username").value.trim();
    try {
      await api("/auth/set-username", { username });
      window.location.href = "/";
    } catch (err) { showError(err.message); }
  }

  function back() {
    show("step-email");
  }

  window.AUTH = { requestOtp, verifyOtp, setUsername, resend, back };
})();
