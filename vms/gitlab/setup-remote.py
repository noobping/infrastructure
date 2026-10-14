#!/usr/bin/python3
"""Root-side steps for setup.py. Transport is authenticated SSH, never HTTP."""
import ctypes
import ctypes.util
import hmac
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

CONFIG = Path('/var/lib/gitlab/config')
RUNNER_CONFIG = Path('/etc/gitlab-runner')
RUNNER_TEMPLATE = Path('/usr/share/gitlab-runner/config.toml')
API_URL = 'http://127.0.0.1:8080/api/v4'


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        # Tools may echo credentials. Never include their output in setup errors.
        raise RuntimeError(f'{args[0]} failed (exit {result.returncode}); inspect its local service log')
    return result.stdout.strip()


def write(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def trust(certificate):
    if certificate.count('-----BEGIN CERTIFICATE-----') != 1 or 'PRIVATE KEY' in certificate:
        raise ValueError('Expected only the public Caddy root certificate')
    info = run('openssl', 'x509', '-noout', '-text', input=certificate)
    if 'CA:TRUE' not in info:
        raise ValueError('Certificate is not a CA')
    run('openssl', 'x509', '-noout', '-checkend', '86400', input=certificate)
    write('/etc/pki/ca-trust/source/anchors/infrastructure-gitlab.crt', certificate, 0o644)
    run('update-ca-trust')


def vm_identity(username, password):
    account = pwd.getpwnam(username)
    if account.pw_uid != 1000:
        raise ValueError('Expected the Butane administrator with UID 1000')
    shadow = next(line.split(':')[1] for line in Path('/etc/shadow').read_text().splitlines()
                  if line.split(':')[0] == username)
    library = ctypes.CDLL(ctypes.util.find_library('crypt'))
    library.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    library.crypt.restype = ctypes.c_char_p
    hashed = library.crypt(password.encode(), shadow.encode())
    if not shadow.startswith('$') or not hashed or not hmac.compare_digest(hashed, shadow.encode()):
        raise ValueError('Password does not match the VM login; no GitLab password was changed')
    home = Path(account.pw_dir)
    paths = [home/'.ssh/authorized_keys', *sorted((home/'.ssh/authorized_keys.d').glob('*'))]
    keys = set()
    for path in paths:
        if path.is_file():
            for line in path.read_text().splitlines():
                fields = line.split()
                # Do not strip source/command restrictions from a restricted key.
                if len(fields) >= 2 and fields[0] in ('ssh-ed25519', 'ssh-rsa',
                        'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521'):
                    keys.add(' '.join(fields[:2]))
    if not keys:
        raise ValueError('No unrestricted Butane SSH public key found for the administrator')
    return sorted(keys)


def api(token, method, path, data=None, missing=False):
    headers = {'PRIVATE-TOKEN': token, 'Host': 'git.vm'}
    if data is not None:
        data = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(API_URL+path,
                                     headers=headers, method=method, data=data)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        if missing and error.code == 404:
            return None
        raise RuntimeError(f'GitLab {method} {path} returned HTTP {error.code}') from None


def wait_ready():
    for _ in range(180):
        try:
            status = run('podman', 'exec', 'gitlab', '/opt/gitlab/embedded/bin/curl',
                         '-fsS', '--max-time', '3', 'http://127.0.0.1:8080/-/readiness')
            if json.loads(status).get('status') == 'ok':
                return
        except (RuntimeError, ValueError):
            pass
        time.sleep(5)
    raise RuntimeError('GitLab did not become ready after certificate trust was installed')


def configure_project(token, username, signing, state):
    project_path = username+'/infrastructure'
    project = api(token, 'GET', '/projects/'+urllib.parse.quote(project_path, safe=''), missing=True)
    if project is None:
        project = api(token, 'POST', '/projects', {'name': 'infrastructure', 'path': 'infrastructure',
                      'visibility': 'private', 'initialize_with_readme': False, 'default_branch': 'main'})
    if project['namespace']['full_path'] != username or project['visibility'] != 'private':
        raise ValueError('Setup requires the administrator-owned private infrastructure project')
    prefix = f'/projects/{project["id"]}'
    previous = api(token, 'GET', prefix+'/variables/COSIGN_PUBLIC_KEY', missing=True)
    if previous and previous['value'].strip() != signing['public'].strip():
        raise ValueError('Existing signing identity differs; restore the worker key instead of rotating it')
    api(token, 'PUT', prefix, {'ci_config_path': '.gitlab/ci/self-hosted.yml',
                              'shared_runners_enabled': False})
    branch = project.get('default_branch') or 'main'
    if not api(token, 'GET', prefix+'/protected_branches/'+urllib.parse.quote(branch, safe=''), missing=True):
        api(token, 'POST', prefix+'/protected_branches',
            {'name': branch, 'push_access_level': 40, 'merge_access_level': 40})
    if not api(token, 'GET', prefix+'/protected_tags/%2A', missing=True):
        api(token, 'POST', prefix+'/protected_tags', {'name': '*', 'create_access_level': 40})
    for name, value, kind in (('COSIGN_KEY', signing['private'], 'file'),
                              ('COSIGN_PUBLIC_KEY', signing['public'], 'file'),
                              ('COSIGN_PASSWORD', signing['password'], 'env_var')):
        existing = api(token, 'GET', prefix+'/variables/'+name, missing=True)
        data = {'key': name, 'value': value, 'variable_type': kind,
                'protected': True, 'masked': name == 'COSIGN_PASSWORD'}
        api(token, 'PUT' if existing else 'POST', prefix+'/variables'+('/'+name if existing else ''), data)
    path = state/'runner.json'
    if path.exists():
        runner = json.loads(path.read_text())
        if runner['project_id'] != project['id']:
            raise ValueError('Existing worker registration belongs to another project')
        detail = api(token, 'GET', f'/runners/{int(runner["id"])}')
        if {p['id'] for p in detail['projects']} != {project['id']}:
            raise ValueError('Runner is assigned outside the infrastructure project')
        api(token, 'PUT', f'/runners/{int(runner["id"])}',
            {'locked': True, 'run_untagged': False, 'access_level': 'ref_protected',
             'tag_list': ['infrastructure-amd64']})
    else:
        runner = api(token, 'POST', '/user/runners', {'runner_type': 'project_type',
            'project_id': project['id'], 'description': 'infrastructure-amd64', 'locked': True,
            'tag_list': ['infrastructure-amd64'], 'run_untagged': False, 'access_level': 'ref_protected'})
        runner['project_id'] = project['id']
        write(path, json.dumps(runner)+'\n')
    # The worker verifies this token using its actual persistent system ID.
    return {'token': runner['token'], 'project': project_path}


def server(data):
    keys = vm_identity(data['username'], data['password'])
    run('systemctl', 'start', 'gitlab.service')  # Wait for first-boot bootstrap to finish.
    trust(data['certificate'])
    write(CONFIG/'trusted-certs/infrastructure-gitlab.crt', data['certificate'], 0o644)
    if Path('/sys/fs/selinux/enforce').exists():
        # This bind mount is already active with :Z. Host-created entries must
        # retain its private MCS label before the running container reads them.
        run('chcon', '--reference', str(CONFIG), str(CONFIG/'trusted-certs'),
            str(CONFIG/'trusted-certs/infrastructure-gitlab.crt'))
    # Install trust into Omnibus's embedded TLS store as well as the FCOS host.
    run('podman', 'exec', 'gitlab', 'gitlab-ctl', 'reconfigure')
    wait_ready()
    ruby = '''require 'json'
d = JSON.parse(STDIN.read)
user = User.find(1)
raise 'Existing administrator identity differs' unless user.admin? && ['root', d['username']].include?(user.username)
user.password = user.password_confirmation = d['password']
user.password_automatically_set = false
user.save!
user.personal_access_tokens.where(name: 'infrastructure-setup', revoked: false).find_each(&:revoke!)
t = user.personal_access_tokens.create!(name: 'infrastructure-setup', scopes: ['api'], expires_at: Date.today + 1)
puts JSON.generate({token: t.token})
'''
    # Use GitLab's documented Rails password reset; the admin HTTP API would
    # force a second password change on login. Secrets travel only over stdin.
    token = json.loads(run('podman', 'exec', '--interactive', 'gitlab', 'gitlab-rails', 'runner', ruby,
                           input=json.dumps({'username': data['username'], 'password': data['password']})))['token']
    try:
        wait_ready()
        user = api(token, 'GET', '/user')
        if user['id'] != 1 or not user['is_admin'] or user['username'] not in ('root', data['username']):
            raise ValueError('Existing GitLab administrator identity differs')
        api(token, 'PUT', '/users/1', {'username': data['username']})
        existing = {' '.join(key['key'].split()[:2]) for key in api(token, 'GET', '/user/keys')}
        for key in keys:
            if key not in existing:
                api(token, 'POST', '/user/keys', {'title': 'Butane administrator key', 'key': key})
        return configure_project(token, data['username'], data['signing'], CONFIG)
    finally:
        try:
            api(token, 'DELETE', '/personal_access_tokens/self')
        except (RuntimeError, urllib.error.URLError):
            # A web restart must not leave a broad API credential active.
            run('podman', 'exec', '--interactive', 'gitlab', 'gitlab-rails', 'runner',
                "require 'json'; PersonalAccessToken.find_by_token(JSON.parse(STDIN.read)['token'])&.revoke!",
                input=json.dumps({'token': token}))


def worker_keys():
    run('systemctl', 'stop', 'gitlab-runner.service')  # SIGQUIT; never force a running job off.
    root = RUNNER_CONFIG/'signing'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    password = root/'password'
    if not password.exists():
        if (root/'cosign.key').exists():
            raise ValueError('Restore the existing signing password; refusing to replace it')
        write(password, secrets.token_hex(32))
    if not (root/'cosign.key').exists():
        run('cosign', 'generate-key-pair', '--output-key-prefix', str(root/'cosign'),
            env={**os.environ, 'COSIGN_PASSWORD': password.read_text()})
        (root/'cosign.key').chmod(0o600)
    return {'private': (root/'cosign.key').read_text(), 'public': (root/'cosign.pub').read_text(),
            'password': password.read_text()}


def worker(data):
    trust(data['certificate'])
    path = RUNNER_CONFIG/'config.toml'
    token = data['runner']['token']
    if not token.startswith('glrt-'):
        raise ValueError('Expected a runner authentication token')
    if run('systemctl', 'show', '--property=ActiveState', '--value', 'gitlab-runner.service') != 'inactive':
        raise ValueError('Drain the worker before installing configuration')
    template = RUNNER_TEMPLATE.read_text()
    write(path, template.replace('[[runners]]', '[[runners]]\n  token = '+json.dumps(token), 1))
    run('gitlab-runner', 'verify', '--config', str(path))
    # Preparation must revalidate changed credentials even on an already booted VM.
    run('systemctl', 'restart', 'gitlab-runner-prepare.service')
    run('systemctl', 'start', 'gitlab-runner.service')
    return {}


def nas(data):
    inventory = '/run/gitlab-setup-inventory.json'
    write(inventory, json.dumps(data['inventory']))
    run('vm-on-demand', 'enable', 'gitlab', '--inventory', inventory)
    prior_hold = Path('/var/lib/infrastructure/vm-on-demand/gitlab.hold').exists()
    run('vm-on-demand', 'hold', 'gitlab')
    run('vm-on-demand', 'wake', 'gitlab')
    # NAS sockets only forward encrypted bytes. No certificate/web service here.
    return {'prior_hold': prior_hold}


def certificate():
    # Runs on the GitLab VM, never on the NAS.
    run('systemctl', 'start', 'gitlab-frontend.service')
    path = Path('/var/lib/gitlab/frontend/data/caddy/pki/authorities/local/root.crt')
    for _ in range(60):
        try:
            run('podman', 'healthcheck', 'run', 'gitlab-frontend')
            if path.is_file():
                return {'certificate': path.read_text()}
        except RuntimeError:
            pass
        time.sleep(1)
    raise RuntimeError('GitLab VM frontend did not create its local CA')


def main():
    if os.geteuid() != 0:
        raise ValueError('Setup requires administrator privileges')
    os.umask(0o077)
    # sudo -S may consume the first line, or leave it when NOPASSWD applies.
    # The final line is always the JSON request, including escaped newlines.
    data = json.loads(sys.stdin.read().splitlines()[-1])
    action = data['action']
    if action == 'nas': result = nas(data)
    elif action == 'certificate': result = certificate()
    elif action == 'server': result = server(data)
    elif action == 'worker_keys': result = worker_keys()
    elif action == 'worker': result = worker(data)
    elif action == 'trust': trust(data['certificate']); result = {}
    elif action == 'release':
        run('vm-on-demand', 'release', 'gitlab'); result = {}
    else: raise ValueError('Unknown setup action')
    print(json.dumps(result))


if __name__ == '__main__':
    try: main()
    except Exception as error:
        # Avoid a traceback containing a subprocess payload or a secret response.
        print(f'Setup failed: {error}', file=sys.stderr)
        sys.exit(1)
