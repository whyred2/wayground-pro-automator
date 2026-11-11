# Native macOS app bundle with release metadata set before code signing.
import ast
from pathlib import Path
import ssl

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
tree = ast.parse((root / "src/config.py").read_text(encoding="utf-8"))
version = next(ast.literal_eval(node.value) for node in tree.body
               if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "VERSION"
                                                       for target in node.targets))
datas = [(str(root / "assets"), "assets")] + collect_data_files("playwright_stealth")
ssl_resource = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
if ssl_resource.is_file():
    datas.append((str(ssl_resource), "."))

a = Analysis([str(root / "src/main.py")], pathex=[str(root / "src")], binaries=[], datas=datas,
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="WaygroundAutomator", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="WaygroundAutomator")
app = BUNDLE(coll, name="WaygroundAutomator.app", icon=str(root / "assets/logo.png"),
             bundle_identifier="io.github.whyred2.waygroundautomator", version=version,
             info_plist={"CFBundleVersion": version, "NSHighResolutionCapable": True})
