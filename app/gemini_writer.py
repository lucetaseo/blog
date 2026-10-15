"""구글 제미나이로 같은 일을 한다. 프롬프트와 응답 형식은 BlogWriter와 같고, AI 호출만 다르다."""

import base64
import json
import re

from .writer import SYSTEM_PROMPT, BlogWriter, WriterError

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

# 사진→글 작업에 맞지 않는 특수 모델은 자동 선택에서 뺀다.
_SKIP_WORDS = ("image", "tts", "audio", "live", "embedding", "robotics", "computer-use")


def _strip_unsupported(schema):
    """제미나이 응답 스키마가 받지 않을 수 있는 키(additionalProperties)를 뺀다."""
    if isinstance(schema, dict):
        return {k: _strip_unsupported(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [_strip_unsupported(v) for v in schema]
    return schema


def pick_flash_model(names: list[str], preferred: str = DEFAULT_GEMINI_MODEL) -> str | None:
    """계정에서 쓸 수 있는 모델 중 하나를 고른다: 원하는 모델 → 가장 최신 Flash → 최신 Flash-Lite."""
    names = [n.removeprefix("models/") for n in names]
    if preferred in names:
        return preferred

    def version(n: str) -> tuple:
        m = re.match(r"gemini-(\d+)(?:\.(\d+))?", n)
        return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)

    flash = [n for n in names if "flash" in n and not any(w in n for w in _SKIP_WORDS)]
    stable = [n for n in flash if "preview" not in n and "exp" not in n] or flash
    for lite in (False, True):
        group = [n for n in stable if ("lite" in n) == lite]
        if group:
            return max(group, key=lambda n: (version(n), -len(n)))
    return None


class GeminiWriter(BlogWriter):
    def __init__(self, client=None, model: str = DEFAULT_GEMINI_MODEL, api_key: str | None = None):
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key)
        self.client = client
        self.model = model or DEFAULT_GEMINI_MODEL
        self.fast_thinking = True

    @staticmethod
    def _parts(content: list[dict]):
        from google.genai import types

        parts = []
        for block in content:
            if block["type"] == "text":
                parts.append(types.Part.from_text(text=block["text"]))
            elif block["type"] == "image":
                src = block["source"]
                parts.append(types.Part.from_bytes(data=base64.b64decode(src["data"]), mime_type=src["media_type"]))
        return parts

    def _call_json(self, content: list[dict], schema: dict, effort: str) -> dict:
        from google.genai import errors, types

        def config(thinking: bool):
            return types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_json_schema=_strip_unsupported(schema),
                max_output_tokens=32000,
                # 생각(추론)을 짧게 해서 응답을 빠르게 한다. 블로그 글은 깊은 추론이 필요 없다.
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW) if thinking else None,
            )

        try:
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=self._parts(content), config=config(self.fast_thinking)
                )
            except errors.ClientError as e:
                # 생각 수준 설정을 받지 않는 모델이면 설정 없이 다시 보낸다.
                if getattr(e, "code", None) != 400 or "thinking" not in str(e).lower() or not self.fast_thinking:
                    raise
                self.fast_thinking = False
                response = self.client.models.generate_content(
                    model=self.model, contents=self._parts(content), config=config(False)
                )
        except errors.ClientError as e:
            raise WriterError(_client_error_message(e, self.model)) from e
        except errors.ServerError as e:
            raise WriterError("제미나이 서버가 잠시 혼잡합니다. 잠시 뒤 다시 시도하세요.") from e
        except OSError as e:  # 네트워크 끊김 등
            raise WriterError("제미나이에 연결할 수 없습니다. 네트워크를 확인하세요.") from e

        finish = ""
        if getattr(response, "candidates", None):
            finish = str(getattr(response.candidates[0], "finish_reason", "") or "")
        if "MAX_TOKENS" in finish:
            raise WriterError("응답이 너무 길어 중간에 끊겼습니다. 사진 수를 줄여 다시 시도하세요.")
        if any(w in finish for w in ("SAFETY", "PROHIBITED", "BLOCKLIST", "RECITATION")) or not response.text:
            raise WriterError("제미나이가 이 사진/요청으로는 글을 쓰지 않았습니다. 다른 사진이나 표현으로 시도해 주세요.")
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as e:
            raise WriterError("AI 응답을 해석하지 못했습니다. 다시 시도해 주세요.") from e


def _client_error_message(e, model: str) -> str:
    code = getattr(e, "code", None)
    text = str(e)
    if code == 429 or "RESOURCE_EXHAUSTED" in text:
        return ("제미나이 사용 한도를 넘었습니다. 무료 사용량은 분당·하루 횟수 제한이 있어요. "
                "잠시 뒤(또는 내일) 다시 시도하거나, AI Studio에서 결제를 연결하면 한도가 늘어납니다.")
    if code in (401, 403) or "API_KEY_INVALID" in text or "PERMISSION_DENIED" in text:
        return "제미나이 API 키가 올바르지 않거나 권한이 없습니다. '설정' 탭에서 키를 다시 넣어 주세요."
    if code == 404:
        return f"제미나이 모델 '{model}'을(를) 찾을 수 없습니다. '설정' 탭에서 키를 다시 저장하면 쓸 수 있는 모델로 자동으로 바뀝니다."
    return f"제미나이 오류 ({code}): {getattr(e, 'message', None) or text}"


def check_gemini_key(key: str, preferred: str = DEFAULT_GEMINI_MODEL) -> tuple[str | None, str | None]:
    """(오류 문구, 사용할 모델). 키가 맞으면 계정에서 쓸 수 있는 모델을 골라 준다."""
    from google import genai
    from google.genai import errors

    try:
        client = genai.Client(api_key=key)
        names = [
            m.name for m in client.models.list()
            if "generateContent" in (getattr(m, "supported_actions", None) or ["generateContent"])
        ]
    except errors.ClientError as e:
        return _client_error_message(e, preferred), None
    except errors.APIError as e:
        return f"제미나이 키 확인 중 오류가 났습니다 ({getattr(e, 'code', '')}). 잠시 뒤 다시 시도하세요.", None
    except OSError:
        return "제미나이 서버에 연결할 수 없습니다. 이 PC의 인터넷 연결(회사 방화벽)을 확인하세요.", None

    model = pick_flash_model(names, preferred)
    if not model:
        return "이 키로 쓸 수 있는 제미나이 Flash 모델을 찾지 못했습니다.", None
    return None, model
