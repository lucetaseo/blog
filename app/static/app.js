// 네이버 블로그 글쓰기 도우미 — 화면 동작
const $ = (id) => document.getElementById(id);

const state = {
  files: [],        // { file, url } — 업로드 순서 = 사진 번호
  sessionId: null,
  topics: [],
  selected: -1,
  post: null,
};

// ---------- 공통 ----------
function showStep(n) {
  [1, 2, 3].forEach((i) => $("step" + i).classList.toggle("hidden", i !== n));
  document.querySelectorAll(".steps li").forEach((li) => li.classList.toggle("active", Number(li.dataset.step) === n));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function loading(on, text = "작업 중…") {
  $("loadingText").textContent = text;
  $("loading").classList.toggle("hidden", !on);
}

let toastTimer;
function toast(msg, isError = false) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("error", isError);
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), isError ? 5000 : 2000);
}

async function api(url, options) {
  const res = await fetch(url, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `요청 실패 (${res.status})`);
  return body;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- 1단계: 사진 ----------
function addFiles(list) {
  for (const file of list) {
    if (!file.type.startsWith("image/")) continue;
    if (state.files.length >= 20) { toast("사진은 최대 20장까지 올릴 수 있어요.", true); break; }
    state.files.push({ file, url: URL.createObjectURL(file) });
  }
  renderPreviews();
}

let dragFrom = null;
function renderPreviews() {
  const box = $("previews");
  box.innerHTML = "";
  state.files.forEach((f, i) => {
    const el = document.createElement("div");
    el.className = "thumb";
    el.draggable = true;
    el.innerHTML = `<img src="${f.url}" alt=""><span class="num">${i + 1}</span><button class="del" title="삭제">×</button>`;
    el.querySelector(".del").onclick = (e) => {
      e.preventDefault();
      URL.revokeObjectURL(f.url);
      state.files.splice(i, 1);
      renderPreviews();
    };
    el.addEventListener("dragstart", () => { dragFrom = i; el.classList.add("dragging"); });
    el.addEventListener("dragend", () => el.classList.remove("dragging"));
    el.addEventListener("dragover", (e) => e.preventDefault());
    el.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (dragFrom === null || dragFrom === i) return;
      const [moved] = state.files.splice(dragFrom, 1);
      state.files.splice(i, 0, moved);
      dragFrom = null;
      renderPreviews();
    });
    box.appendChild(el);
  });
  $("btnTopics").disabled = state.files.length === 0;
}

$("photos").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
const dz = $("dropzone");
dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
dz.addEventListener("dragleave", () => dz.classList.remove("over"));
dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("over"); addFiles(e.dataTransfer.files); });

$("btnTopics").onclick = async () => {
  const fd = new FormData();
  state.files.forEach((f) => fd.append("photos", f.file, f.file.name));
  for (const k of ["blog_name", "industry", "tone", "keywords", "memo"]) fd.append(k, $(k).value);
  try {
    loading(true, "사진을 살펴보고 주제를 고르는 중… (30초~1분)");
    const data = await api("/api/topics", { method: "POST", body: fd });
    state.sessionId = data.session_id;
    state.topics = data.topics;
    state.selected = -1;
    renderTopics(data.photo_notes);
    showStep(2);
  } catch (err) {
    toast(err.message, true);
  } finally {
    loading(false);
  }
};

// ---------- 2단계: 주제 ----------
function renderTopics(notes) {
  $("photoNotes").innerHTML = (notes || []).map((n) => `<li><b>사진 ${n.photo}</b> — ${esc(n.description)}</li>`).join("");
  const box = $("topics");
  box.innerHTML = "";
  state.topics.forEach((t, i) => {
    const el = document.createElement("div");
    el.className = "topic";
    el.innerHTML = `
      <h3>${i === 0 ? "⭐ " : ""}${esc(t.title)}</h3>
      <p>${esc(t.angle)}</p>
      <p class="hint">대상: ${esc(t.target_reader)} · 추천 이유: ${esc(t.reason)}</p>
      <div><span class="kw main">${esc(t.main_keyword)}</span>${(t.sub_keywords || []).map((k) => `<span class="kw">${esc(k)}</span>`).join("")}</div>`;
    el.onclick = () => {
      state.selected = i;
      box.querySelectorAll(".topic").forEach((x, j) => x.classList.toggle("selected", j === i));
      $("btnPost").disabled = false;
    };
    box.appendChild(el);
  });
  $("btnPost").disabled = true;
}

$("btnBack1").onclick = () => showStep(1);

$("btnPost").onclick = async () => {
  if (state.selected < 0) return;
  try {
    loading(true, "블로그 글을 쓰는 중… (1~2분)");
    state.post = await api("/api/post", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId, topic: state.topics[state.selected], length: $("length").value }),
    });
    renderPost();
    showStep(3);
  } catch (err) {
    toast(err.message, true);
  } finally {
    loading(false);
  }
};

// ---------- 3단계: 결과 ----------
function paragraphs(text) {
  return String(text || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)
    .map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("");
}

function renderPost() {
  const p = state.post;
  $("postTitle").value = p.title;

  let html = paragraphs(p.intro);
  const order = [];
  for (const s of p.sections) {
    html += `<h3>${esc(s.heading)}</h3>`;
    for (const n of s.photos) {
      const f = state.files[n - 1];
      if (!f) continue;
      order.push(n);
      html += `<figure data-photo="${n}"><img src="${f.url}" alt=""><figcaption>[사진 ${n}]</figcaption></figure>`;
    }
    html += paragraphs(s.body);
  }
  html += paragraphs(p.outro);
  $("postBody").innerHTML = html;

  $("postTags").textContent = p.hashtags.map((t) => "#" + t.replace(/^#/, "").replace(/\s+/g, "")).join(" ");

  const cl = $("checklist");
  if (p.checklist && p.checklist.length) {
    cl.innerHTML = `<b>⚠ 올리기 전 확인하세요</b><ul>${p.checklist.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`;
    cl.classList.remove("hidden");
  } else {
    cl.classList.add("hidden");
  }

  // 글에 배치되지 않은 사진도 순서 목록 끝에 보여준다.
  state.files.forEach((_, i) => { if (!order.includes(i + 1)) order.push(i + 1); });
  $("photoOrder").innerHTML = order.map((n) =>
    `<div class="thumb"><img src="${state.files[n - 1].url}" alt=""><span class="num">사진 ${n}</span></div>`).join("");
}

// 붙여넣기용: 사진은 [사진 N] 자리표시로 바꾼다 (스마트에디터에서는 사진을 직접 올려야 함).
function bodyForCopy() {
  const clone = $("postBody").cloneNode(true);
  clone.querySelectorAll("figure").forEach((fig) => {
    const p = document.createElement("p");
    p.textContent = `[사진 ${fig.dataset.photo}]`;
    fig.replaceWith(p);
  });
  clone.querySelectorAll("h3").forEach((h) => {
    const p = document.createElement("p");
    p.innerHTML = `<b style="font-size:19px">${esc(h.textContent)}</b>`;
    h.replaceWith(p);
  });
  const blocks = [...clone.children].map((el) => el.innerText.trim()).filter(Boolean);
  return { html: clone.innerHTML, text: blocks.join("\n\n") };
}

async function copy(text, html) {
  try {
    if (html && window.ClipboardItem) {
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([text], { type: "text/plain" }),
      })]);
    } else {
      await navigator.clipboard.writeText(text);
    }
    toast("복사했어요. 스마트에디터에 붙여넣으세요.");
  } catch {
    toast("복사에 실패했어요. 직접 드래그해서 복사해 주세요.", true);
  }
}

$("copyTitle").onclick = () => copy($("postTitle").value);
$("copyBody").onclick = () => { const b = bodyForCopy(); copy(b.text, b.html); };
$("copyTags").onclick = () => copy($("postTags").textContent);
$("downloadTxt").onclick = () => {
  const b = bodyForCopy();
  const content = `${$("postTitle").value}\n\n${b.text}\n\n${$("postTags").textContent}\n`;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
  a.download = `${$("postTitle").value.replace(/[\\/:*?"<>|]/g, "").slice(0, 50) || "blog"}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
};
$("btnBack2").onclick = () => showStep(2);

// ---------- 초기값 ----------
api("/api/defaults").then((d) => {
  for (const k of ["blog_name", "industry", "tone"]) if (d[k] && !$(k).value) $(k).value = d[k];
}).catch(() => {});
