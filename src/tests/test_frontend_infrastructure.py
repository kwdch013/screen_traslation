from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import unittest


@dataclass(frozen=True)
class DockerStage:
    base: str
    instructions: tuple[tuple[str, tuple[str, ...]], ...]


class FrontendInfrastructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository_root = Path(__file__).resolve().parents[2]
        if not (self.repository_root / "Dockerfile").is_file():
            self.skipTest("実行用コンテナにはリポジトリ設定を含めていません")

    def test_docker_builds_frontend_and_copies_only_dist_to_runtime(self) -> None:
        stages = _parse_dockerfile(self.repository_root / "Dockerfile")

        self.assertEqual(stages["frontend-deps"].base, "node:24-slim")
        self.assertEqual(stages["frontend-build"].base, "frontend-deps")
        self.assertEqual(stages["frontend-test"].base, "frontend-build")
        self.assertEqual(_instruction_values(stages["frontend-deps"], "RUN"), [("npm", "ci")])
        self.assertIn(("npm", "run", "build"), _instruction_values(stages["frontend-build"], "RUN"))
        self.assertIn(("npm", "run", "lint"), _instruction_values(stages["frontend-test"], "RUN"))
        self.assertIn(("npx", "vitest", "run"), _instruction_values(stages["frontend-test"], "RUN"))
        runtime = stages["<unnamed-4>"]
        self.assertEqual(runtime.base, "python:3.14-slim")
        self.assertIn(
            ("--from=frontend-build", "/frontend/dist", "./frontend/dist"),
            _instruction_values(runtime, "COPY"),
        )

    def test_dockerignore_excludes_generated_frontend_directories(self) -> None:
        dockerignore = (self.repository_root / ".dockerignore").read_text(encoding="utf-8")

        self.assertIn("frontend/node_modules", dockerignore.splitlines())
        self.assertIn("frontend/dist", dockerignore.splitlines())

    def test_ci_runs_frontend_lint_test_and_build(self) -> None:
        steps = _parse_named_workflow_steps(
            self.repository_root / ".github" / "workflows" / "ci.yml",
        )

        self.assertEqual(
            steps["フロントエンド検証 (コンテナ内)"].get("run"),
            "docker build --target frontend-test --tag frontend-test:ci .",
        )
        self.assertNotIn("working-directory", steps["フロントエンド検証 (コンテナ内)"])
        self.assertEqual(
            steps["フロントエンドインフラ構成テスト (ホスト)"].get("run"),
            "PYTHONPATH=src python -m unittest src.tests.test_frontend_infrastructure",
        )
        self.assertEqual(
            steps["デスクトップ撤去構成テスト (ホスト)"].get("run"),
            "PYTHONPATH=src python -m unittest "
            "src.tests.test_desktop_removal.DesktopRepositoryRemovalTest",
        )
        self.assertNotIn("フロントエンド依存関係を復元", steps)
        self.assertNotIn("フロントエンド lint", steps)
        self.assertNotIn("フロントエンドテスト", steps)
        self.assertNotIn("フロントエンドビルド", steps)

    def test_dependabot_updates_frontend_npm_dependencies(self) -> None:
        dependabot = (self.repository_root / ".github" / "dependabot.yml").read_text(encoding="utf-8")

        self.assertIn("package-ecosystem: npm", dependabot)
        self.assertIn("directory: /frontend", dependabot)
        self.assertIn("target-branch: dev", dependabot)


def _parse_dockerfile(path: Path) -> dict[str, DockerStage]:
    stages: dict[str, DockerStage] = {}
    current_name: str | None = None
    current_base = ""
    current_instructions: list[tuple[str, tuple[str, ...]]] = []
    unnamed_index = 0

    def save_stage() -> None:
        if current_name is not None:
            stages[current_name] = DockerStage(current_base, tuple(current_instructions))

    for line in _logical_dockerfile_lines(path):
        keyword, value = line.split(maxsplit=1)
        if keyword.upper() == "FROM":
            save_stage()
            parts = shlex.split(value)
            unnamed_index += 1
            current_base = parts[0]
            current_name = parts[2] if len(parts) == 3 and parts[1].upper() == "AS" else f"<unnamed-{unnamed_index}>"
            current_instructions = []
            continue
        if current_name is not None:
            current_instructions.append((keyword.upper(), tuple(shlex.split(value))))
    save_stage()
    return stages


def _logical_dockerfile_lines(path: Path) -> list[str]:
    logical_lines: list[str] = []
    buffered = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        buffered = f"{buffered} {stripped}".strip()
        if buffered.endswith("\\"):
            buffered = buffered[:-1].rstrip()
            continue
        logical_lines.append(buffered)
        buffered = ""
    if buffered:
        logical_lines.append(buffered)
    return logical_lines


def _instruction_values(stage: DockerStage, keyword: str) -> list[tuple[str, ...]]:
    return [value for instruction, value in stage.instructions if instruction == keyword]


def _parse_named_workflow_steps(path: Path) -> dict[str, dict[str, str]]:
    steps: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        name_match = re.fullmatch(r" {6}- name: (.+)", line)
        if name_match:
            current = {}
            steps[name_match.group(1)] = current
            continue
        if re.match(r" {6}- ", line):
            current = None
            continue
        field_match = re.fullmatch(r" {8}(run|working-directory): (.+)", line)
        if current is not None and field_match:
            current[field_match.group(1)] = field_match.group(2)
    return steps


if __name__ == "__main__":
    unittest.main()
