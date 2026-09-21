"""Logging for the interpretation layer that cannot leak a conversation.

`melody.log` and the window pane both show whatever is printed, and the rule
for new code (PRD PR-4) is that neither may ever carry transcript text,
quotes, claims, names or goals. Rather than trusting every call site to
remember that, this module refuses free text at the API: a field value must be
a number, a bool, None, or a short single token, and anything that looks like
prose raises before it can reach a log.

The pipeline's own logging is untouched; this binds new code only.
"""

_MAX_TOKEN_CHARS = 40


class UnsafeLogValue(ValueError):
    """A value that could carry conversation content was passed to log_event."""


def _render(name, value):
    if value is None or isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return "{0:.3f}".format(value).rstrip("0").rstrip(".") or "0"
    if isinstance(value, str):
        if len(value) > _MAX_TOKEN_CHARS or any(ch.isspace() for ch in value):
            raise UnsafeLogValue(
                "log_event field {0!r} looks like free text; log ids, counts "
                "and enum tokens only".format(name))
        return value
    raise UnsafeLogValue(
        "log_event field {0!r} has unloggable type {1}".format(
            name, type(value).__name__))


def log_event(name, emit=None, **fields):
    """Print one `[melody] name key=value ...` line; also send it to `emit`.

    `name` follows the same token rule as every value. stdout is melody.log
    when the app is running (main.py redirects it), and `emit` is the window
    pane's callback when a caller has one. Returns the rendered line so tests
    can assert on it.
    """
    _render("event", name)
    parts = ["[melody]", name]
    parts.extend("{0}={1}".format(key, _render(key, value))
                 for key, value in fields.items())
    line = " ".join(parts)
    print(line)
    if emit is not None:
        emit(line)
    return line
