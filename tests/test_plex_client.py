from types import SimpleNamespace
from backend import plex_client


def make_part(file_path=None, size=None):
    return SimpleNamespace(file=file_path, size=size)


def make_media(parts):
    return SimpleNamespace(parts=parts)


def test_get_movie_file_info_basic():
    # media with two parts
    p1 = make_part("/tmp/movie1.mkv", 1024)
    p2 = make_part("/tmp/movie1_cd2.mkv", 2048)
    movie = SimpleNamespace(media=[make_media([p1, p2])])
    path, size = plex_client.get_movie_file_info(movie)
    assert path == "/tmp/movie1.mkv"
    assert size == 3072


def test_get_movie_file_info_missing_parts():
    movie = SimpleNamespace(media=None)
    path, size = plex_client.get_movie_file_info(movie)
    assert path is None and size is None


def test_get_imdb_id_from_plex_guid_variants():
    assert plex_client.get_imdb_id_from_plex_guid("com.plexapp.agents.imdb://tt1234567?lang=en") == "tt1234567"
    assert plex_client.get_imdb_id_from_plex_guid("imdb://tt7654321") == "tt7654321"
    assert plex_client.get_imdb_id_from_plex_guid("somethingelse://123") is None


def test_get_imdb_id_from_movie_with_guids():
    g1 = SimpleNamespace(id="other://abc")
    g2 = SimpleNamespace(id="imdb://tt9999999")
    movie = SimpleNamespace(guids=[g1, g2], guid=None)
    assert plex_client.get_imdb_id_from_movie(movie) == "tt9999999"


def test_get_best_search_title():
    movie = SimpleNamespace(originalTitle="Original Title", title="Fallback")
    assert plex_client.get_best_search_title(movie) == "Original Title"
    movie2 = SimpleNamespace(originalTitle="", title="Fallback 2")
    assert plex_client.get_best_search_title(movie2) == "Fallback 2"
    movie3 = SimpleNamespace()
    assert plex_client.get_best_search_title(movie3) == ""
