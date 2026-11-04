"""Select a unique six-digit code from incoming SMS within 60s of this request.

Sender and purpose text are not selection criteria. Codes stay in memory.
"""
import json,re,sqlite3,time
from pathlib import Path
FOLDER=Path.home()/'.codex/state/rongyao-http'
# Retained only for the legacy explicit source-enrollment command.
PATTERN=re.compile(r'^【炽焰网络】\s*([0-9]{6})\s*为你的后台验证码，10分钟内有效。祝您游戏愉快！$')
CODE_PATTERN=re.compile(r'(?<![0-9])([0-9]{6})(?![0-9])')
WINDOW_SECONDS=60

def connect():
    return sqlite3.connect((Path.home()/'Library/Messages/chat.db').as_uri()+'?mode=ro',uri=True,timeout=3)
def baseline():
    with connect() as db:
        return db.execute('SELECT COALESCE(MAX(ROWID),0) FROM message').fetchone()[0]
def select_code(rows,sender_hash,requested_at):
    # sender_hash retained for caller compatibility; deliberately not consulted.
    candidates={}
    for rowid,date,sender,text in rows:
        received_at=date/1e9+978307200
        if not requested_at <= received_at <= requested_at+WINDOW_SECONDS:continue
        for code in CODE_PATTERN.findall(text or ''):
            candidates[code]=max(rowid,candidates.get(code,0))
    if len(candidates)>1:raise ValueError('AMBIGUOUS_NEW_RONGYAO_SMS')
    return next(((rowid,code) for code,rowid in candidates.items()),None)
def receive(after_rowid,requested_at,timeout=60):
    deadline=time.monotonic()+min(max(timeout,0),WINDOW_SECONDS)
    start=int((requested_at-978307200)*1e9)
    end=int((requested_at+WINDOW_SECONDS-978307200)*1e9)
    while time.monotonic()<deadline:
        with connect() as db:
            rows=db.execute('SELECT ROWID,date,NULL,text FROM message WHERE ROWID>? AND is_from_me=0 AND date>=? AND date<=? ORDER BY ROWID DESC LIMIT 101',(after_rowid,start,end)).fetchall()
        if len(rows)>100:raise ValueError('SMS_WINDOW_TOO_MANY_MESSAGES')
        found=select_code(rows,None,requested_at)
        if found:
            rowid,code=found
            receipt={'stage':'code_received_locally','channel':'mac_messages_readonly','sms_rowid':rowid,'code_persisted':False,'received_at':time.time(),'selection_policy':'request_time_window_60s_unique_six_digits'}
            path=FOLDER/'sms-receipt.json';path.write_text(json.dumps(receipt));path.chmod(0o600)
            return code
        time.sleep(min(1,max(0,deadline-time.monotonic())))
    raise ValueError('RONGYAO_SMS_SYNC_TIMEOUT')
