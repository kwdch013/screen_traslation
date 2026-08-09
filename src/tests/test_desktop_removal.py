from __future__ import annotations

from pathlib import Path
import re
import unittest


class DesktopRemovalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository_root = Path(__file__).resolve().parents[2]

    def test_desktop_modules_are_removed(self) -> None:
        for relative_path in (
            "src/app/desktop_app.py",
            "src/app/tk_overlay.py",
            "src/app/window.py",
        ):
            with self.subTest(path=relative_path):
                self.assertFalse((self.repository_root / relative_path).exists())

    def test_runtime_has_no_tkinter_mss_or_pygetwindow_imports(self) -> None:
        forbidden_import = re.compile(r"(?:^|\n)\s*(?:from|import)\s+(?:tkinter|mss|pygetwindow)\b")

        for path in (self.repository_root / "src" / "app").glob("*.py"):
            with self.subTest(path=path.name):
                self.assertIsNone(forbidden_import.search(path.read_text(encoding="utf-8")))


class DesktopRepositoryRemovalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository_root = Path(__file__).resolve().parents[2]
        if not (self.repository_root / "Dockerfile").is_file():
            self.skipTest("実行用コンテナにはリポジトリ設定を含めていません")

    def test_runtime_dependencies_and_container_have_no_desktop_packages(self) -> None:
        requirements = (self.repository_root / "requirements.txt").read_text(encoding="utf-8")
        dockerfile = (self.repository_root / "Dockerfile").read_text(encoding="utf-8")
        launcher = (self.repository_root / "start_screen_translation.cmd").read_text(encoding="utf-8")

        self.assertNotRegex(requirements, r"(?im)^\s*(?:mss|pygetwindow)(?:\W|$)")
        self.assertNotRegex(dockerfile, r"(?m)^\s*tk\s*\\?\s*$")
        self.assertNotIn("--desktop", launcher)
        self.assertNotRegex(launcher, r"(?i)import[^\n]*(?:mss|pygetwindow)")


if __name__ == "__main__":
    unittest.main()
