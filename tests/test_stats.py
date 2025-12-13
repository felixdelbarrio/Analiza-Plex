from backend import stats
import math
import pandas as pd


def test_compute_global_imdb_mean_from_df():
    df = pd.DataFrame({"imdb_rating": [7.0, 8.0, None, "9.0"]})
    mean = stats.compute_global_imdb_mean_from_df(df)
    # (7 + 8 + 9) / 3 = 8.0
    assert isinstance(mean, float)
    assert abs(mean - 8.0) < 1e-6


def test_global_imdb_mean_is_number_from_cache(monkeypatch):
    # If omdb_cache is empty, function should return a float default
    monkeypatch.setattr(stats, "omdb_cache", {})
    # Reset internal cached value to force recompute
    monkeypatch.setattr(stats, "_GLOBAL_IMDB_MEAN_FROM_CACHE", None)
    mean = stats.get_global_imdb_mean_from_cache()
    assert isinstance(mean, float)
    assert not math.isnan(mean)
