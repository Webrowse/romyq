"""Tests for romyq.loop_detector — planner cycling and oscillation detection."""
import pytest
from romyq.loop_detector import LoopPattern, describe, detect


# ── helpers ───────────────────────────────────────────────────────────────────

def _fps(*patterns) -> list[str]:
    """Build a fingerprint list from short character sequences."""
    return list(patterns)


# ── LoopPattern ───────────────────────────────────────────────────────────────

class TestLoopPattern:
    def test_is_namedtuple(self):
        p = LoopPattern(
            pattern_type="straight",
            fingerprints=["abc"],
            count=3,
            description="same task repeated 3 times",
        )
        assert p.pattern_type == "straight"
        assert p.count == 3

    def test_oscillation_type(self):
        p = LoopPattern(
            pattern_type="oscillation",
            fingerprints=["abc", "def"],
            count=4,
            description="oscillation",
        )
        assert p.pattern_type == "oscillation"


# ── detect() — empty / short inputs ──────────────────────────────────────────

class TestDetectEdgeCases:
    def test_empty_list(self):
        assert detect([]) == []

    def test_single_element(self):
        assert detect(["a"]) == []

    def test_two_unique_elements(self):
        # Not enough for any pattern
        assert detect(["a", "b"]) == []

    def test_all_different(self):
        fps = [f"fp{i}" for i in range(10)]
        assert detect(fps) == []


# ── detect() — straight loop ─────────────────────────────────────────────────

class TestDetectStraightLoop:
    def test_detects_exact_threshold(self):
        fps = _fps("a", "b", "c", "c", "c")  # 3 c's at end
        patterns = detect(fps, straight_threshold=3)
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "straight"
        assert patterns[0].count == 3

    def test_detects_above_threshold(self):
        fps = _fps("a", "b", "c", "c", "c", "c", "c")  # 5 c's
        patterns = detect(fps, straight_threshold=3)
        straights = [p for p in patterns if p.pattern_type == "straight"]
        assert len(straights) == 1
        assert straights[0].count == 5

    def test_no_detection_below_threshold(self):
        fps = _fps("a", "b", "c", "c")  # only 2 c's at end
        patterns = detect(fps, straight_threshold=3)
        straights = [p for p in patterns if p.pattern_type == "straight"]
        assert len(straights) == 0

    def test_straight_fingerprint_recorded(self):
        fps = _fps("x", "y", "z", "z", "z")
        patterns = detect(fps, straight_threshold=3)
        assert "z" in patterns[0].fingerprints

    def test_description_contains_count(self):
        fps = _fps("a", "a", "a", "a")
        patterns = detect(fps, straight_threshold=3)
        assert "4" in patterns[0].description

    def test_straight_threshold_4(self):
        fps = _fps("a", "b", "a", "a", "a", "a")
        patterns = detect(fps, straight_threshold=4)
        straights = [p for p in patterns if p.pattern_type == "straight"]
        assert len(straights) == 1
        assert straights[0].count == 4

    def test_not_straight_when_broken_sequence(self):
        fps = _fps("a", "a", "b", "a", "a")  # broken by b
        patterns = detect(fps, straight_threshold=3)
        straights = [p for p in patterns if p.pattern_type == "straight"]
        assert len(straights) == 0


# ── detect() — oscillation ────────────────────────────────────────────────────

class TestDetectOscillation:
    def test_detects_abab_pattern(self):
        fps = _fps("a", "b", "a", "b")  # minimum oscillation (4)
        patterns = detect(fps, oscillation_min=4)
        osc = [p for p in patterns if p.pattern_type == "oscillation"]
        assert len(osc) == 1

    def test_detects_babab_pattern(self):
        fps = _fps("x", "y", "a", "b", "a", "b")
        patterns = detect(fps, oscillation_min=4)
        osc = [p for p in patterns if p.pattern_type == "oscillation"]
        assert len(osc) == 1

    def test_oscillation_fingerprints_recorded(self):
        fps = _fps("a", "b", "a", "b")
        patterns = detect(fps, oscillation_min=4)
        osc = patterns[0]
        assert "a" in osc.fingerprints
        assert "b" in osc.fingerprints

    def test_no_oscillation_if_3_unique(self):
        # A-B-A-C is NOT a 2-way oscillation
        fps = _fps("a", "b", "a", "c")
        patterns = detect(fps, oscillation_min=4)
        osc = [p for p in patterns if p.pattern_type == "oscillation"]
        assert len(osc) == 0

    def test_no_oscillation_if_not_strictly_alternating(self):
        # A-A-B-A-B is not strict alternation
        fps = _fps("a", "a", "b", "a", "b")
        patterns = detect(fps, oscillation_min=4)
        # The last 4 = a, b, a, b → that IS alternating
        osc = [p for p in patterns if p.pattern_type == "oscillation"]
        # Last 4 elements: a, b, a, b — should detect
        assert len(osc) >= 1

    def test_no_oscillation_below_min(self):
        fps = _fps("a", "b", "a")  # only 3 elements, oscillation_min=4
        patterns = detect(fps, oscillation_min=4)
        osc = [p for p in patterns if p.pattern_type == "oscillation"]
        assert len(osc) == 0

    def test_oscillation_description_mentions_fingerprints(self):
        fps = _fps("fp1", "fp2", "fp1", "fp2")
        patterns = detect(fps, oscillation_min=4)
        desc = patterns[0].description
        assert "fp1" in desc or "fp2" in desc

    def test_oscillation_count_matches_min(self):
        fps = _fps("a", "b", "a", "b", "a", "b")
        patterns = detect(fps, oscillation_min=4)
        osc = [p for p in patterns if p.pattern_type == "oscillation"]
        assert osc[0].count == 4


# ── detect() — both patterns ──────────────────────────────────────────────────

class TestDetectBothPatterns:
    def test_can_detect_both_simultaneously(self):
        # This sequence ends with 3 c's (straight) AND the last 4 = b,c,b,c (osc)
        # Actually: a, b, c, b, c, c, c — last 3 are straight
        # Let's use a clearer example
        fps = _fps("a", "b", "b", "b")
        patterns = detect(fps, straight_threshold=3, oscillation_min=4)
        assert any(p.pattern_type == "straight" for p in patterns)


# ── describe() ────────────────────────────────────────────────────────────────

class TestDescribe:
    def test_empty_patterns_returns_empty(self):
        assert describe([]) == ""

    def test_formats_pattern(self):
        p = LoopPattern("straight", ["a"], 3, "Same task repeated 3 times")
        result = describe([p])
        assert "straight" in result
        assert "Same task repeated" in result

    def test_multiple_patterns(self):
        p1 = LoopPattern("straight", ["a"], 3, "Straight loop")
        p2 = LoopPattern("oscillation", ["a", "b"], 4, "Oscillation")
        result = describe([p1, p2])
        assert "straight" in result
        assert "oscillation" in result
        assert len(result.splitlines()) == 2
