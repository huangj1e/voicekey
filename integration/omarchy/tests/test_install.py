import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('voicekey_menu', BASE / 'configure-menu.py')
menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menu)


class MenuTests(unittest.TestCase):
    def test_comments_urls_and_existing_entries_survive(self):
        source = '{\n // Keep this comment\n "personal.link": {"action": "open https://example.com/a"} // trailing comment\n}\n'
        output = menu.update(source)
        self.assertIn('// Keep this comment', output)
        self.assertIn('// trailing comment', output)
        self.assertIn('https://example.com/a', output)
        self.assertIn(menu.KEY, output)
        self.assertEqual(menu.update(output), output)

    def test_wrapped_items_and_trailing_commas(self):
        source = '{"version":1,"items":{"one":{"label":"A"},},"after":true}'
        result = menu.update(source)
        self.assertIn(menu.KEY, result)
        self.assertEqual(menu.update(result), result)
        cleaned = ''.join(t[0] for i, t in enumerate(menu.tokens(result)) if not (t[0] == ',' and i + 1 < len(menu.tokens(result)) and menu.tokens(result)[i+1][0] in '}]'))
        self.assertIn(menu.KEY, json.loads(cleaned)['items'])

    def test_rejects_invalid_without_modifying_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'menu.jsonc'
            path.write_text('{invalid')
            with self.assertRaises(ValueError): menu.main(path)
            self.assertEqual(path.read_text(), '{invalid')

    def test_remove_entry_in_any_position_preserves_other_comments(self):
        entry = json.dumps(menu.KEY) + ': ' + json.dumps(menu.ENTRY)
        for source in [
            '{' + entry + ', "other": {"label":"keep"}}',
            '{"other": {"label":"keep"}, // keep comment\n' + entry + '}',
            '{"items": {' + entry + ', "other":{"label":"keep"},}, "v":1}',
        ]:
            with self.subTest(source=source):
                result = menu.remove(source)
                self.assertNotIn(menu.KEY, result)
                self.assertIn('keep', result)
                if '// keep comment' in source: self.assertIn('// keep comment', result)
                self.assertEqual(menu.remove(result), result)

    def test_remove_keeps_user_modified_entry(self):
        source = json.dumps({menu.KEY: {'action': 'my-custom-action'}})
        self.assertEqual(menu.remove(source), source)

    def test_existing_entry_is_not_overwritten(self):
        source = json.dumps({menu.KEY: {'action': 'my-custom-action'}})
        self.assertEqual(menu.update(source), source)


class InstallTests(unittest.TestCase):
    def test_no_activate_installs_without_switching_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            config = home / '.config'
            (config / 'hypr').mkdir(parents=True)
            (config / 'hypr/hyprland.lua').write_text('-- my settings\n')
            fake_bin = home / 'bin'
            fake_bin.mkdir()
            wtype = fake_bin / 'wtype'
            wtype.write_text('#!/bin/sh\nexit 0\n')
            wtype.chmod(0o755)
            binary = home / 'input-binary'
            binary.write_text('#!/bin/sh\nexit 0\n')
            binary.chmod(0o755)
            env = os.environ.copy()
            env.update(HOME=str(home), XDG_CONFIG_HOME=str(config), PATH=str(fake_bin) + ':/usr/bin:/bin')
            env.pop('XDG_RUNTIME_DIR', None)
            subprocess.run([str(BASE / 'install.sh'), '--binary', str(binary), '--no-activate'], env=env, check=True, capture_output=True, text=True)
            self.assertTrue((home / '.local/share/voicekey/voicekey').exists())
            self.assertTrue((config / 'systemd/user/voicekey.service').exists())
            self.assertFalse((config / 'omarchy/defaults/dictation').exists())

    def test_install_is_repeatable_and_preserves_symlink_and_custom_files(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            config = home / '.config'
            (config / 'hypr').mkdir(parents=True)
            hypr = config / 'hypr/hyprland.lua'
            hypr.write_text('-- my configuration\n')
            (config / 'voicekey').mkdir()
            shortcut = config / 'voicekey/shortcuts.lua'
            shortcut.write_text('-- my custom binding\n')
            (config / 'omarchy/extensions').mkdir(parents=True)
            real_menu = home / 'managed-menu.jsonc'
            real_menu.write_text('{\n // personal menu\n "personal": {"label": "Personal"}\n}\n')
            link = config / 'omarchy/extensions/omarchy-menu.jsonc'
            link.symlink_to(real_menu)
            fake_bin = home / 'fake-bin'
            fake_bin.mkdir()
            log = home / 'calls'
            for name in ['wtype', 'systemctl', 'omarchy-dictation-use', 'omarchy-restart-hyprctl', 'omarchy-menu', 'hyprctl']:
                p = fake_bin / name
                p.write_text('#!/bin/sh\nprintf "%s\\n" "$(basename "$0") $*" >> "$VOICEKEY_TEST_LOG"\nexit 0\n')
                p.chmod(0o755)
            binary = home / 'input-binary'
            binary.write_text('#!/bin/sh\nexit 0\n')
            binary.chmod(0o755)
            env = os.environ.copy()
            env.update(HOME=str(home), XDG_CONFIG_HOME=str(config), XDG_RUNTIME_DIR=str(home), HYPRLAND_INSTANCE_SIGNATURE='test', VOICEKEY_TEST_LOG=str(log), PATH=str(fake_bin) + ':/usr/bin:/bin')
            cmd = [str(BASE / 'install.sh'), '--binary', str(binary)]
            for _ in range(2): subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
            self.assertTrue(link.is_symlink())
            self.assertIn('// personal menu', real_menu.read_text())
            self.assertEqual(real_menu.read_text().count('"'+menu.KEY+'"'), 1)
            self.assertEqual(hypr.read_text().count('require("hypr.voicekey")'), 1)
            self.assertIn('-- my custom binding', shortcut.read_text())
            self.assertEqual(shortcut.read_text().count('hl.unbind("ALT + SPACE")'), 1)
            self.assertTrue((home / '.local/share/voicekey/voicekey').is_file())
            self.assertTrue((config / 'systemd/user/voicekey.service').is_file())
            calls = log.read_text()
            self.assertIn('omarchy-dictation-use voicekey', calls)
            self.assertIn('systemctl --user enable --now voicekey.service', calls)
            self.assertIn('hyprctl configerrors', calls)

class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / '.config'
        (self.config / 'hypr').mkdir(parents=True)
        (self.config / 'hypr/hyprland.lua').write_text('-- user configuration\n')
        (self.config / 'omarchy/extensions').mkdir(parents=True)
        self.menu = self.home / 'managed-menu.jsonc'
        self.menu.write_text('{\n // custom comment\n "personal": {"label":"Personal"}\n}\n')
        (self.config / 'omarchy/extensions/omarchy-menu.jsonc').symlink_to(self.menu)
        defaults = self.config / 'omarchy/defaults'
        defaults.mkdir(parents=True)
        (defaults / 'dictation').write_text('voxtype\n')
        self.fake = self.home / 'fake-bin'
        self.fake.mkdir()
        self.log = self.home / 'calls'
        for name in ['wtype', 'systemctl', 'omarchy-restart-hyprctl', 'omarchy-menu', 'hyprctl', 'voxtype', 'omarchy-dictation-voxtype']:
            self.command(name, 'exit 0')
        self.command('omarchy-dictation-use', 'mkdir -p "$XDG_CONFIG_HOME/omarchy/defaults"; printf "%s\\n" "$1" > "$XDG_CONFIG_HOME/omarchy/defaults/dictation"')
        self.binary = self.home / 'voicekey-source'
        self.binary.write_text('#!/bin/sh\nexit 0\n')
        self.binary.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.config), XDG_STATE_HOME=str(self.home / 'state'), XDG_DATA_HOME=str(self.home / 'data'), XDG_RUNTIME_DIR=str(self.home), HYPRLAND_INSTANCE_SIGNATURE='test', VOICEKEY_TEST_LOG=str(self.log), PATH=str(self.fake) + ':/usr/bin:/bin')
        subprocess.run([str(BASE / 'install.sh'), '--binary', str(self.binary)], env=self.env, check=True, capture_output=True, text=True)

    def command(self, name, body):
        p = self.fake / name
        p.write_text('#!/bin/sh\nprintf "%s\\n" "$(basename "$0") $*" >> "$VOICEKEY_TEST_LOG"\n' + body + '\n')
        p.chmod(0o755)

    def uninstall(self, *args):
        return subprocess.run([str(BASE / 'uninstall.sh'), *args], env=self.env, check=True, capture_output=True, text=True)

    def test_uninstall_restores_previous_and_preserves_user_files(self):
        data = self.home / 'data/VoiceKey'
        data.mkdir(parents=True)
        (data / 'settings.json').write_text('user settings')
        shortcut = self.config / 'voicekey/shortcuts.lua'
        shortcut.write_text(shortcut.read_text() + '-- my shortcut remains\n')
        self.uninstall()
        self.assertEqual((self.config / 'omarchy/defaults/dictation').read_text().strip(), 'voxtype')
        self.assertFalse((self.home / '.local/share/voicekey/voicekey').exists())
        self.assertFalse((self.config / 'systemd/user/voicekey.service').exists())
        self.assertTrue((data / 'settings.json').exists())
        self.assertEqual((self.config / 'hypr/hyprland.lua').read_text().strip(), '-- user configuration')
        self.assertIn('-- my shortcut remains', shortcut.read_text())
        self.assertNotIn('hl.unbind("ALT + SPACE")', shortcut.read_text())
        self.assertTrue((self.config / 'omarchy/extensions/omarchy-menu.jsonc').is_symlink())
        self.assertNotIn(menu.KEY, self.menu.read_text())
        self.assertIn('// custom comment', self.menu.read_text())
        self.uninstall()  # Repeated removal is safe.
        self.assertEqual((self.config / 'omarchy/defaults/dictation').read_text().strip(), 'voxtype')

    def test_installed_uninstaller_runs_without_source_tree(self):
        uninstall = self.home / '.local/bin/voicekey-uninstall'
        self.assertTrue(uninstall.is_symlink())
        subprocess.run([str(uninstall)], env=self.env, check=True, capture_output=True, text=True)
        self.assertFalse(uninstall.exists())
        self.assertFalse((self.home / '.local/share/voicekey/uninstall-assets').exists())
        self.assertEqual((self.config / 'omarchy/defaults/dictation').read_text().strip(), 'voxtype')

    def test_reinstall_keeps_original_backend_and_modified_binary(self):
        subprocess.run([str(BASE / 'install.sh'), '--binary', str(self.binary)], env=self.env, check=True, capture_output=True, text=True)
        binary = self.home / '.local/share/voicekey/voicekey'
        binary.write_text('user modified executable')
        result = self.uninstall()
        self.assertIn('Preserving modified executable', result.stderr)
        self.assertEqual(binary.read_text(), 'user modified executable')
        self.assertEqual((self.config / 'omarchy/defaults/dictation').read_text().strip(), 'voxtype')
        self.uninstall()
        self.assertTrue(binary.exists())

    def test_new_user_selection_is_not_overwritten(self):
        (self.config / 'omarchy/defaults/dictation').write_text('superwhisper\n')
        self.uninstall()
        self.assertEqual((self.config / 'omarchy/defaults/dictation').read_text().strip(), 'superwhisper')

    def test_missing_previous_backend_clears_default_and_purge_removes_data(self):
        (self.fake / 'voxtype').unlink()
        data = self.home / 'data/VoiceKey'
        data.mkdir(parents=True)
        (data / 'settings.json').write_text('settings')
        self.uninstall('--purge-data')
        self.assertFalse((self.config / 'omarchy/defaults/dictation').exists())
        self.assertFalse(data.exists())

    def test_preserves_rules_when_user_keeps_require(self):
        hypr = self.config / 'hypr/hyprland.lua'
        hypr.write_text(hypr.read_text() + "require('hypr.voicekey') -- user configuration\n")
        self.uninstall()
        self.assertIn("require('hypr.voicekey')", hypr.read_text())
        self.assertTrue((self.config / 'hypr/voicekey.lua').exists())

    def test_modified_service_stops_uninstall_without_changes(self):
        unit = self.config / 'systemd/user/voicekey.service'
        unit.write_text(unit.read_text() + '# user custom service\n')
        result = subprocess.run([str(BASE / 'uninstall.sh')], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.home / '.local/share/voicekey/voicekey').exists())
        self.assertEqual((self.config / 'omarchy/defaults/dictation').read_text().strip(), 'voicekey')

if __name__ == '__main__': unittest.main()
