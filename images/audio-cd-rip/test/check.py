#!/usr/bin/env python3
"""Offline lifecycle/error fixtures; --runtime additionally uses real FLAC/Mutagen."""
import copy
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

REPO = Path(__file__).resolve().parents[3]
RUNTIME = '--runtime' in sys.argv
if RUNTIME:
    sys.argv.remove('--runtime')


def module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(REPO / path))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


rip = module('rip', '/usr/bin/audio-cd-rip' if RUNTIME else 'images/audio-cd-rip/rip.py')
dispatch = module('dispatch', 'images/audio-cd-rip/host/dispatch.py')
TOC = {'id': 'test_disc_id', 'first': 1, 'last': 2, 'sectors': 300,
       'tracks': [{'number': 1, 'offset': 150, 'sectors': 75},
                  {'number': 2, 'offset': 225, 'sectors': 75}]}
META = {'status': 'unknown', 'album': 'Test Album', 'albumartist': 'Test Artist',
        'discnumber': 1, 'disctotal': 1,
        'tracks': [{'title': 'First', 'artist': 'Artist One'}, {'title': 'Second', 'artist': 'Artist Two'}]}
RELEASE_ID = '12345678-1234-1234-1234-123456789abc'
RELEASE = {'id': RELEASE_ID, 'title': 'Album', 'artist-credit': [{'name': 'Artist'}],
           'media': [{'position': 1, 'discs': [{'id': TOC['id']}],
                      'tracks': [{'position': i, 'id': RELEASE_ID, 'title': f'Track {i}',
                                  'recording': {'id': RELEASE_ID}} for i in (1, 2)]}]}


class Temporary(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('LIBRARY', 'STATE', 'CONFIG'):
            path = self.root / name
            path.mkdir()
            self.patch(rip, name, path)
        (rip.CONFIG / 'overrides.json').write_text('{}')
        self.patch(rip, 'log', lambda text: None)

    def patch(self, owner, name, *args, **kwargs):
        patcher = patch.object(owner, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result


class DiscReading(Temporary):
    def setUp(self):
        super().setUp()
        device = self.root / 'sr0'
        device.touch()
        self.patch(rip, 'DEVICE', str(device))
        disc = SimpleNamespace(id=TOC['id'], first_track_num=TOC['first'],
                               last_track_num=TOC['last'], sectors=TOC['sectors'],
                               tracks=[SimpleNamespace(**track) for track in TOC['tracks']])
        self.reader = Mock(return_value=disc)
        self.enterContext(patch.dict(sys.modules, {'discid': SimpleNamespace(read=self.reader)}))

    def test_audio_cd_uses_disc_type_instead_of_drive_status(self):
        # Linux cdrom.h: DRIVE_STATUS returns DISC_OK=4, DISC_STATUS returns AUDIO=100.
        query = self.patch(rip.fcntl, 'ioctl',
                           side_effect=lambda drive, request, *args: {0x5326: 4, 0x5327: 100}[request])
        self.assertEqual(rip.read_disc(), TOC)
        query.assert_called_once()
        self.assertEqual(query.call_args.args[1], 0x5327)
        self.reader.assert_called_once_with(rip.DEVICE, features=['read'])

    def test_non_audio_or_missing_disc_is_rejected_before_reading_toc(self):
        # NO_INFO, NO_DISC, DATA_1/2, XA_2_1/2 and MIXED from Linux cdrom.h.
        for status in (0, 1, 101, 102, 103, 104, 105):
            with self.subTest(status=status), patch.object(rip.fcntl, 'ioctl', return_value=status):
                with self.assertRaisesRegex(RuntimeError, f'CDROM_DISC_STATUS={status}'):
                    rip.read_disc()
        self.reader.assert_not_called()

    def test_device_query_failure_does_not_read_toc(self):
        self.patch(rip.fcntl, 'ioctl', side_effect=OSError('device unavailable'))
        with self.assertRaisesRegex(OSError, 'device unavailable'):
            rip.read_disc()
        self.reader.assert_not_called()


class Metadata(Temporary):
    def test_exact_single_match_and_multidisc(self):
        release = copy.deepcopy(RELEASE)
        release['media'].insert(0, {'position': 1, 'discs': [], 'tracks': []})
        release['media'][1]['position'] = 2
        self.patch(rip, 'fetch', side_effect=[json.dumps({'releases': [{'id': RELEASE_ID}]}).encode(), json.dumps(release).encode()])
        result = rip.metadata(TOC)
        self.assertEqual(result['status'], 'matched')
        self.assertEqual((result['discnumber'], result['disctotal']), (2, 2))
        self.assertEqual(result['tracks'][0]['artist'], 'Artist')

    def test_ambiguous_releases_remain_unknown(self):
        fetch = self.patch(rip, 'fetch', return_value=json.dumps({'releases': [{'id': RELEASE_ID}, {'id': RELEASE_ID}]}).encode())
        result = rip.metadata(TOC)
        self.assertEqual(result['status'], 'ambiguous')
        self.assertTrue(result['album'].startswith('Unknown Album ['))
        fetch.assert_called_once()

    def test_network_failure_does_not_prevent_ripping(self):
        self.patch(rip, 'fetch', side_effect=OSError('offline'))
        self.assertEqual(rip.metadata(TOC)['status'], 'unknown')
        self.assertIsNone(rip.artwork({'status': 'matched', 'release_id': RELEASE_ID}))

    def test_bad_override_fails_closed(self):
        (rip.CONFIG / 'overrides.json').write_text(json.dumps({TOC['id']: '../../unsafe'}))
        with self.assertRaises(ValueError):
            rip.metadata(TOC)
        (rip.CONFIG / 'overrides.json').write_text(json.dumps({TOC['id']: RELEASE_ID}))
        self.patch(rip, 'fetch', return_value=json.dumps(dict(RELEASE, media=[])).encode())
        with self.assertRaises(RuntimeError):
            rip.metadata(TOC)

    def test_track_count_mismatch_and_untrusted_names(self):
        release = copy.deepcopy(RELEASE)
        release['media'][0]['tracks'].pop()
        with self.assertRaises(ValueError):
            rip.choose_medium(release, TOC)
        for name in ('../../evil', '/absolute', '.', '\x00|?*', '日' * 100):
            component = rip.component(name)
            self.assertNotIn('/', component)
            self.assertLessEqual(len(component.encode()), 90)
            self.assertNotIn(component, ('', '.', '..'))

    def test_artwork_rejects_non_image_and_downgrade(self):
        self.patch(rip, 'fetch', return_value=b'<html>not an image</html>')
        self.assertIsNone(rip.artwork({'status': 'matched', 'release_id': RELEASE_ID}))
        with self.assertRaises(ValueError):
            rip.HTTPSRedirect().redirect_request(None, None, 302, '', {}, 'http://example.org/image.jpg')


class Lifecycle(Temporary):
    def setUp(self):
        super().setUp()
        self.patch(rip, 'metadata', return_value=copy.deepcopy(META))
        self.patch(rip, 'artwork', return_value=None)
        self.reader = self.patch(rip, 'read_disc', return_value=copy.deepcopy(TOC))
        self.commands = []
        self.fail_track = None
        self.real_run = rip.run
        self.patch(rip, 'run', self.fake_run)
        if not RUNTIME:
            self.patch(rip, 'tag', lambda *args: None)
        self.logfile = tempfile.TemporaryFile()
        self.addCleanup(self.logfile.close)

    def fake_run(self, args, logfile, timeout=1800):
        self.commands.append(args)
        if args[0] == 'eject':
            return
        if args[0] == 'cdparanoia':
            if int(args[-2]) == self.fail_track:
                raise RuntimeError('damaged track')
            self.assertIn('-X', args)
            self.assertNotIn('-Z', args)
            with wave.open(args[-1], 'wb') as wav:
                wav.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\0' * 44100 * 4)
        elif RUNTIME:
            self.real_run(args, logfile, timeout)
        elif '--test' not in args:
            output = next(a.split('=', 1)[1] for a in args if a.startswith('--output-name='))
            Path(output).write_bytes(b'fLaC fixture bytes')

    def albums(self):
        return [p for p in rip.LIBRARY.glob('*/*/.rip-manifest.json')
                if not p.relative_to(rip.LIBRARY).parts[0].startswith('.')]

    def test_success_duplicate_and_checksums(self):
        rip.process_disc(self.logfile)
        self.assertEqual(len(self.albums()), 1)
        album = self.albums()[0].parent
        self.assertEqual(len(list(album.glob('*.flac'))), 2)
        self.assertEqual(self.commands[-1], ['eject', rip.DEVICE])
        self.commands.clear()
        with patch.object(rip, 'write_json') as writes:
            rip.process_disc(self.logfile)
            writes.assert_not_called()
        self.assertFalse(any(a[0] == 'cdparanoia' for a in self.commands))
        next(album.glob('*.flac')).write_bytes(b'changed')
        self.commands.clear()
        with self.assertRaises(RuntimeError):
            rip.process_disc(self.logfile)
        self.assertNotIn(['eject', rip.DEVICE], self.commands)

    def test_failure_leaves_no_album_and_unlocks_without_eject(self):
        self.fail_track = 2
        with self.assertRaises(RuntimeError):
            rip.process_disc(self.logfile)
        self.assertEqual(self.albums(), [])
        self.assertTrue(list((rip.LIBRARY / '.work').glob('*/*.flac')))
        self.assertTrue((rip.LIBRARY / '.work/.ignore').is_file())
        self.assertEqual(self.commands[-1], ['eject', '-i', 'off', rip.DEVICE])
        self.fail_track = None
        rip.process_disc(self.logfile)
        self.assertEqual(len(self.albums()), 1)

    def test_power_loss_after_manifest_recovers_without_rereading_audio(self):
        write_json = rip.write_json
        def fail_completion(path, value):
            if value.get('status') == 'complete':
                raise OSError('simulated power failure')
            write_json(path, value)
        with patch.object(rip, 'write_json', side_effect=fail_completion):
            with self.assertRaises(OSError):
                rip.import_disc(TOC, self.logfile)
        self.assertEqual(len(self.albums()), 1)
        self.commands.clear()
        rip.import_disc(TOC, self.logfile)
        self.assertEqual(self.commands, [])
        record = next((rip.STATE / 'discs').glob('*.json'))
        self.assertEqual(json.loads(record.read_text())['status'], 'complete')

    def test_disc_swap_low_space_and_existing_directory_never_publish(self):
        self.reader.return_value = dict(TOC, id='replacement')
        with self.assertRaises(RuntimeError):
            rip.import_disc(TOC, self.logfile)
        self.assertEqual(self.albums(), [])
        self.reader.return_value = TOC
        with patch.object(rip.shutil, 'disk_usage', return_value=type('Space', (), {'free': 0})()):
            with self.assertRaises(RuntimeError):
                rip.import_disc(TOC, self.logfile)
        target = rip.LIBRARY / rip.destination(META, rip.disc_key(TOC))
        target.mkdir(parents=True)
        (target / 'keep.txt').write_text('untouched')
        with self.assertRaises(FileNotFoundError):
            rip.import_disc(TOC, self.logfile)
        self.assertEqual((target / 'keep.txt').read_text(), 'untouched')

    def test_existing_empty_album_is_not_taken_over(self):
        target = rip.LIBRARY / rip.destination(META, rip.disc_key(TOC))
        target.mkdir(parents=True)
        with self.assertRaises(FileNotFoundError):
            rip.import_disc(TOC, self.logfile)
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(self.commands, [])

    def test_symlink_escape_and_wrong_wav_length_rejected(self):
        (rip.LIBRARY / 'escape').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            rip.safe_path(rip.LIBRARY, 'escape/file')
        with self.assertRaises(ValueError):
            rip.safe_path(rip.LIBRARY, '../outside')
        path = self.root / 'short.wav'
        with wave.open(str(path), 'wb') as wav:
            wav.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\0' * 4)
        with self.assertRaises(RuntimeError):
            rip.validate_wav(path, 75)

    def test_eject_error_preserves_success_and_never_ejects_replacement(self):
        rip.import_disc(TOC, self.logfile)
        self.reader.side_effect = [TOC, dict(TOC, id='replacement')]
        rip.process_disc(self.logfile)
        self.assertNotIn(['eject', rip.DEVICE], self.commands)
        self.assertEqual(len(self.albums()), 1)

    def test_requested_layout_and_multidisc_append_recovery(self):
        meta = copy.deepcopy(META)
        meta.update(status='matched', release_id=RELEASE_ID, date='2020', disctotal=2)
        for track in meta['tracks']:
            track.update(recording_id=RELEASE_ID, release_track_id=RELEASE_ID)
        with patch.object(rip, 'metadata', return_value=meta):
            rip.import_disc(TOC, self.logfile)
        album = rip.LIBRARY / 'Test Artist/Test Album'
        self.assertTrue((album / '01-01 - First.flac').is_file())
        original_hashes = {p.name: rip.digest(p) for p in album.glob('*.flac')}
        second = dict(TOC, id='disc_two')
        meta['discnumber'] = 2
        self.reader.return_value = second
        write_json = rip.write_json
        def fail_completion(path, value):
            if value.get('status') == 'complete':
                raise OSError('power loss after album publication')
            write_json(path, value)
        with patch.object(rip, 'metadata', return_value=meta), patch.object(rip, 'write_json', side_effect=fail_completion):
            with self.assertRaises(OSError):
                rip.import_disc(second, self.logfile)
        self.assertTrue((album / '02-01 - First.flac').is_file())
        for name, expected in original_hashes.items():
            self.assertEqual(rip.digest(album / name), expected)
        self.commands.clear()
        rip.import_disc(second, self.logfile)
        self.assertEqual(self.commands, [])
        rip.import_disc(TOC, self.logfile)
        self.assertEqual(self.commands, [])
        self.assertEqual(len(rip.verify_manifest(album)['discs']), 2)

    def test_publication_resumes_without_rereading_and_refuses_foreign_files(self):
        real_link = os.link
        count = 0
        def fail_second_link(source, target, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('interrupted publication')
            return real_link(source, target, **kwargs)
        with patch.object(rip.os, 'link', side_effect=fail_second_link):
            with self.assertRaisesRegex(OSError, 'interrupted publication'):
                rip.import_disc(TOC, self.logfile)
        album = rip.LIBRARY / 'Test Artist/Test Album'
        (album / 'foreign.txt').write_text('preserve this')
        with self.assertRaisesRegex(RuntimeError, 'changed during publication'):
            rip.import_disc(TOC, self.logfile)
        self.assertEqual((album / 'foreign.txt').read_text(), 'preserve this')
        (album / 'foreign.txt').unlink()
        self.commands.clear()
        rip.import_disc(TOC, self.logfile)
        self.assertEqual(self.commands, [])
        rip.verify_album(album, rip.disc_key(TOC), 2)
        rip.import_disc(TOC, self.logfile)
        self.assertEqual(self.commands, [])

    def test_multidisc_stages_only_new_tracks_and_preserves_previous_files(self):
        meta = copy.deepcopy(META)
        meta.update(status='matched', release_id=RELEASE_ID, date='2020', disctotal=2)
        for track in meta['tracks']:
            track.update(recording_id=RELEASE_ID, release_track_id=RELEASE_ID)
        with patch.object(rip, 'metadata', return_value=meta):
            rip.import_disc(TOC, self.logfile)
            album = rip.LIBRARY / 'Test Artist/Test Album'
            original = rip.verify_manifest(album)
            second = dict(TOC, id='disc_two')
            meta['discnumber'] = 2
            self.reader.return_value = second
            rip.import_disc(second, self.logfile)
        stages = list((rip.LIBRARY / '.work').glob('*/.rip-manifest.json'))
        self.assertEqual(len(stages), 2)
        for manifest in stages:
            self.assertEqual(len(rip.verify_manifest(manifest.parent)['discs']), 1)
            self.assertEqual(len(list(manifest.parent.glob('*.flac'))), 2)
        final = rip.verify_manifest(album)
        self.assertEqual(len(final['discs']), 2)
        for name, expected in original['files'].items():
            self.assertEqual(final['files'][name], expected)

    def test_interrupted_manifest_write_recovers_without_album_temp_files(self):
        album = rip.LIBRARY / 'Test Artist/Test Album'
        replace = os.replace
        def fail_manifest(source, target):
            if target == album / '.rip-manifest.json':
                raise OSError('interrupted manifest update')
            replace(source, target)
        with patch.object(rip.os, 'replace', side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, 'interrupted manifest'):
                rip.import_disc(TOC, self.logfile)
        self.assertEqual(list(album.glob('*.tmp')), [])
        self.assertTrue(list(rip.STATE.glob('*.tmp')))
        self.commands.clear()
        rip.import_disc(TOC, self.logfile)
        self.assertEqual(self.commands, [])
        rip.verify_album(album, rip.disc_key(TOC), 2)

    def test_missing_previous_disc_file_blocks_multidisc_publication(self):
        meta = copy.deepcopy(META)
        meta.update(status='matched', release_id=RELEASE_ID, date='2020', disctotal=2)
        for track in meta['tracks']:
            track.update(recording_id=RELEASE_ID, release_track_id=RELEASE_ID)
        with patch.object(rip, 'metadata', return_value=meta):
            rip.import_disc(TOC, self.logfile)
            album = rip.LIBRARY / 'Test Artist/Test Album'
            original = (album / '.rip-manifest.json').read_bytes()
            second = dict(TOC, id='disc_two')
            meta['discnumber'] = 2
            self.reader.return_value = second
            publish = rip.publish_album
            def remove_previous_file(stage, target, addition, previous):
                (target / '01-01 - First.flac').unlink()
                publish(stage, target, addition, previous)
            with patch.object(rip, 'publish_album', side_effect=remove_previous_file):
                with self.assertRaisesRegex(RuntimeError, 'missing files'):
                    rip.import_disc(second, self.logfile)
        self.assertEqual((album / '.rip-manifest.json').read_bytes(), original)
        self.assertEqual(list(album.glob('02-*.flac')), [])

    def test_shared_posix_lock_excludes_a_second_process(self):
        self.patch(rip, 'STATE', rip.LIBRARY / '.state')
        rip.STATE.mkdir()
        with (rip.STATE / 'rip.lock').open('a') as lock:
            fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            child = subprocess.run([sys.executable, '-c',
                'import fcntl,sys; f=open(sys.argv[1], "a"); fcntl.lockf(f, fcntl.LOCK_EX|fcntl.LOCK_NB)',
                str(rip.STATE / 'rip.lock')], capture_output=True)
            self.assertNotEqual(child.returncode, 0)
            with patch.object(rip, 'process_disc') as process, patch.object(rip.fcntl, 'lockf', side_effect=BlockingIOError):
                with self.assertRaisesRegex(RuntimeError, 'another extraction'):
                    rip.main()
                process.assert_not_called()

    def test_same_album_title_from_different_release_is_not_merged(self):
        rip.import_disc(TOC, self.logfile)
        other = dict(TOC, id='another_release')
        self.reader.return_value = other
        self.commands.clear()
        with self.assertRaisesRegex(RuntimeError, 'album name collision'):
            rip.import_disc(other, self.logfile)
        self.assertEqual(self.commands, [])
        self.assertEqual(len(self.albums()), 1)

    def test_failed_eject_does_not_invalidate_import(self):
        fake_run = self.fake_run
        def fail_eject(args, logfile, timeout=1800):
            if args == ['eject', rip.DEVICE]:
                raise RuntimeError('USB tray failure')
            fake_run(args, logfile, timeout)
        with patch.object(rip, 'run', side_effect=fail_eject):
            rip.process_disc(self.logfile)
        record = next((rip.STATE / 'discs').glob('*.json'))
        self.assertEqual(json.loads(record.read_text())['status'], 'complete')
        self.assertEqual(len(self.albums()), 1)

    @unittest.skipUnless(RUNTIME, 'real codec test runs inside the runtime image')
    def test_real_tags_pcm_and_cover(self):
        from mutagen.flac import FLAC
        # Valid one-pixel PNG. Embedded in FLAC and also saved alongside the album.
        import base64
        cover = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lZkAAAAASUVORK5CYII=')
        with patch.object(rip, 'artwork', return_value=('png', 'image/png', cover)):
            rip.import_disc(TOC, self.logfile)
        album = self.albums()[0].parent
        path = sorted(album.glob('*.flac'))[0]
        audio = FLAC(path)
        self.assertEqual(audio['album'], ['Test Album'])
        self.assertEqual(audio['artist'], ['Artist One'])
        self.assertEqual(audio['discnumber'], ['1'])
        self.assertEqual(audio.pictures[0].data, cover)
        self.assertEqual(audio.info.sample_rate, 44100)
        self.assertEqual(audio.info.bits_per_sample, 16)
        self.assertEqual(audio.info.total_samples, 44100)
        subprocess.run(['flac', '--silent', '--test', str(path)], check=True)


class Detection(Temporary):
    def setUp(self):
        super().setUp()
        self.patch(dispatch, 'RUNTIME', self.root / 'run')
        self.properties = {'ID_BUS': 'usb', 'ID_MODEL': 'ASUS_BW-16D1HT',
                           'ID_CDROM_MEDIA_CD': '1', 'ID_CDROM_MEDIA_TRACK_COUNT_AUDIO': '16',
                           'DISKSEQ': '12'}
        self.starts = []
        self.state = 'inactive'
        self.patch(dispatch, 'command', self.command)

    def command(self, *args):
        if args[:2] == ('systemctl', 'show'):
            return self.state
        if args[0] == 'udevadm':
            return '\n'.join(k + '=' + v for k, v in self.properties.items())
        self.starts.append(args)
        return ''

    def test_only_target_audio_discs_and_require_generation(self):
        self.assertEqual(dispatch.audio_token(self.properties), '12')
        for field, value in [('ID_BUS', 'sata'), ('ID_MODEL', 'other'),
                             ('ID_CDROM_MEDIA_TRACK_COUNT_DATA', '1'),
                             ('ID_CDROM_MEDIA_TRACK_COUNT_AUDIO', '0'), ('ID_CDROM_MEDIA_CD', '0')]:
            self.assertIsNone(dispatch.audio_token(dict(self.properties, **{field: value})))
        with self.assertRaises(RuntimeError):
            dispatch.audio_token(dict(self.properties, DISKSEQ=''))

    def test_repeat_failed_reinsert_and_explicit_retry(self):
        real_exists = Path.exists
        with patch.object(Path, 'exists', lambda p: True if str(p) == '/dev/sr0' else real_exists(p)):
            dispatch.detect()
            self.state = 'failed'
            dispatch.detect()
            self.assertEqual(len(self.starts), 1)
            self.properties['DISKSEQ'] = '13'
            dispatch.detect()
            self.assertEqual(len(self.starts), 2)
            dispatch.detect(retry=True)
            self.assertEqual(len(self.starts), 3)
            self.state = 'active'
            dispatch.detect(retry=True)
            self.assertEqual(len(self.starts), 3)

    def test_missing_mount_never_creates_library(self):
        self.patch(dispatch, 'MUSIC', self.root / 'unmounted')
        with patch.object(dispatch.os.path, 'ismount', return_value=False):
            with self.assertRaises(RuntimeError):
                dispatch.prepare()
        self.assertFalse(dispatch.MUSIC.exists())

    def test_guest_requires_its_cds_mount_and_numeric_owner(self):
        self.patch(dispatch, 'MUSIC', self.root / 'guest-music')
        (dispatch.MUSIC / 'cds').mkdir(parents=True)
        with patch.object(dispatch.os.path, 'ismount', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'writable cds NFS mount'):
                dispatch.prepare(guest=True)
        with patch.object(dispatch.os.path, 'ismount', return_value=True), patch.object(Path, 'stat', return_value=type('Owner', (), {'st_uid': 1001, 'st_gid': 1001})()), patch.object(Path, 'is_symlink', return_value=False):
            dispatch.prepare(guest=True)
        with patch.object(dispatch.os.path, 'ismount', return_value=True), patch.object(Path, 'stat', return_value=type('Owner', (), {'st_uid': 0, 'st_gid': 0})()), patch.object(Path, 'is_symlink', return_value=False):
            with self.assertRaises(RuntimeError):
                dispatch.prepare(guest=True)

    def test_host_helper_rejects_directory_symlinks(self):
        (self.root / 'cds').symlink_to(self.root / 'STATE', target_is_directory=True)
        with self.assertRaises(OSError):
            dispatch.managed_directory(self.root, 'cds')

    def test_existing_library_is_not_taken_over(self):
        self.patch(dispatch, 'MUSIC', self.root)
        (self.root / 'cds').mkdir()
        (self.root / 'cds/keep').write_text('existing library')
        with patch.object(dispatch.os.path, 'ismount', return_value=True), patch.object(dispatch.os, 'fstat', return_value=type('Owner', (), {'st_uid': 0, 'st_gid': 0})()):
            with self.assertRaises(RuntimeError):
                dispatch.prepare()
        self.assertEqual((self.root / 'cds/keep').read_text(), 'existing library')


if __name__ == '__main__':
    unittest.main()
