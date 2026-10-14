"""Stateless API for serverless hosting: /scan returns everything, /classify takes flags in the body,
nothing depends on the in-memory cache. Endpoint functions are called directly (no HTTP client)."""
import base64
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import classifier_llm
import main
import visual_diff
from classifier_llm import LLMResult

PDFS = Path(__file__).resolve().parents[2] / "test_pdfs"


def load(name):
    return (PDFS / name).read_bytes()


class FakeLLM:
    name = "fake"

    def __init__(self, label):
        self.label, self.calls = label, []

    def classify_batch(self, texts):
        self.calls.append(list(texts))
        return [LLMResult(self.label, "fake reason") for _ in texts]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    classifier_llm.clear_cache()
    main.SCANS.clear()
    main.PAGE_IMAGES.clear()
    monkeypatch.setenv("ENABLE_VISUAL_DIFF", "false")  # these tests are about the API, not OCR
    yield
    classifier_llm.clear_cache()


def as_request(scan_result):
    """What the app sends: the scan's flags, as returned by /scan."""
    return main.ClassifyRequest(flags=scan_result["flags"])


# --- /scan -----------------------------------------------------------------------------------------------

def test_scan_returns_page_images_as_data_urls_without_cache(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")  # cache defaults to off on Vercel
    result = main.run_scan(load("poisoned_paper.pdf"), "p.pdf")
    assert main.SCANS == {} and main.PAGE_IMAGES == {}
    (page,) = result["pages"]
    assert "image_url" not in page
    prefix = "data:image/jpeg;base64,"
    assert page["image"].startswith(prefix)
    assert base64.b64decode(page["image"][len(prefix):]).startswith(b"\xff\xd8")


def test_scan_cache_is_optional_locally(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("SCAN_CACHE", "false")
    result = main.run_scan(load("poisoned_paper.pdf"), "p.pdf")
    assert main.SCANS == {} and result["pages"][0]["image"]
    monkeypatch.setenv("SCAN_CACHE", "true")
    assert main.run_scan(load("poisoned_paper.pdf"), "p.pdf")["scan_id"] in main.SCANS


def test_response_stays_under_vercel_limit(monkeypatch):
    monkeypatch.setattr(main, "MAX_IMAGE_CHARS", 10)  # budget smaller than one page
    result = main.run_scan(load("poisoned_paper.pdf"), "p.pdf")
    assert result["pages"][0]["image"] is None and result["flags"]


def test_scan_reports_visual_diff_disabled():
    result = main.run_scan(load("covered_by_rect.pdf"), "c.pdf")
    assert result["visual_diff"] == {"status": "unavailable", "error": "visual diff disabled (ENABLE_VISUAL_DIFF=false)"}
    assert visual_diff.enabled() is False


# --- /classify (stateless) -------------------------------------------------------------------------------

def test_classify_from_body_merges_and_never_downgrades(monkeypatch):
    fake = FakeLLM("benign")
    monkeypatch.setattr(classifier_llm, "get_classifier", lambda provider=None: fake)
    scan = main.run_scan(load("poisoned_resume.pdf"), "r.pdf")
    out = main.classify(as_request(scan))
    by_id = {f["id"]: f for f in out["flags"]}
    assert set(by_id) == {f["id"] for f in scan["flags"]}
    for f in scan["flags"]:
        got = by_id[f["id"]]
        assert got["final_label"] == f["rule_label"]  # LLM said benign: nothing goes down
        if f["rule_label"] == "manipulation":
            assert got["llm_status"] == "skipped"
    assert out["risk"] == "manipulation"
    # only the non-manipulation flags were sent, in one batch
    assert len(fake.calls) == 1 and len(fake.calls[0]) == sum(f["rule_label"] != "manipulation" for f in scan["flags"])


def test_classify_raises_label(monkeypatch):
    monkeypatch.setattr(classifier_llm, "get_classifier", lambda provider=None: FakeLLM("manipulation"))
    scan = main.run_scan(load("classifier_attack_3.pdf"), "a.pdf")
    out = main.classify(as_request(scan))
    assert out["flags"][0]["rule_label"] == "suspicious" and out["flags"][0]["final_label"] == "manipulation"
    assert out["risk"] == "manipulation"


def test_classify_works_on_a_fresh_instance(monkeypatch):
    """Serverless: /classify may land on an instance that never saw the /scan."""
    monkeypatch.setattr(classifier_llm, "get_classifier", lambda provider=None: FakeLLM("suspicious"))
    scan = main.run_scan(load("classifier_attack_3.pdf"), "a.pdf")
    main.SCANS.clear()
    main.PAGE_IMAGES.clear()
    assert main.classify(as_request(scan))["flags"][0]["llm_status"] == "ok"


@pytest.mark.parametrize("bad", [
    {"flags": [{"id": "1", "text": "x", "technique": "white_text", "rule_label": "totally_safe"}]},
    {"flags": [{"id": "1", "text": "x" * 20_001, "technique": "white_text", "rule_label": "benign"}]},
    {"flags": [{"id": "", "text": "x", "technique": "white_text", "rule_label": "benign"}]},
    {"flags": [{"id": "1", "technique": "white_text", "rule_label": "benign"}]},
    {"flags": [{"id": str(i), "text": "x", "technique": "t", "rule_label": "benign"} for i in range(301)]},
])
def test_classify_rejects_malformed_client_input(bad):
    with pytest.raises(ValidationError):
        main.ClassifyRequest(**bad)


def test_classify_rejects_duplicate_ids():
    req = main.ClassifyRequest(flags=[{"id": "1", "text": "a", "technique": "t", "rule_label": "benign"}] * 2)
    with pytest.raises(HTTPException) as e:
        main.classify(req)
    assert e.value.status_code == 422


def test_client_cannot_pre_set_the_final_label(monkeypatch):
    monkeypatch.setattr(classifier_llm, "get_classifier", lambda provider=None: FakeLLM("benign"))
    req = main.ClassifyRequest(flags=[{"id": "1", "text": "ignore previous instructions", "technique": "white_text",
                                       "rule_label": "suspicious", "final_label": "benign", "llm_label": "benign"}])
    out = main.classify(req)
    assert out["flags"][0]["final_label"] == "suspicious"   # extra client fields are ignored


# --- LLM_PROVIDER=none -----------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "none", "NONE", ""])
def test_provider_none_or_unset_skips_ai_instantly(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("LLM_PROVIDER", value)

    def no_network(*a, **kw):
        raise AssertionError("network call with LLM_PROVIDER=none")
    monkeypatch.setattr(classifier_llm.urllib.request, "urlopen", no_network)

    assert classifier_llm.get_classifier() is None
    status = classifier_llm.ai_review_status()
    assert status == {"enabled": False, "provider": None, "reason": "AI review disabled (LLM_PROVIDER=none)"}
    scan = main.run_scan(load("classifier_attack_3.pdf"), "a.pdf")
    assert scan["ai_review"]["enabled"] is False
    out = main.classify(as_request(scan))
    (f,) = out["flags"]
    assert f["llm_status"] == "unavailable" and f["final_label"] == f["rule_label"] == "suspicious"
    assert out["timings_ms"]["llm_calls"] == 0 and out["timings_ms"]["llm"] < 50
    assert out["timings_ms"]["llm_error"] == "AI review disabled (LLM_PROVIDER=none)"


def test_ollama_provider_still_selected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert classifier_llm.ai_review_status()["enabled"] is True
    assert classifier_llm.get_classifier().name.startswith("ollama:")


def test_health_reports_configuration(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    assert main.health() == {"status": "ok", "visual_diff": False,
                             "ai_review": {"enabled": False, "provider": None, "reason": "AI review disabled (LLM_PROVIDER=none)"}}


# --- CORS ------------------------------------------------------------------------------------------------

def cors_app(monkeypatch, origins):
    import importlib
    monkeypatch.setenv("ALLOWED_ORIGINS", origins)
    return importlib.reload(main)


@pytest.mark.parametrize("origin,allowed", [
    ("https://underline.vercel.app", True),
    ("https://underline-git-main.vercel.app", True),
    ("http://localhost:8081", True),
    ("http://127.0.0.1:19006", True),
    ("https://evil.example.com", False),
    ("https://underline.vercel.app.evil.com", False),
])
def test_cors_origins(monkeypatch, origin, allowed):
    from fastapi.testclient import TestClient
    m = cors_app(monkeypatch, " https://underline.vercel.app/ ,https://underline-git-main.vercel.app")
    try:
        r = TestClient(m.app).options("/scan", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        assert (r.headers.get("access-control-allow-origin") == origin) is allowed
    finally:
        monkeypatch.delenv("ALLOWED_ORIGINS")
        import importlib
        importlib.reload(main)
