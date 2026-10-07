"""Configuration template contracts, not real harness end-to-end tests."""
import json
from pathlib import Path
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


class ClientTemplateTests(unittest.TestCase):
    def load(self, name):
        return json.loads((ROOT / 'examples' / 'clients' / name).read_text())

    def test_zcode_native_layout_and_legacy_selection(self):
        for transport in ('http', 'stdio'):
            document = self.load(f'zcode-{transport}.json')
            server = document['mcp']['servers']['remote-workspace']
            self.assertNotIn('mcpServers', document)
            self.assertEqual(server['type'], transport)
            self.assertEqual(server['protocolVersion'], 'legacy')
            self.assertGreaterEqual(server['timeoutMs'], 27000)
        auth = self.load('zcode-http.json')['mcp']['servers']['remote-workspace']['headers']['Authorization']
        self.assertEqual(auth, 'Bearer <operator-provided BRIDGE_TOKEN>')
        self.assertNotIn('${', auth)  # No unverified native interpolation promise.

    def test_claude_http_documents_environment_interpolation(self):
        server = self.load('claude-http.json')['mcpServers']['remote-workspace']
        self.assertEqual(server['type'], 'http')
        self.assertEqual(server['headers'], {'Authorization': 'Bearer ${BRIDGE_TOKEN}'})

    def test_every_http_url_uses_loopback_mcp_without_query(self):
        for filename in ('zcode-http.json', 'claude-http.json'):
            config = self.load(filename)
            servers = config.get('mcpServers') or config['mcp']['servers']
            url = urlsplit(servers['remote-workspace']['url'])
            self.assertEqual((url.scheme, url.hostname, url.port, url.path),
                             ('http', '127.0.0.1', 8765, '/mcp'))
            self.assertFalse(url.query)
            self.assertFalse(url.username)

    def test_stdio_templates_use_existing_transport(self):
        for filename in ('zcode-stdio.json', 'claude-stdio.json'):
            config = self.load(filename)
            servers = config.get('mcpServers') or config['mcp']['servers']
            server = servers['remote-workspace']
            self.assertEqual(server['type'], 'stdio')
            self.assertEqual(server['args'][-2:], ['--transport', 'stdio'])
            self.assertIn('--config', server['args'])
            self.assertNotIn('headers', server)
            self.assertNotIn('env', server)

    def test_version_and_dependency_metadata(self):
        import tomllib
        from bridge import __version__
        config = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        self.assertEqual(config['project']['version'], __version__)
        self.assertEqual(config['project']['dependencies'], [])
        self.assertIn('mcp>=1.30.0,<2', config['project']['optional-dependencies']['http'])
