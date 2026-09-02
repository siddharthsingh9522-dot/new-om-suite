"""
Unit tests for the remark parsing / merge logic (no network calls needed).
Run with: python -m pytest tests/ -v   (or plain `python tests/test_remark_parser.py`)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.remark_parser import extract_party_code, build_final_remark, already_applied


def test_extract_party_code_variants():
    cases = ["CODE 838219", "C0DE 838219", "code: 838219", "CODE-838219"]
    for text in cases:
        code, method = extract_party_code(text)
        assert code == "838219", f"Failed for: {text}"
        assert method == "matched_code_keyword"


def test_extract_party_code_not_found():
    code, method = extract_party_code("no code here at all")
    assert code is None
    assert method == "not_found"


def test_build_final_remark_prepends_new_before_old():
    final, action = build_final_remark("OLD REMARK ABC", "C0DE 838219 @halol_acc dt22/08/2026 &")
    assert final == "C0DE 838219 @halol_acc dt22/08/2026 & OLD REMARK ABC"
    assert action == "READY"


def test_build_final_remark_empty_existing():
    final, action = build_final_remark(None, "C0DE 838219 @halol_acc dt22/08/2026 &")
    assert final == "C0DE 838219 @halol_acc dt22/08/2026 &"
    assert action == "READY"


def test_duplicate_protection_skips_reapply():
    existing = "C0DE 838219 @halol_acc dt22/08/2026 & OLD REMARK"
    new = "C0DE 838219 @halol_acc dt22/08/2026 &"
    final, action = build_final_remark(existing, new)
    assert action == "ALREADY_APPLIED"
    assert final == existing


if __name__ == "__main__":
    test_extract_party_code_variants()
    test_extract_party_code_not_found()
    test_build_final_remark_prepends_new_before_old()
    test_build_final_remark_empty_existing()
    test_duplicate_protection_skips_reapply()
    print("All tests passed.")
