from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve()
PACKAGE = ROOT / "jarvis"

datas = [(str(PACKAGE / "config.yaml"), "jarvis"), (str(PACKAGE / "ui" / "web"), "jarvis/ui/web")]
datas += collect_data_files("webview")
datas += collect_data_files("dateparser")
datas += collect_data_files("tzdata")
datas += collect_data_files("edge_tts")
datas += collect_data_files("_sounddevice_data")

binaries = []
binaries += collect_dynamic_libs("vosk")
binaries += collect_dynamic_libs("miniaudio")
binaries += collect_dynamic_libs("webview")

hiddenimports = []
hiddenimports += collect_submodules("dateparser")
hiddenimports += collect_submodules("pycaw")
hiddenimports += collect_submodules("comtypes")
hiddenimports += collect_submodules("yt_dlp.extractor.soundcloud")
hiddenimports += collect_submodules("webview.platforms")
hiddenimports += [
    "pystray._win32",
    "clr",
    "clr_loader",
    "win32timezone",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "pyttsx3.drivers",
    "pyttsx3.drivers.sapi5",
    "winotify",
    "keyboard._winkeyboard",
    "python_speech_features",
    "vlc",
]

a = Analysis(
    [str(PACKAGE / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "matplotlib", "IPython", "jupyter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Jarvis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "libvosk.dll"],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
)
