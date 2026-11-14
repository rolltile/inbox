(() => {
  const statusPill = document.getElementById("status-pill");
  const phoneEl = document.getElementById("phone-number");
  const updatedEl = document.getElementById("last-updated");
  const pollEl = document.getElementById("poll-interval");
  const errorBanner = document.getElementById("error-banner");
  const emptyState = document.getElementById("empty-state");
  const messagesEl = document.getElementById("messages");
  const refreshBtn = document.getElementById("refresh-btn");

  let pollIntervalMs = 15000;
  let timer = null;
  let loading = false;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function showError(message) {
    if (!message) {
      errorBanner.classList.add("hidden");
      errorBanner.textContent = "";
      return;
    }
    errorBanner.textContent = message;
    errorBanner.classList.remove("hidden");
  }

  function setStatus(connected, error) {
    if (error) {
      statusPill.textContent = "Disconnected";
      statusPill.className = "pill pill-error";
    } else if (connected) {
      statusPill.textContent = "Connected";
      statusPill.className = "pill pill-ok";
    } else {
      statusPill.textContent = "Checking…";
      statusPill.className = "pill pill-unknown";
    }
  }

  function card(message) {
    const article = document.createElement("article");
    article.className = "card";
    const time = message.timestamp_local || message.timestamp_iso || message.timestamp || "";
    const body = message.body_unavailable
      ? "Message body unavailable. Telnyx only returns a message body for up to 10 days."
      : (message.text || "");
    const isLong = body.length > 200;
    article.innerHTML = `
      <div class="card-head">
        <span class="from">${escapeHtml(message.sender || "Unknown sender")}</span>
        <span class="to">To ${escapeHtml(message.recipient || "—")}</span>
        <time>${escapeHtml(time)}</time>
      </div>
      <p class="body ${isLong ? "collapsed" : ""} ${message.body_unavailable ? "unavailable" : ""}">${escapeHtml(body)}</p>
      ${isLong ? '<button type="button" class="toggle">Show full message</button>' : ""}
      ${message.otp ? `
        <div class="otp-row">
          <span class="otp-label">Verification code</span>
          <span class="otp">${escapeHtml(message.otp)}</span>
          <button type="button" class="copy-btn" data-code="${escapeHtml(message.otp)}">Copy code</button>
        </div>` : ""}
    `;
    const toggle = article.querySelector(".toggle");
    if (toggle) {
      toggle.addEventListener("click", () => {
        const bodyEl = article.querySelector(".body");
        const collapsed = bodyEl.classList.toggle("collapsed");
        toggle.textContent = collapsed ? "Show full message" : "Show less";
      });
    }
    const copyBtn = article.querySelector(".copy-btn");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        const code = copyBtn.getAttribute("data-code") || "";
        try {
          await navigator.clipboard.writeText(code);
        } catch (e) {
          const input = document.createElement("textarea");
          input.value = code;
          document.body.appendChild(input);
          input.select();
          document.execCommand("copy");
          input.remove();
        }
        copyBtn.textContent = "Copied";
        copyBtn.classList.add("copied");
        setTimeout(() => { copyBtn.textContent = "Copy code"; copyBtn.classList.remove("copied"); }, 2000);
      });
    }
    return article;
  }

  async function load() {
    if (loading) return;
    loading = true;
    refreshBtn.disabled = true;
    try {
      const response = await fetch("/api/messages", { credentials: "same-origin" });
      if (response.status === 401) {
        window.location.href = "/login";
        return;
      }
      const data = await response.json();
      if (!response.ok) {
        setStatus(false, data.error || "Request failed");
        showError(data.error || `Request failed (HTTP ${response.status}).`);
        return;
      }
      setStatus(data.connected, data.error);
      showError(data.error || "");
      phoneEl.textContent = data.phone_number || "Not configured";
      updatedEl.textContent = data.last_updated || "—";
      if (data.poll_interval) {
        pollIntervalMs = Math.max(10000, Math.min(60000, data.poll_interval * 1000));
        pollEl.textContent = String(data.poll_interval);
        restartTimer();
      }
      const messages = Array.isArray(data.messages) ? data.messages : [];
      messagesEl.innerHTML = "";
      emptyState.classList.toggle("hidden", messages.length > 0);
      messages.forEach((message) => messagesEl.appendChild(card(message)));
    } catch (e) {
      setStatus(false, "Network error");
      showError("Could not reach the inbox server. Check your connection and try again.");
    } finally {
      loading = false;
      refreshBtn.disabled = false;
    }
  }

  function restartTimer() {
    if (timer) clearInterval(timer);
    timer = setInterval(load, pollIntervalMs);
  }

  refreshBtn.addEventListener("click", load);
  load();
  restartTimer();
})();
