from dataclasses import replace
import json
import os
import shlex
import subprocess
import sys

from steamlaunch.bindings import launch_options
from steamlaunch.storage import LaunchError, ProfileStore
from steamlaunch.wrapper import prepare_launch, replace_executable, safe_environment
from tests.helpers import Fixture


class WrapperTests(Fixture):
    def environment(self):
        return {"SteamAppId": "42", "SteamGameId": "42", "STEAM_COMPAT_DATA_PATH": "/prefix/42",
                "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(self.root),
                "LD_PRELOAD": "overlay.so", "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-1",
                "SECRET_TEST": "do-not-log"}

    def command(self):
        return ["/runtime/_v2-entry-point", "--verb=waitforexitandrun", "--",
                "/Proton 10.0/proton", "waitforexitandrun", "/original/launcher.exe", "--old"]

    def test_runtime_and_proton_prefix_are_preserved(self):
        result = replace_executable(self.command(), self.profile)
        self.assertEqual(result[:5], self.command()[:5])
        self.assertEqual(result[5:], [str(self.exe)] + self.profile.arguments)

    def test_optional_inherited_arguments(self):
        profile = replace(self.profile, inherit_arguments=True)
        result = replace_executable(self.command(), profile)
        self.assertEqual(result[5:], [str(self.exe), "--old"] + profile.arguments)

    def test_run_verb_and_python_invocation(self):
        command = [sys.executable, "/proton/proton", "run", "old.exe"]
        result = replace_executable(command, self.profile)
        self.assertEqual(result[:3], command[:3])
        self.assertEqual(result[3], str(self.exe))

    def test_unsupported_commands_fail_without_fallback(self):
        for command in [[], ["native.exe"], ["/proton", "destroyprefix", "old.exe"],
                        ["/path/proton", "run"], ["/path/proton", "run", ""]]:
            with self.subTest(command=command), self.assertRaises(LaunchError):
                replace_executable(command, self.profile)

    def test_environment_keeps_overlay_prefix_and_extra_mounts(self):
        environment = self.environment()
        environment["STEAM_COMPAT_MOUNTS"] = "/existing"
        plan = prepare_launch(self.profile, self.command(), environment, self.paths)
        for key in ["SteamAppId", "SteamGameId", "LD_PRELOAD", "STEAM_COMPAT_DATA_PATH", "SECRET_TEST"]:
            self.assertEqual(plan.env[key], environment[key])
        self.assertEqual(plan.cwd, self.exe.parent)
        self.assertEqual(plan.env["STEAM_COMPAT_MOUNTS"].split(":"), ["/existing", str(self.exe.parent)])
        self.assertEqual(environment["STEAM_COMPAT_MOUNTS"], "/existing")
        self.assertNotIn("SECRET_TEST", safe_environment(plan.env))

    def test_mismatched_missing_appid_and_missing_prefix(self):
        for changes in [{"SteamAppId": "99"}, {"SteamGameId": "99"},
                        {"SteamAppId": "", "SteamGameId": ""}, {"STEAM_COMPAT_DATA_PATH": ""},
                        {"STEAM_COMPAT_CLIENT_INSTALL_PATH": "/different/steam"}]:
            env = self.environment() | changes
            with self.subTest(changes=changes), self.assertRaises(LaunchError):
                prepare_launch(self.profile, self.command(), env, self.paths)

    def test_workdir_and_proton_log_do_not_mutate_prefix(self):
        profile = replace(self.profile, workdir=str(self.base), proton_log=True)
        plan = prepare_launch(profile, self.command(), self.environment(), self.paths)
        self.assertEqual(plan.cwd, self.base)
        self.assertEqual(plan.env["PROTON_LOG"], "1")
        self.assertEqual(plan.env["STEAM_COMPAT_DATA_PATH"], "/prefix/42")
        self.assertIn(str(self.base), plan.env["STEAM_COMPAT_MOUNTS"].split(":"))
        self.assertFalse(self.paths.state.exists(), "Planning a launch must not create directories")

    def test_colon_in_directory_is_rejected(self):
        directory = self.base / "bad:mount"
        directory.mkdir()
        with self.assertRaises(LaunchError):
            prepare_launch(replace(self.profile, workdir=str(directory)), self.command(),
                           self.environment(), self.paths)

    def test_executable_symlink_target_directory_is_mounted(self):
        link_dir = self.base / "links"
        link_dir.mkdir()
        link = link_dir / "game.exe"
        link.symlink_to(self.exe)
        plan = prepare_launch(replace(self.profile, executable=str(link)), self.command(),
                              self.environment(), self.paths)
        self.assertIn(str(self.exe.parent), plan.env["STEAM_COMPAT_MOUNTS"].split(":"))
        self.assertIn(str(link_dir), plan.env["STEAM_COMPAT_MOUNTS"].split(":"))

    def test_integration_exec_preserves_pid_cwd_arguments_and_exit_code(self):
        ProfileStore(self.paths).save(self.profile)
        runtime = self.base / "fake proton/proton"
        runtime.parent.mkdir()
        capture = self.base / "capture.json"
        runtime.write_text(
            'import json, os, sys\nfrom pathlib import Path\n'
            'Path(os.environ["CAPTURE"]).write_text(json.dumps({"pid": os.getpid(), '
            '"argv": sys.argv, "cwd": os.getcwd(), "appid": os.environ["SteamAppId"]}))\n'
            'print("fake-proton-output", flush=True)\nsys.exit(23)\n')
        command = [sys.executable, str(runtime), "waitforexitandrun", "original.exe", "--old"]
        options = shlex.split(launch_options(self.profile, self.paths))
        self.assertEqual(options[-1], "%command%")
        env = dict(os.environ) | self.environment() | {"CAPTURE": str(capture)}
        env.pop("LD_PRELOAD", None)  # No real overlay or game is used in the test.
        process = subprocess.Popen(options[:-1] + command, cwd=self.base, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 23, (stdout, stderr))
        result = json.loads(capture.read_text())
        self.assertEqual(result["pid"], process.pid)
        self.assertEqual(result["cwd"], str(self.exe.parent))
        self.assertEqual(result["argv"][2:], [str(self.exe)] + self.profile.arguments)
        self.assertEqual(result["appid"], "42")
        log = self.paths.log_file(self.profile.id).read_text()
        self.assertIn("fake-proton-output", log)
        self.assertNotIn("do-not-log", log)

    def test_cli_dry_run_works_outside_project_and_without_gui(self):
        ProfileStore(self.paths).save(self.profile)
        options = shlex.split(launch_options(self.profile, self.paths))
        separator = options.index("--")
        options.insert(separator, "--dry-run")
        env = dict(os.environ) | self.environment()
        env.pop("LD_PRELOAD", None)
        result = subprocess.run(options[:-1] + self.command(), cwd=self.base, env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["argv"][5], str(self.exe))
        self.assertFalse(self.paths.state.exists())

    def test_wrong_appid_exits_with_log_without_starting_proton(self):
        ProfileStore(self.paths).save(self.profile)
        options = shlex.split(launch_options(self.profile, self.paths))
        env = dict(os.environ) | self.environment() | {"SteamAppId": "99", "PATH": ""}
        env.pop("LD_PRELOAD", None)
        result = subprocess.run(options[:-1] + ["/never/execute/proton", "run", "old.exe"],
                                cwd=self.base, env=env, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertIn("AppID", self.paths.log_file(self.profile.id).read_text())
        self.assertEqual(self.paths.state.stat().st_mode & 0o777, 0o700)

    def test_headless_modules_do_not_import_qt(self):
        result = subprocess.run([sys.executable, "-I", "-c",
                                 "import sys, steamlaunch.__main__, steamlaunch.wrapper; "
                                 "assert not any(m.startswith('PySide6') for m in sys.modules)"],
                                cwd=self.base, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
