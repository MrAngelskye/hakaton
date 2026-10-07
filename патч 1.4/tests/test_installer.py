"""Installer and launcher regression checks; no package installs or network."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import environment, install, run, setup_voice


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='nai-test-')
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / 'проект с пробелами'
        self.project.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def interpreter(self, folder):
        python = environment.environment_python(folder)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_bytes(b'test interpreter placeholder')
        return python

    def test_short_project_keeps_local_environment(self):
        project = Path(self.root.anchor) / 'NaryadAI'
        self.assertEqual(environment.choose_environment(project, windows=True), project / '.venv')

    def test_deep_unicode_project_gets_short_stable_environment(self):
        project = self.project / ('вложенная папка ' * 5) / ('следующий уровень ' * 4)
        self.assertGreaterEqual(environment.path_units(project / '.venv' / environment.PYSIDE_RESOURCE), 260)
        chosen = environment.choose_environment(project, windows=True, home=Path.home())
        self.assertNotEqual(chosen, project / '.venv')
        self.assertLess(environment.path_units(chosen / environment.PYSIDE_RESOURCE), 260)
        self.assertEqual(chosen, environment.choose_environment(project, windows=True, home=Path.home()))

    def test_two_projects_have_separate_short_environments(self):
        deep = self.project / ('длинная папка ' * 7)
        first = environment.choose_environment(deep / 'first', windows=True, home=Path.home())
        second = environment.choose_environment(deep / 'second', windows=True, home=Path.home())
        self.assertNotEqual(first, second)

    def test_too_long_profile_reports_actionable_failure(self):
        deep = self.project / ('длинная папка ' * 7)
        with self.assertRaisesRegex(RuntimeError, 'install.bat'):
            environment.choose_environment(deep, windows=True, home=deep / 'profile')

    def test_saved_environment_wins_over_partial_local_environment(self):
        self.interpreter(self.project / '.venv')
        selected = self.root / 'installed'
        expected = self.interpreter(selected)
        environment.save_environment(self.project, selected)
        self.assertEqual(environment.resolve_python(self.project), expected)

    def test_missing_saved_environment_does_not_use_partial_local(self):
        self.interpreter(self.project / '.venv')
        environment.save_environment(self.project, self.root / 'missing')
        with self.assertRaisesRegex(RuntimeError, 'install.bat'):
            environment.resolve_python(self.project)

    def test_project_move_requires_reinstall(self):
        selected = self.root / 'installed'
        self.interpreter(selected)
        environment.save_environment(self.project, selected)
        moved = self.root / 'перенесенный проект'
        moved.mkdir()
        shutil.copyfile(self.project / environment.MARKER, moved / environment.MARKER)
        self.interpreter(moved / '.venv')
        with self.assertRaisesRegex(RuntimeError, 'install.bat'):
            environment.resolve_python(moved)

    def test_corrupt_markers_require_reinstall(self):
        self.interpreter(self.project / '.venv')
        corrupt = [
            'invalid json', '[]', '{}',
            json.dumps({'schema': 1, 'project': environment.project_identity(self.project), 'environment': 'relative/path'}),
        ]
        for content in corrupt:
            with self.subTest(content=content):
                (self.project / environment.MARKER).write_text(content, encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'install.bat'):
                    environment.resolve_python(self.project)

    def test_web_priority_and_desktop_fallback(self):
        desktop = self.root / 'installed'
        expected_desktop = self.interpreter(desktop)
        expected_web = self.interpreter(self.project / '.webvenv')
        environment.save_environment(self.project, desktop)
        self.assertEqual(environment.resolve_python(self.project, web_first=True), expected_web)
        self.assertEqual(environment.resolve_python(self.project, web_fallback=True), expected_desktop)
        expected_web.unlink()
        self.assertEqual(environment.resolve_python(self.project, web_first=True), expected_desktop)

    def test_open_web_fallbacks_when_desktop_absent(self):
        web = self.interpreter(self.project / '.webvenv')
        self.assertEqual(environment.resolve_python(self.project, web_fallback=True), web)
        web.unlink()
        self.assertEqual(environment.resolve_python(self.project, web_fallback=True, system_fallback=True), Path(sys.executable))

    def test_voice_setup_uses_saved_project_interpreter(self):
        self.interpreter(self.project / '.venv')
        selected = self.root / 'installed'
        expected = self.interpreter(selected)
        environment.save_environment(self.project, selected)
        with patch.object(setup_voice, 'ROOT', self.project):
            self.assertEqual(setup_voice.environment_python(), expected)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='nai-install-')
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / 'проект с пробелами'
        self.project.mkdir()
        self.external = self.root / 'selected-runtime'
        self.files = {
            'demo_data/naryadai.db': b'unchanged database',
            'demo_data/photos/photo.jpg': b'unchanged photo',
            'server_config.json': b'{"port":8000}',
            '.venv/partial.txt': b'partial old environment',
        }
        for name, content in self.files.items():
            target = self.project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        environment.save_environment(self.project, self.root / 'previous-runtime')
        self.previous_marker = (self.project / environment.MARKER).read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return install.install(self.project, **kwargs)

    def assert_data_preserved(self):
        for name, content in self.files.items():
            self.assertEqual((self.project / name).read_bytes(), content)

    def test_check_mode_does_not_create_environment_or_publish_marker(self):
        before = {str(path.relative_to(self.project)): path.read_bytes() for path in self.project.rglob('*') if path.is_file()}
        with patch.object(install, 'choose_environment', return_value=self.external), patch.object(install.subprocess, 'run') as execute:
            self.assertEqual(self.invoke(check_only=True), 0)
        execute.assert_not_called()
        self.assertFalse(self.external.exists())
        after = {str(path.relative_to(self.project)): path.read_bytes() for path in self.project.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_each_install_failure_preserves_data_and_previous_marker(self):
        for stage in range(4):
            with self.subTest(stage=stage):
                results = [subprocess.CompletedProcess([], 0) for _ in range(stage)] + [subprocess.CompletedProcess([], 17)]
                with patch.object(install, 'choose_environment', return_value=self.external), patch.object(install.subprocess, 'run', side_effect=results) as execute:
                    self.assertEqual(self.invoke(), 17)
                self.assertEqual(execute.call_count, stage + 1)
                self.assert_data_preserved()
                self.assertEqual((self.project / environment.MARKER).read_bytes(), self.previous_marker)

    def test_os_failure_preserves_data_and_previous_marker(self):
        with patch.object(install, 'choose_environment', return_value=self.external), patch.object(install.subprocess, 'run', side_effect=OSError('test failure')):
            self.assertEqual(self.invoke(), 1)
        self.assert_data_preserved()
        self.assertEqual((self.project / environment.MARKER).read_bytes(), self.previous_marker)

    def test_success_publishes_only_after_pip_and_pyside_verification(self):
        executed = []

        def execute(command, *, cwd, check):
            self.assertEqual(cwd, self.project)
            self.assertFalse(check)
            self.assertEqual((self.project / environment.MARKER).read_bytes(), self.previous_marker)
            executed.append(command)
            return subprocess.CompletedProcess(command, 0)

        def publish(project, selected):
            self.assertEqual(len(executed), 4)
            self.assertEqual(executed[-2][1:], ['-m', 'pip', 'check'])
            self.assertEqual(executed[-1][1], '-c')
            self.assertIn('from PySide6.QtWidgets import QApplication', executed[-1][2])
            environment.save_environment(project, selected)

        with patch.object(install, 'choose_environment', return_value=self.external), patch.object(install.subprocess, 'run', side_effect=execute), patch.object(install, 'save_environment', side_effect=publish):
            self.assertEqual(self.invoke(), 0)
        python = str(environment.environment_python(self.external))
        self.assertEqual(executed[0], [sys.executable, '-m', 'venv', str(self.external)])
        self.assertEqual(executed[1], [python, '-m', 'pip', 'install', '-r', str(self.project / 'requirements.txt')])
        self.assertTrue(all(command[0] == python for command in executed[1:]))
        self.assertEqual(environment.selected_environment(self.project), self.external)
        self.assert_data_preserved()


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='nai-launch-')
        self.project = Path(self.temporary.name).resolve() / 'проект с пробелами'
        self.project.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_child_receives_project_working_directory_and_literal_arguments(self):
        script = self.project / 'capture.py'
        script.write_text(
            'import json, os, sys\n'
            'from pathlib import Path\n'
            'Path("capture.json").write_text(json.dumps({"cwd": os.getcwd(), "args": sys.argv[1:]}), encoding="utf-8")\n'
            'raise SystemExit(23)\n', encoding='utf-8')
        arguments = ['текст с пробелами', 'a&b', '%PATH%', 'quoted "value"', '', '--option=value']
        with patch.object(run, 'resolve_python', return_value=Path(sys.executable)):
            self.assertEqual(run.launch(self.project, 'capture.py', arguments), 23)
        observed = json.loads((self.project / 'capture.json').read_text(encoding='utf-8'))
        self.assertEqual(Path(observed['cwd']).resolve(), self.project)
        self.assertEqual(observed['args'], arguments)

    def test_launch_uses_selected_interpreter_and_forwards_options(self):
        target = self.project / 'main.py'
        target.write_text('pass\n', encoding='utf-8')
        selected = self.project.parent / 'short runtime' / 'python.exe'
        arguments = ['--data-dir', 'данные с пробелами']
        with patch.object(run, 'resolve_python', return_value=selected) as resolve, patch.object(run.subprocess, 'run', return_value=subprocess.CompletedProcess([], 12)) as execute:
            self.assertEqual(run.launch(self.project, 'main.py', arguments, web_first=True, web_fallback=True), 12)
        resolve.assert_called_once_with(self.project, web_first=True, web_fallback=True, system_fallback=False)
        execute.assert_called_once_with([str(selected), str(target), *arguments], cwd=self.project, check=False)

    def test_missing_or_outside_script_is_rejected_before_execution(self):
        outside = self.project.parent / 'outside.py'
        outside.write_text('pass\n', encoding='utf-8')
        for script in ('missing.py', '../outside.py'):
            with self.subTest(script=script), patch.object(run.subprocess, 'run') as execute:
                with self.assertRaises(RuntimeError):
                    run.launch(self.project, script)
                execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
