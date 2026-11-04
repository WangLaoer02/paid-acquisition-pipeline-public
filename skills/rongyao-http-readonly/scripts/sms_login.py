"""Invoke the existing native Keychain helper for one bounded SMS login."""
import fcntl,json,os,subprocess,sys,tempfile
from pathlib import Path
BASE=Path.home()/'.codex/state/rongyao-http'
SOURCE=Path(__file__).resolve().parent
KEYRING=Path.home()/'.codex/skills/rongyao-keyring/scripts'

def launch(output_dir,lifetime=86400,service="readonly",restore_existing=True):
    if service not in ("readonly","upload"):raise ValueError("UNKNOWN_HTTP_SERVICE")
    uploader=Path.home()/".codex/skills/rongyao-http-upload/scripts"
    if service=="upload" and not (uploader/"upload_service.py").is_file():raise ValueError("UPLOAD_EXTENSION_NOT_INSTALLED")
    from session_store import restore_service
    restored=restore_service(output_dir,lifetime,service) if restore_existing else None
    if restored:
        print(json.dumps(restored,ensure_ascii=False),flush=True)
        return 0
    from sms_receiver import baseline
    # Check both prerequisites before sending a code or touching the helper.
    baseline()
    output=Path(output_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    BASE.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(BASE,0o700)
    with open(BASE/'sms-login.lock','a') as lock:
        os.chmod(BASE/'sms-login.lock',0o600)
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        worker=KEYRING/'worker.py';cli=KEYRING/'keyring.py';module=KEYRING/'otp_worker_once.py'
        original=worker.read_bytes();cli_original=cli.read_bytes()
        old='    import fast_video\n    command, *args = sys.argv[1:]\n'
        new="    command, *args = sys.argv[1:]\n    if command == 'ensure-query' and args == ['--http-code-login-once']:\n        import otp_worker_once\n        return otp_worker_once.run()\n    import fast_video\n"
        cli_old='        sub.add_parser(name)\n'
        cli_new="        command_parser = sub.add_parser(name)\n        if name == 'ensure-query':\n            command_parser.add_argument('--http-code-login-once', action='store_true')\n"
        if original.decode().count(old)!=1 or cli_original.decode().count(cli_old)!=1:raise ValueError('KEYRING_STRUCTURE_CHANGED')
        if module.exists():raise ValueError('PENDING_LOCAL_OTP_WORKER')
        patched=original.decode().replace(old,new).encode();cli_patched=cli_original.decode().replace(cli_old,cli_new).encode()
        with tempfile.TemporaryDirectory(prefix='sms-login-',dir=BASE) as private_dir:
            private=Path(private_dir)
            for name,data in [('worker-original.py',original),('cli-original.py',cli_original)]:
                path=private/name;path.write_bytes(data);path.chmod(0o600)
            header='from pathlib import Path\n'+''.join(f'{name}=Path({str(value)!r})\n' for name,value in [('SOURCE',SOURCE),('OUTPUT',output),('KEYRING',KEYRING),('PRIVATE',private)])+f'LIFETIME={int(lifetime)}\nSERVICE_KIND={service!r}\nUPLOAD_SOURCE=Path({str(uploader)!r})\n'
            try:
                module.write_text(header+(SOURCE/'sms_worker.py').read_text());module.chmod(0o600)
                worker.write_bytes(patched);cli.write_bytes(cli_patched)
                return subprocess.run([sys.executable,str(cli),'ensure-query','--http-code-login-once'],timeout=215).returncode
            finally:
                if worker.read_bytes() in (original,patched):worker.write_bytes(original)
                if cli.read_bytes() in (cli_original,cli_patched):cli.write_bytes(cli_original)
                module.unlink(missing_ok=True)

def bind_source(rowid):
    """Explicit per-Mac enrollment from one owner-selected known login SMS."""
    import hashlib
    from sms_receiver import connect,PATTERN
    with connect() as db:
        row=db.execute('SELECT h.id,m.text FROM message m JOIN handle h ON h.ROWID=m.handle_id WHERE m.ROWID=? AND m.is_from_me=0',(rowid,)).fetchone()
    if not row or not row[0] or not PATTERN.fullmatch((row[1] or '').strip()):raise ValueError('SMS_SOURCE_NOT_MATCHED')
    BASE.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(BASE,0o700)
    path=BASE/'sms-source.json';path.write_text(json.dumps({'sender_sha256':hashlib.sha256(row[0].encode()).hexdigest(),'signature':'炽焰网络','purpose':'rongyao_backend_login_only'}));path.chmod(0o600)
    return {'ok':True,'status':'SMS_SOURCE_BOUND','code_printed':False}
