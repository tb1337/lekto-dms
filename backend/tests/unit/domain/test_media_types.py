"""Reading an ICO's directory, which the logo fetcher and the normaliser both trust no further
than its limits."""

from papiq.core.domain.media_types import IconEntry, icon_entries


def directory(*entries: tuple[int, int, int, int]) -> bytes:
    head = b"\x00\x00\x01\x00" + len(entries).to_bytes(2, "little")
    return head + b"".join(
        bytes([width, height, 0, 0, 1, 0, 32, 0])
        + size.to_bytes(4, "little")
        + offset.to_bytes(4, "little")
        for width, height, size, offset in entries
    )


def test_the_pictures_an_icon_names() -> None:
    data = directory((16, 16, 100, 38), (0, 0, 2000, 138))
    assert icon_entries(data, 64) == [
        IconEntry(width=16, height=16, size=100, offset=38),
        IconEntry(width=256, height=256, size=2000, offset=138),  # 0 stands for 256
    ]


def test_an_icon_beyond_the_limit_or_cut_short_has_none() -> None:
    data = directory(*[(16, 16, 10, 0)] * 3)
    assert icon_entries(data, 2) is None
    assert icon_entries(data[:-1], 64) is None
    assert icon_entries(directory(), 64) is None
