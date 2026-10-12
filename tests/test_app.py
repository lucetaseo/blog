import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from datetime import datetime, timedelta, timezone

from app.images import ImageError, prepare_image
from app.settings import Settings
from app.store import PostStore
from app.writer import BlogWriter

TOPICS = {
    "photo_notes": [{"photo": 1, "description": "라떼"}, {"photo": 2, "description": "창가 좌석"}],
    "topics": [{
        "title": "연남동 감성 카페", "post_type": "정보성", "angle": "공간 소개", "target_reader": "20대",
        "main_keyword": "연남동카페", "sub_keywords": ["라떼"], "reason": "사진이 공간 위주",
    }],
}
POST = {
    "title": "연남동 감성 카페 방문기",
    "intro": "안녕하세요.",
    "sections": [{"heading": "메뉴", "photos": [1, 9], "body": "라떼가 맛있어요."},
                 {"heading": "공간", "photos": [2], "body": "창가가 좋아요."}],
    "outro": "또 올게요.",
    "hashtags": ["연남동카페"],
    "checklist": ["[가격 입력] 채우기"],
}


class FakeStream:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=json.dumps(self.payload))],
        )


class FakeClient:
    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["output_config"]["format"]["schema"]
        return FakeStream(TOPICS if "topics" in schema["properties"] else POST)


def jpeg_bytes(size=(3000, 2000), mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch, tmp_path):
    fake = FakeClient()
    monkeypatch.setattr(main, "_writer", BlogWriter(client=fake))
    monkeypatch.setattr(main, "_store", PostStore(tmp_path))
    monkeypatch.setattr(main, "_settings", Settings(tmp_path))
    return TestClient(main.app), fake


def test_prepare_image_downsizes_and_converts():
    img = prepare_image(jpeg_bytes(mode="RGBA"), "a.png")
    assert img.media_type == "image/jpeg"
    assert max(img.width, img.height) == 1568


def test_prepare_image_rejects_non_image():
    with pytest.raises(ImageError):
        prepare_image(b"not an image", "a.txt")


def test_topics_then_post_flow(client):
    tc, fake = client
    files = [("photos", ("1.png", jpeg_bytes(), "image/png")), ("photos", ("2.png", jpeg_bytes(), "image/png"))]
    r = tc.post("/api/topics", files=files,
                data={"blog_name": "OO카페", "keywords": "연남동, 라떼", "post_type": "정보성"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["topics"][0]["main_keyword"] == "연남동카페"

    sent = fake.calls[0]
    assert sent["fallbacks"] == "default"
    images = [b for b in sent["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 2
    prompt = sent["messages"][0]["content"][-1]["text"]
    assert "연남동, 라떼" in prompt
    assert "글 유형은 '정보성'입니다" in prompt

    r = tc.post("/api/post", json={"session_id": body["session_id"], "topic": body["topics"][0]})
    assert r.status_code == 200, r.text
    # 존재하지 않는 사진 번호(9)는 걸러진다
    assert r.json()["sections"][0]["photos"] == [1]
    assert "글 유형: 정보성" in fake.calls[1]["messages"][0]["content"][-1]["text"]


def test_auto_type_asks_for_info_topic(client):
    tc, fake = client
    r = tc.post("/api/topics", files=[("photos", ("1.png", jpeg_bytes(), "image/png"))])
    assert r.status_code == 200, r.text
    assert "정보성 주제를 1개 이상" in fake.calls[0]["messages"][0]["content"][-1]["text"]


def test_post_with_unknown_session(client):
    tc, _ = client
    r = tc.post("/api/post", json={"session_id": "nope", "topic": {}})
    assert r.status_code == 404


def test_rejects_bad_upload(client):
    tc, _ = client
    r = tc.post("/api/topics", files=[("photos", ("x.txt", b"hello", "text/plain"))])
    assert r.status_code == 400


def _save(tc, **extra):
    data = {"title": "제목", "body_html": '<p>본문</p><figure data-photo="2"></figure>',
            "paste_html": "<p>본문</p><p>[사진 2]</p>", "paste_text": "본문\n\n[사진 2]",
            "tags": ["카페"], "photo_order": [2, 1], "post_type": "정보성", **extra}
    files = [("photos", ("a.jpg", b"AAA", "image/jpeg")), ("photos", ("b.png", b"BBB", "image/png"))]
    r = tc.post("/api/posts", data={"data": json.dumps(data)}, files=files)
    assert r.status_code == 200, r.text
    return r.json()


def test_archive_save_list_and_photos(client):
    tc, _ = client
    post = _save(tc)
    assert post["status"] == "draft" and post["photo_count"] == 2

    assert tc.get(f"/api/posts/{post['id']}/photos/2").content == b"BBB"
    assert tc.get(f"/api/posts/{post['id']}/photos/3").status_code == 404

    z = zipfile.ZipFile(io.BytesIO(tc.get(f"/api/posts/{post['id']}/photos.zip").content))
    assert z.namelist() == ["01_사진2.png", "02_사진1.jpg"]

    listed = tc.get("/api/posts").json()
    assert [p["id"] for p in listed] == [post["id"]] and "body_html" not in listed[0]

    assert tc.delete(f"/api/posts/{post['id']}").status_code == 200
    assert tc.get(f"/api/posts/{post['id']}").status_code == 404


def test_schedule_due_and_done(client):
    tc, _ = client
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    late = _save(tc, scheduled_at=past)
    later = _save(tc, scheduled_at=future)
    assert late["status"] == later["status"] == "scheduled"

    assert [p["id"] for p in tc.get("/api/posts/due").json()] == [late["id"]]

    done = tc.put(f"/api/posts/{late['id']}", json={"status": "done"}).json()
    assert done["status"] == "done" and done["scheduled_at"] == late["scheduled_at"]
    assert tc.get("/api/posts/due").json() == []

    # 예정 시각을 지우면 임시저장으로 돌아간다
    assert tc.put(f"/api/posts/{later['id']}", json={"scheduled_at": None}).json()["status"] == "draft"


def test_rejects_naive_schedule_time(client):
    tc, _ = client
    data = {"title": "t", "body_html": "", "paste_html": "", "paste_text": "", "scheduled_at": "2026-10-20T09:00"}
    r = tc.post("/api/posts", data={"data": json.dumps(data)})
    assert r.status_code == 400


# ---------- 설정 ----------

@pytest.fixture
def setup_env(monkeypatch, tmp_path):
    for name in ("ANTHROPIC_API_KEY", "BLOG_NAME", "BLOG_ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(main, "_settings", Settings(tmp_path))
    monkeypatch.setattr(main, "_writer", None)
    checked = []
    monkeypatch.setattr(main.setup_helpers, "check_api_key", lambda k: checked.append(k) or (None if k == "sk-ant-good" else "틀린 키"))
    local = TestClient(main.app, client=("127.0.0.1", 5000))
    remote = TestClient(main.app, client=("192.168.0.23", 5000))
    return local, remote, checked


def test_first_run_needs_key(setup_env):
    local, _, _ = setup_env
    assert local.get("/api/defaults").json()["configured"] is False
    r = local.post("/api/topics", files=[("photos", ("1.png", jpeg_bytes(), "image/png"))])
    assert r.status_code == 502 and "API 키" in r.json()["detail"]


def test_setup_saves_and_validates_key_locally(setup_env, tmp_path):
    local, _, checked = setup_env
    assert local.post("/api/setup", json={"api_key": "sk-ant-bad"}).status_code == 400
    r = local.post("/api/setup", json={"api_key": "sk-ant-good", "blog_name": "OO카페"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] and "sk-ant-good" not in json.dumps(body)
    assert checked == ["sk-ant-bad", "sk-ant-good"]
    assert local.get("/api/defaults").json()["blog_name"] == "OO카페"
    assert json.loads((tmp_path / "settings.json").read_text())["anthropic_api_key"] == "sk-ant-good"


def test_setup_locked_from_other_pcs(setup_env):
    _, remote, _ = setup_env
    assert remote.get("/api/setup").json()["can_edit"] is False
    assert remote.post("/api/setup", json={"blog_name": "x"}).status_code == 403
    # 프록시 뒤(클라우드)라면 로컬 주소로 보여도 막는다
    local, _, _ = setup_env
    assert local.post("/api/setup", json={"blog_name": "x"}, headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 403


def test_setup_admin_password(setup_env, monkeypatch):
    _, remote, _ = setup_env
    monkeypatch.setenv("BLOG_ADMIN_PASSWORD", "pw")
    assert remote.post("/api/setup", json={"blog_name": "x"}).status_code == 403
    assert remote.post("/api/setup", json={"blog_name": "x"}, headers={"X-Admin-Password": "pw"}).status_code == 200


def test_env_overrides_settings_file(setup_env, monkeypatch):
    local, _, _ = setup_env
    local.post("/api/setup", json={"blog_name": "파일값"})
    monkeypatch.setenv("BLOG_NAME", "환경변수값")
    assert local.get("/api/defaults").json()["blog_name"] == "환경변수값"


def test_extension_zip_has_server_address(setup_env):
    local, _, _ = setup_env
    r = local.get("/api/setup/extension.zip", params={"origin": "http://192.168.0.10:8000"})
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    root = "블로그도우미_확장프로그램/"
    assert '"http://192.168.0.10:8000"' in z.read(root + "config.js").decode()
    manifest = json.loads(z.read(root + "manifest.json"))
    assert "http://192.168.0.10/*" in manifest["host_permissions"]
    bridge = next(cs for cs in manifest["content_scripts"] if "bridge.js" in cs["js"])
    assert "http://192.168.0.10/*" in bridge["matches"]
    assert local.get("/api/setup/extension.zip", params={"origin": "javascript:alert(1)"}).status_code == 400


def test_qr_only_for_own_addresses(setup_env, monkeypatch):
    local, _, _ = setup_env
    monkeypatch.setattr(main.setup_helpers, "lan_urls", lambda port: ["http://192.168.0.10:8000"])
    assert local.get("/api/setup/qr.svg", params={"url": "http://192.168.0.10:8000"}).headers["content-type"].startswith("image/svg")
    assert local.get("/api/setup/qr.svg", params={"url": "https://evil.example"}).status_code == 400
