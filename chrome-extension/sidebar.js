(() => {
  if (document.getElementById("dy-archive-sidebar")) return;
  const root = document.createElement("aside");
  root.id = "dy-archive-sidebar";
  document.documentElement.classList.add("dy-archive-open");
  document.body.appendChild(root);

  const call = (message) => new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      response?.ok ? resolve(response.data) : reject(new Error(response?.error || "操作失败"));
    });
  });
  const api = (path, body) => call({ action: "api", path, body });
  let authors = [];
  let selected = new Set();
  let archiveAuthors = [];
  let archiveChecks = {};
  let archiveMetaById = new Map();
  let timer = null;
  const savedDir = () => localStorage.getItem("dyArchiveDownloadDir") || "";
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));

  function shell(body) {
    root.innerHTML = `<div class="dy-head"><div class="dy-logo">抖音<em>珍藏</em></div><div class="dy-spacer"></div><button class="dy-icon" id="dy-settings">⋮</button><button class="dy-icon" id="dy-close">×</button></div><div class="dy-body">${body}</div>`;
    root.querySelector("#dy-close").onclick = () => {
      root.remove(); document.documentElement.classList.remove("dy-archive-open");
      if (timer) clearInterval(timer);
    };
    root.querySelector("#dy-settings").onclick = folderScreen;
  }

  function mainScreen() {
    if (timer) { clearInterval(timer); timer = null; }
    shell(`<div class="dy-center">
      <button class="dy-big" id="dy-like">下载我曾点赞的所有作品</button>
      <button class="dy-big" id="dy-collect">下载我收藏的所有作品</button>
      <button class="dy-big" id="dy-following">挑选我关注的人下载其作品</button>
      <button class="dy-library" id="dy-library">打开本地库</button>
    </div><div class="dy-status" id="dy-status">本机服务连接中…</div>`);
    root.querySelector("#dy-like").onclick = () => accountDownload("like");
    root.querySelector("#dy-collect").onclick = () => accountDownload("collect");
    root.querySelector("#dy-following").onclick = followingFlow;
    root.querySelector("#dy-library").onclick = openLibrary;
    refreshStatus();
  }

  function folderScreen() {
    shell(`<div class="dy-center">
      <button class="dy-big" id="dy-use-folder">指定目标文件夹</button>
      <input class="dy-field" id="dy-folder" placeholder="例如 D:\\抖音备份" value="${savedDir()}">
      <p class="dy-note">输入完整路径后保存。旧抖珍藏归档可继续沿用，不会重复下载。</p>
    </div><div class="dy-bottom"><button class="dy-nav" id="dy-back">‹ 返回</button><button class="dy-nav" id="dy-save">保存 ›</button></div>`);
    root.querySelector("#dy-use-folder").onclick = async () => {
      const button = root.querySelector("#dy-use-folder");
      button.disabled = true;
      button.textContent = "正在打开系统文件夹选择器…";
      try {
        const result = await api("/api/select-folder", {
          initial_dir: root.querySelector("#dy-folder").value.trim()
        });
        if (result.path) {
          root.querySelector("#dy-folder").value = result.path;
          localStorage.setItem("dyArchiveDownloadDir", result.path);
        }
      } catch (error) {
        alert(error.message);
      } finally {
        button.disabled = false;
        button.textContent = "指定目标文件夹";
      }
    };
    root.querySelector("#dy-back").onclick = mainScreen;
    root.querySelector("#dy-save").onclick = () => {
      localStorage.setItem("dyArchiveDownloadDir", root.querySelector("#dy-folder").value.trim());
      mainScreen();
    };
  }

  async function ensureLogin() {
    await call({ action: "syncCookies" });
  }

  async function accountDownload(mode) {
    try {
      await ensureLogin();
      await api("/api/account-download", { mode, download_dir: savedDir() });
      progressScreen(mode === "like" ? "正在下载点赞作品…" : "正在下载收藏作品…");
    } catch (error) { alert(error.message); }
  }

  async function openLibrary() {
    try {
      await api("/api/open-library", { archive_dir: savedDir() });
    } catch (error) { alert(error.message); }
  }

  async function loadArchiveAuthors() {
    if (!savedDir()) {
      archiveAuthors = [];
      return;
    }
    const result = await api("/api/archive-authors", { archive_dir: savedDir() });
    archiveAuthors = result.authors || [];
    archiveChecks = result.checks || {};
    archiveMetaById = new Map();
    archiveAuthors.forEach((author) => {
      if (author.uid) archiveMetaById.set(`uid:${author.uid}`, author);
      if (author.sec_uid) archiveMetaById.set(`sec:${author.sec_uid}`, author);
    });
  }

  async function followingFlow() {
    progressScreen("正在打开您的关注列表…");
    try {
      if (timer) { clearInterval(timer); timer = null; }
      await ensureLogin();
      await api("/api/sync", { download_dir: savedDir() });
      timer = setInterval(async () => {
        const status = await api("/api/status");
        updateProgress(status);
        if (status.status === "completed") {
          clearInterval(timer); timer = null;
          const result = await api("/api/following");
          authors = result.authors;
          await loadArchiveAuthors();
          selectionScreen();
        } else if (status.status === "failed") {
          clearInterval(timer); timer = null;
          alert(status.logs?.slice(-1)[0] || "关注列表同步失败");
          mainScreen();
        }
      }, 1200);
    } catch (error) { alert(error.message); mainScreen(); }
  }

  function progressScreen(text) {
    shell(`<div class="dy-center"><p class="dy-note">${text}</p><div class="dy-status" id="dy-progress">准备中…</div></div><div class="dy-bottom"><button class="dy-nav" id="dy-back">‹ 返回</button></div>`);
    root.querySelector("#dy-back").onclick = mainScreen;
    timer = setInterval(refreshStatus, 1200);
  }

  function updateProgress(status) {
    const target = root.querySelector("#dy-progress") || root.querySelector("#dy-status");
    if (target) target.textContent = status.logs?.slice(-8).join("\n") || status.status;
  }

  async function refreshStatus() {
    try { updateProgress(await api("/api/status")); }
    catch (_error) {
      const target = root.querySelector("#dy-status");
      if (target) target.textContent = "请先启动“浏览器扩展服务”";
    }
  }

  function authorArchiveMeta(author) {
    return archiveMetaById.get(`uid:${author.uid}`)
      || archiveMetaById.get(`sec:${author.sec_uid}`)
      || {};
  }

  function authorLastChecked(author) {
    return Number(archiveChecks[author.sec_uid]
      || authorArchiveMeta(author).last_checked
      || 0);
  }

  function authorArchiveState(author) {
    if (Number(archiveChecks[author.sec_uid] || 0) > 0) return "library";
    return authorArchiveMeta(author).state || "pending";
  }

  function lastCheckedText(timestamp) {
    if (!timestamp) return "从未";
    const days = Math.floor((Date.now() / 1000 - Number(timestamp)) / 86400);
    if (days <= 0) return "今天";
    if (days === 1) return "昨天";
    return `${days}天前`;
  }

  function selectionScreen(resetSelection = true) {
    if (timer) { clearInterval(timer); timer = null; }
    const groups = { library: [], pending: [], ignored: [] };
    authors.forEach((author) => {
      const state = authorArchiveState(author);
      groups[state].push(author);
    });
    if (resetSelection) {
      selected = new Set(groups.library.map((author) => author.sec_uid));
    }
    const row = (author) => {
      const name = author.nickname || author.unique_id || author.sec_uid;
      const initial = name.trim().slice(0, 1) || "抖";
      const avatar = author.avatar_url
        ? `<img class="dy-avatar" src="${esc(author.avatar_url)}" alt="">`
        : "";
      return `<label class="dy-author">
        <input type="checkbox" data-id="${esc(author.sec_uid)}" ${selected.has(author.sec_uid) ? "checked" : ""}>
        <span class="dy-avatar-wrap">${avatar}<span class="dy-avatar-fallback">${esc(initial)}</span></span>
        <span class="dy-author-name">${esc(name)}</span>
      </label>`;
    };
    const pendingSelected = groups.pending.filter((author) => selected.has(author.sec_uid)).length;
    shell(`<div class="dy-limit">您可以下载 <strong>无限</strong> 位作者。</div>
      <details><summary>已在本地库，检查更新（${groups.library.length}）</summary>
        <div class="dy-authors">${groups.library.map(row).join("") || '<p class="dy-empty">暂无</p>'}</div>
      </details>
      <details open><summary>即将加入本地库（<span id="dy-pending-count">${pendingSelected}</span> / ${groups.pending.length}）</summary>
        <div class="dy-authors">${groups.pending.map(row).join("") || '<p class="dy-empty">暂无</p>'}</div>
      </details>
      <details><summary>不需要（${groups.ignored.length}）</summary>
        <div class="dy-authors">${groups.ignored.map(row).join("") || '<p class="dy-empty">暂无</p>'}</div>
      </details>
      <div class="dy-bottom"><button class="dy-nav" id="dy-back">‹ 返回</button><button class="dy-nav" id="dy-confirm">确定 ›</button></div>`);
    root.querySelectorAll(".dy-avatar").forEach((image) => {
      image.onload = () => image.parentElement.classList.add("has-avatar");
      image.onerror = () => image.remove();
    });
    const pendingIds = new Set(groups.pending.map((author) => author.sec_uid));
    root.querySelectorAll("input[data-id]").forEach((box) => box.onchange = () => {
      box.checked ? selected.add(box.dataset.id) : selected.delete(box.dataset.id);
      root.querySelector("#dy-pending-count").textContent =
        [...selected].filter((id) => pendingIds.has(id)).length;
    });
    root.querySelector("#dy-back").onclick = mainScreen;
    root.querySelector("#dy-confirm").onclick = async () => {
      try {
        if (!selected.size) throw new Error("请至少选择一位作者");
        reviewScreen();
      } catch (error) { alert(error.message); }
    };
  }

  function reviewScreen() {
    const chosen = authors.filter((author) => selected.has(author.sec_uid));
    shell(`<button class="dy-run-back" id="dy-back">‹</button>
      <div class="dy-review">
        <p>如果一位作者最近
          <input class="dy-days" id="dy-days" type="number" min="0" max="3650" value="0">
          天之内检查过，则本次暂时跳过。</p>
        <div class="dy-review-counts">
          <p>将访问: <strong id="dy-visit-count">${chosen.length}</strong> 人</p>
          <p>将跳过: <strong id="dy-skip-count">0</strong> 人</p>
        </div>
      </div>
      <div class="dy-bottom dy-start-bottom"><button class="dy-nav dy-start" id="dy-start">开始 ›</button></div>`);
    const eligible = () => {
      const days = Math.max(0, Number(root.querySelector("#dy-days").value) || 0);
      const cutoff = Date.now() / 1000 - days * 86400;
      return chosen.filter((author) => {
        const checked = authorLastChecked(author);
        return !days || !checked || checked < cutoff;
      });
    };
    const updateCounts = () => {
      const visit = eligible().length;
      root.querySelector("#dy-visit-count").textContent = visit;
      root.querySelector("#dy-skip-count").textContent = chosen.length - visit;
    };
    root.querySelector("#dy-days").oninput = updateCounts;
    root.querySelector("#dy-back").onclick = () => selectionScreen(false);
    root.querySelector("#dy-start").onclick = async () => {
      const queue = eligible();
      if (!queue.length) {
        alert("所有作者都在跳过范围内，请调小天数后再开始。");
        return;
      }
      try {
        const result = await api("/api/download", {
          selected_sec_uids: queue.map((author) => author.sec_uid)
        });
        downloadProgressScreen(result.authors || queue);
      } catch (error) { alert(error.message); }
    };
  }

  function queueRow(author) {
    const name = author.nickname || author.unique_id || author.sec_uid;
    const initial = name.trim().slice(0, 1) || "抖";
    const avatar = author.avatar_url
      ? `<img class="dy-avatar" src="${esc(author.avatar_url)}" alt="">`
      : "";
    const statusText = {
      downloading: "下载中",
      completed: "已完成",
      failed: "失败",
      waiting: "等待中"
    }[author.status] || "等待中";
    return `<div class="dy-queue-row">
      <span class="dy-avatar-wrap">${avatar}<span class="dy-avatar-fallback">${esc(initial)}</span></span>
      <span class="dy-queue-name">${esc(name)}</span>
      <span class="dy-queue-state ${esc(author.status || "waiting")}">${statusText}
        <small>上次检查: ${lastCheckedText(author.last_checked || authorLastChecked(author))}</small>
      </span>
    </div>`;
  }

  function downloadProgressScreen(queue) {
    const initial = {
      status: "running",
      current: 0,
      total: queue.length,
      message: "准备开始…",
      authors: queue.map((author) => ({
        ...author,
        status: "waiting",
        last_checked: authorLastChecked(author),
        local_count: 0,
        downloaded: 0
      }))
    };
    shell(`<button class="dy-run-back" id="dy-back">‹</button>
      <div class="dy-run-counter" id="dy-run-counter">0 / ${queue.length}</div>
      <div class="dy-run-message" id="dy-run-message">准备开始…</div>
      <div class="dy-run-detail">正在读取作者主页并下载新增作品…</div>
      <div class="dy-run-metrics">
        <div><span>已处理至:</span><strong id="dy-current-index">第0个</strong></div>
        <div><span>本次新增:</span><strong id="dy-new-count">-</strong></div>
        <div><span>作者作品数:</span><strong id="dy-official-count">-</strong></div>
        <div><span>本地已有:</span><strong id="dy-local-count">-</strong></div>
      </div>
      <div class="dy-queue" id="dy-queue"></div>`);
    root.querySelector("#dy-back").onclick = mainScreen;
    const render = (progress) => {
      const list = progress.authors || [];
      const current = list[Math.max(0, Number(progress.current || 1) - 1)] || {};
      root.querySelector("#dy-run-counter").textContent =
        `${progress.current || 0} / ${progress.total || list.length}`;
      root.querySelector("#dy-run-message").textContent = progress.message || "处理中…";
      root.querySelector("#dy-current-index").textContent = `第${progress.current || 0}个`;
      root.querySelector("#dy-new-count").textContent =
        current.downloaded === undefined ? "-" : `${current.downloaded}个`;
      root.querySelector("#dy-official-count").textContent =
        current.aweme_count ? `${current.aweme_count}个` : "-";
      root.querySelector("#dy-local-count").textContent =
        current.local_count === undefined ? "-" : `${current.local_count}个`;
      root.querySelector("#dy-queue").innerHTML = list.map(queueRow).join("");
      root.querySelectorAll(".dy-avatar").forEach((image) => {
        image.onload = () => image.parentElement.classList.add("has-avatar");
        image.onerror = () => image.remove();
      });
    };
    render(initial);
    if (timer) clearInterval(timer);
    timer = setInterval(async () => {
      try {
        const status = await api("/api/status");
        const progress = status.download_progress;
        if (progress?.authors) render(progress);
        if (status.status === "completed" || status.status === "failed") {
          clearInterval(timer);
          timer = null;
        }
      } catch (_error) {}
    }, 1000);
  }

  mainScreen();
})();
