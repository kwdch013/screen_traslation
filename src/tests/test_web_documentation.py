from __future__ import annotations

from pathlib import Path
import re
import unittest


CURRENT_DOCUMENTS = (
	"README.md",
	"docs/specification.md",
	"docs/user_guide.md",
	"docs/developer_guide.md",
)

API_SOURCE_FILES = (
	"src/app/web_capture_api.py",
	"src/app/web_control_api.py",
	"src/app/web_events_api.py",
	"src/app/web_settings_api.py",
)


class WebDocumentationTest(unittest.TestCase):
	def setUp(self) -> None:
		self.repository_root = Path(__file__).resolve().parents[2]
		if not (self.repository_root / "README.md").is_file():
			self.skipTest("実行用コンテナにはドキュメントを含めていません")

	def test_readme_describes_supported_startup_and_security(self) -> None:
		readme = self._read("README.md")

		for expected in (
			"start_screen_translation.cmd",
			"python -m app.main\n",
			"python -m app.main --no-browser",
			"docker compose build",
			"127.0.0.1",
			"X-Capture-Token",
			"docs/specification.md",
			"docs/user_guide.md",
			"docs/developer_guide.md",
			"画面を選び直す",
			"共有を停止",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, readme)

	def test_user_guide_describes_complete_web_operation(self) -> None:
		guide = self._read("docs/user_guide.md")

		for expected in (
			"python -m app.main --web",
			"プレビュー",
			"字幕リスト",
			"設定",
			"設定を保存",
			"次回開始",
			"辞書",
			"用語を登録",
			"画面を選び直す",
			"共有を停止",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, guide)

	def test_developer_guide_describes_current_toolchain_and_workflow(self) -> None:
		guide = self._read("docs/developer_guide.md")

		for expected in (
			"Python 3.14",
			".venv",
			"Docker",
			"Node.js",
			"Vite",
			"unittest",
			"vitest",
			"ruff check src",
			"GitHub Actions",
			"Issue",
			"PR",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, guide)

	def test_docker_guides_run_frontend_test_stage_explicitly(self) -> None:
		for relative_path in ("README.md", "docs/developer_guide.md"):
			with self.subTest(path=relative_path):
				document = self._read(relative_path)
				self.assertIn("docker build --target frontend-test .", document)

	def test_ci_runs_web_documentation_test_on_host(self) -> None:
		workflow = self._read(".github/workflows/ci.yml")

		self.assertIn(
			"PYTHONPATH=src python -m unittest src.tests.test_web_documentation",
			workflow,
		)

	def test_specification_api_table_matches_implemented_routes(self) -> None:
		documented_routes = _documented_api_routes(self._read("docs/specification.md"))
		implemented_routes: set[tuple[str, str]] = set()
		for relative_path in API_SOURCE_FILES:
			implemented_routes.update(_implemented_api_routes(self._read(relative_path)))

		self.assertEqual(implemented_routes, documented_routes)

	def test_specification_describes_state_generation_sse_coordinates_and_security(self) -> None:
		specification = self._read("docs/specification.md")

		for expected in (
			"WebAppService",
			"awaiting_frame",
			"generation",
			"translation_result",
			"state",
			"heartbeat",
			"frame_id",
			"positioning",
			"(0, 0)",
			"Host",
			"Origin",
			"Content-Length",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, specification)

	def test_specification_assigns_subtitle_history_responsibilities(self) -> None:
		specification = self._read("docs/specification.md")

		self.assertIn(
			"`useTranslationEvents.ts`: SSE を購読し、世代と `frame_id` で古い結果を除外して、"
			"履歴を新しい順に最大100件へ制限する",
			specification,
		)
		self.assertIn("`SubtitleList.tsx`: 字幕履歴を表示する", specification)

	def test_current_documentation_does_not_describe_removed_desktop_features(self) -> None:
		for relative_path in CURRENT_DOCUMENTS:
			document = self._read(relative_path).casefold()
			for forbidden in (
				"--desktop",
				"tkinter",
				"mss",
				"pygetwindow",
				"windows ocr",
				"easyocr",
				"ウィンドウ追従",
				"デスクトップアプリ",
				"透過オーバーレイ",
			):
				with self.subTest(path=relative_path, forbidden=forbidden):
					self.assertNotIn(forbidden, document)

	def test_planning_documents_are_marked_as_historical(self) -> None:
		for relative_path in ("docs/requirements.md", "docs/feasibility.md"):
			with self.subTest(path=relative_path):
				opening = "\n".join(self._read(relative_path).splitlines()[:10])
				self.assertIn("経緯資料", opening)

	def _read(self, relative_path: str) -> str:
		return (self.repository_root / relative_path).read_text(encoding="utf-8")


def _implemented_api_routes(source: str) -> set[tuple[str, str]]:
	return {
		(method.upper(), path)
		for method, path in re.findall(
			r'@app\.(get|post|put|patch|delete)\("([^"\n]+)"\)',
			source,
		)
	}


def _documented_api_routes(document: str) -> set[tuple[str, str]]:
	routes: set[tuple[str, str]] = set()
	for line in document.splitlines():
		match = re.fullmatch(
			r"\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`(/[^`]+)`\s*\|.*",
			line,
		)
		if match:
			routes.add((match.group(1), match.group(2)))
	return routes


if __name__ == "__main__":
	unittest.main()
