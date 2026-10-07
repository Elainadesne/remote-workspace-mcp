"""Public-use regressions. Fixtures contain no real sessions or credentials."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from bridge.config import load_config
from bridge.files import BridgeError, Files
from bridge.server import Bridge, mcp
import diagnose_history

REPO = Path(__file__).resolve().parents[1]


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'projects': {'demo': str(self.root)}}
        self.settings = self.root / 'settings.json'
        self.settings.write_text(json.dumps(self.config), encoding='utf-8')
        self.bridge = Bridge(self.config)

    def run_stdio(self, messages):
        return subprocess.run([sys.executable, '-m', 'bridge.server', '--config', str(self.settings)],
                              input='\n'.join(messages) + '\n', text=True, capture_output=True,
                              timeout=5, cwd=REPO)

    def test_config_rejects_malformed_shapes_and_typo_keys(self):
        cases = [[], {}, {'projects': []}, {'projects': {'': str(self.root)}},
                 {'projects': {'../demo': str(self.root)}}, {'projects': {'demo': 'relative'}},
                 {**self.config, 'unknown': True}]
        for value in ([], {'enabled': 'false'}, {'threads': []}, {'imports': []},
                      {'binary': 'codex'}, {'enabled': True}, {'threads': {'t': 'missing'}},
                      {'imports': {'i': []}}, {'imports': {'i': {'project': 'demo'}}},
                      {'imports': {'i': {'project': 'missing', 'path': 'file.json'}}},
                      {'threads': {'same': 'demo'}, 'imports': {'same': {'project': 'demo', 'path': 'f'}}}):
            cases.append({**self.config, 'codex': value})
        for config in cases:
            with self.subTest(config=config), self.assertRaises(BridgeError):
                Bridge(config)

    def test_config_rejects_duplicate_keys(self):
        self.settings.write_text('{"projects": {}, "projects": {}}')
        with self.assertRaisesRegex(BridgeError, 'Duplicate'):
            load_config(self.settings)

    def test_config_size_and_depth_bounds(self):
        for raw in (' ' * 65537, '[' * 2000 + ']' * 2000):
            self.settings.write_text(raw)
            with self.assertRaises(BridgeError):
                load_config(self.settings)

    def test_config_rejects_unsafe_import_paths(self):
        for path in ('.', '../outside', '/absolute', '.hidden/file', 'secret.json'):
            config = {**self.config, 'codex': {'imports': {'i': {'project': 'demo', 'path': path}}}}
            with self.subTest(path=path), self.assertRaises(BridgeError):
                Bridge(config)

    def test_home_and_system_roots_are_rejected(self):
        for path in (str(Path.home()), '/', '/etc', '/proc', '/dev', '/sys'):
            with self.subTest(path=path), self.assertRaises(BridgeError):
                Files({'demo': path})

    def test_symlink_root_is_rejected(self):
        target = self.root / 'project'
        target.mkdir()
        alias = self.root / 'alias'
        alias.symlink_to(target, target_is_directory=True)
        with self.assertRaises(BridgeError):
            Files({'demo': str(alias)})

    def test_sensitive_root_components_are_rejected(self):
        for name in ('.codex', '.ssh', 'credentials', 'secrets'):
            path = self.root / name / 'project'
            path.mkdir(parents=True)
            with self.subTest(name=name), self.assertRaises(BridgeError):
                Files({'demo': str(path)})

    def test_codex_home_must_not_overlap_projects(self):
        project = self.root / 'project'
        project.mkdir()
        for home in (self.root, project, project / 'codex-data'):
            config = {'projects': {'demo': str(project)}, 'codex': {'home': str(home)}}
            with self.subTest(home=home), self.assertRaises(BridgeError):
                Bridge(config)

    def test_large_directory_stops_scanning_at_limit(self):
        class Entry:
            name = 'fixture'
        def entries():
            for _ in range(10001):
                yield Entry()
            raise AssertionError('must not scan beyond the directory limit')
        with patch('bridge.files.os.scandir') as scan:
            scan.return_value.__enter__.return_value = entries()
            with self.assertRaisesRegex(BridgeError, 'Directory too large'):
                self.bridge.files.list('demo')

    def test_search_limits_queued_directories(self):
        visits = []
        def listing(project, path):
            visits.append(path)
            if not path:
                return [{'name': f'dir-{i}', 'kind': 'directory'} for i in range(1000)]
            return []
        with patch.object(self.bridge.files, 'list', side_effect=listing):
            result = self.bridge.files.search('demo', 'needle')
        self.assertTrue(result['truncated'])
        self.assertEqual(len(visits), 200)

    def test_check_config_does_not_start_subprocess(self):
        with patch('bridge.history.subprocess.Popen', side_effect=AssertionError('must not start')):
            with patch.object(sys, 'argv', ['bridge', '--config', str(self.settings), '--check-config']):
                from bridge.server import main
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    main()
        self.assertIn('Configuration valid', stdout.getvalue())

    def test_config_error_has_no_traceback_or_private_path(self):
        result = subprocess.run([sys.executable, '-m', 'bridge.server', '--config',
                                 str(self.root / 'private-missing-file')], capture_output=True,
                                text=True, cwd=REPO, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
        self.assertEqual(result.stdout, '')

    def test_invalid_tool_name_is_tool_error(self):
        result = mcp(self.bridge, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                   'params': {'name': []}})
        self.assertTrue(result['result']['isError'])

    def test_invalid_mcp_params_are_protocol_errors(self):
        for params in ([], None, 'text', 1):
            result = mcp(self.bridge, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': params})
            self.assertEqual(result['error']['code'], -32602)

    def test_invalid_mcp_request_fields(self):
        for msg in ([], {'jsonrpc': '2.0', 'id': {}, 'method': 'ping'},
                    {'jsonrpc': '2.0', 'id': True, 'method': 'ping'},
                    {'jsonrpc': '2.0', 'id': 1, 'method': []}):
            self.assertEqual(mcp(self.bridge, msg)['error']['code'], -32600)

    def test_stdio_survives_malformed_and_deep_json_and_surrogate_id(self):
        messages = ['{', '[' * 2000 + ']' * 2000,
                    json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': []}),
                    json.dumps({'jsonrpc': '2.0', 'id': '\ud800', 'method': 'ping'}),
                    json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'})]
        result = self.run_stdio(messages)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(replies), 5)
        self.assertEqual(replies[-1], {'jsonrpc': '2.0', 'id': 2, 'result': {}})

    def test_surrogate_filename_is_json_serializable(self):
        raw_path = os.fsencode(self.root) + b'/invalid-\xff-name'
        with open(raw_path, 'wb') as stream:
            stream.write(b'fixture')
        result = self.run_stdio([json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                            'params': {'name': 'list_files', 'arguments': {'project': 'demo'}}})])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('content', json.loads(result.stdout)['result'])

    def test_import_malformed_shapes_fail_closed(self):
        path = self.root / 'reviewed.json'
        bridge = Bridge({**self.config, 'codex': {'imports': {'i': {'project': 'demo', 'path': path.name}}}})
        for value in ([], None, {}, {'messages': None}, {'messages': ['text']}, {'messages': [None]}):
            path.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(BridgeError):
                bridge.history.read('demo', 'i')

    def test_malformed_history_structures_fail_closed(self):
        base = {'id': 't1', 'cwd': str(self.root), 'turns': []}
        cases = [[], None, {**base, 'turns': None}, {**base, 'turns': [None]},
                 {**base, 'turns': [{'items': [None]}]},
                 {**base, 'turns': [{'items': [{'type': 'userMessage', 'content': [None]}]}]},
                 {**base, 'nextCursor': ['bad']}]
        config = {**self.config, 'codex': {'threads': {'t1': 'demo'}}}
        for value in cases:
            bridge = Bridge(config, reader=lambda tid: value)
            with self.subTest(value=value), self.assertRaises(BridgeError):
                bridge.history.read('demo', 't1')

    def test_diagnostic_requires_explicit_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            diagnose_history.main([])
        self.assertEqual(result.exception.code, 2)

    def test_diagnostic_prints_counts_not_content_or_paths(self):
        path = self.root / 'reviewed.json'
        path.write_text(json.dumps({'messages': [{'role': 'user', 'text': 'PRIVATE_CONVERSATION_MARKER'}]}))
        config = {**self.config, 'codex': {'imports': {'sample': {'project': 'demo', 'path': path.name}}}}
        self.settings.write_text(json.dumps(config))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = diagnose_history.main(['--config', str(self.settings), '--project', 'demo', '--thread-id', 'sample'])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue()), {'ok': True, 'source': 'import',
                                                        'public_messages': 1, 'has_more': False})

    def test_diagnostic_rejects_nonallowlisted_thread(self):
        with patch('bridge.history.subprocess.Popen', side_effect=AssertionError('must not start')):
            with contextlib.redirect_stderr(io.StringIO()) as output:
                result = diagnose_history.main(['--config', str(self.settings), '--project', 'demo', '--thread-id', 'other'])
        self.assertEqual(result, 1)
        self.assertIn('Thread not allowed', output.getvalue())

    def test_retired_updater_does_not_change_files(self):
        before = sorted(str(p) for p in self.root.rglob('*'))
        result = subprocess.run([sys.executable, str(REPO / 'upgrade_bridge.py')], cwd=self.root,
                                env={**os.environ, 'HOME': str(self.root)}, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))
        self.assertIn('No files were changed', result.stderr)


if __name__ == '__main__':
    unittest.main()
