"""本番構成(compose.yml・.env.example・Dockerfile)を読み、検証用の正規化済みdictにする。

既定は生のYAMLを`.env.example`の値で補間して読む。`docker compose config --format json`の出力ファイルを
環境変数SERVER_COMPOSE_CONFIG_JSONで渡すと、Composeが実際に解決した設定を同じ検査にかける。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

# リポジトリ上は server/、テストイメージ上は /workspace が compose.yml などの置き場所。
ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "compose.yml"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
DOCKERFILE_PATH = ROOT / "Dockerfile"
MANIFEST_PATH = ROOT / "deploy" / "model-manifest.json"
STANZA_MANIFEST_PATH = ROOT / "deploy" / "stanza-manifest.json"

_VARIABLE = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?::(?P<op>[-?])(?P<arg>[^}]*))?\}")
_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def read_env_example() -> dict[str, str]:
	values: dict[str, str] = {}
	for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
		stripped = line.strip()
		if stripped and not stripped.startswith("#") and "=" in stripped:
			name, _, value = stripped.partition("=")
			values[name.strip()] = value.strip()
	return values


def _interpolate(value: Any, env: dict[str, str]) -> Any:
	if isinstance(value, str):
		def replace(match: re.Match[str]) -> str:
			current = env.get(match["name"], "")
			if match["op"] == "-":
				return current or match["arg"]
			# ":?"は必須。雛形が空なら、運用者が設定する前提のプレースホルダーにする。
			return current or f"<{match['name']}>"
		return _VARIABLE.sub(replace, value)
	if isinstance(value, list):
		return [_interpolate(item, env) for item in value]
	if isinstance(value, dict):
		return {key: _interpolate(item, env) for key, item in value.items()}
	return value


def load_compose() -> dict[str, Any]:
	rendered = os.environ.get("SERVER_COMPOSE_CONFIG_JSON")
	if rendered:
		return json.loads(Path(rendered).read_text(encoding="utf-8"))  # type: ignore[no-any-return]
	raw = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
	return _interpolate(raw, read_env_example())  # type: ignore[no-any-return]


def to_bytes(value: Any) -> int:
	if isinstance(value, int):
		return value
	match = re.fullmatch(r"(\d+)([bkmg]?)b?", str(value).lower())
	if match is None:
		raise ValueError(f"サイズを解釈できません: {value!r}")
	return int(match[1]) * _UNITS[match[2]]


def normalize_ports(ports: list[Any]) -> list[tuple[str, int, int]]:
	"""(公開アドレス, 公開ポート, コンテナポート)へ揃える。短縮形と長い形の両方を扱う。"""
	result: list[tuple[str, int, int]] = []
	for port in ports:
		if isinstance(port, dict):
			result.append((port.get("host_ip", "0.0.0.0"), int(port["published"]), int(port["target"])))
			continue
		parts = str(port).split("/")[0].split(":")
		address = parts[0] if len(parts) == 3 else "0.0.0.0"
		result.append((address, int(parts[-2]), int(parts[-1])))
	return result


def normalize_volumes(volumes: list[Any]) -> list[dict[str, Any]]:
	"""{type, source, target, read_only}へ揃える。"""
	result: list[dict[str, Any]] = []
	for volume in volumes:
		if isinstance(volume, dict):
			result.append({
				"type": volume["type"], "source": volume["source"], "target": volume["target"],
				"read_only": bool(volume.get("read_only", False)),
			})
			continue
		source, target, *mode = str(volume).split(":")
		result.append({
			"type": "bind" if source.startswith(("/", ".")) else "volume", "source": source, "target": target,
			"read_only": "ro" in (mode[0].split(",") if mode else []),
		})
	return result


def environment_of(service: dict[str, Any]) -> dict[str, str | None]:
	environment = service.get("environment", {})
	if isinstance(environment, list):
		return {item.partition("=")[0]: (item.partition("=")[2] if "=" in item else None) for item in environment}
	return {key: (None if value is None else str(value)) for key, value in environment.items()}
