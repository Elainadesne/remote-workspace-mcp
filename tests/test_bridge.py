import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from bridge.files import Files, BridgeError
from bridge.history import AppServer
from bridge.server import Bridge, http_server, mcp

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'src').mkdir()
        (self.root/'src'/'hello.py').write_text('hello world\n你好\n', encoding='utf-8')
        (self.root/'.env').write_text('SECRET=do-not-send')
        self.cfg = {'projects': {'demo': str(self.root)}, 'codex': {'threads': {'t1': 'demo'}}}
        self.b = Bridge(self.cfg, reader=lambda tid: {'id': tid, 'cwd': str(self.root), 'turns': [{'items': [
            {'type': 'reasoning', 'content': 'hidden'},
            {'type': 'commandExecution', 'aggregatedOutput': 'private'},
            {'type': 'userMessage', 'content': [{'type': 'text', 'text': 'question'}]},
            {'type': 'agentMessage', 'text': 'answer', 'phase': 'final_answer'}]}]})
    def tearDown(self):
        self.tmp.cleanup()
    def test_read_utf8(self):
        self.assertIn('你好', self.b.call('read_file', {'project':'demo', 'path':'src/hello.py'})['text'])
    def test_list_hides_dotfiles(self):
        self.assertEqual(self.b.call('list_files', {'project':'demo'}), [{'name':'src','kind':'directory'}])
    def test_traversal_and_secrets(self):
        for p in ('../outside', '/etc/passwd', '.env', 'src/../../x', 'a\\b', 'auth.json', 'secret.txt'):
            with self.subTest(p=p), self.assertRaises((BridgeError, OSError)):
                self.b.files.read('demo', p)
    def test_symlink_file(self):
        (self.root/'link').symlink_to(self.root/'src/hello.py')
        with self.assertRaises(OSError):
            self.b.files.read('demo', 'link')
    def test_symlink_directory(self):
        (self.root/'link').symlink_to(self.root/'src', target_is_directory=True)
        with self.assertRaises(OSError):
            self.b.files.read('demo', 'link/hello.py')
    def test_fifo(self):
        os.mkfifo(self.root/'pipe')
        with self.assertRaises(BridgeError):
            self.b.files.read('demo', 'pipe')
    def test_binary(self):
        (self.root/'binary').write_bytes(b'a\x00b')
        with self.assertRaises(BridgeError):
            self.b.files.read('demo', 'binary')
    def test_large(self):
        (self.root/'large').write_bytes(b'a'*262145)
        with self.assertRaises(BridgeError):
            self.b.files.read('demo', 'large')
    def test_search(self):
        r = self.b.call('search_text', {'project':'demo', 'query':'你好'})
        self.assertEqual(r['hits'][0]['line'], 2)
    def test_unknown_project(self):
        with self.assertRaises(BridgeError):
            self.b.call('list_files', {'project':'no'})
    def test_no_arbitrary_tools(self):
        for name in ('exec', 'turn/start', 'thread/resume'):
            with self.assertRaises(BridgeError):
                self.b.call(name, {})
    def test_unknown_arg(self):
        with self.assertRaises(BridgeError):
            self.b.call('list_files', {'project':'demo','command':'echo nope'})
    def test_history_filters(self):
        r = self.b.call('read_thread', {'project':'demo','thread_id':'t1'})
        self.assertEqual([m['text'] for m in r['messages']], ['question','answer'])
    def test_unlisted_history(self):
        with self.assertRaises(BridgeError):
            self.b.history.read('demo','other')
    def test_outside_history(self):
        self.b.history.reader = lambda tid: {'id':tid,'cwd':'/other','turns':[]}
        with self.assertRaises(BridgeError):
            self.b.history.read('demo','t1')
    def test_history_identity(self):
        self.b.history.reader = lambda tid: {'id':'wrong','cwd':str(self.root),'turns':[]}
        with self.assertRaises(BridgeError):
            self.b.history.read('demo','t1')
    def test_import(self):
        (self.root/'reviewed.json').write_text(json.dumps({'messages':[
            {'role':'system','text':'hidden'}, {'role':'user','text':'password=abc'}]}))
        self.b.history.imports = {'i': {'project':'demo','path':'reviewed.json'}}
        r = self.b.history.read('demo','i')
        self.assertEqual(r['messages'], [{'role':'user','text':'[REDACTED]'}])
    def test_mcp(self):
        r = mcp(self.b, {'jsonrpc':'2.0','id':1,'method':'tools/list'})
        self.assertEqual(len(r['result']['tools']),8)
        r = mcp(self.b, {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'list_projects'}})
        self.assertEqual(json.loads(r['result']['content'][0]['text']), ['demo'])
    def test_http(self):
        token = 't'*32
        server = http_server(self.b, token, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        def req(auth, origin=None):
            c = http.client.HTTPConnection('127.0.0.1',server.server_port)
            headers = {'Content-Type':'application/json','Authorization':auth}
            if origin: headers['Origin']=origin
            c.request('POST','/v1/call',json.dumps({'name':'list_projects','arguments':{}}), headers)
            r = c.getresponse()
            out = (r.status, json.loads(r.read()))
            c.close()
            return out
        try:
            self.assertEqual(req('bad')[0],401)
            self.assertEqual(req('Bearer '+token,'https://evil.example')[0],403)
            self.assertEqual(req('Bearer '+token),(200, {'result':['demo']}))
        finally:
            server.shutdown(); server.server_close(); worker.join()
    def test_token_required(self):
        with self.assertRaises(BridgeError):
            http_server(self.b, '', 0)
    def test_stdio_subprocess(self):
        cfg = self.root/'settings.json'; cfg.write_text(json.dumps(self.cfg))
        requests = '\n'.join(json.dumps(x) for x in [
            {'jsonrpc':'2.0','id':1,'method':'initialize'},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'list_projects'}}])+'\n'
        r = subprocess.run([sys.executable,'-m','bridge.server','--config',str(cfg)],input=requests,
                           text=True,capture_output=True,timeout=5)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(len(r.stdout.splitlines()),2)
    def test_real_process_fake_codex(self):
        # Test protocol transport with a synthetic executable, NOT real user Codex.
        binary = self.root/'fake-codex'
        binary.write_text('#!'+sys.executable+'\n'+'''import json,sys
for line in sys.stdin:
 r=json.loads(line)
 if r['method']=='initialized': continue
 if r['method']=='initialize': result={}
 elif r['method']=='thread/read': result={'thread':{'id':r['params']['threadId'],'cwd':'/test','turns':[]}}
 else: raise RuntimeError('unexpected action')
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
''')
        binary.chmod(0o700)
        self.assertEqual(AppServer(str(binary),str(self.root)).read('t1')['id'],'t1')

    def test_paginated_protocol(self):
        binary = self.root/'fake-paged'
        source = """import json,sys
for line in sys.stdin:
 r=json.loads(line); m=r['method']; a=r.get('params',{})
 if m=='initialized': continue
 if m=='initialize':
  assert a['capabilities']['experimentalApi'] is True
  result={}
 elif m=='thread/read':
  assert a['includeTurns'] is False
  result={'thread':{'id':a['threadId'],'cwd':ROOT,'turns':[]}}
 elif m=='thread/turns/list':
  assert a['limit']==1 and a['itemsView']=='full'
  assert a['cursor']=='page-two'
  result={'data':[{'items':[{'type':'agentMessage','text':'visible'}]}],'nextCursor':'page-three'}
 else: raise RuntimeError('unexpected mutating action')
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
""".replace('ROOT', repr(str(self.root)))
        binary.write_text('#!'+sys.executable+'\n'+source); binary.chmod(0o700)
        app=AppServer(str(binary),str(self.root))
        out=app.read('t1',paginated=True,cursor='page-two',expected_root=str(self.root))
        self.assertEqual(out['nextCursor'],'page-three')
        self.assertEqual(out['turns'][0]['items'][0]['text'],'visible')
        with self.assertRaises(BridgeError):
            app.read('t1',paginated=True,expected_root='/another-project')

    def test_page_cursor_preserved(self):
        class Pager:
            def read(inner, tid, **kw):
                self.assertTrue(kw['paginated'])
                self.assertEqual(kw['cursor'],'next')
                return {'id':tid,'cwd':str(self.root),'turns':[], 'nextCursor':'more','paginated':True}
        self.b.history.app=Pager()
        out=self.b.call('read_thread',{'project':'demo','thread_id':'t1','cursor':'next'})
        self.assertEqual(out['messages'],[])
        self.assertTrue(out['has_more'])
        self.assertEqual(out['next_cursor'],'more')

    def test_unlisted_thread_never_calls_pager(self):
        class Pager:
            def read(inner, *a, **kw):
                raise AssertionError('must not reach upstream')
        self.b.history.app=Pager()
        with self.assertRaises(BridgeError):
            self.b.history.read('demo','not-allowed',cursor='anything')

if __name__ == '__main__':
    unittest.main()
