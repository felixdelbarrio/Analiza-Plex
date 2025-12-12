from backend.scoring import compute_scoring, decide_action


def test_compute_scoring_basic_keep():
    # Peli con buen rating y muchos votos debería tender a KEEP o MAYBE
    res = compute_scoring(imdb_rating=8.5, imdb_votes=5000, rt_score=85, year=2015)
    assert isinstance(res, dict)
    assert "decision" in res
    assert "inputs" in res


def test_compute_scoring_no_data_unknown():
    res = compute_scoring(imdb_rating=None, imdb_votes=None, rt_score=None, year=None)
    assert res["decision"] == "UNKNOWN"


def test_decide_action_tuple():
    d, reason = decide_action(imdb_rating=7.0, imdb_votes=1500, rt_score=60, year=2010)
    assert isinstance(d, str)
    assert isinstance(reason, str)
