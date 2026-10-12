# 네이버 블로그 글쓰기 도우미 (사내용)

사진을 올리면 AI(Claude)가 사진을 보고 **블로그 주제를 추천**하고, 고른 주제로 **네이버 블로그 글을 작성**해 주는 사내 웹 프로그램입니다.

## 사용 흐름

1. **사진 올리기** — 사진(최대 20장)을 올리고 블로그명·업종·말투·키워드·메모를 적습니다.
   - 사진 순서가 곧 글 속 `[사진 N]` 번호입니다. 썸네일을 끌어서 순서를 바꿀 수 있습니다.
   - 가격·영업시간·이벤트처럼 사진에 없는 사실은 **메모**에 적어 주세요. AI는 메모에 없는 사실을 지어내지 않고 `[가격 입력]` 같은 자리표시로 남깁니다.
2. **주제 선택** — AI가 사진을 분석해 서로 다른 관점의 주제 4개(제목, 구성 방향, 대상 독자, 메인/서브 키워드)를 제안합니다. 하나를 고르고 분량을 정합니다.
3. **글 확인·복사** — 제목, 소제목별 본문, 사진 배치, 해시태그, 올리기 전 확인할 항목이 나옵니다.
   - 본문은 화면에서 바로 고칠 수 있습니다.
   - **본문 복사(서식 포함)** 후 네이버 스마트에디터에 붙여넣고, `[사진 N]` 자리에 화면 아래 "사진 업로드 순서"대로 사진을 넣으면 됩니다.

> 네이버는 블로그 글쓰기 API를 제공하지 않아 자동 발행은 하지 않습니다. 복사 → 붙여넣기 방식입니다.

## 설치 및 실행

Python 3.10 이상이 필요합니다.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # Windows: copy .env.example .env
# .env 파일을 열어 ANTHROPIC_API_KEY 를 입력

python -m app.main
```

브라우저에서 `http://localhost:8000` (다른 PC에서는 `http://<서버IP>:8000`)으로 접속합니다.

### 설정 (`.env`)

| 항목 | 설명 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API 키 (필수) |
| `BLOG_MODEL` | 사용할 모델. 기본 `claude-opus-5-5` |
| `BLOG_NAME`, `BLOG_INDUSTRY`, `BLOG_TONE` | 화면 입력칸의 기본값 |
| `HOST`, `PORT` | 서버 주소/포트. 기본 `0.0.0.0:8000` |

## 구조

```
app/
  main.py      FastAPI 서버 (API + 화면 제공)
  writer.py    Claude 호출 — 주제 추천 / 글 작성 프롬프트와 응답 형식(JSON 스키마)
  images.py    사진 회전 보정·축소·JPEG 변환
  static/      화면 (index.html, app.js, style.css)
tests/         테스트 (Claude 호출은 가짜 클라이언트로 대체)
```

- 글의 톤이나 규칙을 바꾸려면 `app/writer.py`의 `SYSTEM_PROMPT`를 수정하세요.
- 사진은 서버 메모리에 2시간만 보관되며 디스크에 저장하지 않습니다. 서버를 재시작하면 진행 중인 작업은 사라집니다.
- 메모리 보관 방식이라 서버는 **프로세스 1개**로 실행해야 합니다 (`--workers` 여러 개 X).

## 테스트

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## 비용 참고

사진은 긴 변 1568px로 줄여서 보냅니다. 사진 10장 기준으로 주제 추천 1회 + 글 작성 1회에 대략 수백 원 수준입니다 (모델·분량에 따라 다름). 비용을 줄이려면 `.env`에서 `BLOG_MODEL=claude-sonnet-5-5`로 바꿀 수 있습니다.
