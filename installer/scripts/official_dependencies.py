"""Pinned official downloads for local use, never redistributed or logged in."""
import hashlib
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def lock():
    return json.loads((ROOT / 'references/official-dependencies.json').read_text())


def tree_hash(files):
    return digest(json.dumps({n: digest(b) for n, b in sorted(files.items())},
                             sort_keys=True, separators=(',', ':')).encode())


def tree_files(path):
    if path.is_symlink() or not path.is_dir():
        raise ValueError('EXISTING_PATH_CONFLICT')
    files = {}
    for p in sorted(path.rglob('*')):
        if p.is_symlink():
            raise ValueError('EXISTING_SYMLINK_CONFLICT')
        if p.is_file():
            files[p.relative_to(path).as_posix()] = p.read_bytes()
    return files


def state(name, destination):
    if destination.is_symlink():
        return 'external_conflict'
    if not destination.exists():
        return 'external_missing'
    for source in lock()['providers'].values():
        if name in source['skills']:
            try:
                return ('external_verified' if tree_hash(tree_files(destination)) == source['skills'][name]['tree_sha256']
                        else 'external_present_unverified_or_modified')
            except (OSError, ValueError):
                return 'external_conflict'
    return 'external_present_unverified_or_modified'


def guard(root, path):
    for p in [path, *path.parents]:
        if p.is_symlink():
            raise ValueError('SYMLINK_PRESERVED')
        if p == root:
            break


def download(spec, cache, ca_bundle=None):
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / spec['sha256']
    guard(cache, dest)
    if dest.exists():
        if not dest.is_file() or digest(dest.read_bytes()) != spec['sha256']:
            raise ValueError('CACHE_CONFLICT: preserve cache; select a new tool-root or review the changed file')
        return dest.read_bytes()
    curl = shutil.which('curl')
    if not curl:
        raise ValueError('CURL_MISSING: install curl from your OS/vendor; TLS verification is required')
    with tempfile.TemporaryDirectory(prefix='.download-', dir=cache) as tmp:
        target = Path(tmp) / 'artifact'
        command = [curl, '--fail', '--silent', '--show-error', '--location', '--proto', '=https',
                   '--proto-redir', '=https', '--max-time', '60', '--max-filesize', '134217728',
                   '--output', str(target), spec['url']]
        if ca_bundle:
            command += ['--cacert', str(ca_bundle)]
        try:
            result = subprocess.run(command, capture_output=True, timeout=65)
        except subprocess.TimeoutExpired:
            raise ValueError('OFFICIAL_DOWNLOAD_TIMEOUT: rerun the same command to resume') from None
        if result.returncode:
            raise ValueError('OFFICIAL_DOWNLOAD_FAILED: curl exit ' + str(result.returncode) +
                             '; check network/TLS/proxy, then rerun; no target files changed')
        data = target.read_bytes()
        if digest(data) != spec['sha256']:
            raise ValueError('OFFICIAL_HASH_MISMATCH: no installation; source/version needs maintainer review')
        target.rename(dest)
        return data


def archive_files(data):
    files = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            name = member.name
            if name.startswith('/') or '..' in Path(name).parts or '\\' in name:
                raise ValueError('UNSAFE_OFFICIAL_ARCHIVE_PATH')
            if member.isdir():
                continue
            if not member.isfile() or name in files:
                raise ValueError('UNSAFE_OFFICIAL_ARCHIVE_TYPE_OR_DUPLICATE')
            total += member.size
            if total > 134217728:
                raise ValueError('OFFICIAL_ARCHIVE_TOO_LARGE')
            files[name] = archive.extractfile(member).read()
    return files


def install(args):
    source = lock()['providers'][args.provider]
    if args.provider == 'dreamina' and getattr(args, 'dreamina_region', 'cn') != source.get('region_code'):
        raise ValueError('DREAMINA_CN_SOURCE_UNVERIFIED: obtain the official CN package; international download requires explicit --dreamina-region international')
    states = {n: state(n, args.skills_dir / n) for n in source['skills']}
    conflicts = [n for n, s in states.items() if s not in ('external_missing', 'external_verified')]
    if conflicts:
        raise ValueError('EXTERNAL_CONFLICT_PRESERVED: ' + ', '.join(conflicts) +
                         '; compare in a new skills-dir; never replace the existing version automatically')
    guard(args.tool_root, args.tool_root / 'official-cache')
    guard(args.skills_dir, args.skills_dir)
    cli_spec = None
    cli_target = args.tool_root / 'bin/dreamina-canvas'
    if args.with_cli:
        key = platform.system() + '-' + platform.machine()
        cli_spec = source.get('binaries', {}).get(key)
        if not cli_spec:
            raise ValueError('OFFICIAL_CLI_PLATFORM_UNVERIFIED: use the official platform installer after review')
        guard(args.tool_root, cli_target)
        if cli_target.exists() and (not cli_target.is_file() or digest(cli_target.read_bytes()) != cli_spec['sha256']):
            raise ValueError('CLI_CONFLICT_PRESERVED: choose a new tool-root')
        existing = shutil.which('dreamina-canvas')
        if existing and Path(existing).resolve() != cli_target.resolve() and not cli_target.exists():
            raise ValueError('EXISTING_CLI_PRESERVED: inspect the existing CLI; use skills-only installation')
    missing = [n for n, s in states.items() if s == 'external_missing']
    installed = []
    if missing:
        data = download(source['archive'], args.tool_root / 'official-cache', args.ca_bundle)
        archive = archive_files(data)
        prepared = {}
        for name, meta in source['skills'].items():
            files = {n[len(meta['prefix']):]: b for n, b in archive.items() if n.startswith(meta['prefix'])}
            if source.get('license_path'):
                files['LICENSE.upstream.txt'] = archive[source['license_path']]
            if 'SKILL.md' not in files or tree_hash(files) != meta['tree_sha256']:
                raise ValueError('OFFICIAL_SKILL_TREE_MISMATCH')
            prepared[name] = files
        args.skills_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.official-stage-', dir=args.skills_dir) as tmp:
            for name in missing:
                staged = Path(tmp) / name
                for relative, data in prepared[name].items():
                    p = staged / relative
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(data)
            for name in missing:
                target = args.skills_dir / name
                if target.exists() or target.is_symlink():
                    raise ValueError('EXTERNAL_TARGET_APPEARED: preserved; rerun after review')
                (Path(tmp) / name).rename(target)
                installed.append(name)
    if cli_spec:
        data = download(cli_spec, args.tool_root / 'official-cache', args.ca_bundle)
        cli_target.parent.mkdir(parents=True, exist_ok=True)
        if not cli_target.exists():
            with tempfile.NamedTemporaryFile(dir=cli_target.parent, delete=False) as stream:
                stream.write(data)
                temp = Path(stream.name)
            try:
                temp.chmod(0o755)
                if cli_target.exists() or cli_target.is_symlink():
                    raise ValueError('CLI_TARGET_APPEARED')
                temp.rename(cli_target)
            finally:
                temp.unlink(missing_ok=True)
    return {'provider': args.provider, 'version': source['version'], 'source': source['source'],
            'archive_sha256': source['archive']['sha256'], 'files_installed': installed,
            'skills': {n: state(n, args.skills_dir / n) for n in source['skills']},
            'cli_installed': bool(cli_spec), 'login_performed': False, 'business_ready': False,
            'region': source.get('region'), 'compatibility_verified': False}
