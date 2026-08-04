const BASE = "http://127.0.0.1:8766";
const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const response = await fetch(`${BASE}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Douyin-Archive": "douyin-archive-extension-v1"
    },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function message(text, bad = false) {
  $("status").textContent = text;
  $("status").style.color = bad ? "#ff786b" : "#eee";
}

async function useChromeLogin() {
  try {
    const cookies = await chrome.cookies.getAll({ domain: "douyin.com" });
    const values = Object.fromEntries(cookies.map((cookie) => [cookie.name, cookie.value]));
    const result = await api("/api/cookies", { cookies: values });
    message(`已读取当前登录（${result.cookie_count} 项 Cookie）`);
  } catch (error) {
    message(error.message, true);
  }
}

async function start(path, body = {}) {
  try {
    await api(path, body);
    message("任务已启动");
  } catch (error) {
    message(error.message, true);
  }
}

async function refresh() {
  try {
    await api("/api/health");
    $("dot").classList.add("ok");
    $("service").textContent = "本机服务已连接";
    const status = await api("/api/status");
    $("status").textContent = status.status === "running" ? "任务运行中…" :
      status.status === "completed" ? "任务完成" :
      status.status === "failed" ? `任务失败（${status.exit_code}）` : "准备就绪";
    $("count").textContent = status.following_count ? `${status.following_count} 位作者` : "";
    $("logs").textContent = status.logs.slice(-60).join("\n");
    $("logs").scrollTop = $("logs").scrollHeight;
  } catch (_error) {
    $("dot").classList.remove("ok");
    $("service").textContent = "请先双击“启动浏览器扩展服务.cmd”";
  }
}

$("login").addEventListener("click", useChromeLogin);
$("importOld").addEventListener("click", () =>
  start("/api/import-douzhencang", { archive_dir: $("oldArchiveDir").value.trim() }));
$("sync").addEventListener("click", () =>
  start("/api/sync", { download_dir: $("downloadDir").value.trim() }));
$("download").addEventListener("click", () => start("/api/download"));
$("stop").addEventListener("click", () => start("/api/stop"));
$("downloadDir").addEventListener("change", () =>
  chrome.storage.local.set({ downloadDir: $("downloadDir").value }));
chrome.storage.local.get(["downloadDir"]).then((value) => {
  $("downloadDir").value = value.downloadDir || "";
});
$("oldArchiveDir").addEventListener("change", () =>
  chrome.storage.local.set({ oldArchiveDir: $("oldArchiveDir").value }));
chrome.storage.local.get(["oldArchiveDir"]).then((value) => {
  $("oldArchiveDir").value = value.oldArchiveDir || "";
});
refresh();
setInterval(refresh, 1200);
