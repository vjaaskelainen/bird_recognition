import csv
import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest
from tools import review_crops


@pytest.fixture
def review_server(
    tmp_path: Path,
) -> Iterator[tuple[ThreadingHTTPServer, str, Path]]:
    csv_path = tmp_path / "review.csv"
    row = {
        "run_id": "run-1",
        "crop_id": "crop-1",
        "lighting": "day",
        "animal_type": "",
        "image_path": "private/crop.jpg",
        "expected_species_id": "",
        "truth_kind": "",
        "notes": "",
        "expected_category": "",
    }
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=review_crops.FIELDS)
        writer.writeheader()
        writer.writerow(row)
    rows = review_crops.load_rows(csv_path)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        review_crops.make_handler(
            csv_path, rows, [{"id": "great_tit", "name": "Great tit"}]
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, f"http://127.0.0.1:{server.server_address[1]}", csv_path
    server.shutdown()
    thread.join()
    server.server_close()


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("great_tit", ("great_tit", "species")),
        ("out_of_list", ("", "out_of_list")),
        ("unidentifiable", ("", "unidentifiable")),
        ("unusable", ("", "unusable")),
        ("not-in-list", ("", "out_of_list")),
        ("unknown", ("", "unidentifiable")),
    ],
)
def test_derive_truth_maps_legacy_and_current_choices(
    choice: str, expected: tuple[str, str]
) -> None:
    assert review_crops.derive_truth(choice) == expected


def test_load_taxa_accepts_legacy_species_schema(tmp_path: Path) -> None:
    path = tmp_path / "species.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "species": [{"id": "great_tit", "name": "Great tit"}],
            }
        ),
        encoding="utf-8",
    )

    assert review_crops.load_taxa(path) == [{"id": "great_tit", "name": "Great tit"}]


def test_load_taxa_accepts_strict_external_taxonomy(tmp_path: Path) -> None:
    path = tmp_path / "taxonomy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "taxa": [
                    {
                        "id": "parus_major",
                        "common_name": "Great tit",
                        "category": "bird",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert review_crops.load_taxa(path) == [
        {"id": "parus_major", "common_name": "Great tit", "category": "bird"}
    ]


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": 1, "taxa": [{"id": "x", "common_name": "X"}]},
        {
            "schema_version": 1,
            "taxa": [{"id": "x", "common_name": "X", "category": "reptile"}],
        },
        {
            "schema_version": 1,
            "taxa": [
                {
                    "id": "x",
                    "common_name": "X",
                    "category": "bird",
                    "unexpected": "value",
                }
            ],
        },
    ],
)
def test_load_taxa_rejects_invalid_external_taxonomy(
    tmp_path: Path, document: dict[str, object]
) -> None:
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SystemExit, match="taxonomy"):
        review_crops.load_taxa(path)


def test_post_saves_truth_and_optional_category(
    review_server: tuple[ThreadingHTTPServer, str, Path],
) -> None:
    _, url, csv_path = review_server
    response = urlopen(
        url,
        data=urlencode(
            {
                "i": "0",
                "animal_type": "unusable",
                "lighting": "unknown",
                "expected_category": "mammal",
                "notes": "reviewed",
                "action": "next",
            }
        ).encode("utf-8"),
    )

    assert response.status == 200
    with csv_path.open(newline="", encoding="utf-8") as handle:
        saved_row = next(csv.DictReader(handle))
    assert saved_row["animal_type"] == "unusable"
    assert saved_row["truth_kind"] == "unusable"
    assert saved_row["expected_species_id"] == ""
    assert saved_row["expected_category"] == "mammal"
    assert saved_row["notes"] == "reviewed"


@pytest.mark.parametrize("expected_category", ["", "bird", "mammal"])
def test_post_accepts_optional_category_values(
    review_server: tuple[ThreadingHTTPServer, str, Path], expected_category: str
) -> None:
    _, url, csv_path = review_server
    response = urlopen(
        url,
        data=urlencode(
            {
                "i": "0",
                "animal_type": "great_tit",
                "lighting": "day",
                "expected_category": expected_category,
                "action": "next",
            }
        ).encode("utf-8"),
    )

    assert response.status == 200
    with csv_path.open(newline="", encoding="utf-8") as handle:
        saved_row = next(csv.DictReader(handle))
    assert saved_row["expected_category"] == expected_category


def test_post_rejects_invalid_category(
    review_server: tuple[ThreadingHTTPServer, str, Path],
) -> None:
    _, url, _ = review_server
    with pytest.raises(HTTPError) as error:
        urlopen(
            url,
            data=urlencode(
                {
                    "i": "0",
                    "animal_type": "unusable",
                    "lighting": "day",
                    "expected_category": "reptile",
                }
            ).encode("utf-8"),
        )
    assert error.value.code == 400


def test_review_page_shows_labels_blindly_on_loopback(
    review_server: tuple[ThreadingHTTPServer, str, Path],
) -> None:
    server, url, _ = review_server
    page = urlopen(url).read().decode("utf-8")

    assert server.server_address[0] == "127.0.0.1"
    assert 'value="out_of_list"' in page
    assert 'value="unidentifiable"' in page
    assert 'value="unusable"' in page
    assert 'name="expected_category"' in page
    assert 'value="bird"' in page
    assert 'value="mammal"' in page
    assert "prediction" not in page.lower()
    assert "score" not in page.lower()
