from pathlib import Path
import unittest


class AiReviewGateDocumentationTest(unittest.TestCase):
	def setUp(self) -> None:
		self.repository_root = Path(__file__).resolve().parents[2]
		if not (self.repository_root / "docs/v1.0/development.md").is_file():
			self.skipTest("文書を含まないテスト用コンテナでは検査しない")

	def test_documents_current_rulesets_and_dependabot_operation(self) -> None:
		document = self._read_development_guide()
		for expected in (
			"2026-11-07 現在の実設定",
			"`protect-develop` (`19132355`)",
			"`protect-main` (`26752581`)",
			"`test`、`AI Review Gate`",
			"mainのAI Review Gateはrequiredにしません",
			"PR #269",
			"@dependabot rebase",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, document)

	def test_documents_only_observed_acceptance_evidence_as_complete(self) -> None:
		document = self._read_development_guide()
		self.assertIn("#### #118受入状況", document)
		self.assertIn("#269", document)
		self.assertIn("BLOCKED", document)
		self.assertIn("未完了", document)

	def _read_development_guide(self) -> str:
		return (self.repository_root / "docs/v1.0/development.md").read_text(encoding="utf-8")
