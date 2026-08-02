const BASE = "http://127.0.0.1:8765";

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

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message.action === "api") return api(message.path, message.body);
    if (message.action === "syncCookies") {
      const cookies = await chrome.cookies.getAll({ domain: "douyin.com" });
      const values = Object.fromEntries(cookies.map((item) => [item.name, item.value]));
      return api("/api/cookies", { cookies: values });
    }
    throw new Error("unknown action");
  })().then(
    (data) => sendResponse({ ok: true, data }),
    (error) => sendResponse({ ok: false, error: error.message })
  );
  return true;
});
