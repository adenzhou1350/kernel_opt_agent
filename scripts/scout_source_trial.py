"""Compose one source-selection trial case without silently dropping failures.

For newly declared shadow protocols, not live Scout routing. An issue-only
catalog yields three UNAVAILABLE_ACTION_SPACE records and no callbacks/GETs;
retain it in enrollment, separately from the available-action comparison.
Do not repair or rescore historical trials with this different branch policy.

Selector/reviewer callbacks own bounded model execution, parsing, durable call
identity and provider/setup/owner accounting. This driver records call failures
without retry, but cannot prove their token cost, native utility or equal budget.
Review output is opaque: returning is not a valid verdict or accepted finding.
Only the supplied immutable-source catalog is admissible, not an exhaustive
action universe. No repository source is executed or PR state changed here.
"""

import json

try:
    from .scout_evidence_acquisition import pinned_raw_url
except ImportError:
    from scout_evidence_acquisition import pinned_raw_url


ARMS = ("no_additional_source", "rules_first_catalog_continuation", "selected_source")


def _copy_view(view):
    # Accept the compact catalog, not a queue row with outcome/lineage metadata.
    # Text remains untrusted; field allowlisting is not a leakage/injection audit.
    text_keys = {
        "repo", "question", "hypothesis_unverified", "next_check_unverified",
        "uncertainty", "scope", "snippet_layout",
    }
    count_keys = {"catalog_omitted", "question_chars_limit"}
    if (
        not isinstance(view, dict)
        or not {"repo", "question", "sources", "scope"} <= view.keys()
        or not view.keys() <= text_keys | count_keys | {"sources"}
        or any(not isinstance(view[k], str) for k in view.keys() & text_keys)
        or any(type(view[k]) is not int or view[k] < 0 for k in view.keys() & count_keys)
        or not isinstance(view["sources"], list) or len(view["sources"]) > 24
    ):
        raise ValueError("expected a compact acquisition view")
    source_keys = {"url", "original_index", "start_line", "end_line",
                   "original_chars", "text", "clipped"}
    for source in view["sources"]:
        if (
            not isinstance(source, dict) or set(source) != source_keys
            or not isinstance(source["url"], str) or len(source["url"]) > 2048
            or not isinstance(source["text"], str)
            or type(source["clipped"]) is not bool
            or any(type(source[k]) is not int or source[k] < 0
                   for k in ("original_index", "original_chars"))
            or any(source[k] is not None and (
                type(source[k]) is not int or source[k] < 1
            ) for k in ("start_line", "end_line"))
        ):
            raise ValueError("invalid compact source catalog entry")
    raw = json.dumps(view, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(raw) > 6500:
        raise ValueError("compact acquisition view exceeds 6500 characters")
    return json.loads(raw)


def _invoke(callback, *args):
    # Separate finite-JSON copies prevent one callback mutating later arm input.
    copies = json.loads(json.dumps(args, ensure_ascii=False, allow_nan=False))
    try:
        return {"status": "RETURNED", "record": callback(*copies)}
    except Exception as error:
        # Backend wrappers must retain uncertain/orphan attempts and costs.
        # Exception text may contain credentials; do not echo it or retry.
        return {"status": "CALL_FAILED", "error_kind": type(error).__name__}


def run_case(view, *, selector, reviewer, session, arm_order=ARMS):
    """One selection, up to one window/arm, one review/arm; no hidden repair.

    Selector returns the existing {url, start_line, reason} object (both selectors
    null for abstention). Reviewer gets only (original_view, additional_source),
    not the arm name or selector rationale. Its opaque return record must include
    observed costs in a real experiment. Window failures stay failures, not text.
    Session costs are explicitly cumulative if a cache is reused across cases.
    """
    if not isinstance(arm_order, (list, tuple)) or (
        len(arm_order) != len(ARMS) or set(arm_order) != set(ARMS)
    ):
        raise ValueError("each declared arm must appear exactly once")
    original = _copy_view(view)
    pinned = [s for s in original["sources"] if pinned_raw_url(s.get("url"))]
    if not pinned:
        return {
            "status": "UNAVAILABLE_ACTION_SPACE",
            "selection": {"status": "NOT_CALLED"},
            "arms": [{"arm": arm, "status": "UNAVAILABLE_ACTION_SPACE"}
                     for arm in arm_order],
            "session_costs": session.costs(),
        }
    selection = _invoke(selector, original)
    pick = selection.get("record")
    choice, selection_status = None, "INVALID_SELECTION"
    if selection["status"] == "CALL_FAILED":
        selection_status = "CALL_FAILED"
    elif (
        isinstance(pick, dict) and set(pick) == {"url", "start_line", "reason"}
        and isinstance(pick["reason"], str) and len(pick["reason"]) <= 600
    ):
        if pick["url"] is None and pick["start_line"] is None:
            selection_status = "ABSTAINED"
        elif (
            isinstance(pick["url"], str)
            and pick["url"] in {s["url"] for s in pinned}
            and type(pick["start_line"]) is int and pick["start_line"] > 0
        ):
            choice = {"url": pick["url"], "start_line": pick["start_line"]}
            selection_status = "SELECTED"
    end = pinned[0].get("end_line")
    choices = {
        "no_additional_source": None,
        "rules_first_catalog_continuation": {
            "url": pinned[0]["url"],
            "start_line": end + 1 if type(end) is int and end > 0 else 1,
        },
        "selected_source": choice,
    }
    records = []
    for arm in arm_order:
        target, acquired, evidence = choices[arm], None, None
        if target is not None:
            try:
                acquired = session.acquire_window(**target, max_lines=80, max_chars=4500)
            except Exception as error:
                acquired = {
                    "acquisition": {
                        "status": "FAILED", "error_kind": type(error).__name__,
                        "cost_scope": "SESSION_FAILURE_COST_MAY_BE_INCOMPLETE",
                    },
                    "window": {"status": "FAILED", "error_kind": "SESSION_FAILURE"},
                }
            window = acquired["window"]
            evidence = dict(window, url=target["url"])
        review = _invoke(reviewer, original, evidence)
        records.append({"arm": arm, "choice": target, "acquisition": acquired,
                        "review": review})
    return {"status": "AVAILABLE_ACTION_SPACE", "selection": selection,
            "selection_status": selection_status, "arms": records,
            "session_costs": session.costs()}
