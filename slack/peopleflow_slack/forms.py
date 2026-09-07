from __future__ import annotations

import json
import math
from datetime import date


def _field_element(values: dict, name: str) -> dict | None:
    block = values.get(name) if isinstance(values, dict) else None
    if not isinstance(block, dict):
        return None
    if "value" in block:
        field = block["value"]
    elif len(block) == 1:
        # Dynamic inputs use request_field_changed; the block ID stays stable.
        field = next(iter(block.values()))
    else:
        return None
    return field if isinstance(field, dict) else None


def field_value(values: dict, name: str):
    field = _field_element(values, name)
    if field is None:
        return None
    if "selected_date" in field:
        return field["selected_date"]
    if "selected_option" in field:
        option = field["selected_option"]
        return option.get("value") if isinstance(option, dict) else None
    if "selected_options" in field:
        return bool(field["selected_options"])
    return field.get("value")


_FORM_DEFAULTS = {
    "start_date": None,
    "end_date": None,
    "comment": "",
    "expected_return_date": None,
    "expected_return_unknown": False,
    "time_away": "full_day",
    "partial_hours": None,
    "extended_or_recurring": False,
}
_SICK_FIELDS = (
    "expected_return_date",
    "expected_return_unknown",
    "time_away",
    "partial_hours",
    "extended_or_recurring",
)


def merge_request_form_state(
    values: dict, request_type: str, metadata: dict | str | None = None
) -> dict:
    """Merge view.state.values with private_metadata.state_values for rendering.

    The result is a UI draft, not an API payload. Its flat state_values stash
    must be copied into the next view's private_metadata by the renderer. Present
    fields replace the stash even when cleared; missing/temporarily hidden fields
    retain it. Raw notes and hours survive toggles without stripping or parsing.
    Use request_payload on submission to validate and omit ineffective values.

    Legacy metadata without a stash, and stashes containing Slack block shapes
    instead of flat values, are accepted. request_type is the caller's selected
    type; a stale type input or previous metadata cannot override it.
    """
    if request_type not in ("pto", "sick_leave"):
        raise ValueError("Only employee PTO and sick leave forms are supported.")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    metadata = metadata if isinstance(metadata, dict) else {}
    saved = metadata.get("state_values", {})
    saved = saved if isinstance(saved, dict) else {}
    state = dict(_FORM_DEFAULTS)
    for name in state:
        if name in saved:
            value = saved[name]
            if value is None or isinstance(value, (str, int, float, bool)):
                state[name] = value
            elif _field_element(saved, name) is not None:
                state[name] = field_value(saved, name)
        if _field_element(values, name) is not None:
            state[name] = field_value(values, name)
    draft = {
        "type": request_type,
        "start_date": state["start_date"],
        # Keep the PTO end date in the stash while showing a sick form. Passing
        # it as the sick draft's end_date would trigger a legacy return fallback.
        "end_date": state["end_date"] if request_type == "pto" else None,
        "comment": state["comment"],
        "details": {name: state[name] for name in _SICK_FIELDS},
        "state_values": state,
    }
    draft_id = metadata.get("draft_id")
    if isinstance(draft_id, str) and draft_id:
        draft["id"] = draft_id
    return draft


def request_payload(values: dict, request_type: str) -> tuple[dict, dict]:
    """Inline UX validation; the backend remains authoritative for every transition."""
    errors: dict[str, str] = {}
    start = field_value(values, "start_date")
    end = field_value(values, "end_date")
    note = field_value(values, "comment")
    comment = note.strip() if isinstance(note, str) else ""
    if note is not None and not isinstance(note, str):
        errors["comment"] = "Enter a text note."

    def valid_date(value, field, required=True):
        if not value and not required:
            return None
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            errors[field] = "Choose a valid date."
            return None

    parsed_start = valid_date(start, "start_date")
    details = {}
    if request_type == "pto":
        parsed_end = valid_date(end, "end_date")
        if parsed_start and parsed_end and parsed_end < parsed_start:
            errors["end_date"] = "The last day cannot be before the first day."
        if not comment:
            errors["comment"] = "Add a short planning or handoff note."
    elif request_type == "sick_leave":
        unknown = field_value(values, "expected_return_unknown") is True
        expected = field_value(values, "expected_return_date")
        away = (
            field_value(values, "time_away")
            if _field_element(values, "time_away") is not None
            else "full_day"
        )
        if away not in ("full_day", "partial_day"):
            errors["time_away"] = "Choose a full day or part of a day."
        parsed_return = (
            valid_date(expected, "expected_return_date", required=not unknown)
            if not unknown
            else None
        )
        if (
            parsed_start
            and parsed_return
            and (
                parsed_return < parsed_start
                or (away == "full_day" and parsed_return == parsed_start)
            )
        ):
            errors["expected_return_date"] = (
                "Choose a return after the first full day away."
                if away == "full_day"
                else "Expected return cannot be before the first day."
            )
        hours = None
        if away == "partial_day":
            try:
                entered_hours = field_value(values, "partial_hours")
                if isinstance(entered_hours, bool):
                    raise ValueError
                hours = float(entered_hours or "")
                if not math.isfinite(hours) or not 0 < hours <= 24:
                    raise ValueError
            except (TypeError, ValueError):
                hours = None
                errors["partial_hours"] = "Enter hours greater than 0 and no more than 24."
        details = {
            "expected_return_date": None if unknown else expected,
            "expected_return_unknown": unknown,
            "time_away": away,
            "partial_hours": hours,
            "extended_or_recurring": field_value(values, "extended_or_recurring") is True,
        }
        end = None  # The API derives the last day from expected return.
    else:
        errors["start_date"] = "This request type is not supported."
    return {
        "type": request_type,
        "start_date": start,
        "end_date": end,
        "comment": comment,
        "details": details,
    }, errors
