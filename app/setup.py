"""첫 실행 설정을 돕는 함수들 — API 키 검사, 접속 주소, QR 코드, 확장 프로그램 설치 파일."""

import io
import ipaddress
import json
import socket
import zipfile
from pathlib import Path
from urllib.parse import urlparse

EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"


def is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def lan_urls(port: int) -> list[str]:
    """같은 네트워크의 다른 PC·휴대폰이 접속할 주소."""
    ips: list[str] = []
    try:
        # 실제로 패킷을 보내지 않고, 바깥으로 나갈 때 쓰는 내 IP만 알아낸다
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return [f"http://{ip}:{port}" for ip in ips if not ip.startswith("127.")]


def check_api_key(key: str) -> str | None:
    """키로 가벼운 요청을 보내 확인한다. 문제가 없으면 None, 있으면 안내 문구."""
    import anthropic

    try:
        anthropic.Anthropic(api_key=key, max_retries=0, timeout=20).models.list(limit=1)
    except anthropic.AuthenticationError:
        return "API 키가 올바르지 않습니다. 콘솔에서 복사한 키 전체를 붙여넣었는지 확인하세요."
    except anthropic.PermissionDeniedError:
        return "이 API 키에 권한이 없습니다. 콘솔에서 키 상태를 확인하세요."
    except anthropic.APIConnectionError:
        return "Claude 서버에 연결할 수 없습니다. 이 PC의 인터넷 연결(회사 방화벽)을 확인하세요."
    except anthropic.APIStatusError as e:
        return f"API 키 확인 중 오류가 났습니다 ({e.status_code}). 잠시 뒤 다시 시도하세요."
    return None


def qr_svg(url: str) -> bytes:
    import segno

    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2, dark="#222", light="#fff")
    return buf.getvalue()


def _origin(value: str) -> str:
    u = urlparse(value)
    if u.scheme not in ("http", "https") or not u.hostname or u.path not in ("", "/") or u.query:
        raise ValueError("서버 주소 형식이 올바르지 않습니다. 예: http://192.168.0.10:8000")
    return f"{u.scheme}://{u.netloc}"


def build_extension_zip(origin: str) -> bytes:
    """extension/ 폴더에 서버 주소를 넣어 묶는다. 설치 후 별도 설정이 필요 없다."""
    origin = _origin(origin)
    host_pattern = f"{urlparse(origin).scheme}://{urlparse(origin).hostname}/*"  # 포트는 패턴에 넣지 않는다

    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
    if host_pattern not in manifest["host_permissions"]:
        manifest["host_permissions"].append(host_pattern)
    for cs in manifest["content_scripts"]:
        if "bridge.js" in cs["js"] and host_pattern not in cs["matches"]:
            cs["matches"].append(host_pattern)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(EXTENSION_DIR.iterdir()):
            if not path.is_file():
                continue
            name = f"블로그도우미_확장프로그램/{path.name}"
            if path.name == "manifest.json":
                zf.writestr(name, json.dumps(manifest, ensure_ascii=False, indent=2))
            elif path.name == "config.js":
                zf.writestr(name, f"// 설치 파일을 만들 때 자동으로 채워진 도우미 서버 주소\nconst NBH_CONFIG = {{ appOrigin: {json.dumps(origin)} }};\n")
            else:
                zf.write(path, name)
    return buf.getvalue()
