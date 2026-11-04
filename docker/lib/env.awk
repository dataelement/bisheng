# Single-line dotenv reader/writer. Values are data, never shell source.
function trim(value) {
    sub(/^[[:space:]]+/, "", value)
    sub(/[[:space:]]+$/, "", value)
    return value
}
function fail(key) {
    print "Cannot read single-line dotenv value: " key > "/dev/stderr"
    invalid = 1
    exit 1
}
function decode(raw, key,    quote, result, i, char, nextchar, tail, closed) {
    raw = trim(raw)
    quote = substr(raw, 1, 1)
    if (quote != "\047" && quote != "\042") {
        sub(/[[:space:]]+#.*/, "", raw)
        if (substr(raw, 1, 1) == "#") raw = ""
        return raw
    }
    result = ""
    for (i = 2; i <= length(raw); i++) {
        char = substr(raw, i, 1)
        nextchar = substr(raw, i + 1, 1)
        if (quote == "\042" && char == "$" && nextchar == "$") {
            result = result "$"
            i++
        } else if (char == "\\" && nextchar == quote) {
            result = result quote
            i++
        } else if (quote == "\042" && char == "\\") {
            if (nextchar == "n" || nextchar == "r") fail(key)
            if (nextchar == "t") result = result "\t"
            else if (nextchar == "\\") result = result "\\"
            else result = result char nextchar
            i++
        } else if (char == quote) {
            tail = trim(substr(raw, i + 1))
            if (tail != "" && substr(tail, 1, 1) != "#") fail(key)
            closed = 1
            break
        } else result = result char
    }
    if (!closed) fail(key)
    return result
}
function encode(value,    result, i, char, double_quoted) {
    # Compose single quotes cannot represent an odd trailing backslash.
    double_quoted = index(value, "\\") > 0
    if (double_quoted) {
        result = "\042"
        for (i = 1; i <= length(value); i++) {
            char = substr(value, i, 1)
            if (char == "\\" || char == "\042") result = result "\\"
            if (char == "$") result = result "$"
            result = result char
        }
        return result "\042"
    }
    result = "\047"
    for (i = 1; i <= length(value); i++) {
        char = substr(value, i, 1)
        if (char == "\047") result = result "\\"
        result = result char
    }
    return result "\047"
}
{
    line = $0
    sub(/\r$/, "", line)
    original[NR] = line
    candidate = line
    sub(/^[[:space:]]*/, "", candidate)
    sub(/^export[[:space:]]+/, "", candidate)
    if (candidate !~ /^[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/) next
    key = candidate
    sub(/[[:space:]]*=.*/, "", key)
    if (seen[key]++) fail(key)
    order[++count] = key
    names[NR] = key
    raw = candidate
    sub(/^[^=]*=/, "", raw)
    values[key] = decode(raw, key)
}
END {
    if (invalid) exit 1
    if (MODE == "get") {
        printf "%s", values[KEY]
    } else if (MODE == "set") {
        value = ENVIRON["BISHENG_ENV_VALUE"]
        if (value ~ /[\r\n]/) fail(KEY)
        for (i = 1; i <= NR; i++) {
            if (names[i] == KEY) print KEY "=" encode(value)
            else print original[i]
        }
        if (!(KEY in values)) print KEY "=" encode(value)
    }
}
