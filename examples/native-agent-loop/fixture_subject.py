"""Deliberately incorrect synthetic subject, not a discovered repository bug."""


def slice_exclusive(data, start, end):
    return data[start : end + 1]
