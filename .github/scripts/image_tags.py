"""The tags the images of a release get (`.github/workflows/release.yml`).

    python3 .github/scripts/image_tags.py v0.6.0 < released.txt

The tags of the published releases come one per line on stdin (the release itself among them).
Writes `version=…` and `tags=…` (space-separated) for `$GITHUB_OUTPUT`.

Every release gets its version without the `v` (`0.6.0`). A beta is a version below 1.0 or one
with a pre-release after Semver (`1.2.0-beta.1`); it gets `beta`, a stable release `stable`.
`latest` follows the newest stable release, and the newest beta while there is none. A channel
tag only moves forward: an older release built again takes no tag from a newer one.
"""

import re
import sys
from collections.abc import Iterable

# Semver without build metadata: a `+` is not allowed in a Docker tag.
_VERSION = re.compile(
    r"v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)


class Version:
    """A Semver version, ordered by Semver's precedence."""

    def __init__(self, tag: str) -> None:
        found = _VERSION.fullmatch(tag.strip())
        if found is None:
            raise ValueError(f"not a release tag after Semver: {tag!r}")
        self.text = tag.strip().removeprefix("v")
        self.core = (int(found["major"]), int(found["minor"]), int(found["patch"]))
        self.pre = tuple(found["pre"].split(".")) if found["pre"] else ()

    @property
    def beta(self) -> bool:
        return self.core[0] == 0 or bool(self.pre)

    def _key(self) -> tuple[tuple[int, int, int], int, tuple[tuple[int, int, str], ...]]:
        # A version without a pre-release ranks above its pre-releases; numeric identifiers
        # rank below alphanumeric ones and compare as numbers.
        identifiers = tuple(
            (0, int(part), "") if part.isdigit() else (1, 0, part) for part in self.pre
        )
        return self.core, 0 if self.pre else 1, identifiers

    def __lt__(self, other: "Version") -> bool:
        return self._key() < other._key()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Version) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())


def image_tags(tag: str, released: Iterable[str]) -> list[str]:
    """The tags for the release `tag`, given the tags of all published releases."""
    version = Version(tag)
    known = {version}
    for line in released:
        if line.strip():
            try:
                known.add(Version(line))
            except ValueError:
                continue  # a tag of another scheme takes part in no channel
    betas = [each for each in known if each.beta]
    stables = [each for each in known if not each.beta]
    tags = [version.text]
    if version == max(betas if version.beta else stables):
        tags.append("beta" if version.beta else "stable")
    if version == max(stables or betas):
        tags.append("latest")
    return tags


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    tags = image_tags(sys.argv[1], sys.stdin)
    print(f"version={tags[0]}")
    print(f"tags={' '.join(tags)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
