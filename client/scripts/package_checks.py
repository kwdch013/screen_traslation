"""配布物へ秘密・固定接続先・ビルド環境の情報を混ぜないための内容検査。

検査結果の文言には一致した文字列そのものを含めない
(CIログや報告に秘密・実環境の値を残さないため)。
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Sequence

# 利用者の設定・資格情報は利用者ごとの保存先にだけ置き、配布物へ入れない
FORBIDDEN_FILE_NAMES = frozenset({
	"settings.json",
	"device-credential.bin",
	"admin-credential.bin",
})
# 証明書・鍵・デバッグ記号(ビルド環境の絶対パスを含む)・ログ・環境変数ファイル
FORBIDDEN_SUFFIXES = (".pfx", ".p12", ".key", ".pem", ".cer", ".crt", ".snk", ".pdb", ".log", ".env")

PRIVATE_KEY_MARKER = re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
# 私設ネットワークのIPv4。直前直後が数字・ドットなら別の数列(版番号等)とみなす
_PRIVATE_ADDRESS = (
	r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
	r"|192\.168\.\d{1,3}\.\d{1,3}"
	r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\d])"
)
# ビルドした環境のユーザー領域・実行領域の絶対パス
_BUILD_PATH = r"(?:/home/[A-Za-z0-9_.-]+|[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+)"
OWN_FILE_PREFIX = "ScreenTranslation."
# 我々が作ったコードが入るファイル。runtime/frameworkのDLLは混入元ではないため除外する
OWN_FILE_SUFFIXES = (".dll", ".exe", ".json", ".config", ".xaml", ".baml", ".manifest")
MIN_EXTRA_LENGTH = 4


@dataclass(frozen=True)
class Violation:
	path: str
	reason: str

	def __str__(self) -> str:
		return f"{self.path}: {self.reason}"


def _search_both_encodings(pattern: str, data: bytes) -> bool:
	"""ASCII/UTF-8の並びと、UTF-16LE(C#の文字列リテラルの格納形式)の並びの両方を照合する。"""
	compiled = re.compile(pattern)
	if compiled.search(data.decode("latin-1")):
		return True
	# UTF-16は2バイト境界が不明なため、0と1バイト目始まりの両方で読む
	return any(compiled.search(data[offset:].decode("utf-16-le", errors="ignore")) for offset in (0, 1))


def is_own_file(relative_path: str) -> bool:
	name = relative_path.rsplit("/", 1)[-1]
	return name.startswith(OWN_FILE_PREFIX) and name.lower().endswith(OWN_FILE_SUFFIXES)


def check_entry(relative_path: str, data: bytes, extra_forbidden: Sequence[str] = ()) -> list[Violation]:
	"""1ファイルを検査し、違反の一覧を返す。"""
	violations: list[Violation] = []
	name = relative_path.rsplit("/", 1)[-1].lower()
	if name in FORBIDDEN_FILE_NAMES:
		violations.append(Violation(relative_path, "利用者の設定・資格情報ファイルは配布物へ含められない"))
	if name.endswith(FORBIDDEN_SUFFIXES):
		violations.append(Violation(relative_path, "証明書・鍵・デバッグ記号・ログ・環境変数ファイルは配布物へ含められない"))
	if PRIVATE_KEY_MARKER.search(data):
		violations.append(Violation(relative_path, "秘密鍵の本文を含んでいる"))
	for text in extra_forbidden:
		if len(text) >= MIN_EXTRA_LENGTH and _contains_text(data, text):
			violations.append(Violation(relative_path, "指定された禁止文字列を含んでいる"))
	if is_own_file(relative_path):
		if _search_both_encodings(_PRIVATE_ADDRESS, data):
			violations.append(Violation(relative_path, "固定接続先になりうる私設ネットワークのアドレスを含んでいる"))
		if _search_both_encodings(_BUILD_PATH, data):
			violations.append(Violation(relative_path, "ビルド環境のユーザー領域の絶対パスを含んでいる"))
	return violations


def _contains_text(data: bytes, text: str) -> bool:
	return text.encode("utf-8") in data or text.encode("utf-16-le") in data


def check_all(entries: Iterable[tuple[str, bytes]], extra_forbidden: Sequence[str] = ()) -> list[Violation]:
	found: list[Violation] = []
	for relative_path, data in entries:
		found.extend(check_entry(relative_path, data, extra_forbidden))
	return found
