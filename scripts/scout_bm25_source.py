"""Optional deterministic BM25 source-window comparator, not live routing.

Indexes preloaded immutable assets, including comments/strings. Ranking is not
relevance, correctness or novelty evidence. Caller accounts for index construction
and full-corpus reads separately from the selected excerpt and downstream calls.
"""
import hashlib
import json
import math
import re
import time
from collections import Counter

try:
    from .scout_evidence_acquisition import pinned_raw_url
    from .scout_source_window import source_window
except ImportError:
    from scout_evidence_acquisition import pinned_raw_url
    from scout_source_window import source_window

K1, B = 1.2, 0.75
MAX_FILES, MAX_BYTES, MAX_DOCUMENTS = 64, 8_000_000, 8192


def tokens(text):
    """Unicode words plus ASCII camel/snake components; no learned expansion."""
    result = []
    for word in re.findall(r'\w+', text):
        result.append(word.casefold())
        split = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', word)
        split = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', split)
        parts = [p.casefold() for p in re.split(r'[_\s]+', split) if p]
        if len(parts) > 1:
            result.extend(parts)
    return result


def bm25_scores(query, documents):
    """Binary query terms; positive-IDF BM25 variant, without Lucene norm coding."""
    query = sorted(set(query))
    counts = [Counter(document) for document in documents]
    average = sum(map(len, documents)) / len(documents) if documents else 0
    if not average:
        return [0.0] * len(documents)
    frequencies = {term: sum(term in count for count in counts) for term in query}
    scores = []
    for count, document in zip(counts, documents):
        normalizer = K1 * (1 - B + B * len(document) / average)
        scores.append(sum(
            math.log1p((len(documents) - frequencies[term] + .5) / (frequencies[term] + .5))
            * count[term] * (K1 + 1) / (count[term] + normalizer)
            for term in query if count[term]
        ))
    return scores


def bm25_choice(view, assets):
    """One <=80-line/4500-character range; no I/O, execution, retries or labels.

    Up to 80-line windows at stride 40, with a possibly shorter EOF window. The
    existing line reader fits whole lines to 4500 characters BEFORE scoring;
    the chosen exact range is never shortened later. All catalog files count
    toward the index-read budget, even if no useful document can be formed.
    """
    started = time.perf_counter()
    stats = dict(method='bm25_code_windows_v1', k1=K1, b=B, files_indexed=0,
                 logical_index_bytes=0, documents=0, skipped_windows=0)

    def finish(status, **values):
        return dict(status=status, **values, retrieval=dict(
            stats, elapsed_seconds=time.perf_counter()-started,
            scope='Preloaded corpus scan cost, NOT free setup or measured network traffic. Relevance and incremental information remain unproven.'))

    catalog = view.get('catalog') if isinstance(view, dict) else None
    if not isinstance(catalog, list) or not 1 <= len(catalog) <= MAX_FILES:
        return finish('UNAVAILABLE', error_kind='CATALOG_LIMIT_OR_INVALID')
    packet = view.get('packet')
    try:
        prior = json.loads(packet.get('untrusted_prior_analysis', '{}'))
    except (AttributeError, TypeError, ValueError):
        return finish('UNAVAILABLE', error_kind='INVALID_PRIOR')
    if not isinstance(prior, dict):
        return finish('UNAVAILABLE', error_kind='INVALID_PRIOR')
    if any(not isinstance(prior.get(k, ''), str) for k in ('hypothesis', 'next_check')):
        return finish('UNAVAILABLE', error_kind='INVALID_QUERY')
    query = '\n'.join(prior.get(k, '') for k in ('hypothesis', 'next_check'))
    try:
        query_bytes = query.encode()
    except UnicodeEncodeError:
        return finish('UNAVAILABLE', error_kind='INVALID_QUERY')
    if len(query_bytes) > 8000:
        return finish('UNAVAILABLE', error_kind='QUERY_LIMIT')
    query = sorted(set(tokens(query)))
    stats['query_terms'] = len(query)
    if not query:
        return finish('ABSTAIN', error_kind='EMPTY_QUERY')
    if len(query) > 256:
        return finish('UNAVAILABLE', error_kind='QUERY_TERM_LIMIT')
    documents, locations, seen, revision = [], [], set(), None
    for entry in catalog:
        if not isinstance(entry, dict):
            return finish('UNAVAILABLE', error_kind='INVALID_CATALOG_ENTRY')
        path = entry.get('path')
        if (not isinstance(path, str) or path in seen or not pinned_raw_url(entry.get('url'))
                or not entry['url'].endswith('/'+path) or path not in assets):
            return finish('UNAVAILABLE', error_kind='INVALID_CATALOG_ENTRY')
        prefix = 'https://raw.githubusercontent.com/'+str(packet.get('repo', ''))+'/'
        if not entry['url'].startswith(prefix):
            return finish('UNAVAILABLE', error_kind='CATALOG_REPOSITORY_MISMATCH')
        commit = entry['url'][len(prefix):].split('/', 1)[0]
        if revision is not None and commit != revision:
            return finish('UNAVAILABLE', error_kind='CATALOG_REVISION_MISMATCH')
        revision = commit
        seen.add(path)
        asset = assets[path]
        text = asset.get('text') if isinstance(asset, dict) else None
        if not isinstance(text, str) or len(text) > 1_000_000:
            return finish('UNAVAILABLE', error_kind='INVALID_ASSET')
        try:
            raw = text.encode()
        except UnicodeEncodeError:
            return finish('UNAVAILABLE', error_kind='INVALID_UTF8_ASSET')
        stats['logical_index_bytes'] += len(raw)
        if len(raw) > 1_000_000 or stats['logical_index_bytes'] > MAX_BYTES:
            return finish('UNAVAILABLE', error_kind='CORPUS_BYTE_LIMIT')
        digest = hashlib.sha256(raw).hexdigest()
        if asset.get('sha256') != digest or entry.get('sha256') != digest:
            return finish('UNAVAILABLE', error_kind='ASSET_IDENTITY_MISMATCH')
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        if lines and lines[-1] == '':
            lines.pop()
        if type(entry.get('lines')) is not int or entry['lines'] != len(lines):
            return finish('UNAVAILABLE', error_kind='LINE_COUNT_MISMATCH')
        stats['files_indexed'] += 1
        start = 0
        while start < len(lines):
            window = source_window(text, start_line=start+1, max_lines=80, max_chars=4500)
            if window['status'] != 'ACQUIRED':
                stats['skipped_windows'] += 1
                start += 1  # A single oversized line must not hide later lines.
                continue
            if len(documents) >= MAX_DOCUMENTS:
                return finish('UNAVAILABLE', error_kind='DOCUMENT_LIMIT')
            documents.append(tokens(path+'\n'+window['text']))
            count = window['end_line']-window['start_line']+1
            locations.append((path, window['start_line'], count))
            stats['documents'] = len(documents)
            if window['end_line'] == len(lines):
                break
            start += min(40, count)  # Character-fitting must not create gaps.
    stats['documents'] = len(documents)
    scores = bm25_scores(query, documents)
    ranked = sorted(zip(scores, locations), key=lambda item: (-item[0], item[1]))
    if not ranked or ranked[0][0] <= 0:
        return finish('ABSTAIN', error_kind='NO_LEXICAL_MATCH')
    score, (path, first, count) = ranked[0]
    return finish('SELECTED', path=path, ranges=[dict(start_line=first, line_count=count)], score=score)
