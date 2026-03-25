import datetime as dt
import unittest

from lifestyles_browser.booking_workflows import plan_group_booking


def _make_slot(
    *,
    slot_id: int,
    location_id: int,
    start_time: str,
    available_slots: int,
    location_name: str,
) -> dict:
    return {
        "SlotId": slot_id,
        "FacilityId": location_id,
        "FacilityName": location_name,
        "LocationId": location_id,
        "LocationName": location_name,
        "ActivityId": 254,
        "AvailableSlots": available_slots,
        "StartTime": start_time,
        "ActivityName": "Badminton Hire",
        "ProductId": 503,
        "Duration": 60,
        "ResourceLocationSelectionEnabled": False,
    }


class PlanGroupBookingTests(unittest.TestCase):
    def test_prefers_full_group_over_earlier_subset(self) -> None:
        slots = [
            _make_slot(
                slot_id=1,
                location_id=144,
                location_name="Location A",
                start_time="2025-07-09T19:00:00",
                available_slots=1,
            ),
            _make_slot(
                slot_id=2,
                location_id=3,
                location_name="Location B",
                start_time="2025-07-09T20:00:00",
                available_slots=2,
            ),
        ]

        plan = plan_group_booking(
            slots=slots,
            profiles=["paddy", "hannah"],
            locations=[144, 3],
            target_date=dt.date(2025, 7, 9),
            window_start="19:00",
            window_end="21:00",
        )

        self.assertTrue(plan["bookable"])
        self.assertEqual(plan["planned_courts"], 2)
        self.assertEqual(plan["location_id"], 3)
        self.assertEqual(plan["start_time"], "2025-07-09T20:00:00")

    def test_uses_location_order_to_break_even_week_ties(self) -> None:
        slots = [
            _make_slot(
                slot_id=1,
                location_id=144,
                location_name="Location A",
                start_time="2025-07-10T19:00:00",
                available_slots=2,
            ),
            _make_slot(
                slot_id=2,
                location_id=3,
                location_name="Location B",
                start_time="2025-07-10T19:00:00",
                available_slots=2,
            ),
        ]

        plan = plan_group_booking(
            slots=slots,
            profiles=["paddy", "hannah"],
            locations=[144, 3],
            target_date=dt.date(2025, 7, 10),
            window_start="19:00",
            window_end="21:00",
        )

        self.assertTrue(plan["bookable"])
        self.assertEqual(plan["location_priority"], [144, 3])
        self.assertEqual(plan["location_id"], 144)

    def test_reverses_location_priority_on_odd_weeks(self) -> None:
        slots = [
            _make_slot(
                slot_id=1,
                location_id=144,
                location_name="Location A",
                start_time="2025-07-02T19:00:00",
                available_slots=2,
            ),
            _make_slot(
                slot_id=2,
                location_id=3,
                location_name="Location B",
                start_time="2025-07-02T19:00:00",
                available_slots=2,
            ),
        ]

        plan = plan_group_booking(
            slots=slots,
            profiles=["paddy", "hannah"],
            locations=[144, 3],
            target_date=dt.date(2025, 7, 2),
            window_start="19:00",
            window_end="21:00",
        )

        self.assertTrue(plan["bookable"])
        self.assertEqual(plan["location_priority"], [3, 144])
        self.assertEqual(plan["location_id"], 3)

    def test_falls_back_to_largest_available_subset(self) -> None:
        slots = [
            _make_slot(
                slot_id=1,
                location_id=144,
                location_name="Location A",
                start_time="2025-07-10T19:00:00",
                available_slots=1,
            ),
            _make_slot(
                slot_id=2,
                location_id=3,
                location_name="Location B",
                start_time="2025-07-10T20:00:00",
                available_slots=1,
            ),
        ]

        plan = plan_group_booking(
            slots=slots,
            profiles=["paddy", "hannah"],
            locations=[144, 3],
            target_date=dt.date(2025, 7, 10),
            window_start="19:00",
            window_end="21:00",
        )

        self.assertTrue(plan["bookable"])
        self.assertEqual(plan["planned_courts"], 1)
        self.assertEqual(plan["location_id"], 144)
        self.assertEqual(plan["start_time"], "2025-07-10T19:00:00")

    def test_subset_profile_selection_rotates_by_week(self) -> None:
        slots = [
            _make_slot(
                slot_id=1,
                location_id=3,
                location_name="Location B",
                start_time="2025-07-16T19:00:00",
                available_slots=1,
            ),
        ]

        plan = plan_group_booking(
            slots=slots,
            profiles=["paddy", "hannah"],
            locations=[3],
            target_date=dt.date(2025, 7, 16),
            window_start="19:00",
            window_end="21:00",
        )

        self.assertTrue(plan["bookable"])
        self.assertEqual(plan["planned_courts"], 1)
        self.assertEqual(plan["selected_profiles"], ["hannah"])


if __name__ == "__main__":
    unittest.main()
