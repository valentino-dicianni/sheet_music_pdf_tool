#!/usr/bin/env python3
"""Package the desktop app for the platform this runs on (cx_Freeze):

    python3 build_app.py        Linux   -> dist/sheetmusic-tools_<version>_<arch>.deb  (needs dpkg-deb)
    py build_app.py             Windows -> dist/SheetMusicTools-<version>-setup.exe    (needs Inno Setup 6)
                                           or dist/SheetMusicTools-<version>-windows.zip without it

The app is frozen in a separate venv (build/venv) that holds only the GUI dependencies.
Tesseract stays outside the .deb (a package dependency); on Windows an installed Tesseract
(C:\\Program Files\\Tesseract-OCR) is copied into the app, so the .exe needs nothing else."""

import os
import shutil
import subprocess
import sys
import sysconfig
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD, DIST = ROOT / "build", ROOT / "dist"
FROZEN = BUILD / "app"
WINDOWS = sys.platform == "win32"
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
VERSION = PROJECT["version"]
NAME, TITLE = "sheetmusic-tools", "Sheet Music PDF Tools"
EXE = "SheetMusicTools"
TESS_LANGS = ("eng", "osd")                     # the tessdata files bundled on Windows
ICON = ROOT / "sheetmusic/gui/icon.png"         # made from assets/pdf_icon.jpg
# Qt plugins a desktop app never loads (embedded / EGL devices, VNC, the compositor side of Wayland; the GTK theme,
# whose job the xdg portal plugin does): they would only drag in more system libraries as package dependencies
UNUSED_PLUGINS = ("egldeviceintegrations", "wayland-graphics-integration-server", "platforms/libqeglfs.so",
                  "platforms/libqlinuxfb.so", "platforms/libqminimalegl.so", "platforms/libqvnc.so",
                  "platforms/libqvkkhrdisplay.so", "generic", "platformthemes/libqgtk3.so")

LAUNCHER = """import sys
from sheetmusic.__main__ import main
sys.exit(main(sys.argv[1:] or ["gui"]))         # no arguments: the desktop app; otherwise the command line
"""


def run(*cmd, **kw) -> None:
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def venv_python() -> Path:
    py = BUILD / "venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    if not py.exists():
        run(sys.executable, "-m", "venv", BUILD / "venv")
    run(py, "-m", "pip", "install", "-q", "--upgrade", "pip")
    # PySide6-Essentials, not PySide6: the add-ons (WebEngine, 3D, ...) would triple the size for nothing
    run(py, "-m", "pip", "install", "-q", str(ROOT), "PySide6-Essentials", "cx_Freeze>=8.4")
    return py


# ---------------------------------------------------------------------------- freezing (runs inside build/venv)
def freeze() -> None:
    from cx_Freeze import Executable, setup

    launcher = BUILD / "launcher.py"
    launcher.write_text(LAUNCHER)
    icon = None
    if WINDOWS:
        from PIL import Image
        icon = BUILD / "icon.ico"
        Image.open(ICON).save(icon, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    shutil.rmtree(FROZEN, ignore_errors=True)
    options = {
        "build_exe": str(FROZEN),
        "packages": ["sheetmusic"],
        "excludes": ["sheetmusic.bot", "telegram", "telethon", "dotenv", "tkinter", "unittest", "pytest"],
        "include_msvcr": True,
    }
    if not WINDOWS:
        # the system's own libraries (glibc, GL, X11 / Wayland, even a system Qt) come from the distribution, as
        # package dependencies: bundled, they clash with the user's graphics driver and Qt version
        options["bin_path_excludes"] = [d for d in ("/lib", "/lib64", "/usr/lib", "/usr/lib64", "/usr/local/lib")
                                        if Path(d).is_dir()]
        options["bin_includes"] = [f"libpython{sysconfig.get_python_version()}*"]
    setup(
        name=NAME,
        version=VERSION,
        description=TITLE,
        executables=[Executable(launcher, base="gui" if WINDOWS else None, target_name=EXE, icon=icon)],
        options={"build_exe": options},
        script_args=["build_exe"],
    )
    for plugin in UNUSED_PLUGINS:
        for path in (FROZEN / "lib/PySide6/Qt/plugins").glob(plugin):
            shutil.rmtree(path) if path.is_dir() else path.unlink()


def system_depends() -> list[str]:
    """The Debian packages of the system libraries the frozen app links against (what dpkg-shlibdeps would find)."""
    libs: set[str] = set()
    for f in FROZEN.rglob("*"):
        if f.is_file() and (f.suffix == ".so" or ".so." in f.name or f.name == EXE):
            out = subprocess.run(["ldd", str(f)], capture_output=True, text=True).stdout
            for line in out.splitlines():
                parts = line.split("=>")
                if len(parts) == 2 and parts[1].strip().startswith("/"):
                    lib = Path(parts[1].split("(")[0].strip())
                    if not lib.resolve().is_relative_to(FROZEN.resolve()):
                        libs.add(str(lib.resolve()))
    pkgs: set[str] = set()
    for lib in sorted(libs):
        for candidate in (lib, lib.removeprefix("/usr"), "/usr" + lib):
            r = subprocess.run(["dpkg", "-S", candidate], capture_output=True, text=True)
            if r.returncode == 0:
                pkgs.add(r.stdout.split(":")[0].split(",")[0].strip())
                break
        else:
            print(f"warning: no package owns {lib}")
    return sorted(pkgs)


# ---------------------------------------------------------------------------- Linux: .deb
def build_deb() -> Path:
    arch = subprocess.run(["dpkg", "--print-architecture"], capture_output=True, text=True, check=True).stdout.strip()
    root = BUILD / "deb"
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(FROZEN, root / "opt" / NAME)
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin" / NAME).symlink_to(f"/opt/{NAME}/{EXE}")
    icons = root / "usr/share/icons/hicolor/256x256/apps"
    icons.mkdir(parents=True)
    shutil.copy2(ICON, icons / f"{NAME}.png")
    apps = root / "usr/share/applications"
    apps.mkdir(parents=True)
    (apps / f"{NAME}.desktop").write_text(f"""[Desktop Entry]
Type=Application
Name={TITLE}
Comment=Split scanned sheet-music sets into parts; A3 to A4
Exec={NAME} gui
Icon={NAME}
Terminal=false
Categories=Office;Graphics;
""")
    size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file() and not f.is_symlink()) // 1024
    (root / "DEBIAN").mkdir()
    (root / "DEBIAN/control").write_text(f"""Package: {NAME}
Version: {VERSION}
Section: graphics
Priority: optional
Architecture: {arch}
Installed-Size: {size}
Depends: {", ".join(["tesseract-ocr", *system_depends()])}
Maintainer: {os.environ.get("DEBFULLNAME", "Sheet Music Tools")} <{os.environ.get("DEBEMAIL", "noreply@localhost")}>
Description: {PROJECT["description"]}
 Desktop app: split a scanned set into one PDF per instrument (OCR),
 and A3 to A4 with better contrast. Run "{NAME}" or find it in the app menu.
""")
    out = DIST / f"{NAME}_{VERSION}_{arch}.deb"
    run("dpkg-deb", "--root-owner-group", "-Zxz", "--build", root, out)
    return out


# ---------------------------------------------------------------------------- Windows: setup .exe (or .zip)
def bundle_tesseract() -> bool:
    src = Path(os.environ.get("TESSERACT_DIR") or Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR")
    if not (src / "tesseract.exe").is_file():
        print(f"warning: Tesseract not found in {src} (set TESSERACT_DIR): the app will need it installed separately")
        return False
    dst = FROZEN / "tesseract"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("tessdata", "*.html", "doc", "unins*"))
    (dst / "tessdata").mkdir()
    for lang in TESS_LANGS:
        f = src / "tessdata" / f"{lang}.traineddata"
        if f.is_file():
            shutil.copy2(f, dst / "tessdata")
    return True


def find_iscc() -> str | None:
    for c in (shutil.which("iscc"), *(Path(os.environ.get(v, "")) / "Inno Setup 6" / "ISCC.exe"
                                      for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"))):
        if c and Path(c).is_file():
            return str(c)
    return None


def build_windows() -> Path:
    bundle_tesseract()
    iscc = find_iscc()
    if iscc is None:
        print("warning: Inno Setup 6 not found (https://jrsoftware.org/isinfo.php): making a portable .zip instead")
        return Path(shutil.make_archive(str(DIST / f"{EXE}-{VERSION}-windows"), "zip", FROZEN))
    iss = BUILD / "setup.iss"
    iss.write_text(f"""[Setup]
AppName={TITLE}
AppVersion={VERSION}
DefaultDirName={{autopf}}\\{TITLE}
DefaultGroupName={TITLE}
OutputDir={DIST}
OutputBaseFilename={EXE}-{VERSION}-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile={BUILD / "icon.ico"}
UninstallDisplayIcon={{app}}\\{EXE}.exe

[Tasks]
Name: "desktopicon"; Description: "{{cm:CreateDesktopIcon}}"; Flags: unchecked

[Files]
Source: "{FROZEN}\\*"; DestDir: "{{app}}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{{group}}\\{TITLE}"; Filename: "{{app}}\\{EXE}.exe"
Name: "{{autodesktop}}\\{TITLE}"; Filename: "{{app}}\\{EXE}.exe"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{EXE}.exe"; Description: "Start {TITLE}"; Flags: nowait postinstall skipifsilent
""", encoding="utf-8")
    run(iscc, "/Q", iss)
    return DIST / f"{EXE}-{VERSION}-setup.exe"


def main() -> None:
    if "--freeze" in sys.argv:                  # second stage, inside build/venv
        freeze()
        return
    if sys.platform not in ("win32", "linux"):
        sys.exit(f"build_app.py makes a .deb (Linux) or a setup .exe (Windows), not a package for {sys.platform}")
    if not WINDOWS and not shutil.which("dpkg-deb"):
        sys.exit("dpkg-deb not found: the .deb is built on Debian / Ubuntu")
    BUILD.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)
    run(venv_python(), __file__, "--freeze", cwd=ROOT)
    out = build_windows() if WINDOWS else build_deb()
    print(f"\nbuilt {out.relative_to(ROOT)}")
    if not WINDOWS:
        print(f"install: sudo apt install ./{out.relative_to(ROOT)}    run: {NAME}")


if __name__ == "__main__":
    main()
