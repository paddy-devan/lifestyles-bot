import datetime as dt
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, TypedDict, Union
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://liverpoollifestyles.legendonlineservices.co.uk"
LOGIN_PATH = "/enterprise/account/login"
LOGIN_URL = f"{BASE_URL}{LOGIN_PATH}"
SPORT_COURSE_SEARCH_PATH = "/enterprise/sportscoursesearch"
SPORT_COURSE_CATEGORIES_PATH = "/Enterprise/category/"
SPORT_COURSE_LANGUAGES_PATH = "/enterprise/languages/retrieveavailablelanguages"
SPORT_COURSE_SEASON_TYPES_PATH = "/Enterprise/seasons/getallactiveseasontypes"
SPORT_COURSE_SEASONS_PATH = "/Enterprise/seasons/getseasons"
SPORT_COURSE_INSTRUCTORS_PATH = "/Enterprise/api/instructors"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RETRIES = 3
RETRYABLE_STATUSES = {500, 502, 503, 504}
LONDON_TZ = ZoneInfo("Europe/London")

JsonDict = Dict[str, Any]
DateFilter = Union[str, dt.date, dt.datetime]


class ResourceLocation(TypedDict):
    id: Optional[int]
    name: Optional[str]
    available_slots: Optional[int]
    raw: JsonDict


@dataclass(frozen=True)
class Credentials:
    profile: str
    email: str
    password: str


@dataclass(frozen=True)
class BookingWindow:
    start: dt.datetime
    end: dt.datetime
    days: int


def today_in_london() -> dt.date:
    return dt.datetime.now(LONDON_TZ).date()


def _ordinal(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _human_date(d: dt.date) -> str:
    return f"{d.strftime('%A')}, {d.strftime('%B')} {_ordinal(d.day)} {d.year}"


def _parse_dt(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.removesuffix("Z"))


def _format_sport_course_date(value: Optional[DateFilter]) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min).isoformat()
    return value


def _format_sport_course_location_ids(
    location_ids: Optional[Union[str, Sequence[int]]],
) -> str:
    if location_ids is None:
        return ""
    if isinstance(location_ids, str):
        return location_ids
    return ";".join(str(int(location_id)) for location_id in location_ids)


def _form_value(value: Any) -> Any:
    if value is None:
        return ""
    return value


def build_sport_course_search_payload(
    *,
    name: Optional[str] = None,
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
) -> List[Tuple[str, Any]]:
    payload: List[Tuple[str, Any]] = [
        ("Name", _form_value(name)),
        ("CategoryId", _form_value(category_id)),
        ("StartFromDate", _format_sport_course_date(start_from_date)),
        ("StartBeforeDate", _format_sport_course_date(start_before_date)),
        ("InstructorId", _form_value(instructor_id)),
        ("SeasonId", _form_value(season_id)),
        ("SeasonTypeId", _form_value(season_type_id)),
        ("LocationIdList", _format_sport_course_location_ids(location_ids)),
        ("AgeMonths", _form_value(age_months)),
    ]

    if start_hour is not None:
        payload.append(("StartHour", start_hour))
    if end_hour is not None:
        payload.append(("EndHour", end_hour))
    if days_of_week:
        payload.extend(("DaysOfWeek[]", day) for day in days_of_week)
    if languages:
        payload.extend(("Languages[]", language) for language in languages)
    if page is not None:
        payload.append(("Page", page))

    return payload


def build_booking_window(
    target_date: dt.date,
    window_start: str,
    window_end: str,
) -> BookingWindow:
    start_time = dt.time.fromisoformat(window_start)
    end_time = dt.time.fromisoformat(window_end)
    start_dt = dt.datetime.combine(target_date, start_time)

    if end_time <= start_time:
        end_dt = dt.datetime.combine(target_date + dt.timedelta(days=1), end_time)
        return BookingWindow(start=start_dt, end=end_dt, days=2)

    end_dt = dt.datetime.combine(target_date, end_time)
    return BookingWindow(start=start_dt, end=end_dt, days=1)


def slot_key(slot: JsonDict) -> Tuple[Any, Any, Any]:
    return (
        slot.get("SlotId"),
        slot.get("LocationId"),
        slot.get("StartTime"),
    )


def _normalise_profile_name(profile: Optional[str]) -> str:
    if not profile:
        return "default"
    return profile.strip().lower()


def resolve_credentials(
    profile: Optional[str] = None,
    *,
    email: Optional[str] = None,
    password: Optional[str] = None,
) -> Credentials:
    normalised_profile = _normalise_profile_name(profile)

    if email or password:
        if not email or not password:
            raise RuntimeError(
                "Both email and password are required when passing explicit credentials."
            )
        return Credentials(profile=normalised_profile, email=email, password=password)

    if profile:
        email_key = f"EMAIL_{profile.strip().upper()}"
        password_key = f"PASSWORD_{profile.strip().upper()}"
        profile_email = os.environ.get(email_key)
        profile_password = os.environ.get(password_key)
        if not profile_email or not profile_password:
            raise RuntimeError(
                f"Missing credentials for profile '{normalised_profile}'. "
                f"Expected environment variables {email_key} and {password_key}."
            )
        return Credentials(
            profile=normalised_profile,
            email=profile_email,
            password=profile_password,
        )

    default_email = os.environ.get("lifestyles_email")
    default_password = os.environ.get("lifestyles_password")
    if not default_email or not default_password:
        raise RuntimeError(
            "Missing lifestyles_email or lifestyles_password in environment."
        )
    return Credentials(
        profile=normalised_profile,
        email=default_email,
        password=default_password,
    )


def _truncate_for_log(text: str, limit: int = 4000) -> str:
    if not text:
        return "<empty>"
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [truncated {len(text) - limit} chars]"


class BookingClient:
    def __init__(
        self,
        credentials: Credentials,
        *,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = requests.Session()

    @property
    def profile(self) -> str:
        return self.credentials.profile

    def close(self) -> None:
        self.session.close()

    def _retry_delay(self, attempt: int) -> int:
        return min(2 ** (attempt - 1), 5)

    def request(
        self,
        method: str,
        path: str,
        *,
        action: str,
        retries: Optional[int] = None,
        retryable_statuses: Optional[Iterable[int]] = None,
        log_success_body: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        attempt_limit = max(1, retries or self.max_retries)
        retryable = set(retryable_statuses or RETRYABLE_STATUSES)

        for attempt in range(1, attempt_limit + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    timeout=self.timeout_seconds,
                    **kwargs,
                )
            except requests.RequestException as exc:
                print(
                    f"[http] profile={self.profile} action={action} method={method.upper()} "
                    f"attempt={attempt}/{attempt_limit} error={exc.__class__.__name__}: {exc}"
                )
                if attempt >= attempt_limit:
                    raise
                delay = self._retry_delay(attempt)
                print(
                    f"[http] profile={self.profile} action={action} "
                    f"retrying_after={delay}s"
                )
                time.sleep(delay)
                continue

            print(
                f"[http] profile={self.profile} action={action} method={method.upper()} "
                f"status={response.status_code} attempt={attempt}/{attempt_limit}"
            )

            if response.status_code >= 400 or log_success_body:
                print(
                    f"[http-body] profile={self.profile} action={action}\n"
                    f"{_truncate_for_log(response.text)}"
                )

            if response.status_code in retryable and attempt < attempt_limit:
                delay = self._retry_delay(attempt)
                print(
                    f"[http] profile={self.profile} action={action} status={response.status_code} "
                    f"retrying_after={delay}s"
                )
                time.sleep(delay)
                continue

            response.raise_for_status()
            return response

        raise RuntimeError(f"Request exhausted retries for action '{action}'.")

    def request_json(
        self,
        method: str,
        path: str,
        *,
        action: str,
        **kwargs: Any,
    ) -> Any:
        response = self.request(method, path, action=action, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Expected JSON response for action '{action}', got non-JSON payload."
            ) from exc

    def login(self) -> "BookingClient":
        login_page = self.request("GET", LOGIN_PATH, action="login_page")
        token_input = BeautifulSoup(login_page.text, "html.parser").find(
            "input",
            attrs={"name": "__RequestVerificationToken"},
        )
        if not isinstance(token_input, Tag):
            raise RuntimeError("Could not find login verification token.")
        token = token_input.get("value")
        if not token:
            raise RuntimeError("Could not find login verification token.")

        payload = {
            "Email": self.credentials.email,
            "Password": self.credentials.password,
            "__RequestVerificationToken": token,
        }
        response = self.request(
            "POST",
            LOGIN_PATH,
            action="login",
            data=payload,
            allow_redirects=True,
        )

        if (
            response.url.startswith(LOGIN_URL)
            and "__RequestVerificationToken" in response.text
        ):
            raise RuntimeError(f"Login appears to have failed for profile '{self.profile}'.")

        return self

    def list_activities(self) -> List[JsonDict]:
        locations = self.request_json(
            "GET",
            "/enterprise/filteredlocationhierarchy",
            action="filtered_location_hierarchy",
        )
        activities: List[JsonDict] = []

        for loc in locations[0]["Children"]:
            loc_id = loc["Id"]
            categories = self.request_json(
                "GET",
                f"/enterprise/Bookings/ActivitySubTypeCategories?LocationIds={loc_id}",
                action=f"activity_categories:{loc_id}",
            )
            for cat in categories:
                acts = self.request_json(
                    "GET",
                    "/enterprise/Bookings/ActivitySubTypes"
                    f"?ResourceSubTypeCategoryId={cat['ResourceSubTypeCategoryId']}"
                    f"&LocationIds={loc_id}",
                    action=f"activities:{loc_id}:{cat['ResourceSubTypeCategoryId']}",
                )
                for activity in acts:
                    activities.append(
                        {
                            "ActivityId": activity.get("ResourceSubTypeId"),
                            "ActivityName": activity.get("Name"),
                            "LocationId": loc_id,
                            "LocationName": loc.get("Name"),
                            "CategoryId": cat.get("ResourceSubTypeCategoryId"),
                            "CategoryName": cat.get("Name"),
                        }
                    )

        activities.sort(
            key=lambda item: (item["ActivityName"] or "", item["ActivityId"] or 0)
        )
        return activities

    def list_sport_course_categories(self) -> List[JsonDict]:
        return self.request_json(
            "GET",
            SPORT_COURSE_CATEGORIES_PATH,
            action="sport_course_categories",
        )

    def list_sport_course_languages(self) -> List[JsonDict]:
        return self.request_json(
            "GET",
            SPORT_COURSE_LANGUAGES_PATH,
            action="sport_course_languages",
        )

    def list_sport_course_season_types(self) -> List[JsonDict]:
        return self.request_json(
            "GET",
            SPORT_COURSE_SEASON_TYPES_PATH,
            action="sport_course_season_types",
        )

    def list_sport_course_seasons(self, season_type_id: int) -> List[JsonDict]:
        return self.request_json(
            "GET",
            SPORT_COURSE_SEASONS_PATH,
            action=f"sport_course_seasons:{season_type_id}",
            params={"seasonTypeId": season_type_id},
        )

    def list_sport_course_instructors(self, location_id: int) -> List[JsonDict]:
        return self.request_json(
            "GET",
            f"{SPORT_COURSE_INSTRUCTORS_PATH}/{location_id}",
            action=f"sport_course_instructors:{location_id}",
        )

    def search_sport_courses(
        self,
        *,
        name: Optional[str] = None,
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
    ) -> JsonDict:
        payload = build_sport_course_search_payload(
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
        return self.request_json(
            "POST",
            SPORT_COURSE_SEARCH_PATH,
            action="sport_course_search",
            data=payload,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    def fetch_slots(
        self,
        start_date: dt.date,
        *,
        days: int = 1,
        activity_id: Optional[int] = None,
        location_ids: Optional[Sequence[int]] = None,
    ) -> List[JsonDict]:
        start_dt = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end_dt = (start_date + dt.timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        requested_locations = set(location_ids or [])
        slots: List[JsonDict] = []

        locations = self.request_json(
            "GET",
            "/enterprise/filteredlocationhierarchy",
            action="filtered_location_hierarchy",
        )

        for loc in locations[0]["Children"]:
            location_id = loc["Id"]
            if requested_locations and location_id not in requested_locations:
                continue

            facility_ids = self.request_json(
                "GET",
                f"/enterprise/FacilityLocation?request={location_id}",
                action=f"facility_location:{location_id}",
            )
            if not facility_ids:
                continue
            booking_facility_id = facility_ids[0]

            categories = self.request_json(
                "GET",
                f"/enterprise/Bookings/ActivitySubTypeCategories?LocationIds={location_id}",
                action=f"activity_categories:{location_id}",
            )
            for cat in categories:
                activities = self.request_json(
                    "GET",
                    "/enterprise/Bookings/ActivitySubTypes"
                    f"?ResourceSubTypeCategoryId={cat['ResourceSubTypeCategoryId']}"
                    f"&LocationIds={location_id}",
                    action=f"activities:{location_id}:{cat['ResourceSubTypeCategoryId']}",
                )
                for activity in activities:
                    if (
                        activity_id is not None
                        and activity.get("ResourceSubTypeId") != activity_id
                    ):
                        continue

                    schedules = self.request_json(
                        "GET",
                        "/enterprise/BookingsCentre/SportsHallTimeTable"
                        f"?Activities={activity['ResourceSubTypeId']}"
                        f"&BookingFacilities={booking_facility_id}"
                        f"&Start={start_dt}"
                        f"&End={end_dt}",
                        action=f"timetable:{location_id}:{activity['ResourceSubTypeId']}",
                    )
                    snapshots = schedules.get("SportsHallActivitySnapshots") or []
                    if not snapshots:
                        continue
                    rows = snapshots[0].get("SportsHallTimetableRows") or []
                    for row in rows:
                        enriched_row = dict(row)
                        enriched_row["LocationId"] = location_id
                        enriched_row["LocationName"] = loc.get("Name")
                        enriched_row["BookingFacilityId"] = booking_facility_id
                        slots.append(enriched_row)

        return slots

    def get_resource_locations(self, slot: JsonDict) -> List[ResourceLocation]:
        payload = {
            "models": [
                {
                    "SlotId": slot["SlotId"],
                    "FacilityId": slot["FacilityId"],
                    "ActivityId": slot["ActivityId"],
                    "StartTime": slot["StartTime"].replace("T", " ").replace("Z", ""),
                    "Duration": slot["Duration"],
                }
            ]
        }
        data = self.request_json(
            "POST",
            "/enterprise/BookingsCentre/GetResourceLocation",
            action=f"resource_locations:{slot['SlotId']}",
            json=payload,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        return _extract_resource_locations(data)

    def book_slot(
        self,
        slot: JsonDict,
        *,
        resource_id: Optional[int],
        resource_name: Optional[str],
        dry_run: bool = True,
    ) -> JsonDict:
        params = _build_booking_params(
            slot,
            resource_id=resource_id,
            resource_name=resource_name,
        )

        if dry_run:
            return {
                "dry_run": True,
                "book_url": f"{BASE_URL}/enterprise/BookingsCentre/BookSportsHallSlot",
                "params": params,
            }

        book_response = self.request(
            "GET",
            "/enterprise/BookingsCentre/BookSportsHallSlot",
            action=f"book_slot:{slot['SlotId']}",
            params=params,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        basket_response = self.request(
            "PUT",
            "/enterprise/universalbasket/updatebasketexpiry",
            action="update_basket_expiry",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        confirm_response = self.request(
            "POST",
            "/enterprise/cart/confirmbasket",
            action="confirm_basket",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/json",
            },
            data=json.dumps({}),
        )
        return {
            "dry_run": False,
            "book_status": book_response.status_code,
            "book_response_text": book_response.text,
            "basket_status": basket_response.status_code,
            "confirm_status": confirm_response.status_code,
            "confirm_response_text": confirm_response.text,
        }


def _extract_resource_locations(resp_json: Any) -> List[ResourceLocation]:
    candidates: List[JsonDict] = []

    if isinstance(resp_json, list):
        candidates = resp_json
    elif isinstance(resp_json, dict):
        for key in ("ResourceLocations", "Resources", "Locations", "Data"):
            if isinstance(resp_json.get(key), list):
                candidates = resp_json[key]
                break

    resources: List[ResourceLocation] = []
    for candidate in candidates:
        available_slots = candidate.get("AvailableSlots")
        if available_slots is not None and available_slots <= 0:
            continue
        resource_id = (
            candidate.get("Id")
            or candidate.get("ResourceLocationId")
            or candidate.get("LocationId")
        )
        resource_name = (
            candidate.get("Name")
            or candidate.get("ResourceLocationName")
            or candidate.get("LocationName")
        )
        if resource_id is None and resource_name is None:
            continue
        resources.append(
            {
                "id": resource_id,
                "name": resource_name,
                "available_slots": available_slots,
                "raw": candidate,
            }
        )
    return resources


def _build_booking_params(
    slot: JsonDict,
    *,
    resource_id: Optional[int],
    resource_name: Optional[str],
) -> JsonDict:
    start_dt = _parse_dt(slot["StartTime"])
    params: Dict[str, Any] = {
        "ActivityId": slot["ActivityId"],
        "ActivityName": slot.get("ActivityName"),
        "ProductId": slot["ProductId"],
        "Date": _human_date(start_dt.date()),
        "StartTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "Time": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "MultiLocation": "false",
        "Duration": slot["Duration"],
        "FacilityId": slot["FacilityId"],
        "FacilityName": slot.get("FacilityName"),
        "AvailableSlots": slot.get("AvailableSlots", 1),
        "ResourceLocationSelectionEnabled": str(
            slot.get("ResourceLocationSelectionEnabled", False)
        ).lower(),
        "Locations[0][SlotId]": slot["SlotId"],
        "Locations[0][FacilityId]": slot["FacilityId"],
        "Locations[0][FacilityName]": slot.get("FacilityName"),
        "Locations[0][ActivityId]": slot["ActivityId"],
        "Locations[0][AvailableSlots]": slot.get("AvailableSlots", 1),
        "Locations[0][StartTime]": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "Locations[0][ActivityName]": slot.get("ActivityName"),
        "Locations[0][ProductId]": slot["ProductId"],
        "Locations[0][Duration]": slot["Duration"],
        "Locations[0][ResourceLocationSelectionEnabled]": str(
            slot.get("ResourceLocationSelectionEnabled", False)
        ).lower(),
        "AddedToBasket": "false",
        "Text": "1 Slots",
        "SlotId": slot["SlotId"],
    }

    if resource_id is not None:
        params["SelectedCourts"] = resource_id
    if resource_name is not None:
        params["ResourceLocation"] = resource_name

    return params


def filter_slots_in_window(
    slots: Sequence[JsonDict],
    *,
    activity_id: int,
    window: BookingWindow,
    location_ids: Optional[Sequence[int]] = None,
) -> List[JsonDict]:
    allowed_locations = set(location_ids or [])
    candidates: List[JsonDict] = []

    for slot in slots:
        if slot.get("ActivityId") != activity_id:
            continue
        if allowed_locations and slot.get("LocationId") not in allowed_locations:
            continue

        slot_dt = _parse_dt(slot["StartTime"])
        if window.start <= slot_dt <= window.end:
            candidates.append(slot)

    return candidates


def plan_shared_slot(
    slots: Sequence[JsonDict],
    *,
    activity_id: int,
    window: BookingWindow,
    location_priority: Sequence[int],
    max_requested_slots: int,
    capacity_overrides: Optional[Dict[Tuple[Any, Any, Any], int]] = None,
) -> Optional[JsonDict]:
    if max_requested_slots <= 0:
        return None

    location_rank = {location_id: index for index, location_id in enumerate(location_priority)}
    capacity_lookup = capacity_overrides or {}
    candidates = filter_slots_in_window(
        slots,
        activity_id=activity_id,
        window=window,
        location_ids=location_priority,
    )

    def available_capacity(slot: JsonDict) -> int:
        capacity = capacity_lookup.get(slot_key(slot), slot.get("AvailableSlots", 0) or 0)
        return int(capacity)

    def location_priority_rank(slot: JsonDict) -> int:
        location_id = slot.get("LocationId")
        if isinstance(location_id, int) and location_id in location_rank:
            return location_rank[location_id]
        return len(location_rank)

    for requested_slots in range(max_requested_slots, 0, -1):
        feasible = [
            slot
            for slot in candidates
            if available_capacity(slot) >= requested_slots
        ]
        if not feasible:
            continue

        feasible.sort(
            key=lambda slot: (
                _parse_dt(slot["StartTime"]),
                location_priority_rank(slot),
            )
        )
        chosen = feasible[0]
        return {
            "slot": chosen,
            "planned_courts": requested_slots,
            "available_slots": available_capacity(chosen),
        }

    return None


def login_session(
    profile: Optional[str] = None,
    *,
    email: Optional[str] = None,
    password: Optional[str] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> BookingClient:
    credentials = resolve_credentials(profile, email=email, password=password)
    return BookingClient(
        credentials,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    ).login()


def list_activities(client: BookingClient) -> List[JsonDict]:
    return client.list_activities()


def list_sport_course_categories(client: BookingClient) -> List[JsonDict]:
    return client.list_sport_course_categories()


def list_sport_course_languages(client: BookingClient) -> List[JsonDict]:
    return client.list_sport_course_languages()


def list_sport_course_season_types(client: BookingClient) -> List[JsonDict]:
    return client.list_sport_course_season_types()


def list_sport_course_seasons(
    client: BookingClient,
    season_type_id: int,
) -> List[JsonDict]:
    return client.list_sport_course_seasons(season_type_id)


def list_sport_course_instructors(
    client: BookingClient,
    location_id: int,
) -> List[JsonDict]:
    return client.list_sport_course_instructors(location_id)


def search_sport_courses(
    client: BookingClient,
    *,
    name: Optional[str] = None,
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
) -> JsonDict:
    return client.search_sport_courses(
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


def fetch_slots(
    client: BookingClient,
    start_date: dt.date,
    *,
    days: int = 1,
    activity_id: Optional[int] = None,
    location_id: Optional[int] = None,
    location_ids: Optional[Sequence[int]] = None,
) -> List[JsonDict]:
    requested_locations: Optional[List[int]]
    if location_ids is not None:
        requested_locations = list(location_ids)
    elif location_id is not None:
        requested_locations = [location_id]
    else:
        requested_locations = None

    return client.fetch_slots(
        start_date,
        days=days,
        activity_id=activity_id,
        location_ids=requested_locations,
    )


def get_resource_locations(
    client: BookingClient,
    slot: JsonDict,
) -> List[ResourceLocation]:
    return client.get_resource_locations(slot)


def get_resource_location(
    client: BookingClient,
    slot: JsonDict,
) -> Tuple[Optional[int], Optional[str], List[ResourceLocation]]:
    resources = client.get_resource_locations(slot)
    if not resources:
        return None, None, []
    first = resources[0]
    return first["id"], first["name"], resources


def book_slot(
    client: BookingClient,
    slot: JsonDict,
    resource_id: Optional[int],
    resource_name: Optional[str],
    dry_run: bool = True,
) -> JsonDict:
    return client.book_slot(
        slot,
        resource_id=resource_id,
        resource_name=resource_name,
        dry_run=dry_run,
    )


def find_and_book(
    activity_id: int,
    days_ahead: int,
    window_start: str,
    window_end: str,
    dry_run: bool = True,
    location_id: Optional[int] = None,
    profile: Optional[str] = None,
) -> JsonDict:
    client = login_session(profile=profile)

    target_date = today_in_london() + dt.timedelta(days=days_ahead)
    window = build_booking_window(target_date, window_start, window_end)
    slots = fetch_slots(
        client,
        target_date,
        days=window.days,
        activity_id=activity_id,
        location_id=location_id,
    )

    if location_id is not None:
        location_priority = [location_id]
    else:
        location_priority = list(
            dict.fromkeys(
                slot["LocationId"]
                for slot in slots
                if slot.get("LocationId") is not None
            )
        )

    slot_plan = plan_shared_slot(
        slots,
        activity_id=activity_id,
        window=window,
        location_priority=location_priority,
        max_requested_slots=1,
    )
    if slot_plan is None:
        return {
            "booked": False,
            "dry_run": dry_run,
            "reason": "No available slots in window",
            "target_date": target_date.isoformat(),
        }

    chosen = slot_plan["slot"]
    resource_id: Optional[int] = None
    resource_name: Optional[str] = None
    resource_raw: List[ResourceLocation] = []
    if chosen.get("ResourceLocationSelectionEnabled"):
        resource_id, resource_name, resource_raw = get_resource_location(client, chosen)
        if resource_id is None and resource_name is None:
            return {
                "booked": False,
                "dry_run": dry_run,
                "reason": (
                    "Slot required explicit resource selection but no resources were "
                    "returned."
                ),
                "slot": chosen,
                "target_date": target_date.isoformat(),
            }

    booking_result = book_slot(
        client,
        chosen,
        resource_id=resource_id,
        resource_name=resource_name,
        dry_run=dry_run,
    )

    return {
        "booked": not dry_run,
        "dry_run": dry_run,
        "slot": chosen,
        "resource": {"id": resource_id, "name": resource_name},
        "resource_raw": resource_raw,
        "booking": booking_result,
        "target_date": target_date.isoformat(),
        "profile": client.profile,
    }


if __name__ == "__main__":
    raise SystemExit(
        "This module provides booking logic. Use `python -m lifestyles_browser.cli`."
    )
