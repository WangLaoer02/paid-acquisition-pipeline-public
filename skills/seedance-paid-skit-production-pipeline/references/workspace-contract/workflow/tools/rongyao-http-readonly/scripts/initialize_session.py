"""One-time local manual SMS initialization, using the existing trusted login worker."""
import json
import hashlib
from pathlib import Path
import sys

SOURCE=Path(__file__).resolve().parent


def worker_source():
    text=(SOURCE/'sms_worker.py').read_text()
    old=' from sms_receiver import baseline,receive\n'
    replacement=''' def baseline(): return 0
 def receive(after_rowid,requested_at):
  import subprocess
  script='text returned of (display dialog "荣耀后台免重复登录初始化：请输入刚收到的本次六位短信验证码。仅用于建立本机钥匙串会话，不会上传视频。" default answer "" with hidden answer buttons {"取消", "继续"} default button "继续" giving up after 150)'
  reply=subprocess.run(['/usr/bin/osascript','-e',script],capture_output=True,text=True,timeout=155)
  code=reply.stdout.strip()
  if reply.returncode or not re.fullmatch(r'[0-9]{6}',code):raise ValueError('LOCAL_MANUAL_CODE_CANCELLED_OR_INVALID')
  return code
'''
    if text.count(old)!=1:raise ValueError('INITIALIZE_AUTH_SOURCE_CHANGED')
    text=text.replace(old,replacement).replace('existing_keychain_password_and_fresh_sms',
                                              'existing_keychain_password_and_manual_sms')
    text=text.replace('code_received_locally','code_received_manually')
    text=text.replace('验证码已发送，正在从本机信息自动接收。无需手动填写。',
                      '验证码已发送，请在本机安全输入窗口填写本次验证码。')
    compile(text,'local-session-initializer','exec')
    return text


def initialize(output_dir,scope):
    # This explicit auth-only setup does not manufacture an upload batch or grant upload rights.
    manifest=json.loads((SOURCE.parent/'manifest.json').read_text())
    if any(hashlib.sha256((SOURCE.parent/name).read_bytes()).hexdigest()!=digest
           for name,digest in manifest['files'].items()):raise ValueError('HTTP_AUTH_SOURCE_CHANGED')
    source=(SOURCE/'sms_login.py').read_text()
    precheck="    from sms_receiver import baseline\n    # Check both prerequisites before sending a code or touching the helper.\n    if not (BASE/'sms-source.json').is_file():raise ValueError('SMS_SOURCE_NOT_CONFIGURED')\n    baseline()\n"
    statement="module.write_text(header+(SOURCE/'sms_worker.py').read_text())"
    if source.count(precheck)!=1 or source.count(statement)!=1:raise ValueError('INITIALIZE_AUTH_SOURCE_CHANGED')
    worker_source()
    source=source.replace(precheck,'    # Explicit local manual initialization; no Messages enrollment required.\n')
    source=source.replace(statement,'module.write_text(header+worker_source())')
    namespace={'__file__':str(SOURCE/'sms_login.py'),'worker_source':worker_source}
    exec(compile(source,'local-session-launcher','exec'),namespace)
    return namespace['launch'](output_dir,service=scope)
