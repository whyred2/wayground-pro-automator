"""
Browser auto-detection and launching with Chrome DevTools Protocol (CDP) debugging port.
"""

import os
import sys
import subprocess
import time

from config import C_BOLD, C_DIM, C_YELLOW, C_RESET
from ui import log_info, log_error, log_step


def find_browser_exe() -> tuple[str, str]:
    """
    Auto-detect Edge or Chrome executable on Windows.
    Returns (path, name) or exits if not found.
    """
    candidates = [
        # Edge (most common on Windows)
        (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
        (os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
        (os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"), "Edge"),
        # Chrome
        (os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"), "Chrome"),
        (os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"), "Chrome"),
        (os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"), "Chrome"),
    ]

    for path, name in candidates:
        if os.path.isfile(path):
            return path, name

    log_error("Could not find Edge or Chrome!")
    print(f"  {C_DIM}Looked in:{C_RESET}")
    for path, name in candidates:
        print(f"    {C_DIM}{path}{C_RESET}")
    sys.exit(1)


def get_user_data_dir(browser_name: str) -> str:
    """Get the default user data directory for the browser."""
    if browser_name == "Edge":
        return os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\User Data")
    else:
        return os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data")


def is_port_open(port: int) -> bool:
    """Check if a CDP port is already open."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def launch_browser_with_debug(port: int) -> subprocess.Popen:
    """
    Find Edge/Chrome, launch with --remote-debugging-port.
    Uses the user's existing profile so all logins are preserved.
    """
    exe_path, browser_name = find_browser_exe()
    user_data = get_user_data_dir(browser_name)

    log_info(f"Found {browser_name}: {exe_path}")
    log_info(f"Profile: {user_data}")

    cmd = [
        exe_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    log_info(f"Launching {browser_name} with debug port {port}...")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
    )

    # Wait for browser to start and open the debug port
    for i in range(15):
        if is_port_open(port):
            log_info(f"{browser_name} is ready! (port {port})")
            return proc
        time.sleep(1)
        if i % 3 == 2:
            log_step(f"Waiting for {browser_name} to start... ({i+1}s)")

    print()
    log_error(f"{browser_name} is running, but port {port} is not responding.")
    log_info("This usually happens because the browser is ALREADY open in normal mode.")
    log_info(f"We can safely restart {browser_name} for you (all your tabs will be restored).")
    
    confirm = input(f"  {C_BOLD}[?]{C_RESET} Do you want to automatically restart {browser_name}? (y/n) [y]: ").strip().lower()
    
    if confirm not in ("n", "no"):
        log_info(f"Closing existing {browser_name} processes...")
        exe_name = os.path.basename(exe_path)
        subprocess.run(["taskkill", "/F", "/IM", exe_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)  # Give processes a moment to fully terminate
        
        log_info(f"Relaunching {browser_name} with debug port...")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
        )
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
