"""업로드된 사진을 Claude에 보내기 좋은 형태로 정리한다."""

import base64
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

# Claude 비전은 긴 변 1568px 정도면 충분하고, 이보다 크면 비용만 늘어난다.
MAX_LONG_EDGE = 1568
JPEG_QUALITY = 85


class ImageError(ValueError):
    pass


@dataclass
class PreparedImage:
    filename: str
    media_type: str
    data_b64: str
    width: int
    height: int

    def to_content_block(self) -> dict:
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": self.media_type, "data": self.data_b64},
        }


def prepare_image(raw: bytes, filename: str) -> PreparedImage:
    """사진을 열어 회전 보정·크기 축소·JPEG 변환 후 base64로 인코딩한다."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:  # Pillow는 포맷별로 다양한 예외를 던진다
        raise ImageError(f"'{filename}' 파일을 이미지로 열 수 없습니다.") from e

    # 휴대폰 사진의 EXIF 회전 정보를 반영 (안 하면 옆으로 누운 사진이 된다)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    img.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return PreparedImage(
        filename=filename,
        media_type="image/jpeg",
        data_b64=base64.standard_b64encode(buf.getvalue()).decode("ascii"),
        width=img.width,
        height=img.height,
    )
