"""Build the standalone desktop executable with an isolated Windows DLL path."""

import argparse
import ast
import os
from pathlib import Path
import subprocess
import sys


def main():
    if sys.platform != "win32":
        raise SystemExit("Build the Windows executable on Windows.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--console", action="store_true", help="Diagnostic console build")
    parser.add_argument("--distpath", help="Alternative output folder when a previous executable is running")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "src" / "config.py").read_text(encoding="utf-8"))
    version = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets))
    environment = os.environ.copy()
    windows = Path(environment.get("SystemRoot", "C:/Windows"))
    # An unrelated tool's ICU/UCRT DLLs on PATH must not shadow Windows APIs
    # while PyInstaller resolves Qt dependencies. Qt's own DLLs are located
    # by its package hooks. This changes the build subprocess only.
    environment["PATH"] = os.pathsep.join(map(str, [
        Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows,
    ]))
    destination = args.distpath or ("scratch/gui-debug" if args.console else f"dist/{version}")
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--noupx",
        "--console" if args.console else "--windowed", "--name", "WaygroundAutomator",
        "--distpath", destination, "--workpath", f"build/desktop-{version}",
        "--icon", "assets/icon.ico", "--version-file", "assets/version_info.txt",
        "--add-data", "assets;assets", "--collect-data", "playwright_stealth", "--paths", "src", "src/main.py",
    ]
    subprocess.run(command, cwd=root, env=environment, check=True)


if __name__ == "__main__":
    main()
