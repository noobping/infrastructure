#!/usr/bin/python3
"""Read-only preflight for service-state roles; never follows state symlinks."""
import os
from pathlib import Path
import stat

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.policy_paths import Host


def collect(root, directories, seeds, links):
    host = Host(root)
    result = dict(directories=[], files=[], seeds=[], links=[])
    planned_directories = {}
    users = {'root': '0'}
    groups = {'root': '0'}
    for virtual, identities, index in (('/etc/passwd', users, 2), ('/etc/group', groups, 2)):
        for line in host.resolve(virtual).read_text().splitlines():
            fields = line.split(':')
            if len(fields) > index and fields[index].isascii() and fields[index].isdecimal():
                identities[fields[0]] = fields[index]

    def safe(virtual, kind):
        if any(part in ('', '.', '..') for part in virtual.split('/')[1:]):
            raise ValueError('invalid service policy path')
        path = host.resolve(virtual, leaf=True)
        if path != host.root / virtual.lstrip('/'):
            raise ValueError('redirected service policy path')
        if kind == 'directory':
            host.directory(path)
        elif kind == 'file':
            host.regular(path)
        return path

    def ownership(spec):
        try:
            return dict(uid=users[spec['owner']], gid=groups[spec['group']])
        except KeyError:
            raise ValueError('required service user or group is missing') from None

    def entry(virtual, spec, mode, kind):
        return dict(path=str(safe(virtual, kind)), virtual=virtual,
                    mode=mode, **ownership(spec))

    def directory(virtual, spec, mode):
        planned_directories[virtual] = entry(virtual, spec, mode, 'directory')

    def walk(path):
        # os.walk does not follow symlink directories, but they must still be
        # rejected explicitly before Ansible receives any mutation targets.
        for parent, dirs, files in os.walk(path, followlinks=False):
            for name in sorted(dirs + files):
                child = Path(parent) / name
                if child.is_symlink():
                    raise ValueError('symbolic link in service state or seed data')
                if not child.is_dir() and not child.is_file():
                    raise ValueError('unsupported service state or seed entry')
                yield child

    for spec in directories:
        virtual = spec['path']
        directory(virtual, spec, spec['mode'])
        path = safe(virtual, 'directory')
        if spec.get('recursive') and path.exists():
            for child in walk(path):
                child_virtual = '/' + str(child.relative_to(host.root))
                if child.is_dir():
                    mode = spec.get('directory_mode', format(stat.S_IMODE(child.stat().st_mode), '04o'))
                    directory(child_virtual, spec, mode)
                else:
                    result['files'].append(entry(child_virtual, spec, spec['file_mode'], 'file'))

    for seed in seeds:
        source = safe(seed['source'], 'directory')
        if not source.is_dir():
            raise ValueError('service seed directory is missing')
        destination = seed['destination']
        parents = [spec for spec in directories if destination == spec['path']
                   or destination.startswith(spec['path'] + '/')]
        if not parents:
            raise ValueError('seed destination is outside managed service directories')
        spec = max(parents, key=lambda item: len(item['path']))
        target = safe(destination, 'directory')
        if destination not in planned_directories:
            mode = spec.get('directory_mode', format(stat.S_IMODE(
                target.stat().st_mode if target.exists() else source.stat().st_mode), '04o'))
            directory(destination, spec, mode)
        for child in walk(source):
            virtual = destination + '/' + str(child.relative_to(source))
            if child.is_dir():
                if virtual not in planned_directories:
                    directory(virtual, spec, spec.get('directory_mode', format(stat.S_IMODE(child.stat().st_mode), '04o')))
            else:
                item = entry(virtual, spec, spec['file_mode'], 'file')
                if not Path(item['path']).exists():
                    result['seeds'].append(dict(source=str(child), **item))

    for spec in links:
        path = safe(spec['path'], 'link')
        if path.is_dir() and not path.is_symlink():
            raise ValueError('directory blocks service compatibility link')
        result['links'].append(dict(path=str(path), virtual=spec['path'],
                                    target=spec['target'], **ownership(spec),
                                    remove=os.path.lexists(path) and not path.is_symlink()))
    result['directories'] = [planned_directories[key] for key in sorted(planned_directories)]
    return result


def main():
    module = AnsibleModule(argument_spec=dict(
        root=dict(type='path', required=True),
        directories=dict(type='list', elements='dict', required=True),
        seeds=dict(type='list', elements='dict', default=[]),
        links=dict(type='list', elements='dict', default=[]),
    ), supports_check_mode=True)
    try:
        result = collect(**module.params)
    except ValueError as error:
        module.fail_json(msg=str(error), policy_error=str(error))
    except (OSError, KeyError):
        module.fail_json(msg='cannot read service policy inputs')
    module.exit_json(changed=False, **result)


if __name__ == '__main__':
    main()
