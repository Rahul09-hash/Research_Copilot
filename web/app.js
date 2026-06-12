const state = {
  workspaceId: null,
  chatId: null,
  activeView: "chat",
  isIncognito: false,
  settings: {},
};

let currentAbortController = null;

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

  const searchInput = el("chatSearchInput");
  const searchResults = el("chatSearchResults");
  let searchTimeout = null;

  searchInput.addEventListener("input", (e) => {
    clearTimeout(searchTimeout);
    const query = e.target.value.trim();
    
    if (!query) {
      searchResults.style.display = "none";
      return;
    }

    searchTimeout = setTimeout(async () => {
      try {
        const data = await api(`/api/chats/search?q=${encodeURIComponent(query)}`);
        searchResults.innerHTML = "";
        
        if (data.chats.length === 0) {
          searchResults.innerHTML = '<div class="search-result-item" style="color: var(--muted); cursor: default;">No chats found</div>';
        } else {
          for (const chat of data.chats) {
            const item = document.createElement("div");
            item.className = "search-result-item";
            
            const title = document.createElement("div");
            title.textContent = chat.title;
            
            const workspace = document.createElement("div");
            workspace.className = "search-result-workspace";
            workspace.textContent = chat.workspace_name;
            
            item.append(title, workspace);
            item.addEventListener("click", async () => {
              searchInput.value = "";
              searchResults.style.display = "none";
              
              const wasIncognito = state.isIncognito;
              const prevChatId = state.chatId;
              
              state.workspaceId = chat.workspace_id;
              state.chatId = chat.id;
              
              if (wasIncognito && prevChatId) {
                await api(`/api/chats/${prevChatId}`, { method: "DELETE" });
              }
              
              // Update Workspace select visually without triggering its onChange
              const wsSelect = el("workspaceSelect");
              for (let i = 0; i < wsSelect.options.length; i++) {
                if (Number(wsSelect.options[i].value) === Number(chat.workspace_id)) {
                  wsSelect.selectedIndex = i;
                  break;
                }
              }
              
              await loadChats();
              refreshActiveView();
            });
            searchResults.append(item);
          }
        }
        searchResults.style.display = "block";
      } catch (err) {
        console.error("Chat search failed", err);
      }
    }, 300);
  });

  document.addEventListener("click", (e) => {
    if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
      searchResults.style.display = "none";
    }
  });

  el("workspaceSelect").addEventListener("change", async (e) => {
    state.workspaceId = e.target.value;
    state.chatId = null;
    await loadChats();
    refreshActiveView();
  });
  
  el("editWorkspaceBtn").addEventListener("click", renameWorkspace);

  el("chatSelect").addEventListener("change", async (e) => {
    const prevChatId = state.chatId;
    const wasIncognito = state.isIncognito;
    
    state.chatId = e.target.value;
    
    if (wasIncognito && prevChatId) {
        // Self-destruct previous incognito chat when switching away
        await api(`/api/chats/${prevChatId}`, { method: "DELETE" });
        await loadChats();
        refreshActiveView();
    } else {
        refreshActiveView();
    }
  });
  
  el("editChatBtn").addEventListener("click", renameChat);
  el("archiveChatBtn").addEventListener("click", archiveChat);
  el("deleteChatBtn").addEventListener("click", deleteChat);

  el("addWorkspaceBtn").addEventListener("click", createWorkspace);
  el("addChatBtn").addEventListener("click", createChat);
  
  el("incognitoToggle").addEventListener("change", async (e) => {
      if (e.target.checked) {
          await createIncognitoChat();
      } else {
          const prevChatId = state.chatId;
          const wasIncognito = state.isIncognito;
          
          const data = await api(`/api/chats?workspace_id=${state.workspaceId}`);
          const normalChat = data.chats.find(c => !c.is_incognito);
          
          if (normalChat) {
              state.chatId = normalChat.id;
          } else {
              // Note: createChat will internally call loadChats and loadMessages
              await createChat();
          }
          
          if (wasIncognito && prevChatId) {
              await api(`/api/chats/${prevChatId}`, { method: "DELETE" });
          }
          await loadChats();
          await loadMessages();
      }
  });
  
  el("showArchivedBtn").addEventListener("click", showArchivedChats);
  el("closeArchiveModalBtn").addEventListener("click", () => {
      el("archiveModal").style.display = "none";
  });

  el("refreshMessagesBtn").addEventListener("click", loadMessages);
  el("chatForm").addEventListener("submit", sendMessage);
  el("stopBtn").addEventListener("click", () => {
      if (currentAbortController) {
          currentAbortController.abort();
      }
  });
  el("promptInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      el("chatForm").dispatchEvent(new Event("submit"));
    }
  });
  el("promptInput").addEventListener("paste", handlePaste);
  el("pdfInput").addEventListener("change", uploadFiles);
  el("folderInput").addEventListener("change", uploadFiles);
  el("noteForm").addEventListener("submit", saveNote);
  el("regenerateGraphBtn").addEventListener("click", () => loadGraph(true));
  el("literatureBtn").addEventListener("click", generateLiteratureReview);
  el("compareBtn").addEventListener("click", compareDocuments);
  if (el("micBtn")) el("micBtn").addEventListener("click", toggleRecording);
  el("themeToggle").addEventListener("change", (event) => {
    setTheme(event.target.checked ? "dark" : "light");
  });

  document.querySelectorAll("[data-export]").forEach((button) => {
    button.addEventListener("click", () => exportChat(button.dataset.export));
  });

  el("modelSelect").addEventListener("change", async (e) => {
    const newModel = e.target.value;
    await fetch("/api/config/model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: newModel })
    });
  });

  el("rerankerToggle").addEventListener("change", async (e) => {
    const isEnabled = e.target.checked;
    await fetch("/api/config/reranker", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: isEnabled })
    });
  });
}

async function bootstrap() {
  try {
    const config = await api("/api/bootstrap");
    el("embeddingStatus").textContent = config.settings.embedding;
    el("rerankerToggle").checked = !!config.settings.reranker;

    // Load available models
    try {
      const modelData = await api("/api/models");
      const select = el("modelSelect");
      select.innerHTML = "";
      modelData.models.forEach(modelName => {
        const option = document.createElement("option");
        option.value = modelName;
        option.textContent = modelName;
        if (modelName === modelData.active) {
          option.selected = true;
        }
        select.appendChild(option);
      });
    } catch (e) {
      console.error("Failed to load models", e);
    }

    const { workspaces } = await api("/api/workspaces");
    state.settings = config.settings;
    state.workspaceId = config.workspace_id;
    state.chatId = config.chat_id;

    renderWorkspaceOptions(workspaces);
    await loadChats();
  } catch (e) {
    console.error("Bootstrap failed", e);
  }
}

async function refreshActiveView() {
  if (state.activeView === "chat") await loadMessages();
  if (state.activeView === "documents") await loadDocuments();
  if (state.activeView === "notes") await loadNotes();
  if (state.activeView === "graph") {
    loadGraph();
  } else if (state.activeView === "images") {
    loadImages();
  } else if (state.activeView === "exports") {
    await loadExportDocuments();
  }
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

async function renameWorkspace() {
  const currentName = el("workspaceSelect").options[el("workspaceSelect").selectedIndex].text;
  const newName = prompt("Enter new workspace name:", currentName);
  if (!newName || newName === currentName) return;
  
  await api(`/api/workspaces/${state.workspaceId}`, {
    method: "PATCH",
    body: { name: newName }
  });
  const workspaces = await api("/api/workspaces");
  renderWorkspaceOptions(workspaces.workspaces);
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
  
  // Check if current chat is incognito
  const currentChat = data.chats.find(c => Number(c.id) === Number(state.chatId));
  state.isIncognito = currentChat ? !!currentChat.is_incognito : false;
  
  const toggle = el("incognitoToggle");
  if (toggle) toggle.checked = state.isIncognito;
  
  if (state.isIncognito) {
      el("chatSelect").style.backgroundColor = "rgba(255, 0, 0, 0.1)";
      el("chatSelect").style.borderColor = "var(--danger)";
      el("incognitoWarning").style.display = "block";
  } else {
      el("chatSelect").style.backgroundColor = "";
      el("chatSelect").style.borderColor = "";
      el("incognitoWarning").style.display = "none";
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

async function createIncognitoChat() {
  const result = await api("/api/chats/incognito", {
    method: "POST",
    body: { workspace_id: state.workspaceId },
  });
  state.chatId = result.chat_id;
  state.isIncognito = true;
  await loadChats();
  await loadMessages();
}

async function renameChat() {
  const currentName = el("chatSelect").options[el("chatSelect").selectedIndex].text.split(" #")[0];
  const newName = prompt("Enter new chat title:", currentName);
  if (!newName || newName === currentName) return;
  
  await api(`/api/chats/${state.chatId}`, {
    method: "PATCH",
    body: { title: newName }
  });
  await loadChats();
}

async function archiveChat() {
  if (!confirm("Are you sure you want to archive this chat? It will be hidden from the sidebar.")) return;
  
  await api(`/api/chats/${state.chatId}/archive`, {
    method: "POST"
  });
  
  state.chatId = null;
  await loadChats();
  await loadMessages();
}

async function deleteChat() {
  if (!confirm("Are you sure you want to permanently delete this chat? This cannot be undone.")) return;
  
  await api(`/api/chats/${state.chatId}`, {
    method: "DELETE"
  });
  
  state.chatId = null;
  await loadChats();
  await loadMessages();
}

async function showArchivedChats() {
    const data = await api(`/api/chats/archived?workspace_id=${state.workspaceId}`);
    const list = el("archiveList");
    list.innerHTML = "";
    
    if (data.chats.length === 0) {
        list.innerHTML = "<p style='color: var(--muted);'>No archived chats.</p>";
    } else {
        for (const chat of data.chats) {
            const row = document.createElement("div");
            row.style.display = "flex";
            row.style.justifyContent = "space-between";
            row.style.alignItems = "center";
            row.style.padding = "8px";
            row.style.border = "1px solid var(--line)";
            row.style.borderRadius = "4px";
            
            const title = document.createElement("span");
            title.textContent = `${chat.title} #${chat.id}`;
            row.append(title);
            
            const btn = document.createElement("button");
            btn.textContent = "Unarchive";
            btn.className = "secondary-btn";
            btn.style.fontSize = "12px";
            btn.style.padding = "4px 8px";
            btn.onclick = async () => {
                await api(`/api/chats/${chat.id}/unarchive`, { method: "POST" });
                await loadChats();
                el("archiveModal").style.display = "none";
            };
            row.append(btn);
            
            list.append(row);
        }
    }
    
    el("archiveModal").style.display = "flex";
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

let currentImageIds = [];

async function handlePaste(e) {
  const items = (e.clipboardData || e.originalEvent.clipboardData).items;
  for (const item of items) {
    if (item.type.indexOf("image") === 0) {
      e.preventDefault();
      const file = item.getAsFile();
      await uploadImage(file);
      break;
    }
  }
}

async function uploadImage(file) {
  const formData = new FormData();
  formData.append("workspace_id", state.workspaceId);
  formData.append("chat_id", state.chatId);
  formData.append("file", file);
  setBusy(true);
  try {
    const response = await fetch("/api/upload_image", { method: "POST", body: formData });
    const data = await response.json();
    if (data.error) throw new Error(data.error);
    currentImageIds.push(data.image_id);
    const imgEl = document.createElement("img");
    imgEl.src = `/api/images/${data.image_id}/content`;
    imgEl.style.cssText = "max-height: 60px; border-radius: 4px; border: 1px solid var(--line);";
    el("imagePreviewGallery").append(imgEl);
    el("imagePreviewContainer").classList.remove("hidden");
  } catch(e) {
    alert(e.message);
  } finally {
    setBusy(false);
  }
}

function clearImagePreview() {
  currentImageIds = [];
  el("imagePreviewContainer").classList.add("hidden");
  el("imagePreviewGallery").innerHTML = "";
}

async function loadMessages() {
  const data = await api(`/api/messages?chat_id=${state.chatId}`);
  const messages = el("messages");
  messages.innerHTML = "";
  const hidden = Math.max(0, data.total - data.messages.length);
  el("chatHint").textContent = hidden
    ? `Showing the latest ${data.messages.length} messages. ${hidden} older messages are stored.`
    : "Ask questions grounded in uploaded PDFs.";

  // Group messages by group_id
  const groups = new Map();
  const order = [];
  for (const message of data.messages) {
    const gid = message.group_id || String(message.id);
    if (!groups.has(gid)) {
      groups.set(gid, []);
      order.push(gid);
    }
    groups.get(gid).push(message);
  }

  let lastAssistantIndex = -1;
  for (let i = order.length - 1; i >= 0; i--) {
    const group = groups.get(order[i]);
    if (group && group.length > 0 && group[0].role === "assistant") {
      lastAssistantIndex = i;
      break;
    }
  }

  for (let i = 0; i < order.length; i++) {
    const gid = order[i];
    const group = groups.get(gid);
    const activeIndex = group.findIndex(m => m.is_active === 1);
    const idx = activeIndex >= 0 ? activeIndex : group.length - 1;
    const message = group[idx];
    
    const isLastAssistant = (i === lastAssistantIndex);
    
    addMessage(
      message.role, 
      message.content, 
      message.citations || [], 
      message.images || [], 
      message.id,
      {
        variants: group,
        currentIndex: idx,
        isLastAssistant
      }
    );
  }
  scrollMessages();
}

function addMessage(role, content = "", citations = [], images = [], messageId = null, variantData = null) {
  const item = document.createElement("article");
  item.className = `message ${role}`;
  if (messageId) {
    item.id = `msg-${messageId}`;
  }
  const label = document.createElement("span");
  label.className = "role";
  label.textContent = role;
  
  const body = document.createElement("div");
  body.className = "message-body";
  
  if (images && images.length) {
    const gallery = document.createElement("div");
    gallery.style.cssText = "display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;";
    for (const img of images) {
      const imgEl = document.createElement("img");
      imgEl.src = `/api/images/${img.id}/content`;
      imgEl.style.cssText = "max-height: 120px; border-radius: 4px; border: 1px solid var(--line); cursor: pointer;";
      imgEl.onclick = () => window.openImageViewer(imgEl.src, "Image Preview");
      gallery.append(imgEl);
    }
    body.append(gallery);
  }
  
  const textBody = document.createElement("div");
  renderRichText(textBody, content);
  body.append(textBody);
  
  item.style.position = "relative";
  const copyBtn = document.createElement("button");
  copyBtn.className = "action-btn copy-btn";
  copyBtn.innerHTML = "📋";
  copyBtn.title = "Copy to clipboard";
  copyBtn.onclick = () => {
    navigator.clipboard.writeText(textBody.dataset.rawText || textBody.textContent || content);
    copyBtn.innerHTML = "✅";
    setTimeout(() => copyBtn.innerHTML = "📋", 2000);
  };
  
  item.append(label, body);
  if (citations.length) item.append(renderSources(citations));
  
  const actionsBar = document.createElement("div");
  actionsBar.className = "message-actions";
  
  if (variantData) {
      if (variantData.isLastAssistant) {
          const retryBtn = document.createElement("button");
          retryBtn.className = "action-btn retry-btn";
          retryBtn.innerHTML = "↺";
          retryBtn.title = "Retry";
          retryBtn.onclick = () => retryMessage(messageId);
          actionsBar.append(retryBtn);
      }
      
      if (role === "user") {
          const editBtn = document.createElement("button");
          editBtn.className = "action-btn edit-btn";
          editBtn.innerHTML = "✎";
          editBtn.title = "Edit";
          editBtn.onclick = () => editMessage(messageId, textBody, item);
          actionsBar.append(editBtn);
      }
  }
  
  actionsBar.append(copyBtn);
  item.append(actionsBar);
  
  if (variantData && variantData.variants && variantData.variants.length > 1) {
          const footer = document.createElement("div");
          footer.style.display = "flex";
          footer.style.justifyContent = "space-between";
          footer.style.alignItems = "center";
          
          const navContainer = document.createElement("div");
          navContainer.className = "variant-nav";
          
          const prevBtn = document.createElement("button");
          prevBtn.innerHTML = "&lsaquo;";
          prevBtn.disabled = variantData.currentIndex === 0;
          prevBtn.onclick = () => switchVariant(variantData.variants[variantData.currentIndex - 1].id);
          
          const nextBtn = document.createElement("button");
          nextBtn.innerHTML = "&rsaquo;";
          nextBtn.disabled = variantData.currentIndex === variantData.variants.length - 1;
          nextBtn.onclick = () => switchVariant(variantData.variants[variantData.currentIndex + 1].id);
          
          const labelSpan = document.createElement("span");
          labelSpan.textContent = `${variantData.currentIndex + 1} / ${variantData.variants.length}`;
          
          navContainer.append(prevBtn, labelSpan, nextBtn);
          footer.append(navContainer);
          item.append(footer);
      }
  
  el("messages").append(item);
  scrollMessages();
  return textBody;
}

async function sendMessage(event) {
  event.preventDefault();
  const input = el("promptInput");
  const prompt = input.value.trim();
  if (!prompt && !currentImageIds.length) return;
  input.value = "";
  setBusy(true);
  
  const tempImageIds = [...currentImageIds];
  const imagesForRender = tempImageIds.map(id => ({id})); 
  clearImagePreview();
  
  addMessage("user", prompt, [], imagesForRender);
  const assistantBody = addMessage("assistant", "");
  const queue = [];
  let typing = true;
  typeInto(assistantBody, queue, () => typing);

  currentAbortController = new AbortController();
  const signal = currentAbortController.signal;
  el("sendBtn").style.display = "none";
  el("stopBtn").style.display = "block";

  try {
    const isDeepResearch = document.getElementById("deepResearchToggle")?.checked || false;
    const isDataAnalysis = document.getElementById("dataAnalystToggle")?.checked || false;
    
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
        workspace_id: state.workspaceId,
        chat_id: state.chatId,
        image_ids: tempImageIds,
        prompt,
        is_deep_research: isDeepResearch,
        is_data_analysis: isDataAnalysis,
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
    
    // Replace the streamed typing text with the final cleaned content from the server
    if (donePayload && donePayload.content) {
      renderRichText(assistantBody, donePayload.content);
    } else {
      renderRichText(assistantBody, assistantBody.dataset.rawText || assistantBody.textContent);
    }
    
    if (donePayload?.citations?.length) {
      assistantBody.parentElement.append(renderSources(donePayload.citations));
    }
  } catch (error) {
    if (error.name === "AbortError") {
        queue.push(...`\n\n*[Response stopped by user]*`.split(""));
    } else {
        queue.push(...`Error: ${error.message}`.split(""));
    }
    await waitForQueue(queue);
    typing = false;
    renderRichText(assistantBody, assistantBody.dataset.rawText || assistantBody.textContent);
  } finally {
    setBusy(false);
    currentAbortController = null;
    el("sendBtn").style.display = "block";
    el("stopBtn").style.display = "none";
    await loadMessages();
  }
}

async function editMessage(messageId, textBody, item) {
  const originalText = textBody.dataset.rawText || textBody.textContent;
  
  // Create editor UI
  const editorDiv = document.createElement("div");
  editorDiv.style.marginTop = "8px";
  
  const textarea = document.createElement("textarea");
  textarea.value = originalText;
  textarea.style.width = "100%";
  textarea.style.minHeight = "80px";
  textarea.style.padding = "8px";
  textarea.style.marginBottom = "8px";
  textarea.style.fontFamily = "inherit";
  
  const actionsDiv = document.createElement("div");
  actionsDiv.style.display = "flex";
  actionsDiv.style.gap = "8px";
  actionsDiv.style.justifyContent = "flex-end";
  
  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "Cancel";
  cancelBtn.onclick = () => {
    editorDiv.remove();
    textBody.style.display = "block";
    // Show buttons again
    Array.from(item.querySelectorAll(".edit-btn, .copy-btn")).forEach(b => b.style.display = "");
  };
  
  const saveBtn = document.createElement("button");
  saveBtn.textContent = "Save & Submit";
  saveBtn.style.background = "var(--accent)";
  saveBtn.style.color = "var(--panel)";
  saveBtn.onclick = async () => {
    const newText = textarea.value.trim();
    if (!newText || newText === originalText) {
      cancelBtn.onclick();
      return;
    }
    await submitEdit(messageId, newText);
  };
  
  actionsDiv.append(cancelBtn, saveBtn);
  editorDiv.append(textarea, actionsDiv);
  
  // Hide the original text and buttons
  textBody.style.display = "none";
  Array.from(item.querySelectorAll(".edit-btn, .copy-btn")).forEach(b => b.style.display = "none");
  
  textBody.parentElement.insertBefore(editorDiv, textBody.nextSibling);
  textarea.focus();
}

async function submitEdit(messageId, newPrompt) {
  setBusy(true);
  const queue = [];
  
  // Add a temporary assistant block below to stream into
  const assistantBody = addMessage("assistant", "");
  let typing = true;
  typeInto(assistantBody, queue, () => typing);

  currentAbortController = new AbortController();
  const signal = currentAbortController.signal;
  el("sendBtn").style.display = "none";
  el("stopBtn").style.display = "block";

  try {
    const isDeepResearch = document.getElementById("deepResearchToggle")?.checked || false;
    const isDataAnalysis = document.getElementById("dataAnalystToggle")?.checked || false;
    
    const response = await fetch("/api/chat/edit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
        workspace_id: state.workspaceId,
        message_id: messageId,
        prompt: newPrompt,
        is_deep_research: isDeepResearch,
        is_data_analysis: isDataAnalysis,
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
    
    if (donePayload && donePayload.content) {
      renderRichText(assistantBody, donePayload.content);
    } else {
      renderRichText(assistantBody, assistantBody.dataset.rawText || assistantBody.textContent);
    }
    
    if (donePayload?.citations?.length) {
      assistantBody.parentElement.append(renderSources(donePayload.citations));
    }
  } catch (error) {
    if (error.name === "AbortError") {
        queue.push(...`\n\n*[Response stopped by user]*`.split(""));
    } else {
        queue.push(...`Error: ${error.message}`.split(""));
    }
    await waitForQueue(queue);
    typing = false;
    renderRichText(assistantBody, assistantBody.dataset.rawText || assistantBody.textContent);
  } finally {
    setBusy(false);
    currentAbortController = null;
    el("sendBtn").style.display = "block";
    el("stopBtn").style.display = "none";
    await loadMessages();
  }
}

async function switchVariant(messageId) {
    try {
        await api(`/api/messages/${messageId}/activate`, { method: "POST" });
        await loadMessages();
    } catch (e) {
        alert(e.message);
    }
}

async function retryMessage(messageId) {
  setBusy(true);
  const assistantBody = addMessage("assistant", "");
  const queue = [];
  let typing = true;
  typeInto(assistantBody, queue, () => typing);

  currentAbortController = new AbortController();
  const signal = currentAbortController.signal;
  el("sendBtn").style.display = "none";
  el("stopBtn").style.display = "block";

  try {
    const isDeepResearch = document.getElementById("deepResearchToggle")?.checked || false;
    const isDataAnalysis = document.getElementById("dataAnalystToggle")?.checked || false;
    
    const response = await fetch("/api/chat/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
        workspace_id: state.workspaceId,
        message_id: messageId,
        is_deep_research: isDeepResearch,
        is_data_analysis: isDataAnalysis,
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
    
    if (donePayload && donePayload.content) {
      renderRichText(assistantBody, donePayload.content);
    } else {
      renderRichText(assistantBody, assistantBody.dataset.rawText || assistantBody.textContent);
    }
    
    if (donePayload?.citations?.length) {
      assistantBody.parentElement.append(renderSources(donePayload.citations));
    }
  } catch (error) {
    if (error.name === "AbortError") {
        queue.push(...`\n\n*[Response stopped by user]*`.split(""));
    } else {
        queue.push(...`Error: ${error.message}`.split(""));
    }
    await waitForQueue(queue);
    typing = false;
    renderRichText(assistantBody, assistantBody.dataset.rawText || assistantBody.textContent);
  } finally {
    setBusy(false);
    currentAbortController = null;
    el("sendBtn").style.display = "block";
    el("stopBtn").style.display = "none";
    await loadMessages();
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
    source.href = "#";
    
    let url = citation.url || `/api/documents/${citation.document_id}/pdf#page=${citation.page_start || 1}`;
    
    // Use dynamic backend highlighting if chunk_id is available
    if (citation.chunk_id) {
      url = `/api/documents/${citation.document_id}/highlight/${citation.chunk_id}#page=${citation.page_start || 1}`;
    } else if (citation.snippet) {
      // Fallback for native browser highlighting
      const cleanSnippet = citation.snippet.replace(/\n/g, ' ').replace(/\s+/g, ' ');
      const exactText = encodeURIComponent(cleanSnippet.substring(0, 50));
      if (url.includes("#")) {
        url += `&search=${exactText}`;
      } else {
        url += `#search=${exactText}`;
      }
    }
    
    source.addEventListener("click", (e) => {
      e.preventDefault();
      window.openPdfViewer(url, citation.file_name);
    });

    const lineRange = citation.line_start
      ? `, lines ${citation.line_start}${citation.line_end && citation.line_end !== citation.line_start ? `-${citation.line_end}` : ""}`
      : "";
    source.textContent = `[${citation.number}] ${citation.file_name} p.${citation.page_start || "?"}${lineRange}`;
    source.title = "Open side-by-side PDF";
    sources.append(source);
  }
  return sources;
}

window.openPdfViewer = function(url, title) {
  document.querySelector(".main").classList.add("split-layout");
  el("pdfViewerPanel").classList.remove("hidden");
  el("pdfTitle").textContent = title || "Document Viewer";
  
  el("imageViewerImg").classList.add("hidden");
  el("imageViewerImg").src = "";
  
  el("pdfIframe").classList.remove("hidden");
  const iframe = el("pdfIframe");
  const newIframe = iframe.cloneNode();
  newIframe.src = url;
  iframe.replaceWith(newIframe);
};

window.openImageViewer = function(url, title) {
  document.querySelector(".main").classList.add("split-layout");
  el("pdfViewerPanel").classList.remove("hidden");
  el("pdfTitle").textContent = title || "Image Viewer";
  
  el("pdfIframe").classList.add("hidden");
  el("pdfIframe").src = "";
  
  el("imageViewerImg").classList.remove("hidden");
  el("imageViewerImg").src = url;
};

window.closePdfViewer = function() {
  document.querySelector(".main").classList.remove("split-layout");
  el("pdfViewerPanel").classList.add("hidden");
  el("pdfIframe").src = "";
  el("pdfIframe").classList.remove("hidden");
  el("imageViewerImg").src = "";
  el("imageViewerImg").classList.add("hidden");
};


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
        <button data-open="${doc.id}">Open PDF</button>
        <button data-reprocess="${doc.id}">Reprocess</button>
        <button class="danger" data-delete="${doc.id}">Delete</button>
      </div>
    `;
    list.append(card);
  }
  document.querySelectorAll("[data-open]").forEach((button) => {
    button.addEventListener("click", () => window.openPdfViewer(`/api/documents/${button.dataset.open}/pdf`));
  });
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

async function uploadFiles(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) return;
  
  const allowedExtensions = ['.pdf', '.csv', '.xlsx'];
  const validFiles = files.filter(file => {
      const name = file.name.toLowerCase();
      return allowedExtensions.some(ext => name.endsWith(ext));
  });

  if (!validFiles.length) {
      el("uploadStatus").textContent = "No valid files found (.pdf, .csv, .xlsx).";
      return;
  }

  setBusy(true);
  for (const file of validFiles) {
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

async function loadImages() {
  const data = await api(`/api/images?workspace_id=${state.workspaceId}`);
  const list = el("imagesList");
  list.innerHTML = "";
  if (!data.images.length) {
    list.innerHTML = '<div class="muted" style="grid-column: 1/-1;">No images uploaded yet. Paste an image into the chat to get started.</div>';
    return;
  }
  for (const img of data.images) {
    const div = document.createElement("div");
    div.style.cssText = "display: flex; flex-direction: column; gap: 8px; background: var(--panel); padding: 8px; border: 1px solid var(--line); border-radius: 8px;";
    
    const preview = document.createElement("img");
    preview.src = `/api/images/${img.id}/content`;
    preview.style.cssText = "width: 100%; height: 150px; object-fit: contain; background: var(--bg); border-radius: 4px; cursor: pointer;";
    preview.onclick = () => window.openImageViewer(preview.src, "Image Preview");
    
    const meta = document.createElement("div");
    meta.style.cssText = "font-size: 11px; color: var(--muted);";
    meta.textContent = new Date(img.created_at + 'Z').toLocaleString();
    
    const btn = document.createElement("button");
    btn.textContent = "Jump to Chat";
    btn.style.width = "100%";
    if (!img.chat_id) {
       btn.disabled = true;
       btn.textContent = "No chat linked";
    } else {
       btn.onclick = async () => {
         el("chatSelect").value = img.chat_id;
         state.chatId = img.chat_id;
         await loadMessages();
         switchView('chat');
         
         setTimeout(() => {
           const msgEl = document.getElementById(`msg-${img.message_id}`);
           if (msgEl) {
             const doScroll = () => msgEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
             doScroll();
             setTimeout(doScroll, 300);
             setTimeout(doScroll, 800);
             
             msgEl.style.transition = 'background-color 0.5s ease';
             msgEl.style.backgroundColor = 'var(--line)';
             setTimeout(() => msgEl.style.backgroundColor = 'transparent', 2000);
           }
         }, 100);
       };
    }
    
    div.append(preview, meta, btn);
    list.append(div);
  }
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
  if (kind === "pdf") {
    // Save current active view
    const activeView = document.querySelector(".view.active");
    const activeViewId = activeView ? activeView.id : "chatView";
    
    // Switch to Chat View for printing
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    el("chatView").classList.add("active");
    
    // Allow DOM to update before triggering print dialog
    setTimeout(() => {
      window.print();
      
      // Restore previous view after print dialog closes
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      if (el(activeViewId)) {
        el(activeViewId).classList.add("active");
      }
    }, 100);
    return;
  }

  el("exportResult").textContent = `Generating ${kind} export...`;
  try {
    const response = await fetch(`/api/export/${kind}?chat_id=${state.chatId}`, { method: "POST" });
    if (!response.ok) {
      throw new Error(`Export failed: ${response.statusText}`);
    }
    
    const contentDisposition = response.headers.get("Content-Disposition") || "";
    const match = contentDisposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : `export.${kind}`;
    
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    a.remove();
    
    el("exportResult").textContent = "Download complete!";
  } catch (err) {
    el("exportResult").textContent = err.message;
  }
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
  // Ensure headings have double newlines around them so they break into separate blocks
  const spacedText = text.replace(/^([ \t]*#{1,4}[ \t]+.+)$/gm, "\n\n$1\n\n");
  return spacedText
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
  const inlinePattern = /(\\\([\s\S]+?\\\)|\$[^$\n]{1,240}\$|!\[.*?\]\([^\)]+\))/g;
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = inlinePattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(escapeHtml(text.slice(lastIndex, match.index)));
    }
    const token = match[0];
    if (token.startsWith("![")) {
      const altMatch = token.match(/!\[(.*?)\]/);
      const urlMatch = token.match(/\((.*?)\)/);
      if (altMatch && urlMatch) {
        parts.push(`<img src="${escapeHtml(urlMatch[1])}" alt="${escapeHtml(altMatch[1])}" style="max-height:300px; border-radius:4px; margin-top:8px;" onclick="window.openImageViewer(this.src, this.alt)">`);
      } else {
        parts.push(escapeHtml(token));
      }
    } else {
      const formula = token.startsWith("\\(") ? token.slice(2, -2) : token.slice(1, -1);
      parts.push(looksLikeInlineFormula(formula) ? renderEquationSpan(formula) : escapeHtml(token));
    }
    lastIndex = inlinePattern.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(escapeHtml(text.slice(lastIndex)));
  }
  
  let html = parts.join("");
  // Simple bold and italic parsing
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
  html = html.replace(/`(.*?)`/g, '<code>$1</code>');
  return html;
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
    if (button.id !== "refreshMessagesBtn" && button.id !== "stopBtn") button.disabled = isBusy;
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

// --- Voice Recording Logic ---
let audioContext;
let audioProcessor;
let mediaStream;
let pcmChunks = [];
let isRecording = false;
let isTranscribingLive = false;
let basePromptText = "";
let lastLoudTime = Date.now();
let liveTranscriptionInterval;
let vadInterval;

async function sendPartialAudio() {
  if (isTranscribingLive || pcmChunks.length === 0 || !isRecording) return;
  isTranscribingLive = true;
  
  const totalLen = pcmChunks.reduce((acc, val) => acc + val.length, 0);
  const mergedPcm = new Float32Array(totalLen);
  let offset = 0;
  for (let chunk of pcmChunks) {
    mergedPcm.set(chunk, offset);
    offset += chunk.length;
  }
  
  const formData = new FormData();
  const blob = new Blob([mergedPcm.buffer], { type: "application/octet-stream" });
  formData.append("audio", blob, "audio.raw");
  
  try {
    const res = await fetch("/api/transcribe", { method: "POST", body: formData });
    const data = await res.json();
    if (data.text && isRecording) {
      const promptEl = document.getElementById("promptInput");
      promptEl.value = (basePromptText ? basePromptText + " " : "") + data.text;
    }
  } catch (e) {
    console.error("Live transcription error:", e);
  } finally {
    isTranscribingLive = false;
  }
}

async function stopRecording() {
  if (!isRecording) return;
  isRecording = false;
  clearInterval(liveTranscriptionInterval);
  clearInterval(vadInterval);
  
  const btn = document.getElementById("micBtn");
  if (btn) btn.classList.remove("recording");
  
  if (audioProcessor) audioProcessor.disconnect();
  if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());
  if (audioContext) audioContext.close();
  
  const promptEl = document.getElementById("promptInput");
  promptEl.placeholder = "Ask about your research... (Paste images with Ctrl+V)";
  
  // Final flush
  await sendPartialAudio();
}

async function toggleRecording() {
  if (isRecording) {
    await stopRecording();
    return;
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(mediaStream);
    audioProcessor = audioContext.createScriptProcessor(4096, 1, 1);
    
    pcmChunks = [];
    isRecording = true;
    lastLoudTime = Date.now();
    basePromptText = document.getElementById("promptInput").value.trim();
    document.getElementById("promptInput").placeholder = "Listening... (speak now)";
    
    const btn = document.getElementById("micBtn");
    if (btn) btn.classList.add("recording");
    
    audioProcessor.onaudioprocess = (e) => {
      const inputData = e.inputBuffer.getChannelData(0);
      pcmChunks.push(new Float32Array(inputData));
      
      let sum = 0;
      for (let i = 0; i < inputData.length; i++) {
        sum += inputData[i] * inputData[i];
      }
      const rms = Math.sqrt(sum / inputData.length);
      if (rms > 0.015) {
        lastLoudTime = Date.now();
      }
    };
    
    source.connect(audioProcessor);
    audioProcessor.connect(audioContext.destination);
    
    // Live stream transcription
    liveTranscriptionInterval = setInterval(sendPartialAudio, 1500);
    
    // VAD Auto-stop
    vadInterval = setInterval(() => {
      if (Date.now() - lastLoudTime > 2000) {
        stopRecording();
      }
    }, 200);
    
  } catch (err) {
    console.error(err);
    alert("Could not access microphone.");
  }
}

// Init
loadSettings().then(loadApp);

// Incognito Mode Cleanup on Close
window.addEventListener("beforeunload", () => {
    if (state.isIncognito && state.chatId) {
        fetch(`/api/chats/${state.chatId}`, { method: 'DELETE', keepalive: true });
    }
});
