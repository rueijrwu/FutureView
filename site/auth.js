const API_ORIGIN = "https://futureview.rueijrwu.workers.dev";
const TOKEN_KEY = "futureview_auth_token";
const USER_KEY = "futureview_auth_user";
const form = document.getElementById("auth-form");
const title = document.getElementById("title");
const subtitle = document.getElementById("subtitle");
const submit = document.getElementById("submit");
const modeButton = document.getElementById("mode");
const message = document.getElementById("message");
const password = document.getElementById("password");
let mode = "login";
let registrationOpen = false;

function saveSession(payload) {
  if (!payload?.token) throw new Error("Authentication server did not return a session token");
  localStorage.setItem(TOKEN_KEY, payload.token);
  localStorage.setItem(USER_KEY, payload.user?.username || "");
}

function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function render() {
  const registering = mode === "register";
  title.textContent = registering ? "Create account" : "Sign in";
  subtitle.textContent = registering
    ? "Create the first FutureView account. Registration closes automatically after this account is created."
    : "Sign in to access the replay workspace.";
  submit.textContent = registering ? "Create account" : "Sign in";
  password.autocomplete = registering ? "new-password" : "current-password";
  modeButton.hidden = !registrationOpen;
  modeButton.textContent = registering ? "Back to sign in" : "Create the first account";
  message.textContent = "";
}

async function api(path, options = {}) {
  const response = await fetch(`${API_ORIGIN}${path}`, {
    cache: "no-store",
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload = {};
  try { payload = await response.json(); } catch {}
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function refreshStatus() {
  const status = await api("/api/auth/status", { method: "GET" });
  registrationOpen = Boolean(status.registration_open);
  if (!registrationOpen && mode === "register") mode = "login";
  render();
}

async function validateExistingSession() {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return false;
  const response = await fetch(`${API_ORIGIN}/api/auth/me`, {
    cache: "no-store",
    headers: { authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    clearSession();
    return false;
  }
  location.replace("/");
  return true;
}

modeButton.addEventListener("click", () => {
  mode = mode === "login" ? "register" : "login";
  render();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submit.disabled = true;
  message.textContent = "";
  try {
    const payload = await api(`/api/auth/${mode}`, {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: password.value,
      }),
    });
    saveSession(payload);
    location.replace("/");
  } catch (error) {
    message.textContent = error.message;
    await refreshStatus().catch(() => {});
  } finally {
    submit.disabled = false;
  }
});

(async () => {
  try {
    if (await validateExistingSession()) return;
    await refreshStatus();
  } catch (error) {
    message.textContent = error.message || "Unable to load authentication status.";
  }
})();
