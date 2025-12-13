from backend import omdb_client


def test_normalize_imdb_votes_variants():
    assert omdb_client.normalize_imdb_votes("1,234") == 1234
    assert omdb_client.normalize_imdb_votes(5678) == 5678
    assert omdb_client.normalize_imdb_votes("N/A") is None
    assert omdb_client.normalize_imdb_votes(None) is None


def test_parse_rt_and_imdb_rating_and_year():
    data = {
        "Ratings": [{"Source": "Rotten Tomatoes", "Value": "85%"}],
        "imdbRating": "7.3",
        "Year": "2019" ,
    }
    assert omdb_client.parse_rt_score_from_omdb(data) == 85
    assert abs(omdb_client.parse_imdb_rating_from_omdb(data) - 7.3) < 1e-6
    assert omdb_client.extract_year_from_omdb(data) == 2019


def test_extract_ratings_and_empty():
    data = {
        "Ratings": [{"Source": "Rotten Tomatoes", "Value": "90%"}],
        "imdbRating": "8.0",
        "imdbVotes": "10,000",
    }
    r, v, rt = omdb_client.extract_ratings_from_omdb(data)
    assert abs(r - 8.0) < 1e-6
    assert v == 10000
    assert rt == 90

    assert omdb_client.is_omdb_data_empty_for_ratings({}) is True
    assert omdb_client.is_omdb_data_empty_for_ratings(None) is True
