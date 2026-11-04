#!/usr/bin/env python3
"""本批一次性会话：正确入口的认证在内存中复用，不持久化Cookie。"""
import argparse
import hashlib
from pathlib import Path
import json
import multiprocessing as mp
import sqlite3
import sys
import time

import rongyao_checked_upload as checked
import workflow_runtime as runtime
from material_upload import UploadError

ENTRY = 'http://adopenplatform.backend.example.invalid/app/data/?_c=jrttList&_a=index&ac=toImgInfo&do=video'
EXECUTION_SECONDS=59  # 留一秒用于终止进程与输出反馈。


def _run_command(pipe, command, secret, display_name):
    """认证仅通过进程内存传递；每次API执行有独立的60秒边界。"""
    try:
        import rongyao_video_list_upload as adapter
        result=adapter.command(command,secret,None,display_name)
        pipe.send(adapter.feedback(result) if command['action']=='run' else result)
    except (UploadError, ValueError, KeyError, OSError, TypeError) as exc:
        pipe.send({'phase':'blocked','error':getattr(exc,'code','LOCAL_ERROR'),
                   'reason':str(exc) if isinstance(exc,UploadError) else '本地状态无效，未输出私有内容。'})
    finally:
        secret.clear()
        pipe.close()


def deadline_feedback(command, started):
    import rongyao_video_list_upload as adapter
    names=command.get('names') or ([command['name']] if command.get('name') else
                                 [x['upload_name'] for x in adapter.read_json(adapter.PLAN)['items']])
    queue=adapter.native.private_queue_dir('~/.config/rongyao-material-upload','single-current')
    receipts={}
    try:
        with sqlite3.connect((queue/'receipts.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=.1) as db:
            for (raw,) in db.execute('SELECT receipt FROM receipts'):
                row=json.loads(raw)
                if row.get('upload_name') not in names or row.get('started_at_epoch',0)<started: continue
                receipts[row['upload_name']]=row
    except sqlite3.Error:
        return {'提示':'一分钟到时；账本暂不可读，受理结果待回查，禁止重发。',
                '成功数量':0,'状态':'ACCEPTANCE_UNKNOWN','执行截止秒数':60,'素材名称':names}
    items=[]
    for name in names:
        row=receipts.get(name,{'upload_name':name,'status':'NOT_STARTED'})
        state=row['status']
        if state=='SENDING': state='ACCEPTANCE_UNKNOWN'
        elif state=='JOIN_ACK': state='JOIN_ACK_PENDING_READBACK'
        items.append(dict(adapter.feedback(dict(row,status=state)),状态=state))
    return {'提示':'一分钟到时，已停止本次执行；已受理或未知请求只回查，不重发。',
            '成功数量':sum(x['状态']=='CONFIRMED' for x in items),
            '待确认数量':sum(x['状态'] in ('ACCEPTANCE_UNKNOWN','JOIN_ACK_PENDING_READBACK') for x in items),
            '执行截止秒数':60,'items':items}


def execute_bounded(command, secret, display_name):
    started=time.time()
    deadline=time.monotonic()+EXECUTION_SECONDS
    ctx=mp.get_context('spawn')
    reader,writer=ctx.Pipe(duplex=False)
    process=ctx.Process(target=_run_command,args=(writer,command,secret,display_name))
    process.start()
    writer.close()
    try:
        if reader.poll(max(0,deadline-time.monotonic())):
            try: return reader.recv()
            except EOFError: return {'phase':'blocked','error':'WORKER_ENDED','reason':'执行进程结束；保留账本，未知请求不重传。'}
        process.terminate()
        process.join(timeout=.2)
        if process.is_alive():
            process.kill()
            process.join(timeout=.2)
        return deadline_feedback(command,started)
    finally:
        reader.close()
        process.join(timeout=.2)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request-file',required=True);p.add_argument('--creator-sha256',default=None,help=argparse.SUPPRESS);p.add_argument('--display-name',required=True);p.add_argument('--authorization-ticket',required=True);args=p.parse_args()
    request_path=Path(args.request_file).expanduser().resolve();request_sha=hashlib.sha256(request_path.read_bytes()).hexdigest();scope='material-upload:'+args.display_name
    runtime.ensure_writer('material_upload');runtime.check_circuit('material_upload',scope);runtime.dependencies('material_upload');runtime.ensure_release(True);runtime.authorization(args.authorization_ticket,'material_upload',scope,request_sha,False)
    secret=checked.consume_request_file(args.request_file,{'entry':ENTRY})
    print(json.dumps({'phase':'memory_session_ready','request_file_deleted':True}),flush=True)
    try:
        with runtime.mutation('material_upload',scope,authorization_ticket=args.authorization_ticket,input_sha256=request_sha):
            for line in sys.stdin:
                try:
                    command=json.loads(line)
                    if command['action']=='quit':break
                    result=execute_bounded(command,secret,args.display_name);print(json.dumps(result,ensure_ascii=False),flush=True)
                except (UploadError,ValueError,KeyError,OSError,TypeError) as exc:
                    print(json.dumps({'phase':'blocked','error':getattr(exc,'code','LOCAL_ERROR'),'reason':str(exc) if isinstance(exc,UploadError) else '本地状态无效，未输出私有内容。'},ensure_ascii=False),flush=True)
    finally:
        secret.clear();print(json.dumps({'phase':'session_cleared','credential_saved':False}),flush=True)


if __name__ == '__main__':
    main()
