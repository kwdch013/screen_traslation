"""本番Compose(server/compose.yml)を実コンテナで起動し、停止・再開・作り直しを操作する試験用ハーネス(Issue #196)。

ホストのDocker Compose v2を使う。TLSの一時CA・証明書とtokenは試験ごとに生成して破棄し、
OSの信頼ストアには触れない。固定のsleepは同期条件にせず、期限付きの状態ポーリングで待つ。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import tempfile
import time

import httpx

from ws_client import SyncWebSocket

SERVER_DIRECTORY = Path(__file__).resolve().parents[2]
TOKEN_PATTERN = re.compile(r"\b[0-9a-f]{64}\b")


def wait_until(predicate: Callable[[], bool], timeout: float, description: str, interval: float = 1.0) -> None:
	"""期限付きのポーリング。timeoutは固定待ちではなく、条件が満たされない場合の失敗検出に使う。"""
	deadline = time.monotonic() + timeout
	while not predicate():
		if time.monotonic() >= deadline:
			raise TimeoutError(f"{timeout}秒以内に条件を満たしませんでした: {description}")
		time.sleep(interval)


def free_port() -> int:
	with socket.socket() as probe:
		probe.bind(("127.0.0.1", 0))
		return int(probe.getsockname()[1])


def openssl(*arguments: object) -> None:
	result = subprocess.run(["openssl", *map(str, arguments)], capture_output=True, text=True, check=False)
	if result.returncode:
		raise RuntimeError(f"openssl failed: {result.stderr[-300:]}")


class ComposeStack:
	"""自分専用のプロジェクト名で本番Composeを動かす。volumeはプロジェクトに閉じる。"""

	def __init__(self, extra_files: list[Path], models_from: str | None, image: str | None) -> None:
		self._temporary = tempfile.TemporaryDirectory(prefix="server-container-")
		self.directory = Path(self._temporary.name)
		self.project = f"stc-{secrets.token_hex(4)}"
		self.port = free_port()
		self.models_from = models_from
		self.tls_directory = self.directory / "tls"
		self._make_certificates()
		env = {
			"SERVER_API_PORT": str(self.port),
			"SERVER_ALLOWED_HOSTS": f"localhost:{self.port}",
			"SERVER_TLS_DIR": str(self.tls_directory),
		}
		if image:
			env["SERVER_IMAGE"] = image
		(self.directory / "env").write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
		self.files = [SERVER_DIRECTORY / "compose.yml", *extra_files]
		self.admin_token = ""
		self.device_token = ""

	def _make_certificates(self) -> None:
		current = self.tls_directory / "current"
		current.mkdir(parents=True)
		ca = self.tls_directory
		openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", ca / "ca.key", "-out", ca / "ca.pem",
			"-days", "2", "-subj", "/CN=Container Test CA", "-addext", "basicConstraints=critical,CA:TRUE",
			"-addext", "keyUsage=critical,keyCertSign,cRLSign")
		openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", current / "private-key.pem",
			"-out", ca / "server.csr", "-subj", "/CN=localhost")
		(ca / "server.ext").write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n", encoding="ascii")
		openssl("x509", "-req", "-in", ca / "server.csr", "-CA", ca / "ca.pem", "-CAkey", ca / "ca.key",
			"-CAcreateserial", "-out", current / "fullchain.pem", "-days", "2", "-extfile", ca / "server.ext")
		# 使い捨ての試験鍵。コンテナの非root(UID 10001)が読めるよう、一時ディレクトリ内に限り全員読み取り可にする。
		for path in (self.tls_directory, current):
			path.chmod(0o755)
		for path in current.iterdir():
			path.chmod(0o644)

	def compose(self, *arguments: str, timeout: float = 600, environment: dict[str, str] | None = None,
		check: bool = True) -> subprocess.CompletedProcess[str]:
		command = ["docker", "compose", "-p", self.project, "--env-file", str(self.directory / "env")]
		for file in self.files:
			command += ["-f", str(file)]
		result = subprocess.run([*command, *arguments], capture_output=True, text=True, timeout=timeout, check=False,
			env={**os.environ, **(environment or {})})
		if check and result.returncode:
			raise RuntimeError(f"docker compose {' '.join(arguments[:3])} が失敗しました(終了コード {result.returncode}): {result.stderr[-400:]}")
		return result

	def prepare(self) -> None:
		"""イメージのビルド、モデルの準備、資格情報の発行を行う。"""
		self.compose("build", timeout=1800)
		self.compose("create", "server")  # volumeを(非root所有で)作る
		if self.models_from:
			# 既存volumeを読み取り専用で借り、自分専用のvolumeへ複製する(借り元は変更しない)。
			volume = f"{self.project}_server-models"
			subprocess.run(["docker", "run", "--rm", "--entrypoint", "sh", "-v", f"{self.models_from}:/src:ro",
				"-v", f"{volume}:/dst", self.image_name(), "-c", "cp -a /src/. /dst/"], check=True, capture_output=True, timeout=600)
		# 複製の有無によらず準備段階を通す(複製済みなら再取得せず検証し、Stanza資源だけを取得する。外向き通信が必要)。
		self.compose("--profile", "model", "run", "--rm", "prepare-model", timeout=3600)
		expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
		self.admin_token = self._issue("init-admin", "--expires-at", expires)
		environment = {"SCREEN_TRANSLATION_ADMIN_TOKEN": self.admin_token}
		self.device_token = self._issue("issue", "container-device", "--role", "device", "--expires-at", expires, environment=environment)

	def image_name(self) -> str:
		out = self.compose("config", "--images", "server").stdout.split()
		return out[0]

	def _issue(self, *arguments: str, environment: dict[str, str] | None = None) -> str:
		output = self.compose("--profile", "admin", "run", "--rm", "admin", *arguments, environment=environment).stdout
		tokens = TOKEN_PATTERN.findall(output)
		if len(tokens) != 1:
			raise RuntimeError("資格情報の発行結果からtokenを1つ取得できませんでした。")
		return tokens[0]

	# --- 操作 ---
	def container_id(self) -> str:
		return self.compose("ps", "-q", "server").stdout.strip()

	def started_at(self) -> str:
		return subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}", self.container_id()],
			capture_output=True, text=True, check=True).stdout.strip()

	def health(self) -> str:
		rows = [json.loads(line) for line in self.compose("ps", "--format", "json", "server").stdout.splitlines() if line.strip()]
		return str(rows[0].get("Health", "")) if rows else ""

	def logs(self) -> str:
		result = self.compose("logs", "--no-color", "server")
		return result.stdout + result.stderr

	def exec_python(self, code: str) -> str:
		return self.compose("exec", "-T", "server", "python", "-c", code).stdout.strip()

	def teardown(self) -> None:
		# 自分が作ったプロジェクトのvolume・networkだけを消す(他プロジェクトには触れない)。
		if os.environ.get("SERVER_TEST_KEEP") == "1":  # 失敗調査用。プロジェクト名を出して残す
			print(f"残したプロジェクト: {self.project}")
			return
		self.compose("down", "--volumes", "--remove-orphans", check=False, timeout=300)
		self._temporary.cleanup()

	# --- クライアント(検証付きTLS。一時CAだけを信頼する) ---
	def trusted_context(self) -> ssl.SSLContext:
		return ssl.create_default_context(cafile=str(self.tls_directory / "ca.pem"))

	def client(self) -> httpx.Client:
		return httpx.Client(base_url=f"https://localhost:{self.port}", verify=self.trusted_context(), trust_env=False, timeout=10)

	def websocket(self, token: str) -> SyncWebSocket:
		return SyncWebSocket(f"wss://localhost:{self.port}/api/v1/stream", ssl=self.trusted_context(),
			open_timeout=30, additional_headers={"Authorization": f"Bearer {token}"})

	def is_ready(self) -> bool:
		try:
			with self.client() as client:
				return client.get("/api/v1/ready", headers={"Authorization": f"Bearer {self.device_token}"}).status_code == 200
		except httpx.HTTPError:
			return False  # 起動中の接続拒否は未readyとして扱う

	def wait_ready(self, timeout: float = 900) -> None:
		wait_until(self.is_ready, timeout, "ready(200)")

	def start_and_wait(self, *, recreate: bool = False) -> None:
		self.compose("up", "-d", *(["--force-recreate"] if recreate else []))
		self.wait_ready()

