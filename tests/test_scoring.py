from backend import scoring


def test_compute_scoring_basic_keep(monkeypatch):
    # Hacemos el entorno determinista: fijamos umbrales y media global
    monkeypatch.setattr(scoring, "get_votes_threshold_for_year", lambda y: 5)
    monkeypatch.setattr(scoring, "get_global_imdb_mean_from_cache", lambda: 6.0)
    monkeypatch.setattr(scoring, "get_auto_keep_rating_threshold", lambda: 6.5)
    monkeypatch.setattr(scoring, "get_auto_delete_rating_threshold", lambda: 4.0)

    # Peli con buen rating y muchos votos debería clasificarse como KEEP
    res = scoring.compute_scoring(imdb_rating=8.5, imdb_votes=5000, rt_score=85, year=2015)
    assert isinstance(res, dict)
    assert res["decision"] == "KEEP"
    assert "inputs" in res


def test_compute_scoring_no_data_unknown():
    res = scoring.compute_scoring(imdb_rating=None, imdb_votes=None, rt_score=None, year=None)
    assert res["decision"] == "UNKNOWN"


def test_decide_action_tuple(monkeypatch):
    # Determinismo similar al primer test
    monkeypatch.setattr(scoring, "get_votes_threshold_for_year", lambda y: 10)
    monkeypatch.setattr(scoring, "get_global_imdb_mean_from_cache", lambda: 6.5)
    monkeypatch.setattr(scoring, "get_auto_keep_rating_threshold", lambda: 7.0)
    monkeypatch.setattr(scoring, "get_auto_delete_rating_threshold", lambda: 4.0)

    d, reason = scoring.decide_action(imdb_rating=7.5, imdb_votes=1500, rt_score=60, year=2010)
    assert isinstance(d, str)
    assert isinstance(reason, str)
    assert d in ("KEEP", "MAYBE", "DELETE", "UNKNOWN")


def test__compute_bayes_score_edge_cases():
    # Import internal helper for edge case testing
    f = scoring._compute_bayes_score
    assert f(None, 100, 5, 6.0) is None
    assert f(7.0, None, 5, 6.0) is None
    # negative votes -> None
    assert f(7.0, -10, 5, 6.0) is None
    # zero votes with m=0 -> None
    assert f(7.0, 0, 0, 6.0) is None
    # normal case
    val = f(8.0, 100, 10, 6.0)
    assert isinstance(val, float)
