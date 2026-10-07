import argparse
import hmac
import json
import os
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from . import __version__
from .config import load_config, validate_config
from .files import Files, BridgeError
from .history import History

TOOLS = {
    'list_projects': {},
    'list_files': {'project': 'string', 'path': 'string'},
    'read_file': {'project': 'string', 'path': 'string'},
    'search_text': {'project': 'string', 'query': 'string', 'path': 'string'},
    'list_threads': {'project': 'string'},
    'read_thread': {'project': 'string', 'thread_id': 'string', 'cursor': 'string'},
}
REQUIRED = {'list_projects': [], 'list_files': ['project'], 'read_file': ['project', 'path'],
            'search_text': ['project', 'query'], 'list_threads': ['project'], 'read_thread': ['project', 'thread_id']}

def tool_specs():
    return [{'name': name, 'description': 'Read-only '+name.replace('_', ' '),
             'inputSchema': {'type': 'object', 'properties': {k: {'type': t} for k, t in args.items()},
                             'required': REQUIRED[name], 'additionalProperties': False},
             'annotations': {'readOnlyHint': True, 'destructiveHint': False}}
            for name, args in TOOLS.items()]

class Bridge:
    def __init__(self, config, reader=None):
        validate_config(config)
        self.files = Files(config['projects'])
        codex_home = config.get('codex', {}).get('home')
        if codex_home:
            home = Path(codex_home).resolve()
            if any(Path(root).is_relative_to(home) or home.is_relative_to(Path(root))
                   for root in self.files.roots.values()):
                raise BridgeError('Project directories and Codex home must not overlap')
        for spec in config.get('codex', {}).get('imports', {}).values():
            if not self.files.parts(spec['path']):
                raise BridgeError('Imports must select a file with a relative path')
        self.history = History(self.files, config.get('codex', {}), reader)
    def call(self, name, args):
        if not isinstance(name, str) or name not in TOOLS or not isinstance(args, dict):
            raise BridgeError('Unknown tool or invalid arguments')
        if set(args)-set(TOOLS[name]) or not set(REQUIRED[name]) <= set(args):
            raise BridgeError('Unexpected or missing argument')
        if any(not isinstance(v, str) or len(v) > 4096 for v in args.values()):
            raise BridgeError('Arguments must be short strings')
        if name == 'list_projects':
            return sorted(self.files.roots)  # Do not leak absolute paths.
        if name == 'list_threads':
            return self.history.list(**args)
        if name == 'read_thread':
            return self.history.read(**args)
        if name == 'list_files':
            return self.files.list(**args)
        if name == 'read_file':
            return {'text': self.files.read(**args)}
        return self.files.search(**args)

def mcp(bridge, msg):
    if (not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0'
            or not isinstance(msg.get('method'), str)
            or ('id' in msg and (isinstance(msg['id'], bool)
                or not isinstance(msg['id'], (str, int, type(None)))))):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
    if 'id' not in msg:
        return None
    result = {'jsonrpc': '2.0', 'id': msg['id']}
    method = msg.get('method')
    if 'params' in msg and not isinstance(msg['params'], dict):
        result['error'] = {'code': -32602, 'message': 'Params must be an object'}
        return result
    try:
        if method == 'initialize':
            result['result'] = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                                'serverInfo': {'name': 'vm-codex-bridge', 'version': __version__}}
        elif method == 'ping':
            result['result'] = {}
        elif method == 'tools/list':
            result['result'] = {'tools': tool_specs()}
        elif method == 'tools/call':
            p = msg.get('params', {})
            value = bridge.call(p.get('name'), p.get('arguments', {}))
            result['result'] = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]}
        else:
            result['error'] = {'code': -32601, 'message': 'Method not supported'}
    except (BridgeError, OSError, ValueError, KeyError, TypeError, RecursionError) as e:
        error = str(e) if isinstance(e, BridgeError) else 'Read failed; inspect operator configuration'
        result['result'] = {'isError': True, 'content': [{'type': 'text', 'text': error}]}
    return result

def http_server(bridge, token, port):
    if not isinstance(token, str) or len(token) < 32:
        raise BridgeError('Set BRIDGE_TOKEN to at least 32 characters before HTTP startup')
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)
        def log_message(self, *args):
            pass  # Never log paths, content, query text or Authorization headers.
        def reply(self, status, obj):
            data = json.dumps(obj, ensure_ascii=True).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            # Local HTTP is for SSH forwarding/trusted gateways, never direct public exposure.
            if self.headers.get('Origin') is not None:
                return self.reply(403, {'error': 'Browser origins are not supported'})
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                return self.reply(403, {'error': 'Invalid host'})
            auth = self.headers.get('Authorization', '')
            if not hmac.compare_digest(auth.encode(), ('Bearer '+token).encode()):
                return self.reply(401, {'error': 'Unauthorized'})
            if self.path != '/v1/call':
                return self.reply(404, {'error': 'Not found'})
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
                return self.reply(400, {'error': 'JSON with Content-Length required'})
            try:
                size = int(self.headers.get('Content-Length', '-1'))
                if not 0 < size <= 65536:
                    return self.reply(413, {'error': 'Invalid body size'})
                raw = self.rfile.read(size)
                if len(raw) != size:
                    return self.reply(400, {'error': 'Incomplete body'})
                req = json.loads(raw)
                if not isinstance(req, dict) or set(req) != {'name', 'arguments'}:
                    raise BridgeError('Expected name and arguments')
                value = bridge.call(req['name'], req['arguments'])
                self.reply(200, {'result': value})
            except (BridgeError, OSError, ValueError, KeyError, TypeError, RecursionError) as e:
                self.reply(400, {'error': str(e) if isinstance(e, BridgeError) else 'Read failed'})
    # Single operator server intentionally serializes access. Not a public multiuser server.
    return HTTPServer(('127.0.0.1', port), Handler)

def main():
    parser = argparse.ArgumentParser(description='Read-only VM files and Codex history')
    parser.add_argument('--config', required=True)
    parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--check-config', action='store_true',
                        help='Validate settings and local paths, without starting a server or Codex')
    args = parser.parse_args()
    try:
        bridge = Bridge(load_config(args.config))
    except (BridgeError, OSError) as error:
        parser.exit(2, f'Configuration error: {error if isinstance(error, BridgeError) else "check local paths and permissions"}\n')
    if args.check_config:
        print('Configuration valid; no server or Codex process started')
        return
    if args.transport == 'http':
        server = http_server(bridge, os.environ.get('BRIDGE_TOKEN', ''), args.port)
        print(f'Listening on loopback port {server.server_port}', file=sys.stderr)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    else:
        while True:
            line = sys.stdin.buffer.readline(65537)
            if not line:
                break
            if len(line) > 65536:
                raise BridgeError('Input exceeds 64 KiB')
            try:
                msg = json.loads(line)
                reply = mcp(bridge, msg)
            except (ValueError, RecursionError):
                reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Invalid JSON'}}
            if reply is not None:
                print(json.dumps(reply, ensure_ascii=True), flush=True)

if __name__ == '__main__':
    main()
