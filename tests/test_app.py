import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.images import ImageError, prepare_image
from app.writer import BlogWriter

TOPICS = {
    "photo_notes": [{"photo": 1, "description": "라떼"}, {"photo": 2, "description": "창가 좌석"}],
    "topics": [{
        "title": "연남동 감성 카페", "angle": "공간 소개", "target_reader": "20대",
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
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(main, "_writer", BlogWriter(client=fake))
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
    r = tc.post("/api/topics", files=files, data={"blog_name": "OO카페", "keywords": "연남동, 라떼"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["topics"][0]["main_keyword"] == "연남동카페"

    sent = fake.calls[0]
    assert sent["fallbacks"] == "default"
    images = [b for b in sent["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 2
    assert "연남동, 라떼" in sent["messages"][0]["content"][-1]["text"]

    r = tc.post("/api/post", json={"session_id": body["session_id"], "topic": body["topics"][0]})
    assert r.status_code == 200, r.text
    # 존재하지 않는 사진 번호(9)는 걸러진다
    assert r.json()["sections"][0]["photos"] == [1]


def test_post_with_unknown_session(client):
    tc, _ = client
    r = tc.post("/api/post", json={"session_id": "nope", "topic": {}})
    assert r.status_code == 404


def test_rejects_bad_upload(client):
    tc, _ = client
    r = tc.post("/api/topics", files=[("photos", ("x.txt", b"hello", "text/plain"))])
    assert r.status_code == 400
