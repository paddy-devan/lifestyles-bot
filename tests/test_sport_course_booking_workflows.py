import datetime as dt
import unittest
from unittest.mock import Mock, patch

from lifestyles_browser.booking import build_sport_course_search_payload
from lifestyles_browser.sport_course_booking_workflows import sport_course_availability


class SportCourseSearchPayloadTests(unittest.TestCase):
    def test_matches_har_tennis_search_payload(self) -> None:
        payload = build_sport_course_search_payload(name="tennis")

        self.assertEqual(
            payload,
            [
                ("Name", "tennis"),
                ("CategoryId", ""),
                ("StartFromDate", ""),
                ("StartBeforeDate", ""),
                ("InstructorId", ""),
                ("SeasonId", ""),
                ("SeasonTypeId", ""),
                ("LocationIdList", ""),
                ("AgeMonths", ""),
            ],
        )

    def test_formats_extended_filters_like_frontend(self) -> None:
        payload = build_sport_course_search_payload(
            name="tennis",
            category_id=11,
            start_from_date=dt.date(2026, 4, 27),
            start_before_date="2026-05-31T00:00:00+01:00",
            instructor_id=7,
            season_id=8,
            season_type_id=9,
            location_ids=[1, 2],
            age_months=216,
            start_hour=18,
            end_hour=20,
            days_of_week=[1, 3],
            languages=[23],
            page=1,
        )

        self.assertEqual(payload[7], ("LocationIdList", "1;2"))
        self.assertIn(("StartFromDate", "2026-04-27T00:00:00"), payload)
        self.assertIn(("StartBeforeDate", "2026-05-31T00:00:00+01:00"), payload)
        self.assertIn(("DaysOfWeek[]", 1), payload)
        self.assertIn(("DaysOfWeek[]", 3), payload)
        self.assertIn(("Languages[]", 23), payload)
        self.assertIn(("Page", 1), payload)


class SportCourseAvailabilityTests(unittest.TestCase):
    @patch("lifestyles_browser.sport_course_booking_workflows.search_sport_courses")
    @patch("lifestyles_browser.sport_course_booking_workflows.login_session")
    def test_wraps_raw_search_response_for_inspection(
        self,
        login_session: Mock,
        search_sport_courses: Mock,
    ) -> None:
        client = Mock(profile="default")
        login_session.return_value = client
        search_response = {
            "TotalResultsCount": 20,
            "Data": [
                {
                    "Id": 10936,
                    "Name": "Adult Tennis Coaching 3 8 Weeks",
                    "AvailableCapacity": 18,
                }
            ],
        }
        search_sport_courses.return_value = search_response

        with patch("builtins.print"):
            result = sport_course_availability(name="tennis")

        self.assertEqual(result["profile"], "default")
        self.assertEqual(result["search"]["name"], "tennis")
        self.assertEqual(result["total_results_count"], 20)
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["courses"], search_response["Data"])
        self.assertEqual(result["raw"], search_response)
        search_sport_courses.assert_called_once_with(
            client,
            name="tennis",
            category_id=None,
            start_from_date=None,
            start_before_date=None,
            instructor_id=None,
            season_id=None,
            season_type_id=None,
            location_ids=None,
            age_months=None,
            start_hour=None,
            end_hour=None,
            days_of_week=None,
            languages=None,
            page=None,
        )


if __name__ == "__main__":
    unittest.main()
