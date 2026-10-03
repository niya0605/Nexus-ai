"""UUIDv7 generation.

Every primary key in this system is a UUIDv7 (time-ordered), generated
application-side — per the PostgreSQL Database Design's Identifier
Strategy (Section 1): it preserves B-tree insert locality (unlike
UUIDv4) while staying non-enumerable, and needs no database round-trip
or extension to produce.

Implemented locally, with no new dependency, because Python's stdlib
`uuid` module doesn't gain `uuid.uuid7()` until 3.14 — this project's
floor is 3.12 (see backend/pyproject.toml). This is a standard,
straightforward implementation of the RFC 9562 layout: a 48-bit
millisecond timestamp, a 4-bit version, a 2-bit variant, and the
remaining 74 bits random.
"""

import os
import time
import uuid


def generate_uuid7() -> uuid.UUID:
    """Generate one UUIDv7 identifier."""
    unix_ts_ms = int(time.time() * 1000)
    rand = os.urandom(10)  # 80 bits of randomness; 74 are actually used below

    ts_bytes = unix_ts_ms.to_bytes(6, byteorder="big")

    uuid_bytes = bytearray(16)
    uuid_bytes[0:6] = ts_bytes
    uuid_bytes[6] = 0x70 | (rand[0] & 0x0F)  # version 7 (high nibble) + 4 bits rand_a
    uuid_bytes[7] = rand[1]  # remaining 8 bits rand_a (12 bits rand_a total)
    uuid_bytes[8] = 0x80 | (rand[2] & 0x3F)  # variant 10xxxxxx (high 2 bits) + 6 bits rand_b
    uuid_bytes[9:16] = rand[3:10]  # remaining 56 bits rand_b (62 bits rand_b total)

    return uuid.UUID(bytes=bytes(uuid_bytes))
