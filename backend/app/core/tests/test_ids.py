"""UUIDv7 primary keys must sort in creation order, even within one millisecond."""

import uuid
from unittest import mock

from app.utils import ids
from app.utils.ids import generate_uuid7


def test_ids_are_valid_uuid7() -> None:
    value = generate_uuid7()
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_ids_strictly_increase_within_the_same_millisecond() -> None:
    with mock.patch.object(ids.time, "time", return_value=1_800_000_000.0):
        batch = [generate_uuid7() for _ in range(5000)]
    assert batch == sorted(batch)
    assert len(set(batch)) == len(batch)


def test_ids_keep_increasing_if_the_clock_goes_backwards() -> None:
    first = generate_uuid7()
    with mock.patch.object(ids.time, "time", return_value=0.0):
        later = generate_uuid7()
    assert later > first
