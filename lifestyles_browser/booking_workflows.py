import datetime as dt
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from .booking import (
    ResourceLocation,
    build_booking_window,
    book_slot,
    fetch_slots,
    get_resource_locations,
    login_session,
    plan_shared_slot,
    slot_key,
    today_in_london,
)

BADMINTON_ACTIVITY_ID = 254


def _normalise_profiles(profiles: Sequence[str]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for profile in profiles:
        name = profile.strip().lower()
        if not name:
            continue
        if name in seen:
            continue
        cleaned.append(name)
        seen.add(name)
    if not cleaned:
        raise ValueError("At least one profile is required.")
    return cleaned


def _normalise_locations(locations: Sequence[int]) -> List[int]:
    cleaned: List[int] = []
    seen = set()
    for location in locations:
        if location in seen:
            continue
        cleaned.append(int(location))
        seen.add(location)
    if not cleaned:
        raise ValueError("At least one location is required.")
    return cleaned


def _prioritise_locations_for_week(target_date: dt.date, locations: Sequence[int]) -> List[int]:
    ordered = list(locations)
    if target_date.isocalendar().week % 2 == 0:
        return ordered
    return list(reversed(ordered))


def _rotate_profiles_for_week(target_date: dt.date, profiles: Sequence[str]) -> List[str]:
    ordered = list(profiles)
    if len(ordered) <= 1:
        return ordered
    rotation = target_date.isocalendar().week % len(ordered)
    return ordered[rotation:] + ordered[:rotation]


def _pick_unused_resource(
    resources: Sequence[ResourceLocation],
    used_resource_ids: Sequence[int],
) -> Optional[ResourceLocation]:
    used = set(used_resource_ids)
    for resource in resources:
        resource_id = resource.get("id")
        if resource_id is None:
            return resource
        if resource_id not in used:
            return resource
    return None


def plan_group_booking(
    *,
    slots: Sequence[Dict[str, Any]],
    profiles: Sequence[str],
    locations: Sequence[int],
    target_date: dt.date,
    window_start: str,
    window_end: str,
    activity_id: int = BADMINTON_ACTIVITY_ID,
    capacity_overrides: Optional[Dict[Tuple[Any, Any, Any], int]] = None,
) -> Dict[str, Any]:
    cleaned_profiles = _normalise_profiles(profiles)
    cleaned_locations = _normalise_locations(locations)
    location_priority = _prioritise_locations_for_week(target_date, cleaned_locations)
    window = build_booking_window(target_date, window_start, window_end)

    slot_plan = plan_shared_slot(
        slots,
        activity_id=activity_id,
        window=window,
        location_priority=location_priority,
        max_requested_slots=len(cleaned_profiles),
        capacity_overrides=capacity_overrides,
    )
    if slot_plan is None:
        return {
            "bookable": False,
            "reason": "No shared availability in window",
            "requested_profiles": cleaned_profiles,
            "requested_courts": len(cleaned_profiles),
            "location_priority": location_priority,
            "window_start": window_start,
            "window_end": window_end,
            "target_date": target_date.isoformat(),
        }

    rotated_profiles = _rotate_profiles_for_week(target_date, cleaned_profiles)
    selected_profiles = rotated_profiles[: slot_plan["planned_courts"]]
    slot = slot_plan["slot"]

    return {
        "bookable": True,
        "requested_profiles": cleaned_profiles,
        "selected_profiles": selected_profiles,
        "requested_courts": len(cleaned_profiles),
        "planned_courts": slot_plan["planned_courts"],
        "available_slots": slot_plan["available_slots"],
        "location_priority": location_priority,
        "window_start": window_start,
        "window_end": window_end,
        "target_date": target_date.isoformat(),
        "slot": slot,
        "location_id": slot.get("LocationId"),
        "location_name": slot.get("LocationName"),
        "start_time": slot.get("StartTime"),
    }


def badminton_club_booking(
    *,
    profiles: Sequence[str],
    locations: Sequence[int],
    window_start: str,
    window_end: str,
    days_ahead: int = 7,
    dry_run: bool = False,
    activity_id: int = BADMINTON_ACTIVITY_ID,
) -> Dict[str, Any]:
    cleaned_profiles = _normalise_profiles(profiles)
    cleaned_locations = _normalise_locations(locations)
    target_date = today_in_london() + dt.timedelta(days=days_ahead)
    location_priority = _prioritise_locations_for_week(target_date, cleaned_locations)
    window = build_booking_window(target_date, window_start, window_end)

    print(
        f"[workflow] activity_id={activity_id} target_date={target_date.isoformat()} "
        f"requested_profiles={cleaned_profiles} location_priority={location_priority} "
        f"window={window_start}-{window_end}"
    )

    try:
        discovery_client = login_session(profile=cleaned_profiles[0])
        slots = fetch_slots(
            discovery_client,
            target_date,
            days=window.days,
            activity_id=activity_id,
            location_ids=location_priority,
        )
    except requests.RequestException as exc:
        print(
            f"[workflow] discovery failed profile={cleaned_profiles[0]} "
            f"error={exc.__class__.__name__}: {exc}"
        )
        return {
            "bookable": False,
            "reason": "Availability lookup failed",
            "error": str(exc),
            "requested_profiles": cleaned_profiles,
            "requested_courts": len(cleaned_profiles),
            "location_priority": location_priority,
            "window_start": window_start,
            "window_end": window_end,
            "target_date": target_date.isoformat(),
            "dry_run": dry_run,
            "booked_courts": 0,
            "all_planned_booked": False,
            "all_requested_booked": False,
            "bookings": [],
        }

    capacity_overrides: Dict[Tuple[Any, Any, Any], int] = {}
    while True:
        plan = plan_group_booking(
            slots=slots,
            profiles=cleaned_profiles,
            locations=cleaned_locations,
            target_date=target_date,
            window_start=window_start,
            window_end=window_end,
            activity_id=activity_id,
            capacity_overrides=capacity_overrides,
        )
        if not plan["bookable"]:
            print("[workflow] no shared slot found for the requested window.")
            return {
                **plan,
                "dry_run": dry_run,
                "booked_courts": 0,
                "all_planned_booked": False,
                "all_requested_booked": False,
                "bookings": [],
            }

        slot = plan["slot"]
        if not slot.get("ResourceLocationSelectionEnabled"):
            break

        try:
            resources = get_resource_locations(discovery_client, slot)
        except requests.RequestException as exc:
            print(
                f"[workflow] resource lookup failed during planning "
                f"slot_id={slot['SlotId']} error={exc.__class__.__name__}: {exc}"
            )
            return {
                **plan,
                "dry_run": dry_run,
                "booked_courts": 0,
                "all_planned_booked": False,
                "all_requested_booked": False,
                "bookings": [],
                "reason": "Resource lookup failed during planning",
                "error": str(exc),
            }
        actual_capacity = len(resources)
        if actual_capacity >= plan["planned_courts"]:
            break

        capacity_overrides[slot_key(slot)] = actual_capacity
        print(
            f"[workflow] slot_id={slot['SlotId']} resource_capacity={actual_capacity} "
            f"is below planned_courts={plan['planned_courts']}; replanning."
        )

    print(
        f"[workflow] selected location={plan['location_name']} "
        f"location_id={plan['location_id']} start_time={plan['start_time']} "
        f"planned_courts={plan['planned_courts']}/{plan['requested_courts']}"
    )

    if dry_run:
        return {
            **plan,
            "dry_run": True,
            "booked_courts": 0,
            "all_planned_booked": False,
            "all_requested_booked": False,
            "bookings": [],
        }

    bookings: List[Dict[str, Any]] = []
    used_resource_ids: List[int] = []
    slot = plan["slot"]

    for profile in plan["selected_profiles"]:
        try:
            client = login_session(profile=profile)
        except requests.RequestException as exc:
            print(
                f"[workflow] login failed profile={profile} "
                f"error={exc.__class__.__name__}: {exc}; stopping after partial progress."
            )
            bookings.append(
                {
                    "profile": profile,
                    "success": False,
                    "reason": "Login failed",
                    "error": str(exc),
                }
            )
            break

        resource: Optional[ResourceLocation] = None

        if slot.get("ResourceLocationSelectionEnabled"):
            try:
                resources = get_resource_locations(client, slot)
            except requests.RequestException as exc:
                print(
                    f"[workflow] resource lookup failed profile={profile} "
                    f"error={exc.__class__.__name__}: {exc}; stopping after partial progress."
                )
                bookings.append(
                    {
                        "profile": profile,
                        "success": False,
                        "reason": "Resource lookup failed",
                        "error": str(exc),
                    }
                )
                break
            resource = _pick_unused_resource(resources, used_resource_ids)
            if resource is None:
                print(
                    f"[workflow] profile={profile} could not find a distinct resource for "
                    f"slot_id={slot['SlotId']}."
                )
                bookings.append(
                    {
                        "profile": profile,
                        "success": False,
                        "reason": "No distinct resources remaining for slot",
                        "resource_options": resources,
                    }
                )
                break

        try:
            booking_result = book_slot(
                client,
                slot,
                resource_id=resource["id"] if resource else None,
                resource_name=resource["name"] if resource else None,
                dry_run=False,
            )
        except requests.HTTPError as exc:
            response = exc.response
            status_code = response.status_code if response is not None else None
            response_text = response.text if response is not None else None
            print(
                f"[workflow] booking failed profile={profile} status={status_code}; "
                f"stopping after partial progress."
            )
            bookings.append(
                {
                    "profile": profile,
                    "success": False,
                    "error": str(exc),
                    "status_code": status_code,
                    "response_text": response_text,
                    "resource": resource,
                }
            )
            break
        except requests.RequestException as exc:
            print(
                f"[workflow] booking failed profile={profile} error={exc.__class__.__name__}: {exc}; "
                f"stopping after partial progress."
            )
            bookings.append(
                {
                    "profile": profile,
                    "success": False,
                    "error": str(exc),
                    "resource": resource,
                }
            )
            break

        if resource:
            resource_id = resource.get("id")
            if resource_id is not None:
                used_resource_ids.append(resource_id)

        print(
            f"[workflow] booked profile={profile} location={plan['location_name']} "
            f"start_time={plan['start_time']} resource={resource['name'] if resource else 'auto'}"
        )
        bookings.append(
            {
                "profile": profile,
                "success": True,
                "resource": resource,
                "booking": booking_result,
            }
        )

    booked_courts = sum(1 for booking in bookings if booking.get("success"))
    return {
        **plan,
        "dry_run": False,
        "bookings": bookings,
        "booked_courts": booked_courts,
        "all_planned_booked": booked_courts == plan["planned_courts"],
        "all_requested_booked": booked_courts == plan["requested_courts"],
    }
