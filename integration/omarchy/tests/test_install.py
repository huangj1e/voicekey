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

if __name__ == '__main__': unittest.main()
