const $ = (id) => document.getElementById(id);
const SCRIPT_ID = "nbh-bridge";

function setStatus(msg, ok = true) {
  $("status").textContent = msg;
  $("status").style.color = ok ? "#02a64b" : "#d33";
}

chrome.storage.local.get("appOrigin").then(({ appOrigin }) => {
  if (appOrigin) {
    $("origin").value = appOrigin;
    setStatus(`등록됨: ${appOrigin}`);
  }
});

$("save").onclick = async () => {
  let origin;
  try {
    origin = new URL($("origin").value.trim()).origin;
  } catch {
    return setStatus("주소 형식이 올바르지 않습니다. 예: http://192.168.0.10:8000", false);
  }
  const pattern = `${origin}/*`;

  // 크롬이 "이 사이트의 데이터 읽기" 권한을 물어본다 — 허용해야 연결된다.
  const granted = await chrome.permissions.request({ origins: [pattern] });
  if (!granted) return setStatus("권한이 허용되지 않아 연결하지 못했습니다.", false);

  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [SCRIPT_ID] });
  if (existing.length) await chrome.scripting.unregisterContentScripts({ ids: [SCRIPT_ID] });
  await chrome.scripting.registerContentScripts([
    { id: SCRIPT_ID, matches: [pattern], js: ["bridge.js"], runAt: "document_idle" },
  ]);
  await chrome.storage.local.set({ appOrigin: origin });
  setStatus(`저장했습니다: ${origin} — 도우미 화면을 새로고침하세요.`);
};
