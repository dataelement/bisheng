"""Compare two pytest junit XML files and list newly failing test cases.

Usage: python compare_junit.py <baseline.xml> <current.xml>

A test case counts as a new failure when it fails or errors in the current run
and either passed (or was skipped) in the baseline or did not exist there.
The last output line is always ``NEW FAILURES: <n>``.
"""

import sys
import xml.etree.ElementTree as ET


def load(path):
    """Return {case_id: status} where status is pass/fail/skip."""
    result = {}
    root = ET.parse(path).getroot()
    for case in root.iter("testcase"):
        case_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        status = "pass"
        for child in case:
            if child.tag in ("failure", "error"):
                status = "fail"
                break
            if child.tag == "skipped":
                status = "skip"
        # A case may appear twice (call failure + teardown error); fail wins.
        if result.get(case_id) == "fail":
            continue
        result[case_id] = status
    return result


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        print("NEW FAILURES: -1")
        return 2
    baseline = load(argv[1])
    current = load(argv[2])
    new_failures = sorted(
        case_id for case_id, status in current.items() if status == "fail" and baseline.get(case_id) != "fail"
    )
    for case_id in new_failures:
        print(case_id)
    print(f"NEW FAILURES: {len(new_failures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
