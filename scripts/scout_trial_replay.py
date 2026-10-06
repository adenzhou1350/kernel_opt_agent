"""Check saved trial-call identity before replay or reported-cost aggregation.

These checks establish record consistency, not authentic provider usage, equal
experimental budgets, a valid outcome label, or permission for another call.
They perform no I/O. Preserve terminal trial inputs when adopting this helper.
"""

import hashlib
import json


def request_digest(request):
    if not isinstance(request, dict):
        raise ValueError("REQUEST_IDENTITY: request must be an object")
    try:
        raw = json.dumps(request, sort_keys=True, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise ValueError("REQUEST_IDENTITY: request is not finite JSON") from error
    return hashlib.sha256(raw).hexdigest()


def validate_saved_call(saved_request, record, *, requested=None):
    """Use the pilot's existing canonical digest, not its JSON file formatting."""
    digest = request_digest(saved_request)
    if not isinstance(record, dict) or record.get("request_sha256") != digest:
        raise ValueError("REQUEST_IDENTITY: result does not bind the saved request")
    if requested is not None and request_digest(requested) != digest:
        raise ValueError("REQUEST_IDENTITY: requested input differs from saved call")
    return record


def reported_cost(pairs):
    """Count request/result pairs once; failed calls with usage still cost tokens.

    The caller must reconcile orphan attempts before constructing pairs. Unknown
    usage is an error, never zero. This is reported tokens, not total cost.
    """
    count = tokens = 0
    for request, record in pairs:
        validate_saved_call(request, record)
        response = record.get("response")
        usage = response.get("usage") if isinstance(response, dict) else None
        charged = usage.get("total_tokens") if isinstance(usage, dict) else None
        if type(charged) is not int or charged < 0:
            raise ValueError("REPORTED_COST: missing or invalid usage")
        count += 1
        tokens += charged
    return count, tokens
