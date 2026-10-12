// 1분마다 도우미 서버에 "발행할 시간이 된 글"이 있는지 묻고, 있으면 알림을 띄운다.
// 알림을 누르면 네이버 글쓰기 화면을 열고, 에디터 패널에서 바로 채워 넣을 수 있게 글을 준비해 둔다.
importScripts("config.js");
const DEFAULT_ORIGIN = NBH_CONFIG.appOrigin || "http://localhost:8000";
const DEFAULT_WRITE_URL = "https://blog.naver.com/GoBlogWrite.naver";

async function appOrigin() {
  const { appOrigin } = await chrome.storage.local.get("appOrigin");
  return appOrigin || DEFAULT_ORIGIN;
}

async function getJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

function setup() {
  chrome.alarms.create("check-due", { periodInMinutes: 1, delayInMinutes: 0.1 });
}
chrome.runtime.onInstalled.addListener(setup);
chrome.runtime.onStartup.addListener(setup);

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "check-due") checkDue();
});

async function checkDue() {
  let due;
  try {
    due = await getJson(`${await appOrigin()}/api/posts/due`);
  } catch {
    chrome.action.setBadgeText({ text: "" });
    return; // 서버가 꺼져 있으면 다음 확인 때 다시 시도
  }
  chrome.action.setBadgeBackgroundColor({ color: "#d33" });
  chrome.action.setBadgeText({ text: due.length ? String(due.length) : "" });

  const { notified = {} } = await chrome.storage.local.get("notified");
  const monthAgo = Date.now() - 30 * 24 * 60 * 60 * 1000;
  for (const [k, t] of Object.entries(notified)) if (t < monthAgo) delete notified[k];

  for (const post of due) {
    const key = `${post.id}@${post.scheduled_at}`; // 예정 시각을 바꾸면 다시 알린다
    if (notified[key]) continue;
    notified[key] = Date.now();
    chrome.notifications.create(`post:${post.id}`, {
      type: "basic",
      iconUrl: "icon128.png",
      title: "블로그 글 올릴 시간이에요 📝",
      message: post.title,
      contextMessage: `사진 ${post.photo_count}장 · ${post.post_type || "블로그 글"}`,
      buttons: [{ title: "네이버 에디터 열기" }, { title: "도우미에서 보기" }],
      requireInteraction: true,
    });
  }
  await chrome.storage.local.set({ notified });
}

async function openEditor(postId) {
  const origin = await appOrigin();
  try {
    const [post, defaults] = await Promise.all([
      getJson(`${origin}/api/posts/${postId}`),
      getJson(`${origin}/api/defaults`).catch(() => ({})),
    ]);
    await chrome.storage.local.set({
      pendingPost: {
        title: post.title,
        html: post.paste_html,
        text: post.paste_text,
        tags: post.tags,
        postId,
        zipUrl: `${origin}/api/posts/${postId}/photos.zip`,
        savedAt: Date.now(),
      },
    });
    chrome.tabs.create({ url: defaults.write_url || DEFAULT_WRITE_URL });
  } catch {
    chrome.tabs.create({ url: `${origin}/?post=${postId}` });
  }
}

chrome.notifications.onClicked.addListener((id) => {
  if (!id.startsWith("post:")) return;
  chrome.notifications.clear(id);
  openEditor(id.slice(5));
});

chrome.notifications.onButtonClicked.addListener(async (id, index) => {
  if (!id.startsWith("post:")) return;
  chrome.notifications.clear(id);
  const postId = id.slice(5);
  if (index === 0) openEditor(postId);
  else chrome.tabs.create({ url: `${await appOrigin()}/?post=${postId}` });
});

// 툴바 아이콘: 서버에 연결되면 보관함을, 안 되면 설정 화면을 연다.
chrome.action.onClicked.addListener(async () => {
  const origin = await appOrigin();
  try {
    await getJson(`${origin}/api/defaults`);
    chrome.tabs.create({ url: `${origin}/?view=archive` });
  } catch {
    chrome.runtime.openOptionsPage();
  }
});

// 에디터 패널의 "발행 완료" 버튼 — 콘텐츠 스크립트는 도우미 서버에 직접 요청할 수 없어 여기서 대신 보낸다.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type !== "markDone") return;
  (async () => {
    try {
      await getJson(`${await appOrigin()}/api/posts/${msg.postId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "done" }),
      });
      checkDue();
      sendResponse({ ok: true });
    } catch {
      sendResponse({ ok: false });
    }
  })();
  return true;
});
