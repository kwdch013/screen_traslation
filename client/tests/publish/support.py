"""配布物の試験で共有する、疑似publish出力の組み立て。"""
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "client" / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
	sys.path.insert(0, str(SCRIPTS_DIRECTORY))

ENTRY_POINT = "ScreenTranslation.Windows.exe"
NOTICES_TEXT = "THIRD-PARTY NOTICES (試験用)\n"


def write_publish_tree(root: Path) -> Path:
	"""dotnet publish の出力に似た最小のディレクトリを作る。"""
	root.mkdir(parents=True, exist_ok=True)
	files = {
		ENTRY_POINT: b"MZ\x90\x00 entry",
		"ScreenTranslation.Windows.dll": b"MZ windows",
		"ScreenTranslation.Client.dll": b"MZ client",
		"ScreenTranslation.Windows.deps.json": b'{"runtimeTarget": {}}',
		"ScreenTranslation.Windows.runtimeconfig.json": b'{"runtimeOptions": {}}',
		"System.Private.CoreLib.dll": b"MZ corelib",
		"sub/PresentationFramework.dll": b"MZ wpf",
	}
	for name, data in files.items():
		target = root / name
		target.parent.mkdir(parents=True, exist_ok=True)
		target.write_bytes(data)
	return root


def write_notices(path: Path) -> Path:
	path.write_text(NOTICES_TEXT, encoding="utf-8")
	return path
