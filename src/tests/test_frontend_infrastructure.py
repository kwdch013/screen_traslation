from __future__ import annotations

from pathlib import Path
import unittest


class FrontendInfrastructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository_root = Path(__file__).resolve().parents[2]
        if not (self.repository_root / "Dockerfile").is_file():
            self.skipTest("実行用コンテナにはリポジトリ設定を含めていません")

    def test_docker_builds_frontend_and_copies_only_dist_to_runtime(self) -> None:
        dockerfile = (self.repository_root / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("FROM node:24-slim AS frontend-build", dockerfile)
        self.assertIn("RUN npm ci", dockerfile)
        self.assertIn("RUN npm run build", dockerfile)
        self.assertIn("COPY --from=frontend-build /frontend/dist ./frontend/dist", dockerfile)
        self.assertLess(dockerfile.index("FROM node:24-slim"), dockerfile.index("FROM python:3.14-slim"))

    def test_dockerignore_excludes_generated_frontend_directories(self) -> None:
        dockerignore = (self.repository_root / ".dockerignore").read_text(encoding="utf-8")

        self.assertIn("frontend/node_modules", dockerignore.splitlines())
        self.assertIn("frontend/dist", dockerignore.splitlines())

    def test_ci_runs_frontend_lint_test_and_build(self) -> None:
        workflow = (self.repository_root / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8",
        )

        self.assertIn("actions/setup-node@v4", workflow)
        self.assertIn("npm run lint", workflow)
        self.assertIn("npm test", workflow)
        self.assertIn("npm run build", workflow)

    def test_dependabot_updates_frontend_npm_dependencies(self) -> None:
        dependabot = (self.repository_root / ".github" / "dependabot.yml").read_text(encoding="utf-8")

        self.assertIn("package-ecosystem: npm", dependabot)
        self.assertIn("directory: /frontend", dependabot)
        self.assertIn("target-branch: dev", dependabot)


if __name__ == "__main__":
    unittest.main()
