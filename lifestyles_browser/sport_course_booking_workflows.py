import datetime as dt
from typing import Any, Dict, Optional, Sequence, Union

import requests

from .booking import DateFilter, JsonDict, login_session, search_sport_courses


def _course_count(response: JsonDict) -> int:
    courses = response.get("Data")
    if isinstance(courses, list):
        return len(courses)
    return 0


def _json_safe(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return value


def sport_course_availability(
    *,
    profile: Optional[str] = None,
    name: Optional[str] = "tennis",
    category_id: Optional[int] = None,
    start_from_date: Optional[DateFilter] = None,
    start_before_date: Optional[DateFilter] = None,
    instructor_id: Optional[int] = None,
    season_id: Optional[int] = None,
    season_type_id: Optional[int] = None,
    location_ids: Optional[Union[str, Sequence[int]]] = None,
    age_months: Optional[int] = None,
    start_hour: Optional[int] = None,
    end_hour: Optional[int] = None,
    days_of_week: Optional[Sequence[int]] = None,
    languages: Optional[Sequence[int]] = None,
    page: Optional[int] = None,
) -> Dict[str, Any]:
    print(
        f"[workflow] sport_course_search name={name!r} category_id={category_id} "
        f"location_ids={location_ids} page={page}"
    )

    client = login_session(profile=profile)
    response = search_sport_courses(
        client,
        name=name,
        category_id=category_id,
        start_from_date=start_from_date,
        start_before_date=start_before_date,
        instructor_id=instructor_id,
        season_id=season_id,
        season_type_id=season_type_id,
        location_ids=location_ids,
        age_months=age_months,
        start_hour=start_hour,
        end_hour=end_hour,
        days_of_week=days_of_week,
        languages=languages,
        page=page,
    )

    return {
        "profile": client.profile,
        "search": {
            "name": _json_safe(name),
            "category_id": _json_safe(category_id),
            "start_from_date": _json_safe(start_from_date),
            "start_before_date": _json_safe(start_before_date),
            "instructor_id": _json_safe(instructor_id),
            "season_id": _json_safe(season_id),
            "season_type_id": _json_safe(season_type_id),
            "location_ids": _json_safe(location_ids),
            "age_months": _json_safe(age_months),
            "start_hour": _json_safe(start_hour),
            "end_hour": _json_safe(end_hour),
            "days_of_week": _json_safe(days_of_week),
            "languages": _json_safe(languages),
            "page": _json_safe(page),
        },
        "total_results_count": response.get("TotalResultsCount"),
        "returned_count": _course_count(response),
        "courses": response.get("Data", []),
        "raw": response,
    }


def main():
    courses = sport_course_availability()["courses"]

    courses_filtered = [
        course for course in courses
        if "Adult Tennis Coaching 3" in course["Name"]
        and course["RemainingSessions"] > 0
        and course["AvailableCapacity"] > 0
    ]

    if len(courses_filtered) > 0:
        requests.post(
            "https://ntfy.sh/T6L6nmBfV7fZGpBi",
            data="spot on tennis course available 🎾",
            timeout=30,
        ).raise_for_status()


if __name__ == "__main__":
    main()
