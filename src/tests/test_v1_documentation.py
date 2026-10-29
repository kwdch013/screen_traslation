from pathlib import Path
import re
import unittest


DOCUMENTS = (
	"requirements/version_1/requirements.md",
	"docs/v1.0/acceptance.md",
	"plan/version_1/roadmap.md",
)


class V1DocumentationTest(unittest.TestCase):
	def setUp(self) -> None:
		self.root = Path(__file__).resolve().parents[2]
		if not (self.root / "README.md").is_file():
			self.skipTest("文書を含むリポジトリをマウントして実行してください")

	def read(self, path: str) -> str:
		return (self.root / path).read_text(encoding="utf-8")

	def requirement_ids(self) -> set[str]:
		document = self.read(DOCUMENTS[0])
		ids = re.findall(r"(?m)^\| (REQ-(?:F|NF)-\d{3}) \|", document)
		self.assertGreaterEqual(len(ids), 20)
		self.assertEqual(len(ids), len(set(ids)), "要件IDを重複定義しない")
		return set(ids)

	def test_every_requirement_has_priority_and_normal_and_failure_checks(self) -> None:
		self.requirement_ids()
		for line in self.read(DOCUMENTS[0]).splitlines():
			if re.match(r"\| REQ-(?:F|NF)-\d{3} \|", line):
				cells = [cell.strip() for cell in line.strip("|").split("|")]
				with self.subTest(requirement=cells[0]):
					self.assertEqual(len(cells), 6)
					self.assertIn(cells[1], ("必須", "推奨"))
					self.assertTrue(all(cells))
					self.assertRegex(cells[4], r"ACC-\d{2}")
					self.assertRegex(cells[5], r"ACC-\d{2}")

	def test_traceability_covers_all_requirements_and_existing_tasks(self) -> None:
		requirements = self.requirement_ids()
		roadmap = self.read(DOCUMENTS[2])
		rows = re.findall(r"(?m)^\| (REQ-(?:F|NF)-\d{3}) \| (.+)$", roadmap)
		self.assertEqual(requirements, {key for key, _ in rows})
		self.assertEqual(len(rows), len(requirements))
		for key, row in rows:
			with self.subTest(requirement=key):
				self.assertRegex(row, r"#\d+")
				self.assertRegex(row, r"ACC-\d{2}")
		self.assertIn("#118", roadmap)
		self.assertIn("REQ-BASE", roadmap)
		self.assertIn("REQ-CONTRACT", roadmap)
		self.assertIn("REQ-SEC", roadmap)

	def test_referenced_acceptance_scenarios_exist_and_have_steps_and_results(self) -> None:
		acceptance = self.read(DOCUMENTS[1])
		scenarios = set(re.findall(r"(?m)^### (ACC-\d{2}) ", acceptance))
		self.assertGreaterEqual(len(scenarios), 10)
		for path in DOCUMENTS:
			with self.subTest(document=path):
				self.assertLessEqual(set(re.findall(r"ACC-\d{2}", self.read(path))), scenarios)
		for scenario in re.split(r"(?m)^### ACC-\d{2} ", acceptance)[1:]:
			for field in ("前提:", "操作:", "期待結果:", "担当:", "証跡:"):
				self.assertIn(field, scenario)

	def test_performance_metrics_include_numeric_limits_and_measurement_protocol(self) -> None:
		requirements = self.read(DOCUMENTS[0])
		for name in ("取得fps", "送信fps", "ROI", "初回準備", "warm p50", "warm p95", "OCR", "古い表示", "CPU", "メモリ", "連続稼働"):
			with self.subTest(metric=name):
				self.assertRegex(requirements, rf"(?m)^\| {re.escape(name)} \| [^\n]*\d[^\n]*\|$")
		acceptance = self.read(DOCUMENTS[1])
		for condition in ("nearest-rank", "単調時計", "SHA-256", "200枚", "300件", "失敗率", "CER", "モデル", "GPU", "RTT"):
			self.assertIn(condition, acceptance)

	def test_confirmation_and_release_cannot_be_inferred_from_document_tests(self) -> None:
		for path in DOCUMENTS:
			with self.subTest(document=path):
				document = self.read(path)
				self.assertIn("Owner", document)
				self.assertIn("未確認", document)
		acceptance = self.read(DOCUMENTS[1])
		for expected in ("ユーザー追加シナリオ", "見た目", "合格扱いにしない", "確認記録", "#110"):
			self.assertIn(expected, acceptance)

	def test_scope_preserves_web_and_excludes_optional_existing_issues(self) -> None:
		requirements = self.read(DOCUMENTS[0])
		for expected in ("Windows", "C#", "Linux", "Python 3.14", "Tesseract", "Argos", "英語→日本語", "単一", "2台目", "暗黙", "追加言語", "新規LLM", "#26", "#49", "撤去しない"):
			self.assertIn(expected, requirements)

	def test_documents_do_not_embed_machine_specific_connection_data(self) -> None:
		for path in DOCUMENTS:
			with self.subTest(document=path):
				document = self.read(path)
				self.assertNotRegex(document, r"\b(?:\d{1,3}\.){3}\d{1,3}\b|/home/|[A-Za-z]:\\Users\\|id_(?:rsa|ed25519)|ssh\s+\S+@")

	def test_relative_document_links_resolve(self) -> None:
		for path in DOCUMENTS:
			for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", self.read(path)):
				if "://" in target or target.startswith("#"):
					continue
				with self.subTest(document=path, target=target):
					self.assertTrue((self.root / path).parent.joinpath(target.split("#")[0]).is_file())

	def test_current_guides_link_to_versioned_requirements_without_changing_web_contract(self) -> None:
		for path in ("README.md", "docs/specification.md", "docs/user_guide.md", "docs/developer_guide.md", "docs/v1.0/development.md"):
			with self.subTest(document=path):
				self.assertIn("requirements/version_1/requirements.md", self.read(path))
