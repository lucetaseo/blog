// 사내 글쓰기 도우미 화면에서 실행된다. 화면이 넘겨준 글을 확장 저장소에 보관한다.
(() => {
  const reply = (type) => window.postMessage({ source: "nbh-ext", type }, location.origin);

  window.addEventListener("message", async (e) => {
    if (e.source !== window || e.data?.source !== "nbh-app") return;
    if (e.data.type === "ping") reply("ready");
    if (e.data.type === "post") {
      const { title, html, text, tags } = e.data.post || {};
      await chrome.storage.local.set({
        pendingPost: { title, html, text, tags, savedAt: Date.now() },
      });
      reply("saved");
    }
  });

  reply("ready");
})();
