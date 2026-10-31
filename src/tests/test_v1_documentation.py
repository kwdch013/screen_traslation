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

	def test_development_guide_documents_client_server_and_contract_bootstrap(self) -> None:
		guide = self.read("docs/v1.0/development.md")
		for expected in (
			"client/compose.test.yml",
			"server/compose.test.yml",
			"docker compose -f client/compose.test.yml run --rm test",
			"docker compose -f server/compose.test.yml run --rm test",
			".NET SDK 10.0.402",
			"Runtime 10.0.14",
			"Python 3.14",
			"contracts/README.md",
			"Web版",
			"client/ScreenTranslation.sln",
			"client/global.json",
			".github/workflows/ci.yml",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, guide)

	def test_development_issue_traceability_ids_exist_and_issue_89_and_92_are_complete(self) -> None:
		requirements = self.requirement_ids()
		guide = self.read("docs/v1.0/development.md")
		issue_rows = [line for line in guide.splitlines() if re.match(r"\| #\d+", line)]
		listed_ids = {
			f"{prefix}{number}"
			for row in issue_rows
			for prefix, numbers in re.findall(r"(REQ-(?:F|NF)-)(\d{3}(?:/\d{3})*)", row)
			for number in numbers.split("/")
		}
		self.assertLessEqual(listed_ids, requirements, "対応表の要件IDは要件書に定義されている")

		issue_89_rows = [row for row in issue_rows if row.startswith("| #89 ")]
		self.assertEqual(len(issue_89_rows), 1, "#89の対応表行を1行記載する")
		for requirement_id in ("REQ-F-008", "REQ-NF-009"):
			with self.subTest(requirement=requirement_id):
				self.assertIn(requirement_id, issue_89_rows[0])

		issue_92_rows = [row for row in issue_rows if row.startswith("| #92 ")]
		self.assertEqual(len(issue_92_rows), 1, "#92の対応表を1行記載する")
		for expected in (
			"client/src/ScreenTranslation.Client/Capture/",
			"client/src/ScreenTranslation.Windows/Capture/",
			"REQ-F-006",
			"WGC session/factory",
			"対象状態watcher",
			"実画面取得",
			"自己キャプチャ除外/WDA",
			"混在DPI",
			"#135/#136/#148",
		):
			with self.subTest(issue_92=expected):
				self.assertIn(expected, issue_92_rows[0])
		self.assertNotIn("Windows APIを使う機能は後続Taskで実装", guide)

	def test_issue_73_traceability_records_requirements_deliverables_and_open_scope(self) -> None:
		guide = self.read("docs/v1.0/development.md")
		row = next(line for line in guide.splitlines() if line.startswith("| #73 "))
		for expected in (
			"sessions/",
			"server/tests/test_session_lifecycle.py",
			"REQ-F-006",
			"REQ-F-010",
			"REQ-NF-004",
			"#74",
			"#108",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, row)
		architecture = self.read("docs/v1.0/design/architecture.md")
		design_row = next(line for line in architecture.splitlines() if line.startswith("| #73 |"))
		self.assertIn("REQ-F-006 / REQ-F-010 / REQ-NF-004", design_row)
		operations = self.read("docs/v1.0/operations.md")
		for expected in ("## セッションと切断時の運用", "409 SESSION_IN_USE", "#74", "#108"):
			with self.subTest(operation_doc=expected):
				self.assertIn(expected, operations)
		contract = self.read("contracts/session-state.md")
		self.assertIn("Issue #73 の `SessionManager` はこの遷移表に従い", contract)

	def test_roadmap_maps_bootstrap_to_v1_requirements(self) -> None:
		roadmap = self.read("plan/version_1/roadmap.md")
		row = next(line for line in roadmap.splitlines() if line.startswith("| #68/#69/#103/#104/#105/#106 |"))
		for expected in ("REQ-F-012", "REQ-NF-008/009/010", "10.0.402", "10.0.14", "client/server/contracts"):
			with self.subTest(expected=expected):
				self.assertIn(expected, row)
		self.assertIn("#68 client/server/contractsの雛形", self.read("docs/v1.0/development.md"))


class V1DesignDecisionTest(unittest.TestCase):
	def setUp(self) -> None:
		self.root = Path(__file__).resolve().parents[2]
		if not (self.root / "README.md").is_file():
			self.skipTest("文書を含むリポジトリをマウントして実行してください")
		self.design = self.root / "docs/v1.0/design"
		self.index = self.design / "adr/README.md"
		self.security = self.design / "security.md"
		self.requirements = set(re.findall(
			r"(?m)^\| (REQ-(?:F|NF)-\d{3}) \|",
			(self.root / DOCUMENTS[0]).read_text(encoding="utf-8"),
		))

	def read(self, path: Path) -> str:
		self.assertTrue(path.is_file(), f"設計文書が必要です: {path.relative_to(self.root)}")
		return path.read_text(encoding="utf-8")

	def rows(self, document: str, prefix: str) -> list[list[str]]:
		return [
			[cell.strip() for cell in line.strip("|").split("|")]
			for line in document.splitlines() if line.startswith(f"| {prefix}")
		]

	def test_all_requirements_trace_to_decisions_and_acceptance(self) -> None:
		rows = self.rows(self.read(self.index), "REQ-")
		self.assertEqual(len(rows), len(self.requirements))
		self.assertEqual({row[0] for row in rows}, self.requirements)
		for row in rows:
			with self.subTest(requirement=row[0]):
				self.assertEqual(len(row), 4)
				self.assertRegex(row[1], r"\[ADR-\d{4}\]\([^)]+\.md\)")
				self.assertRegex(row[2], r"Q-\d{2}")
				self.assertRegex(row[3], r"ACC-\d{2}")

	def test_session_id_visibility_and_device_token_changes_trigger_contract_review(self) -> None:
		section = self.read(self.security).split("### session IDの既知性", 1)[1].split("\n## ", 1)[0]
		for expected in (
			"所有者以外に開示される経路",
			"device tokenの認証・発行・共有範囲",
			"OpenAPI",
			"API-004",
			"error fixture",
			"テスト",
			"403/404",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, section)

	def test_decisions_compare_options_and_leave_validation_explicit(self) -> None:
		self.read(self.index)
		adrs = sorted((self.design / "adr").glob("[0-9]*.md"))
		self.assertGreaterEqual(len(adrs), 6)
		for path in adrs:
			with self.subTest(adr=path.name):
				document = self.read(path)
				for heading in ("状態", "対象要件", "背景", "比較", "採用方式", "検証と確定担当", "影響", "根拠"):
					self.assertIn(f"## {heading}", document)
				self.assertIn("設計採用", document)
				self.assertIn("未実施", document)
				self.assertRegex(document, r"Q-\d{2}")
				self.assertRegex(document, r"#57")
				self.assertRegex(document, r"REQ-(?:F|NF)-\d{3}")
				self.assertGreaterEqual(len(self.rows(document, "")), 4)

	def test_threats_have_boundary_countermeasure_owner_and_failure_oracle(self) -> None:
		document = self.read(self.security)
		for heading in ("前提/仮定", "資産と信頼境界", "脅威と設計対策", "認証とTLS", "残余リスク"):
			self.assertIn(f"## {heading}", document)
		rows = self.rows(document, "TH-")
		self.assertGreaterEqual(len(rows), 10)
		self.assertEqual(len(rows), len({row[0] for row in rows}))
		for row in rows:
			with self.subTest(threat=row[0]):
				self.assertEqual(len(row), 7)
				self.assertTrue(all(row))
				self.assertRegex(row[2], r"B-\d")
				self.assertRegex(row[3], r"REQ-(?:F|NF)-\d{3}")
				self.assertRegex(row[5], r"Q-\d{2}.*#\d+")
				self.assertRegex(row[6], r"ACC-\d{2}")

	def test_questions_have_observable_criteria_and_all_references_resolve(self) -> None:
		index = self.read(self.index)
		questions = self.rows(index, "Q-")
		question_ids = {row[0] for row in questions}
		self.assertEqual(len(questions), len(question_ids))
		self.assertGreaterEqual(len(questions), 10)
		for row in questions:
			self.assertEqual(len(row), 6)
			self.assertTrue(all(row))
			self.assertRegex(row[2], r"#\d+")
			self.assertIn("未実施", row[5])
		for path in [self.security, *sorted((self.design / "adr").glob("*.md"))]:
			document = self.read(path)
			with self.subTest(document=path.name):
				self.assertLessEqual(set(re.findall(r"Q-\d{2}", document)), question_ids)
				self.assertLessEqual(set(re.findall(r"REQ-(?:F|NF)-\d{3}", document)), self.requirements)
				self.assertLessEqual(set(re.findall(r"ACC-\d{2}", document)), {f"ACC-{n:02}" for n in range(1, 16)})
				self.assertNotRegex(document, r"\b(?:\d{1,3}\.){3}\d{1,3}\b|/home/|[A-Za-z]:\\Users\\|id_(?:rsa|ed25519)|ssh\s+\S+@")
				for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document):
					if "://" not in target and not target.startswith("#"):
						reference, separator, function_name = target.partition("::")
						reference_path = path.parent.joinpath(reference.split("#")[0])
						self.assertTrue(reference_path.is_file(), target)
						if separator:
							self.assertTrue(self._python_file_defines(reference_path, function_name), target)
				for reference in re.findall(r"`([^`]+\.py)::([A-Za-z_]\w*)`", document):
					reference_path = path.parent.joinpath(reference[0])
					with self.subTest(reference=reference):
						self.assertTrue(reference_path.is_file(), reference[0])
						self.assertTrue(self._python_file_defines(reference_path, reference[1]), reference[1])

	def _python_file_defines(self, path: Path, function_name: str) -> bool:
		if not path.is_file() or path.suffix != ".py":
			return False
		return re.search(rf"^\s*(?:async\s+)?def\s+{re.escape(function_name)}\s*\(", path.read_text(), re.MULTILINE) is not None

	def test_existing_guides_link_to_adopted_design_and_open_validation(self) -> None:
		for name in ("specification.md", "developer_guide.md", "user_guide.md"):
			document = self.read(self.root / "docs" / name)
			self.assertIn("v1.0/design/adr/README.md", document)
			self.assertIn("v1.0/design/security.md", document)
			self.assertIn("設計採用", document)
			self.assertIn("Windows実機", document)
		self.assertIn("docs/v1.0/design/adr/README.md", self.read(self.root / DOCUMENTS[2]))

	def test_downstream_issue_transfer_table_names_every_target_and_design_reference(self) -> None:
		document = self.read(self.root / "docs/v1.0/design/architecture.md")
		section = document.split("## 下流Issueへの仕様反映", 1)[1].split("### 要件IDと設計要素", 1)[0]
		rows = [line for line in section.splitlines() if re.match(r"\| #\d+ \|", line)]
		self.assertGreaterEqual(len(rows), 35)
		issues: list[str] = []
		for row_number, row in enumerate(rows, start=1):
			match = re.match(r"\| #(\d+) \|", row)
			assert match is not None, f"仕様転記対象の表の{row_number}行目がIssue行ではありません: {row}"
			issues.append(match.group(1))
		self.assertEqual(len(issues), len(set(issues)), "仕様転記対象のIssue番号を重複させない")
		for issue, row in zip(issues, rows, strict=True):
			with self.subTest(issue=issue):
				self.assertIn("docs/v1.0/design/architecture.md", row)
				self.assertTrue(row.strip().endswith("|"))


class CaptureExclusionResearchTest(unittest.TestCase):
	def setUp(self) -> None:
		self.root = Path(__file__).resolve().parents[2]
		if not (self.root / "README.md").is_file():
			self.skipTest("文書を含むリポジトリをマウントして実行してください")
		self.document = self.root / "docs/v1.0/research/capture-exclusion.md"

	def test_research_cites_official_api_docs_and_states_constraints(self) -> None:
		self.assertTrue(self.document.is_file())
		text = self.document.read_text(encoding="utf-8")
		for expected in (
			"Windows.Graphics.Capture",
			"DXGI Desktop Duplication",
			"GDI",
			"WDA_EXCLUDEFROMCAPTURE",
			"Windows 10 version 1803",
			"Windows 10 version 1903",
			"Windows 10 version 2004",
			"DXGI_ERROR_ACCESS_LOST",
			"DWM",
			"Windows 11 25H2",
			"未実施",
			"Windows実機が必要",
			"独立 Task #135",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, text)
		for url in (
			"https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.graphicscaptureitem",
			"https://learn.microsoft.com/en-us/windows/win32/api/windows.graphics.capture.interop/nf-windows-graphics-capture-interop-igraphicscaptureiteminterop-createforwindow",
			"https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity",
			"https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api",
			"https://learn.microsoft.com/en-us/windows/win32/gdi/capturing-an-image",
		):
			with self.subTest(url=url):
				self.assertIn(url, text)

	def test_windows_runbook_and_result_template_mark_measurements_unperformed(self) -> None:
		text = self.document.read_text(encoding="utf-8")
		for expected in (
			"実機検証手順",
			"検証プログラム雛形",
			"実測記録テンプレート",
			"OS ビルド",
			"GetLastError",
			"除外確認",
			"未実施",
			"Windows実機が必要",
			"独立 Task #135",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, text)
		self.assertNotRegex(text, r"実測結果: (?:成功|合格)")

	def test_related_design_and_development_guides_link_to_research(self) -> None:
		text = self.document.read_text(encoding="utf-8")
		self.assertIn("REQ-F-001 / ACC-03", text)
		self.assertIn("REQ-F-005 / ACC-07", text)
		self.assertIn("capture-exclusion.md", (self.root / "docs/v1.0/design/adr/0002-windows-client.md").read_text(encoding="utf-8"))
		self.assertIn("capture-exclusion.md", (self.root / "docs/v1.0/development.md").read_text(encoding="utf-8"))


class V1ArchitectureDesignTest(unittest.TestCase):
	def setUp(self) -> None:
		self.root = Path(__file__).resolve().parents[2]
		if not (self.root / "README.md").is_file():
			self.skipTest("文書を含むリポジトリをマウントして実行してください")
		self.design = self.root / "docs/v1.0/design"
		self.architecture = self.design / "architecture.md"

	def read(self, path: Path) -> str:
		self.assertTrue(path.is_file(), f"設計文書が必要です: {path.relative_to(self.root)}")
		return path.read_text(encoding="utf-8")

	def test_architecture_maps_all_requirements_to_detailed_design(self) -> None:
		document = self.read(self.architecture)
		requirements = set(re.findall(
			r"(?m)^\| (REQ-(?:F|NF)-\d{3}) \|",
			(self.root / DOCUMENTS[0]).read_text(encoding="utf-8"),
		))
		rows = re.findall(r"(?m)^\| (REQ-(?:F|NF)-\d{3}) \| (.+)$", document)
		self.assertEqual(requirements, {requirement for requirement, _ in rows})
		self.assertEqual(len(rows), len(requirements))
		for requirement, row in rows:
			with self.subTest(requirement=requirement):
				self.assertRegex(row, r"ACC-\d{2}")
				self.assertRegex(row, r"(?:ADR-\d{4}|INF-\d{3}|CMP-\d{3}|FLW-\d{3})")
		for heading in ("文書情報", "前提/仮定", "システム構成", "技術スタック", "画面", "レイヤー", "業務フロー", "通信・API詳細", "データと状態", "セキュリティ、運用、復旧", "詳細テスト観点", "下流Issueへの仕様反映"):
			with self.subTest(heading=heading):
				self.assertIn(f"## {heading}", document)
		for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document):
			if "//" not in target and not target.startswith("#"):
				with self.subTest(target=target):
					self.assertTrue((self.architecture.parent / target.split("#")[0]).exists(), target)

	def test_final_design_decisions_include_limits_and_real_device_assumptions(self) -> None:
		document = self.read(self.architecture)
		for expected in (
			"採用", ".NET 10", "WPF", "Windows.Graphics.Capture", "WDA_EXCLUDEFROMCAPTURE",
			"HTTPS", "WSS", "TLS 1.2", "Per-Monitor V2", "Tesseract", "Argos",
			"2 fps", "5 fps", "4 MiB", "2,073,600", "4 GiB", "2 CPU",
			"5秒", "10秒", "1秒", "1920×1080", "#135", "#136", "未実施",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, document)
		self.assertRegex(document, r"(?s)前提/仮定.*Windows実機.*未実施")

	def test_design_diagrams_are_editable_svg_pairs_and_embed_consistently(self) -> None:
		document = self.read(self.architecture)
		for stem in ("system-architecture", "layers"):
			with self.subTest(diagram=stem):
				drawio = self.design / "diagrams" / f"{stem}.drawio"
				svg = self.design / "diagrams" / f"{stem}.svg"
				self.assertTrue(drawio.is_file())
				svg_text = self.read(svg)
				self.assertIn("<svg", svg_text)
				self.assertIn(f"diagrams/{stem}.svg", document)
				self.assertIn(f"diagrams/{stem}.drawio", document)

	def test_adr_and_security_show_decisions_separately_from_unperformed_measurements(self) -> None:
		index = self.read(self.design / "adr/README.md")
		adrs = index + "\n".join(path.read_text(encoding="utf-8") for path in sorted((self.design / "adr").glob("[0-9]*.md")))
		for decision in ("HTTPS制御", "WSS", "WPF", "Windows.Graphics.Capture", "段階抽出", "アプリ内TLS終端", "単一所有者", "Tesseract", "Argos"):
			with self.subTest(decision=decision):
				self.assertIn(decision, adrs)
		self.assertIn("採用", index)
		self.assertIn("未実施", index)
		self.assertIn("前提/仮定", self.read(self.design / "security.md"))
		self.assertIn("#135", self.read(self.design / "adr/0002-windows-client.md"))
		self.assertIn("#136", self.read(self.design / "adr/0002-windows-client.md"))

	def test_downstream_issue_specification_reflection_is_complete_and_explicit(self) -> None:
		document = self.read(self.architecture)
		section = document.split("## 下流Issueへの仕様反映", 1)[1]
		issues = {int(number) for number in re.findall(r"(?m)^\| #(\d+) \|", section)}
		self.assertGreaterEqual(len(issues), 20)
		self.assertTrue({61, 62, 63, 68, 72, 73, 75, 77, 78, 79, 80, 81, 82, 83, 84, 85, 88, 89, 90, 92, 93, 94, 95, 97, 98, 99, 100, 103, 104, 105, 106, 108, 109, 110, 111} <= issues)
		for issue in issues:
			with self.subTest(issue=issue):
				row = next(line for line in section.splitlines() if line.startswith(f"| #{issue} |"))
				self.assertGreaterEqual(len(row.split("|")), 4)
				self.assertTrue(row.split("|")[2].strip())
