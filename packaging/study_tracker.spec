# PyInstaller one-folder build recipe for Study Tracker.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / "src" / "study_tracker"
datas = [
    (str(PACKAGE / "ui" / "theme"), "study_tracker/ui/theme"),
    (str(PACKAGE / "ui" / "assets"), "study_tracker/ui/assets"),
    (str(PACKAGE / "db" / "migrations"), "study_tracker/db/migrations"),
]
datas += collect_data_files("matplotlib")

a = Analysis(
    [str(PACKAGE / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["matplotlib.backends.backend_qtagg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="StudyTracker",
    icon=str(PACKAGE / "ui" / "assets" / "app.ico"),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="StudyTracker")
