from backend.stats import get_global_imdb_mean_from_cache
import math


def test_global_imdb_mean_is_number():
    mean = get_global_imdb_mean_from_cache()
    assert isinstance(mean, float)
    assert not math.isnan(mean)
