import subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class UploadHardGateCLITests(unittest.TestCase):
    def assert_ticket_required(self,script,args):
        r=subprocess.run([sys.executable,str(ROOT/script),*args],cwd=ROOT,capture_output=True,text=True,timeout=8)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('authorization-ticket',(r.stderr+r.stdout).lower())

    def test_material_upload_upload_requires_ticket(self):
        self.assert_ticket_required('scripts/material_upload.py',['upload','--contract','x','--mapping','x','--plan','x','--output','x'])
    def test_material_upload_batch_requires_ticket(self):
        self.assert_ticket_required('scripts/material_upload.py',['batch','--jobs','x','--output','x'])
    def test_native_upload_requires_ticket(self):
        self.assert_ticket_required('scripts/rongyao_material_upload.py',['upload','--plan','x','--output','x'])
    def test_native_batch_requires_ticket(self):
        self.assert_ticket_required('scripts/rongyao_material_upload.py',['batch','--plans','x','--output','x'])
    def test_checked_execute_requires_ticket(self):
        self.assert_ticket_required('scripts/rongyao_checked_upload.py',['execute','--queue','x','--user-id','1','--display-name','u','--output-dir','x'])
    def test_checked_execute_single_requires_ticket(self):
        self.assert_ticket_required('scripts/rongyao_checked_upload.py',['execute-single','--queue','x','--request-file','x','--display-name','u','--output-dir','x'])

if __name__=='__main__':
    unittest.main()
