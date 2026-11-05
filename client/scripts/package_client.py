"""Windowsクライアントの配布物(zip・チェックサム・manifest)の生成と検証。

dotnet publish の出力ディレクトリから、同じ入力なら同じバイト列になるzipを作る。
配布物には利用者の設定・資格情報・秘密・固定接続先を含めない(package_checks)。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import zipfile

import package_checks

ENTRY_POINT = "ScreenTranslation.Windows.exe"
RUNTIME = "win-x64"
NOTICES_NAME = "THIRD-PARTY-NOTICES.txt"
README_NAME = "README.txt"
INNER_MANIFEST = "package-manifest.json"
SUMS_NAME = "SHA256SUMS"
RELEASE_MANIFEST = "release-manifest.json"
# zipの更新時刻を固定して再現可能にする(zipの下限である1980-01-01)
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
# 版はSemVer(任意のpre-release付き)のみ。パスやファイル名へ使うため厳密に絞る
_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")


class PackageError(Exception):
	"""配布物の生成・検証の失敗。"""


@dataclass(frozen=True)
class PackageResult:
	zip_path: Path
	sums_path: Path
	manifest_path: Path


def check_version(version: str) -> str:
	if not _VERSION.match(version):
		raise PackageError("版は 1.2.3 または 1.2.3-rc.1 の形式で指定してください。")
	return version


def _sha256(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()


def _violations_to_error(violations: list[package_checks.Violation]) -> PackageError:
	return PackageError("配布物に含められない内容があります: " + "; ".join(str(v) for v in violations[:20]))


def _collect(publish_dir: Path) -> dict[str, bytes]:
	files: dict[str, bytes] = {}
	for path in sorted(publish_dir.rglob("*")):
		if path.is_file() and not path.is_symlink():
			files[path.relative_to(publish_dir).as_posix()] = path.read_bytes()
	return files


def build_package(
	publish_dir: Path,
	output_dir: Path,
	version: str,
	notices: Path,
	readme: Path | None = None,
	commit: str = "",
	extra_forbidden: tuple[str, ...] = (),
) -> PackageResult:
	check_version(version)
	if not (publish_dir / ENTRY_POINT).is_file():
		raise PackageError(f"起動入口 {ENTRY_POINT} が publish 出力にありません。")
	if not notices.is_file():
		raise PackageError("依存ライセンスの一覧が見つかりません。")
	files = _collect(publish_dir)
	violations = package_checks.check_all(files.items(), extra_forbidden)
	if violations:
		raise _violations_to_error(violations)
	for reserved in (NOTICES_NAME, README_NAME, INNER_MANIFEST):
		if reserved in files:
			raise PackageError(f"{reserved} は配布物の生成側が付与するため publish 出力に置けません。")
	files[NOTICES_NAME] = notices.read_bytes()
	if readme is not None:
		files[README_NAME] = readme.read_bytes()
	manifest = {
		"product": "ScreenTranslation",
		"version": version,
		"commit": commit,
		"runtime": RUNTIME,
		"self_contained": True,
		"entry_point": ENTRY_POINT,
		"files": [
			{"path": name, "sha256": _sha256(data), "size": len(data)}
			for name, data in sorted(files.items())
		],
	}
	files[INNER_MANIFEST] = _json_bytes(manifest)
	output_dir.mkdir(parents=True, exist_ok=True)
	zip_path = output_dir / f"ScreenTranslation-Client-{version}-{RUNTIME}.zip"
	_write_zip(zip_path, f"ScreenTranslation-{version}", files)
	zip_bytes = zip_path.read_bytes()
	digest = _sha256(zip_bytes)
	sums_path = output_dir / SUMS_NAME
	sums_path.write_text(f"{digest} *{zip_path.name}\n", encoding="utf-8", newline="\n")
	manifest_path = output_dir / RELEASE_MANIFEST
	manifest_path.write_bytes(_json_bytes({
		"product": "ScreenTranslation",
		"version": version,
		"commit": commit,
		"runtime": RUNTIME,
		"entry_point": ENTRY_POINT,
		"artifact": {"name": zip_path.name, "sha256": digest, "size": len(zip_bytes)},
		"file_count": len(files),
	}))
	return PackageResult(zip_path, sums_path, manifest_path)


def _json_bytes(value: object) -> bytes:
	return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_zip(zip_path: Path, prefix: str, files: dict[str, bytes]) -> None:
	with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
		for name in sorted(files):
			info = zipfile.ZipInfo(f"{prefix}/{name}", FIXED_TIMESTAMP)
			info.compress_type = zipfile.ZIP_DEFLATED
			info.external_attr = 0o644 << 16
			archive.writestr(info, files[name])


def verify_package(output_dir: Path, version: str, extra_forbidden: tuple[str, ...] = ()) -> None:
	"""生成済みの配布物が、チェックサム・manifest・内容検査・版のすべてに合うことを確認する。"""
	check_version(version)
	zip_path = output_dir / f"ScreenTranslation-Client-{version}-{RUNTIME}.zip"
	if not zip_path.is_file():
		raise PackageError(f"版 {version} の配布物 {zip_path.name} が見つかりません。")
	digest = _sha256(zip_path.read_bytes())
	expected_line = f"{digest} *{zip_path.name}"
	sums_path = output_dir / SUMS_NAME
	if not sums_path.is_file() or expected_line not in sums_path.read_text(encoding="utf-8").splitlines():
		raise PackageError("チェックサムが SHA256SUMS と一致しません。")
	release = json.loads((output_dir / RELEASE_MANIFEST).read_text(encoding="utf-8"))
	if release.get("version") != version or release["artifact"]["sha256"] != digest:
		raise PackageError("release-manifest の版またはチェックサムが配布物と一致しません。")
	prefix = f"ScreenTranslation-{version}/"
	with zipfile.ZipFile(zip_path) as archive:
		contents = {
			info.filename[len(prefix):]: archive.read(info)
			for info in archive.infolist()
			if not info.is_dir()
		}
		outside = [info.filename for info in archive.infolist() if not info.filename.startswith(prefix)]
	if outside:
		raise PackageError("zip内に配布物ディレクトリ外のファイルがあります。")
	_verify_inner(contents, version)
	violations = package_checks.check_all(contents.items(), extra_forbidden)
	if violations:
		raise _violations_to_error(violations)


def _verify_inner(contents: dict[str, bytes], version: str) -> None:
	if INNER_MANIFEST not in contents:
		raise PackageError("zip内に package-manifest.json がありません。")
	manifest = json.loads(contents[INNER_MANIFEST])
	if manifest.get("version") != version:
		raise PackageError("package-manifest の版が指定の版と一致しません。")
	if manifest.get("entry_point") != ENTRY_POINT or ENTRY_POINT not in contents:
		raise PackageError("起動入口が配布物にありません。")
	if NOTICES_NAME not in contents:
		raise PackageError("依存ライセンスの一覧が配布物にありません。")
	listed = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
	actual = {name: _sha256(data) for name, data in contents.items() if name != INNER_MANIFEST}
	if listed != actual:
		raise PackageError("package-manifest とzip内のファイル(一覧またはSHA-256)が一致しません。")


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	sub = parser.add_subparsers(dest="command", required=True)
	build = sub.add_parser("package", help="publish出力から配布物を作る")
	build.add_argument("--publish-dir", type=Path, required=True)
	build.add_argument("--notices", type=Path, required=True)
	build.add_argument("--readme", type=Path)
	build.add_argument("--commit", default="")
	verify = sub.add_parser("verify", help="生成済みの配布物を検証する")
	for command in (build, verify):
		command.add_argument("--output-dir", type=Path, required=True)
		command.add_argument("--version", required=True)
		# 実環境固有の値(ホスト名など)は環境変数で受け、リポジトリへ書かない
		command.add_argument("--forbid-env", default="PACKAGE_FORBIDDEN_STRINGS",
			help="配布物に含めてはならない文字列を ; 区切りで持つ環境変数名")
	args = parser.parse_args(argv)
	extra = tuple(t for t in os.environ.get(args.forbid_env, "").split(";") if t)
	try:
		if args.command == "package":
			result = build_package(args.publish_dir, args.output_dir, args.version, args.notices,
				args.readme, args.commit, extra)
			print(f"生成: {result.zip_path.name}")
		verify_package(args.output_dir, args.version, extra)
		print("検証: OK")
	except PackageError as error:
		print(f"失敗: {error}", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
