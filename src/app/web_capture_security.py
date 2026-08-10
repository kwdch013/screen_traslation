from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Protocol, TYPE_CHECKING
from urllib.parse import urlsplit

from .errors import DependencyUnavailableError

if TYPE_CHECKING:
    from PIL.Image import Image

MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_IMAGE_DIMENSION = 10_000
MAX_IMAGE_PIXELS = 50_000_000
ALLOWED_CONTENT_TYPE_FORMATS: dict[str, frozenset[str]] = {
    "image/jpeg": frozenset({"JPEG"}),
    "image/png": frozenset({"PNG"}),
}
ALLOWED_CONTENT_TYPES = frozenset(ALLOWED_CONTENT_TYPE_FORMATS)
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
READ_TIMEOUT_SECONDS = 15
TOKEN_HEADER = "X-Capture-Token"


class FrameReadTimeoutError(TimeoutError):
    """フレーム本文を制限時間内に読み取れなかったことを表す。"""


class FrameBodyTooLargeError(ValueError):
    """フレーム本文が受信上限を超えたことを表す。"""


class BodyRequest(Protocol):
    def stream(self) -> AsyncIterator[bytes]: ...


def host_allowed(host_header: str | None) -> bool:
    host = _host_from_header(host_header)
    return host in ALLOWED_HOSTS


def origin_allowed(origin_header: str | None) -> bool:
    # ブラウザがOriginを付けない同一オリジンPOSTとの互換性を維持する。
    if not origin_header:
        return True
    try:
        origin = urlsplit(origin_header)
        if origin.scheme.lower() not in {"http", "https"}:
            return False
        if origin.username is not None or origin.password is not None:
            return False
        if origin.path or origin.query or origin.fragment:
            return False
        if not _origin_port_allowed(origin.netloc):
            return False
        _ = origin.port
    except ValueError:
        return False
    return (origin.hostname or "").lower() in ALLOWED_HOSTS


def content_type_value(content_type: str | None) -> str | None:
    if not content_type:
        return None
    value = content_type.split(";", 1)[0].strip().lower()
    return value if value in ALLOWED_CONTENT_TYPES else None


async def read_request_body(
    request: BodyRequest,
    timeout_seconds: float = READ_TIMEOUT_SECONDS,
    max_bytes: int = MAX_FRAME_BYTES,
) -> bytes:
    async def read_chunks() -> bytes:
        chunks: list[bytes] = []
        received_bytes = 0
        async for chunk in request.stream():
            received_bytes += len(chunk)
            if received_bytes > max_bytes:
                raise FrameBodyTooLargeError
            chunks.append(chunk)
        return b"".join(chunks)

    try:
        return await asyncio.wait_for(read_chunks(), timeout=timeout_seconds)
    except TimeoutError as error:
        raise FrameReadTimeoutError from error


def decode_frame_bytes(
    payload: bytes, expected_content_type: str | None = None
) -> Image:
    try:
        from PIL import Image
    except ImportError as error:
        raise DependencyUnavailableError(
            "ブラウザ画面キャプチャの受信には Pillow が必要です。requirements.txt を使ってインストールしてください。"
        ) from error
    with Image.open(BytesIO(payload)) as image:
        width, height = image.size
        # open()はヘッダのみ読むため、展開前に検証してメモリ枯渇を防ぐ。
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            raise ValueError(
                f"画像の辺が大きすぎます(最大{MAX_IMAGE_DIMENSION}px): {width}x{height}"
            )
        if width * height > MAX_IMAGE_PIXELS:
            raise ValueError(
                f"画像の総画素数が大きすぎます(最大{MAX_IMAGE_PIXELS}px): {width * height}"
            )
        if expected_content_type is not None:
            allowed_formats = ALLOWED_CONTENT_TYPE_FORMATS.get(
                expected_content_type, frozenset()
            )
            if (image.format or "").upper() not in allowed_formats:
                raise ValueError(
                    f"Content-Type({expected_content_type})と実フォーマット({image.format})が一致しません。"
                )
        image.load()
        return image.convert("RGB")


def _host_from_header(host_header: str | None) -> str | None:
    if not host_header:
        return None
    value = host_header.strip()
    if not value or any(character in value for character in "/,@"):
        return None
    if value.startswith("["):
        closing = value.find("]")
        if closing < 0:
            return None
        host = value[1:closing]
        remainder = value[closing + 1 :]
        if remainder and (
            not remainder.startswith(":") or not _port_allowed(remainder[1:])
        ):
            return None
        return host.lower()
    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        if not _port_allowed(port):
            return None
        return host.lower()
    if value.count(":") > 1:
        return value.lower()
    return value.lower()


def _origin_port_allowed(authority: str) -> bool:
    if authority.startswith("["):
        closing = authority.find("]")
        if closing < 0:
            return False
        remainder = authority[closing + 1 :]
        return not remainder or (
            remainder.startswith(":") and _port_allowed(remainder[1:])
        )
    if ":" not in authority:
        return True
    return _port_allowed(authority.rsplit(":", 1)[1])


def _port_allowed(port: str) -> bool:
    if not port or not port.isascii() or not port.isdigit():
        return False
    significant_digits = port.lstrip("0") or "0"
    return len(significant_digits) < 5 or (
        len(significant_digits) == 5 and significant_digits <= "65535"
    )
