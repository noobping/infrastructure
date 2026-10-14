#!/usr/bin/python3
"""One-time configuration of already provisioned GitLab VMs. Does not migrate Git."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]


def butane_user():
    # The shared VM fragment contains one administrator, before storage/systemd.
    text = (REPO/'butane/vm.yml').read_text().split('storage:', 1)[0]
    names = re.findall(r'^\s+- name: ([a-z_][a-z0-9_-]*)\s*$', text, re.M)
    if len(names) != 1:
        raise ValueError('Expected one Butane VM administrator; select --user explicitly')
    return names[0]


def remote(host, username, password, data):
    source = (REPO/'vms/gitlab/setup-remote.py').read_text()
    command = shlex.join(['sudo', '-S', '-k', '-p', '', 'python3', '-c', source])
    for attempt in range(60):
        result = subprocess.run(['ssh', '-T', '-o', 'StrictHostKeyChecking=yes',
                                 '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', f'{username}@{host}', command],
                                input=password+'\n'+json.dumps(data)+'\n', text=True, capture_output=True)
        if result.returncode != 255 or not any(message in result.stderr for message in (
                'Connection refused', 'Connection timed out', 'No route to host')):
            break
        time.sleep(5)
    if result.returncode:
        # Remote commands never echo secret tool output. SSH diagnostics are useful.
        raise RuntimeError(f'{host}: '+result.stderr.strip())
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', help='SSH administrator (defaults to butane/vm.yml)')
    parser.add_argument('--trust-local', action='store_true', help='Also install the public CA in this Fedora computer\'s trust store')
    args = parser.parse_args()
    user = args.user or butane_user()
    if not re.fullmatch('[a-z_][a-z0-9_-]*', user):
        raise ValueError('Invalid SSH administrator')
    for host in ('nas.vm', 'gitlab.vm', 'gitlab-runner.vm', 'git.vm', 'git-registry.vm', 'git-ssh.vm'):
        socket.getaddrinfo(host, None)
    print('Configure existing GitLab VMs, encrypted NAS forwarding on 8443 and a protected project worker.')
    print('The VM login password will also become the GitLab administrator password. No repository is imported.')
    password = getpass.getpass(f'Existing Butane/VM password for {user}: ')
    if not password or '\n' in password or '\r' in password:
        raise ValueError('Expected a nonempty single-line password')
    inventory = json.loads((REPO/'vms/inventory.json').read_text())
    print('Hold and wake the pair through the NAS.', flush=True)
    try:
        state = remote('nas.vm', user, password, {'action': 'nas', 'inventory': inventory})
    except Exception:
        print('NAS setup failed; a maintenance hold may remain. Inspect it before releasing gitlab.', file=sys.stderr)
        raise
    output = REPO/'dist/gitlab-setup'
    output.mkdir(parents=True, exist_ok=True)
    try:
        print('Obtain the GitLab VM public CA over authenticated SSH.', flush=True)
        certificate = remote('gitlab.vm', user, password, {'action': 'certificate'})['certificate']
        (output/'gitlab-root.crt').write_text(certificate)
        print('Drain the worker and prepare its private signing identity.', flush=True)
        signing = remote('gitlab-runner.vm', user, password, {'action': 'worker_keys'})
        print('Configure the administrator, SSH key, private project and protected signing variables.', flush=True)
        runner = remote('gitlab.vm', user, password, {'action': 'server', 'username': user,
                         'password': password, 'signing': signing, 'certificate': certificate})
        print('Install CA trust and start the protected project worker.', flush=True)
        remote('gitlab-runner.vm', user, password, {'action': 'worker', 'runner': runner, 'certificate': certificate})
        if args.trust_local:
            result = subprocess.run(['sudo', '-S', '-k', '-p', '', 'python3', str(REPO/'vms/gitlab/setup-remote.py')],
                input=password+'\n'+json.dumps({'action': 'trust', 'certificate': certificate})+'\n',
                text=True, capture_output=True)
            if result.returncode:
                raise RuntimeError('Local CA installation failed; retry without --trust-local and import the public CA manually')
        if not state['prior_hold']:
            remote('nas.vm', user, password, {'action': 'release'})
    except Exception:
        print('Setup stopped safely; the NAS hold remains and the worker may be stopped. Rerun after fixing the error.', file=sys.stderr)
        print('After recovery, release the hold with: ssh '+user+'@nas.vm sudo vm-on-demand release gitlab', file=sys.stderr)
        raise
    print(f'Ready: https://git.vm:8443/{runner["project"]}; sign in as {user} with your VM password.')
    print(f'Public CA for your browser/computer: {output/"gitlab-root.crt"}')
    if state['prior_hold']:
        print('The pre-existing NAS maintenance hold was preserved.')


if __name__ == '__main__':
    try: main()
    except (Exception, KeyboardInterrupt) as error:
        print(f'Setup incomplete: {error}', file=sys.stderr)
        sys.exit(1)
