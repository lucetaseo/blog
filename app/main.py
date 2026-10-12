"""사진 → 주제 추천 → 네이버 블로그 글 작성 웹앱 (사내용)."""

import os
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from .images import ImageError, PreparedImage, prepare_image  # noqa: E402
from .writer import BlogProfile, BlogWriter, WriterError  # noqa: E402

MAX_PHOTOS = 20
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SESSION_TTL_SECONDS = 2 * 60 * 60
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="네이버 블로그 글쓰기 도우미")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_writer: BlogWriter | None = None


def get_writer() -> BlogWriter:
    global _writer
    if _writer is None:
        _writer = BlogWriter()
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
        "blog_name": os.getenv("BLOG_NAME", ""),
        "industry": os.getenv("BLOG_INDUSTRY", ""),
        "tone": os.getenv("BLOG_TONE", ""),
        "write_url": os.getenv("BLOG_WRITE_URL", "https://blog.naver.com/GoBlogWrite.naver"),
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


def run():
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )


if __name__ == "__main__":
    run()
