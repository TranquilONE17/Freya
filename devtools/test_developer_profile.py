"""Offline regression tests for the conservative developer permission profile."""
import unittest

from developer_profile import DEFAULT_PROFILE, DeveloperAction, DeveloperProfile


class DeveloperProfileTests(unittest.TestCase):
    def test_proposal_only(self):
        self.assertTrue(DEFAULT_PROFILE.allows(DeveloperAction.READ_SOURCE))
        self.assertTrue(DEFAULT_PROFILE.allows(DeveloperAction.PROPOSE_PATCH))

    def test_effects_disabled(self):
        for action in DeveloperAction:
            if action not in (DeveloperAction.READ_SOURCE, DeveloperAction.PROPOSE_PATCH):
                with self.subTest(action=action):
                    self.assertFalse(DEFAULT_PROFILE.allows(action))

    def test_unknown_action_denied(self):
        self.assertFalse(DEFAULT_PROFILE.allows("shell"))
        self.assertFalse(DEFAULT_PROFILE.allows(""))
        self.assertFalse(DEFAULT_PROFILE.allows("MERGE"))

    def test_immutable(self):
        with self.assertRaises(Exception):
            DEFAULT_PROFILE.name = "unsafe"

    def test_explicit_profile(self):
        profile = DeveloperProfile(permitted_actions=frozenset({DeveloperAction.READ_SOURCE}))
        self.assertFalse(profile.allows(DeveloperAction.PROPOSE_PATCH))


if __name__ == "__main__":
    unittest.main()
