from pathlib import Path

import pytest

from app.records.employee_photos import resolve_photo_path, store_employee_photo


def test_store_employee_photo_writes_file_and_relative_path(tmp_path):
    stored = store_employee_photo(
        tmp_path,
        "9001",
        filename="face.PNG",
        data=b"\x89PNG fake-bytes",
    )
    assert stored == "data/employee-photos/9001.png"
    on_disk = tmp_path / "data" / "employee-photos" / "9001.png"
    assert on_disk.read_bytes() == b"\x89PNG fake-bytes"
    assert resolve_photo_path(tmp_path, stored) == on_disk


def test_store_employee_photo_rejects_non_image(tmp_path):
    with pytest.raises(ValueError, match="JPG, PNG, or WebP"):
        store_employee_photo(tmp_path, "9001", filename="notes.pdf", data=b"pdf")


def test_store_employee_photo_rejects_too_large(tmp_path):
    with pytest.raises(ValueError, match="8 MB"):
        store_employee_photo(tmp_path, "9001", filename="big.jpg", data=b"x" * (8 * 1024 * 1024 + 1))
