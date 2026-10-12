"""사진 → 주제 추천 → 네이버 블로그 글 작성 웹앱 (사내용)."""

import io
import json
import os
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from . import setup as setup_helpers  # noqa: E402
from .images import ImageError, PreparedImage, prepare_image  # noqa: E402
from .settings import Settings, mask_key  # noqa: E402
from .store import PostStore  # noqa: E402
from .writer import BlogProfile, BlogWriter, WriterError  # noqa: E402

MAX_PHOTOS = 20
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SESSION_TTL_SECONDS = 2 * 60 * 60
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="네이버 블로그 글쓰기 도우미")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_writer: BlogWriter | None = None
_store: PostStore | None = None
_settings: Settings | None = None


def data_dir() -> Path:
    return Path(os.getenv("BLOG_DATA_DIR", "data"))


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings(data_dir())
    return _settings


def get_store() -> PostStore:
    global _store
    if _store is None:
        _store = PostStore(data_dir())
    return _store


def get_writer() -> BlogWriter:
    global _writer
    if _writer is None:
        import anthropic

        key = get_settings().get("anthropic_api_key")
        if not key:
            raise WriterError("API 키가 아직 설정되지 않았습니다. 상단 '설정' 탭에서 입력해 주세요.")
        _writer = BlogWriter(client=anthropic.Anthropic(api_key=key))
    return _writer


class _Session:
    def __init__(self, images: list[PreparedImage], profile: BlogProfile):
        self.images = images
        self.profile = profile
        self.created = time.time()


# 주제 추천 → 글 작성 사이에 사진을 다시 올리지 않도록 메모리에 잠시 보관한다.
# 단일 프로세스 사내 서버 기준. 여러 워커로 띄우면 공유 저장소로 바꿔야 한다.
_sessions: dict[str, _Session] = {}
_sessions_lock = threading.Lock()


def _store_session(session: _Session) -> str:
    sid = uuid.uuid4().hex
    now = time.time()
    with _sessions_lock:
        for k in [k for k, s in _sessions.items() if now - s.created > SESSION_TTL_SECONDS]:
            del _sessions[k]
        _sessions[sid] = session
    return sid


def _get_session(sid: str) -> _Session:
    with _sessions_lock:
        session = _sessions.get(sid)
    if session is None or time.time() - session.created > SESSION_TTL_SECONDS:
        raise HTTPException(404, "작업이 만료되었습니다. 사진을 다시 올려 주세요.")
    return session


def _split_keywords(raw: str) -> list[str]:
    return [k.strip() for k in raw.replace("\n", ",").split(",") if k.strip()]


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/defaults")
def defaults():
    return {
        **{k: v for k, v in get_settings().all().items() if k != "anthropic_api_key"},
        "configured": bool(get_settings().get("anthropic_api_key")),
    }


@app.post("/api/topics")
def suggest_topics(
    photos: list[UploadFile] = File(...),
    blog_name: str = Form(""),
    industry: str = Form(""),
    tone: str = Form(""),
    memo: str = Form(""),
    keywords: str = Form(""),
    post_type: str = Form("자동"),
):
    if not photos:
        raise HTTPException(400, "사진을 1장 이상 올려 주세요.")
    if len(photos) > MAX_PHOTOS:
        raise HTTPException(400, f"사진은 최대 {MAX_PHOTOS}장까지 올릴 수 있습니다.")

    images = []
    for photo in photos:
        raw = photo.file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, f"'{photo.filename}' 파일이 너무 큽니다 (최대 25MB).")
        try:
            images.append(prepare_image(raw, photo.filename or "photo"))
        except ImageError as e:
            raise HTTPException(400, str(e)) from e

    profile = BlogProfile(
        blog_name=blog_name.strip(),
        industry=industry.strip(),
        tone=tone.strip(),
        memo=memo.strip(),
        keywords=_split_keywords(keywords),
    )
    try:
        result = get_writer().suggest_topics(images, profile, post_type=post_type)
    except WriterError as e:
        raise HTTPException(502, str(e)) from e

    return {"session_id": _store_session(_Session(images, profile)), **result}


class PostRequest(BaseModel):
    session_id: str
    topic: dict
    length: str = "보통 (공백 포함 약 1,500~2,000자)"


@app.post("/api/post")
def write_post(req: PostRequest):
    session = _get_session(req.session_id)
    try:
        post = get_writer().write_post(session.images, session.profile, req.topic, req.length)
    except WriterError as e:
        raise HTTPException(502, str(e)) from e

    # 모델이 없는 사진 번호를 넣었을 경우를 대비해 범위 밖 번호는 걸러낸다.
    n = len(session.images)
    for section in post.get("sections", []):
        section["photos"] = [p for p in section.get("photos", []) if isinstance(p, int) and 1 <= p <= n]
    return post


# ---------- 글 보관함 ----------

def _read_upload(photo: UploadFile) -> bytes:
    raw = photo.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"'{photo.filename}' 파일이 너무 큽니다 (최대 25MB).")
    return raw


def _require_post(post_id: str) -> dict:
    post = get_store().get(post_id)
    if post is None:
        raise HTTPException(404, "글을 찾을 수 없습니다.")
    return post


@app.post("/api/posts")
def create_post(data: str = Form(...), photos: list[UploadFile] = File(default=[])):
    """data: 글 내용 JSON, photos: 원본 사진 (업로드 순서 = [사진 N] 번호)."""
    try:
        payload = json.loads(data)
        for k in ("title", "body_html", "paste_html", "paste_text"):
            if not isinstance(payload.get(k), str):
                raise ValueError(f"'{k}' 항목이 없습니다.")
        if len(photos) > MAX_PHOTOS:
            raise ValueError(f"사진은 최대 {MAX_PHOTOS}장까지 저장할 수 있습니다.")
        files = [(p.filename or "photo.jpg", _read_upload(p)) for p in photos]
        return get_store().create(payload, files)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(400, str(e)) from e


class PostUpdate(BaseModel):
    title: str | None = None
    body_html: str | None = None
    paste_html: str | None = None
    paste_text: str | None = None
    tags: list[str] | None = None
    photo_order: list[int] | None = None
    status: str | None = None
    scheduled_at: str | None = None


@app.put("/api/posts/{post_id}")
def update_post(post_id: str, req: PostUpdate):
    data = req.model_dump(exclude_unset=True)
    try:
        post = get_store().update(post_id, data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if post is None:
        raise HTTPException(404, "글을 찾을 수 없습니다.")
    return post


@app.get("/api/posts")
def list_posts():
    return get_store().list_all()


@app.get("/api/posts/due")
def due_posts():
    """예정 시각이 지났는데 발행 완료 표시가 안 된 글 (크롬 확장 알림용)."""
    return get_store().due()


@app.get("/api/posts/{post_id}")
def get_post(post_id: str):
    return _require_post(post_id)


@app.delete("/api/posts/{post_id}")
def delete_post(post_id: str):
    if not get_store().delete(post_id):
        raise HTTPException(404, "글을 찾을 수 없습니다.")
    return {"ok": True}


@app.get("/api/posts/{post_id}/photos/{n}")
def get_photo(post_id: str, n: int):
    path = get_store().photo_path(post_id, n)
    if path is None or not path.exists():
        raise HTTPException(404, "사진을 찾을 수 없습니다.")
    return FileResponse(path)


@app.get("/api/posts/{post_id}/photos.zip")
def download_photos(post_id: str):
    """글에 배치된 순서대로 번호를 붙인 사진 묶음."""
    import zipfile
    from urllib.parse import quote

    post = _require_post(post_id)
    count = len(post["photos"])
    order = [n for n in post["photo_order"] if isinstance(n, int) and 1 <= n <= count]
    order += [n for n in range(1, count + 1) if n not in order]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i, n in enumerate(order, start=1):
            path = get_store().photo_path(post_id, n)
            zf.write(path, f"{i:02d}_사진{n}{path.suffix}")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('블로그사진.zip')}"},
    )


# ---------- 설정 ----------

def _port() -> int:
    return int(os.getenv("PORT", "8000"))


def _can_edit_settings(request: Request, password: str | None) -> bool:
    """설정 변경은 서버 PC에서 직접 열었을 때만 허용한다.
    클라우드처럼 프록시 뒤에서 돌릴 때는 BLOG_ADMIN_PASSWORD로 허용한다."""
    admin = os.getenv("BLOG_ADMIN_PASSWORD")
    if admin:
        return password == admin
    proxied = "x-forwarded-for" in request.headers
    return not proxied and setup_helpers.is_loopback(request.client.host if request.client else "")


@app.get("/api/setup")
def setup_status(request: Request, x_admin_password: str | None = Header(default=None)):
    st = get_settings()
    key = st.get("anthropic_api_key")
    return {
        "configured": bool(key),
        "key_masked": mask_key(key),
        "key_from_env": st.from_env("anthropic_api_key"),
        "can_edit": _can_edit_settings(request, x_admin_password),
        "needs_password": bool(os.getenv("BLOG_ADMIN_PASSWORD")),
        **{k: v for k, v in st.all().items() if k != "anthropic_api_key"},
        "lan_urls": setup_helpers.lan_urls(_port()),
    }


class SetupRequest(BaseModel):
    api_key: str | None = None
    blog_name: str | None = None
    industry: str | None = None
    tone: str | None = None
    write_url: str | None = None


@app.post("/api/setup")
def save_setup(req: SetupRequest, request: Request, x_admin_password: str | None = Header(default=None)):
    global _writer
    if not _can_edit_settings(request, x_admin_password):
        raise HTTPException(403, "설정은 도우미를 실행한 PC에서만 바꿀 수 있습니다.")
    values = req.model_dump(exclude_none=True)
    key = values.pop("api_key", "").strip()
    if key:
        error = setup_helpers.check_api_key(key)
        if error:
            raise HTTPException(400, error)
        values["anthropic_api_key"] = key
    if values.get("write_url") and not values["write_url"].startswith("https://"):
        raise HTTPException(400, "글쓰기 주소는 https:// 로 시작해야 합니다.")
    get_settings().update(values)
    _writer = None  # 새 키로 다시 만든다
    return setup_status(request, x_admin_password)


@app.get("/api/setup/qr.svg")
def setup_qr(url: str):
    # 이 서버의 접속 주소만 QR로 만든다 (임의 URL 생성기로 쓰이지 않게)
    if url not in setup_helpers.lan_urls(_port()):
        raise HTTPException(400, "알 수 없는 주소입니다.")
    return Response(setup_helpers.qr_svg(url), media_type="image/svg+xml")


@app.get("/api/setup/extension.zip")
def extension_zip(origin: str):
    """서버 주소를 미리 넣은 크롬 확장 설치 파일. 직원은 압축만 풀어 설치하면 된다."""
    try:
        data = setup_helpers.build_extension_zip(origin)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    from urllib.parse import quote

    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('블로그도우미_확장프로그램.zip')}"},
    )


def run():
    import uvicorn

    port = _port()
    print("\n  블로그 글쓰기 도우미가 켜졌습니다.")
    print(f"  · 이 PC에서:        http://localhost:{port}")
    for url in setup_helpers.lan_urls(port):
        print(f"  · 다른 PC·휴대폰:   {url}  (같은 와이파이/사내망)")
    print("  · 끄려면 이 창을 닫으세요.\n")
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )


if __name__ == "__main__":
    run()
