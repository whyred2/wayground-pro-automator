"""Prepare a native PyInstaller build on Windows, Linux or macOS."""

import argparse
import ast
import json
import os
from pathlib import Path
import platform
import ssl
import subprocess
import sys


def read_version(root):
    tree = ast.parse((root / "src" / "config.py").read_text(encoding="utf-8"))
    return next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "VERSION"
                                                        for target in node.targets))


def platform_label(target, architecture=None):
    name = {"win32": "windows", "darwin": "macos", "linux": "linux"}[target]
    arch = (architecture or platform.machine()).lower()
    arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(arch, arch)
    return f"{name}-{arch}"


def build_command(root, *, target, console=False, distpath=None):
    version = read_version(root)
    label = platform_label(target)
    destination = distpath or (
        ("scratch/gui-debug" if console else f"dist/{version}") if target == "win32" else
        (f"scratch/gui-debug/{label}" if console else f"dist/{version}/{label}"))
    if target == "darwin" and not console:
        return [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", destination,
                "--workpath", f"build/desktop-{version}-{label}",
                str(root / "packaging/WaygroundAutomator-macos.spec")]
    separator = ";" if target == "win32" else ":"
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--noupx",
               "--name", "WaygroundAutomator", "--distpath", destination,
               "--workpath", f"build/desktop-{version}-{label}",
               "--specpath", f"build/specs-{label}",
               "--add-data", f"{root / 'assets'}{separator}assets", "--collect-data", "playwright_stealth",
               "--paths", str(root / "src")]
    command.append("--onefile")
    if target == "win32":
        command.extend(["--console" if console else "--windowed", "--icon", str(root / "assets/icon.ico"),
                        "--version-file", str(root / "assets/version_info.txt")])
    # Some Python runtimes require this PEM beside the frozen ssl module.
    ssl_resource = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
    if ssl_resource.is_file():
        command.extend(["--add-data", f"{ssl_resource}{separator}."])
    command.append(str(root / "src/main.py"))
    return command


def build_environment(target):
    environment = os.environ.copy()
    if target == "win32":
        windows = Path(environment.get("SystemRoot", "C:/Windows"))
        # Keep unrelated tools' ICU/UCRT DLLs out of the Windows build subprocess.
        environment["PATH"] = os.pathsep.join(map(str, [
            Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows,
        ]))
    return environment


def main(argv=None):
    if sys.platform not in ("win32", "darwin", "linux"):
        raise SystemExit("Supported build hosts: Windows, Linux and macOS.")
    parser = argparse.ArgumentParser(description="Build on the target operating system; cross-compilation is not supported.")
    parser.add_argument("--console", action="store_true", help="Build a diagnostic executable")
    parser.add_argument("--distpath", help="Override the output folder")
    parser.add_argument("--dry-run", action="store_true", help="Print the build command without building or writing files")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    command = build_command(root, target=sys.platform, console=args.console, distpath=args.distpath)
    if args.dry_run:
        print(json.dumps({"platform": platform_label(sys.platform), "version": read_version(root),
                          "command": command}, indent=2))
        return
    subprocess.run(command, cwd=root, env=build_environment(sys.platform), check=True)


if __name__ == "__main__":
    main()
