#!/usr/bin/python3
"""Read host data and preflight paths. All convergence belongs to the roles.

Ansible's normal getent/facts see container IDs, and realpath follows absolute
host symlinks into the container. Resolve those inputs here without writing.
This is preflight validation, not protection against concurrent directory
renames by logged-in users; the host unit must run before user sessions.
"""
import os
from pathlib import Path
import re
import stat

from ansible.module_utils.basic import AnsibleModule


class Host:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("root is not a directory")

    def resolve(self, virtual, leaf=False):
        if not virtual.startswith('/') or any(ord(c) < 32 for c in virtual):
            raise ValueError("invalid policy path")
        pending = virtual.split('/')[1:]
        resolved = []
        links = 0
        while pending:
            part = pending.pop(0)
            if part in ('', '.'):
                continue
            if part == '..':
                if not resolved:
                    raise ValueError("policy path escapes supplied root")
                resolved.pop()
                continue
            path = self.root.joinpath(*resolved, part)
            if path.is_symlink() and not (leaf and not pending):
                links += 1
                if links > 40:
                    raise ValueError("too many symbolic links")
                target = os.readlink(path)
                if target.startswith('/'):
                    resolved = []
                pending = target.split('/') + pending
            else:
                resolved.append(part)
        return self.root.joinpath(*resolved)

    def directory(self, path):
        if path.is_symlink():
            raise ValueError("refusing to follow symbolic link")
        if path.exists() and not path.is_dir():
            raise ValueError("policy directory has incorrect type")

    def regular(self, path):
        if path.is_symlink():
            raise ValueError("refusing symbolic link for policy file")
        if path.exists() and not path.is_file():
            raise ValueError("policy file has incorrect type")

    def confined(self, path, parent):
        if path == parent or not path.is_relative_to(parent):
            raise ValueError("policy path resolves outside allowed directory")


def read_environment(path, profile):
    allowed = {
        'NUT_UPS_HOST', 'NUT_UPS_NAME', 'NUT_UPS_PORT', 'NUT_MONITOR_USER',
        'NUT_MONITOR_PASSWORD', 'NUT_POWER_VALUE', 'NUT_ROLE', 'NUT_SHUTDOWNCMD',
    }
    if profile == 'nas':
        allowed.update({'NUT_MODE', 'NUT_DRIVER', 'NUT_DEVICE_PORT',
                        'NUT_UPS_DESCRIPTION', 'NUT_REMOTE_MONITOR_USER',
                        'NUT_REMOTE_MONITOR_PASSWORD'})
    values = {}
    # Parse assignments as data. Never invoke a shell, expand variables, or
    # evaluate quotes/backticks/Jinja from the host's environment file.
    for raw in path.read_text().split('\n'):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        line = re.sub(r'^export\s+', '', line)
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)', line)
        if not match:
            raise ValueError("invalid environment assignment")
        key, value = match.groups()
        if key not in allowed or key in values:
            raise ValueError("unsupported or duplicate environment key")
        value = value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError("unterminated quoted environment value")
            value = value[1:-1]
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("control character in environment value")
        values[key] = value
    return values


def collect(root, profile, report_managed):
    host = Host(root)
    data = dict(homes=[], skeleton=[], environment={}, nut_enabled=False,
                nut_gid='', nut_directory='', nut_files=[], managed=[], report_path='')
    if report_managed:
        report = host.resolve('/run/infrastructure-policy/managed-paths', leaf=True)
        if report.parent != host.root / 'run/infrastructure-policy' or not report.parent.is_dir():
            raise ValueError("managed-path report directory is not mounted")
        host.regular(report)
        data['report_path'] = str(report)

    if profile == 'workstation':
        home_base = host.resolve('/var/home')
        if home_base != host.root / 'var/home':
            raise ValueError("home mount resolves outside /var/home")
        skeleton = host.resolve('/etc/skel')
        sources = []
        if skeleton.is_dir():
            for parent, dirs, files in os.walk(skeleton, followlinks=False):
                for name in sorted(dirs + files):
                    sources.append(Path(parent) / name)
        sources.sort()
        for line in host.resolve('/etc/passwd').read_text().splitlines():
            fields = line.split(':')
            if len(fields) != 7:
                raise ValueError("invalid host passwd entry")
            user, _, uid, gid, _, home, shell = fields
            if not uid.isdecimal() or not gid.isdecimal() or not 1000 <= int(uid) < 60000:
                continue
            if not home.startswith(('/home/', '/var/home/')):
                continue
            if any(p in ('', '.', '..') for p in home.split('/')[1:]):
                continue
            path = host.resolve(home, leaf=True)
            host.confined(path, home_base)
            host.directory(path)
            interactive = not shell.endswith(('/false', '/nologin'))
            data['homes'].append(dict(path=str(path), virtual=home, uid=uid, gid=gid,
                                      interactive=interactive))
            data['managed'].append(home)
            if not interactive:
                continue
            for source in sources:
                virtual = home + '/' + str(source.relative_to(skeleton))
                destination = host.resolve(virtual, leaf=True)
                host.confined(destination, path)
                source_stat = source.lstat()
                kind = ('link' if stat.S_ISLNK(source_stat.st_mode) else
                        'directory' if stat.S_ISDIR(source_stat.st_mode) else 'file')
                if kind == 'file' and not stat.S_ISREG(source_stat.st_mode):
                    raise ValueError("unsupported skeleton entry type")
                exists = os.path.lexists(destination)
                if kind == 'directory' and exists:
                    if destination.is_symlink() or not destination.is_dir():
                        raise ValueError("blocks an additive skeleton directory")
                data['skeleton'].append(dict(
                    source=str(source), path=str(destination), virtual=virtual,
                    uid=uid, gid=gid, kind=kind, exists=exists,
                    mode=format(stat.S_IMODE(source_stat.st_mode), '04o'),
                    link=os.readlink(source) if kind == 'link' else '',
                ))
                data['managed'].append(virtual)

    nut_directory = host.resolve('/etc/ups', leaf=True)
    if nut_directory != host.root / 'etc/ups':
        raise ValueError("NUT directory resolves outside /etc/ups")
    host.directory(nut_directory)
    config = nut_directory / ('nut.env' if profile == 'nas' else 'netclient.env')
    host.regular(config)
    if config.exists():
        data['nut_enabled'] = True
        data['environment'] = read_environment(config, profile)
        data['nut_directory'] = str(nut_directory)
        for line in host.resolve('/etc/group').read_text().splitlines():
            fields = line.split(':')
            if len(fields) >= 3 and fields[0] == 'nut' and fields[2].isdecimal():
                data['nut_gid'] = fields[2]
                break
        if not data['nut_gid']:
            raise ValueError("required host group nut is missing")
        names = ['nut.conf', 'upsmon.conf']
        if profile == 'nas' and data['environment'].get('NUT_MODE') in ('standalone', 'netserver'):
            names += ['ups.conf', 'upsd.conf', 'upsd.users']
        data['managed'].append('/etc/ups')
        for name in names:
            destination = nut_directory / name
            host.regular(destination)
            data['nut_files'].append(dict(name=name, path=str(destination)))
            data['managed'].append('/etc/ups/' + name)
    return data


def main():
    module = AnsibleModule(argument_spec=dict(
        root=dict(type='path', required=True),
        profile=dict(choices=['workstation', 'nas'], required=True),
        report_managed=dict(type='bool', default=False),
    ), supports_check_mode=True)
    try:
        result = collect(**module.params)
    except ValueError as error:
        module.fail_json(msg=str(error), policy_error=str(error))
    except OSError:
        module.fail_json(msg="cannot read mounted host policy inputs")
    module.exit_json(changed=False, **result)


if __name__ == '__main__':
    main()
