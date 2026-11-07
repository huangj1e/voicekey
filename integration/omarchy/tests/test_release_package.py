import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]

class ReleasePackageTests(unittest.TestCase):
    def test_archive_installs_without_source_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / 'voicekey-binary'
            binary.write_text('#!/bin/sh\nexit 0\n')
            binary.chmod(0o755)
            archive = root / 'release.tar.gz'
            subprocess.run([str(BASE / 'package-release.sh'), '1.9.1', str(binary), str(archive)], check=True, capture_output=True, text=True)
            extracted = root / 'extracted'
            extracted.mkdir()
            with tarfile.open(archive) as tar:
                tar.extractall(extracted, filter='data')
            package = extracted / 'VoiceKey-1.9.1-linux-x86_64'
            home = root / 'home'
            config = home / '.config'
            (config / 'hypr').mkdir(parents=True)
            (config / 'hypr/hyprland.lua').write_text('-- test configuration\n')
            fake = root / 'fake-bin'
            fake.mkdir()
            wtype = fake / 'wtype'
            wtype.write_text('#!/bin/sh\nexit 0\n')
            wtype.chmod(0o755)
            env = os.environ.copy()
            env.update(HOME=str(home), XDG_CONFIG_HOME=str(config), XDG_STATE_HOME=str(home / 'state'), PATH=str(fake) + ':/usr/bin:/bin')
            env.pop('XDG_RUNTIME_DIR', None)
            subprocess.run([str(package / 'install.sh'), '--no-activate'], env=env, check=True, capture_output=True, text=True)
            self.assertEqual((home / '.local/share/voicekey/voicekey').read_bytes(), binary.read_bytes())
            self.assertTrue((home / '.local/bin/voicekey-uninstall').is_symlink())
            self.assertTrue((home / '.local/share/voicekey/resources/sounds/pop.wav').exists())

    def test_invalid_version_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([str(BASE / 'package-release.sh'), '../bad', '/bin/true', str(Path(temp) / 'x.tar.gz')], capture_output=True)
            self.assertNotEqual(result.returncode, 0)

if __name__ == '__main__': unittest.main()
