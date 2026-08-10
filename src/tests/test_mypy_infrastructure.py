from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path
import re
import unittest


class MypyInfrastructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository_root = Path(__file__).resolve().parents[2]
        if not (self.repository_root / "Dockerfile").is_file():
            self.skipTest("実行用コンテナにはリポジトリ設定を含めていません")

    def test_development_requirements_pin_mypy(self) -> None:
        requirements = self._read("requirements-dev.txt")

        self.assertRegex(requirements, r"(?m)^mypy==\d+\.\d+\.\d+$")

    def test_mypy_configuration_enables_initial_checks_and_scoped_ignores(self) -> None:
        parser = ConfigParser()
        parser.read(self.repository_root / "mypy.ini", encoding="utf-8")

        self.assertTrue(parser.getboolean("mypy", "check_untyped_defs"))
        self.assertTrue(parser.getboolean("mypy", "warn_unused_ignores"))
        self.assertFalse(parser.getboolean("mypy", "ignore_missing_imports"))
        for module in ("argostranslate.*", "httpx2.*", "psutil", "pytesseract"):
            with self.subTest(module=module):
                self.assertTrue(
                    parser.getboolean(f"mypy-{module}", "ignore_missing_imports"),
                )

    def test_runtime_image_contains_mypy_and_its_configuration(self) -> None:
        dockerfile = self._read("Dockerfile")

        self.assertIn("COPY requirements.txt requirements-dev.txt ./", dockerfile)
        self.assertIn("-r requirements-dev.txt", dockerfile)
        self.assertIn("COPY mypy.ini ./", dockerfile)

    def test_ci_runs_mypy_in_the_built_application_image(self) -> None:
        workflow = self._read(".github/workflows/ci.yml")

        self.assertRegex(
            workflow,
            re.compile(
                r"- name: 型チェック \(mypy\)\n"
                r"\s+run: docker run --rm -e PYTHONPATH=/app/src app:ci mypy src",
            ),
        )

    def test_ci_runs_mypy_for_the_windows_target_platform(self) -> None:
        # 本番実行環境はWindowsのため、msvcrt/ctypes.windll側の型定義でも
        # 型エラーが無いことをCIで確認する (Issue #22 codexレビュー指摘対応)。
        workflow = self._read(".github/workflows/ci.yml")

        self.assertRegex(
            workflow,
            re.compile(
                r"- name: 型チェック \(mypy, Windows向け\)\n"
                r"\s+run: docker run --rm -e PYTHONPATH=/app/src app:ci mypy --platform win32 src",
            ),
        )

    def test_developer_guide_documents_containerized_mypy(self) -> None:
        guide = self._read("docs/developer_guide.md")

        self.assertIn("docker compose run --rm app mypy src", guide)
        self.assertIn("docker compose run --rm app mypy --platform win32 src", guide)

    def _read(self, relative_path: str) -> str:
        return (self.repository_root / relative_path).read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
