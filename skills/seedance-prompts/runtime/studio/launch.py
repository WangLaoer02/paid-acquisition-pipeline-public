"""Start this optional local workbench; never replace another service or DB."""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
from configuration import BASE, DB, PORT

URL = f'http://127.0.0.1:{PORT}/'

def running():
    try:
        with urllib.request.urlopen(URL + 'api/runtime', timeout=2) as response:
            info = json.load(response)
    except urllib.error.HTTPError:
        raise SystemExit('STUDIO_PORT_OCCUPIED: existing service has no compatible runtime identity; keep it running and choose another configured port')
    except (OSError, ValueError):
        return False
    if info.get('schema') != 'seedance.runtime.v1' or info.get('db') != str(DB) or info.get('runtime') != str(BASE):
        raise SystemExit('STUDIO_RUNTIME_MISMATCH: existing service uses another runtime/database; no replacement attempted')
    return True

if __name__ == '__main__':
    if running():
        print(URL)
        sys.exit(0)
    DB.parent.mkdir(parents=True, exist_ok=True)
    log_path = DB.parent / 'server.log'
    with log_path.open('ab') as log:
        process = subprocess.Popen([sys.executable, str(BASE / 'serve.py'), '--port', str(PORT)],
                                   cwd=BASE, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True)
    for _ in range(40):
        if process.poll() is not None:
            break
        if running():
            print(URL)
            sys.exit(0)
        time.sleep(.1)
    raise SystemExit('STUDIO_START_FAILED: inspect ' + str(log_path))
