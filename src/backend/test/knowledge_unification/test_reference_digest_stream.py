"""Original reference SHA bytes and bounded-memory ordered streaming."""

import hashlib
import json
import tracemalloc
from dataclasses import dataclass

import pytest

from bisheng.resource_reference.application import contracts
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey


def _legacy_normalize(references):
    # Unmodified pre-T892 semantics, including a one-shot iterator's consumption.
    if any(not isinstance(reference, ReferenceSpec) for reference in references):
        raise TypeError("references must contain only ReferenceSpec values")
    return tuple(
        sorted(set(references), key=lambda ref: (ref.slot_key, ref.target.target_type.value, ref.target.target_id))
    )


def _legacy_digest(references):
    canonical = [
        (reference.slot_key, reference.target.target_type.value, reference.target.target_id)
        for reference in _legacy_normalize(references)
    ]
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ref(slot="saved", target_id="1", target_type="model"):
    return ReferenceSpec(slot, TargetKey(target_type, target_id))


@dataclass(frozen=True, slots=True)
class TaggedReference(ReferenceSpec):
    tag: str


def _tagged():
    target = TargetKey("model", "1")
    return (TaggedReference("saved", target, "a"), TaggedReference("saved", target, "b"))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: (),
        lambda: (ref(),),
        lambda: [ref("z"), ref("a", "2"), ref("a", "10")],
        lambda: (ref(), ref(), ref()),
        lambda: (ref("same", "2"), ref("same", "10"), ref("same", "100")),
        lambda: (ref("same", "1", "knowledge_space"), ref("same", "1", "knowledge_file")),
        lambda: (ref('引用."/\\\n', "10"), ref("🚀", "2", "knowledge_file")),
        _tagged,
        lambda: (row for row in (ref("z"), ref("a"))),
        lambda: iter(()),
    ],
    ids=["empty", "one", "list", "duplicates", "lex-ids", "types", "utf8", "subclasses", "generator", "empty-iterator"],
)
def test_original_api_preserves_actual_prechange_successes(factory):
    assert contracts.reference_set_digest(factory()) == _legacy_digest(factory())


@pytest.mark.parametrize("factory", [lambda: None, lambda: 1, lambda: "bad", lambda: (ref(), None), lambda: [1]])
def test_original_api_preserves_actual_prechange_errors(factory):
    with pytest.raises(TypeError) as original:
        _legacy_digest(factory())
    with pytest.raises(type(original.value)) as current:
        contracts.reference_set_digest(factory())
    assert str(current.value) == str(original.value)


def test_actual_old_utf8_and_escaped_bytes_are_fixed():
    rows = (ref('引用."/\\\n', "10"), ref("🚀", "2", "knowledge_file"))
    old_bytes = bytes.fromhex(
        "5b5b22e5bc95e794a82e5c222f5c5c5c6e222c226d6f64656c222c223130225d2c"
        "5b22f09f9a80222c226b6e6f776c656467655f66696c65222c2232225d5d"
    )
    assert _legacy_digest(rows) == hashlib.sha256(old_bytes).hexdigest()
    assert contracts.reference_set_digest(rows) == "6692ed1064bec811a73f1ca6a148001eb2ee95b7bee20b37768d29d2b8fdb213"


def test_old_generator_success_remains_the_old_empty_sha():
    assert contracts.reference_set_digest(row for row in (ref("a"), ref("b"))) == _legacy_digest(())


@pytest.mark.parametrize(
    "rows",
    [
        (),
        (ref(),),
        (ref("a", "10"), ref("a", "100"), ref("a", "2")),
        (ref("same", "1", "knowledge_file"), ref("same", "1", "knowledge_space"), ref("same")),
        (ref('引用."/\\\n', "10"), ref("🚀", "2", "knowledge_file")),
        _tagged(),
    ],
    ids=["empty", "one", "lex-ids", "types", "utf8", "subclasses"],
)
def test_accumulator_hashes_original_normalized_rows(rows):
    accumulator = contracts.ReferenceSetDigestAccumulator()
    for row in rows:
        assert accumulator.update(row) is None
    assert accumulator.hexdigest() == _legacy_digest(rows)
    assert accumulator.hexdigest() == _legacy_digest(rows)


def test_accumulator_equal_keys_preserve_multiplicity_instead_of_deduplicating():
    row = ref()
    accumulator = contracts.ReferenceSetDigestAccumulator()
    accumulator.update(row)
    accumulator.update(row)
    # Base duplicates are normally removed; tagged subclasses prove that two
    # equal canonical keys can legally survive the original set normalization.
    assert accumulator.hexdigest() == _legacy_digest(_tagged())
    assert accumulator.hexdigest() != _legacy_digest((row, row))


def test_hexdigest_is_non_destructive_and_update_can_continue():
    accumulator = contracts.ReferenceSetDigestAccumulator()
    assert accumulator.hexdigest() == _legacy_digest(())
    accumulator.update(ref("a"))
    first = accumulator.hexdigest()
    assert first == accumulator.hexdigest() == _legacy_digest((ref("a"),))
    accumulator.update(ref("b"))
    assert accumulator.hexdigest() == _legacy_digest((ref("a"), ref("b")))


@pytest.mark.parametrize(
    "previous,current",
    [
        (ref("b"), ref("a")),
        (ref("a", "2"), ref("a", "10")),
        (ref("a", "1", "model"), ref("a", "1", "knowledge_space")),
    ],
)
def test_descending_key_is_rejected_without_corrupting_the_previous_digest(previous, current):
    accumulator = contracts.ReferenceSetDigestAccumulator()
    accumulator.update(previous)
    before = accumulator.hexdigest()
    with pytest.raises(ValueError):
        accumulator.update(current)
    assert accumulator.hexdigest() == before


@pytest.mark.parametrize("invalid", [None, 1, "bad", ("slot", "model", "1"), {"slot_key": "saved"}])
def test_non_reference_is_rejected_without_corrupting_state(invalid):
    accumulator = contracts.ReferenceSetDigestAccumulator()
    accumulator.update(ref())
    before = accumulator.hexdigest()
    with pytest.raises(TypeError):
        accumulator.update(invalid)
    assert accumulator.hexdigest() == before


def test_ordered_100001_generator_has_constant_auxiliary_memory():
    peaks = []
    # These fixed digests were obtained from the actual pre-T892 public function
    # before implementation; the measured path never constructs a refs list.
    expected = {
        1001: "22df6be95044d69e4f532334ac7ff6020ee6d6ef76c119d37024e202211d9e82",
        100001: "86c2e5872b5d0fc0391baab2d9f48c000397443bf98e47b6c316af906af1fbcf",
    }
    for count, digest in expected.items():
        tracemalloc.start()
        try:
            accumulator = contracts.ReferenceSetDigestAccumulator()
            rows = (ref(f"slot-{index:06}") for index in range(count))
            for row in rows:
                accumulator.update(row)
            actual = accumulator.hexdigest()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert actual == digest
        peaks.append(peak)
    assert max(peaks) < 128 * 1024
    assert peaks[1] <= peaks[0] + 16 * 1024
    print({"ordered_reference_counts": tuple(expected), "tracemalloc_peak_bytes": peaks})
