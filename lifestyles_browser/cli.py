import argparse
import json

from .booking import find_and_book, list_activities, login_session
from .booking_workflows import badminton_club_booking
from .sport_course_booking_workflows import sport_course_availability


def main() -> None:
    parser = argparse.ArgumentParser(description="Find and book Lifestyles slots.")
    parser.add_argument("--badminton-club-booking", action="store_true")
    parser.add_argument("--list-activities", action="store_true")
    parser.add_argument("--sport-course-availability", action="store_true")
    parser.add_argument("--activity-id", type=int)
    parser.add_argument("--days-ahead", type=int, help="Days ahead from today")
    parser.add_argument("--window-start", type=str, help="HH:MM (24h)")
    parser.add_argument("--window-end", type=str, help="HH:MM (24h)")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--location-id", type=int, help="Single location id for the direct flow")
    parser.add_argument(
        "--location",
        type=int,
        action="append",
        default=[],
        help="Location id for badminton club workflow. Repeat for multiple locations.",
    )
    parser.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Profile name. Repeat for multiple profiles.",
    )
    parser.add_argument(
        "--course-name",
        type=str,
        default="tennis",
        help="Sport course name search term.",
    )
    parser.add_argument("--course-category-id", type=int)
    parser.add_argument("--course-start-from-date", type=str)
    parser.add_argument("--course-start-before-date", type=str)
    parser.add_argument("--course-instructor-id", type=int)
    parser.add_argument("--course-season-id", type=int)
    parser.add_argument("--course-season-type-id", type=int)
    parser.add_argument("--course-age-months", type=int)
    parser.add_argument("--course-start-hour", type=int)
    parser.add_argument("--course-end-hour", type=int)
    parser.add_argument("--course-day-of-week", type=int, action="append", default=[])
    parser.add_argument("--course-language", type=int, action="append", default=[])
    parser.add_argument("--course-location-id", type=int, action="append", default=[])
    parser.add_argument("--course-page", type=int)

    args = parser.parse_args()

    primary_profile = args.profile[0] if args.profile else None

    if args.list_activities:
        client = login_session(profile=primary_profile)
        activities = list_activities(client)
        print(json.dumps(activities, indent=2))
        return

    if args.badminton_club_booking:
        if not (args.window_start and args.window_end):
            raise SystemExit("Missing required arguments for badminton club booking.")
        if not args.profile:
            raise SystemExit("At least one --profile is required for badminton club booking.")
        if not args.location:
            raise SystemExit("At least one --location is required for badminton club booking.")

        result = badminton_club_booking(
            profiles=args.profile,
            locations=args.location,
            window_start=args.window_start,
            window_end=args.window_end,
            days_ahead=args.days_ahead or 7,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return

    if args.sport_course_availability:
        result = sport_course_availability(
            profile=primary_profile,
            name=args.course_name,
            category_id=args.course_category_id,
            start_from_date=args.course_start_from_date,
            start_before_date=args.course_start_before_date,
            instructor_id=args.course_instructor_id,
            season_id=args.course_season_id,
            season_type_id=args.course_season_type_id,
            location_ids=args.course_location_id or None,
            age_months=args.course_age_months,
            start_hour=args.course_start_hour,
            end_hour=args.course_end_hour,
            days_of_week=args.course_day_of_week or None,
            languages=args.course_language or None,
            page=args.course_page,
        )
        print(json.dumps(result, indent=2))
        return

    if not (
        args.activity_id
        and args.days_ahead is not None
        and args.window_start
        and args.window_end
    ):
        raise SystemExit("Missing required arguments for booking flow.")

    result = find_and_book(
        activity_id=args.activity_id,
        days_ahead=args.days_ahead,
        window_start=args.window_start,
        window_end=args.window_end,
        dry_run=args.dry_run,
        location_id=args.location_id,
        profile=primary_profile,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
