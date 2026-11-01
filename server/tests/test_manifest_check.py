"""manifestと取得元の差分確認コマンド(#215)の単体試験。取得はスタブで、外部へは通信しない。"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from production_config import MANIFEST_PATH, STANZA_MANIFEST_PATH
from screen_translation_server import manifest_check as mc
from screen_translation_server.engines.stanza_resources import is_commit_pinned_url

DATA = {
	"https://models.example.invalid/a.argosmodel": b"argos-model-bytes",
	"https://res.example.invalid/resources.json": b'{"en": {}}',
	"https://res.example.invalid/en/tokenize/combined.pt": b"tokenize",
}


def observation(data: bytes, final_url: str | None = None) -> mc.Observation:
	return mc.Observation(len(data), hashlib.sha256(data).hexdigest(), final_url)


def model_manifest(data: bytes = DATA["https://models.example.invalid/a.argosmodel"]) -> dict:
	return {
		"version": "1.1",
		"source_url": "https://models.example.invalid/a.argosmodel",
		"size_bytes": len(data),
		"sha256": hashlib.sha256(data).hexdigest(),
		"license_name": "確認済み",
		"license_url": "https://license.example.invalid/",
		"license_accepted": True,
	}


def stanza_manifest(contents: dict[str, bytes] | None = None) -> dict:
	contents = contents or {
		"resources.json": DATA["https://res.example.invalid/resources.json"],
		"en/tokenize/combined.pt": DATA["https://res.example.invalid/en/tokenize/combined.pt"],
	}
	return {
		"version": "1.10.0",
		"files": [
			{
				"path": path,
				"url": f"https://res.example.invalid/{path}",
				"size_bytes": len(data),
				"sha256": hashlib.sha256(data).hexdigest(),
			}
			for path, data in contents.items()
		],
	}


class FakeFetcher:
	def __init__(self, data: dict[str, bytes | Exception | mc.Observation]) -> None:
		self.data = data
		self.calls: list[str] = []

	def __call__(self, url: str, timeout_seconds: float) -> mc.Observation:
		self.calls.append(url)
		value = self.data[url]
		if isinstance(value, Exception):
			raise value
		if isinstance(value, mc.Observation):
			return value
		return observation(value)


class CompareTest(unittest.TestCase):
	def entries(self) -> list[mc.Entry]:
		return mc.entries_from_manifests(model_manifest(), stanza_manifest())

	def test_全件一致なら差分なし(self) -> None:
		results = mc.check_entries(self.entries(), FakeFetcher(dict(DATA)))
		self.assertEqual({r.status for r in results}, {"match"})
		self.assertEqual(len(results), 3)

	def test_ラベルは対象と配置先を示す(self) -> None:
		labels = [e.label for e in self.entries()]
		self.assertEqual(labels, ["argos:1.1", "stanza:1.10.0:resources.json", "stanza:1.10.0:en/tokenize/combined.pt"])

	def test_SHA256だけ違えば差分としてsha256を挙げる(self) -> None:
		data = dict(DATA)
		data["https://res.example.invalid/resources.json"] = b'{"en": {"x": 1}}'
		changed = [r for r in mc.check_entries(self.entries(), FakeFetcher(data)) if r.status == "changed"]
		self.assertEqual(len(changed), 1)
		self.assertEqual(changed[0].differences, ("size_bytes", "sha256"))

	def test_サイズだけ違う観測値はsize_bytesのみ差分(self) -> None:
		entries = self.entries()
		first = entries[0]
		observed = mc.Observation(first.size_bytes + 1, first.sha256)
		fetcher = FakeFetcher({**DATA, first.url: observed})
		result = mc.check_entries(entries, fetcher)[0]
		self.assertEqual((result.status, result.differences), ("changed", ("size_bytes",)))

	def test_SHA256は大文字小文字を区別しない(self) -> None:
		entries = self.entries()
		upper = entries[0].__class__(**{**entries[0].__dict__, "sha256": entries[0].sha256.upper()})
		result = mc.check_entries([upper], FakeFetcher(dict(DATA)))[0]
		self.assertEqual(result.status, "match")

	def test_HTTPS以外へのリダイレクトは差分(self) -> None:
		entries = self.entries()
		first = entries[0]
		observed = mc.Observation(first.size_bytes, first.sha256, "http://elsewhere.example.invalid/x")
		result = mc.check_entries([first], FakeFetcher({first.url: observed}))[0]
		self.assertEqual((result.status, result.differences), ("changed", ("redirect_not_https",)))

	def test_HTTPSのままの別ホストへのリダイレクトはCDNの通常動作で差分にしない(self) -> None:
		first = self.entries()[0]
		observed = mc.Observation(first.size_bytes, first.sha256, "https://cdn.example.invalid/x?Signature=secret")
		result = mc.check_entries([first], FakeFetcher({first.url: observed}))[0]
		self.assertEqual(result.status, "match")

	def test_取得失敗は確認不能で続行する(self) -> None:
		data = dict(DATA)
		data["https://res.example.invalid/resources.json"] = OSError("secret-path")
		results = mc.check_entries(self.entries(), FakeFetcher(data))
		self.assertEqual([r.status for r in results], ["match", "error", "match"])
		self.assertEqual(results[1].differences, ("fetch_failed:OSError",))
		self.assertNotIn("secret-path", repr(results[1]))

	def test_固定SHAが到達不能_404_410なら確認不能で差分にしない(self) -> None:
		# コミット固定URLが削除・force pushで消えた場合。差分(1)ではなく取得不能(3)として報告する(#218)。
		import urllib.error

		for status in (404, 410):
			data = dict(DATA)
			data["https://res.example.invalid/resources.json"] = urllib.error.HTTPError("https://res.example.invalid/resources.json", status, "gone", None, None)  # type: ignore[arg-type]
			results = mc.check_entries(self.entries(), FakeFetcher(data))
			self.assertEqual(results[1].status, "error", status)
			self.assertEqual(results[1].differences, ("fetch_failed:HTTPError",))
			self.assertEqual(mc.exit_code(results), 3)
			self.assertIn("確認不能", mc.format_report(results))

	def test_空のmanifestは確認不能ではなく設定エラー(self) -> None:
		with self.assertRaises(mc.ManifestCheckError):
			mc.entries_from_manifests(model_manifest(), {"version": "1.0", "files": []})

	def test_manifest項目が不正なら設定エラー(self) -> None:
		with self.assertRaises(mc.ManifestCheckError):
			mc.entries_from_manifests({"version": "1.1"}, stanza_manifest())


class ReportTest(unittest.TestCase):
	def test_終了コード(self) -> None:
		def result(status: str) -> mc.Result:
			return mc.Result("x", "https://a.example.invalid/", status, (), None)

		self.assertEqual(mc.exit_code([result("match")]), 0)
		self.assertEqual(mc.exit_code([result("match"), result("error")]), 3)
		self.assertEqual(mc.exit_code([result("changed"), result("error")]), 1)
		self.assertEqual(mc.exit_code([result("changed")]), 1)

	def test_レポートに観測値と更新の注意を含みmanifestは変更しない(self) -> None:
		entries = mc.entries_from_manifests(model_manifest(), stanza_manifest())
		data = dict(DATA)
		data["https://res.example.invalid/resources.json"] = b"new"
		report = mc.format_report(mc.check_entries(entries, FakeFetcher(data)))
		self.assertIn("差分あり", report)
		self.assertIn(hashlib.sha256(b"new").hexdigest(), report)
		self.assertIn("stanza:1.10.0:resources.json", report)
		self.assertIn("自動更新しません", report)
		self.assertIn("一致", report)

	def test_署名付きリダイレクト先URLを報告に出さない(self) -> None:
		first = mc.entries_from_manifests(model_manifest(), stanza_manifest())[0]
		observed = mc.Observation(first.size_bytes + 1, first.sha256, "https://cdn.example.invalid/x?Signature=secret")
		report = mc.format_report(mc.check_entries([first], FakeFetcher({first.url: observed})))
		self.assertIn("差分あり", report)
		self.assertNotIn("secret", report)


class FakeResponse:
	def __init__(self, body: bytes, final_url: str, length: str | None = None) -> None:
		self._stream = io.BytesIO(body)
		self._url = final_url
		self.headers = {"Content-Length": length} if length is not None else {}

	def geturl(self) -> str:
		return self._url

	def read(self, size: int = -1) -> bytes:
		return self._stream.read(size)

	def __enter__(self) -> FakeResponse:
		return self

	def __exit__(self, *args: object) -> None:
		return None


class FetchTest(unittest.TestCase):
	def test_ストリームのサイズとSHA256を計算する(self) -> None:
		body = b"x" * 3_000_000
		seen: list[object] = []

		def opener(request: object, timeout: float) -> FakeResponse:
			seen.append(request)
			return FakeResponse(body, "https://a.example.invalid/f")

		got = mc.fetch_observation("https://a.example.invalid/f", 5, opener=opener)
		self.assertEqual((got.size_bytes, got.sha256), (len(body), hashlib.sha256(body).hexdigest()))
		self.assertEqual(got.final_url, "https://a.example.invalid/f")

	def test_上限を超える取得は中断する(self) -> None:
		body = b"x" * 2_000_000
		with self.assertRaises(ValueError):
			mc.fetch_observation("https://a.example.invalid/f", 5, opener=lambda r, timeout: FakeResponse(body, "https://a.example.invalid/f"), max_bytes=1_000_000)

	def test_HTTP_URLは取得しない(self) -> None:
		def opener(request: object, timeout: float) -> FakeResponse:
			raise AssertionError("通信してはいけない")

		with self.assertRaises(ValueError):
			mc.fetch_observation("http://a.example.invalid/f", 5, opener=opener)

	def test_期限を超えたら中断する(self) -> None:
		clock = iter([0.0, 100.0, 200.0, 300.0])
		with self.assertRaises(TimeoutError):
			mc.fetch_observation(
				"https://a.example.invalid/f", 10,
				opener=lambda r, timeout: FakeResponse(b"x" * 10, "https://a.example.invalid/f"),
				monotonic=lambda: next(clock),
			)


class MainTest(unittest.TestCase):
	def run_main(self, args: list[str], fetcher: FakeFetcher, environment: dict[str, str] | None = None) -> tuple[int, str, str]:
		out, err = io.StringIO(), io.StringIO()
		with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
			code = mc.main(args, environment=environment or {}, fetcher=fetcher)
		return code, out.getvalue(), err.getvalue()

	def write_manifests(self, root: Path) -> list[str]:
		model, stanza = root / "model.json", root / "stanza.json"
		model.write_text(json.dumps(model_manifest()), encoding="utf-8")
		stanza.write_text(json.dumps(stanza_manifest()), encoding="utf-8")
		return ["--model-manifest", str(model), "--stanza-manifest", str(stanza)]

	def test_一致なら0(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			code, out, _ = self.run_main(self.write_manifests(Path(d)), FakeFetcher(dict(DATA)))
		self.assertEqual(code, 0)
		self.assertIn("3件", out)

	def test_差分があれば1でmanifestファイルは書き換えない(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			args = self.write_manifests(Path(d))
			before = {p.name: p.read_bytes() for p in Path(d).iterdir()}
			data = dict(DATA)
			data["https://models.example.invalid/a.argosmodel"] = b"changed"
			code, _, _ = self.run_main(args, FakeFetcher(data))
			after = {p.name: p.read_bytes() for p in Path(d).iterdir()}
		self.assertEqual(code, 1)
		self.assertEqual(before, after)

	def test_対象指定でargosだけ確認する(self) -> None:
		fetcher = FakeFetcher(dict(DATA))
		with tempfile.TemporaryDirectory() as d:
			code, _, _ = self.run_main(["--target", "argos", *self.write_manifests(Path(d))], fetcher)
		self.assertEqual((code, fetcher.calls), (0, ["https://models.example.invalid/a.argosmodel"]))

	def test_環境変数のmanifestを既定にする(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			args = self.write_manifests(Path(d))
			env = {
				"SCREEN_TRANSLATION_MODEL_MANIFEST": args[1],
				"SCREEN_TRANSLATION_STANZA_MANIFEST": args[3],
			}
			code, _, _ = self.run_main([], FakeFetcher(dict(DATA)), env)
		self.assertEqual(code, 0)

	def test_manifest未指定は2で通信しない(self) -> None:
		fetcher = FakeFetcher(dict(DATA))
		code, _, err = self.run_main([], fetcher)
		self.assertEqual((code, fetcher.calls), (2, []))
		self.assertIn("manifest", err)

	def test_manifestが読めなければ2でパスを出さない(self) -> None:
		code, _, err = self.run_main(["--model-manifest", "/nonexistent/secret.json", "--stanza-manifest", "/nonexistent/s2.json"], FakeFetcher({}))
		self.assertEqual(code, 2)
		self.assertNotIn("secret", err)


class ProductionManifestTest(unittest.TestCase):
	"""同梱の本番manifestが、この確認コマンドで読める形であること(通信しない)。"""

	def test_同梱manifestから確認対象を作れる(self) -> None:
		entries = mc.entries_from_files(MANIFEST_PATH, STANZA_MANIFEST_PATH)
		self.assertEqual(entries[0].label.split(":")[0], "argos")
		self.assertTrue(any(e.label.startswith("stanza:") for e in entries))
		self.assertTrue(all(e.url.startswith("https://") for e in entries))

	def test_同梱のStanza資源URLはコミットSHA固定(self) -> None:
		stanza = [e for e in mc.entries_from_files(MANIFEST_PATH, STANZA_MANIFEST_PATH) if e.label.startswith("stanza:")]
		self.assertTrue(stanza)
		self.assertTrue(all(is_commit_pinned_url(e.url) for e in stanza), [e.url for e in stanza if not is_commit_pinned_url(e.url)])


if __name__ == "__main__":
	unittest.main()
