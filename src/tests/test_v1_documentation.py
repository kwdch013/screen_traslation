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
		self.assertEqual(scenarios, {f"ACC-{number:02d}" for number in range(1, 16)})
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
				self.assertIn("Owner承認済み", document)
				self.assertIn("2026-10-29", document)
				self.assertIn("#60/#109", document)
				self.assertRegex(document, r"https://github\.com/[^/]+/[^/]+/issues/55#issuecomment-\d+")
				self.assertNotRegex(document, r"Owner(?:未確認|確認待ち)|草案（Owner確認待ち）")
		acceptance = self.read(DOCUMENTS[1])
		for expected in ("ユーザー追加シナリオ", "見た目", "合格扱いにしない", "確認記録", "#110"):
			self.assertIn(expected, acceptance)
		self.assertIn("a8c0f528ce95c9208977ed262b4ef2a81e7b56d7", acceptance)
		self.assertIn("AskUserQuestion", acceptance)
		self.assertIn("このまま承認", acceptance)
		rows = [line for line in acceptance.splitlines() if line.startswith("| ")]
		owner_rows = [line for line in rows if "| Owner |" in line]
		self.assertEqual(len(owner_rows), 5)
		for line in owner_rows:
			self.assertIn("未実施" if "本人の見た目" in line else "承認済み", line)
		for subject in ("実機性能結果", "独立シナリオ結果"):
			self.assertTrue(any(subject in line and "未実施" in line for line in rows))

	def test_downstream_requirements_are_reflected_without_claiming_design_or_measurement(self) -> None:
		roadmap = self.read(DOCUMENTS[2])
		section = roadmap.split("## Owner承認後の下流反映", 1)[1].split("## 現行文書", 1)[0]
		rows = [line for line in section.splitlines() if line.startswith("| #")]
		self.assertEqual(len(rows), 9)
		for row in rows:
			with self.subTest(targets=row.split("|")[1]):
				self.assertIn("要求反映済み", row)
				self.assertNotIn("反映待ち", row)
		for remaining in ("spec/pending", "native dependency", "未確定", "未実施", "#57", "#109", "#110"):
			self.assertIn(remaining, section)

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
				document = self.read(path)
				self.assertIn("requirements/version_1/requirements.md", document)
				self.assertNotRegex(document, r"Owner確認待ち|Ownerの対応環境・性能値・受入手順の確認は未実施")
