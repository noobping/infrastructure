#!/usr/bin/env python3
"""Generate repository Quadlets using the same pinned FCOS tooling on every host."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
IMAGE = (REPO / 'test/quadlet-image').read_text().strip()
GENERATOR = '/usr/lib/systemd/system-generators/podman-system-generator'
SUFFIXES = {'.container': '', '.volume': '-volume', '.network': '-network'}


def generate(source):
    with tempfile.TemporaryDirectory(prefix='infrastructure-quadlet-') as directory:
        stage = Path(directory)
        for path in source.iterdir():
            if path.suffix in SUFFIXES:
                shutil.copyfile(path, stage / path.name)
            elif path.is_dir() and any(path.name.endswith(s + '.d') for s in SUFFIXES):
                shutil.copytree(path, stage / path.name)
        return subprocess.run([
            'podman', 'run', '--rm', '--pull=missing', '--network=none',
            '--read-only', '--cap-drop=all', '--security-opt=no-new-privileges',
            '--pids-limit=128', '--memory=256m',
            '--volume', f'{stage}:/units:ro,Z',
            '--env', 'QUADLET_UNIT_DIRS=/units', '--entrypoint', GENERATOR,
            IMAGE, '--dryrun',
        ], capture_output=True, text=True, check=False)


class Quadlets(unittest.TestCase):
    def test_all_repository_units_generate(self):
        self.assertRegex(IMAGE, r'^quay\.io/fedora/fedora-coreos:[\d.]+@sha256:[a-f0-9]{64}$')
        units = sorted(path for tree in ('images', 'vms')
                       for path in (REPO / tree).rglob('*') if path.suffix in SUFFIXES)
        self.assertTrue(units, 'No repository Quadlets found')
        print(f'Checking {len(units)} Quadlets and their drop-ins with {IMAGE}', flush=True)
        for source in sorted({path.parent for path in units}):
            with self.subTest(directory=str(source.relative_to(REPO))):
                result = generate(source)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('unsupported key', result.stderr)
                for path in (p for p in units if p.parent == source):
                    service = path.stem + SUFFIXES[path.suffix] + '.service'
                    self.assertIn(f'---{service}---', result.stdout, result.stdout)

    def test_invalid_quadlet_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='infrastructure-invalid-quadlet-') as directory:
            source = Path(directory)
            (source / 'broken.container').write_text(
                '[Container]\nImage=localhost/fixture:latest\nUnsupportedSetting=true\n')
            result = generate(source)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported key 'UnsupportedSetting'", result.stderr)
            self.assertNotIn('---broken.service---', result.stdout)


if __name__ == '__main__':
    if shutil.which('podman') is None:
        raise SystemExit('Quadlet validation requires Podman. Run the full check pipeline on a container-capable host; Git hooks use check-source.')
    unittest.main()
