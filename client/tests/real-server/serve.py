"""クライアントの結合試験用に、本物のサーバーアプリ(screen_translation_server.app)を実TLSで起動する。

OCR・翻訳のエンジンだけを固定の代替にし、HTTPS制御API・WSS・セッション管理・認証・TLSは製品と同じ経路を通す。
起動のたびに一時CA・サーバー証明書・端末資格情報を生成し、共有ディレクトリへ公開する(固定の秘密をリポジトリへ置かない)。

共有ディレクトリ(引数1。既定 /shared)へ書くもの:
- ca.pem: 一時CAの証明書(クライアントが信頼する)
- device-a.token / device-b.token: 端末資格情報(別々の所有者として使う)
- ready: すべての待受が始まった合図(最後に作る)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time

from app.contracts import Rect, TextRegion
from screen_translation_server.admin.credentials import CredentialManager
from screen_translation_server.app import create_app, create_server
from screen_translation_server.pipeline import TranslationPipeline
from screen_translation_server.security.auth import (
	CredentialStore,
	Role,
	SecurityPolicy,
	create_credential,
	create_server_tls_context,
)
from screen_translation_server.sessions import SessionManager

# クライアント側の証明書検証はホスト名を照合するため、試験側が接続に使う名前をSANに入れる(同じnamespaceのloopback)
HOST_NAME = os.environ.get("REAL_SERVER_HOST_NAME", "localhost")
READY_PORT = 8443
NOT_READY_PORT = 8444
# 切断検知を速くして、試験が所有権の解放を待つ時間を短くする(製品の既定は5秒)
DISCONNECT_TIMEOUT = 1.0


def openssl(*arguments: object) -> None:
	result = subprocess.run(["openssl", *map(str, arguments)], capture_output=True, text=True, check=False)
	if result.returncode:
		raise RuntimeError(f"openssl failed: {result.stderr[-300:]}")


def make_certificates(directory: Path) -> None:
	openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", directory / "ca.key",
		"-out", directory / "ca.pem", "-days", "2", "-subj", "/CN=Client Integration Test CA",
		"-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
	openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", directory / "server.key",
		"-out", directory / "server.csr", "-subj", f"/CN={HOST_NAME}")
	(directory / "server.ext").write_text(
		f"subjectAltName=DNS:{HOST_NAME}\nextendedKeyUsage=serverAuth\nkeyUsage=digitalSignature,keyEncipherment\n",
		encoding="ascii",
	)
	openssl("x509", "-req", "-in", directory / "server.csr", "-CA", directory / "ca.pem",
		"-CAkey", directory / "ca.key", "-CAcreateserial", "-out", directory / "server.pem",
		"-days", "2", "-extfile", directory / "server.ext")


def fixed_ocr(_frame: object) -> list[TextRegion]:
	"""画像の中身によらず、画像内の固定領域に1行を返す(結果の往復を確認するため)。"""
	return [TextRegion("Hello", Rect(10, 10, 100, 30), 0.99)]


class Instance:
	"""1つの待受(app+uvicorn)。別スレッドのイベントループで動かす。"""

	def __init__(self, directory: Path, port: int, *, ready: bool) -> None:
		self.port = port
		data_dir = directory / f"data-{port}"
		data_dir.mkdir()
		# create_app/create_serverは保存先・待受を環境変数から読む。1つずつ作る間だけ設定する
		os.environ.update({
			"SCREEN_TRANSLATION_DATA_DIR": str(data_dir),
			"SCREEN_TRANSLATION_BIND_HOST": "0.0.0.0",
			"SCREEN_TRANSLATION_PORT": str(port),
		})
		sessions = SessionManager(clock=time.monotonic, sleep=asyncio.sleep, disconnect_timeout=DISCONNECT_TIMEOUT)
		app = create_app(
			credentials=CredentialStore.from_file(directory / "credentials.json"),
			policy=SecurityPolicy(frozenset({f"{HOST_NAME}:{port}"})),
			is_ready=ready,
			sessions=sessions,
			pipeline=TranslationPipeline(fixed_ocr, lambda text: f"訳:{text}", clock=time.monotonic, is_current=sessions.is_current),
		)
		self.server = create_server(app, tls_context=create_server_tls_context(directory / "server.pem", directory / "server.key"))
		self.thread = threading.Thread(target=lambda: asyncio.run(self.server.serve()), daemon=True)

	def start(self) -> None:
		self.thread.start()
		deadline = time.monotonic() + 60
		while not self.server.started:
			if time.monotonic() > deadline or not self.thread.is_alive():
				raise RuntimeError(f"ポート{self.port}の待受が始まりませんでした。")
			time.sleep(0.05)

	def stop(self) -> None:
		self.server.should_exit = True
		self.thread.join(timeout=15)


def main() -> int:
	shared = Path(sys.argv[1] if len(sys.argv) > 1 else "/shared")
	# 前回の実行の資格情報・ready合図が残っていても、新しい実行のものと取り違えない
	for name in ("ready", "ca.pem", "device-a.token", "device-b.token"):
		(shared / name).unlink(missing_ok=True)
	with tempfile.TemporaryDirectory(prefix="client-integration-server-") as temporary:
		directory = Path(temporary)
		make_certificates(directory)
		token_a, token_b = secrets.token_hex(32), secrets.token_hex(32)
		expires = datetime.now(UTC) + timedelta(hours=2)
		CredentialManager(directory / "credentials.json")._write([
			create_credential(token_a, Role.DEVICE, expires, "device-a"),
			create_credential(token_b, Role.DEVICE, expires, "device-b"),
		])
		instances = [Instance(directory, READY_PORT, ready=True), Instance(directory, NOT_READY_PORT, ready=False)]
		for instance in instances:
			instance.start()
		(shared / "ca.pem").write_text((directory / "ca.pem").read_text(encoding="ascii"), encoding="ascii")
		(shared / "device-a.token").write_text(token_a, encoding="ascii")
		(shared / "device-b.token").write_text(token_b, encoding="ascii")
		(shared / "ready").write_text("ready", encoding="ascii")
		print("client integration server ready", flush=True)

		stop = threading.Event()
		for name in (signal.SIGTERM, signal.SIGINT):
			signal.signal(name, lambda *_: stop.set())
		stop.wait()
		for instance in instances:
			instance.stop()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
