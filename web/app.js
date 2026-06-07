const state = {
  workspaceId: null,
  chatId: null,
  activeView: "chat",
  settings: {},
};

const el = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  bindEvents();
  await bootstrap();
  await loadMessages();
});

function bindEvents() {
  document.querySelectorAll(".nav button").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });

  el("workspaceSelect").addEventListener("change", async (event) => {
    state.workspaceId = Number(event.target.value);
    await loadChats();
    await refreshActiveView();
  });

  el("chatSelect").addEventListener("change", async (event) => {
    state.chatId = Number(event.target.value);
    await refreshActiveView();
  });

  el("addWorkspaceBtn").addEventListener("click", createWorkspace);
  el("addChatBtn").addEventListener("click", createChat);
  el("refreshMessagesBtn").addEventListener("click", loadMessages);
  el("chatForm").addEventListener("submit", sendMessage);
  el("pdfInput").addEventListener("change", uploadPdfs);
  el("noteForm").addEventListener("submit", saveNote);
  el("regenerateGraphBtn").addEventListener("click", () => loadGraph(true));
  el("literatureBtn").addEventListener("click", generateLiteratureReview);
  el("compareBtn").addEventListener("click", compareDocuments);
  el("themeToggle").addEventListener("change", (event) => {
    setTheme(event.target.checked ? "dark" : "light");
  });

  document.querySelectorAll("[data-export]").forEach((button) => {
    button.addEventListener("click", () => exportChat(button.dataset.export));
  });
}

async function bootstrap() {
  const data = await api("/api/bootstrap");
  state.settings = data.settings;
  state.workspaceId = data.workspace_id;
  state.chatId = data.chat_id;

  el("embeddingStatus").textContent = data.settings.embedding;
  el("rerankerStatus").textContent = data.settings.reranker ? "on" : "off";
  el("modelStatus").textContent = data.settings.ollama_model;

  renderWorkspaceOptions(data.workspaces);
  renderChatOptions(data.chats);
}

async function refreshActiveView() {
  if (state.activeView === "chat") await loadMessages();
  if (state.activeView === "documents") await loadDocuments();
  if (state.activeView === "notes") await loadNotes();
  if (state.activeView === "graph") await loadGraph(false);
  if (state.activeView === "exports") await loadExportDocuments();
}

function renderWorkspaceOptions(workspaces) {
  el("workspaceSelect").innerHTML = "";
  for (const workspace of workspaces) {
    const option = document.createElement("option");
    option.value = workspace.id;
    option.textContent = workspace.name;
    option.selected = Number(workspace.id) === Number(state.workspaceId);
    el("workspaceSelect").append(option);
  }
}

function renderChatOptions(chats) {
  el("chatSelect").innerHTML = "";
  for (const chat of chats) {
    const option = document.createElement("option");
    option.value = chat.id;
    option.textContent = `${chat.title} #${chat.id}`;
    option.selected = Number(chat.id) === Number(state.chatId);
    el("chatSelect").append(option);
  }
}

async function createWorkspace() {
  const input = el("workspaceName");
  const name = input.value.trim();
  if (!name) return;
  const result = await api("/api/workspaces", { method: "POST", body: { name } });
  input.value = "";
  const workspaces = await api("/api/workspaces");
  state.workspaceId = result.workspace_id;
  renderWorkspaceOptions(workspaces.workspaces);
  await loadChats();
}

async function loadChats() {
  const data = await api(`/api/chats?workspace_id=${state.workspaceId}`);
  if (!data.chats.length) {
    const created = await api("/api/chats", {
      method: "POST",
      body: { workspace_id: state.workspaceId, title: "Research Chat" },
    });
    state.chatId = created.chat_id;
    return loadChats();
  }
  if (!data.chats.some((chat) => Number(chat.id) === Number(state.chatId))) {
    state.chatId = data.chats[0].id;
  }
  renderChatOptions(data.chats);
}

async function createChat() {
  const input = el("chatTitle");
  const title = input.value.trim() || "Research Chat";
  const result = await api("/api/chats", {
    method: "POST",
    body: { workspace_id: state.workspaceId, title },
  });
  input.value = "";
  state.chatId = result.chat_id;
  await loadChats();
  await loadMessages();
}

function switchView(view) {
  state.activeView = view;
  document.querySelectorAll(".nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((section) => section.classList.remove("active"));
  el(`${view}View`).classList.add("active");
  refreshActiveView();
}

async function loadMessages() {
  const data = await api(`/api/messages?chat_id=${state.chatId}`);
  const messages = el("messages");
  messages.innerHTML = "";
  const hidden = Math.max(0, data.total - data.messages.length);
  el("chatHint").textContent = hidden
    ? `Showing the latest ${data.messages.length} messages. ${hidden} older messages are stored.`
    : "Ask questions grounded in uploaded PDFs.";
  for (const message of data.messages) {
    addMessage(message.role, message.content, message.citations || []);
  }
  scrollMessages();
}

function addMessage(role, content = "", citations = []) {
  const item = document.createElement("article");
  item.className = `message ${role}`;
  const label = document.createElement("span");
  label.className = "role";
  label.textContent = role;
  const body = document.createElement("div");
  body.className = "message-body";
  renderRichText(body, content);
  item.append(label, body);
  if (citations.length) item.append(renderSources(citations));
  el("messages").append(item);
  scrollMessages();
  return body;
}

async function sendMessage(event) {
  event.preventDefault();
  const input = el("promptInput");
  const prompt = input.value.trim();
  if (!prompt) return;
  input.value = "";
  setBusy(true);
  addMessage("user", prompt);
  const assistantBody = addMessage("assistant", "");
  const queue = [];
  let typing = true;
  typeInto(assistantBody, queue, () => typing);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workspace_id: state.workspaceId,
        chat_id: state.chatId,
        prompt,
      }),
    });
    if (!response.body) throw new Error("Streaming is not available.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let donePayload = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const eventData = JSON.parse(line);
        if (eventData.type === "delta") queue.push(...eventData.text.split(""));
        if (eventData.type === "done") donePayload = eventData;
        if (eventData.type === "error") queue.push(...eventData.message.split(""));
      }
    }

    await waitForQueue(queue);
    typing = false;
    renderRichText(assistantBody, assistantBody.dataset.rawText || assistantBody.textContent);
    if (donePayload?.citations?.length) {
      assistantBody.parentElement.append(renderSources(donePayload.citations));
    }
  } catch (error) {
    queue.push(...`Error: ${error.message}`.split(""));
    await waitForQueue(queue);
    typing = false;
    renderRichText(assistantBody, assistantBody.dataset.rawText || assistantBody.textContent);
  } finally {
    setBusy(false);
    await loadChats();
  }
}

function typeInto(target, queue, isTyping) {
  const tick = () => {
    let budget = 10;
    let addition = "";
    while (queue.length && budget > 0) {
      addition += queue.shift();
      budget -= 1;
    }
    if (addition) {
      target.dataset.rawText = `${target.dataset.rawText || target.textContent || ""}${addition}`;
      target.textContent = target.dataset.rawText;
    }
    if (queue.length) scrollMessages();
    if (isTyping() || queue.length) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function waitForQueue(queue) {
  return new Promise((resolve) => {
    const check = () => {
      if (!queue.length) resolve();
      else requestAnimationFrame(check);
    };
    check();
  });
}

function renderSources(citations) {
  const sources = document.createElement("div");
  sources.className = "sources";
  for (const citation of citations) {
    const source = document.createElement("a");
    source.className = "source";
    source.href = citation.url || `/api/documents/${citation.document_id}/pdf#page=${citation.page_start || 1}`;
    source.target = "_blank";
    source.rel = "noopener";
    const lineRange = citation.line_start
      ? `, lines ${citation.line_start}${citation.line_end && citation.line_end !== citation.line_start ? `-${citation.line_end}` : ""}`
      : "";
    source.textContent = `[${citation.number}] ${citation.file_name} p.${citation.page_start || "?"}${lineRange}`;
    source.title = "Open source PDF";
    sources.append(source);
  }
  return sources;
}

async function loadDocuments() {
  const data = await api(`/api/documents?workspace_id=${state.workspaceId}`);
  const list = el("documentsList");
  list.innerHTML = "";
  if (!data.documents.length) {
    list.append(emptyCard("No documents uploaded yet."));
    return;
  }
  for (const doc of data.documents) {
    const card = document.createElement("article");
    card.className = "card";
    const metadata = doc.metadata || {};
    const status = metadata.ingest_status || (doc.chunk_count ? "ready" : "empty_text");
    const message = metadata.ingest_message || "";
    const statusClass = doc.chunk_count ? "" : "warn";
    card.innerHTML = `
      <h3>${escapeHtml(doc.file_name)}</h3>
      <p>${doc.page_count} pages - ${doc.chunk_count || 0} chunks - ${doc.sha256.slice(0, 12)} - ${doc.created_at}</p>
      <p class="${statusClass}">${escapeHtml(status)}${message ? `: ${escapeHtml(message)}` : ""}</p>
      <div class="card-actions">
        <a href="/api/documents/${doc.id}/pdf" target="_blank" rel="noopener">Open PDF</a>
        <button data-reprocess="${doc.id}">Reprocess</button>
        <button class="danger" data-delete="${doc.id}">Delete</button>
      </div>
    `;
    list.append(card);
  }
  document.querySelectorAll("[data-reprocess]").forEach((button) => {
    button.addEventListener("click", () => reprocessDocument(button.dataset.reprocess));
  });
  document.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", () => deleteDocument(button.dataset.delete));
  });
}

async function deleteDocument(documentId) {
  if (!window.confirm("Are you sure you want to delete this PDF? This action cannot be undone.")) {
    return;
  }
  setBusy(true);
  el("uploadStatus").textContent = "Deleting PDF...";
  await api(`/api/documents/${documentId}`, { method: "DELETE" });
  el("uploadStatus").textContent = "PDF deleted successfully.";
  await loadDocuments();
  setBusy(false);
}

async function uploadPdfs(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) return;
  setBusy(true);
  for (const file of files) {
    el("uploadStatus").textContent = `Uploading ${file.name}...`;
    const form = new FormData();
    form.append("workspace_id", state.workspaceId);
    form.append("chat_id", state.chatId);
    form.append("file", file);
    const response = await fetch("/api/upload", { method: "POST", body: form });
    if (!response.ok) {
      el("uploadStatus").textContent = `Upload failed: ${file.name}`;
      break;
    }
    const result = await response.json();
    el("uploadStatus").textContent = result.is_duplicate
      ? `${file.name} was already uploaded.`
      : `${file.name}: ${result.page_count} pages, ${result.chunk_count} chunks. ${result.message || ""}`;
  }
  event.target.value = "";
  await loadDocuments();
  setBusy(false);
}

async function reprocessDocument(documentId) {
  setBusy(true);
  el("uploadStatus").textContent = "Reprocessing PDF...";
  const result = await api(`/api/documents/${documentId}/reprocess`, { method: "POST" });
  el("uploadStatus").textContent = `${result.page_count} pages, ${result.chunk_count} chunks. ${result.message || ""}`;
  await loadDocuments();
  setBusy(false);
}

async function loadNotes() {
  const data = await api(`/api/notes?workspace_id=${state.workspaceId}&chat_id=${state.chatId}`);
  const list = el("notesList");
  list.innerHTML = "";
  if (!data.notes.length) {
    list.append(emptyCard("No notes yet."));
    return;
  }
  for (const note of data.notes) {
    const card = document.createElement("article");
    card.className = "card";
    card.innerHTML = `<h3>${escapeHtml(note.title)}</h3><p>${escapeHtml(note.body)}</p>`;
    list.append(card);
  }
}

async function saveNote(event) {
  event.preventDefault();
  const title = el("noteTitle").value.trim() || "Untitled note";
  const body = el("noteBody").value.trim();
  if (!body && !title) return;
  await api("/api/notes", {
    method: "POST",
    body: { workspace_id: state.workspaceId, chat_id: state.chatId, title, body },
  });
  el("noteTitle").value = "";
  el("noteBody").value = "";
  await loadNotes();
}

async function loadGraph(regenerate) {
  setBusy(true);
  const data = await api(`/api/graph?workspace_id=${state.workspaceId}&regenerate=${regenerate ? "1" : "0"}`);
  el("graphEmpty").classList.toggle("hidden", !data.empty);
  el("graphFrame").classList.toggle("hidden", data.empty);
  if (!data.empty) {
    el("graphFrame").srcdoc = data.html;
  }
  setBusy(false);
}

async function exportChat(kind) {
  const result = await api(`/api/export/${kind}?chat_id=${state.chatId}`, { method: "POST" });
  el("exportResult").textContent = `Saved: ${result.path}`;
}

async function loadExportDocuments() {
  const data = await api(`/api/documents?workspace_id=${state.workspaceId}`);
  for (const select of [el("compareA"), el("compareB")]) {
    select.innerHTML = "";
    for (const doc of data.documents) {
      const option = document.createElement("option");
      option.value = doc.id;
      option.textContent = `${doc.file_name} #${doc.id}`;
      select.append(option);
    }
  }
  if (el("compareB").options.length > 1) el("compareB").selectedIndex = 1;
}

async function compareDocuments() {
  const documentA = Number(el("compareA").value);
  const documentB = Number(el("compareB").value);
  if (!documentA || !documentB || documentA === documentB) {
    el("exportResult").textContent = "Select two different documents to compare.";
    return;
  }
  const result = await api("/api/compare", {
    method: "POST",
    body: { document_a_id: documentA, document_b_id: documentB },
  });
  renderRichText(el("exportResult"), result.markdown, { stripSources: false });
}

async function generateLiteratureReview() {
  setBusy(true);
  el("exportResult").textContent = "Generating literature review...";
  const result = await api("/api/literature-review", {
    method: "POST",
    body: { workspace_id: state.workspaceId, chat_id: state.chatId },
  });
  renderRichText(el("exportResult"), result.content, { stripSources: false });
  setBusy(false);
}

function renderRichText(target, content, options = {}) {
  const raw = options.stripSources === false ? String(content || "").trim() : stripSourcesBlock(content);
  target.dataset.rawText = raw;
  target.innerHTML = raw ? renderRichHtml(raw) : "";
}

function renderRichHtml(raw) {
  const normalized = String(raw || "").replace(/\r\n/g, "\n");
  const parts = [];
  const fencePattern = /```([A-Za-z0-9_-]+)?\n?([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;

  while ((match = fencePattern.exec(normalized)) !== null) {
    if (match.index > lastIndex) {
      parts.push(renderMathAwareText(normalized.slice(lastIndex, match.index)));
    }
    const language = match[1] ? ` data-language="${escapeHtml(match[1])}"` : "";
    parts.push(`<pre class="code-block"${language}><code>${escapeHtml(match[2])}</code></pre>`);
    lastIndex = fencePattern.lastIndex;
  }

  if (lastIndex < normalized.length) {
    parts.push(renderMathAwareText(normalized.slice(lastIndex)));
  }
  return parts.join("");
}

function renderMathAwareText(text) {
  const displayPattern =
    /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\begin\{(?:equation\*?|align\*?|aligned)\}[\s\S]+?\\end\{(?:equation\*?|align\*?|aligned)\})/g;
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = displayPattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(renderTextBlocks(text.slice(lastIndex, match.index)));
    }
    parts.push(renderEquationBlock(match[0]));
    lastIndex = displayPattern.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(renderTextBlocks(text.slice(lastIndex)));
  }
  return parts.join("");
}

function renderTextBlocks(text) {
  return text
    .split(/\n{2,}/)
    .map((block) => renderTextBlock(block))
    .join("");
}

function renderTextBlock(block) {
  const trimmed = block.trim();
  if (!trimmed) return "";
  const lines = trimmed.split("\n").map((line) => line.trim()).filter(Boolean);
  const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);

  if (heading && lines.length === 1) {
    const level = Math.min(4, heading[1].length + 1);
    return `<h${level}>${renderInlineText(heading[2])}</h${level}>`;
  }

  if (lines.length === 1 && looksLikeDisplayFormula(trimmed)) {
    return renderEquationBlock(trimmed);
  }

  if (lines.every((line) => /^[-*]\s+/.test(line))) {
    return `<ul>${lines
      .map((line) => `<li>${renderInlineText(line.replace(/^[-*]\s+/, ""))}</li>`)
      .join("")}</ul>`;
  }

  if (lines.every((line) => /^\d+\.\s+/.test(line))) {
    return `<ol>${lines
      .map((line) => `<li>${renderInlineText(line.replace(/^\d+\.\s+/, ""))}</li>`)
      .join("")}</ol>`;
  }

  return `<p>${lines.map((line) => renderInlineText(line)).join("<br>")}</p>`;
}

function renderInlineText(text) {
  const inlinePattern = /(\\\([\s\S]+?\\\)|\$[^$\n]{1,240}\$)/g;
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = inlinePattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(escapeHtml(text.slice(lastIndex, match.index)));
    }
    const token = match[0];
    const formula = token.startsWith("\\(") ? token.slice(2, -2) : token.slice(1, -1);
    parts.push(looksLikeInlineFormula(formula) ? renderEquationSpan(formula) : escapeHtml(token));
    lastIndex = inlinePattern.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(escapeHtml(text.slice(lastIndex)));
  }
  return parts.join("");
}

function renderEquationBlock(source) {
  const equation = stripDisplayWrappers(source);
  const rows = splitEquationRows(equation);
  const isChemical = rows.some((row) => looksLikeChemicalEquation(row));
  const className = isChemical ? "math-display chem-display" : "math-display";
  const content = rows.length ? rows : [equation];
  return `<div class="${className}">${content
    .map((row) => `<div class="math-row">${renderFormula(row)}</div>`)
    .join("")}</div>`;
}

function renderEquationSpan(source) {
  const isChemical = looksLikeChemicalEquation(source);
  const className = isChemical ? "math-inline chem-inline" : "math-inline";
  return `<span class="${className}">${renderFormula(source)}</span>`;
}

function renderFormula(source) {
  const trimmed = stripLatexContainers(String(source || "").trim());
  if (looksLikeChemicalEquation(trimmed) && !/\\(?:frac|dfrac|tfrac|sqrt|sum|int|prod|lim)\b/.test(trimmed)) {
    return formatChemicalEquationHtml(trimmed);
  }
  return renderLatexExpression(trimmed);
}

function renderLatexExpression(source) {
  const value = cleanupLatex(source);
  let html = "";
  let index = 0;

  while (index < value.length) {
    const fracLength = value.startsWith("\\dfrac", index) || value.startsWith("\\tfrac", index)
      ? 6
      : value.startsWith("\\frac", index)
        ? 5
        : 0;
    if (fracLength) {
      const numerator = readLatexArgument(value, index + fracLength);
      const denominator = readLatexArgument(value, numerator.end);
      if (numerator.value && denominator.value) {
        html += `<span class="math-frac"><span>${renderLatexExpression(numerator.value)}</span><span>${renderLatexExpression(denominator.value)}</span></span>`;
        index = denominator.end;
        continue;
      }
    }

    if (value.startsWith("\\sqrt", index)) {
      const argument = readLatexArgument(value, index + 5);
      html += `<span class="math-sqrt"><span>${renderLatexExpression(argument.value)}</span></span>`;
      index = argument.end;
      continue;
    }

    if (value.startsWith("\\ce", index)) {
      const argument = readLatexArgument(value, index + 3);
      html += `<span class="chem-inline">${formatChemicalEquationHtml(argument.value)}</span>`;
      index = argument.end;
      continue;
    }

    if (value.startsWith("\\mathrm", index) || value.startsWith("\\operatorname", index) || value.startsWith("\\text", index)) {
      const commandLength = value.startsWith("\\operatorname", index)
        ? 13
        : value.startsWith("\\mathrm", index)
          ? 7
          : 5;
      const argument = readLatexArgument(value, index + commandLength);
      html += `<span class="math-roman">${escapeHtml(argument.value)}</span>`;
      index = argument.end;
      continue;
    }

    const character = value[index];
    if (character === "^" || character === "_") {
      const argument = readLatexArgument(value, index + 1);
      const tag = character === "^" ? "sup" : "sub";
      html += `<${tag}>${renderLatexExpression(argument.value)}</${tag}>`;
      index = argument.end;
      continue;
    }

    if (character === "\\") {
      if (value[index + 1] === "\\") {
        html += "<br>";
        index += 2;
        continue;
      }
      const command = readLatexCommand(value, index);
      if (!command.name) {
        html += escapeHtml(value[index + 1] || "");
        index += 2;
        continue;
      }
      html += latexSymbolHtml(command.name);
      index = command.end;
      continue;
    }

    if (character === "{" || character === "}" || character === "&") {
      index += 1;
      continue;
    }

    html += escapeHtml(character);
    index += 1;
  }

  return html;
}

function stripDisplayWrappers(source) {
  let value = String(source || "").trim();
  if (value.startsWith("$$") && value.endsWith("$$")) value = value.slice(2, -2);
  if (value.startsWith("\\[") && value.endsWith("\\]")) value = value.slice(2, -2);
  return stripLatexContainers(value.trim());
}

function stripLatexContainers(source) {
  return String(source || "")
    .replace(/\\begin\{(?:equation\*?|align\*?|aligned)\}/g, "")
    .replace(/\\end\{(?:equation\*?|align\*?|aligned)\}/g, "")
    .trim();
}

function cleanupLatex(source) {
  return stripLatexContainers(source)
    .replace(/\\left/g, "")
    .replace(/\\right/g, "")
    .replace(/\\,/g, " ")
    .replace(/\\;/g, " ")
    .replace(/\\!/g, "")
    .replace(/\\quad|\\qquad/g, " ");
}

function splitEquationRows(source) {
  return cleanupLatex(source)
    .split(/\\\\|\\newline/g)
    .map((row) => row.replace(/&/g, " ").trim())
    .filter(Boolean);
}

function readLatexArgument(source, startIndex) {
  let index = startIndex;
  while (index < source.length && /\s/.test(source[index])) index += 1;
  if (index >= source.length) return { value: "", end: index };

  if (source[index] === "{") {
    let depth = 1;
    let cursor = index + 1;
    while (cursor < source.length && depth > 0) {
      if (source[cursor] === "{") depth += 1;
      if (source[cursor] === "}") depth -= 1;
      cursor += 1;
    }
    return { value: source.slice(index + 1, cursor - 1), end: cursor };
  }

  if (source[index] === "\\") {
    const command = readLatexCommand(source, index);
    const end = command.end > index ? command.end : index + 1;
    return { value: source.slice(index, end), end };
  }

  return { value: source[index], end: index + 1 };
}

function readLatexCommand(source, startIndex) {
  const match = source.slice(startIndex + 1).match(/^[A-Za-z]+/);
  if (match) return { name: match[0], end: startIndex + 1 + match[0].length };
  const symbol = source[startIndex + 1] || "";
  return { name: symbol, end: Math.min(startIndex + 2, source.length) };
}

function latexSymbolHtml(command) {
  const symbols = {
    alpha: "&alpha;",
    beta: "&beta;",
    gamma: "&gamma;",
    Gamma: "&Gamma;",
    delta: "&delta;",
    Delta: "&Delta;",
    epsilon: "&epsilon;",
    theta: "&theta;",
    lambda: "&lambda;",
    Lambda: "&Lambda;",
    mu: "&mu;",
    pi: "&pi;",
    rho: "&rho;",
    sigma: "&sigma;",
    Sigma: "&Sigma;",
    omega: "&omega;",
    Omega: "&Omega;",
    partial: "&part;",
    nabla: "&nabla;",
    infty: "&infin;",
    sum: "&sum;",
    prod: "&prod;",
    int: "&int;",
    cdot: "&middot;",
    times: "&times;",
    div: "&divide;",
    pm: "&plusmn;",
    mp: "&#8723;",
    leq: "&le;",
    le: "&le;",
    geq: "&ge;",
    ge: "&ge;",
    neq: "&ne;",
    approx: "&asymp;",
    sim: "&sim;",
    propto: "&prop;",
    to: "&rarr;",
    rightarrow: "&rarr;",
    leftarrow: "&larr;",
    leftrightarrow: "&harr;",
    Rightarrow: "&rArr;",
    Leftarrow: "&lArr;",
    degree: "&deg;",
    prime: "&prime;",
    log: "log",
    ln: "ln",
    exp: "exp",
    sin: "sin",
    cos: "cos",
    tan: "tan",
    lim: "lim",
    min: "min",
    max: "max",
  };
  if (Object.prototype.hasOwnProperty.call(symbols, command)) return symbols[command];
  if (command === "," || command === ";" || command === ":" || command === " ") return " ";
  return escapeHtml(command);
}

function looksLikeInlineFormula(source) {
  const compact = String(source || "").replace(/\s+/g, "");
  if (!compact) return false;
  return (
    /\\[A-Za-z]+/.test(source) ||
    /[A-Za-z][A-Za-z0-9_{}]*[=+\-*/^<>]/.test(compact) ||
    /[=+\-*/^<>][A-Za-z]/.test(compact) ||
    /[A-Za-z]\d/.test(compact)
  );
}

function looksLikeDisplayFormula(source) {
  const value = String(source || "").trim();
  if (!value || value.length > 600) return false;
  if (looksLikeChemicalEquation(value)) return true;
  if (/\\(?:frac|dfrac|tfrac|sqrt|sum|int|prod|lim|alpha|beta|gamma|delta|theta|lambda|mu|sigma|pi|partial|nabla)\b/.test(value)) {
    return true;
  }
  if (!/[=<>]|->|<=>|\\to|\\rightarrow/.test(value)) return false;
  if (/\b(the|because|therefore|using|where|paper|study|model)\b/i.test(value)) return false;
  return /^[A-Za-z0-9\\()[\]{}_^+\-*/=<>.,:; ]+$/.test(value);
}

function looksLikeChemicalEquation(source) {
  const value = String(source || "").trim();
  return /\\ce\{/.test(value) || (/(?:->|<=>|<->|=>|\\to|\\rightarrow)/.test(value) && /[A-Z][a-z]?\d*/.test(value));
}

function formatChemicalEquationHtml(source) {
  let value = String(source || "").trim();
  if (value.startsWith("\\ce")) {
    value = readLatexArgument(value, 3).value;
  }
  value = value
    .replace(/\\rightarrow|\\to/g, " -> ")
    .replace(/\\leftarrow/g, " <- ")
    .replace(/\\rightleftharpoons|\\leftrightarrow/g, " <=> ")
    .replace(/<=>|<->/g, " __EQ__ ")
    .replace(/=>|->/g, " __RIGHT__ ")
    .replace(/<-/g, " __LEFT__ ")
    .replace(/\s+\+\s+/g, " + ")
    .replace(/\s+/g, " ")
    .trim();

  if (!value) return "";
  return value
    .split(" ")
    .map((token) => renderChemicalToken(token))
    .join(" ");
}

function renderChemicalToken(token) {
  if (token === "__EQ__") return "&#8652;";
  if (token === "__RIGHT__") return "&rarr;";
  if (token === "__LEFT__") return "&larr;";
  if (token === "+") return "+";

  let html = "";
  for (let index = 0; index < token.length; index += 1) {
    const character = token[index];
    const charge = token.slice(index).match(/^\d+[+-]$/);
    if (charge && index > 0) {
      html += `<sup>${toSuperscriptHtml(charge[0])}</sup>`;
      break;
    }
    if (character === "^") {
      const chargeMatch = token.slice(index + 1).match(/^[0-9+\-]+/);
      const chargeText = chargeMatch ? chargeMatch[0] : "";
      html += `<sup>${toSuperscriptHtml(chargeText)}</sup>`;
      index += chargeText.length;
      continue;
    }
    if ((character === "+" || character === "-") && index === token.length - 1 && index > 0) {
      html += `<sup>${toSuperscriptHtml(character)}</sup>`;
      continue;
    }
    if (/\d/.test(character) && index > 0 && /[A-Za-z)\]]/.test(token[index - 1])) {
      html += toSubscriptHtml(character);
      continue;
    }
    html += escapeHtml(character);
  }
  return html;
}

function toSubscriptHtml(value) {
  const map = {
    "0": "&#8320;",
    "1": "&#8321;",
    "2": "&#8322;",
    "3": "&#8323;",
    "4": "&#8324;",
    "5": "&#8325;",
    "6": "&#8326;",
    "7": "&#8327;",
    "8": "&#8328;",
    "9": "&#8329;",
  };
  return String(value)
    .split("")
    .map((character) => map[character] || escapeHtml(character))
    .join("");
}

function toSuperscriptHtml(value) {
  const map = {
    "0": "&#8304;",
    "1": "&#185;",
    "2": "&#178;",
    "3": "&#179;",
    "4": "&#8308;",
    "5": "&#8309;",
    "6": "&#8310;",
    "7": "&#8311;",
    "8": "&#8312;",
    "9": "&#8313;",
    "+": "&#8314;",
    "-": "&#8315;",
  };
  return String(value)
    .split("")
    .map((character) => map[character] || escapeHtml(character))
    .join("");
}

async function api(path, options = {}) {
  const init = { method: options.method || "GET" };
  if (options.body) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

function setBusy(isBusy) {
  document.querySelectorAll("button").forEach((button) => {
    if (button.id !== "refreshMessagesBtn") button.disabled = isBusy;
  });
}

function emptyCard(text) {
  const card = document.createElement("article");
  card.className = "card";
  card.textContent = text;
  return card;
}

function scrollMessages() {
  const messages = el("messages");
  messages.scrollTop = messages.scrollHeight;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function stripSourcesBlock(content) {
  return String(content || "").replace(/\n+### Sources[\s\S]*$/i, "").trim();
}

function initTheme() {
  const saved = localStorage.getItem("rc-theme") || "light";
  setTheme(saved);
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("rc-theme", theme);
  const toggle = el("themeToggle");
  if (toggle) toggle.checked = theme === "dark";
}
