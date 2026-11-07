"""導入・復旧・ライセンス文書が実成果物と一致することを機械的に検査する (Issue #105)。

文書中のコマンド・環境変数・パス・リンクが、compose・.env.example・配布物定義・
manifest・依存定義の実体と食い違わないこと、特定マシン情報や秘密を含まないこと、
ライセンスの最終確認をOwner判断として扱っていることを確認する。
"""
from pathlib import Path
import json
import re
import unittest


INSTALL_SERVER = "docs/v1.0/install-server.md"
INSTALL_CLIENT = "docs/v1.0/install-client.md"
OPERATIONS = "docs/v1.0/operations.md"
LICENSES = "docs/v1.0/licenses.md"
README = "README.md"
TARGET_DOCS = (README, INSTALL_SERVER, INSTALL_CLIENT, OPERATIONS, LICENSES)


class InstallDocsTest(unittest.TestCase):
	def setUp(self) -> None:
		self.root = Path(__file__).resolve().parents[2]
		if not (self.root / "README.md").is_file() or not (self.root / "server/compose.yml").is_file():
			self.skipTest("文書を含むリポジトリをマウントして実行してください")

	def read(self, path: str) -> str:
		return (self.root / path).read_text(encoding="utf-8")

	def all_text(self) -> dict[str, str]:
		return {path: self.read(path) for path in TARGET_DOCS}

	# ---- 存在と構成 -------------------------------------------------

	def test_必要な文書が存在し主要な見出しを持つ(self) -> None:
		for path in (INSTALL_SERVER, LICENSES):
			self.assertTrue((self.root / path).is_file(), path)
		server = self.read(INSTALL_SERVER)
		for heading in ("Linuxサーバーの導入", "モデルの導入", "TLS証明書と資格情報", "日常操作", "停止", "更新", "ロールバック"):
			with self.subTest(heading=heading):
				self.assertRegex(server, rf"(?m)^#+ .*{heading}")
		client = self.read(INSTALL_CLIENT)
		for heading in ("Windowsクライアントの設定", "日常操作"):
			with self.subTest(heading=heading):
				self.assertRegex(client, rf"(?m)^#+ .*{heading}")
		operations = self.read(OPERATIONS)
		for heading in ("障害の切り分け", "設定・辞書のバックアップと復元", "ログ採取時の秘匿化"):
			with self.subTest(heading=heading):
				self.assertRegex(operations, rf"(?m)^#+ .*{heading}")

	def test_障害の切り分けは必須の症状をすべて扱う(self) -> None:
		section = self.section(self.read(OPERATIONS), "障害の切り分け")
		for symptom in ("キー失効", "証明書期限", "モデル未準備", "切断", "OCR低精度", "DPIずれ"):
			with self.subTest(symptom=symptom):
				self.assertIn(symptom, section)

	def test_READMEはv1_0の導入文書へ案内し旧Web版を別見出しで保持する(self) -> None:
		readme = self.read(README)
		for target in ("docs/v1.0/install-server.md", "docs/v1.0/install-client.md", "docs/v1.0/operations.md", "docs/v1.0/licenses.md"):
			self.assertIn(target, readme)
		self.assertRegex(readme, r"(?m)^## .*v1\.0.*導入")
		self.assertRegex(readme, r"(?m)^## .*(旧|既存).*Web版")
		# 旧Web版の起動手順が残っている
		self.assertIn("start_screen_translation.cmd", readme)
		self.assertIn("python -m app.main", readme)

	# ---- コマンド・環境変数・パスの実体照合 -----------------------------

	def test_composeコマンドのファイル_profile_サービスが実在する(self) -> None:
		compose = self.read("server/compose.yml")
		services = set(re.findall(r"(?m)^  ([a-z][a-z0-9-]*):$", compose.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]))
		profiles = set(re.findall(r"profiles: \[([a-z-]+)\]", compose))
		self.assertEqual(services, {"server", "prepare-model", "admin"})
		for path, text in self.all_text().items():
			for command in re.findall(r"(?m)^\s*(docker compose [^\n`]*)", text):
				with self.subTest(document=path, command=command):
					self.assertNotIn("docker-compose", command)
					files = re.findall(r"-f (\S+)", command)
					for file in files:
						self.assertTrue((self.root / file).is_file(), f"{file} が存在しない")
					for profile in re.findall(r"--profile (\S+)", command):
						if "server/compose.yml" in command:
							self.assertIn(profile, profiles)
					if "server/compose.yml" in command:
						after = re.sub(r"-f \S+|--profile \S+|-p \S+|--rm|-d\b|-T\b", "", command)
						for service in re.findall(r"(?:run|exec|up|kill|stop|logs|ps|build)\b[^\n]*", after)[:1]:
							words = service.split()
							if words[0] in ("run", "exec"):
								candidates = [w for w in words[1:] if not w.startswith("-") and not w.startswith("<") and not w.startswith("'")]
								self.assertIn(candidates[0], services)

	def test_docker_compose_ハイフン形式を使わない(self) -> None:
		for path, text in self.all_text().items():
			with self.subTest(document=path):
				self.assertNotRegex(text, r"docker-compose(?!\.)")

	def test_SERVER_変数は_env_exampleに定義されている(self) -> None:
		defined = set(re.findall(r"(?m)^#?\s*(SERVER_[A-Z_]+)=", self.read("server/.env.example")))
		self.assertTrue({"SERVER_ALLOWED_HOSTS", "SERVER_TLS_DIR", "SERVER_BIND_ADDRESS", "SERVER_API_PORT"} <= defined)
		for path, text in self.all_text().items():
			used = set(re.findall(r"\bSERVER_[A-Z][A-Z_]+\b", text))
			# SERVER_CONTAINER_TEST等の試験用変数は試験文書の管轄。導入文書では使わない
			for name in used:
				with self.subTest(document=path, variable=name):
					self.assertIn(name, defined)

	def test_SCREEN_TRANSLATION_変数は実装かcomposeに存在する(self) -> None:
		known = set(re.findall(r"SCREEN_TRANSLATION_[A-Z_]+", self.read("server/compose.yml")))
		for source in (self.root / "server/src").rglob("*.py"):
			known |= set(re.findall(r"SCREEN_TRANSLATION_[A-Z_]+", source.read_text(encoding="utf-8")))
		known |= set(re.findall(r"SCREEN_TRANSLATION_[A-Z_]+", self.read("server/Dockerfile")))
		self.assertIn("SCREEN_TRANSLATION_ADMIN_TOKEN", known)
		for path, text in self.all_text().items():
			for name in set(re.findall(r"SCREEN_TRANSLATION_[A-Z_]+", text)):
				with self.subTest(document=path, variable=name):
					self.assertIn(name, known)

	def test_PACKAGE_FORBIDDEN_STRINGSなど配布物の変数と版の正本が実在する(self) -> None:
		publish = (self.root / "client/scripts/publish-client.ps1").read_text(encoding="utf-8")
		package = (self.root / "client/scripts/package_client.py").read_text(encoding="utf-8")
		self.assertIn("PACKAGE_FORBIDDEN_STRINGS", package)
		self.assertIn("Version", publish)
		client = self.read(INSTALL_CLIENT)
		self.assertIn("pwsh client/scripts/publish-client.ps1", client)

	def test_バッククォート内のリポジトリパスが実在する(self) -> None:
		prefixes = ("server/", "client/", "docs/", "contracts/", "scripts/", "requirements/", ".github/")
		# 利用者が .env.example から作る生成物は、リポジトリに存在しないのが正しい
		generated = {"server/.env"}
		for path, text in self.all_text().items():
			for token in re.findall(r"`([^`\s]+)`", text):
				token = token.split("#", 1)[0]
				if token in generated:
					self.assertTrue((self.root / "server/.env.example").is_file())
					continue
				if not token.startswith(prefixes) or any(c in token for c in "<>*{}$"):
					continue
				if token.endswith("/"):
					exists = (self.root / token).is_dir()
				else:
					exists = (self.root / token).exists()
				with self.subTest(document=path, token=token):
					self.assertTrue(exists, f"{token} が実在しない")

	def test_コードブロック内のリポジトリパスが実在する(self) -> None:
		for path, text in self.all_text().items():
			for block in re.findall(r"(?s)```(?:sh|bash|powershell)?\n(.*?)```", text):
				for token in re.findall(r"(?<![\w/.-])((?:server|client|docs|contracts|scripts)/[\w./-]+)", block):
					token = token.rstrip(".")
					if token in ("server/.env",):
						continue
					with self.subTest(document=path, token=token):
						self.assertTrue((self.root / token).exists(), f"{token} が実在しない")

	def test_相対リンクと見出しアンカーが解決する(self) -> None:
		for path, text in self.all_text().items():
			base = (self.root / path).parent
			for target in re.findall(r"\]\(([^)\s]+)\)", text):
				if re.match(r"[a-z]+://", target):
					continue
				file_part, _, anchor = target.partition("#")
				destination = (base / file_part) if file_part else (self.root / path)
				with self.subTest(document=path, link=target):
					self.assertTrue(destination.exists(), f"{target} が解決しない")
					if anchor and destination.suffix == ".md":
						self.assertIn(anchor, self.anchors(destination.read_text(encoding="utf-8")), f"{target} の見出しが無い")

	def anchors(self, markdown: str) -> set[str]:
		result = set()
		for heading in re.findall(r"(?m)^#{1,6} +(.+?) *$", markdown):
			slug = re.sub(r"[^\w\- ]", "", heading.lower().replace("`", "")).strip().replace(" ", "-")
			result.add(slug)
		return result

	def section(self, document: str, heading_text: str) -> str:
		match = re.search(rf"(?ms)^(#+) [^\n]*{re.escape(heading_text)}[^\n]*\n(.*?)(?=^\1 |\Z)", document)
		if match is None:
			self.fail(f"見出し {heading_text} が無い")
		return match.group(2)

	# ---- 秘匿・特定環境の混入 -------------------------------------------

	def test_特定マシン情報と秘密を含まない(self) -> None:
		forbidden = {
			"プライベートIPv4": r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b",
			"ホームの絶対パス": r"/home/[a-z]",
			"Windowsユーザー領域": r"[A-Za-z]:\\Users\\",
			"ssh接続先": r"\bssh\s+(?:-\S+\s+)*\S+@",
			"鍵ファイル": r"id_(?:rsa|ed25519|sd_remote)",
			"秘密鍵本文": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
			"64桁hex(token候補)": r"(?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F])",
		}
		for path, text in self.all_text().items():
			for name, pattern in forbidden.items():
				with self.subTest(document=path, rule=name):
					self.assertIsNone(re.search(pattern, text), f"{path} に {name} が含まれる")

	# ---- Issue #266: 表現の統一・手順・危険コマンド -----------------------

	def test_license_acceptedは運用上の導入ゲートでOwner確認の代わりではないと書く(self) -> None:
		for path in (INSTALL_SERVER, LICENSES):
			text = self.read(path)
			for sentence in re.findall(r"[^\n。]*license_accepted[^\n。]*。?", text):
				with self.subTest(document=path, sentence=sentence[:40]):
					# Ownerの確認証跡・確認した証跡とは書かない (実際はOwner未確認のままtrue)
					self.assertNotRegex(sentence, r"(確認した|確認の)証跡")
					self.assertNotIn("Ownerがライセンスを確認した", sentence)
			self.assertRegex(text, r"license_accepted[^\n]*導入ゲート")
			self.assertRegex(text, r"Owner[^\n]*最終確認の代わりでは(?:ない|ありません)")

	def test_提供元の表示は未照合の転記と明記する(self) -> None:
		licenses = self.read(LICENSES)
		self.assertIn("未照合の転記", licenses)
		self.assertIn("提供元での再確認は未実施", licenses)
		self.assertNotIn("調査時点で転記", licenses)

	def test_管理トークンをファイルへ安全に保存する手順がある(self) -> None:
		section = self.section(self.read(INSTALL_SERVER), "管理トークンの保存")
		self.assertIn("umask 077", section)
		self.assertIn("chmod 600", section)
		self.assertIn("0600", section)
		self.assertIn("履歴", section)
		self.assertIn("wait-ready.sh", section)
		# トークンをコマンド引数・環境変数・echoで渡す例を載せない
		for line in section.splitlines():
			if line.lstrip().startswith(("echo ", "printf ", "export ")):
				self.fail(f"トークンを引数や環境変数で扱う例がある: {line}")

	def test_バックアップ復元は既存ファイルを上書きするだけと書く(self) -> None:
		rollback = self.read(INSTALL_SERVER)
		self.assertRegex(rollback, r"上書き[^\n]*余分なファイルは消え")

	DANGEROUS = (
		re.compile(r"\bdown\b[^\n`]*\s(?:-v|--volumes)\b"),
		re.compile(r"\bdocker\s+volume\s+(?:rm|remove|prune)\b"),
		re.compile(r"\bdocker\s+compose\b[^\n`]*\brm\b[^\n`]*\s-\w*v"),
		re.compile(r"\bprune\b[^\n`]*--volumes"),
	)
	NEGATION = re.compile(r"付けない|付与しない|使わない|使用しない|禁止|しないで|ないでください|消えます|消す")

	def dangerous_lines(self, text: str) -> list[str]:
		found = []
		for line in text.splitlines():
			if any(pattern.search(line) for pattern in self.DANGEROUS) and not self.NEGATION.search(line):
				found.append(line.strip())
		return found

	def test_volumeを消すコマンドを勧めない(self) -> None:
		for path, text in self.all_text().items():
			with self.subTest(document=path):
				self.assertEqual(self.dangerous_lines(text), [])

	def test_危険コマンド検査は検出と否定文脈の許容を区別する(self) -> None:
		self.assertTrue(self.dangerous_lines("docker compose -f server/compose.yml down -v"))
		self.assertTrue(self.dangerous_lines("docker compose down --volumes"))
		self.assertTrue(self.dangerous_lines("docker volume rm screen-translation-server_server-data"))
		self.assertTrue(self.dangerous_lines("docker volume prune -f"))
		self.assertEqual(self.dangerous_lines("`down -v` は付けないでください"), [])
		self.assertEqual(self.dangerous_lines("docker volume rm は禁止です"), [])

	# ---- ライセンス棚卸し -------------------------------------------------

	def test_ライセンスの最終確認はOwner判断として扱い合格と書かない(self) -> None:
		licenses = self.read(LICENSES)
		self.assertIn("Owner判断待ち", licenses)
		self.assertIn("未確認", licenses)
		self.assertRegex(licenses, r"本製品[^\n]*ライセンス[^\n]*未決定")
		for phrase in ("ライセンス確認済み", "ライセンス確認完了", "ライセンスに問題なし", "ライセンス合格", "再配布可能と確認"):
			self.assertNotIn(phrase, licenses)
		# 本製品のライセンスを宣言していない
		self.assertNotRegex(licenses, r"(?m)^本製品は[^\n]*(MIT|Apache|GPL|BSD)[^\n]*(で提供|として公開|のもとで)")

	def test_ライセンス一覧は依存定義と配布物のすべてを網羅する(self) -> None:
		licenses = self.read(LICENSES)
		# サーバーのPython依存 (server/requirements.txt と ルートrequirements.txt)
		names = []
		for path in ("server/requirements.txt", "requirements.txt"):
			for line in self.read(path).splitlines():
				match = re.match(r"([A-Za-z0-9_.\-]+)", line.strip())
				if match and not line.strip().startswith("#"):
					names.append(match.group(1))
		self.assertGreaterEqual(len(names), 8)
		first_cells = [
			line.strip("|").split("|")[0].strip().lower()
			for line in licenses.splitlines()
			if line.startswith("| ") and line.count("|") >= 8
		]
		for name in names:
			with self.subTest(package=name):
				self.assertTrue(any(re.search(rf"(?<![\w-]){re.escape(name.lower())}(?![\w-])", cell) for cell in first_cells), f"{name} の行が無い")
		# torch
		self.assertIn("torch", licenses)
		# Dockerfileで導入するOSパッケージ
		dockerfile = self.read("server/Dockerfile")
		for package in re.findall(r"apt-get install[^\n]*?(tesseract-ocr(?:-eng)?)\b", dockerfile) + ["tesseract-ocr", "tesseract-ocr-eng"]:
			self.assertIn(package, licenses)
		# NuGet (すべてのcsproj)
		for csproj in (self.root / "client").rglob("*.csproj"):
			if "tests" in csproj.parts:
				continue
			for package, version in re.findall(r'PackageReference Include="([^"]+)" Version="([^"]+)"', csproj.read_text(encoding="utf-8")):
				with self.subTest(nuget=package):
					self.assertIn(package, licenses)
					self.assertIn(version, licenses)
		# manifestの版・取得元
		model = json.loads(self.read("server/deploy/model-manifest.json"))
		stanza = json.loads(self.read("server/deploy/stanza-manifest.json"))
		self.assertIn(model["source_url"], licenses)
		self.assertIn(model["version"], licenses)
		self.assertIn(stanza["version"], licenses)
		self.assertIn("huggingface.co/stanfordnlp/stanza-en", licenses)
		self.assertIn("stanza-resources", licenses)
		for runtime in (".NET", "WPF", "Python", "Argos", "Stanza", "Tesseract"):
			self.assertIn(runtime, licenses)

	def test_ライセンス一覧の各行に同梱か利用者取得かの判断と状態がある(self) -> None:
		licenses = self.read(LICENSES)
		rows = [line for line in licenses.splitlines() if re.match(r"\| (?!-)", line) and "同梱方針" not in line and "項目" not in line]
		inventory = [r for r in rows if r.count("|") >= 7]
		self.assertGreaterEqual(len(inventory), 15)
		for row in inventory:
			cells = [c.strip() for c in row.strip("|").split("|")]
			with self.subTest(row=cells[0]):
				self.assertTrue(all(cells), "空欄がある")
				self.assertRegex(cells[4], r"^(同梱|同梱しない)")
				self.assertRegex(cells[6], r"Owner判断待ち|未確認")

	def test_配布物の同梱ライセンス通知と整合する(self) -> None:
		notices = self.read("client/publish/THIRD-PARTY-NOTICES.txt")
		licenses = self.read(LICENSES)
		for component in ("System.Security.Cryptography.ProtectedData", "WPF", ".NET"):
			self.assertIn(component, notices)
			self.assertIn(component, licenses)
		self.assertIn("本製品自体のライセンスは未決定", notices)

	def test_文書の要件IDは要件書に実在し対象要件を参照する(self) -> None:
		requirements = self.read("requirements/version_1/requirements.md")
		defined = set(re.findall(r"(?m)^\| (REQ-(?:F|NF)-\d{3}) \|", requirements))
		combined = "\n".join(self.all_text().values())
		used = set(re.findall(r"REQ-(?:F|NF)-\d{3}", combined))
		self.assertLessEqual(used, defined)
		self.assertTrue({"REQ-F-012", "REQ-NF-008", "REQ-NF-009", "REQ-NF-010"} <= used)

	def test_Web版の起動入口は維持されている(self) -> None:
		self.assertTrue((self.root / "start_screen_translation.cmd").is_file())
		self.assertTrue((self.root / "frontend").is_dir())


if __name__ == "__main__":
	unittest.main()
