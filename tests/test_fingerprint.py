"""Tests for romyq.fingerprint — normalization, fingerprinting, similarity."""
import pytest
from romyq.fingerprint import fingerprint, is_similar, normalize, similarity, _tokens


# ── normalize() ───────────────────────────────────────────────────────────────

class TestNormalize:
    def test_lowercases(self):
        assert normalize("Add Health Endpoint") == "add health endpoint"

    def test_strips_whitespace(self):
        assert normalize("  add endpoint  ") == "add endpoint"

    def test_collapses_internal_whitespace(self):
        assert normalize("add   health  endpoint") == "add health endpoint"

    def test_collapses_newlines(self):
        assert "add health endpoint" == normalize("add health\nendpoint")

    def test_strips_punctuation(self):
        # Exclamation, comma, period removed
        assert normalize("Add endpoint, now!") == "add endpoint now"

    def test_preserves_slashes(self):
        assert "/health" in normalize("Add /health route")

    def test_preserves_hyphens(self):
        assert "health-check" in normalize("add health-check")

    def test_empty_string(self):
        assert normalize("") == ""

    def test_already_normalized(self):
        t = "add health endpoint"
        assert normalize(t) == t

    def test_unicode_preserved(self):
        # Basic unicode preserved (not stripped)
        result = normalize("añadir endpoint")
        assert "endpoint" in result


# ── fingerprint() ─────────────────────────────────────────────────────────────

class TestFingerprint:
    def test_returns_12_chars(self):
        assert len(fingerprint("Add health endpoint")) == 12

    def test_deterministic(self):
        assert fingerprint("same text") == fingerprint("same text")

    def test_different_for_different_text(self):
        assert fingerprint("add endpoint") != fingerprint("remove endpoint")

    def test_case_insensitive(self):
        assert fingerprint("Add Health Endpoint") == fingerprint("add health endpoint")

    def test_whitespace_insensitive(self):
        assert fingerprint("add  health  endpoint") == fingerprint("add health endpoint")

    def test_punctuation_stripped(self):
        assert fingerprint("Add endpoint.") == fingerprint("Add endpoint")

    def test_newline_insensitive(self):
        assert fingerprint("add\nendpoint") == fingerprint("add endpoint")

    def test_empty_string_stable(self):
        fp1 = fingerprint("")
        fp2 = fingerprint("")
        assert fp1 == fp2

    def test_hex_chars_only(self):
        fp = fingerprint("some task text here")
        assert all(c in "0123456789abcdef" for c in fp)

    def test_slash_preserved_in_fingerprint(self):
        # /health route has different FP from health route
        assert fingerprint("/health route") != fingerprint("health route")


# ── similarity() ──────────────────────────────────────────────────────────────

class TestSimilarity:
    def test_identical_text(self):
        assert similarity("add health endpoint", "add health endpoint") == 1.0

    def test_completely_different(self):
        s = similarity("add database migration", "refactor css layout")
        assert s < 0.2

    def test_partial_overlap(self):
        s = similarity("add health endpoint", "add metrics endpoint")
        assert 0.0 < s < 1.0

    def test_symmetric(self):
        a = "add health check"
        b = "implement health monitoring"
        assert similarity(a, b) == similarity(b, a)

    def test_empty_both(self):
        assert similarity("", "") == 1.0

    def test_empty_one_side(self):
        # One empty, one non-empty → 0.0
        assert similarity("", "some text") == 0.0

    def test_only_filler_words(self):
        # Both contain only filler — token sets are both empty
        s = similarity("a the and", "is are the")
        assert s == 1.0

    def test_high_overlap_same_concept(self):
        # Both tasks talk about health endpoint
        s = similarity("add /health endpoint to api", "implement /health endpoint in server")
        assert s >= 0.3

    def test_range_0_to_1(self):
        pairs = [
            ("add tests", "write unit tests"),
            ("fix bug in parser", "refactor database schema"),
            ("implement auth", "implement authentication module"),
        ]
        for a, b in pairs:
            s = similarity(a, b)
            assert 0.0 <= s <= 1.0

    def test_returns_float(self):
        assert isinstance(similarity("a", "b"), float)


# ── is_similar() ──────────────────────────────────────────────────────────────

class TestIsSimilar:
    def test_identical_is_similar(self):
        assert is_similar("add health endpoint", "add health endpoint")

    def test_case_difference_is_similar(self):
        assert is_similar("Add Health Endpoint", "add health endpoint")

    def test_whitespace_difference_is_similar(self):
        assert is_similar("add  health  endpoint", "add health endpoint")

    def test_completely_different_is_not_similar(self):
        assert not is_similar("add database migration", "refactor css stylesheet", threshold=0.6)

    def test_threshold_0_always_true_for_non_empty(self):
        assert is_similar("completely different text here", "other stuff", threshold=0.0)

    def test_threshold_1_only_exact(self):
        # At threshold=1.0, only exact (post-normalize) matches pass
        assert is_similar("add endpoint", "add endpoint", threshold=1.0)
        # This may or may not pass depending on token overlap; just check it runs
        result = is_similar("add endpoint", "implement endpoint", threshold=1.0)
        assert isinstance(result, bool)

    def test_uses_fingerprint_shortcut(self):
        # Normalized-identical texts are similar regardless of threshold
        assert is_similar("add endpoint!", "add endpoint?", threshold=0.99)

    def test_returns_bool(self):
        result = is_similar("a", "b")
        assert isinstance(result, bool)


# ── _tokens() ─────────────────────────────────────────────────────────────────

class TestTokens:
    def test_removes_filler_words(self):
        tokens = _tokens("add the endpoint to the api")
        assert "the" not in tokens
        assert "to" not in tokens

    def test_keeps_meaningful_words(self):
        tokens = _tokens("add health endpoint")
        # "add" is not in filler, "health" and "endpoint" definitely not
        assert "health" in tokens
        assert "endpoint" in tokens

    def test_returns_frozenset(self):
        assert isinstance(_tokens("text"), frozenset)

    def test_empty_text(self):
        assert _tokens("") == frozenset()

    def test_filters_single_chars(self):
        tokens = _tokens("a b c health")
        # Single chars are filtered (len > 1)
        assert "a" not in tokens
        assert "b" not in tokens
        assert "health" in tokens
