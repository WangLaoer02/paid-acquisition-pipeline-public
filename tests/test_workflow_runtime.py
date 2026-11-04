import contextlib,hashlib,json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import workflow_runtime as rt
import receiver_config

class RuntimeGuardTests(unittest.TestCase):
    def temp_runtime(self):
        td=tempfile.TemporaryDirectory(dir=ROOT);root=Path(td.name)
        policy={'schema_version':1,'release_id':'TEST','writer_hosts':['writer.local'],'local_lock_timeout_seconds':0,
        'circuit':{'failure_threshold':2,'window_seconds':600,'cooldown_seconds':900},
        'authorization':{'directory':'workflow/authorizations','max_lifetime_minutes':120,'high_risk_actions':['paid_generation','material_upload','ad_publish']},
        'event_log':{'directory':'evidence/events','format':'jsonl'},
        'dependency_profiles':{'state_sync':{'executables':[],'python_imports':[]},'paid_generation':{'executables':[],'python_imports':[]},'material_upload':{'executables':[],'python_imports':[]},'ad_publish':{'unsupported':True}}}
        (root/'receiver.local.json').write_text(json.dumps({'schema_version':1,'writer_host':'writer.local'}))
        (root/'workflow').mkdir();(root/'workflow/runtime-policy.json').write_text(json.dumps(policy));(root/'workflow/rules').mkdir();(root/'workflow/rules/manifest.json').write_text(json.dumps({'release_id':'TEST'}))
        return td,root
    def patch_root(self,root):
        stack=contextlib.ExitStack()
        stack.enter_context(patch.object(receiver_config,'ROOT',root))
        stack.enter_context(patch.object(rt,'ROOT',root));stack.enter_context(patch.object(rt,'POLICY_PATH',root/'workflow/runtime-policy.json'));stack.enter_context(patch.object(rt,'RUNTIME',root/'workflow/runtime'));stack.enter_context(patch.object(rt,'LOCKS',root/'workflow/runtime/locks'));stack.enter_context(patch.object(rt,'CIRCUITS',root/'workflow/runtime/circuits.json'));stack.enter_context(patch.object(rt,'AUTH_LEDGER',root/'workflow/runtime/authorization-ledger.json'));stack.enter_context(patch.object(rt,'host',return_value='writer.local'))
        return stack
    def test_wrong_machine_is_read_only(self):
        td,root=self.temp_runtime()
        try:
          with self.patch_root(root),patch.object(rt,'host',return_value='other.local'):
            with self.assertRaisesRegex(ValueError,'WRITER_HOST_REQUIRED'):rt.ensure_writer('state_sync')
        finally:td.cleanup()
    def test_scope_lock_rejects_second_session(self):
        td,root=self.temp_runtime()
        try:
          with self.patch_root(root):
            with rt.lock('same-scope','state_sync'):
              with self.assertRaisesRegex(ValueError,'WORKFLOW_LOCKED'):
                with rt.lock('same-scope','state_sync'):pass
        finally:td.cleanup()
    def test_ticket_is_input_bound_and_single_use(self):
        td,root=self.temp_runtime()
        try:
          with self.patch_root(root):
            p,t=rt.create_ticket('paid_generation','scope','a'*64,'current-user-message',30)
            rt.authorization(p,'paid_generation','scope','a'*64,True)
            with self.assertRaisesRegex(ValueError,'already reserved'):rt.authorization(p,'paid_generation','scope','a'*64,True)
        finally:td.cleanup()
    def test_wrong_input_does_not_reserve_reviewed_ticket(self):
        td,root=self.temp_runtime()
        try:
          with self.patch_root(root):
            p,t=rt.create_ticket('material_upload','scope','a'*64,'current-user-message',30)
            with self.assertRaisesRegex(ValueError,'input hash differs'):
                rt.authorization(p,'material_upload','scope','b'*64,True)
            self.assertFalse(rt.AUTH_LEDGER.exists())
            rt.authorization(p,'material_upload','scope','a'*64,True)
        finally:td.cleanup()
    def test_interrupted_mutation_keeps_ticket_reserved_for_original_operation(self):
        td,root=self.temp_runtime()
        try:
          with self.patch_root(root),patch.object(rt,'ensure_release',return_value={'release_id':'TEST'}):
            p,t=rt.create_ticket('material_upload','scope','a'*64,'current-user-message',30)
            sends=[]
            with self.assertRaises(subprocess.TimeoutExpired):
                with rt.mutation('material_upload','scope',p,'a'*64):
                    sends.append('isolated-send')
                    raise subprocess.TimeoutExpired('isolated-transport',1)
            # The second entry reloads the on-disk ledger, as a restarted CLI does.
            with self.assertRaisesRegex(ValueError,'already reserved'):
                with rt.mutation('material_upload','scope',p,'a'*64):
                    sends.append('duplicate-send')
            self.assertEqual(sends,['isolated-send'])
            self.assertIn(t['ticket_id'],rt.load(rt.AUTH_LEDGER)['tickets'])
        finally:td.cleanup()
    def test_circuit_opens_after_two_same_scope_failures(self):
        td,root=self.temp_runtime()
        try:
          with self.patch_root(root):
            rt.record_failure('material_upload','scope','network','timeout one');rt.record_failure('material_upload','scope','network','timeout two')
            with self.assertRaisesRegex(ValueError,'CIRCUIT_OPEN'):rt.check_circuit('material_upload','scope')
        finally:td.cleanup()
    def test_unsupported_publish_is_machine_blocked(self):
        td,root=self.temp_runtime()
        try:
          with self.patch_root(root):
            with self.assertRaisesRegex(ValueError,'ACTION_UNSUPPORTED'):rt.dependencies('ad_publish')
        finally:td.cleanup()
    def test_event_is_jsonl_and_redacts_secret_keys(self):
        td,root=self.temp_runtime()
        try:
          with self.patch_root(root):
            rt.event('state_sync','verified','scope',token='secret',input_sha256='a'*64)
            p=next((root/'evidence/events').glob('*.jsonl'));row=json.loads(p.read_text().strip())
            self.assertEqual(row['details']['token'],'[REDACTED]');self.assertEqual(row['details']['input_sha256'],'a'*64)
        finally:td.cleanup()
if __name__=='__main__':unittest.main()
