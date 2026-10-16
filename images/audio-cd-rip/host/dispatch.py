#!/usr/bin/python3
"""Root-only, short host operations; extraction runs as the music UID in Quadlet."""
import argparse
import fcntl
import os
from pathlib import Path
import subprocess

MUSIC = Path('/var/srv/music')
RUNTIME = Path('/run/audio-cd-rip-dispatch')


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=15).stdout.strip()


def audio_token(properties):
    if (properties.get('ID_BUS') != 'usb'
            or 'BW-16D1HT' not in properties.get('ID_MODEL', '')
            or properties.get('ID_CDROM_MEDIA_CD') != '1'
            or int(properties.get('ID_CDROM_MEDIA_TRACK_COUNT_AUDIO', '0')) < 1
            or int(properties.get('ID_CDROM_MEDIA_TRACK_COUNT_DATA', '0')) != 0):
        return None
    # Linux increments diskseq on media changes, including a rapid reinsert with
    # the same track count. Refuse to guess if it is unavailable on an old host.
    sequence = properties.get('DISKSEQ')
    if not sequence or not sequence.isdigit():
        raise RuntimeError('udev has no DISKSEQ; inspect the host before enabling automatic ripping')
    return sequence


def managed_directory(parent, name):
    # Directory FDs prevent symlinks from redirecting root's chown.
    # Existing directories are only inspected.
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        created = False
        try:
            os.mkdir(name, mode=0o755, dir_fd=parent_fd)
            created = True
        except FileExistsError:
            pass
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            if created:
                os.fchown(fd, 1001, 1001)
                os.fsync(fd)
                os.fsync(parent_fd)
            info = os.fstat(fd)
            if info.st_uid != 1001 or info.st_gid != 1001:
                raise RuntimeError(f'expected directory owned by 1001:1001: {parent / name}; no existing ownership was changed')
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def prepare(guest=False):
    if guest:
        path = MUSIC / 'cds'
        if path.is_symlink() or not os.path.ismount(path) or path.stat().st_uid != 1001 or path.stat().st_gid != 1001:
            raise RuntimeError('the VM needs the writable cds NFS mount owned by 1001:1001')
        return
    # nofail in the NAS fstab must not turn a missing SSD into writes on the OS disk.
    if not os.path.ismount(MUSIC) or MUSIC.is_symlink():
        raise RuntimeError(f'{MUSIC} must be its mounted music filesystem')
    managed_directory(MUSIC, 'cds')


def detect(retry=False):
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    with (RUNTIME / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if command('systemctl', 'show', '-p', 'ActiveState', '--value', 'audio-cd-rip.service') not in ('inactive', 'failed'):
            return
        seen = RUNTIME / 'seen'
        if retry:
            seen.unlink(missing_ok=True)
        if not Path('/dev/sr0').exists():
            seen.unlink(missing_ok=True)
            return
        properties = dict(line.split('=', 1) for line in command(
            'udevadm', 'info', '--query=property', '--name=/dev/sr0').splitlines() if '=' in line)
        token = audio_token(properties)
        if token is None:
            seen.unlink(missing_ok=True)
            return
        if seen.exists() and seen.read_text() == token:
            return
        # Mark before queuing. A failed rip stays loaded and is not retried every
        # ten seconds. Reinsertion, reboot, or explicit retry permits one attempt.
        seen.write_text(token)
        command('systemctl', '--no-block', 'start', 'audio-cd-rip.service')
        print(f'Queued audio CD extraction for media generation {token}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'prepare-guest', 'detect', 'retry'])
    action = parser.parse_args().action
    if os.geteuid() != 0:
        raise SystemExit('run as root')
    if action in ('prepare', 'prepare-guest'):
        prepare(guest=action == 'prepare-guest')
    else:
        detect(retry=action == 'retry')
