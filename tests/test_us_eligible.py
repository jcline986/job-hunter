import unittest

from hunter.normalize import us_eligible
from hunter.sources import himalayas_location


class UsEligibleTests(unittest.TestCase):
    def test_nigeria_only_location(self):
        self.assertFalse(us_eligible("Senior Data Engineer", "Nigeria only"))

    def test_remote_without_country_lock_is_kept(self):
        self.assertTrue(us_eligible("Senior Data Engineer", "Remote"))

    def test_company_bio_mentioning_nigeria_is_kept(self):
        self.assertTrue(
            us_eligible(
                "Senior Data Engineer",
                "Remote",
                "As Nigeria's largest merchant acquirer we power POS transactions.",
            )
        )

    def test_uk_and_cardiff_locations_drop(self):
        self.assertFalse(us_eligible("Principal Engineer", "UK"))
        self.assertFalse(us_eligible("Lead Analytics Engineer", "Cardiff"))

    def test_munich_umlaut_drops(self):
        self.assertFalse(us_eligible("Senior Data Engineer", "München"))

    def test_explicit_us_wins_over_other_regions(self):
        self.assertTrue(us_eligible("Senior Data Analyst", "LATAM, Canada, USA"))
        self.assertTrue(us_eligible("Senior Data Engineer", "United States only"))

    def test_country_only_in_description(self):
        self.assertFalse(
            us_eligible("Senior Data Engineer", "Remote", "This role is Nigeria only.")
        )

    def test_uk_work_authorization_drops(self):
        self.assertFalse(
            us_eligible(
                "Principal Engineer",
                "Remote",
                "Candidates must have the right to work in the UK.",
            )
        )

    def test_us_work_authorization_is_kept(self):
        self.assertTrue(
            us_eligible(
                "Senior Analytics Engineer",
                "Remote",
                "Must be authorized to work in the United States.",
            )
        )


class HimalayasLocationTests(unittest.TestCase):
    def test_empty_restrictions_are_worldwide(self):
        self.assertEqual(himalayas_location({"locationRestrictions": []}), "Remote")

    def test_single_country_becomes_only_badge(self):
        self.assertEqual(
            himalayas_location({"locationRestrictions": ["Nigeria"]}),
            "Nigeria only",
        )

    def test_object_restrictions(self):
        self.assertEqual(
            himalayas_location(
                {"locationRestrictions": [{"alpha2": "NG", "name": "Nigeria", "slug": "nigeria"}]}
            ),
            "Nigeria only",
        )


if __name__ == "__main__":
    unittest.main()
