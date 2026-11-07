(function () {
  var form = document.getElementById("ai-propose-form");
  var statusEl = document.getElementById("agent-flow-status");
  var elapsedEl = statusEl ? statusEl.querySelector("[data-flow-elapsed]") : null;
  var copyBtn = document.getElementById("agent-decision-trace-copy");
  var tracePre = document.getElementById("agent-decision-trace-json");
  var root = document.querySelector("[data-agent-workspace]");
  var backdrop = document.querySelector("[data-agent-backdrop]");

  if (copyBtn && tracePre) {
    copyBtn.addEventListener("click", function () {
      var text = tracePre.textContent || "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text);
      }
    });
  }

  function closeDrawers() {
    if (!root) return;
    root.classList.remove("agent-sidebar-open", "agent-inspector-open");
    if (backdrop) backdrop.hidden = true;
    document.querySelectorAll("[data-agent-toggle]").forEach(function (btn) {
      btn.setAttribute("aria-expanded", "false");
    });
  }

  document.querySelectorAll("[data-agent-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!root) return;
      var which = btn.getAttribute("data-agent-toggle");
      var openClass = which === "sidebar" ? "agent-sidebar-open" : "agent-inspector-open";
      var other = which === "sidebar" ? "agent-inspector-open" : "agent-sidebar-open";
      var willOpen = !root.classList.contains(openClass);
      root.classList.remove(other);
      root.classList.toggle(openClass, willOpen);
      if (backdrop) backdrop.hidden = !willOpen;
      document.querySelectorAll("[data-agent-toggle]").forEach(function (b) {
        b.setAttribute(
          "aria-expanded",
          String(b.getAttribute("data-agent-toggle") === which && willOpen)
        );
      });
    });
  });
  if (backdrop) {
    backdrop.addEventListener("click", closeDrawers);
  }

  var thread = document.querySelector(".agent-chat-thread");
  if (thread) {
    thread.scrollTop = thread.scrollHeight;
  }

  function agentTurnNavigate(el) {
    var href = el.getAttribute("data-agent-turn-href");
    if (href) window.location.href = href;
  }
  document.querySelectorAll("[data-agent-turn-href]").forEach(function (el) {
    el.addEventListener("click", function (ev) {
      if (ev.target.closest("a, button, input, textarea, select, label, pre, code, .table-scroll a")) {
        return;
      }
      agentTurnNavigate(el);
    });
    el.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      // Ignore Enter/Space that originate from Markdown links or other interactive children
      // so parent bubble navigation does not steal keyboard activation.
      var origin = ev.target;
      if (origin && origin.nodeType === 3) origin = origin.parentElement;
      if (
        origin &&
        origin.closest &&
        origin.closest("a, button, input, textarea, select, label, pre, code, .table-scroll a")
      ) {
        return;
      }
      if (document.activeElement !== el) return;
      ev.preventDefault();
      agentTurnNavigate(el);
    });
  });

  var historyList = document.querySelector(".agent-chat-history-list");
  if (historyList && historyList.dataset.historyUrl) {
    var historyLoading = false;
    var historyDone = historyList.dataset.historyDone === "1";
    function appendHistory(items) {
      items.forEach(function (item) {
        var li = document.createElement("li");
        var link = document.createElement("a");
        link.href = item.href || "#";
        link.title = item.title || "";
        if (item.session_id && item.session_id === historyList.dataset.activeSession) {
          link.className = "active";
        }
        var title = document.createElement("span");
        title.className = "agent-history-title";
        title.textContent = item.title || "";
        link.appendChild(title);
        if (item.last_message_at) {
          var meta = document.createElement("span");
          meta.className = "agent-history-meta muted";
          meta.textContent = item.last_message_at;
          link.appendChild(meta);
        }
        li.appendChild(link);
        historyList.appendChild(li);
      });
    }
    function loadMoreHistory() {
      if (historyDone || historyLoading) return;
      var next = Number(historyList.dataset.historyNext || 0);
      var max = Number(historyList.dataset.historyMax || 50);
      if (next >= max) {
        historyDone = true;
        return;
      }
      var nearBottom = historyList.scrollTop + historyList.clientHeight >= historyList.scrollHeight - 48;
      var notScrollable = historyList.scrollHeight <= historyList.clientHeight + 1;
      if (!nearBottom && !notScrollable) return;
      historyLoading = true;
      var page = historyList.dataset.historyPage || "15";
      fetch(historyList.dataset.historyUrl + "?offset=" + next + "&limit=" + page, {
        credentials: "same-origin",
        headers: { Accept: "application/json" }
      })
        .then(function (resp) { return resp.ok ? resp.json() : { items: [], has_more: false, next_offset: next }; })
        .then(function (data) {
          appendHistory(data.items || []);
          historyList.dataset.historyNext = String(data.next_offset != null ? data.next_offset : next);
          if (!data.has_more) historyDone = true;
        })
        .catch(function () { historyDone = true; })
        .finally(function () {
          historyLoading = false;
          if (!historyDone) loadMoreHistory();
        });
    }
    historyList.addEventListener("scroll", loadMoreHistory);
    loadMoreHistory();
  }

  var fileInput = document.getElementById("agent-corpus-file");
  var uploadStatus = document.getElementById("agent-upload-status");
  if (fileInput) {
    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      if (!file) return;
      var url = fileInput.getAttribute("data-upload-url");
      if (!url) return;
      if (uploadStatus) {
        uploadStatus.hidden = false;
        uploadStatus.textContent = "Yükleniyor: " + file.name;
      }
      var body = new FormData();
      body.append("file", file);
      fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        body: body
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data };
          });
        })
        .then(function (result) {
          if (!uploadStatus) return;
          if (result.ok && result.data && result.data.ok) {
            var displayName =
              result.data.source_filename ||
              result.data.display_name ||
              (file && file.name) ||
              "Belge";
            uploadStatus.textContent =
              result.data.message || (displayName + " yüklendi");
            var ta = document.getElementById("ai-request-text");
            if (ta && !ta.value.trim()) {
              ta.value =
                result.data.suggest_prompt ||
                (displayName + " dosyasını oku ve özetle");
            }
          } else {
            var err = (result.data && result.data.error) || "upload_failed";
            uploadStatus.textContent = "Yükleme başarısız: " + err;
          }
        })
        .catch(function () {
          if (uploadStatus) uploadStatus.textContent = "Yükleme başarısız: network";
        })
        .finally(function () {
          fileInput.value = "";
        });
    });
  }

  if (!form || !statusEl || !elapsedEl) return;
  form.addEventListener("submit", function () {
    statusEl.hidden = false;
    var started = Date.now();
    elapsedEl.textContent = "0s";
    setInterval(function () {
      elapsedEl.textContent = Math.floor((Date.now() - started) / 1000) + "s";
    }, 1000);
  });
})();
