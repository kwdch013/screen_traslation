"""Tesseractを子プロセスとして期限付きで実行する(server専用)。

pytesseractのtimeoutは終了を待たずに戻る経路があり、孫プロセスや回収待ち(zombie)を残し得る。
期限を超えたら子プロセスをプロセスグループごとSIGKILLし、必ずwaitで回収してから戻る。
画像はstdinで渡し、一時ファイルを作らない(期限切れで消し忘れが残らない)。
"""

from __future__ import annotations

import io
import os
import shlex
import signal
import subprocess
from collections.abc import Callable
from typing import Any

from PIL import Image

KILL_WAIT_SECONDS = 5.0  # SIGKILL後の回収待ち上限。カーネルが終了させるため通常は即時


class OcrTimeoutError(Exception):
	"""OCRの期限を超えて打ち切った。文字なしではなく「読み取れなかった」ことを表す。"""


class TesseractFailedError(Exception):
	"""Tesseractを起動できない、または異常終了した。"""


def parse_tsv(text: str) -> dict[str, list[Any]]:
	"""TesseractのTSV出力を列ごとのリストにする(pytesseractのDICT形式と同じ型)。

	引用符の解除はしない(Tesseractは文字をそのまま出す)。textは空の行があっても列を揃える。
	"""
	rows = [row.split("\t") for row in text.strip("\n").split("\n") if row]
	if len(rows) < 1 or len(rows[0]) < 2:
		return {}
	header = rows[0]
	result: dict[str, list[Any]] = {name: [] for name in header}
	for row in rows[1:]:
		row = row + [""] * (len(header) - len(row))
		for index, name in enumerate(header):
			if name == "text":
				result[name].append(row[index])
				continue
			try:
				result[name].append(int(float(row[index])))
			except ValueError:
				result[name].append(row[index])
	return result


def _kill_group(process: subprocess.Popen[bytes]) -> None:
	try:
		os.killpg(process.pid, signal.SIGKILL)
	except (ProcessLookupError, PermissionError):
		process.kill()


def run_tesseract(
	image: Image.Image,
	*,
	command: str,
	language: str,
	config: str,
	timeout_seconds: float,
	threads: int | None = None,
	popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> dict[str, list[Any]]:
	"""画像を認識しTSVを返す。timeout_seconds以内に終わらなければ子プロセスを殺して回収し、OcrTimeoutErrorを送出する。"""
	if timeout_seconds <= 0:
		raise OcrTimeoutError("OCRの残り時間がありません。")
	buffer = io.BytesIO()
	image.save(buffer, format="PNG", compress_level=1)  # 速度優先(転送は同一ホストのpipe)
	env = dict(os.environ)
	if threads is not None:
		env["OMP_THREAD_LIMIT"] = str(threads)
	arguments = [command, "stdin", "stdout", "-l", language, *shlex.split(config), "tsv"]
	try:
		process = popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
			env=env, start_new_session=True)  # 独立グループにして孫ごと止められるようにする
	except OSError as error:
		raise TesseractFailedError(f"Tesseractを起動できません: {error.strerror}") from error
	try:
		stdout, stderr = process.communicate(buffer.getvalue(), timeout=timeout_seconds)
	except subprocess.TimeoutExpired:
		_kill_group(process)
		process.communicate()  # パイプを閉じ、子プロセスを回収する
		raise OcrTimeoutError("OCRが期限を超えたため打ち切りました。") from None
	except BaseException:
		_kill_group(process)
		process.wait(KILL_WAIT_SECONDS)
		raise
	if process.returncode != 0:
		raise TesseractFailedError(f"Tesseractが異常終了しました(終了コード{process.returncode})。")
	return parse_tsv(stdout.decode("utf-8", errors="replace"))
