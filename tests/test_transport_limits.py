"""Independent in-process boundary tests with synthetic I/O only."""
import asyncio
import json
import threading
import unittest
from unittest.mock import patch
import bridge.streamable_http as mod
from bridge.files import BridgeError
TOKEN='synthetic-only-'+'a'*32
BODY=b'{"jsonrpc":"2.0","id":0,"method":"ping"}'

class ResourceLimits(unittest.IsolatedAsyncioTestCase):
    def scope(self):
        return {'type':'http','method':'POST','path':'/mcp','raw_path':b'/mcp','query_string':b'', 'headers':[(b'host',b'127.0.0.1:8765'),(b'authorization',('Bearer '+TOKEN).encode()),(b'content-type',b'application/json'),(b'content-length',str(len(BODY)).encode()),(b'accept',b'application/json, text/event-stream')]}

    async def run_app(self,boundary,receive=None):
        responses=[]
        async def recv(): return {'type':'http.request','body':BODY,'more_body':False}
        async def send(message): responses.append(message)
        await boundary(self.scope(),receive or recv,send)
        return responses

    async def test_body_deadline_recovers_admission(self):
        async def unexpected(*args): self.fail('must not dispatch incomplete body')
        boundary=mod.Boundary(unexpected,TOKEN,8765)
        async def slow():
            await asyncio.sleep(.05)
            return {'type':'http.request','body':BODY,'more_body':False}
        with patch.object(mod,'BODY_TIMEOUT',.01): out=await self.run_app(boundary,slow)
        self.assertEqual(out[0]['status'],408)
        self.assertEqual(boundary.in_flight,0)

    async def test_request_admission_saturated(self):
        async def unexpected(*args): self.fail('must not dispatch overloaded request')
        boundary=mod.Boundary(unexpected,TOKEN,8765); boundary.in_flight=mod.MAX_REQUESTS
        out=await self.run_app(boundary)
        self.assertEqual(out[0]['status'],503)
        self.assertEqual(boundary.in_flight,mod.MAX_REQUESTS)

    async def test_oversized_output_fails_closed(self):
        async def app(scope,receive,send):
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'x'*(mod.MAX_RESPONSE+1)})
        boundary=mod.Boundary(app,TOKEN,8765)
        out=await self.run_app(boundary)
        self.assertEqual(out[0]['status'],500)
        self.assertLess(len(out[1]['body']),512)
        self.assertEqual(boundary.in_flight,0)

    async def test_sdk_error_redaction(self):
        async def app(scope,receive,send):
            await send({'type':'http.response.start','status':400,'headers':[]})
            await send({'type':'http.response.body','body':json.dumps({'jsonrpc':'2.0','id':0,'error':{'code':-32602,'message':'PRIVATE_ERROR_MARKER','data':{'value':TOKEN}}}).encode()})
        out=await self.run_app(mod.Boundary(app,TOKEN,8765))
        self.assertEqual(out[0]['status'],400)
        self.assertNotIn(b'PRIVATE_ERROR_MARKER',out[1]['body'])
        self.assertNotIn(TOKEN.encode(),out[1]['body'])

    async def test_slow_read_retains_worker_admission(self):
        release=threading.Event(); calls=[]
        class SlowBridge:
            def call(self,name,arguments):
                calls.append(name)
                release.wait(1)
                return {'ok':True}
        reader=mod.SingleReader(SlowBridge())
        try:
            with patch.object(mod,'TOOL_TIMEOUT',.02):
                with self.assertRaisesRegex(BridgeError,'timed out'):
                    await reader.call('first',{})
                with self.assertRaisesRegex(BridgeError,'busy'):
                    await reader.call('second',{})
            self.assertEqual(calls,['first'])
            release.set()
            await asyncio.sleep(.03)
            self.assertEqual(await reader.call('third',{}),{'ok':True})
            self.assertEqual(calls,['first','third'])
        finally:
            release.set(); reader.close()

    async def test_token_documented_maximum(self):
        for value in ('a'*31,'a'*513,'a'*32+'='*512):
            with self.subTest(length=len(value)),self.assertRaises(BridgeError): mod.validate_token(value)

if __name__=='__main__':unittest.main(verbosity=2)
