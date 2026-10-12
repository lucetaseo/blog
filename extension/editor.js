// 네이버 블로그 글쓰기 화면(스마트에디터 ONE)에서 실행된다.
// 도우미가 넘겨준 글이 있으면 오른쪽 아래에 패널을 띄우고, 누르면 제목·본문을 채운다.
// 발행은 담당자가 직접 확인하고 누른다.
(() => {
  const POST_MAX_AGE_MS = 6 * 60 * 60 * 1000;

  // 스마트에디터 구조가 바뀌면 여기 선택자만 고치면 된다.
  const TITLE_SELECTORS = [
    ".se-documentTitle .se-text-paragraph",
    ".se-title-text .se-text-paragraph",
    ".se-documentTitle [contenteditable='true']",
  ];
  const BODY_SELECTORS = [
    ".se-component.se-text .se-text-paragraph",
    ".se-content .se-text-paragraph",
  ];

  const findTitle = () => {
    for (const s of TITLE_SELECTORS) {
      const el = document.querySelector(s);
      if (el) return el;
    }
    return null;
  };
  const findBody = () => {
    for (const s of BODY_SELECTORS) {
      const el = [...document.querySelectorAll(s)].find((e) => !e.closest(".se-documentTitle, .se-title-text"));
      if (el) return el;
    }
    return null;
  };

  function waitForEditor(timeoutMs = 30000) {
    return new Promise((resolve) => {
      if (findTitle() || findBody()) return resolve(true);
      const obs = new MutationObserver(() => {
        if (findTitle() || findBody()) { obs.disconnect(); clearTimeout(t); resolve(true); }
      });
      obs.observe(document.documentElement, { childList: true, subtree: true });
      const t = setTimeout(() => { obs.disconnect(); resolve(false); }, timeoutMs);
    });
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) => String(s || "").replace(/[\s\u200b\ufeff]+/g, "");

  function placeCaretAtEnd(el) {
    el.scrollIntoView({ block: "center" });
    el.click();
    const editable = el.closest("[contenteditable='true']") || el;
    editable.focus();
    // 커서는 문단 안 마지막 글자 노드 끝에 둔다 (빈 문단도 에디터가 자리표시 글자를 넣어 둔다).
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let last = null;
    while (walker.nextNode()) last = walker.currentNode;
    const range = document.createRange();
    if (last) range.setStart(last, last.length);
    else { range.selectNodeContents(el); range.collapse(false); }
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    return editable;
  }

  // 에디터가 실제 붙여넣기와 똑같이 처리하도록 paste 이벤트를 보낸다.
  function dispatchPaste(target, html, text) {
    const dt = new DataTransfer();
    if (html) dt.setData("text/html", html);
    dt.setData("text/plain", text);
    target.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  }

  async function fillTitle(title) {
    const el = findTitle();
    if (!el) return false;
    if (norm(el.textContent).includes(norm(title))) return true;
    const target = placeCaretAtEnd(el);
    document.execCommand("insertText", false, title);
    await sleep(200);
    if (norm(findTitle()?.textContent).includes(norm(title))) return true;
    dispatchPaste(target, null, title);
    await sleep(300);
    return norm(findTitle()?.textContent).includes(norm(title));
  }

  async function fillBody(post) {
    const el = findBody();
    if (!el) return false;
    const probe = norm(post.text).slice(0, 15);
    const bodyText = () => norm(document.querySelector(".se-content, .se-main-container")?.textContent || findBody()?.textContent);
    if (probe && bodyText().includes(probe)) return true;

    const target = placeCaretAtEnd(el);
    dispatchPaste(target, post.html, post.text);
    await sleep(500);
    if (bodyText().includes(probe)) return true;
    document.execCommand("insertHTML", false, post.html);
    await sleep(300);
    return bodyText().includes(probe);
  }

  async function copyToClipboard(text, html) {
    try {
      if (html) {
        await navigator.clipboard.write([new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" }),
        })]);
      } else {
        await navigator.clipboard.writeText(text);
      }
      return true;
    } catch {
      return false;
    }
  }

  function buildPanel(post) {
    const host = document.createElement("div");
    host.id = "nbh-panel-host";
    host.style.cssText = "position:fixed;right:20px;bottom:20px;z-index:2147483647;";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        .p { width: 290px; background: #fff; border: 2px solid #03c75a; border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,.18);
             font: 14px -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; color: #222; padding: 14px; }
        .h { display: flex; justify-content: space-between; align-items: center; font-weight: 700; color: #02a64b; margin-bottom: 8px; }
        .x { border: 0; background: none; font-size: 18px; cursor: pointer; color: #888; }
        .t { background: #f5f6f8; border-radius: 6px; padding: 6px 8px; margin-bottom: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        button.b { width: 100%; padding: 9px; margin-top: 6px; border-radius: 6px; border: 1px solid #ddd; background: #fff; cursor: pointer; font: inherit; }
        button.main { background: #03c75a; border-color: #03c75a; color: #fff; font-weight: 700; }
        .row { display: flex; gap: 6px; } .row button.b { flex: 1; }
        .m { margin-top: 10px; font-size: 13px; line-height: 1.5; white-space: pre-line; }
        .ok { color: #02a64b; } .err { color: #d33; }
        .s { margin-top: 8px; font-size: 12px; color: #888; }
      </style>
      <div class="p">
        <div class="h"><span>📝 블로그 글쓰기 도우미</span><button class="x" title="닫기">×</button></div>
        <div class="t"></div>
        <button class="b main" data-a="fill">제목·본문 채워 넣기</button>
        <div class="row">
          <button class="b" data-a="title">제목 복사</button>
          <button class="b" data-a="body">본문 복사</button>
          <button class="b" data-a="tags">태그 복사</button>
        </div>
        <button class="b zip" data-a="zip">📷 사진 순서대로 받기 (ZIP)</button>
        <div class="m"></div>
        <div class="s">사진은 본문의 [사진 N] 자리에 직접 넣고, 확인 후 발행하세요.<br>
          <a href="#" data-a="done">발행했어요 (패널 닫고 완료 표시)</a></div>
      </div>`;
    root.querySelector(".t").textContent = post.title;
    if (!post.zipUrl) root.querySelector(".zip").remove();
    const msg = (text, ok = true) => {
      const m = root.querySelector(".m");
      m.textContent = text;
      m.className = "m " + (ok ? "ok" : "err");
    };

    root.addEventListener("click", async (e) => {
      const a = e.target.closest("[data-a]")?.dataset.a || (e.target.classList.contains("x") ? "close" : null);
      if (!a) return;
      e.preventDefault();
      if (a === "close") return host.remove();
      if (a === "zip") return window.open(post.zipUrl, "_blank");
      if (a === "done") {
        // 보관함에 저장된 글이면 도우미에도 "발행 완료"로 표시한다.
        if (post.postId) await chrome.runtime.sendMessage({ type: "markDone", postId: post.postId }).catch(() => {});
        await chrome.storage.local.remove("pendingPost");
        return host.remove();
      }
      if (a === "title") return msg((await copyToClipboard(post.title)) ? "제목을 복사했어요. 제목 칸에 붙여넣으세요." : "복사 실패", true);
      if (a === "body") return msg((await copyToClipboard(post.text, post.html)) ? "본문을 복사했어요. 본문에 붙여넣으세요 (Ctrl+V)." : "복사 실패", true);
      if (a === "tags") {
        const tags = (post.tags || []).map((t) => "#" + t).join(" ");
        return msg((await copyToClipboard(tags)) ? "태그를 복사했어요. 발행 창의 태그 칸에 붙여넣으세요." : "복사 실패", true);
      }
      if (a === "fill") {
        msg("채우는 중…");
        const titleOk = await fillTitle(post.title);
        const bodyOk = await fillBody(post);
        if (titleOk && bodyOk) return msg("제목과 본문을 넣었어요. 사진을 넣고 확인 후 발행하세요.");
        const failed = [!titleOk && "제목", !bodyOk && "본문"].filter(Boolean).join("·");
        msg(`${failed}을(를) 자동으로 넣지 못했어요.\n위의 복사 버튼으로 복사해서 직접 붙여넣어 주세요.`, false);
      }
    });

    document.body.appendChild(host);
  }

  async function main() {
    const { pendingPost } = await chrome.storage.local.get("pendingPost");
    if (!pendingPost || Date.now() - (pendingPost.savedAt || 0) > POST_MAX_AGE_MS) return;
    // 블로그 화면은 여러 프레임으로 되어 있어, 에디터가 있는 프레임에만 패널을 띄운다.
    if (!(await waitForEditor())) return;
    if (!document.getElementById("nbh-panel-host")) buildPanel(pendingPost);
  }

  main();
})();
