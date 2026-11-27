"""Pure dataset-format recognition and lossless Alpaca-to-messages conversion."""

from .dataset_validation import validate_records


def convert_legacy_records(records: list) -> list[dict]:
    if not isinstance(records, list) or not records:
        raise ValueError("Dataset must be a non-empty JSON list")
    result = []
    allowed = {"instruction", "input", "output", "system", "history"}
    for index, row in enumerate(records):

        def fail(reason, index=index):
            raise ValueError(f"Record {index}: {reason}")

        if not isinstance(row, dict) or set(row) - allowed:
            fail("unsupported legacy fields; conversion would discard data")
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in ("instruction", "output")):
            fail("instruction and output must be non-empty strings")
        if not isinstance(row.get("input", ""), str) or not isinstance(row.get("system", ""), str):
            fail("input and system must be strings")
        messages = []
        if row.get("system", "").strip():
            messages.append({"role": "system", "content": row["system"]})
        history = row.get("history", [])
        if not isinstance(history, list):
            fail("history must contain question/answer pairs")
        for pair in history:
            if (
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or any(not isinstance(x, str) or not x.strip() for x in pair)
            ):
                fail("history must contain non-empty question/answer pairs")
            messages.extend([{"role": "user", "content": pair[0]}, {"role": "assistant", "content": pair[1]}])
        prompt = row["instruction"] + ("\n\n" + row["input"] if row.get("input") else "")
        messages.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": row["output"]}])
        result.append({"messages": messages})
    validate_records(result)
    return result


def classify_records(records: list) -> str:
    if not isinstance(records, list) or not records or any(not isinstance(row, dict) for row in records):
        raise ValueError("Dataset must be a non-empty JSON list of objects")
    legacy = ["messages" not in row for row in records]
    if any(legacy):
        if not all(legacy):
            raise ValueError("Dataset contains mixed legacy and messages formats")
        convert_legacy_records(records)
        return "legacy"
    kinds = {"image_text" if row.get("images") else "video_text" if row.get("videos") else "text" for row in records}
    if len(kinds) != 1:
        raise ValueError("Dataset contains mixed data types")
    kind = kinds.pop()
    validate_records(records, kind)
    return kind
