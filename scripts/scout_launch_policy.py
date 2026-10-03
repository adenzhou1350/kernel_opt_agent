"""Classify a confirmed OS launch policy denial, not a provider failure."""


def application_control_denied(receipt):
    """Only trusted controller diagnostics can stop automatic dispatch.

    A model answer, an arbitrary OSError, or a filesystem preparation failure
    must not be mistaken for Windows blocking the configured executable.
    No alternate executable or security-policy change is attempted here.
    """
    if not isinstance(receipt, dict) or receipt.get("state") != "FAILED":
        return False
    error = receipt.get("os_error")
    return (
        isinstance(error, dict)
        and error.get("operation") == "run_backend"
        and type(error.get("winerror")) is int
        and error["winerror"] == 4551
    )
