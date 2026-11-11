"""
Browser auto-detection and launching with Chrome DevTools Protocol (CDP) debugging port.
"""

import os
from pathlib import Path
import shutil
import sys
import subprocess
import time

from config import C_BOLD, C_DIM, C_YELLOW, C_RESET
from ui import log_info, log_error, log_step
from app_paths import app_data_dir


def find_browser_exe() -> tuple[str, str]:
    """
    Auto-detect an installed Edge, Chrome or Chromium on the current platform.
    Returns (path, name) or exits if not found.
    """
    override = os.environ.get("WAYGROUND_BROWSER", "").strip()
    if override:
        path = shutil.which(override)
        if path:
            return path, "Custom browser"
        log_error("WAYGROUND_BROWSER must name an executable browser path or command.")
        sys.exit(1)
    candidates = []
    if sys.platform == "win32":
        candidates = [
            # Keep the existing Windows preference for Edge.
            (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
            (os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
            (os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
            (os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"), "Chrome"),
            (os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"), "Chrome"),
            (os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"), "Chrome"),
        ]
    elif sys.platform == "darwin":
        for directory in (Path("/Applications"), Path.home() / "Applications"):
            for bundle, binary, name in (
                ("Microsoft Edge", "Microsoft Edge", "Edge"),
                ("Google Chrome", "Google Chrome", "Chrome"),
                ("Chromium", "Chromium", "Chromium"),
            ):
                candidates.append((str(directory / f"{bundle}.app" / "Contents" / "MacOS" / binary), name))
    for command, name in (
        ("microsoft-edge", "Edge"), ("microsoft-edge-stable", "Edge"),
        ("google-chrome", "Chrome"), ("google-chrome-stable", "Chrome"),
        ("chromium", "Chromium"), ("chromium-browser", "Chromium"),
    ):
        path = shutil.which(command)
        if path:
            candidates.append((path, name))

    for path, name in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path, name

    log_error("Could not find Edge, Chrome or Chromium. Install one or set WAYGROUND_BROWSER.")
    print(f"  {C_DIM}Looked in:{C_RESET}")
    for path, name in candidates:
        print(f"    {C_DIM}{path}{C_RESET}")
    sys.exit(1)


def get_user_data_dir(browser_name: str) -> str:
    """
    Get the persistent user data directory for automation.
    Using a dedicated profile prevents conflicts with already running Edge/Chrome instances,
    ensures the debug port opens instantly, and permanently preserves Wayground logins.
    """
    profile_dir = app_data_dir() / "BrowserProfile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return str(profile_dir)


def is_port_open(port: int) -> bool:
    """Check if a CDP port is already open."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def launch_browser_with_debug(port: int, *, interactive: bool = True) -> subprocess.Popen:
    """
    Find Edge/Chrome, launch with --remote-debugging-port.
    Uses dedicated automator profile so debug port opens instantly even
    if user already has Edge/Chrome running with 100 tabs.
    """
    exe_path, browser_name = find_browser_exe()
    user_data = get_user_data_dir(browser_name)

    log_info(f"Found {browser_name}: {exe_path}")
    log_info(f"Automation Profile: {user_data}")

    cmd = [
        exe_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    log_info(f"Launching {browser_name} with debug port {port}...")
    process_options = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        process_options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        process_options["start_new_session"] = True
    proc = subprocess.Popen(cmd, **process_options)

    # Wait for browser to start and open the debug port (typically 1-2 seconds with dedicated profile)
    for i in range(12):
        if is_port_open(port):
            log_info(f"✅ {browser_name} is ready and connected! (port {port})")
            return proc
        time.sleep(0.8)
        if i % 3 == 2:
            log_step(f"Waiting for {browser_name} port {port}... ({int((i+1)*0.8)}s)")

    if not interactive:
        raise RuntimeError(
            f"{browser_name} did not open the automation port. "
            "Close the Automator browser window and connect again. Your other browser windows are left open."
        )
    print()
    log_error(f"{browser_name} is running, but port {port} is not responding.")
    log_info("Check whether the Automator profile is already open or the debug port is blocked.")
    log_info(f"We can retry the dedicated {browser_name} process launched by this program.")
    
    confirm = input(f"  {C_BOLD}[?]{C_RESET} Do you want to automatically restart {browser_name}? (y/n) [y]: ").strip().lower()
    
    if confirm not in ("n", "no"):
        if proc.poll() is None:
            log_info(f"Closing the launched {browser_name} process...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        
        log_info(f"Relaunching {browser_name} with debug port...")
        proc = subprocess.Popen(cmd, **process_options)
        for i in range(15):
            if is_port_open(port):
                log_info(f"{browser_name} successfully restarted! (port {port})")
                return proc
            time.sleep(1)
            
        log_error(f"Still failed to open port {port} after restart.")
        sys.exit(1)
    else:
        log_error("Cannot continue without debugging port. Exiting.")
        sys.exit(1)
