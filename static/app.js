(function () {
  let state = null;
  let selectedClientId = null;
  let sending = false;

  const el = (id) => document.getElementById(id);

  async function api(path, opts) {
    const res = await fetch(path, opts ? {
      ...opts,
      headers: { "Content-Type": "application/json" },
    } : undefined);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || ("Erro " + res.status));
    }
    return res.json();
  }

  async function loadState() {
    state = await api("/api/state");
    if (!selectedClientId && state.clients.length) selectedClientId = state.clients[0].id;
    render();
  }

  function currentClient() {
    return state.clients.find((c) => c.id === selectedClientId);
  }

  /* ---------------- Fase 1: Responde ---------------- */
  function renderClientPicker() {
    const wrap = el("clientPicker");
    wrap.innerHTML = "";
    state.clients.forEach((c) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "client-chip" + (c.id === selectedClientId ? " active" : "");
      btn.innerHTML = `<span class="mode-dot ${c.mode}"></span> ${c.name} · ${c.business}`;
      btn.addEventListener("click", () => {
        selectedClientId = c.id;
        loadChatHistory();
        render();
      });
      wrap.appendChild(btn);
    });
  }

  function renderModeSwitch() {
    const c = currentClient();
    if (!c) return;
    el("modeAssistido").classList.toggle("active", c.mode === "assistido");
    el("modeAutomatico").classList.toggle("active", c.mode === "automatico");
    el("modeNote").textContent = c.mode === "assistido"
      ? "No modo assistido, o bot sugere a resposta e o contador aprova antes de enviar."
      : "No modo automático, o bot já responde sozinho assim que reconhece a pergunta.";
  }

  function renderPhoneHeader() {
    const c = currentClient();
    if (!c) return;
    el("phoneAvatar").textContent = c.name.charAt(0).toUpperCase();
    el("phoneName").textContent = c.name + " — " + c.business;
    el("phoneSub").textContent = c.whatsapp + " · modo " + c.mode;
  }

  async function loadChatHistory() {
    if (!selectedClientId) return;
    const messages = await api(`/api/clients/${selectedClientId}/messages`);
    const body = el("phoneBody");
    body.innerHTML = "";
    if (!messages.length) {
      body.innerHTML = '<div class="phone-empty">Nenhuma mensagem ainda com este cliente.</div>';
      return;
    }
    messages.forEach((m) => addBubble(m.text, m.direction, tagFor(m), false));
    body.scrollTop = body.scrollHeight;
  }

  function tagFor(m) {
    if (m.direction !== "out") return null;
    if (m.status === "pending") return "aguardando aprovação";
    if (m.mode_used === "automatico") return "enviado automaticamente";
    if (m.mode_used === "assistido") return "aprovado pelo contador";
    return null;
  }

  function addBubble(text, direction, tag, animate) {
    const body = el("phoneBody");
    const empty = body.querySelector(".phone-empty");
    if (empty) empty.remove();
    const b = document.createElement("div");
    b.className = "bubble " + direction + (animate ? " enter" : "");
    b.textContent = text;
    if (tag) {
      const t = document.createElement("span");
      t.className = "tag";
      t.textContent = tag;
      b.appendChild(t);
    }
    body.appendChild(b);
    body.scrollTop = body.scrollHeight;
  }

  function renderPendingQueue() {
    const panelBody = el("panelBody");
    if (!state.pending.length) {
      panelBody.innerHTML = '<div class="queue-empty">Nenhuma pergunta pendente.</div>';
      return;
    }
    panelBody.innerHTML = "";
    state.pending.forEach((m) => {
      const card = document.createElement("div");
      card.className = "suggestion-card";
      card.innerHTML =
        `<div class="from">Sugestão de resposta para ${m.client_name}</div>` +
        `<div class="reply-text"></div>` +
        `<div class="suggestion-actions"><button type="button" class="btn btn-approve">Aprovar e enviar</button><button type="button" class="btn btn-ghost">Descartar</button></div>`;
      card.querySelector(".reply-text").textContent = m.text;
      card.querySelector(".btn-approve").addEventListener("click", async () => {
        await api(`/api/messages/${m.id}/approve`, { method: "POST" });
        await refreshAll();
      });
      card.querySelector(".btn-ghost").addEventListener("click", async () => {
        await api(`/api/messages/${m.id}/discard`, { method: "POST" });
        await refreshAll();
      });
      panelBody.appendChild(card);
    });
  }

  function renderLog() {
    const list = el("logList");
    if (!state.log.length) {
      list.innerHTML = '<li class="log-empty">Ainda sem atividade.</li>';
      return;
    }
    list.innerHTML = "";
    state.log.forEach((m) => {
      const li = document.createElement("li");
      const time = document.createElement("time");
      time.textContent = m.created_at.slice(11, 16) || "";
      li.appendChild(time);
      const span = document.createElement("span");
      span.textContent = `${m.client_name}: ${m.text.slice(0, 60)}${m.text.length > 60 ? "…" : ""}`;
      li.appendChild(span);
      list.appendChild(li);
    });
  }

  async function sendMessage(text) {
    if (!selectedClientId || sending) return;
    sending = true;
    addBubble(text, "in", null, true);
    try {
      const result = await api(`/api/clients/${selectedClientId}/inbound`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      if (result.status === "sent") {
        addBubble(result.text, "out", "enviado automaticamente", true);
      }
      await refreshAll();
    } finally {
      sending = false;
    }
  }

  /* ---------------- Fase 2: Cobra ---------------- */
  function renderDocuments() {
    const body = el("docTableBody");
    if (!state.documents.length) {
      body.innerHTML = '<tr><td colspan="5" class="pending-doc">Nenhuma pendência registrada.</td></tr>';
      return;
    }
    body.innerHTML = "";
    state.documents.forEach((d) => {
      const tr = document.createElement("tr");
      const recebido = d.status === "recebido";
      tr.innerHTML = `
        <td class="client-name">${d.client_name}</td>
        <td class="pending-doc">${d.referencia}</td>
        <td>${recebido ? "—" : d.dias_atraso + " dia(s)"}</td>
        <td><span class="status-chip ${d.stage}">${d.stage_label}</span></td>
        <td></td>`;
      const actionCell = tr.querySelector("td:last-child");
      if (!recebido) {
        const remindBtn = document.createElement("button");
        remindBtn.type = "button";
        remindBtn.textContent = "Enviar lembrete agora";
        remindBtn.addEventListener("click", async () => {
          await api(`/api/documents/${d.id}/remind`, { method: "POST" });
          await refreshAll();
        });
        const receiveBtn = document.createElement("button");
        receiveBtn.type = "button";
        receiveBtn.textContent = "Marcar como recebido";
        receiveBtn.addEventListener("click", async () => {
          await api(`/api/documents/${d.id}/receive`, { method: "POST" });
          await refreshAll();
        });
        actionCell.appendChild(remindBtn);
        actionCell.appendChild(receiveBtn);
      } else {
        actionCell.textContent = "—";
      }
      body.appendChild(tr);
    });
  }

  /* ---------------- Fase 3: Radar ---------------- */
  let riskDetailClientId = null;

  function renderRisk() {
    const grid = el("riskGrid");
    grid.innerHTML = "";
    state.clients.forEach((c) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "risk-card " + c.risk.level;
      btn.innerHTML = `
        <div class="client">${c.business}</div>
        <span class="level">Risco ${c.risk.level}</span>
        <p class="signals">${c.risk.signals[0]}</p>`;
      btn.addEventListener("click", () => {
        riskDetailClientId = c.id;
        renderRiskDetail();
      });
      grid.appendChild(btn);
    });
    if (riskDetailClientId) renderRiskDetail();
  }

  function renderRiskDetail() {
    const c = state.clients.find((cl) => cl.id === riskDetailClientId);
    if (!c) return;
    el("riskDetail").classList.add("show");
    el("riskDetailName").textContent = c.business + " — score " + c.risk.score;
    el("riskDetailSignals").textContent = "Sinais: " + c.risk.signals.join("; ") + ".";
    el("riskDetailAction").textContent = c.risk.action;
    el("logComplaintBtn").onclick = async () => {
      await api("/api/complaints", {
        method: "POST",
        body: JSON.stringify({ client_id: c.id, texto: "Reclamação registrada manualmente pelo contador." }),
      });
      await refreshAll();
    };
  }

  /* ---------------- Global render / refresh ---------------- */
  function render() {
    renderClientPicker();
    renderModeSwitch();
    renderPhoneHeader();
    renderPendingQueue();
    renderLog();
    renderDocuments();
    renderRisk();
    el("clock").textContent = "Relógio da demo: " + state.now;
  }

  async function refreshAll() {
    await loadState();
    await loadChatHistory();
  }

  /* ---------------- Event wiring ---------------- */
  el("modeAssistido").addEventListener("click", async () => {
    if (!selectedClientId) return;
    await api(`/api/clients/${selectedClientId}/mode`, { method: "POST", body: JSON.stringify({ mode: "assistido" }) });
    await refreshAll();
  });
  el("modeAutomatico").addEventListener("click", async () => {
    if (!selectedClientId) return;
    await api(`/api/clients/${selectedClientId}/mode`, { method: "POST", body: JSON.stringify({ mode: "automatico" }) });
    await refreshAll();
  });

  document.querySelectorAll("#quickQs button").forEach((btn) => {
    btn.addEventListener("click", () => sendMessage(btn.getAttribute("data-q")));
  });

  el("composeForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = el("composeInput");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    sendMessage(text);
  });

  el("advanceTime").addEventListener("click", async () => {
    await api("/api/time/advance", { method: "POST", body: JSON.stringify({ days: 1 }) });
    await refreshAll();
  });

  el("resetDemo").addEventListener("click", async () => {
    await api("/api/reset", { method: "POST" });
    riskDetailClientId = null;
    await refreshAll();
  });

  const tabs = document.querySelectorAll(".phase-tab");
  const panels = document.querySelectorAll(".phase-panel");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.getAttribute("data-tab");
      tabs.forEach((t) => {
        const active = t === tab;
        t.classList.toggle("active", active);
        t.setAttribute("aria-selected", active ? "true" : "false");
      });
      panels.forEach((p) => p.classList.toggle("active", p.getAttribute("data-panel") === target));
    });
  });

  const themeToggle = el("themeToggle");
  themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    themeToggle.textContent = next === "dark" ? "Modo claro" : "Modo escuro";
  });

  loadState().then(loadChatHistory);
})();
