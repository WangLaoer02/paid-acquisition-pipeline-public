#!/usr/bin/env python3
"""Read a real Premiere project without changing it; check every external path."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as E


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('project', type=Path)
    p.add_argument('--base', type=Path, help='Resolve relative paths under this package root')
    args = p.parse_args()
    data = args.project.read_bytes()
    decoded = gzip.decompress(data) if data.startswith(b'\x1f\x8b') else data
    root = E.fromstring(decoded)
    base = args.base.resolve() if args.base else args.project.parent.resolve()
    refs = sorted({x.text for x in root.iter() if x.tag in ('FilePath', 'ActualMediaFilePath')
                   and x.text and not x.text.isdigit()})
    aliases = sorted({x.text for x in root.iter() if x.tag in ('RelativePath', 'relativePath') and x.text})
    results = []
    for value in refs:
        path = Path(value)
        actual = path if path.is_absolute() else base / path
        results.append({'declared': value, 'resolved': str(actual), 'exists': actual.is_file()})
    print(json.dumps({'project_sha256': hashlib.sha256(data).hexdigest(), 'path_fields': results,
                      'external_media_count': len({x['resolved'] for x in results}),
                      'all_external_paths_exist': bool(results) and all(x['exists'] for x in results),
                      'relative_aliases': aliases,
                      'alias_note': 'Relative aliases may remain stale after native relink; numeric IDs are internal generators. Native Online still requires Premiere.',
                      'native_open_verified': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
