#!/usr/bin/python3
"""One audio CD per invocation. Never publish partial audio or overwrite an album."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

# Linux UAPI: include/uapi/linux/cdrom.h. DRIVE_STATUS (0x5326) is a different query.
CDROM_DISC_STATUS = 0x5327
CDS_AUDIO = 100
DEVICE = '/dev/sr0'
LIBRARY = Path('/music')
STATE = LIBRARY / '.state'
CONFIG = Path('/config')
USER_AGENT = 'infrastructure-cd-rip/1.0 (https://github.com/noobping/infrastructure)'
MB = 'https://musicbrainz.org/ws/2/'
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
_last_request = 0.0


def log(message):
    print(message, flush=True)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path, value):
    # State shares the music filesystem. Interrupted JSON writes must not
    # leave unexpected temporary files in an otherwise recoverable album.
    temporary = STATE / (uuid.uuid4().hex + '.tmp')
    with temporary.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def safe_path(root, relative, create=False):
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts or any(p in ('.', '..') for p in relative.parts):
        raise ValueError('unsafe relative path')
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f'refusing symlink: {current}')
        if create and not current.exists():
            current.mkdir(mode=0o755)
            sync_directory(current.parent)
    return current


def component(value):
    value = unicodedata.normalize('NFC', str(value))
    value = ''.join('_' if c in '<>:"/\\|?*' or unicodedata.category(c).startswith('C') else c for c in value)
    value = value.strip(' .')
    return value.encode('utf-8')[:90].decode('utf-8', errors='ignore').rstrip(' .') or 'Unknown'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(args, logfile, timeout=1800):
    logfile.write(('\n' + repr(args) + '\n').encode())
    logfile.flush()
    process = subprocess.Popen(args, stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        code = process.wait(timeout=timeout)
        if code:
            raise RuntimeError(f'{args[0]} exited {code}; see rip.log')
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        raise


def read_disc():
    import discid
    with open(DEVICE, 'rb', buffering=0) as drive:
        # Explicitly reject mixed-mode discs, DVDs and data CDs.
        status = fcntl.ioctl(drive, CDROM_DISC_STATUS)
        if status != CDS_AUDIO:
            raise RuntimeError(f'the drive does not contain a pure audio CD (CDROM_DISC_STATUS={status})')
    disc = discid.read(DEVICE, features=['read'])
    tracks = [{'number': t.number, 'offset': t.offset, 'sectors': t.sectors} for t in disc.tracks]
    if not tracks or any(t['sectors'] <= 0 for t in tracks):
        raise RuntimeError('invalid audio table of contents')
    toc = {'id': disc.id, 'first': disc.first_track_num, 'last': disc.last_track_num,
           'sectors': disc.sectors, 'tracks': tracks}
    return toc


def disc_key(toc):
    return hashlib.sha256(json.dumps(toc, sort_keys=True).encode()).hexdigest()


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise ValueError('refusing non-HTTPS artwork redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit=5 * 1024 * 1024):
    global _last_request
    for attempt in range(3):
        # Also limit retries; never exceed MusicBrainz's one request per second.
        time.sleep(max(0, 1.1 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        try:
            with urllib.request.build_opener(HTTPSRedirect()).open(request, timeout=15) as response:
                data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('metadata/artwork response exceeds size limit')
            return data
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError('request failed')


def credit(value):
    return ''.join(item.get('name', item.get('artist', {}).get('name', '')) + item.get('joinphrase', '')
                   for item in value if isinstance(item, dict)) or 'Unknown Artist'


def choose_medium(release, toc):
    matches = [m for m in release.get('media', [])
               if any(d.get('id') == toc['id'] for d in m.get('discs', []))]
    if len(matches) != 1:
        raise ValueError('release does not have exactly one matching disc ID')
    medium = matches[0]
    tracks = medium.get('tracks', [])
    if (len(tracks) != len(toc['tracks'])
            or [t.get('position') for t in tracks] != list(range(1, len(tracks) + 1))):
        raise ValueError('release track list does not match the audio CD')
    return medium


def metadata(toc):
    """Only apply an unambiguous exact disc-ID match, or an explicit override."""
    overrides = json.loads((CONFIG / 'overrides.json').read_text())
    selected = overrides.get(toc['id'])
    if selected is not None and (not isinstance(selected, str) or not UUID.fullmatch(selected)):
        raise ValueError('release override must be a MusicBrainz release UUID')
    result = {'status': 'unknown', 'candidates': [], 'album': f'Unknown Album [{disc_key(toc)[:16]}]',
              'albumartist': 'Unknown Artist', 'discnumber': 1, 'disctotal': 1,
              'tracks': [{'title': f'Track {t["number"]:02}', 'artist': 'Unknown Artist'} for t in toc['tracks']]}
    try:
        if selected is None:
            lookup = json.loads(fetch(MB + 'discid/' + urllib.parse.quote(toc['id'], safe='') + '?fmt=json'))
            releases = lookup.get('releases', [])
            result['candidates'] = [{'id': r['id'], 'title': r.get('title', '')} for r in releases]
            if len(releases) != 1 or lookup.get('release-count', len(releases)) != 1:
                result['status'] = 'ambiguous' if releases else 'unknown'
                return result
            selected = releases[0]['id']
        if not UUID.fullmatch(selected):
            raise ValueError('invalid release identifier')
        release = json.loads(fetch(MB + 'release/' + selected + '?inc=recordings+artist-credits+discids+release-groups&fmt=json'))
        medium = choose_medium(release, toc)
        result.update(status='matched', release_id=selected, album=release['title'],
                      albumartist=credit(release.get('artist-credit', [])),
                      date=release.get('date', ''), discnumber=medium['position'],
                      disctotal=len(release['media']), release=release,
                      tracks=[{'title': t.get('title') or t['recording']['title'],
                               'artist': credit(t.get('artist-credit') or t['recording'].get('artist-credit') or release.get('artist-credit', [])),
                               'recording_id': t['recording']['id'], 'release_track_id': t.get('id', '')}
                              for t in medium['tracks']])
    except (OSError, ValueError, KeyError, TypeError) as error:
        if overrides.get(toc['id']) is not None:
            raise RuntimeError('explicit release override could not be verified') from error
        log(f'Metadata unavailable; using Unknown tags: {error}')
        result['error'] = str(error)
    return result


def artwork(meta):
    if meta['status'] != 'matched':
        return None
    try:
        data = fetch('https://coverartarchive.org/release/' + meta['release_id'] + '/front-500')
        if data.startswith(b'\xff\xd8\xff'):
            return ('jpg', 'image/jpeg', data)
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return ('png', 'image/png', data)
        raise ValueError('cover is not JPEG or PNG')
    except (OSError, ValueError) as error:
        log(f'Cover art unavailable: {error}')
        return None


def tag(path, meta, track, index, toc, cover):
    from mutagen.flac import FLAC, Picture
    audio = FLAC(path)
    tags = {'album': meta['album'], 'albumartist': meta['albumartist'],
            'artist': track['artist'], 'title': track['title'], 'tracknumber': str(index),
            'tracktotal': str(len(toc['tracks'])), 'discnumber': str(meta['discnumber']),
            'disctotal': str(meta['disctotal']), 'musicbrainz_discid': toc['id'],
            'comment': 'Extracted with cdparanoia full paranoia and abort-on-skip; FLAC verified.'}
    if meta['status'] == 'matched':
        tags.update(date=meta['date'], musicbrainz_albumid=meta['release_id'],
                    musicbrainz_trackid=track['recording_id'],
                    musicbrainz_releasetrackid=track['release_track_id'])
    for key, value in tags.items():
        if value:
            audio[key] = [value]
    if cover:
        picture = Picture()
        picture.type, picture.mime, picture.desc, picture.data = 3, cover[1], 'Front cover', cover[2]
        audio.add_picture(picture)
    audio.save()


def destination(meta, key):
    return Path(component(meta['albumartist'])) / component(meta['album'])


def verify_manifest(path):
    manifest_path = safe_path(path, '.rip-manifest.json')
    if path.is_symlink():
        raise RuntimeError('published album was replaced by a symlink')
    manifest = json.loads(manifest_path.read_text())
    files = manifest['files']
    if set(p.name for p in path.iterdir()) != set(files) | {'.rip-manifest.json'}:
        raise RuntimeError('existing album has missing or additional files; refusing overwrite')
    for name, expected in files.items():
        if Path(name).name != name:
            raise RuntimeError('invalid manifest filename')
        candidate = safe_path(path, name)
        if not candidate.is_file() or digest(candidate) != expected:
            raise RuntimeError(f'existing album is missing or changed: {candidate}; refusing overwrite')
    return manifest


def verify_album(path, key, count):
    manifest = verify_manifest(path)
    disc = manifest['discs'].get(key)
    if not disc or len(disc['tracks']) != count or not set(disc['tracks']) <= set(manifest['files']):
        raise RuntimeError('existing album identity or track count differs; refusing overwrite')
    return manifest


def completed(toc, key, record):
    if not record.exists():
        return False
    transaction = json.loads(record.read_text())
    path = safe_path(LIBRARY, transaction['destination'])
    pending = transaction['status'] == 'pending'
    if pending:
        manifest = safe_path(path, '.rip-manifest.json')
        current = json.loads(manifest.read_text()) if manifest.exists() else {}
        if key not in current.get('discs', {}):
            stage = safe_path(LIBRARY, transaction['stage'])
            publish_album(stage, path, verify_manifest(stage), transaction.get('previous'))
    verify_album(path, key, len(toc['tracks']))
    if pending:
        write_json(record, {'status': 'complete', 'destination': transaction['destination'], 'key': key})
    log(f'Import verified: {path}')
    return True


def publish_album(stage, target, addition, previous):
    # One method for local and NFS storage: add verified files without replacing
    # existing names, then atomically update the manifest. Shared POSIX locking
    # serializes ripper writers; checksums also reject external changes.
    expected = {'files': dict(previous['files']) if previous else {},
                'discs': dict(previous['discs']) if previous else {},
                'release_id': addition['release_id']}
    for name, checksum in addition['files'].items():
        if name in expected['files'] and expected['files'][name] != checksum:
            raise RuntimeError('album filename collision; existing file preserved')
    expected['files'].update(addition['files'])
    expected['discs'].update(addition['discs'])
    if target.exists():
        if target.is_symlink():
            raise RuntimeError('album target is a symlink')
        present = {entry.name for entry in target.iterdir()}
        if previous and not (set(previous['files']) | {'.rip-manifest.json'}).issubset(present):
            raise RuntimeError('existing album has missing files; refusing publication')
        for name in present:
            entry = safe_path(target, name)
            if name == '.rip-manifest.json':
                if json.loads(entry.read_text()) not in (previous, expected):
                    raise RuntimeError('album manifest changed during publication')
            elif name not in expected['files'] or digest(entry) != expected['files'][name]:
                raise RuntimeError('album changed during publication; refusing overwrite')
    elif previous:
        raise RuntimeError('existing album disappeared during publication')
    target.mkdir(exist_ok=True)
    for name, checksum in addition['files'].items():
        source = safe_path(stage, name)
        if digest(source) != checksum:
            raise RuntimeError('staged data changed before publication')
        try:
            os.link(source, target / name, follow_symlinks=False)
        except FileExistsError:
            if digest(safe_path(target, name)) != checksum:
                raise RuntimeError('album filename collision; existing file preserved')
    write_json(target / '.rip-manifest.json', expected)
    sync_directory(target.parent)


def validate_wav(path, sectors):
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()) != (2, 2, 44100, sectors * 588):
            raise RuntimeError('ripped PCM format/length differs from the disc table of contents')


def import_disc(toc, logfile):
    key = disc_key(toc)
    records = safe_path(STATE, 'discs', create=True)
    record = records / (key + '.json')
    if completed(toc, key, record):
        return
    meta = metadata(toc)
    relative = destination(meta, key)
    target = safe_path(LIBRARY, relative)
    existing = None
    if target.exists():
        existing = verify_manifest(target)
        if key in existing['discs']:
            verify_album(target, key, len(toc['tracks']))
            write_json(record, {'status': 'complete', 'destination': str(relative), 'key': key})
            return
        if (meta['status'] != 'matched' or existing.get('release_id') != meta.get('release_id')
                or any(d['number'] == meta['discnumber'] for d in existing['discs'].values())):
            raise RuntimeError('album name collision with another release/disc; existing album preserved')
    needed = sum(t['sectors'] for t in toc['tracks']) * 2352 * 2 + 256 * 1024 * 1024
    if shutil.disk_usage(LIBRARY).free < needed:
        raise RuntimeError(f'insufficient music storage; need at least {needed} free bytes')
    work = safe_path(LIBRARY, '.work', create=True)
    (work / '.ignore').touch(exist_ok=True)
    stage = safe_path(work, key[:16] + '-' + uuid.uuid4().hex, create=True)
    log(f'Working directory: {stage}; metadata: {meta["status"]}')
    prefix = f'{meta["discnumber"]:02}-' if meta['disctotal'] > 1 else ''
    write_json(stage / f'{prefix}metadata.json', {'toc': toc, 'metadata': meta})
    cover = artwork(meta)
    if cover:
        cover_name = ('disc-' + prefix if existing else '') + 'cover.' + cover[0]
        (stage / cover_name).write_bytes(cover[2])
    for index, (physical, track) in enumerate(zip(toc['tracks'], meta['tracks'], strict=True), 1):
        if read_disc() != toc:
            raise RuntimeError('disc changed during extraction')
        log(f'Extracting track {index}/{len(toc["tracks"])}')
        wav = stage / f'{index:02}.wav'
        flac = stage / f'{prefix}{index:02} - {component(track["title"])}.flac'
        run(['cdparanoia', '-d', DEVICE, '-q', '-X', str(physical['number']), str(wav)], logfile)
        validate_wav(wav, physical['sectors'])
        run(['flac', '--silent', '--verify', '--output-name=' + str(flac), str(wav)], logfile, timeout=300)
        tag(flac, meta, track, index, toc, cover)
        run(['flac', '--silent', '--test', str(flac)], logfile, timeout=300)
        wav.unlink()
    if read_disc() != toc:
        raise RuntimeError('disc changed before publication')
    files = {p.name: digest(p) for p in stage.iterdir() if p.is_file()}
    discs = {key: {'toc': toc, 'number': meta['discnumber'],
                   'tracks': [name for name in files if name.endswith('.flac')]}}
    write_json(stage / '.rip-manifest.json', {'discs': discs, 'files': files,
                                            'release_id': meta.get('release_id')})
    for path in stage.iterdir():
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
    sync_directory(stage)
    safe_path(LIBRARY, relative.parent, create=True)
    # The same completion path handles a new import and an interrupted one.
    write_json(record, {'status': 'pending', 'destination': str(relative), 'key': key,
                        'stage': str(stage.relative_to(LIBRARY)), 'previous': existing})
    completed(toc, key, record)


def process_disc(logfile):
    toc = None
    success = False
    try:
        run(['eject', '-i', 'on', DEVICE], logfile, timeout=15)
        toc = read_disc()
        log(f'Audio CD {toc["id"]}, {len(toc["tracks"])} tracks')
        import_disc(toc, logfile)
        success = True
    finally:
        try:
            run(['eject', '-i', 'off', DEVICE], logfile, timeout=15)
        except Exception as error:
            log(f'Drive unlock failed: {error}; use eject -i off manually')
        if success:
            try:
                if read_disc() != toc:
                    raise RuntimeError('disc changed; refusing to eject the replacement')
                run(['eject', DEVICE], logfile, timeout=15)
                log('Verified import complete; disc ejected')
            except Exception as error:
                # Never invalidate completed audio because a USB tray failed.
                log(f'Import is complete, but eject failed: {error}; eject manually')


def interrupted(signum, frame):
    raise InterruptedError(f'received signal {signum}; leaving incomplete audio unpublished')


def main():
    os.umask(0o022)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, interrupted)
    safe_path(LIBRARY, STATE.relative_to(LIBRARY), create=True)
    (STATE / '.ignore').touch(exist_ok=True)
    with (STATE / 'rip.lock').open('a') as lock:
        try:
            # POSIX locks interoperate between local NAS and NFS client writers.
            fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another extraction is running')
        logs = safe_path(STATE, 'logs', create=True)
        attempt = safe_path(logs, time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:8], create=True)
        log(f'Extraction log: {attempt / "rip.log"}')
        with (attempt / 'rip.log').open('ab', buffering=0) as logfile:
            try:
                process_disc(logfile)
            except Exception as error:
                write_json(attempt / 'error.json', {'error': str(error)})
                raise


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        log(f'FAILED: {error}. Disc left loaded; inspect logs before retrying.')
        raise SystemExit(1)
