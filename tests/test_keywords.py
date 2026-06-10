"""Tests for keyword extraction and coverage computation."""

from job_search.generation.keywords import KeywordExtractor


def test_extracts_tier1_keywords():
    extractor = KeywordExtractor()
    jd = "Experience with AutoCAD Civil 3D and HEC-RAS required. EIT preferred."
    keywords = extractor.extract(jd)
    tier1 = {k.keyword.lower() for k in keywords if k.tier == 1}
    assert any("civil 3d" in kw or "autocad" in kw for kw in tier1)
    assert any("hec-ras" in kw for kw in tier1)


def test_coverage_100_when_all_present():
    extractor = KeywordExtractor()
    jd = "AutoCAD Civil 3D required. Structural analysis. Engineer in Training (EIT)."
    keywords = extractor.extract(jd)
    # Document contains all extracted keywords
    coverage, hits, misses = extractor.compute_coverage(keywords, jd)
    assert coverage == 1.0
    assert len(misses) == 0


def test_coverage_partial():
    extractor = KeywordExtractor()
    jd = "AutoCAD Civil 3D required. HEC-RAS. Structural analysis. EIT preferred."
    keywords = extractor.extract(jd)
    # Document missing some keywords
    doc = "AutoCAD Civil 3D experience. Some structural background."
    coverage, hits, misses = extractor.compute_coverage(keywords, doc)
    assert 0.0 < coverage < 1.0
    assert len(misses) > 0
