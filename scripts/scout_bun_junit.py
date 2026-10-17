"""Observed Bun 1.4 JUnit accounting, not generic JUnit or a test oracle.

Bun nests describe suites and emits identical names for some parameterized
cases. Preserve those as location-bound groups with observed multiplicity;
never invent parameter values or use report order as semantic identity.
"""
import hashlib
import json
import re
from pathlib import PurePosixPath
from xml.etree import ElementTree


def case_id(file, line, scopes, name):
    """Exact JSON location/group ID; does not identify parameter values."""
    if (not isinstance(file, str) or not file or '\\' in file
            or PurePosixPath(file).is_absolute() or ':' in file
            or any(part in {'', '.', '..'} for part in file.split('/'))
            or type(line) is not int or not 1 <= line <= 10000000
            or not isinstance(name, str) or not name
            or not isinstance(scopes, (list, tuple)) or len(scopes) > 32):
        raise ValueError('invalid Bun case location')
    for scope in scopes:
        if (not isinstance(scope, (list, tuple)) or len(scope) != 2
                or not isinstance(scope[0], str) or not scope[0]
                or type(scope[1]) is not int or not 1 <= scope[1] <= 10000000):
            raise ValueError('invalid Bun describe location')
    value = json.dumps([file, line, scopes, name], ensure_ascii=True, separators=(',', ':'))
    if len(value) > 512:
        raise ValueError('overlong Bun case identity')
    return value


def summarize(text, exit_code, expected_results, issue):
    counts = dict(passed=0, failed=0, skipped=0)
    seen, groups, files = set(), {}, set()
    metadata = dict(todo=0, grouped_case_inventory_sha256=None,
                    reported_total_tests=None, case_groups=0,
                    parameter_values_identified=False)
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.IGNORECASE):
        issue('Bun JUnit DTD/entity declarations are unsupported')
        return counts, seen, 0, None, metadata
    try:
        root = ElementTree.fromstring(text)
    except (ElementTree.ParseError, ValueError, RecursionError):
        issue('malformed or truncated Bun JUnit XML')
        return counts, seen, 0, None, metadata
    if root.tag != 'testsuites' or root.get('name') != 'bun test':
        issue('unsupported Bun JUnit root')
        return counts, seen, 0, None, metadata

    def integer(value):
        return int(value) if re.fullmatch(r'[0-9]{1,8}', value or '') else None

    def totals(element, observed):
        for key, expected in (('tests', sum(observed.values())),
                              ('failures', observed['failed']), ('skipped', observed['skipped'])):
            if integer(element.get(key)) != expected:
                issue('Bun JUnit case/summary cardinality mismatch')
        if 'errors' in element.attrib and integer(element.get('errors')) != 0:
            issue('Bun JUnit reports setup/runner errors')

    def suite(element, file, scopes, depth):
        observed = dict.fromkeys(counts, 0)
        if depth > 32:
            issue('Bun JUnit nesting exceeds 32 levels')
            return observed
        if element.get('file') != file or not element.get('name'):
            issue('missing or inconsistent Bun suite location')
        for child in element:
            if child.tag == 'testsuite':
                line = integer(child.get('line'))
                nested = suite(child, file, scopes + [(child.get('name', ''), line)], depth+1)
                for key in observed:
                    observed[key] += nested[key]
                continue
            if child.tag != 'testcase':
                issue('unsupported Bun suite child')
                continue
            outcome_tags = [node.tag for node in child]
            if (len(outcome_tags) > 1 or any(tag not in {'failure', 'skipped'} for tag in outcome_tags)
                    or any(len(node) for node in child)):
                issue('unsupported or contradictory Bun case outcomes')
                continue
            outcome = {'failure': 'failed', 'skipped': 'skipped'}.get(
                outcome_tags[0] if outcome_tags else None, 'passed')
            observed[outcome] += 1
            if outcome == 'skipped' and child[0].get('message') == 'TODO':
                metadata['todo'] += 1
            if outcome == 'failed' and child[0].get('type') == 'TimeoutError':
                issue('Bun test timeout is not an assertion-failure reproduction')
            try:
                identity = case_id(child.get('file'), integer(child.get('line')), scopes, child.get('name'))
            except ValueError:
                issue('missing or invalid Bun case location; possible hook/setup failure')
                continue
            if (child.get('file') != file
                    or child.get('classname') != ' > '.join(name for name, _line in reversed(scopes))):
                issue('Bun case/describe location mismatch')
            groups[identity] = groups.get(identity, 0) + 1
            if outcome != 'skipped':
                seen.add(identity)
            if identity in expected_results:
                expected_results[identity][outcome] += 1
        totals(element, observed)
        return observed

    batches = 0
    for element in root:
        if element.tag != 'testsuite':
            issue('unsupported Bun root child')
            continue
        file = element.get('file')
        if not isinstance(file, str) or not file or file in files or element.get('name') != file:
            issue('missing or duplicate Bun file suite')
        files.add(file)
        observed = suite(element, file, [], 0)
        for key in counts:
            counts[key] += observed[key]
        batches += 1
    totals(root, counts)
    if sum(1 for _ in root.iter('testcase')) != sum(counts.values()):
        issue('Bun contains cases outside the supported suite structure')
    metadata.update(reported_total_tests=integer(root.get('tests')), case_groups=len(groups),
        grouped_case_inventory_sha256=hashlib.sha256(json.dumps(sorted(groups.items()),
            ensure_ascii=True, separators=(',', ':')).encode()).hexdigest())
    if exit_code not in {0, 1}:
        issue('Bun did not exit normally with pass or test-failure status')
    return counts, seen, batches, 'fail' if counts['failed'] else 'pass', metadata
