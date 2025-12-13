from pathlib import Path
from backend.reporting import write_interactive_html


def test_write_interactive_html_creates_file(tmp_path: Path):
    rows = [
        {
            "poster_url": None,
            "library": "MyLib",
            "title": "Sample Movie",
            "year": 2020,
            "imdb_rating": 7.2,
            "rt_score": 85,
            "imdb_votes": 1200,
            "metacritic_score": 70,
            "decision": "MAYBE",
            "reason": "Test",
            "misidentified_hint": "",
            "file": "/path/to/file.mp4",
        }
    ]

    out = tmp_path / "report.html"
    write_interactive_html(str(out), rows)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Plex Movies Cleaner" in text
    assert "Sample Movie" in text
    # El JSON de filas debe estar presente en una etiqueta <script type="application/json">
    assert '<script id="rows-data" type="application/json">' in text
    # Extraemos y parseamos el JSON para comprobar estructura mínima
    start = text.find('<script id="rows-data" type="application/json">')
    assert start != -1
    start = text.find('>', start) + 1
    end = text.find('</script>', start)
    rows_json = text[start:end].strip()
    import json
    parsed = json.loads(rows_json)
    assert isinstance(parsed, list)
    assert parsed[0]["title"] == "Sample Movie"
