"""화면에서 입력한 설정을 data/settings.json에 보관한다.

우선순위: 환경변수(.env) > settings.json > 기본값.
.env를 직접 고치지 않아도 첫 실행 설정 화면만으로 쓸 수 있게 하는 것이 목적이다.
"""

import json
import os
import threading
from pathlib import Path

DEFAULTS = {
    "anthropic_api_key": "",
    "blog_name": "",
    "industry": "",
    "tone": "",
    "write_url": "https://blog.naver.com/GoBlogWrite.naver",
}

# 설정 키 → 같은 의미의 환경변수
ENV_NAMES = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "blog_name": "BLOG_NAME",
    "industry": "BLOG_INDUSTRY",
    "tone": "BLOG_TONE",
    "write_url": "BLOG_WRITE_URL",
}


class Settings:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "settings.json"
        self._lock = threading.Lock()

    def _read_file(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def get(self, key: str) -> str:
        env = os.getenv(ENV_NAMES[key])
        if env:
            return env
        return self._read_file().get(key) or DEFAULTS[key]

    def all(self) -> dict:
        return {k: self.get(k) for k in DEFAULTS}

    def from_env(self, key: str) -> bool:
        return bool(os.getenv(ENV_NAMES[key]))

    def update(self, values: dict) -> None:
        with self._lock:
            data = self._read_file()
            for k, v in values.items():
                if k in DEFAULTS and v is not None:
                    data[k] = str(v).strip()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            # API 키가 담긴 파일이므로 다른 사용자 계정이 읽지 못하게 한다 (윈도우에서는 무시됨)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass


def mask_key(key: str) -> str:
    return f"{key[:10]}…{key[-4:]}" if len(key) > 16 else ("설정됨" if key else "")
