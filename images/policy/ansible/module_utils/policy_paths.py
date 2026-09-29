"""Resolve mounted host paths without following absolute links into the container."""
import os
from pathlib import Path


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
