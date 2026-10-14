#!/usr/bin/python3
"""GitLab companion lifecycle, activity, bootstrap and security contracts."""
import copy
import importlib.machinery
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[3]


def module(name,path):
    loader=importlib.machinery.SourceFileLoader(name,str(REPO/path))
    spec=importlib.util.spec_from_loader(name,loader)
    mod=importlib.util.module_from_spec(spec);loader.exec_module(mod)
    return mod


host=module('gitlab_host','images/nas/bin/vm-on-demand')
server=module('gitlab_idle','vms/gitlab/bin/gitlab-idle')
runner=module('runner_idle','vms/gitlab-runner/bin/gitlab-runner-idle')


class Lifecycle(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for key in ('STATE','RUNTIME','CONFIG','UNITS'):
            path=self.root/key;path.mkdir()
            p=patch.object(host,key,path);p.start();self.addCleanup(p.stop)
        self.config=host.validate_inventory(REPO/'vms/inventory.json',['gitlab'])[0]
        for name,value in [('enabled',True),('state','running'),('proxy_busy',False),
                           ('idle_after',True),
                           ('property_of','inactive'),('guest_report',{'version':1,'idle':True,'safe_to_stop':True,'checked_at':time.time()})]:
            p=patch.object(host,name,return_value=value);setattr(self,name,p.start());self.addCleanup(p.stop)
        self.activity=host.RUNTIME/'gitlab.activity';self.activity.write_text(str(time.monotonic()-1900))
        (host.RUNTIME/'gitlab.confirmed-idle').touch()

    def test_housekeeping_blocks_shutdown_without_restarting_idle_clock(self):
        self.guest_report.side_effect=[{'idle':True,'safe_to_stop':False},{'idle':True}]
        before=self.activity.read_text()
        with patch.object(host,'shutdown') as stop:
            host.idle_one(self.config);stop.assert_not_called()
        self.assertEqual(before,self.activity.read_text())

    def test_running_or_pending_job_restarts_full_quiet_interval(self):
        for server_idle,worker_idle in [(False,True),(True,False)]:
            self.guest_report.side_effect=[{'idle':server_idle,'safe_to_stop':True},{'idle':worker_idle}]
            with patch.object(host,'shutdown') as stop:
                host.idle_one(self.config);stop.assert_not_called()
            self.assertLess(time.monotonic()-float(self.activity.read_text()),1)

    def test_worker_shutdown_precedes_server(self):
        with patch.object(host,'shutdown') as stop:
            host.idle_one(self.config)
            self.assertEqual([c.args[0]['name'] for c in stop.call_args_list],['gitlab-runner','gitlab'])

    def test_new_request_after_drain_restarts_worker(self):
        self.idle_after.return_value=False
        with patch.object(host,'shutdown') as stop,patch.object(host,'start') as start:
            host.idle_one(self.config)
            self.assertEqual(stop.call_args.args[0]['name'],'gitlab-runner')
            self.assertEqual(stop.call_count,1);start.assert_called_once_with(self.config)

    def test_worker_timeout_never_stops_server(self):
        with patch.object(host,'shutdown',side_effect=RuntimeError('timeout')) as stop:
            with self.assertRaises(RuntimeError):host.idle_one(self.config)
            self.assertEqual(stop.call_count,1)
        self.assertTrue((host.RUNTIME/'gitlab.draining').exists())

    def test_new_queue_after_worker_stopped_recovers_worker(self):
        (host.RUNTIME/'gitlab.draining').touch()
        self.state.side_effect=lambda n:'running' if n=='gitlab' else 'shut off'
        self.guest_report.return_value={'idle':False,'safe_to_stop':False}
        with patch.object(host,'start') as start:
            host.idle_one(self.config);start.assert_called_once_with(self.config)

    def test_absent_companion_is_not_idle(self):
        self.state.side_effect=lambda n:'running' if n=='gitlab' else 'shut off'
        with self.assertRaises(ValueError):host.group_report(self.config)

    def test_backup_hold_prevents_any_probe(self):
        (host.STATE/'gitlab.hold').touch();host.idle_one(self.config)
        self.guest_report.assert_not_called()

    def test_sleeping_pair_is_never_probed_or_woken(self):
        self.state.return_value='shut off'
        with patch.object(host,'start') as start:
            host.idle_one(self.config);start.assert_not_called()
        self.guest_report.assert_not_called()

    def test_nightly_waits_for_either_member_even_without_enabled_listeners(self):
        with patch.object(host,'virsh',return_value='gitlab\ngitlab-runner'):
            for busy in ('gitlab','gitlab-runner'):
                self.state.side_effect=lambda n:'running' if n==busy else 'shut off'
                self.assertFalse(host.nightly_ready())
            self.state.side_effect=None;self.state.return_value='shut off'
            self.assertTrue(host.nightly_ready())

    def test_wake_during_drain_keeps_recovery_marker(self):
        marker=host.RUNTIME/'gitlab.draining';marker.touch()
        with patch.object(host,'virsh'):
            host.start(self.config)
        self.assertTrue(marker.exists())

    def test_start_orders_server_before_worker(self):
        self.state.return_value='shut off'
        with patch.object(host,'virsh') as virsh:
            host.start(self.config)
        self.assertEqual([c.args for c in virsh.call_args_list],[('start','gitlab'),('start','gitlab-runner')])


class Activity(unittest.TestCase):
    def test_post_drain_report_must_start_after_worker_stops(self):
        before={'idle':True,'safe_to_stop':True,'sampled_at':99,'checked_at':101}
        after={**before,'sampled_at':102,'checked_at':103}
        with patch.object(host,'guest_report',side_effect=[before,after]) as report, \
             patch.object(host,'proxy_busy',return_value=False),patch.object(host.time,'sleep'):
            self.assertTrue(host.idle_after({'name':'gitlab'},100))
            self.assertEqual(report.call_count,2)
        for evidence in ({**after,'idle':False}, {**after,'safe_to_stop':False},
                         {**after,'sampled_at':None}):
            with patch.object(host,'guest_report',return_value=evidence), \
                 patch.object(host,'proxy_busy',return_value=False):
                self.assertFalse(host.idle_after({'name':'gitlab'},100))
        with patch.object(host,'proxy_busy',return_value=True),patch.object(host,'guest_report') as report:
            self.assertFalse(host.idle_after({'name':'gitlab'},100))
            report.assert_not_called()
        with patch.object(host.time,'monotonic',side_effect=[0,111]):
            self.assertFalse(host.idle_after({'name':'gitlab'},100))

    def test_queued_jobs_and_child_pipelines_prevent_idle(self):
        paths=[]
        def pages(path):
            paths.append(path)
            return [{'id':1}] if path=='/api/v4/projects?simple=true' else []
        self.assertTrue(server.ci_idle(pages))
        for busy in ('/jobs?', '/pipelines?status=pending',
                     '/pipelines?status=running&source=parent_pipeline'):
            def active(path):
                return [{'id':2}] if busy in path else pages(path)
            self.assertFalse(server.ci_idle(active))
        self.assertFalse(any('status=scheduled' in p or 'status=manual' in p for p in paths))

    def test_sidekiq_busy_and_queued_work_are_not_safe(self):
        value={'queues':{'default':{'backlog':0}},'processes':[{'busy':0}],'jobs':{'enqueued':0}}
        self.assertTrue(server.sidekiq_idle(value))
        for key in ('backlog','busy','enqueued'):
            data=copy.deepcopy(value)
            target=data['queues']['default'] if key=='backlog' else data['processes'][0] if key=='busy' else data['jobs']
            target[key]=1;self.assertFalse(server.sidekiq_idle(data))
        value['processes']=[]
        with self.assertRaises(ValueError):server.sidekiq_idle(value)

    def test_runner_metrics_require_complete_nonnegative_evidence(self):
        self.assertTrue(runner.metrics_idle('gitlab_runner_jobs{executor_stage="idle",stage="idle",state="idle"} 0'))
        self.assertTrue(runner.metrics_idle('gitlab_runner_jobs{state="running"} 0'))
        self.assertFalse(runner.metrics_idle('gitlab_runner_jobs{state="running"} 1'))
        for text in ('', 'gitlab_runner_jobs -1', 'gitlab_runner_jobs NaN'):
            with self.assertRaises(ValueError):runner.metrics_idle(text)

    def test_runner_control_api_bypasses_nas_encrypted_wake_listener(self):
        caddy=(REPO/'vms/gitlab/frontend/Caddyfile').read_text()
        self.assertIn('https://gitlab.vm:8443',caddy)
        self.assertIn('handle /api/v4/*',caddy)
        self.assertIn('reverse_proxy http://127.0.0.1:8080',caddy)
        self.assertNotIn('nas.vm',caddy)
        self.assertNotIn('health_uri',caddy)
        runner=(REPO/'vms/gitlab-runner/config.toml').read_text()
        self.assertIn('url = "https://gitlab.vm:8443"',runner)
        self.assertIn('clone_url = "https://git.vm:8443"',runner)
        config=host.validate_inventory(REPO/'vms/inventory.json',['gitlab'])[0]
        self.assertEqual([(e['listen_port'],e['guest_port']) for e in config['endpoints']],[(8443,8443),(2222,2222)])
        rendered=''.join(host.render(config).values())
        self.assertIn('gitlab.vm:8443',rendered)
        self.assertNotIn('caddy',rendered)

    def test_pins_storage_and_secret_contracts(self):
        quadlet=(REPO/'vms/gitlab/containers/gitlab.container').read_text()
        self.assertRegex(quadlet,r'Image=.*:19\.4\.2-ce\.0@sha256:[0-9a-f]{64}')
        self.assertNotIn('Privileged=true',quadlet)
        self.assertNotIn('label=disable',quadlet)
        for mount in ('config','data','logs'):
            self.assertIn('Volume=/var/lib/gitlab/'+mount+':',quadlet)
        for role in ('gitlab','gitlab-runner'):
            backup=(REPO/f'vms/{role}/containers/{role}-backups.volume').read_text()
            self.assertIn('Type=nfs',backup);self.assertIn(',hard,',backup)
        unit=(REPO/'vms/gitlab-runner/gitlab-runner.service').read_text()
        for setting in ('KillSignal=SIGQUIT','SendSIGKILL=no','TimeoutStopSec=infinity','user@1011.service'):
            self.assertIn(setting,unit)

    def test_bootstrap_secret_persists_and_upgrade_requires_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=root/'state';version=root/'version';version.write_text('19.4.2\n');(root/'gitlab.rb').write_text('# fixture')
            script=(REPO/'vms/gitlab/bin/gitlab-prepare').read_text().replace('/var/lib/gitlab',str(state)).replace('/usr/share/gitlab/version',str(version)).replace('/usr/share/gitlab/gitlab.rb',str(root/'gitlab.rb')).replace('/var/lib/infrastructure/backup/gitlab',str(root/'backup'))
            def prepare():return subprocess.run(['bash','-c',script],capture_output=True)
            self.assertEqual(prepare().returncode,0)
            secret=(state/'config/bootstrap-password').read_bytes()
            self.assertEqual(prepare().returncode,0)
            self.assertEqual(secret,(state/'config/bootstrap-password').read_bytes())
            self.assertEqual((state/'config/bootstrap-password').stat().st_mode&0o777,0o600)
            (state/'version').write_text('19.3.5\n')
            self.assertNotEqual(prepare().returncode,0)
            (state/'upgrade-approved').write_text('19.3.5 19.4.2\n')
            self.assertNotEqual(prepare().returncode,0)
            (root/'backup').mkdir();(root/'backup/version').write_text('19.3.5\n');(root/'backup/completed').write_text('complete')
            self.assertEqual(prepare().returncode,0)


class Backup(unittest.TestCase):
    def test_server_bundle_restores_frontend_ca_and_refuses_missing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bindir=root/'bin';bindir.mkdir()
            role=root/'gitlab';(role/'config').mkdir(parents=True)
            (role/'data/backups').mkdir(parents=True)
            (role/'config/gitlab-secrets.json').write_text('fixture application secret')
            (role/'version').write_text('19.4.2\n')
            ca=role/'frontend/data/caddy/pki/authorities/local';ca.mkdir(parents=True)
            (ca/'root.crt').write_text('fixture public CA')
            (ca/'root.key').write_text('fixture private CA');(ca/'root.key').chmod(0o600)
            export=root/'export';export.mkdir()
            stub='''#!/usr/bin/python3
import io,os,sys,tarfile
from pathlib import Path
a=sys.argv[1:];n=Path(sys.argv[0]).name
if n=='gitlab-idle': print('{"idle": true}')
if n=='findmnt': print('nfs4')
if n=='podman':
    if a[:2]==['volume','inspect']: print('nfs')
    if a[:2]==['volume','mount']: print(os.environ['EXPORT'])
    if a[:3]==['exec','gitlab','gitlab-backup']:
        backup=a[-1].split('=',1)[1]
        with tarfile.open(Path(os.environ['ROLE'])/'data/backups'/(backup+'_gitlab_backup.tar'),'w') as tar:
            item=tarfile.TarInfo('fixture');item.size=3;tar.addfile(item,io.BytesIO(b'app'))
'''
            for name in ('gitlab-idle','findmnt','podman','systemctl'):
                p=bindir/name;p.write_text(stub);p.chmod(0o755)
            body=(REPO/'vms/vm/bin/gitlab-backup').read_text().replace('/var/lib/infrastructure/backup',str(root/'state'))
            body=body.replace('/var/lib/gitlab',str(role)).replace('/usr/libexec/infrastructure/gitlab-idle',str(bindir/'gitlab-idle'))
            body=body.replace('os.setgroups([]); os.setgid(uid); os.setuid(uid)', 'pass # isolated unprivileged fixture')
            env={**os.environ,'PATH':str(bindir)+':'+os.environ['PATH'],'ROLE':str(role),'EXPORT':str(export)}
            result=subprocess.run(['bash','-c',body,'--','gitlab','prepare'],env=env,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            saved=(export/'backup.tar').read_bytes()
            restored=root/'restore';restored.mkdir()
            subprocess.run(['tar','-xf',str(export/'backup.tar'),'-C',str(restored)],check=True)
            subprocess.run(['sha256sum','--check','SHA256SUMS'],cwd=restored,check=True,capture_output=True)
            restored_ca=restored/'frontend/data/caddy/pki/authorities/local'
            self.assertEqual((restored_ca/'root.key').read_text(),'fixture private CA')
            self.assertEqual((restored_ca/'root.key').stat().st_mode&0o777,0o600)
            (ca/'root.crt').unlink()
            result=subprocess.run(['bash','-c',body,'--','gitlab','prepare'],env=env,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((export/'backup.tar').read_bytes(),saved)
            self.assertTrue((root/'state/gitlab/prepared').exists())
            self.assertFalse((root/'state/gitlab/completed').exists())

    def test_export_failure_retains_previous_bundle_and_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bindir=root/'bin';bindir.mkdir()
            export=root/'export';export.mkdir();(export/'backup.tar').write_text('previous')
            config=root/'config';config.mkdir();(config/'config.toml').write_text('fixture-token')
            stub = """#!/usr/bin/python3
import os,sys
from pathlib import Path
a=sys.argv[1:];n=Path(sys.argv[0]).name
if n=='systemctl' and 'show' in a: print(os.environ.get('RUNNER_STATE','inactive'))
if n=='gitlab-runner': print('Version: 19.4.1')
if n=='podman':
    if a[:2]==['volume','inspect']: print('nfs')
    if a[:2]==['volume','mount']: print(os.environ['EXPORT'])
if n=='findmnt': print(os.environ.get('FSTYPE','nfs4'))
if n=='cat':
    if os.environ.get('FAIL')=='transfer' and len(a)==0: sys.exit(1)
    os.execv('/usr/bin/cat',['cat',*a])
"""
            for name in ('systemctl','gitlab-runner','podman','findmnt','cat'):
                p=bindir/name;p.write_text(stub);p.chmod(0o755)
            body=(REPO/'vms/vm/bin/gitlab-backup').read_text().replace('/var/lib/infrastructure/backup',str(root/'state')).replace('/etc/gitlab-runner',str(config))
            body=body.replace('os.setgroups([]); os.setgid(uid); os.setuid(uid)', 'pass # unprivileged test fixture')
            env={**os.environ,'PATH':str(bindir)+':'+os.environ['PATH'],'EXPORT':str(export)}
            for failure in ({'FAIL':'transfer'},{'FSTYPE':'ext4'},{'RUNNER_STATE':'deactivating'}):
                result=subprocess.run(['bash','-c',body,'--','gitlab-runner','prepare'],env={**env,**failure},capture_output=True)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual((export/'backup.tar').read_text(),'previous')
                self.assertTrue((root/'state/gitlab-runner/prepared').exists())
                self.assertFalse((root/'state/gitlab-runner/completed').exists())
            result=subprocess.run(['bash','-c',body,'--','gitlab-runner','prepare'],env=env,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            self.assertTrue((root/'state/gitlab-runner/completed').exists())
            self.assertTrue((root/'state/gitlab-runner/prepared').exists())
            subprocess.run(['tar','-tf',str(export/'backup.tar')],check=True,capture_output=True)
            subprocess.run(['bash','-c',body,'--','gitlab-runner','finish'],env=env,check=True)
            self.assertFalse((root/'state/gitlab-runner/prepared').exists())


class Worker(unittest.TestCase):
    def test_disk_pressure_or_leftover_container_refuses_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            stub='''#!/usr/bin/python3
import os,sys
from pathlib import Path
n=Path(sys.argv[0]).name
if n=='id': print('1011')
if n=='stat': print('cgroup2fs')
if n=='df': print('Avail\\n'+os.environ.get('FREE',str(50*1024**3)))
if n=='podman': print(os.environ.get('CONTAINER',''))
'''
            for name in ('id','stat','df','podman','buildah','skopeo','git','git-lfs','jq','xorriso','cosign'):
                p=root/name;p.write_text(stub);p.chmod(0o755)
            env={**os.environ,'PATH':str(root)+':'+os.environ['PATH']}
            script=REPO/'vms/gitlab-runner/bin/gitlab-runner-preflight'
            self.assertEqual(subprocess.run(['bash',str(script)],env=env,capture_output=True).returncode,0)
            for failure in ({'FREE':str(39*1024**3)},{'CONTAINER':'leftover-container'}):
                self.assertNotEqual(subprocess.run(['bash',str(script)],env={**env,**failure},capture_output=True).returncode,0)


class Publishing(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.bin=self.root/'bin';self.bin.mkdir()
        for name in ['justfile','online.just']:shutil.copy(REPO/name,self.root/name)
        stub="""#!/usr/bin/python3
import os,sys
from pathlib import Path
n=Path(sys.argv[0]).name
with open(os.environ['CALLS'],'a') as f:f.write(n+' '+' '.join(sys.argv[1:])+'\\n')
if n=='curl':print('{"id":"'+os.environ.get('HEAD_SHA','fixture')+'"}')
if n=='skopeo' and 'inspect' in sys.argv:print(os.environ.get('ARCH','amd64'))
if n=='buildah':Path(os.environ['REGISTRY_AUTH_FILE']).write_text('{}')
if n=='cosign' and os.environ.get('SIGN_FAIL')=='1':sys.exit(1)
"""
        for name in ['curl','skopeo','buildah','cosign']:
            p=self.bin/name;p.write_text(stub);p.chmod(0o755)
        state=self.root/'dist/online/state/stable/fixture';state.mkdir(parents=True)
        for name in ['ips','policy','workstation','sway','nas','vm','k3s','minecraft','jellyfin','immich','audiomuse','gitlab','gitlab-runner']:
            (state/(name+'-amd64.digest')).write_text('sha256:'+'a'*64)
        for name in ['key','pub']:(self.root/name).write_text('fixture')
        self.env={**os.environ,'PATH':str(self.bin)+':'+os.environ['PATH'],'XDG_RUNTIME_DIR':str(self.root),
                  'CI_SERVER_HOST':'git.vm','CI_COMMIT_REF_PROTECTED':'true','COSIGN_KEY':str(self.root/'key'),
                  'COSIGN_PUBLIC_KEY':str(self.root/'pub'),'CI_DEFAULT_BRANCH':'main','CI_COMMIT_SHA':'fixture',
                  'CI_JOB_TOKEN':'fixture','CI_API_V4_URL':'https://git.vm:8443/api/v4','CI_PROJECT_ID':'1',
                  'CI_REGISTRY_PASSWORD':'fixture','CI_REGISTRY_USER':'fixture','CI_REGISTRY':'git-registry.vm:8443',
                  'CI_REGISTRY_IMAGE':'git-registry.vm:8443/infrastructure','PIPELINE_RUN_ID':'fixture','CALLS':str(self.root/'calls')}

    def publish(self,**env):
        executable=os.environ.get('TEST_JUST') or shutil.which('just')
        if not executable:
            self.fail('Run through just check-vm or set TEST_JUST to the Just executable')
        result=subprocess.run([executable,'--justfile',str(self.root/'justfile'),'online::local-publish'],env={**self.env,**env},capture_output=True,text=True)
        calls=(self.root/'calls').read_text() if (self.root/'calls').exists() else ''
        return result,calls

    def test_signatures_are_verified_before_all_amd64_tags_are_promoted(self):
        result,calls=self.publish();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls.count('cosign sign '),13)
        self.assertEqual(calls.count('cosign verify '),13)
        self.assertEqual(calls.count('skopeo copy '),13)
        self.assertLess(calls.rfind('cosign verify '),calls.index('skopeo copy '))
        self.assertNotIn(':latest',calls);self.assertNotIn('manifest',calls)

    def test_wrong_architecture_failed_signature_or_missing_key_cannot_promote(self):
        for env in [{'ARCH':'arm64'},{'SIGN_FAIL':'1'},{'COSIGN_KEY':'/missing'}]:
            (self.root/'calls').unlink(missing_ok=True)
            result,calls=self.publish(**env)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('skopeo copy ',calls)

    def test_stale_revision_skips_publication(self):
        result,calls=self.publish(HEAD_SHA='newer')
        self.assertEqual(result.returncode,0)
        self.assertNotIn('cosign sign ',calls);self.assertNotIn('skopeo copy ',calls)


if __name__=='__main__':unittest.main()
