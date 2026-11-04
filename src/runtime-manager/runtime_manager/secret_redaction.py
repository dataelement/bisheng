"""Operation-bound output filtering, including short and ordinary-named secrets."""

import re

_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "KEY", "PROXY", "INDEX_URL", "REGISTRY", "AUTH")


def _overlap(left, right):
    """Length of the longest suffix(left) equal to a prefix(right), in linear time."""
    values = [*right[: len(left)], None, *left]
    prefix = [0] * len(values)
    for index in range(1, len(values)):
        match = prefix[index - 1]
        while match and values[index] != values[match]:
            match = prefix[match - 1]
        if values[index] == values[match]:
            match += 1
        prefix[index] = match
    return prefix[-1] if prefix else 0


def redact_output(text, environment, sensitive_names=()):
    names = set(sensitive_names or ())
    if any(name not in environment or not isinstance(environment[name], str) for name in names):
        return ""
    names.update(name for name in environment if any(marker in name.upper() for marker in _MARKERS))
    values = {environment[name] for name in names if isinstance(environment.get(name), str) and environment[name]}
    # Log transports may insert framing between lines of a multiline value.
    values.update(part for value in tuple(values) for part in value.splitlines() if part)
    output = str(text)
    if values:
        expression = "|".join(re.escape(value) for value in sorted(values, key=lambda value: (-len(value), value)))
        output = re.sub(expression, "<redacted>", output)
        for value in sorted(values, key=len, reverse=True):
            leading = _overlap(value, output)
            if 0 < leading < len(value):
                output = "<redacted>" + output[leading:]
            trailing = _overlap(output[-len(value) :], value)
            if 0 < trailing < len(value):
                output = output[:-trailing] + "<redacted>"
    output = re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1<redacted>@", output)
    return re.sub(
        r"([?&](?:access_token|token|api_key|key|password|secret)=)[^&\s]+",
        r"\1<redacted>",
        output,
        flags=re.IGNORECASE,
    )


def diagnostic_environment(config, payload):
    env = dict(payload.get("runtime_env", {}))
    for name in (
        "hmac_secret",
        "platform_secret",
        "inbound_secret",
        "minio_access_key",
        "minio_secret_key",
        "build_index_url",
        "build_extra_index_url",
        "build_npm_registry",
    ):
        env["RTM_" + name.upper()] = getattr(config, name, "")
    return env


def bounded_diagnostic(text, environment, sensitive_names=()):
    """Redact before truncation so clipping cannot reveal a fragment of a secret."""
    output = redact_output(text, environment, sensitive_names)
    return "\n".join(output.splitlines()[-40:]).encode("utf-8")[-16384:].decode("utf-8", errors="ignore")


def image_failure_context(error):
    role, reference = getattr(error, "image_role", ""), getattr(error, "image_ref", "")
    if (
        not isinstance(role, str)
        or role not in {"runtime", "preparer", "base", "image", "helper", "assembler"}
        or not isinstance(reference, str)
        or len(reference) > 512
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:_-]*(?:@sha256:[a-f0-9]{64})?", reference)
    ):
        return {}
    return {"image_role": role, "image_ref": reference}
