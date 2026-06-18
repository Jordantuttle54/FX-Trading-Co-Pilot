(() => {
  const TOKEN_KEY = "afx_auth_token";
  const USER_KEY = "afx_auth_user";
  const rawFetch = window.fetch.bind(window);

  function pathFromInput(input) {
    const raw = typeof input === "string" ? input : input.url;
    try {
      const url = new URL(raw, window.location.origin);
      return url.pathname;
    } catch (_) {
      return raw || "";
    }
  }

  function emptyProtectedResponse(path) {
    if (path === "/api/journal") {
      return { rows: [], stats: { trades: 0, win_rate_pct: 0, total_r: 0, avg_r: 0 } };
    }
    if (path === "/api/paper-trades") {
      return { rows: [], stats: { trades: 0, open: 0, closed: 0, win_rate_pct: 0, total_r: 0, estimated_pnl: 0 } };
    }
    return null;
  }

  window.fetch = async (input, init = {}) => {
    const path = pathFromInput(input);
    const method = String(init.method || "GET").toUpperCase();
    const token = localStorage.getItem(TOKEN_KEY);
    const fallback = !token && method === "GET" ? emptyProtectedResponse(path) : null;
    if (fallback) {
      return new Response(JSON.stringify(fallback), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    const headers = new Headers(init.headers || {});
    if (token && path.startsWith("/api/") && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return rawFetch(input, { ...init, headers });
  };

  async function verify() {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return null;
    const res = await rawFetch("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      return null;
    }
    const data = await res.json();
    localStorage.setItem(USER_KEY, data.user);
    return data.user;
  }

  function addUserBadge(user) {
    let badge = document.getElementById("authUserBadge");
    if (!badge) {
      badge = document.createElement("div");
      badge.id = "authUserBadge";
      document.body.appendChild(badge);
    }
    badge.innerHTML = `<span>Signed in as <strong>${user}</strong></span><button type="button" id="authLogout">Log out</button>`;
    document.getElementById("authLogout").onclick = () => {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      window.location.reload();
    };
  }

  function showLogin(message = "") {
    let overlay = document.getElementById("authOverlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "authOverlay";
      document.body.appendChild(overlay);
    }
    overlay.innerHTML = `
      <div class="auth-card">
        <div class="pill"><span class="dot"></span> Private workstation</div>
        <h1>ALEX Trading Co-Pilot</h1>
        <p class="muted">Sign in to keep journal, paper-trade and performance records separated by user.</p>
        <form id="authForm">
          <label>Username
            <select id="authUsername">
              <option>Jordan</option>
              <option>Jake</option>
            </select>
          </label>
          <label>Access code
            <input id="authPasscode" type="password" autocomplete="current-password" />
          </label>
          <button type="submit">Enter workstation</button>
          <div id="authMessage" class="auth-message">${message}</div>
        </form>
      </div>`;
    document.getElementById("authForm").onsubmit = async (event) => {
      event.preventDefault();
      const username = document.getElementById("authUsername").value;
      const passcode = document.getElementById("authPasscode").value;
      const msg = document.getElementById("authMessage");
      msg.textContent = "Checking...";
      const res = await rawFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, passcode })
      });
      if (!res.ok) {
        msg.textContent = "Login failed. Check the username and access code.";
        return;
      }
      const data = await res.json();
      localStorage.setItem(TOKEN_KEY, data.access_token);
      localStorage.setItem(USER_KEY, data.user);
      window.location.reload();
    };
  }

  document.addEventListener("DOMContentLoaded", async () => {
    try {
      const user = await verify();
      if (user) {
        addUserBadge(user);
      } else {
        showLogin();
      }
    } catch (err) {
      console.error(err);
      showLogin("Unable to verify session. Try signing in again.");
    }
  });
})();
