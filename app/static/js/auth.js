(function () {
  "use strict";

  const TOKEN_KEY = "campusclaw-access-token";

  function getToken() {
    return window.sessionStorage.getItem(TOKEN_KEY);
  }

  function setToken(token) {
    window.sessionStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    window.sessionStorage.removeItem(TOKEN_KEY);
  }

  function redirectToLogin() {
    if (window.location.pathname !== "/login") {
      window.location.assign("/login");
    }
  }

  async function authenticatedFetch(input, options = {}) {
    const token = getToken();
    if (!token) {
      clearToken();
      redirectToLogin();
      throw new Error("missing_token");
    }
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${token}`);
    const response = await window.fetch(input, { ...options, headers });
    if (response.status === 401) {
      clearToken();
      redirectToLogin();
    }
    return response;
  }

  async function logout() {
    try {
      if (getToken()) {
        await authenticatedFetch("/api/auth/logout", { method: "POST" });
      }
    } catch {
      // Local authentication state is cleared even when the network fails.
    } finally {
      clearToken();
      window.location.assign("/login");
    }
  }

  window.CampusAuth = {
    getToken,
    setToken,
    clearToken,
    redirectToLogin,
    authenticatedFetch,
    logout,
  };

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("login-form");
    if (!form) return;
    const submit = document.getElementById("login-submit");
    const error = document.getElementById("login-error");
    for (const preset of document.querySelectorAll(".login-preset")) {
      preset.addEventListener("click", () => {
        form.elements.username.value = preset.dataset.username;
        form.elements.password.value = preset.dataset.password;
        error.hidden = true;
        form.elements.password.focus();
      });
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      error.hidden = true;
      try {
        const response = await window.fetch("/api/auth/token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: form.elements.username.value.trim(),
            password: form.elements.password.value,
          }),
        });
        const data = await response.json();
        if (!response.ok || !data.access_token) {
          error.textContent = "用户名或密码错误";
          error.hidden = false;
          return;
        }
        setToken(data.access_token);
        window.location.assign("/materials");
      } catch {
        error.textContent = "暂时无法登录，请稍后重试";
        error.hidden = false;
      } finally {
        submit.disabled = false;
      }
    });
  });
})();
