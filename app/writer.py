"""Claude로 사진을 분석해 주제를 고르고, 네이버 블로그용 글을 작성한다."""

import json
import os
from dataclasses import dataclass, field

import anthropic

from .images import PreparedImage

MODEL = os.getenv("BLOG_MODEL", "claude-opus-5-5")

# 안전 분류기가 요청을 거절하면 서버 측에서 권장 모델로 자동 재시도한다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class WriterError(RuntimeError):
    pass


@dataclass
class BlogProfile:
    """블로그/업체 정보. 비어 있는 항목은 프롬프트에서 생략된다."""

    blog_name: str = ""
    industry: str = ""
    tone: str = ""
    memo: str = ""
    keywords: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        lines = []
        if self.blog_name:
            lines.append(f"- 블로그/업체명: {self.blog_name}")
        if self.industry:
            lines.append(f"- 업종/분야: {self.industry}")
        if self.tone:
            lines.append(f"- 원하는 말투: {self.tone}")
        if self.keywords:
            lines.append(f"- 꼭 반영할 키워드: {', '.join(self.keywords)}")
        if self.memo:
            lines.append(f"- 작성자 메모: {self.memo}")
        return "\n".join(lines) if lines else "(별도 정보 없음 — 사진만 보고 판단)"


SYSTEM_PROMPT = """\
당신은 네이버 블로그 운영을 돕는 한국어 콘텐츠 에디터입니다. 사내 담당자가 올린 사진을 보고 \
블로그 주제를 제안하고, 네이버 스마트에디터에 바로 옮겨 붙일 수 있는 글을 씁니다.

원칙:
- 업체에 관한 사실(가격·영업시간·주소·시공 기간·보유 장비·경력 등)은 사진에 보이는 것과 \
작성자가 준 정보만 씁니다. 없는 정보는 지어내지 말고 "[가격 입력]"처럼 대괄호 자리표시로 남깁니다.
- 정보성 내용(방법, 요령, 비교, 주의사항)은 해당 분야의 일반적인 상식 수준에서 정확하게 씁니다. \
통계·법령·규정·의학적 효과처럼 틀리면 문제가 되는 구체적 수치나 조항은 단정하지 말고, \
쓴 경우 checklist에 "사실 확인 필요"로 남깁니다.
- 의료·법률·금융·건강식품 등 광고 규제가 있는 업종은 효과 보장, 최상급 표현("최고", "100%"), \
치료 전후 비교, 이용 후기 형식을 쓰지 않습니다.
- 네이버 검색에 잘 노출되도록 핵심 키워드를 제목 앞쪽과 본문 초반에 자연스럽게 넣되, \
같은 단어를 억지로 반복하지 않습니다.
- 모바일에서 읽기 편하게 문단은 2~4문장으로 짧게 끊고, 소제목으로 흐름을 나눕니다.
- 광고 문구처럼 과장하지 말고, 실제 방문자/이용자가 궁금해할 정보를 중심으로 씁니다.
- 사진 번호는 업로드 순서 기준 1번부터 셉니다."""


# 글 유형별 작성 지침. 키는 화면의 선택값과 같다.
POST_TYPES = {
    "정보성": (
        "독자가 검색으로 찾아올 만한 질문(예: 고르는 법, 관리 방법, 비용이 정해지는 요소, 자주 하는 실수)에 "
        "답하는 글입니다. 업체 홍보보다 독자에게 실제로 도움이 되는 정보를 중심에 두고, 사진은 설명을 돕는 "
        "예시로 씁니다. 업체 소개는 마지막에 짧게 한 문단 정도만 자연스럽게 연결합니다. "
        "단계·체크리스트·비교처럼 구조가 분명하게 씁니다."
    ),
    "업체 소개·후기": (
        "매장/서비스를 소개하는 글입니다. 공간, 대표 메뉴·서비스, 이용 방법을 사진과 함께 보여 주고, "
        "방문하거나 문의하고 싶어지도록 씁니다."
    ),
    "작업·시공 사례": (
        "실제로 진행한 작업을 소개하는 포트폴리오 글입니다. 고객 상황(의뢰 배경) → 작업 과정 → 결과 순서로 "
        "쓰고, 과정에서 신경 쓴 점과 비슷한 고민을 가진 독자를 위한 팁을 넣습니다. 고객 개인정보는 쓰지 않습니다."
    ),
    "이벤트·공지": (
        "새 소식(신메뉴, 이벤트, 휴무, 가격 변경 등)을 알리는 글입니다. 핵심 내용(무엇을, 언제까지, 어떻게)을 "
        "앞부분에 분명히 쓰고, 기간·조건 등 메모에 없는 정보는 자리표시로 남깁니다."
    ),
}
AUTO_TYPE = "자동"


TOPICS_SCHEMA = {
    "type": "object",
    "properties": {
        "photo_notes": {
            "type": "array",
            "description": "사진별 관찰 내용 (업로드 순서대로)",
            "items": {
                "type": "object",
                "properties": {
                    "photo": {"type": "integer"},
                    "description": {"type": "string"},
                },
                "required": ["photo", "description"],
                "additionalProperties": False,
            },
        },
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "블로그 제목 후보"},
                    "post_type": {"type": "string", "enum": list(POST_TYPES)},
                    "angle": {"type": "string", "description": "어떤 관점/구성으로 쓸지 한두 문장"},
                    "target_reader": {"type": "string"},
                    "main_keyword": {"type": "string"},
                    "sub_keywords": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string", "description": "이 주제를 추천하는 이유"},
                },
                "required": ["title", "post_type", "angle", "target_reader", "main_keyword", "sub_keywords", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["photo_notes", "topics"],
    "additionalProperties": False,
}


POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "intro": {"type": "string", "description": "도입부 (2~3문장)"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string", "description": "소제목"},
                    "photos": {
                        "type": "array",
                        "description": "이 소제목 바로 아래 배치할 사진 번호들",
                        "items": {"type": "integer"},
                    },
                    "body": {
                        "type": "string",
                        "description": "본문. 문단 사이는 빈 줄(\\n\\n)로 구분",
                    },
                },
                "required": ["heading", "photos", "body"],
                "additionalProperties": False,
            },
        },
        "outro": {"type": "string", "description": "마무리 문단"},
        "hashtags": {
            "type": "array",
            "description": "# 없이 태그 단어만, 10~15개",
            "items": {"type": "string"},
        },
        "checklist": {
            "type": "array",
            "description": "올리기 전에 담당자가 확인/채워야 할 항목 (자리표시 등)",
            "items": {"type": "string"},
        },
    },
    "required": ["title", "intro", "sections", "outro", "hashtags", "checklist"],
    "additionalProperties": False,
}


def _photo_content(images: list[PreparedImage]) -> list[dict]:
    blocks: list[dict] = []
    for i, img in enumerate(images, start=1):
        blocks.append({"type": "text", "text": f"[사진 {i}] ({img.filename})"})
        blocks.append(img.to_content_block())
    return blocks


class BlogWriter:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model

    def _call_json(self, content: list[dict], schema: dict, effort: str) -> dict:
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=32000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                response = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise WriterError("Claude API 키가 올바르지 않습니다. '설정' 탭에서 키를 다시 넣어 주세요.") from e
        except anthropic.RateLimitError as e:
            raise WriterError("요청이 많아 잠시 제한되었습니다. 1분 뒤 다시 시도하세요.") from e
        except anthropic.APIStatusError as e:
            if "credit balance" in str(e.message).lower():
                raise WriterError(
                    "Claude 계정에 크레딧(충전 금액)이 없습니다. console.anthropic.com → 설정 → 결제(Plans & Billing)에서 "
                    "크레딧을 충전한 뒤 다시 시도하세요. API 키는 다시 넣지 않아도 됩니다."
                ) from e
            if e.status_code == 529 or e.status_code >= 500:
                raise WriterError("Claude 서버가 잠시 혼잡합니다. 잠시 뒤 다시 시도하세요.") from e
            raise WriterError(f"Claude API 오류 ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise WriterError("Claude API에 연결할 수 없습니다. 네트워크를 확인하세요.") from e

        if response.stop_reason == "refusal":
            raise WriterError("이 사진/요청으로는 글을 작성할 수 없습니다. 다른 사진으로 시도해 주세요.")
        if response.stop_reason == "max_tokens":
            raise WriterError("응답이 너무 길어 중간에 끊겼습니다. 사진 수를 줄여 다시 시도하세요.")

        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise WriterError("AI 응답을 해석하지 못했습니다. 다시 시도해 주세요.") from e

    def suggest_topics(
        self,
        images: list[PreparedImage],
        profile: BlogProfile,
        post_type: str = AUTO_TYPE,
        count: int = 4,
    ) -> dict:
        if post_type in POST_TYPES:
            type_instruction = (
                f"글 유형은 '{post_type}'입니다. 모든 주제를 이 유형으로 제안하세요.\n"
                f"유형 설명: {POST_TYPES[post_type]}"
            )
        else:
            guide = "\n".join(f"- {k}: {v}" for k, v in POST_TYPES.items())
            type_instruction = (
                "글 유형은 사진과 블로그 정보에 맞게 골라 주세요. 업체 블로그는 검색 유입을 위해 "
                "정보성 글이 중요하니, 가능하면 정보성 주제를 1개 이상 포함하세요.\n"
                f"글 유형:\n{guide}"
            )
        content = _photo_content(images)
        content.append({
            "type": "text",
            "text": (
                f"위 사진 {len(images)}장으로 네이버 블로그 글을 쓰려고 합니다.\n\n"
                f"블로그 정보:\n{profile.to_prompt()}\n\n"
                f"{type_instruction}\n\n"
                "먼저 사진마다 무엇이 보이는지 짧게 정리하고, "
                f"이 사진들로 쓸 수 있는 블로그 주제를 서로 다른 관점으로 {count}개 제안해 주세요. "
                "가장 추천하는 주제를 첫 번째에 두세요."
            ),
        })
        return self._call_json(content, TOPICS_SCHEMA, effort="medium")

    def write_post(
        self,
        images: list[PreparedImage],
        profile: BlogProfile,
        topic: dict,
        length: str = "보통 (공백 포함 약 1,500~2,000자)",
    ) -> dict:
        post_type = topic.get("post_type")
        if post_type not in POST_TYPES:
            post_type = "업체 소개·후기"
        content = _photo_content(images)
        content.append({
            "type": "text",
            "text": (
                f"블로그 정보:\n{profile.to_prompt()}\n\n"
                "선택한 주제:\n"
                f"- 제목 후보: {topic.get('title', '')}\n"
                f"- 글 유형: {post_type} — {POST_TYPES[post_type]}\n"
                f"- 구성 방향: {topic.get('angle', '')}\n"
                f"- 대상 독자: {topic.get('target_reader', '')}\n"
                f"- 메인 키워드: {topic.get('main_keyword', '')}\n"
                f"- 서브 키워드: {', '.join(topic.get('sub_keywords', []))}\n\n"
                f"분량: {length}\n\n"
                "이 주제로 네이버 블로그 글을 작성해 주세요. 업로드한 사진은 모두 한 번씩 "
                "글 흐름에 맞는 소제목 아래에 배치하고(순서는 바꿔도 됩니다), "
                "본문에서 해당 사진 내용을 자연스럽게 설명해 주세요."
            ),
        })
        return self._call_json(content, POST_SCHEMA, effort="high")
