"""Platform branches can be checked on any host without launching or building binaries."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import app_paths
import browser
import build_desktop
import config


def system(name, **values):
    return SimpleNamespace(platform=name, executable=sys.executable, base_prefix=sys.base_prefix,
                           exit=sys.exit, **values)


class LocationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        home_patch = patch("app_paths.Path.home", return_value=self.home)
        home_patch.start()
        self.addCleanup(home_patch.stop)

    def test_windows_keeps_existing_profile_and_preferences_locations(self):
        local = self.home / "local-app-data"
        with patch.object(app_paths, "sys", system("win32")), patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            self.assertEqual(app_paths.app_data_dir(), local / "WaygroundAutomator")
            self.assertEqual(app_paths.app_config_dir(), local / "WaygroundAutomator")
            self.assertEqual(app_paths.playwright_cache_dir(), local / "ms-playwright")

    def test_macos_uses_application_support_and_library_cache(self):
        with patch.object(app_paths, "sys", system("darwin")):
            self.assertEqual(app_paths.app_data_dir(), self.home / "Library/Application Support/WaygroundAutomator")
            self.assertEqual(app_paths.app_config_dir(), app_paths.app_data_dir())
            self.assertEqual(app_paths.playwright_cache_dir(), self.home / "Library/Caches/ms-playwright")

    def test_linux_respects_all_three_xdg_locations(self):
        env = {name: str(self.home / name) for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")}
        with patch.object(app_paths, "sys", system("linux")), patch.dict(os.environ, env):
            self.assertEqual(app_paths.app_config_dir(), Path(env["XDG_CONFIG_HOME"]) / "wayground-automator")
            self.assertEqual(app_paths.app_data_dir(), Path(env["XDG_DATA_HOME"]) / "wayground-automator")
            self.assertEqual(app_paths.playwright_cache_dir(), Path(env["XDG_CACHE_HOME"]) / "ms-playwright")

    def test_linux_ignores_relative_xdg_values(self):
        env = {name: "relative-directory" for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME")}
        with patch.object(app_paths, "sys", system("linux")), patch.dict(os.environ, env):
            self.assertEqual(app_paths.app_config_dir(), self.home / ".config/wayground-automator")
            self.assertEqual(app_paths.app_data_dir(), self.home / ".local/share/wayground-automator")
            self.assertEqual(app_paths.playwright_cache_dir(), self.home / ".cache/ms-playwright")

    def test_browser_profile_is_created_only_in_application_data(self):
        with patch("browser.app_data_dir", return_value=self.home / "app-data"):
            profile = Path(browser.get_user_data_dir("Chromium"))
        self.assertEqual(profile, self.home / "app-data/BrowserProfile")
        self.assertTrue(profile.is_dir())

    def test_env_directory_is_outside_macos_app_bundle(self):
        app = self.home / "WaygroundAutomator.app/Contents/MacOS/WaygroundAutomator"
        self.assertEqual(app_paths.executable_directory(app), self.home)
        executable = self.home / "binary/WaygroundAutomator"
        self.assertEqual(app_paths.executable_directory(executable), self.home / "binary")

    def test_frozen_env_loader_reads_from_the_application_directory(self):
        (self.home / ".env").write_text("WAYGROUND_PLATFORM_TEST=loaded\n", encoding="utf-8")
        with patch.object(config, "sys", SimpleNamespace(frozen=True)), \
                patch("config.executable_directory", return_value=self.home), patch.dict(os.environ, {}, clear=True):
            config._load_dotenv()
            self.assertEqual(os.environ["WAYGROUND_PLATFORM_TEST"], "loaded")


class BrowserPlatformTests(unittest.TestCase):
    def setUp(self):
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        environment = patch.dict(os.environ, {"WAYGROUND_BROWSER": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def test_linux_discovers_chromium_on_path(self):
        with patch.object(browser, "sys", system("linux")), \
                patch("browser.shutil.which", side_effect=lambda name: "/usr/bin/chromium" if name == "chromium" else None), \
                patch("browser.os.path.isfile", return_value=True), patch("browser.os.access", return_value=True):
            self.assertEqual(browser.find_browser_exe(), ("/usr/bin/chromium", "Chromium"))

    def test_macos_discovers_system_and_user_application_bundles(self):
        for directory in (Path("/Applications"), Path.home() / "Applications"):
            path = directory / "Google Chrome.app/Contents/MacOS/Google Chrome"
            with self.subTest(directory=directory), patch.object(browser, "sys", system("darwin")), \
                    patch("browser.shutil.which", return_value=None), \
                    patch("browser.os.path.isfile", side_effect=lambda value: Path(value) == path), \
                    patch("browser.os.access", return_value=True):
                self.assertEqual(browser.find_browser_exe(), (str(path), "Chrome"))

    def test_windows_still_prefers_edge(self):
        with patch.object(browser, "sys", system("win32")), patch("browser.shutil.which", return_value=None), \
                patch("browser.os.path.isfile", return_value=True), patch("browser.os.access", return_value=True):
            self.assertEqual(browser.find_browser_exe()[1], "Edge")

    def test_explicit_browser_is_used_without_shell_or_argument_splitting(self):
        command = str(Path.home() / "Browser With Spaces/chrome")
        with patch.dict(os.environ, {"WAYGROUND_BROWSER": command}), \
                patch("browser.shutil.which", return_value=command) as which:
            self.assertEqual(browser.find_browser_exe(), (command, "Custom browser"))
        which.assert_called_once_with(command)

    def test_invalid_override_does_not_silently_switch_browser(self):
        with patch.dict(os.environ, {"WAYGROUND_BROWSER": "missing-browser"}), \
                patch("browser.shutil.which", return_value=None), self.assertRaises(SystemExit):
            browser.find_browser_exe()

    def test_posix_launch_detaches_its_own_browser_session(self):
        for target in ("linux", "darwin"):
            with self.subTest(target=target), patch.object(browser, "sys", system(target)), \
                    patch("browser.find_browser_exe", return_value=("/browser with spaces/chrome", "Chrome")), \
                    patch("browser.get_user_data_dir", return_value="/data/BrowserProfile"), \
                    patch("browser.is_port_open", return_value=True), patch("browser.subprocess.Popen") as spawn:
                browser.launch_browser_with_debug(9222, interactive=False)
                self.assertTrue(spawn.call_args.kwargs["start_new_session"])
                self.assertNotIn("creationflags", spawn.call_args.kwargs)
                self.assertEqual(spawn.call_args.args[0][0], "/browser with spaces/chrome")
                self.assertIn("--user-data-dir=/data/BrowserProfile", spawn.call_args.args[0])

    def test_noninteractive_timeout_never_terminates_existing_browsers(self):
        with patch.object(browser, "sys", system("linux")), \
                patch("browser.find_browser_exe", return_value=("/browser", "Chrome")), \
                patch("browser.get_user_data_dir", return_value="/profile"), \
                patch("browser.is_port_open", return_value=False), patch("browser.time.sleep"), \
                patch("browser.subprocess.Popen") as spawn, self.assertRaises(RuntimeError):
            browser.launch_browser_with_debug(9222, interactive=False)
        spawn.assert_called_once()
        spawn.return_value.terminate.assert_not_called()

    def test_windows_launch_keeps_native_detached_process_flags(self):
        with patch.object(browser, "sys", system("win32")), \
                patch("browser.find_browser_exe", return_value=("browser.exe", "Edge")), \
                patch("browser.get_user_data_dir", return_value="profile"), \
                patch("browser.is_port_open", return_value=True), patch("browser.subprocess.Popen") as spawn, \
                patch.object(browser.subprocess, "DETACHED_PROCESS", 8, create=True), \
                patch.object(browser.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True):
            browser.launch_browser_with_debug(9222, interactive=False)
        self.assertEqual(spawn.call_args.kwargs["creationflags"], 520)
        self.assertNotIn("start_new_session", spawn.call_args.kwargs)

    def test_interactive_retry_terminates_only_the_process_it_launched(self):
        old, new = Mock(), Mock()
        old.poll.return_value = None
        with patch.object(browser, "sys", system("linux")), \
                patch("browser.find_browser_exe", return_value=("/browser", "Chrome")), \
                patch("browser.get_user_data_dir", return_value="/profile"), \
                patch("browser.is_port_open", side_effect=[False] * 12 + [True]), patch("browser.time.sleep"), \
                patch("builtins.input", return_value="y"), patch("browser.subprocess.run") as command, \
                patch("browser.subprocess.Popen", side_effect=[old, new]):
            self.assertIs(browser.launch_browser_with_debug(9222), new)
        old.terminate.assert_called_once()
        new.terminate.assert_not_called()
        command.assert_not_called()


class NativeBuildTests(unittest.TestCase):
    def test_commands_use_native_resources_and_do_not_cross_platform_flags(self):
        windows = build_desktop.build_command(ROOT, target="win32")
        linux = build_desktop.build_command(ROOT, target="linux")
        mac = build_desktop.build_command(ROOT, target="darwin")
        self.assertIn("--version-file", windows)
        self.assertIn(f"{ROOT / 'assets'};assets", windows)
        self.assertIn("--onefile", linux)
        self.assertIn(f"{ROOT / 'assets'}:assets", linux)
        self.assertNotIn("--version-file", linux)
        self.assertNotIn("--windowed", linux)
        self.assertEqual(mac[-1], str(ROOT / "packaging/WaygroundAutomator-macos.spec"))
        self.assertTrue(Path(mac[-1]).is_file())
        self.assertNotIn("--onefile", mac)
        self.assertNotIn("--version-file", mac)

    def test_dry_run_does_not_invoke_pyinstaller(self):
        output = io.StringIO()
        with patch.object(build_desktop, "sys", system("linux")), \
                patch("build_desktop.subprocess.run") as run, contextlib.redirect_stdout(output):
            build_desktop.main(["--dry-run"])
        run.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["version"], "4.1")

    def test_ssl_resource_is_included_only_when_the_runtime_needs_it(self):
        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / "codex-rejected-cas.pem"
            with patch.object(build_desktop, "ssl", SimpleNamespace(__file__=str(Path(directory) / "ssl.py"))):
                self.assertFalse(any("codex-rejected-cas.pem" in value for value in build_desktop.build_command(ROOT, target="linux")))
                resource.write_text("fixture", encoding="utf-8")
                self.assertIn(f"{resource}:.", build_desktop.build_command(ROOT, target="linux"))
                self.assertIn(f"{resource};.", build_desktop.build_command(ROOT, target="win32"))

    def test_custom_output_and_console_mac_do_not_create_app_bundle(self):
        command = build_desktop.build_command(ROOT, target="darwin", console=True, distpath="custom-output")
        self.assertEqual(command[command.index("--distpath") + 1], "custom-output")
        self.assertIn("--onefile", command)
        self.assertNotIn("--windowed", command)


if __name__ == "__main__":
    unittest.main()
