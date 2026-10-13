import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.tools import app_discovery as discovery
from app.tools.desktop_actions import DesktopActionTool
from app.core.user_settings import UserWorkspaceSettings, UserSettingsStore
from app.core.engine import LunaEngine
from app.models.nvidia_model import NvidiaModel

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.apps = discovery.parse_applications([
            {'Name': 'Visual Studio Code', 'AppID': 'Microsoft.VisualStudioCode'},
            {'Name': 'Poznámkový blok', 'AppID': 'Microsoft.Notepad!App'},
            {'Name': 'Blender', 'AppID': 'steam://rungameid/365670'},
        ])

    def test_alias_and_diacritics(self):
        self.assertEqual(discovery.find_registered_app('VSCODE', self.apps)['title'], 'Visual Studio Code')
        self.assertEqual(discovery.find_registered_app('notepad', self.apps)['title'], 'Poznámkový blok')
        self.assertEqual(discovery.find_registered_app('poznamkovy blok', self.apps)['title'], 'Poznámkový blok')

    def test_missing_and_ambiguous_apps_are_not_guessed(self):
        self.assertIsNone(discovery.find_registered_app('missing.exe & calc', self.apps))
        apps = discovery.parse_applications([{'Name': 'Blender 4', 'AppID': 'b4'}, {'Name': 'Blender 5', 'AppID': 'b5'}])
        with self.assertRaises(ValueError): discovery.find_registered_app('blender', apps)

    def test_uninstall_and_document_links_are_excluded(self):
        apps = discovery.parse_applications([{'Name': 'Uninstall App', 'AppID': 'remove'}, {'Name': 'Manual', 'AppID': 'manual.pdf'}, {'Name': 'Site', 'AppID': 'https://example.com'}])
        self.assertEqual(apps, [])

    def test_launch_uses_only_target_found_in_windows(self):
        with patch.object(discovery, 'list_applications', return_value=self.apps), patch.object(discovery.os, 'startfile', create=True) as start:
            self.assertTrue(discovery.launch_registered_app('notepad')['ok'])
            start.assert_called_once_with('shell:AppsFolder\\Microsoft.Notepad!App')
            self.assertFalse(discovery.launch_registered_app('unknown')['ok'])
            self.assertEqual(start.call_count, 1)

    def test_chat_tool_falls_back_to_registration_without_configured_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = DesktopActionTool(Path(tmp))
            with patch.object(tool, '_load_apps_config', return_value={}), patch('app.tools.desktop_actions.shutil.which', return_value=None), patch('app.tools.desktop_actions.subprocess.run', return_value=SimpleNamespace(returncode=1)), patch('app.tools.desktop_actions.find_registered_app', return_value=self.apps[0]), patch('app.tools.desktop_actions.launch_registered_app', return_value={'ok': True, 'message': 'Opened'}) as launch:
                result = tool.launch_connected_app('blender', UserWorkspaceSettings())
                self.assertTrue(result['ok'])
                launch.assert_called_once_with('blender')

    def test_plain_chat_command_resolves_an_installed_app(self):
        engine = LunaEngine.__new__(LunaEngine)
        engine._guarded_action = lambda category, label, callback: callback()
        engine.open_connected_app = Mock(return_value={'ok': True, 'message': 'Opened Notepad'})
        item = discovery.find_registered_app('notepad', self.apps)
        with patch('app.core.engine.find_registered_app', return_value=item):
            self.assertEqual(engine._try_local_app_action('Otevři Poznámkový blok'), 'Opened Notepad')
        engine.open_connected_app.assert_called_once_with(item['key'], '', log_result=False)

class ResponseProfileTests(unittest.TestCase):
    def test_saved_profiles_change_actual_nvidia_request_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = UserSettingsStore(Path(tmp)/'settings.json')
            for value, expected in [(35, 2048), (50, 4096), (70, 8192)]:
                store.data.cpu_limit_percent = value
                store.data.gpu_limit_percent = value
                store.data.memory_limit_percent = value
                store.save()
                engine = LunaEngine.__new__(LunaEngine)
                engine.user_settings = UserSettingsStore(store.storage_path)
                engine.model = NvidiaModel('nvidia/nemotron-test', 'test-key')
                engine._apply_runtime_limits()
                client = Mock()
                client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='OK'))])
                with patch.object(engine.model, '_client', return_value=client), patch.object(engine.model, 'is_available', return_value=True):
                    self.assertEqual(engine.model.generate('test'), 'OK')
                self.assertEqual(client.chat.completions.create.call_args.kwargs['max_tokens'], expected)
                self.assertEqual(engine._runtime_budget_profile()['agent_chain_steps'], {35: 1, 50: 2, 70: 3}[value])

if __name__ == '__main__': unittest.main()
