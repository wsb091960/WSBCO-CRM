"""Tests for conservative Esri county verification; no external calls."""
from urllib.parse import parse_qs

from app.services.esri_import import enrich_preview, enrich_next_batch, eligible_rows, suggest_county


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


def test_esri_full_state_name_matches_postal_abbreviation(monkeypatch):
    monkeypatch.setenv("ARCGIS_API_KEY", "test-key")
    data = {"address": "123 Main St", "city": "Salem", "state": "OR", "zip_code": "97301"}
    def fake(_):
        return {"candidates": [{"score": 99, "attributes": {
            "Addr_type": "PointAddress", "Region": "Oregon",
            "Postal": "97301", "Subregion": "Marion County"}}]}
    result = suggest_county(data, fake)
    assert result["status"] == "verified"
    assert result["county"] == "Marion County"


def test_esri_different_full_state_name_is_rejected(monkeypatch):
    monkeypatch.setenv("ARCGIS_API_KEY", "test-key")
    data = {"address": "123 Main St", "city": "Salem", "state": "OR", "zip_code": "97301"}
    def fake(_):
        return {"candidates": [{"score": 99, "attributes": {
            "Addr_type": "PointAddress", "Region": "Washington",
            "Postal": "97301", "Subregion": "Some County"}}]}
    result = suggest_county(data, fake)
    assert result["status"] == "review"
    assert "state_mismatch" in result["reasons"]


def test_resumable_batches_do_not_repeat_calls():
    result = {"rows": [
        {"row": i, "action": "create", "data": {"county": ""}}
        for i in range(2, 27)
    ]}
    calls = []
    def fake(data):
        calls.append(1)
        return {"status": "review", "county": ""}
    first = enrich_next_batch(result, limit=10, lookup=fake)
    second = enrich_next_batch(result, previous=first, limit=10, lookup=fake)
    third = enrich_next_batch(result, previous=second, limit=10, lookup=fake)
    fourth = enrich_next_batch(result, previous=third, limit=10, lookup=fake)
    assert [len(first), len(second), len(third), len(fourth)] == [10, 20, 25, 25]
    assert len(calls) == 25
    assert len(eligible_rows(result)) == 25


def test_batch_skips_existing_county_and_non_import_rows():
    result = {"rows": [
        {"row": 2, "action": "create", "data": {"county": "Lane"}},
        {"row": 3, "action": "skip", "data": {"county": ""}},
        {"row": 4, "action": "create", "data": {"county": ""}},
    ]}
    assert [row["row"] for row in eligible_rows(result)] == [4]
