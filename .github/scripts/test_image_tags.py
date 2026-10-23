"""Tests of `image_tags.py`: `python3 -m unittest discover .github/scripts`."""

import unittest

from image_tags import Version, image_tags


class VersionTest(unittest.TestCase):
    def test_orders_by_semver(self) -> None:
        ordered = [
            "0.9.9",
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
            "1.0.1",
            "1.10.0",
        ]
        versions = [Version(each) for each in ordered]
        shuffled = versions[1::2] + versions[::2]
        self.assertEqual(sorted(shuffled), versions)

    def test_a_beta_is_below_one_or_a_pre_release(self) -> None:
        self.assertTrue(Version("v0.6.0").beta)
        self.assertTrue(Version("v1.2.0-beta.1").beta)
        self.assertFalse(Version("v1.0.0").beta)

    def test_refuses_what_is_not_semver(self) -> None:
        for tag in ("v1.2", "1.2.0.beta1", "v1.2.0+build.5", "latest", "v01.2.3"):
            with self.assertRaises(ValueError, msg=tag):
                Version(tag)


class ImageTagsTest(unittest.TestCase):
    def test_a_beta_without_a_stable_release_is_latest(self) -> None:
        released = ["v0.4.0", "v0.5.0", "v0.6.0"]
        self.assertEqual(image_tags("v0.6.0", released), ["0.6.0", "beta", "latest"])

    def test_a_stable_release_is_latest(self) -> None:
        released = ["v0.6.0", "v1.0.0"]
        self.assertEqual(image_tags("v1.0.0", released), ["1.0.0", "stable", "latest"])

    def test_a_beta_after_a_stable_release_is_not_latest(self) -> None:
        released = ["v1.0.0", "v1.1.0-beta.1"]
        self.assertEqual(image_tags("v1.1.0-beta.1", released), ["1.1.0-beta.1", "beta"])

    def test_an_older_release_built_again_takes_no_channel_tag(self) -> None:
        released = ["v0.6.0", "v0.6.1"]
        self.assertEqual(image_tags("v0.6.0", released), ["0.6.0"])
        released = ["v1.0.0", "v1.0.1", "v1.1.0-beta.1"]
        self.assertEqual(image_tags("v1.0.0", released), ["1.0.0"])

    def test_the_release_counts_even_when_the_list_misses_it(self) -> None:
        self.assertEqual(image_tags("v0.6.0", ["v0.5.0"]), ["0.6.0", "beta", "latest"])

    def test_tags_of_another_scheme_are_left_out(self) -> None:
        released = ["nightly", "v0.6.0", ""]
        self.assertEqual(image_tags("v0.6.0", released), ["0.6.0", "beta", "latest"])


if __name__ == "__main__":
    unittest.main()
