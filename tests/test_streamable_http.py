"""MCP wire and security contracts. Optional SDK tests require .[http].

These use the real local HTTP transport and the official SDK as a client. They
are not evidence that ZCode or Claude Code has been launched or authenticated.
"""
import asyncio
import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from bridge.files import BridgeError
from bridge.streamable_http import Boundary, SingleReader, parse_request, validate_token

ROOT = Path(__file__).resolve().parents[1]
SDK = importlib.util.find_spec('mcp') is not None
TOKEN = 'synthetic-test-only-' + 'x' * 32


class BoundaryUnitTests(unittest.TestCase):
    def test_token_syntax(self):
        for value in ('', 'a' * 31, 'a' * 513, 'x' * 32 + '\n', 'x' * 32 + ' '):
            with self.assertRaises(BridgeError):
                validate_token(value)
        self.assertEqual(validate_token(TOKEN), TOKEN)

    def test_strict_envelopes(self):
        invalid = [b'[]', b'{"jsonrpc":"2.0","method":"ping","id":null}',
                   b'{"jsonrpc":"2.0","method":"ping","id":true}',
                   b'{"jsonrpc":"2.0","method":"ping","id":1.0}',
                   b'{"jsonrpc":"2.0","method":"ping","id":NaN}',
                   b'{"jsonrpc":"2.0","method":"ping","method":"tools/list"}',
                   b'{"jsonrpc":"2.0","id":1,"result":{}}', b'\xff', b'[' * 2000 + b']' * 2000]
        for raw in invalid:
            with self.subTest(raw=raw[:80]), self.assertRaises((ValueError, RecursionError)):
                parse_request(raw)

    def test_body_deadline_is_total_not_per_chunk(self):
        async def run():
            async def app(*args):
                raise AssertionError('must not dispatch')
            async def receive():
                await asyncio.sleep(.03)
                return {'type': 'http.request', 'body': b'x', 'more_body': True}
            messages = []
            async def send(message):
                messages.append(message)
            scope = {'type': 'http', 'path': '/mcp', 'method': 'POST', 'headers': [
                (b'host', b'127.0.0.1:8765'), (b'authorization', ('Bearer ' + TOKEN).encode()),
                (b'content-type', b'application/json'), (b'content-length', b'100'),
                (b'accept', b'application/json, text/event-stream')]}
            boundary = Boundary(app, TOKEN, 8765)
            with patch('bridge.streamable_http.BODY_TIMEOUT', .05):
                await boundary(scope, receive, send)
            self.assertEqual(messages[0]['status'], 408)
            self.assertEqual(boundary.in_flight, 0)
        asyncio.run(run())

    def test_timed_out_worker_keeps_admission_slot(self):
        event, entered = threading.Event(), threading.Event()
        class SlowBridge:
            def call(self, name, arguments):
                entered.set()
                event.wait(2)
                return 'done'
        async def run():
            reader = SingleReader(SlowBridge())
            try:
                with patch('bridge.streamable_http.TOOL_TIMEOUT', .02):
                    with self.assertRaisesRegex(BridgeError, 'timed out'):
                        await reader.call('fixture', {})
                self.assertTrue(entered.is_set())
                with self.assertRaisesRegex(BridgeError, 'busy'):
                    await reader.call('fixture', {})
                event.set()
                for _ in range(100):
                    if reader.slot.acquire(blocking=False):
                        reader.slot.release()
                        break
                    await asyncio.sleep(.005)
                self.assertEqual(await reader.call('fixture', {}), 'done')
            finally:
                event.set()
                reader.close()
        asyncio.run(run())


@unittest.skipUnless(SDK, 'optional HTTP SDK not installed; run pip install .[http]')
class StreamableHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.project = Path(cls.tmp.name)
        (cls.project / 'README.md').write_text('workspace fixture\n')
        config = cls.project / 'settings.json'
        config.write_text(json.dumps({'projects': {'demo': str(cls.project)}}))
        with socket.socket() as bound:
            bound.bind(('127.0.0.1', 0))
            cls.port = bound.getsockname()[1]
        cls.process = subprocess.Popen([sys.executable, '-m', 'bridge.server', '--config', str(config),
            '--transport', 'streamable-http', '--port', str(cls.port)], cwd=ROOT,
            env={**os.environ, 'BRIDGE_TOKEN': TOKEN}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(100):
            if cls.process.poll() is not None:
                raise AssertionError(cls.process.communicate()[1].decode())
            try:
                with socket.create_connection(('127.0.0.1', cls.port), .1):
                    return
            except OSError:
                time.sleep(.03)
        raise AssertionError('HTTP server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        stdout, stderr = cls.process.communicate(timeout=5)
        cls.tmp.cleanup()
        if stdout or stderr:
            raise AssertionError('Server should not print request data: ' + repr((stdout, stderr)))

    def request(self, value, *, headers=None, method='POST', path='/mcp'):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        values = {'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json',
                  'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25'}
        if headers:
            values.update(headers)
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        connection.request(method, path, raw, values)
        reply = connection.getresponse()
        result = reply.status, dict(reply.getheaders()), reply.read()
        connection.close()
        return result

    def rpc(self, method, params=None, id=1):
        request = {'jsonrpc': '2.0', 'id': id, 'method': method}
        if params is not None:
            request['params'] = params
        status, headers, body = self.request(request)
        return status, headers, json.loads(body)

    def test_negotiation_matrix(self):
        for offered, expected in [('2025-03-26', '2025-03-26'), ('2025-06-18', '2025-06-18'),
                                  ('2025-11-25', '2025-11-25'), ('2026-07-28', '2025-11-25'),
                                  ('2024-11-05', '2025-11-25')]:
            status, headers, result = self.rpc('initialize', {'protocolVersion': offered,
                'capabilities': {}, 'clientInfo': {'name': 'fixture', 'version': '1'}})
            self.assertEqual(status, 200)
            self.assertEqual(result['result']['protocolVersion'], expected)
            self.assertNotIn('Mcp-Session-Id', headers)
        status, _, _ = self.request({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                                    headers={'MCP-Protocol-Version': '2026-07-28'})
        self.assertEqual(status, 400)

    def test_notification_and_id_roundtrip(self):
        status, _, body = self.request({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        self.assertEqual((status, body), (202, b''))
        for request_id in (0, '', 'fixture', 15):
            self.assertEqual(self.rpc('ping', id=request_id)[2]['id'], request_id)
        self.assertEqual(self.rpc('not-a-method')[2]['error']['code'], -32601)

    def test_every_http_method_authenticates(self):
        for method in ('POST', 'GET', 'DELETE', 'OPTIONS', 'HEAD', 'PATCH'):
            status, _, _ = self.request({}, method=method, headers={'Authorization': 'invalid'})
            self.assertEqual(status, 401)
        for method in ('GET', 'DELETE', 'OPTIONS', 'HEAD', 'PATCH'):
            self.assertEqual(self.request({}, method=method)[0], 405)

    def test_origin_host_accept_and_paths(self):
        for headers, expected in [({'Origin': 'https://attacker.invalid'}, 403),
                ({'Origin': 'null'}, 403), ({'Host': 'attacker.invalid'}, 403),
                ({'Accept': 'application/json'}, 406),
                ({'Accept': 'application/json, text/event-stream;q=0'}, 406),
                ({'Content-Type': 'text/plain'}, 415)]:
            self.assertEqual(self.request({}, headers=headers)[0], expected)
        for path in ('/v1/call', '/mcp?token=private', '/mcp/', '/%6dcp'):
            self.assertEqual(self.request({}, path=path)[0], 404)

    def test_invalid_data_is_sanitized(self):
        marker = 'PRIVATE_FIXTURE_DO_NOT_ECHO'
        invalid = [b'{', b'[]', b'\xff', ('{"jsonrpc":"2.0","method":"ping","id":true,"x":"' + marker + '"}').encode()]
        for body in invalid:
            status, _, raw = self.request(body)
            self.assertEqual(status, 400)
            self.assertNotIn(marker.encode(), raw)
        status, _, raw = self.request(b' ' * 65537)
        self.assertEqual(status, 413)
        status, _, value = self.rpc('tools/call', {'name': 'read_file', 'arguments': {'project': 'other', 'path': marker}})
        self.assertTrue(value['result']['isError'])
        self.assertNotIn(marker, json.dumps(value))

    def test_tool_schemas_and_cross_project_denial(self):
        tools = self.rpc('tools/list')[2]['result']['tools']
        self.assertEqual(len(tools), 8)
        self.assertTrue(all(tool['annotations']['readOnlyHint'] for tool in tools))
        for name in ('exec', 'write_file', 'turn/start', 'thread/resume'):
            value = self.rpc('tools/call', {'name': name, 'arguments': {}})[2]
            self.assertTrue(value['result']['isError'])
        for project, path in [('other', 'README.md'), ('demo', '../outside'), ('demo', '.env')]:
            value = self.rpc('tools/call', {'name': 'read_file', 'arguments': {'project': project, 'path': path}})[2]
            self.assertTrue(value['result']['isError'])

    def test_official_sdk_client(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        import httpx
        async def run():
            async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + TOKEN}, trust_env=False) as http:
              async with streamable_http_client(f'http://127.0.0.1:{self.port}/mcp',
                http_client=http, terminate_on_close=False) as streams:
                async with ClientSession(streams[0], streams[1]) as client:
                    initialized = await client.initialize()
                    self.assertEqual(initialized.protocolVersion, '2025-11-25')
                    listed = await client.list_tools()
                    self.assertEqual(len(listed.tools), 8)
                    result = await client.call_tool('read_file', {'project': 'demo', 'path': 'README.md'})
                    self.assertFalse(result.isError)
                    self.assertIn('workspace fixture', result.content[0].text)
        asyncio.run(run())
