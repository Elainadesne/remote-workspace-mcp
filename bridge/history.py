"""Explicit thread allowlist, using the official read-only App Server API."""
import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from . import __version__
from .files import BridgeError

SECRET = re.compile(r'(?i)(bearer\s+\S+|(?:sk-|ghp_|github_pat_)[A-Za-z0-9_\-]{12,}|(?:password|api_key|access_token)\s*[:=]\s*[^\s,;]+)')
def redact(text):
    return SECRET.sub('[REDACTED]', text)

class AppServer:
    def __init__(self, binary, home):
        # Operator config only, never client-supplied command or arguments.
        if (not isinstance(binary, str) or not isinstance(home, str)
                or not Path(binary).is_absolute() or not Path(home).is_absolute()):
            raise BridgeError('Codex binary and home must be absolute paths')
        if not Path(binary).is_file() or not os.access(binary, os.X_OK) or not Path(home).is_dir():
            raise BridgeError('Configured Codex binary must be executable and Codex home must exist')
        self.binary, self.home = binary, home

    def read(self, thread_id, include_turns=True, *, paginated=False, cursor=None, expected_root=None):
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'LANG', 'SYSTEMROOT', 'TMPDIR')}
        env['CODEX_HOME'] = self.home
        try:
            p = subprocess.Popen([self.binary, 'app-server'], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        except OSError as e:
            raise BridgeError('Cannot start configured Codex App Server') from e
        messages = queue.Queue(maxsize=32)
        stopped = threading.Event()
        def reader():
            try:
                while not stopped.is_set():
                    line = p.stdout.readline(32 * 1024 * 1024 + 1)
                    if not line:
                        messages.put({'bridge_error': 'Codex App Server closed its output'}, timeout=1)
                        break
                    if len(line) > 32 * 1024 * 1024:
                        messages.put({'bridge_error': 'Codex response exceeds 32 MiB; try metadata-only reading'}, timeout=1)
                        break
                    msg = json.loads(line)
                    if not isinstance(msg, dict):
                        raise ValueError('Non-object response')
                    if 'id' in msg:
                        messages.put(msg, timeout=1)
            except (ValueError, OSError, RecursionError):
                try:
                    messages.put({'bridge_error': 'Codex returned an invalid protocol response'}, timeout=1)
                except queue.Full:
                    pass
            except queue.Full:
                pass
            finally:
                try:
                    messages.put(None, timeout=1)
                except queue.Full:
                    pass
        worker = threading.Thread(target=reader, daemon=True)
        worker.start()
        deadline = time.monotonic() + 20
        def send(obj):
            p.stdin.write((json.dumps(obj)+'\n').encode())
            p.stdin.flush()
        def rpc(n, method, params):
            send({'id': n, 'method': method, 'params': params})
            while True:
                if time.monotonic() >= deadline:
                    raise BridgeError('Codex App Server timed out')
                try:
                    msg = messages.get(timeout=max(.01, deadline-time.monotonic()))
                except queue.Empty as e:
                    raise BridgeError('Codex App Server timed out') from e
                if msg is None:
                    raise BridgeError('Codex App Server output ended before the response')
                if 'bridge_error' in msg:
                    raise BridgeError(msg['bridge_error'])
                if 'method' in msg:
                    # Deny ALL server-initiated actions/approvals.
                    send({'id': msg['id'], 'error': {'code': -32601, 'message': 'Read-only bridge'}})
                    continue
                if msg.get('id') == n:
                    if 'error' in msg:
                        raise BridgeError('Codex read failed; check version, user environment and thread ID')
                    result = msg.get('result')
                    if not isinstance(result, dict):
                        raise BridgeError('Unsupported Codex response')
                    return result
        try:
            rpc(1, 'initialize', {'clientInfo': {'name': 'vm_codex_bridge', 'version': __version__},
                                  'capabilities': {'experimentalApi': paginated}})
            send({'method': 'initialized', 'params': {}})
            thread = rpc(2, 'thread/read', {'threadId': thread_id, 'includeTurns': False if paginated else include_turns})['thread']
            if not isinstance(thread, dict):
                raise BridgeError('Unsupported Codex thread response')
            if paginated:
                cwd = thread.get('cwd')
                if (thread.get('id') != thread_id or not isinstance(cwd, str)
                    or not Path(cwd).is_absolute() or expected_root is None
                    or not Path(cwd).resolve().is_relative_to(Path(expected_root).resolve())):
                    raise BridgeError('Thread is outside allowed project or has invalid identity')
                params = {'threadId': thread_id, 'limit': 1, 'itemsView': 'full', 'sortDirection': 'desc'}
                if cursor is not None:
                    params['cursor'] = cursor
                page = rpc(3, 'thread/turns/list', params)
                if not isinstance(page.get('data'), list) or len(page['data']) > 1:
                    raise BridgeError('Unsupported paginated response')
                validate_cursor(page.get('nextCursor'))
                thread['turns'] = page['data']
                thread['nextCursor'] = page.get('nextCursor')
                thread['paginated'] = True
            return thread
        except (KeyError, BrokenPipeError, OSError) as e:
            raise BridgeError('Unsupported Codex response') from e
        finally:
            stopped.set()
            p.terminate()
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            worker.join(timeout=2)
            p.stdin.close()
            p.stdout.close()

class History:
    def __init__(self, files, config, reader=None):
        self.files = files
        self.allowed = config.get('threads', {})
        self.imports = config.get('imports', {})
        self.reader = reader
        self.app = None
        if config.get('enabled') and reader is None:
            self.app = AppServer(config['binary'], config['home'])

    def list(self, project):
        if project not in self.files.roots:
            raise BridgeError('Unknown project')
        return [{'id': tid, 'source': 'codex'} for tid, p in self.allowed.items() if p == project] + [
            {'id': tid, 'source': 'import'} for tid, spec in self.imports.items() if spec['project'] == project]

    def read(self, project, thread_id, cursor=None):
        if project not in self.files.roots:
            raise BridgeError('Unknown project')
        if thread_id in self.imports:
            if cursor is not None:
                raise BridgeError('Imports do not accept pagination cursors')
            spec = self.imports[thread_id]
            if spec['project'] != project:
                raise BridgeError('Thread not allowed')
            # Imported files are explicitly operator-selected, inside project roots.
            doc = json.loads(self.files.read(project, spec['path']))
            if not isinstance(doc, dict) or not isinstance(doc.get('messages'), list):
                raise BridgeError('Import must be an object containing a messages array')
            raw = doc.get('messages', [])
            if any(not isinstance(m, dict) for m in raw):
                raise BridgeError('Import messages must be objects')
            msgs = [{'role': m['role'], 'text': redact(m['text'])} for m in raw
                    if m.get('role') in ('user', 'assistant') and isinstance(m.get('text'), str)]
            return self.finish(thread_id, msgs, 'import')
        if self.allowed.get(thread_id) != project:
            raise BridgeError('Thread not allowed')
        if self.reader is None and self.app is None:
            raise BridgeError('Codex history is disabled; configure it or use reviewed imports')
        if self.app is not None:
            thread = self.app.read(thread_id, paginated=True, cursor=cursor, expected_root=self.files.roots[project])
        else:
            if cursor is not None:
                raise BridgeError('This reader does not support cursors')
            thread = self.reader(thread_id)
        if not isinstance(thread, dict):
            raise BridgeError('Unsupported Codex thread response')
        if thread.get('id') != thread_id:
            raise BridgeError('Thread identity mismatch')
        cwd = thread.get('cwd')
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise BridgeError('Thread has no verifiable project directory')
        if not Path(cwd).resolve().is_relative_to(Path(self.files.roots[project])):
            raise BridgeError('Thread is outside allowed project')
        msgs = []
        for turn in object_list(thread.get('turns', [])):
            for item in object_list(turn.get('items', [])):
                if item.get('type') == 'userMessage':
                    text = '\n'.join(c['text'] for c in object_list(item.get('content', []))
                                     if c.get('type') == 'text' and isinstance(c.get('text'), str))
                    msgs.append({'role': 'user', 'text': redact(text)})
                elif item.get('type') == 'agentMessage' and item.get('phase') in (None, 'final_answer', 'commentary'):
                    if isinstance(item.get('text'), str):
                        msgs.append({'role': 'assistant', 'text': redact(item['text'])})
                # No reasoning, system/developer instructions or tool output.
        out = self.finish(thread_id, msgs, 'codex')
        validate_cursor(thread.get('nextCursor'))
        out['next_cursor'] = thread.get('nextCursor')
        out['has_more'] = bool(thread.get('nextCursor'))
        out['order'] = 'newest_turn_first' if thread.get('paginated') else 'stored_order'
        return out

    @staticmethod
    def finish(tid, msgs, source):
        if len(msgs) > 2000 or sum(len(m['text']) for m in msgs) > 1000000:
            raise BridgeError('History too large; import a selected excerpt')
        return {'id': tid, 'source': source, 'messages': msgs,
                'warning': 'Secret masking is best-effort. Only authorize reviewed conversations.'}


def object_list(value):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise BridgeError('Unsupported Codex history structure')
    return value


def validate_cursor(cursor):
    if cursor is not None and (not isinstance(cursor, str) or not 0 < len(cursor) <= 4096):
        raise BridgeError('Unsupported pagination cursor')
