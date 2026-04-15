"""
UI helpers: logging, banners, spinners, and console output formatting.
"""

import os
import asyncio

from config import C_RESET, C_GREEN, C_RED, C_YELLOW, C_CYAN, C_BOLD, C_DIM

VERSION = "2.1"


def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_banner(subtitle: str = ""):
    """Print the app banner, optionally with a subtitle/status line."""
    print(f"""
{C_CYAN}╔══════════════════════════════════════════════╗
║        Wayground Pro Automator   v{VERSION}        ║
╚══════════════════════════════════════════════╝{C_RESET}""")
    if subtitle:
        print(f"  {C_DIM}{subtitle}{C_RESET}")
        print()


class Spinner:
    """Simple async spinner for waiting states."""
    _FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    
    def __init__(self, message: str):
        self.message = message
        self._task = None
        self._stop = False
    
    async def _spin(self):
        i = 0
        while not self._stop:
            frame = self._FRAMES[i % len(self._FRAMES)]
            print(f"\r  {C_CYAN}{frame}{C_RESET} {self.message}", end="", flush=True)
            i += 1
            await asyncio.sleep(0.1)
        print(f"\r  {C_GREEN}✓{C_RESET} {self.message}" + " " * 10)
    
    async def __aenter__(self):
        self._stop = False
        self._task = asyncio.create_task(self._spin())
        return self
    
    async def __aexit__(self, *_):
        self._stop = True
        if self._task:
            await self._task


def log_info(msg: str):
    print(f"{C_CYAN}[INFO]{C_RESET} {msg}")


def log_found(msg: str):
    print(f"{C_GREEN}{C_BOLD}[FOUND]{C_RESET} {C_GREEN}{msg}{C_RESET}")


def log_progress(current: int, total: int, msg: str = ""):
    bar_len = 30
    filled = int(bar_len * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = int(100 * current / total) if total > 0 else 0
    extra = f" — {msg}" if msg else ""
    print(f"{C_YELLOW}[PROGRESS]{C_RESET} [{bar}] {current}/{total} ({pct}%){extra}")


def log_error(msg: str):
    print(f"{C_RED}{C_BOLD}[ERROR]{C_RESET} {C_RED}{msg}{C_RESET}")


def log_step(msg: str):
    print(f"{C_DIM}  → {msg}{C_RESET}")


def log_wrong(msg: str):
    print(f"{C_RED}[WRONG]{C_RESET} {C_YELLOW}{msg}{C_RESET}")


def print_phase_header(phase_num: int, title: str):
    """Print a clean phase separator."""
    print()
    print(f"{C_CYAN}{'━'*60}{C_RESET}")
    print(f"  {C_BOLD}{C_CYAN}PHASE {phase_num}{C_RESET}  {title}")
    print(f"{C_CYAN}{'━'*60}{C_RESET}")
    print()
