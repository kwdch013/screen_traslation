from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Callable
from urllib import request
from urllib.error import URLError

from .errors import DependencyUnavailableError


Transport = Callable[[str, dict[str, object], dict[str, str], float], dict[str, object]]


class OpenAICompatibleClient:
    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:8000/v1",
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        transport: Transport | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or os.environ.get("LLM_API_KEY")
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _http_post_json

    def complete_text(self, system_prompt: str, user_text: str, temperature: float = 0.0) -> str:
        return self._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=temperature,
        )

    def complete_image(self, system_prompt: str, image: object, user_text: str, temperature: float = 0.0) -> str:
        data_url = image_to_data_url(image)
        return self._chat(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            temperature=temperature,
        )

    def validate(self) -> None:
        if not self._model:
            raise DependencyUnavailableError("LLMモデル名を指定してください。")

    def _chat(self, messages: list[dict[str, object]], temperature: float) -> str:
        self.validate()
        payload: dict[str, object] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            response = self._transport(
                f"{self._base_url}/chat/completions",
                payload,
                headers,
                self._timeout_seconds,
            )
        except Exception as error:
            raise DependencyUnavailableError("LLM APIへ接続できませんでした。") from error
        return _extract_message_content(response)


def image_to_data_url(image: object) -> str:
    try:
        from io import BytesIO
    except ImportError as error:
        raise DependencyUnavailableError("画像のエンコードに失敗しました。") from error
    if hasattr(image, "save"):
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    if isinstance(image, (str, Path)):
        encoded = base64.b64encode(Path(image).read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    raise DependencyUnavailableError("LLM OCRにはPillow画像または画像パスが必要です。")


def _http_post_json(url: str, payload: dict[str, object], headers: dict[str, str], timeout_seconds: float) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except URLError as error:
        raise DependencyUnavailableError("LLM APIへ接続できませんでした。") from error
    return json.loads(body)


def _extract_message_content(response: dict[str, object]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise DependencyUnavailableError("LLM APIの応答にchoicesがありません。")
    first = choices[0]
    if not isinstance(first, dict):
        raise DependencyUnavailableError("LLM APIの応答形式が不正です。")
    message = first.get("message")
    if not isinstance(message, dict):
        raise DependencyUnavailableError("LLM APIの応答にmessageがありません。")
    content = message.get("content")
    if not isinstance(content, str):
        raise DependencyUnavailableError("LLM APIの応答にcontentがありません。")
    return content.strip()
