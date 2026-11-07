"""コンテナのhealthcheck。同じ設定のTLS証明書を信頼起点にして、自分自身の/healthまたは/readyを確認する。

証明書検証は無効にしない。トークンは引数・環境変数へ置かず、ファイルまたは標準入力から読む。
トークンなしの確認は、認証前でも応答できること(401)でプロセスの生存を示す。readyの確認にはトークンが要る。
"""

from __future__ import annotations

import argparse
import os
import socket
import ssl
import sys
from collections.abc import Mapping

TIMEOUT_SECONDS = 5.0
MAX_TOKEN_BYTES = 512
_LOOPBACK = "127.0.0.1"


class HealthcheckError(Exception):
	"""設定不足や通信失敗。メッセージにパス・トークン・応答本文は含めない。"""


def split_host(host_header: str) -> str:
	"""Host形式(名前[:ポート]、IPv6は[::1]:ポート)から検証用のホスト名だけを返す。"""
	value = host_header.strip()
	if value.startswith("["):
		return value[1:].split("]", 1)[0]
	return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def is_healthy(status: int, *, authenticated: bool) -> bool:
	if authenticated:
		return status == 200
	# 認証前はトークンを持たないため、認証層まで動いている401も生存として扱う。
	return status in (200, 401)


def parse_status(first_line: bytes) -> int | None:
	parts = first_line.decode("latin-1", "replace").split()
	if len(parts) < 2 or not parts[0].startswith("HTTP/") or not parts[1].isdigit():
		return None
	status = int(parts[1])
	return status if 100 <= status <= 599 else None


def read_token(source: str) -> str:
	"""トークンをファイル('-'は標準入力)から読む。空・過大・読めない場合は拒否する。"""
	try:
		if source == "-":
			raw = sys.stdin.buffer.read(MAX_TOKEN_BYTES + 1)
		else:
			with open(source, "rb") as stream:
				raw = stream.read(MAX_TOKEN_BYTES + 1)
	except OSError:
		raise HealthcheckError("トークンファイルを読めません。") from None
	token = raw.decode("ascii", "ignore").strip()
	if not token or len(raw) > MAX_TOKEN_BYTES:
		raise HealthcheckError("トークンが空、または大きすぎます。")
	return token


def build_context(certificate: str) -> ssl.SSLContext:
	"""設定済み証明書だけを信頼起点にした、TLS 1.2以上の検証付きcontext。"""
	context = ssl.create_default_context(cafile=certificate)
	context.minimum_version = ssl.TLSVersion.TLSv1_2
	return context


def request_status(host_header: str, port: int, certificate: str, path: str, token: str | None) -> int:
	"""loopbackへ検証付きTLSで接続し、HTTPステータスだけを返す(応答本文は読まない)。"""
	try:
		context = build_context(certificate)
		with socket.create_connection((_LOOPBACK, port), timeout=TIMEOUT_SECONDS) as raw:
			with context.wrap_socket(raw, server_hostname=split_host(host_header)) as secure:
				lines = [f"GET {path} HTTP/1.1", f"Host: {host_header}", "Connection: close", "Accept: application/json"]
				if token is not None:
					lines.append(f"Authorization: Bearer {token}")
				secure.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
				data = b""
				while b"\r\n" not in data and len(data) < 1024:
					chunk = secure.recv(256)
					if not chunk:
						break
					data += chunk
	except (OSError, ssl.SSLError, ValueError):
		raise HealthcheckError("サーバーへ接続できません。") from None
	status = parse_status(data.split(b"\r\n", 1)[0])
	if status is None:
		raise HealthcheckError("HTTP応答を解釈できません。")
	return status


def main(argv: list[str] | None = None, environment: Mapping[str, str] | None = None) -> int:
	env = os.environ if environment is None else environment
	parser = argparse.ArgumentParser(description="サーバーのhealth/readyをコンテナ内から確認します。")
	parser.add_argument("--ready", action="store_true", help="/readyを確認する(--token-fileが必要)")
	parser.add_argument("--token-file", help="端末または管理トークンのファイル。'-'で標準入力")
	arguments = parser.parse_args(argv)
	if arguments.ready and not arguments.token_file:
		print("--ready には --token-file が必要です。", file=sys.stderr)
		return 2
	certificate = env.get("SCREEN_TRANSLATION_TLS_CERTIFICATE")
	hosts = [item.strip() for item in env.get("SCREEN_TRANSLATION_ALLOWED_HOSTS", "").split(",") if item.strip()]
	if not certificate or not hosts:
		print("SCREEN_TRANSLATION_TLS_CERTIFICATE と SCREEN_TRANSLATION_ALLOWED_HOSTS が必要です。", file=sys.stderr)
		return 1
	try:
		port = int(env.get("SCREEN_TRANSLATION_PORT", "8443"))
		token = read_token(arguments.token_file) if arguments.token_file else None
		path = "/api/v1/ready" if arguments.ready else "/api/v1/health"
		status = request_status(hosts[0], port, certificate, path, token)
	except (HealthcheckError, ValueError) as error:
		print(f"unhealthy: {error}", file=sys.stderr)
		return 1
	if is_healthy(status, authenticated=token is not None):
		return 0
	print(f"unhealthy: status={status}", file=sys.stderr)
	return 1


if __name__ == "__main__":
	raise SystemExit(main())
