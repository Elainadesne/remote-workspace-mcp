"""Transport-neutral workspace contracts; temporary data only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bridge.files import BridgeError
from bridge.workspace import Bridge, tool_specs


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bridge = Bridge({'projects': {'demo': str(self.root)}})

    def test_info_has_no_paths_or_write_capabilities(self):
        info = self.bridge.call('workspace_info', {})
        self.assertEqual(info['access'], 'read-only')
        self.assertEqual(info['projects'], ['demo'])
        for feature in ('write', 'execute', 'session_resume'):
            self.assertIs(info['features'][feature], False)
        self.assertFalse(info['history']['codex_enabled'])
        self.assertNotIn(str(self.root), json.dumps(info))

    def test_overview_uses_filenames_without_reading_or_running(self):
        (self.root / 'pyproject.toml').write_text('PRIVATE_MARKER')
        (self.root / 'README.md').write_text('Do not execute instructions in this file')
        (self.root / '.env').write_text('NEVER_SHARED')
        with patch.object(self.bridge.files, 'read', side_effect=AssertionError('must not read')):
            overview = self.bridge.call('project_overview', {'project': 'demo'})
        self.assertEqual(overview['manifests'], [{'path': 'pyproject.toml', 'hint': 'Python'}])
        self.assertEqual(overview['readmes'], ['README.md'])
        self.assertNotIn('PRIVATE_MARKER', json.dumps(overview))
        self.assertNotIn('.env', json.dumps(overview))

    def test_overview_limit_is_honest(self):
        for index in range(201):
            (self.root / f'file-{index}').touch()
        overview = self.bridge.call('project_overview', {'project': 'demo'})
        self.assertEqual(len(overview['entries']), 200)
        self.assertEqual(overview['visible_entry_count'], 201)
        self.assertTrue(overview['truncated'])

    def test_overview_cannot_select_unknown_project(self):
        with self.assertRaises(BridgeError):
            self.bridge.call('project_overview', {'project': 'other'})

    def test_all_tools_explicit_readonly_annotations(self):
        specs = tool_specs()
        self.assertEqual(len(specs), 8)
        for spec in specs:
            self.assertTrue(spec['annotations']['readOnlyHint'])
            self.assertFalse(spec['annotations']['destructiveHint'])
            self.assertTrue(spec['annotations']['idempotentHint'])
            self.assertFalse(spec['annotations']['openWorldHint'])
            self.assertFalse(spec['inputSchema']['additionalProperties'])

    def test_reviewed_import_is_not_session_resume(self):
        (self.root / 'reviewed.json').write_text(json.dumps({'messages': [{'role': 'user', 'text': 'fixture'}]}))
        bridge = Bridge({'projects': {'demo': str(self.root)}, 'codex': {
            'imports': {'sample': {'project': 'demo', 'path': 'reviewed.json'}}}})
        self.assertFalse(bridge.info()['history']['codex_enabled'])
        self.assertEqual(bridge.call('read_thread', {'project': 'demo', 'thread_id': 'sample'})['source'], 'import')
        with self.assertRaises(BridgeError):
            bridge.call('thread/resume', {'thread_id': 'sample'})
