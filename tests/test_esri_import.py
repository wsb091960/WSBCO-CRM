"""Tests for conservative Esri county verification; no external calls."""
from urllib.parse import parse_qs

from app.services.esri_import import enrich_preview, suggest_county


def test_verified_county_when_street_state_and_zip_agree(monkeypatch):
    monkeypatch.setenv("ARCGIS_API_KEY", "test-key")
    data = {"address": "123 Main St", "city": "Salem", "state": "OR", "zip_code": "97301", "county": ""}
    def fake(body):
        fields = parse_qs(body.decode())
        assert "123 Main St" in fields["SingleLine"][0]
        assert "first_name" not in fields
        return {"candidates": [{"score": 99, "attributes": {
            "Addr_type": "PointAddress", "Region": "OR",
            "Postal": "97301", "Subregion": "Marion County"}}]}
    assert suggest_county(data, fake)["county"] == "Marion County"


def test_zip_mismatch_requires_review(monkeypatch):
    monkeypatch.setenv("ARCGIS_API_KEY", "test-key")
    data = {"address": "123 Main St", "city": "Salem", "state": "OR", "zip_code": "97301"}
    def fake(_):
        return {"candidates": [{"score": 100, "attributes": {
            "Addr_type": "PointAddress", "Region": "OR",
            "Postal": "97401", "Subregion": "Lane County"}}]}
    result = suggest_county(data, fake)
    assert result["status"] == "review"
    assert "zip_mismatch" in result["reasons"]


def test_existing_county_is_never_overwritten():
    assert suggest_county({"county": "Douglas County"})["status"] == "existing"


def test_preview_limits_requests():
    result = {"rows": [
        {"row": i, "action": "create", "data": {"county": ""}}
        for i in range(2, 25)
    ]}
    calls = []
    def fake(data):
        calls.append(data)
        return {"status": "review", "county": ""}
    suggestions = enrich_preview(result, limit=10, lookup=fake)
    assert len(suggestions) == len(calls) == 10


def test_missing_esri_county_explains_review(monkeypatch):
    monkeypatch.setenv("ARCGIS_API_KEY", "test-key")
    data = {"address": "123 Main St", "city": "Salem", "state": "OR", "zip_code": "97301"}
    def fake(_):
        return {"candidates": [{"score": 100, "attributes": {
            "Addr_type": "PointAddress", "Region": "OR", "Postal": "97301"}}]}
    result = suggest_county(data, fake)
    assert result["status"] == "review"
    assert "county_missing" in result["reasons"]
