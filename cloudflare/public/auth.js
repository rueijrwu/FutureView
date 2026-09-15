const form = document.getElementById("auth-form");
const title = document.getElementById("title");
const subtitle = document.getElementById("subtitle");
const submit = document.getElementById("submit");
const modeButton = document.getElementById("mode");
const message = document.getElementById("message");
const password = document.getElementById("password");
let mode = "login";
let registrationOpen = false;

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

async function refreshStatus() {
  const response = await fetch("/api/auth/status", { cache: "no-store" });
  const status = await response.json();
  registrationOpen = Boolean(status.registration_open);
  if (!registrationOpen && mode === "register") mode = "login";
  render();
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
    const response = await fetch(`/api/auth/${mode}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: password.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Authentication failed");
    location.replace("/");
  } catch (error) {
    message.textContent = error.message;
    await refreshStatus().catch(() => {});
  } finally {
    submit.disabled = false;
  }
});

refreshStatus().catch(() => {
  message.textContent = "Unable to load authentication status.";
});
