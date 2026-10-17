"""Export pinned Scout Python source and lessons, never a live run or provider config.

Static flat-module import closure only; no target imports, network, installation,
SSH, model execution or publication. Review the manifest before any transfer.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath

import knowledge_notes
import qualification_source_bundle as bundle

ENTRYPOINTS = ('kimi_scout', 'scout_openai_backend')
MAX_BLOB_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_FILES = 512
BOUNDARY = ('Pinned static Python imports and committed lesson bytes only. Not a secret '
            'scanner, complete dynamic/runtime dependency closure, environment approval, '
            'transfer authority, model consumption or evidence of better PR yield.')


def export(repo, commit, output):
    repo, output = Path(repo).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('export directory must be fresh')
    if not bundle.full_sha1(commit):
        raise ValueError('use a full pinned commit, not a branch or abbreviated revision')
    if bundle.git(repo, 'rev-parse', '--verify', commit + '^{commit}').decode().strip() != commit:
        raise ValueError('source identity is not this commit')
    entries = bundle.git_tree_entries(repo, commit, ['scripts', 'knowledge/lessons'])
    modules = {PurePosixPath(path).stem: (path, mode, oid)
               for path, mode, oid in entries
               if PurePosixPath(path).parent == PurePosixPath('scripts') and path.endswith('.py')}
    packages = {PurePosixPath(path).parts[1] for path, _, _ in entries
                if path.startswith('scripts/') and len(PurePosixPath(path).parts) > 2}
    if not all(name in modules for name in ENTRYPOINTS):
        raise ValueError('missing Scout entrypoint')
    cards = [entry for entry in entries
             if PurePosixPath(entry[0]).parent == PurePosixPath('knowledge/lessons')
             and entry[0].endswith('.json')]
    if not cards:
        raise ValueError('no committed default lessons')
    pending, seen, files, external = set(ENTRYPOINTS), set(), {}, set()
    total = 0

    def load(selected):
        nonlocal total
        if len(files) + len(selected) > MAX_FILES:
            raise ValueError('export file budget exceeded')
        for path, mode, _ in selected:
            if mode not in ('100644', '100755'):
                raise ValueError('selected export source must be a regular Git file')
            bundle.safe_windows_extraction_path(path)
        for path, _, raw in bundle.iter_git_tree_blobs(repo, sorted(selected), max_blob_bytes=MAX_BLOB_BYTES):
            total += len(raw)
            if total > MAX_TOTAL_BYTES:
                raise ValueError('export byte budget exceeded')
            if any(old.casefold() == path.casefold() for old in files):
                raise ValueError('case-colliding export paths')
            files[path] = raw

    while pending:
        frontier = sorted(pending - seen)
        if not frontier:
            break
        pending.clear()
        load([modules[name] for name in frontier])
        seen.update(frontier)
        for name in frontier:
            path = modules[name][0]
            for node in ast.walk(ast.parse(files[path], filename=path)):
                if isinstance(node, ast.Import):
                    imports = [alias.name.split('.')[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 1:
                        raise ValueError(f'parent-relative imports need a separately reviewed package export: {path}')
                    imports = ([node.module.split('.')[0]] if node.module else
                               [alias.name.split('.')[0] for alias in node.names] if node.level else [])
                    if node.level and any(item not in modules for item in imports):
                        raise ValueError(f'unresolved relative imports need a separately reviewed package export: {path}')
                else:
                    continue
                if any(item in packages and item not in modules for item in imports):
                    raise ValueError(f'local packages need a separately reviewed package export: {path}')
                pending.update(item for item in imports if item in modules and item not in seen)
                external.update(item for item in imports if item not in modules)
    load(cards)
    lesson_keys = {key: set() for key in ('id', 'title', 'lesson')}
    for path, _, _ in cards:
        card = json.loads(files[path])
        knowledge_notes.validate(card)
        if card['id'] != PurePosixPath(path).stem:
            raise ValueError('lesson identity does not match filename')
        for key, values in lesson_keys.items():
            value = knowledge_notes.normalized(card[key])
            if value in values:
                raise ValueError(f'duplicate lesson {key}')
            values.add(value)
    record = dict(commit=commit, entrypoints=list(ENTRYPOINTS), source_modules=len(seen),
                  lesson_cards=len(cards), total_bytes=total,
                  external_import_roots=sorted(external),
                  files={path: dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                         for path, raw in sorted(files.items())}, boundary=BOUNDARY)
    # All source/shape/budget validation precedes the first output write.
    output.mkdir()
    for path, raw in sorted(files.items()):
        target = output.joinpath(*PurePosixPath(path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
    with (output / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, sort_keys=True, indent=2)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    record = export(args.repo, args.commit, args.output)
    print(json.dumps({key: value for key, value in record.items() if key != 'files'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
