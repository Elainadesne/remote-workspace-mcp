"""Validate operator-owned settings without starting Codex or any service."""
import json
from pathlib import Path
import re

from .files import BridgeError

MAX_CONFIG_BYTES = 65536
ALIAS = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')


def _object(value, allowed, label):
    if not isinstance(value, dict) or set(value) - allowed:
        raise BridgeError(f'{label} must be an object with only documented keys')


def _short_string(value):
    return isinstance(value, str) and 0 < len(value) <= 4096 and '\x00' not in value


def validate_config(config):
    _object(config, {'projects', 'codex'}, 'Config')
    projects = config.get('projects')
    if not isinstance(projects, dict) or not projects:
        raise BridgeError('Configure at least one project alias and absolute directory')
    for alias, path in projects.items():
        if not isinstance(alias, str) or not ALIAS.fullmatch(alias):
            raise BridgeError('Project aliases must be 1-64 letters, digits, underscores or hyphens')
        if not _short_string(path) or not Path(path).is_absolute():
            raise BridgeError('Each project needs an absolute directory path')
    codex = config.get('codex', {})
    _object(codex, {'enabled', 'binary', 'home', 'threads', 'imports'}, 'Codex config')
    if not isinstance(codex.get('enabled', False), bool):
        raise BridgeError('codex.enabled must be true or false')
    for key in ('binary', 'home'):
        value = codex.get(key)
        if key in codex or codex.get('enabled'):
            if not _short_string(value) or not Path(value).is_absolute():
                raise BridgeError('Codex binary and home must be absolute paths')
    threads, imports = codex.get('threads', {}), codex.get('imports', {})
    if not isinstance(threads, dict) or not isinstance(imports, dict):
        raise BridgeError('codex.threads and codex.imports must be objects')
    if set(threads) & set(imports):
        raise BridgeError('Thread IDs and import aliases must not overlap')
    for tid, project in threads.items():
        if not _short_string(tid) or not isinstance(project, str) or project not in projects:
            raise BridgeError('Each thread ID must reference a configured project alias')
    for alias, spec in imports.items():
        if not _short_string(alias):
            raise BridgeError('Import aliases must be nonempty short strings')
        _object(spec, {'project', 'path'}, 'Import config')
        if (set(spec) != {'project', 'path'} or not isinstance(spec['project'], str)
                or spec['project'] not in projects or not _short_string(spec['path'])):
            raise BridgeError('Each import needs a configured project and relative path')
    return config


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BridgeError('Duplicate JSON configuration keys are not allowed')
        result[key] = value
    return result


def load_config(path):
    try:
        with open(path, 'rb') as stream:
            data = stream.read(MAX_CONFIG_BYTES + 1)
        if len(data) > MAX_CONFIG_BYTES:
            raise BridgeError('Config exceeds 64 KiB')
        config = json.loads(data, object_pairs_hook=_unique_keys)
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        raise BridgeError('Cannot read config; use an accessible UTF-8 JSON file') from error
    return validate_config(config)
