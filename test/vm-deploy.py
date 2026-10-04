#!/usr/bin/env python3
"""Run the provisioner against disposable files and simulated hypervisor tools."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
STUB = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
from xml.etree import ElementTree
root = Path(os.environ['DEPLOY_FIXTURE'])
name, args = Path(sys.argv[0]).name, sys.argv[1:]
with (root / 'calls').open('a') as log:
    log.write(name + ' ' + ' '.join(args) + '\n')
if name == 'uname':
    print('x86_64')
elif name == 'podman':
    if any('mikefarah/yq' in arg for arg in args):
        print('fixture ignition')
    else:
        sys.stdout.write(sys.stdin.read())
elif name == 'ignition-validate':
    if os.environ.get('INVALID_IGNITION') == 'true': sys.exit(1)
elif name == 'qemu-img':
    Path(args[-2]).write_text('new qcow2 fixture')
elif name == 'virsh':
    domains = root / 'domains'
    domains.mkdir(exist_ok=True)
    if args[0] == 'dominfo':
        sys.exit(0 if (domains / args[1]).exists() else 1)
    if args[0] == 'define':
        xml = ElementTree.parse(args[1])
        (domains / xml.findtext('name')).touch()
    if args[0] == 'undefine':
        (domains / args[1]).unlink(missing_ok=True)
elif name == 'coreos-installer':
    raise RuntimeError('The fixture base image should already exist')
'''


class Deploy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vm-deploy-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo with spaces'
        (self.repo / 'vms/libvirt').mkdir(parents=True)
        shutil.copy(REPO / 'vms/libvirt/domain.xml.in', self.repo / 'vms/libvirt')
        self.pool = self.root / 'pool'
        (self.pool / 'base').mkdir(parents=True)
        (self.pool / 'base/fedora-coreos-fixture-qemu.x86_64.qcow2').write_text('base')
        data = json.loads((REPO / 'vms/inventory.json').read_text())
        data['storage_pool']['path'] = str(self.pool)
        self.inventory = self.repo / 'vms/inventory.json'
        self.inventory.write_text(json.dumps(data))
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for tool in ['uname', 'podman', 'ignition-validate', 'qemu-img', 'virsh',
                     'coreos-installer', 'btrfs', 'ip', 'chown', 'restorecon',
                     'virt-xml-validate']:
            path = self.bin / tool
            path.write_text(STUB)
            path.chmod(0o755)
        # Only the superuser gate/ownership differ; all provisioning logic runs.
        script = (REPO / 'images/nas/bin/vm-deploy').read_text()
        script = script.replace('if (( EUID != 0 )); then', 'if false; then')
        script = script.replace('-o root -g qemu', f'-o {os.getuid()} -g {os.getgid()}')
        self.command = self.bin / 'vm-deploy'
        self.command.write_text(script)
        self.command.chmod(0o755)
        self.env = {**os.environ, 'DEPLOY_FIXTURE': str(self.root),
                    'PATH': f'{self.bin}:{os.environ["PATH"]}'}

    def deploy(self, *args, success=True, **extra):
        result = subprocess.run([str(self.command), *args], cwd=self.repo,
                                env={**self.env, **extra}, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_immich_create_only_and_no_implicit_start(self):
        self.deploy('immich')
        disk = self.pool / 'disks/immich-root.qcow2'
        original = disk.read_bytes()
        self.assertTrue((self.repo / 'dist/ign/immich.ign').exists())
        xml = (self.pool / 'config/immich.xml').read_text()
        self.assertIn('<vcpu placement=\'static\'>8</vcpu>', xml)
        self.assertIn('16384', xml)
        self.assertEqual(xml.count("device='disk'"), 1)
        calls = (self.root / 'calls').read_text()
        self.assertIn('virsh autostart immich', calls)
        self.assertNotIn('virsh start immich', calls)
        result = self.deploy('immich', success=False)
        self.assertIn('refusing to replace', result.stderr)
        self.assertEqual(original, disk.read_bytes())

    def test_all_uses_selected_inventory_and_ignition_paths(self):
        data = json.loads(self.inventory.read_text())
        guest = data['vms'][-1]
        guest.update(name='fixture', ignition='custom/fixture.ign', autostart=False)
        data['vms'] = [guest]
        custom = self.repo / 'custom.json'
        custom.write_text(json.dumps(data))
        self.deploy('--all', '--inventory', str(custom), '--start')
        self.assertTrue((self.repo / 'custom/fixture.ign').exists())
        self.assertTrue((self.pool / 'disks/fixture-root.qcow2').exists())
        calls = (self.root / 'calls').read_text()
        self.assertIn('virsh start fixture', calls)
        self.assertNotIn('virsh autostart fixture', calls)
        self.assertNotIn('k3s', calls)

    def test_invalid_ignition_never_creates_a_disk(self):
        self.deploy('immich', success=False, INVALID_IGNITION='true')
        self.assertFalse((self.pool / 'disks').exists())
        self.assertNotIn('virsh define', (self.root / 'calls').read_text())

    def test_existing_disk_is_preserved(self):
        (self.pool / 'disks').mkdir()
        disk = self.pool / 'disks/immich-root.qcow2'
        disk.write_text('existing data')
        result = self.deploy('immich', success=False)
        self.assertIn('refusing to overwrite', result.stderr)
        self.assertEqual(disk.read_text(), 'existing data')


if __name__ == '__main__':
    unittest.main()
