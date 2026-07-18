from __future__ import annotations

from pathlib import Path
import unittest


class WebDocumentationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository_root = Path(__file__).resolve().parents[2]
        if not (self.repository_root / "README.md").is_file():
            self.skipTest("実行用コンテナにはドキュメントを含めていません")

    def test_readme_describes_web_start_stop_and_reselect(self) -> None:
        readme = (self.repository_root / "README.md").read_text(encoding="utf-8")

        self.assertIn("python -m app.main\n", readme)
        self.assertIn("python -m app.main --no-browser", readme)
        self.assertIn("画面を選び直す", readme)
        self.assertIn("共有を停止", readme)

    def test_user_guide_describes_web_start_stop_and_reselect(self) -> None:
        guide = (self.repository_root / "docs" / "user_guide.md").read_text(encoding="utf-8")

        self.assertIn("python -m app.main --web", guide)
        self.assertIn("画面を選び直す", guide)
        self.assertIn("共有を停止", guide)

    def test_current_documentation_does_not_guide_removed_desktop_option_or_backends(self) -> None:
        for relative_path in (
            "docs/user_guide.md",
            "docs/specification.md",
            "docs/developer_guide.md",
        ):
            with self.subTest(path=relative_path):
                document = (self.repository_root / relative_path).read_text(encoding="utf-8")
                self.assertNotIn("--desktop", document)
                self.assertNotIn("mss", document.casefold())
                self.assertNotIn("pygetwindow", document.casefold())
                self.assertNotIn("tkinter", document.casefold())


if __name__ == "__main__":
    unittest.main()
