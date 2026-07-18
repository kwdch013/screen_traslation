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

        self.assertIn("python -m app.main --web", readme)
        self.assertIn("画面を選び直す", readme)
        self.assertIn("共有を停止", readme)

    def test_user_guide_describes_web_start_stop_and_reselect(self) -> None:
        guide = (self.repository_root / "docs" / "user_guide.md").read_text(encoding="utf-8")

        self.assertIn("python -m app.main --web", guide)
        self.assertIn("画面を選び直す", guide)
        self.assertIn("共有を停止", guide)


if __name__ == "__main__":
    unittest.main()
