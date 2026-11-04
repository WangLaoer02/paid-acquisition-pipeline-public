"""Local shared Seedance workbench. python3 serve.py [--port 8786]."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote
import argparse, json, re
from catalog import catalog
import store
import diagnostics
from configuration import runtime_info, PORT

BASE = Path(__file__).resolve().parent

class Handler(BaseHTTPRequestHandler):
    def send_data(self, data, kind='application/json; charset=utf-8', status=200, filename=None):
        if not isinstance(data, bytes): data=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        for key,value in [('Content-Type',kind),('Content-Length',str(len(data))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer')]: self.send_header(key,value)
        if filename:self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(filename))
        self.end_headers(); self.wfile.write(data)

    def check_origin(self):
        hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        host=self.headers.get('Host','')
        if host not in hosts:
            raise store.StudioError('Local same-origin access only',403)
        if self.command=='GET' and urlsplit(self.path).path in {'/','/index.html','/maker','/maker.html'} and self.headers.get('Sec-Fetch-Dest')=='document':return
        if self.headers.get('Sec-Fetch-Site')=='cross-site':raise store.StudioError('Local same-origin access only',403)
        origin=self.headers.get('Origin')
        if origin and origin not in {'http://'+h for h in hosts}:
            raise store.StudioError('Origin not allowed',403)

    def do_GET(self): self.handle_request('GET')
    def do_POST(self): self.handle_request('POST')
    def do_PATCH(self): self.handle_request('PATCH')

    def send_file(self,item):
        path=Path(item['path']);size=path.stat().st_size;start=0;end=size-1;status=200
        request_range=self.headers.get('Range')
        if request_range:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',request_range)
            if not match or not any(match.groups()):raise store.StudioError('Invalid range',416)
            if not match[1]:start=max(0,size-int(match[2]))
            else:
                start=int(match[1]);end=min(end,int(match[2])) if match[2] else end
            if start> end or start>=size:raise store.StudioError('Range outside file',416)
            status=206
        self.send_response(status)
        self.send_header('Content-Type',item['type']);self.send_header('Content-Length',str(max(0,end-start+1)))
        self.send_header('Accept-Ranges','bytes');self.send_header('Cache-Control','no-store')
        self.send_header('Content-Disposition',"inline; filename*=UTF-8''"+quote(path.name))
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"sandbox; default-src 'none'")
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as source:
            source.seek(start);remaining=end-start+1
            while remaining>0:
                data=source.read(min(1024*1024,remaining))
                if not data:break
                self.wfile.write(data);remaining-=len(data)

    def handle_request(self, method):
        try:
            self.check_origin()
            parsed=urlsplit(self.path); path=parsed.path; parts=path.strip('/').split('/')
            if method=='GET':
                if path in ['/','/index.html']:
                    return self.send_data((BASE/'index.html').read_bytes(),'text/html; charset=utf-8')
                if path in ['/maker','/maker.html']:
                    page=(BASE/'maker.html').read_text()
                    snapshot=json.dumps(catalog(),ensure_ascii=False).replace('<','\\u003c')
                    page=re.sub(r'(<script id="skill-data" type="application/json">).*?(</script>)',lambda m:m[1]+snapshot+m[2],page,flags=re.S)
                    return self.send_data(page.encode(),'text/html; charset=utf-8')
                if path in ['/workspace.js','/workspace.css','/monitor.js','/monitor.css']:
                    return self.send_data((BASE/path[1:]).read_bytes(),'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
                if len(parts)==5 and parts[:2]==['api','runs'] and parts[3]=='skills':return self.send_data(diagnostics.skill_snapshot(parts[2],parts[4]))
                if len(parts)==4 and parts[:2]==['api','runs'] and parts[3]=='inspect':
                    query=parse_qs(parsed.query)
                    return self.send_data(diagnostics.inspection(parts[2],query.get('step',[None])[0],query.get('issue',[None])[0]),filename=parts[2]+'_inspection.json' if query.get('download')==['1'] else None)
                if path=='/api/monitor':return self.send_data(diagnostics.monitor())
                if len(parts)==3 and parts[:2]==['api','files']:return self.send_file(diagnostics.registered_file(parts[2]))
                if len(parts)==4 and parts[:2]==['api','files'] and parts[3]=='frame':return self.send_data(diagnostics.frame(parts[2],parse_qs(parsed.query).get('at',['0'])[0]),'image/jpeg')
                if path=='/api/catalog': return self.send_data(catalog())
                if path=='/api/state': return self.send_data(store.workspace())
                if path=='/api/pending': return self.send_data(store.pending())
                if path=='/api/runtime': return self.send_data(runtime_info())
                if path=='/api/agent': return self.send_data((BASE/'AGENT.md').read_bytes(),'text/plain; charset=utf-8')
                if len(parts)==5 and parts[:2]==['api','tasks'] and parts[3]=='versions':
                    with store.connection() as db:
                        row=db.execute('SELECT body FROM versions WHERE task_id=? AND revision=?',(parts[2],int(parts[4]))).fetchone()
                        if not row: raise store.StudioError('Version not found',404)
                        return self.send_data(json.loads(row['body']))
                if len(parts)==3 and parts[:2]==['api','assets']:
                    asset=store.asset_path(parts[2]); file=Path(asset['path'])
                    self.send_response(200)
                    self.send_header('Content-Type',asset['type']);self.send_header('Content-Length',str(file.stat().st_size));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"sandbox; default-src 'none'");self.end_headers()
                    with file.open('rb') as src:
                        while chunk:=src.read(1024*1024): self.wfile.write(chunk)
                    return
                if len(parts) in {3,4} and parts[:2]==['api','tasks']:
                    result=store.context(parts[2]) if len(parts)==4 and parts[3]=='context' else None
                    if len(parts)==3:
                        with store.connection() as db: result=store.task_bundle(db,parts[2])
                    if result is not None: return self.send_data(result)
            else:
                if len(parts)==4 and parts[:2]==['api','tasks'] and parts[3]=='assets' and method=='POST':
                    return self.send_data(store.save_asset(parts[2],parse_qs(parsed.query).get('name',['素材'])[0],self.headers.get('Content-Type',''),self.rfile,int(self.headers.get('Content-Length','0'))))
                if self.headers.get_content_type()!='application/json': raise store.StudioError('Use application/json',415)
                size=int(self.headers.get('Content-Length','0'))
                if size<=0 or size>4*1024*1024: raise store.StudioError('JSON body limit: 4 MiB',413)
                value=json.loads(self.rfile.read(size));who=value.get('actor')
                if path=='/api/issues' and method=='POST':return self.send_data(diagnostics.save_issue(value,who),status=201)
                if len(parts)==3 and parts[:2]==['api','issues'] and method=='PATCH':return self.send_data(diagnostics.save_issue(value,who,parts[2]))
                if len(parts)==4 and parts[:2]==['api','runs'] and parts[3]=='steps' and method=='POST':
                    return self.send_data(diagnostics.start_step(parts[2],who,value.get('title',''),value.get('kind','tool'),value.get('inputs'),value.get('skill_slug'),value.get('parent_step_id'),value.get('reason',''),value.get('expected','')),status=201)
                if len(parts)==5 and parts[:2]==['api','runs'] and parts[3]=='steps' and method=='PATCH':
                    return self.send_data(diagnostics.finish_step(parts[2],parts[4],who,value.get('status'),value.get('output',''),value.get('error',''),value.get('duration_ms'),value.get('evidence'),value.get('exit_code'),value.get('outcome')))
                if path=='/api/tasks' and method=='POST': return self.send_data(store.create_task(value['task'],who),status=201)
                if len(parts)>=3 and parts[:2]==['api','tasks']:
                    task_id=parts[2]
                    if len(parts)==3 and method=='PATCH': return self.send_data(store.update_task(task_id,value['task'],who,value.get('expected_revision'),value.get('event_type','task_saved')))
                    if len(parts)==4 and method=='POST':
                        if parts[3]=='activate': return self.send_data(store.activate(task_id,who))
                        if parts[3]=='notes': return self.send_data(store.add_note(task_id,who,value.get('summary',''),value.get('run_id'),value.get('evidence')))
                        if parts[3]=='runs': return self.send_data(store.start_run(task_id,who,value.get('skills'),value.get('queued',False),value.get('summary',''),value.get('request_key')),status=201)
                if len(parts)==4 and parts[:2]==['api','runs'] and method=='POST':
                    if parts[3]=='claim': return self.send_data(store.claim_run(parts[2],who))
                    if parts[3]=='finish': return self.send_data(store.finish_run(parts[2],who,value.get('status'),value.get('summary',''),value.get('output',''),value.get('evidence')))
            raise store.StudioError('Route not found',404)
        except store.StudioError as exc:
            self.send_data({'error':str(exc)},status=exc.status)
        except (ValueError,KeyError,TypeError) as exc:
            self.send_data({'error':'Invalid request: '+str(exc)},status=400)
        except (BrokenPipeError,ConnectionResetError): pass

    def log_message(self,*args): pass

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=PORT);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Seedance Studio: http://127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()
