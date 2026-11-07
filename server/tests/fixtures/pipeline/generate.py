"""実エンジン結合試験用の固定画像を決定的に生成する。

画像はすべてこのスクリプトが自前で描画するため、第三者の画像権利を含まない。
文字はOS同梱のDejaVu Sans (自由ライセンス) で描く。サーバー試験イメージ内で次の通り再生成できる。

	docker compose -f server/compose.test.yml run --rm --no-deps \
		-v "$PWD/server/tests/fixtures/pipeline:/out" test \
		sh -c "python /out/generate.py /out && chown -R $(id -u):$(id -g) /out"

出力のPNGと、期待値・分類を記した `cases.json` を `/out` へ書く。再生成後は差分を目視確認する。
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# (id, 正解文) / (id, 正解文, 背景方式)
CLEAR = [
	("clear-01", "Press any key to start the game."),
	("clear-02", "Your quest log has been updated."),
	("clear-03", "Do you want to save your progress?"),
	("clear-04", "Settings\nChange the audio and video options."),
	("clear-05", "Not enough gold to buy this item."),
	("clear-06", "Warning: low health. Find a safe place to rest."),
]
COMPLEX = [
	("complex-01", "Open the door and go inside.", "gradient"),
	("complex-02", "The merchant has new items for sale.", "stripes"),
	("complex-03", "Defeat all enemies to continue.", "noise"),
	("complex-04", "Return to the village before night.", "checker"),
]


def _canvas(width: int, height: int, color: tuple[int, int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
	image = Image.new("RGB", (width, height), color)
	return image, ImageDraw.Draw(image)


def _clear(text: str) -> Image.Image:
	lines = text.split("\n")
	font = ImageFont.truetype(FONT, 28)
	width = max(480, int(max(font.getlength(line) for line in lines)) + 48)
	image, draw = _canvas(width, 40 + 44 * len(lines), (255, 255, 255))
	for index, line in enumerate(lines):
		draw.text((24, 20 + 44 * index), line, font=font, fill=(0, 0, 0))
	return image


def _complex(text: str, style: str, seed: int) -> Image.Image:
	rng = random.Random(seed)
	font = ImageFont.truetype(FONT, 28)
	width, height = int(font.getlength(text)) + 64, 96
	image, draw = _canvas(width, height, (20, 30, 70))
	if style == "gradient":
		for y in range(height):
			draw.line([(0, y), (width, y)], fill=(20 + y, 30 + y, 90 + y // 2))
		fill = (255, 255, 255)
	elif style == "stripes":
		for x in range(-height, width, 14):
			draw.line([(x, 0), (x + height, height)], fill=(60, 60, 60), width=6)
		fill = (255, 230, 90)
	elif style == "noise":
		pixels = image.load()
		assert pixels is not None
		for y in range(height):
			for x in range(width):
				value = rng.randint(30, 110)
				pixels[x, y] = (value, value, value + 20)
		fill = (250, 250, 250)
	else:
		for y in range(0, height, 16):
			for x in range(0, width, 16):
				shade = 40 if (x // 16 + y // 16) % 2 else 70
				draw.rectangle([x, y, x + 15, y + 15], fill=(shade, shade, shade))
		fill = (245, 245, 245)
	draw.text((33, 31), text, font=font, fill=(0, 0, 0))  # 影
	draw.text((32, 30), text, font=font, fill=fill)
	return image


def _noise() -> Image.Image:
	rng = random.Random(7)
	image, _draw = _canvas(320, 96, (255, 255, 255))
	pixels = image.load()
	assert pixels is not None
	for y in range(96):
		for x in range(320):
			pixels[x, y] = (rng.randint(0, 255),) * 3
	return image


def build(out: Path) -> list[dict[str, object]]:
	out.mkdir(parents=True, exist_ok=True)
	entries: list[dict[str, object]] = []

	def save(case_id: str, group: str, expected: str, image: Image.Image) -> None:
		path = out / f"{case_id}.png"
		image.save(path, format="PNG", optimize=False)
		entries.append({
			"id": case_id, "group": group, "expected_text": expected, "file": path.name,
			"width": image.width, "height": image.height,
			"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
		})

	for case_id, text in CLEAR:
		save(case_id, "clear", text, _clear(text))
	for index, (case_id, text, style) in enumerate(COMPLEX):
		save(case_id, "complex", text, _complex(text, style, index))
	save("empty-white", "empty", "", _canvas(320, 96, (255, 255, 255))[0])
	save("empty-black", "empty", "", _canvas(320, 96, (0, 0, 0))[0])
	save("unreadable-noise", "unreadable", "", _noise())
	return entries


if __name__ == "__main__":
	destination = Path(sys.argv[1])
	cases = build(destination)
	(destination / "cases.json").write_text(
		json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
	)
