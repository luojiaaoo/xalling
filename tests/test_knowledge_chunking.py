"""使用取自 zvec-grep 99cf43f 输出的固定样本验证文本处理行为。"""

import json
from pathlib import Path

import pytest

from backend.service.knowledge.chunking import chunk_text, index_chunk_options
from backend.service.knowledge.text_files import decode_text, detect_file_type, utf8_text

_REFERENCE = json.loads((Path(__file__).parent / "fixtures" / "zvec-text-parity.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _REFERENCE["chunks"], ids=lambda case: case["name"])
def test_chunks_match_upstream_outputs(case):
    chunks = chunk_text(
        case["text"], markdown=case["markdown"], max_chars=case["max_chars"], overlap_chars=case["overlap_chars"]
    )
    assert chunks == case["expected"]
    assert [utf8_text(chunk) for chunk in chunks] == case["utf8_expected"]


@pytest.mark.parametrize("case", [case for case in _REFERENCE["chunks"] if case["name"].startswith("budget-")])
def test_model_and_density_budget_matches_upstream(case):
    assert index_chunk_options(case["max_input_tokens"], case["text"]) == (case["max_chars"], case["overlap_chars"])


@pytest.mark.parametrize("case", _REFERENCE["files"], ids=lambda case: case["source"])
def test_file_type_matches_upstream(case):
    assert detect_file_type(Path(case["source"])) == case["expected"]


@pytest.mark.parametrize("case", _REFERENCE["sniff"])
def test_binary_sniff_and_decode_match_upstream(case):
    data = bytes.fromhex(case["hex"])
    if case["binary"]:
        with pytest.raises(ValueError, match="二进制"):
            decode_text(data)
    else:
        assert decode_text(data) == case["expected"]


@pytest.mark.parametrize("max_chars,overlap_chars", [(0, 0), (20, -1), (20, 20), (True, 0), (20, 1.5)])
def test_invalid_chunk_budgets_are_rejected(max_chars, overlap_chars):
    with pytest.raises(ValueError):
        chunk_text("text", max_chars=max_chars, overlap_chars=overlap_chars)
