"""Build desktop and console entries with shared resources in directory mode."""
# PyInstaller injects its build classes when executing this specification.
# ruff: noqa: F821

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# A small standalone helper runs before the main application is installed.
installer_helper = Analysis(
    ["script/installer_data.py"], pathex=["."], binaries=[], datas=[],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False, optimize=0,
)
EXE(
    PYZ(installer_helper.pure), installer_helper.scripts,
    installer_helper.binaries, installer_helper.datas, [],
    name="Xalling-DataSetup", console=True, icon=["favicon.ico"],
)

datas = [("frontend/dist", "frontend/dist"), ("tutorials", "tutorials")]
binaries = [
    ("plugins/bin/claude-proxy-rust.exe", "plugins/bin"),
    ("plugins/bin/claude.exe", "plugins/bin"),
]
hiddenimports = [
    "backend.scheduler",  # Restore jobs persisted before the service package move.
    "clr",
]
# Uvicorn selects loop and protocol modules dynamically for the build platform.
hiddenimports += collect_submodules("uvicorn")
datas += collect_data_files("claude_agent_sdk")
for package in ("anydoc", "zvec", "fastembed", "onnxruntime", "tokenizers"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
clr_datas, clr_binaries, clr_imports = collect_all("clr_loader")
datas += clr_datas
binaries += clr_binaries
hiddenimports += clr_imports

executables = []
shared_binaries = []
shared_datas = []
for script, name, console in [
    ("main.py", "Xalling", False),
    ("main_headless.py", "Xalling-Server", True),
]:
    analysis = Analysis(
        [script],
        pathex=[],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
        optimize=0,
    )
    pyz = PYZ(analysis.pure)
    executable = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=["favicon.ico"],
    )
    executables.append(executable)
    shared_binaries += analysis.binaries
    shared_datas += analysis.datas

collection = COLLECT(
    *executables,
    shared_binaries,
    shared_datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Xalling",
)
