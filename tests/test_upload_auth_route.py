import importlib.util,pathlib,subprocess,sys,unittest,json
from unittest.mock import patch,Mock
ROOT=pathlib.Path(__file__).resolve().parents[1]
WORKER=ROOT/'workflow/rules/implementation/rongyao-tools/skills/rongyao-keyring/scripts/worker.py'
STACK=WORKER.parents[2]/'rongyao-data-stack/scripts';sys.path.insert(0,str(STACK))
class UploadAuthRouteTests(unittest.TestCase):
 def test_upload_recovery_does_not_use_query_only_login(self):
  spec=importlib.util.spec_from_file_location('upload_worker',WORKER);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  import fast_video
  result={'ok':True,'authenticated':True,'entry':'upload','file_selected':False,'upload_performed':False}
  with patch.object(sys,'argv',[str(WORKER),'verify-upload-chrome']),patch.object(fast_video,'prepare',side_effect=AssertionError('query-only login is not upload recovery')),patch.object(fast_video.session,'ensure_active_session') as session,patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(result),'')) as run:
   self.assertTrue(m.main()['authenticated']);session.assert_called_once();run.assert_called_once()
if __name__=='__main__':unittest.main()
