"""Real Uvicorn socket checks, with shortened constants only in a test subprocess."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import importlib.util
REPO = Path(__file__).resolve().parents[1]
SDK = importlib.util.find_spec('mcp') is not None

@unittest.skipUnless(SDK, 'optional HTTP SDK not installed; run pip install .[http]')
class SocketBoundaries(unittest.TestCase):
    def test_absolute_deadline_and_connection_admission(self):
        with tempfile.TemporaryDirectory(prefix='connection-audit-') as tmp:
            with socket.socket() as s:
                s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
            code='''import os
from bridge.workspace import Bridge
import bridge.streamable_http as s
s.CONNECTION_TIMEOUT=.5
s.MAX_CONNECTIONS=3
s.serve(Bridge({'projects':{'sample':os.environ['AUDIT_PROJECT']}}), 'test-only-'+'x'*40, int(os.environ['AUDIT_PORT']))
'''
            proc=subprocess.Popen([sys.executable,'-c',code],cwd=REPO,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','AUDIT_PROJECT':tmp,'AUDIT_PORT':str(port)},stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            sockets=[]
            try:
                for _ in range(100):
                    if proc.poll() is not None: self.fail('server stopped during startup')
                    try:
                        socket.create_connection(('127.0.0.1',port),timeout=.02).close(); break
                    except OSError: time.sleep(.02)
                time.sleep(.03)
                started=time.monotonic()
                for _ in range(5):
                    sock=socket.create_connection(('127.0.0.1',port),timeout=.1)
                    sock.sendall(b'POST /mcp HTTP/1.1\r\nX-Test: PRIVATE_HEADER_MARKER')
                    sockets.append(sock)
                time.sleep(.03)
                closed=[]
                for i,sock in enumerate(sockets):
                    sock.settimeout(.015)
                    try:
                        if sock.recv(1)==b'': closed.append(i)
                    except ConnectionResetError: closed.append(i)
                    except TimeoutError: pass
                self.assertEqual(closed,[3,4])
                survivor=sockets[0]
                was_closed=False
                while time.monotonic()-started<1:
                    try:
                        survivor.sendall(b'x')
                        if survivor.recv(1)==b'': was_closed=True; break
                    except (ConnectionResetError,BrokenPipeError): was_closed=True; break
                    except TimeoutError: pass
                    time.sleep(.02)
                elapsed=time.monotonic()-started
                self.assertTrue(was_closed,'trickled header connection outlived its deadline')
                self.assertGreater(elapsed,.35)
                self.assertLess(elapsed,1.0)
            finally:
                for sock in sockets: sock.close()
                proc.terminate()
                try: out,err=proc.communicate(timeout=3)
                except subprocess.TimeoutExpired: proc.kill();out,err=proc.communicate()
            self.assertNotIn(b'PRIVATE_HEADER_MARKER',out+err)
            self.assertNotIn(b'Traceback',out+err)

if __name__=='__main__': unittest.main(verbosity=2)
