"""A story passes only when every number it states is in the paper entry it was written from."""

from newsroom.gate import numbers, unsupported

PAPER = {
    "regimen": "EC+mFOLFOX6 vs SOC (1L)",
    "studyType": "Phase 3 RCT (updated)",
    "n": 479,
    "endpoint": "PFS by BICR + OS",
    "result": "mPFS 12.8 vs 7.1 mo; mOS 30.3 vs 15.1 mo, HR 0.49",
    "bottomLine": "mOS 30.3 個月",
    "journal": "NEJM",
    "year": 2025,
}


def _story(**changes) -> dict:
    story = {
        "headline": ["BREAKWATER：", "mOS 達 ", "30.3 個月"],
        "dek": "共 479 人，HR 0.49。",
        "key": {"value": "30.3", "unit": "個月", "label": "mOS，對照組 15.1 個月"},
        "figures": [
            {
                "kind": "compare",
                "armA": "EC",
                "armB": "SOC",
                "rows": [{"label": "mOS", "unit": "個月", "a": 30.3, "b": 15.1}],
            }
        ],
        "figureNote": "NEJM 2025",
        "body": [{"heading": "發生了什麼", "text": "Phase 3 試驗，mPFS 是 12.8 對 7.1 個月。"}],
    }
    return story | changes


def test_story_built_from_the_entry_passes():
    assert unsupported(_story(), PAPER) == []


def test_number_missing_from_the_entry_is_reported_wherever_it_appears():
    assert unsupported(_story(dek="共 479 人，HR 0.49（95% CI 0.38–0.63）。"), PAPER) == ["0.38", "0.63", "95"]
    in_figure = [{"kind": "numbers", "stats": [{"label": "ORR", "value": "61", "unit": "%"}]}]
    assert unsupported(_story(figures=in_figure), PAPER) == ["61"]


def test_a_count_the_writer_made_up_is_reported():
    assert unsupported(_story(key={"value": "4", "unit": "項", "label": "主要更新"}), PAPER) == ["4"]


def test_the_same_number_written_two_ways_matches():
    assert numbers("4.0 個月、4 個月、0.490") == {"4", "0.49"}
    assert unsupported(_story(dek="mOS 30.30 個月。"), PAPER) == []


def test_optional_figure_note_may_be_omitted():
    story = _story()
    del story["figureNote"]
    assert unsupported(story, PAPER) == []
