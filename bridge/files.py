import fnmatch
import os
import stat
import sys
from pathlib import Path

class BridgeError(Exception):
    pass

DENY = ('.*', '*.pem', '*.key', '*.p12', '*.pfx', '*credentials*', '*secret*',
        'id_rsa*', 'id_ed25519*', 'auth.json', 'config.json', '*token*')
SKIP = {'node_modules', '__pycache__', 'venv', 'dist', 'build'}

class Files:
    """Linux directory-FD traversal; every component is opened with NOFOLLOW."""
    def __init__(self, roots):
        if not isinstance(roots, dict) or not roots or not sys.platform.startswith('linux'):
            raise BridgeError('Configure project roots on Linux')
        self.roots = {}
        for name, path in roots.items():
            if not isinstance(path, str):
                raise BridgeError('Each project needs an absolute directory path')
            p = Path(path)
            if not p.is_absolute() or not p.is_dir() or p.resolve() == Path('/'):
                raise BridgeError('Each project needs an absolute, non-root directory')
            if p.resolve() in {Path.home().resolve(), Path('/home'), Path('/root'), Path('/etc'),
                               Path('/proc'), Path('/sys'), Path('/dev'), Path('/run'), Path('/boot')}:
                raise BridgeError('Choose a narrow project directory, not a home or system directory')
            if p.absolute() != p.resolve():
                raise BridgeError('Project roots must be canonical paths without symlinks or parent traversal')
            if any(any(fnmatch.fnmatch(part.lower(), pattern) for pattern in DENY) for part in p.parts[1:]):
                raise BridgeError('Project roots must not be inside hidden or sensitive-name directories')
            self.roots[name] = str(p.resolve())

    def parts(self, path):
        if not isinstance(path, str) or len(path) > 4096 or '\\' in path or '\x00' in path:
            raise BridgeError('Invalid path')
        if path in ('', '.'):
            return []
        parts = path.split('/')
        if any(p in ('', '.', '..') or any(fnmatch.fnmatch(p.lower(), pat) for pat in DENY)
               or p in SKIP for p in parts):
            raise BridgeError('Path not allowed')
        return parts

    def open(self, project, path='', directory=False):
        if project not in self.roots:
            raise BridgeError('Unknown project')
        parts = self.parts(path)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(self.roots[project], flags | os.O_DIRECTORY)
        try:
            for i, part in enumerate(parts):
                isdir = i < len(parts)-1 or directory
                nextfd = os.open(part, flags | (os.O_DIRECTORY if isdir else 0), dir_fd=fd)
                os.close(fd)
                fd = nextfd
            mode = os.fstat(fd).st_mode
            if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
                raise BridgeError('Unsupported file type')
            return fd
        except Exception:
            os.close(fd)
            raise

    def list(self, project, path=''):
        fd = self.open(project, path, directory=True)
        try:
            entries = []
            names = []
            with os.scandir(fd) as scan:
                for entry in scan:
                    if len(names) >= 10000:
                        raise BridgeError('Directory too large; choose a narrower directory')
                    names.append(entry.name)
            for name in sorted(names):
                try:
                    self.parts(name)
                    s = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode):
                        entries.append({'name': name, 'kind': 'directory' if stat.S_ISDIR(s.st_mode) else 'file'})
                except BridgeError:
                    pass
            return entries
        finally:
            os.close(fd)

    def read(self, project, path):
        fd = self.open(project, path)
        try:
            if os.fstat(fd).st_size > 262144:
                raise BridgeError('File exceeds 256 KiB')
            with os.fdopen(fd, 'rb', closefd=False) as f:
                data = f.read(262145)
            if len(data) > 262144 or b'\x00' in data:
                raise BridgeError('Binary or oversized file')
            return data.decode('utf-8')
        finally:
            os.close(fd)

    def search(self, project, query, path=''):
        if not isinstance(query, str) or not 1 <= len(query) <= 200:
            raise BridgeError('Query must contain 1–200 characters')
        pending = [(path, 0)]
        hits, scanned, visited = [], 0, 0
        truncated = False
        while pending:
            folder, depth = pending.pop()
            visited += 1
            if visited > 200 or scanned >= 500:
                truncated = True
                break
            for e in self.list(project, folder):
                p = '/'.join(x for x in (folder, e['name']) if x)
                if e['kind'] == 'directory':
                    if depth < 8 and visited + len(pending) < 200:
                        pending.append((p, depth+1))
                    else:
                        truncated = True
                    continue
                scanned += 1
                if scanned > 500:
                    truncated = True
                    break
                try:
                    content = self.read(project, p)
                except (BridgeError, OSError, UnicodeError):
                    continue
                for line, text in enumerate(content.splitlines(), 1):
                    if query in text:
                        hits.append({'path': p, 'line': line, 'text': text[:500]})
                        if len(hits) >= 100:
                            return {'hits': hits, 'truncated': True}
        return {'hits': hits, 'truncated': truncated}
