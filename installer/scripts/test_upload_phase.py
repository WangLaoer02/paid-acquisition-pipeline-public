"""Cold upload installation must include its default HTTP authentication route."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

class UploadPhaseTests(unittest.TestCase):
    def test_cold_upload_installs_http_dependencies_without_login(self):
        script=Path(__file__).with_name('progressive_install.py')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            result=subprocess.run([sys.executable,'-B',str(script),'--skills-dir',str(root/'skills'),
                '--tool-root',str(root/'tools'),'install','--phase','upload'],capture_output=True,text=True,check=True)
            receipt=json.loads(result.stdout)
            self.assertFalse(receipt['accounts_authorized'])
            self.assertFalse(receipt['business_phase_passed'])
            for name in ['rongyao-http-upload','rongyao-http-readonly','rongyao-operations','rongyao-keyring','rongyao-data-stack']:
                self.assertTrue((root/'skills'/name/'SKILL.md').is_file(),name)

if __name__=='__main__':unittest.main()
