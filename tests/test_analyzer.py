from types import SimpleNamespace
from backend import analyzer


def make_movie(title="Sample", year=2020):
    return SimpleNamespace(
        librarySectionTitle="MyLib",
        title=title,
        year=year,
        rating=None,
        ratingKey="rk1",
        guid="imdb://tt0000001",
        thumb=None,
        media=[],
    )


def test_analyze_single_movie_minimal(monkeypatch):
    movie = make_movie("My Movie", 2010)

    # Patch external dependencies to deterministic fakes
    monkeypatch.setattr(analyzer, "get_movie_record", lambda title, year, imdb_id_hint: {
        "imdbID": "tt0000001",
        "imdbRating": "7.0",
        "imdbVotes": "1,000",
        "Ratings": [{"Source": "Rotten Tomatoes", "Value": "80%"}],
        "Poster": "http://example.com/poster.jpg",
        "Website": "http://example.com",
    })

    monkeypatch.setattr(analyzer, "decide_action", lambda r, v, rt, year, metacritic_score=None: ("MAYBE", "reason"))
    monkeypatch.setattr(analyzer, "get_movie_file_info", lambda m: ("/tmp/f.mp4", 12345))
    monkeypatch.setattr(analyzer, "generate_metadata_suggestions_row", lambda movie, omdb: None)
    monkeypatch.setattr(analyzer, "detect_misidentified", lambda title, year, omdb, ir, iv, rt: "")

    row, meta, logs = analyzer.analyze_single_movie(movie)
    assert isinstance(row, dict)
    assert row["title"] == "My Movie"
    assert row["imdb_id"] == "tt0000001"
    assert row["decision"] == "MAYBE"
    assert row["file"] == "/tmp/f.mp4"
