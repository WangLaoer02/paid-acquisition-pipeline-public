import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import urllib.parse
import threading

import fast_video as v
import video_mcp as m

class VideoTests(unittest.TestCase):
    def test_ignore_summary_and_preserve_exact_url(self):
        # Synthetic query assembled locally; no captured material URL or network request.
        url=urllib.parse.urlunsplit(('https','demand.backend.example.invalid','/data/',urllib.parse.urlencode({'_c':'creativeVideoList','_a':'index','ac':'openVideo','video_name':'A+B'}),''))
        rows={'rows':[{'date':'总数量','mid':20},{'demand_url':url,'video_name':'A+B','cost':0},{'demand_url':url,'video_name':'A+B'}]}
        items=v.normalize_rows(rows)
        self.assertEqual(len(items),1);self.assertEqual(items[0]['demand_url'],url)
        self.assertEqual(items[0]['cost'],0);self.assertIsNone(items[0]['transcript'])

    def test_invalid_query_never_opens_browser(self):
        with patch.object(v,'prepare') as prepare:
            with self.assertRaises(Exception):v.search('2026/99/01-2026/99/02','2026/09/01-2026/09/02','193')
            prepare.assert_not_called()

    def test_exact_cache_no_extra_backend_request(self):
        with tempfile.TemporaryDirectory() as d,patch.object(v,'CACHE',Path(d)),patch.object(v,'prepare'),patch.object(v.capture,'run_batch') as run:
            run.return_value={'results':[{'ok':True,'rows':[],'query':{'totalpage':3,'pages_completed':1}}]}
            a=v.search('2026/09/01-2026/09/02','2026/09/01-2026/09/02','193')
            b=v.search('2026/09/01-2026/09/02','2026/09/01-2026/09/02','193',limit=1)
            self.assertFalse(a['cache_hit']);self.assertTrue(b['cache_hit']);self.assertTrue(b['has_more']);self.assertEqual(run.call_count,1)

    def test_backend_failure_not_cached_or_retried(self):
        with tempfile.TemporaryDirectory() as d,patch.object(v,'CACHE',Path(d)),patch.object(v,'prepare'),patch.object(v.capture,'run_batch') as run:
            run.return_value={'results':[{'ok':False,'error':'HTTP_504'}]}
            with self.assertRaisesRegex(RuntimeError,'HTTP_504'):v.search('2026/09/01-2026/09/02','2026/09/01-2026/09/02','193')
            self.assertEqual(run.call_count,1);self.assertFalse((Path(d)/'queries').exists())

    def test_arbitrary_download_rejected_before_network(self):
        with patch.object(v.urllib.request,'build_opener') as net:
            for u in ['http://127.0.0.1/a.mp4','https://market-sy-ad-static.backend.example.invalid.evil/a.mp4','file:///a.mp4']:
                with self.assertRaises(ValueError):v.download(u,Path('not-created'))
            net.assert_not_called()

    def test_ids_cannot_escape_cache(self):
        with self.assertRaises(ValueError):v.get_item('../../secret')

    def test_relogin_invalidates_previous_account_indexes(self):
        with tempfile.TemporaryDirectory() as d,patch.object(v,'CACHE',Path(d)),patch.object(v.session,'ensure_active_session'),patch.object(v,'bridge',return_value={'ok':True}) as bridge:
            for folder in ['queries','materials','media']:
                p=Path(d)/folder/'sample.json';p.parent.mkdir();p.write_text('{}')
            v.relogin()
            self.assertFalse((Path(d)/'queries/sample.json').exists())
            self.assertFalse((Path(d)/'materials/sample.json').exists())
            self.assertTrue((Path(d)/'media/sample.json').exists())
            bridge.assert_called_once_with('relogin')

    def test_mcp_content_emits_images_without_local_paths(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'sample.jpg';p.write_bytes(b'image')
            with patch.object(v,'frames',return_value={'ok':True,'transcript':None,'frames':[{'seconds':1,'path':str(p)}]}):
                result=m.call('rongyao_video_content',{'id':'abc'})
            self.assertEqual(result['content'][2]['type'],'image');self.assertNotIn(d,json.dumps(result));self.assertFalse(result['isError'])
            self.assertEqual(result['structuredContent'],json.loads(result['content'][0]['text']))
            self.assertEqual(result['structuredContent']['frames'],[{'seconds':1}])

    def test_http_initialize_list_and_error(self):
        server=m.ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        def rpc(method,params=None):
            req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/mcp',data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}).encode(),headers={'Content-Type':'application/json'})
            return json.load(urllib.request.urlopen(req))
        try:
            # No OAuth metadata is advertised; tunnel discovery requires 404.
            for path,status in [('/mcp',405),('/',404),('/.well-known/oauth-protected-resource/mcp',404),('/.well-known/oauth-authorization-server',404)]:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}{path}')
                self.assertEqual(error.exception.code,status)
            self.assertEqual(rpc('initialize')['result']['protocolVersion'],'2025-06-18')
            self.assertEqual(rpc('initialize',{'protocolVersion':'2025-11-25'})['result']['protocolVersion'],'2025-11-25')
            self.assertEqual(len(rpc('tools/list')['result']['tools']),4)
            error=rpc('tools/call',{'name':'unknown'})['result']
            self.assertTrue(error['isError'])
            self.assertEqual(error['structuredContent'],{'ok':False,'error':'UNKNOWN_TOOL'})
        finally:server.shutdown();server.server_close();worker.join()

    def test_text_only_content_preserves_data_and_no_visual_claim(self):
        with patch.object(m,'INCLUDE_IMAGES',False),patch.object(v,'frames',return_value={'ok':True,'video_url':'https://example.test/a.mp4','transcript':None,'frames':[{'seconds':1,'path':'/private/frame.jpg'}]}):
            result=m.call('rongyao_video_content',{'id':'abc'})
        self.assertEqual(len(result['content']),1)
        self.assertEqual(result['structuredContent']['image_delivery'],'text_only_no_visual_input')
        self.assertNotIn('/private',json.dumps(result))

if __name__=='__main__':unittest.main()
