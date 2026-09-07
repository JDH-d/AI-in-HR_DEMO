"""Focused dynamic form-state tests; no Slack, backend, or filesystem state."""

from __future__ import annotations

import copy
import json

import pytest

from peopleflow_slack.forms import field_value, merge_request_form_state, request_payload

CURRENT = {
    "start_date": "2030-04-01",
    "end_date": "2030-04-03",
    "comment": "  Coverage with R&D <team>\n  Keep this spacing.  ",
    "expected_return_date": "2030-04-04",
    "expected_return_unknown": False,
    "time_away": "partial_day",
    "partial_hours": "3.50",
    "extended_or_recurring": True,
}
DATES = {"start_date", "end_date", "expected_return_date"}
FLAGS = {"expected_return_unknown", "extended_or_recurring"}


def input_values(fields, *, action_id="value"):
    values = {}
    for name, value in fields.items():
        if name in DATES:
            element = {"type": "datepicker", "selected_date": value}
        elif name in FLAGS:
            element = {
                "type": "checkboxes",
                "selected_options": [{"value": "true"}] if value else [],
            }
        elif name in {"time_away", "type"}:
            element = {
                "type": "static_select",
                "selected_option": {"value": value} if value is not None else None,
            }
        else:
            element = {"type": "plain_text_input", "value": value}
        values[name] = {action_id: element}
    return values


def metadata_for(draft):
    return {
        "request_type": draft["type"],
        "draft_id": draft.get("id"),
        "state_values": copy.deepcopy(draft["state_values"]),
    }


@pytest.mark.parametrize("action_id", ["value", "request_field_changed"])
@pytest.mark.parametrize(
    "name,value",
    [
        ("time_away", "partial_day"),
        ("time_away", None),
        ("expected_return_unknown", True),
        ("expected_return_unknown", False),
        ("expected_return_date", "2030-04-04"),
        ("expected_return_date", None),
        ("partial_hours", "3.50"),
        ("comment", "  raw note  "),
    ],
)
def test_field_value_accepts_old_and_dynamic_action_ids(action_id, name, value):
    assert field_value(input_values({name: value}, action_id=action_id), name) == value


def test_field_value_accepts_a_sole_element_but_never_guesses_between_elements():
    assert field_value({"note": {"future_action": {"value": "note"}}}, "note") == "note"
    assert (
        field_value({"note": {"first": {"value": "a"}, "second": {"value": "b"}}}, "note") is None
    )
    assert (
        field_value({"note": {"value": {"value": "old"}, "other": {"value": "new"}}}, "note")
        == "old"
    )


@pytest.mark.parametrize(
    "values", [None, {}, {"note": None}, {"note": {}}, {"note": {"value": None}}]
)
def test_missing_or_unusable_field_shape_returns_none(values):
    assert field_value(values, "note") is None


def test_merge_preserves_exact_input_and_draft_id_without_mutating_arguments():
    values = input_values(CURRENT)
    metadata = {"request_type": "sick_leave", "draft_id": "draft-existing"}
    original = copy.deepcopy((values, metadata))
    draft = merge_request_form_state(values, "sick_leave", metadata)
    assert draft["state_values"] == CURRENT
    assert draft["id"] == "draft-existing"
    assert draft["comment"] == CURRENT["comment"]
    assert draft["details"]["partial_hours"] == "3.50"
    assert draft["end_date"] is None
    assert (values, metadata) == original
    draft["state_values"]["comment"] = "new"
    assert (values, metadata) == original


def test_full_day_partial_day_toggles_restore_hidden_hours_and_other_edits():
    partial = merge_request_form_state(
        input_values(CURRENT), "sick_leave", {"draft_id": "draft-existing"}
    )
    full = merge_request_form_state(
        input_values({"time_away": "full_day"}, action_id="request_field_changed"),
        "sick_leave",
        metadata_for(partial),
    )
    assert full["details"]["time_away"] == "full_day"
    assert full["state_values"]["partial_hours"] == "3.50"
    restored = merge_request_form_state(
        input_values({"time_away": "partial_day"}, action_id="request_field_changed"),
        "sick_leave",
        metadata_for(full),
    )
    assert restored["state_values"] == CURRENT
    assert restored["id"] == "draft-existing"
    payload, errors = request_payload(input_values(restored["state_values"]), "sick_leave")
    assert not errors
    assert payload["details"]["partial_hours"] == 3.5
    assert payload["comment"] == CURRENT["comment"].strip()


def test_unknown_return_toggles_restore_date_from_json_private_metadata():
    known = merge_request_form_state(input_values(CURRENT), "sick_leave")
    unknown = merge_request_form_state(
        input_values({"expected_return_unknown": True}, action_id="request_field_changed"),
        "sick_leave",
        json.dumps(metadata_for(known)),
    )
    assert unknown["details"]["expected_return_unknown"] is True
    assert unknown["state_values"]["expected_return_date"] == CURRENT["expected_return_date"]
    restored = merge_request_form_state(
        input_values({"expected_return_unknown": False}, action_id="request_field_changed"),
        "sick_leave",
        json.dumps(metadata_for(unknown)),
    )
    assert restored["state_values"] == CURRENT


def test_type_round_trip_keeps_pto_end_date_note_and_sick_flags():
    pto = merge_request_form_state(input_values(CURRENT), "pto", {"draft_id": "draft-existing"})
    sick = merge_request_form_state({}, "sick_leave", metadata_for(pto))
    assert sick["type"] == "sick_leave"
    assert sick["end_date"] is None
    restored = merge_request_form_state({}, "pto", metadata_for(sick))
    assert restored == pto
    payload, errors = request_payload(input_values(restored["state_values"]), "pto")
    assert not errors
    assert payload["end_date"] == CURRENT["end_date"]
    assert payload["details"] == {}


def test_explicit_request_type_overrides_stale_type_selector_and_metadata():
    draft = merge_request_form_state(
        input_values({**CURRENT, "type": "pto"}),
        "sick_leave",
        {"request_type": "pto"},
    )
    assert draft["type"] == "sick_leave"
    assert "type" not in draft["state_values"]


@pytest.mark.parametrize(
    "name,cleared",
    [
        ("start_date", None),
        ("end_date", None),
        ("comment", ""),
        ("comment", None),
        ("expected_return_date", None),
        ("partial_hours", ""),
        ("partial_hours", None),
        ("expected_return_unknown", False),
        ("extended_or_recurring", False),
        ("time_away", None),
    ],
)
def test_explicit_clear_replaces_stash_but_missing_field_preserves_it(name, cleared):
    saved = {**CURRENT, "expected_return_unknown": True}
    metadata = {"state_values": saved}
    absent = merge_request_form_state({}, "sick_leave", metadata)
    cleared_draft = merge_request_form_state(
        input_values({name: cleared}, action_id="request_field_changed"),
        "sick_leave",
        metadata,
    )
    assert absent["state_values"][name] == saved[name]
    assert cleared_draft["state_values"][name] == cleared
    assert metadata["state_values"] == saved
    # A later toggle cannot resurrect an explicitly cleared value.
    assert (
        merge_request_form_state({}, "sick_leave", metadata_for(cleared_draft))["state_values"][
            name
        ]
        == cleared
    )


def test_cleared_return_date_is_not_replaced_by_legacy_pto_end_date():
    draft = merge_request_form_state(
        input_values({"expected_return_date": None}),
        "sick_leave",
        {"state_values": CURRENT},
    )
    assert draft["details"]["expected_return_date"] is None
    assert draft["end_date"] is None
    assert draft["state_values"]["end_date"] == CURRENT["end_date"]


def test_legacy_metadata_and_nested_slack_state_stashes_are_supported():
    old = merge_request_form_state(input_values(CURRENT), "sick_leave", {"draft_id": "d1"})
    restored = merge_request_form_state(
        {},
        "sick_leave",
        {
            "draft_id": "d1",
            "state_values": input_values(CURRENT),
        },
    )
    assert restored == old


@pytest.mark.parametrize("metadata", [None, {}, "{}", "not json", "[]", [], {"state_values": None}])
def test_absent_or_unusable_metadata_keeps_current_input_and_safe_defaults(metadata):
    draft = merge_request_form_state(input_values({"comment": "Note"}), "sick_leave", metadata)
    assert draft["comment"] == "Note"
    assert draft["details"]["time_away"] == "full_day"
    assert draft["details"]["expected_return_unknown"] is False
    assert "id" not in draft


def test_stash_is_limited_to_editable_fields():
    draft = merge_request_form_state(
        {},
        "pto",
        {
            "request_type": "pto",
            "token": "DO_NOT_COPY",
            "state_values": {
                **CURRENT,
                "token": "DO_NOT_COPY",
                "role": "manager",
                "id": "wrong-id",
            },
        },
    )
    assert draft["state_values"] == CURRENT
    assert "DO_NOT_COPY" not in json.dumps(draft)
    assert "id" not in draft


def test_hidden_hours_and_unknown_date_never_enter_effective_api_payload():
    visible = {**CURRENT, "time_away": "full_day", "expected_return_unknown": True}
    draft = merge_request_form_state(input_values(visible), "sick_leave")
    assert draft["state_values"]["partial_hours"] == "3.50"
    assert draft["state_values"]["expected_return_date"] == "2030-04-04"
    # Stale hidden controls may still be present in Slack state during an update.
    values = input_values(
        {**visible, "partial_hours": "NaN", "expected_return_date": "invalid"},
        action_id="request_field_changed",
    )
    payload, errors = request_payload(values, "sick_leave")
    assert not errors
    assert payload["details"]["partial_hours"] is None
    assert payload["details"]["expected_return_date"] is None
    assert payload["end_date"] is None
    assert "state_values" not in payload
    json.dumps(payload, allow_nan=False)


def test_pto_note_remains_required_after_clearing_and_type_toggles():
    cleared = merge_request_form_state(
        input_values({"comment": "  \n "}), "sick_leave", {"state_values": CURRENT}
    )
    pto = merge_request_form_state({}, "pto", metadata_for(cleared))
    assert pto["comment"] == "  \n "
    payload, errors = request_payload(input_values(pto["state_values"]), "pto")
    assert payload["comment"] == ""
    assert errors["comment"] == "Add a short planning or handoff note."


@pytest.mark.parametrize("away", [None, "", "unknown", "half_day"])
def test_explicit_invalid_time_away_is_a_field_error(away):
    payload, errors = request_payload(input_values({**CURRENT, "time_away": away}), "sick_leave")
    assert "time_away" in errors
    assert payload["details"]["partial_hours"] is None


def test_legacy_missing_time_away_still_defaults_to_full_day():
    legacy = {key: value for key, value in CURRENT.items() if key != "time_away"}
    payload, errors = request_payload(input_values(legacy), "sick_leave")
    assert not errors
    assert payload["details"]["time_away"] == "full_day"
    assert payload["details"]["partial_hours"] is None


@pytest.mark.parametrize("hours", [None, "", "NaN", "Infinity", "0", "25", True, {"wrong": 1}, [1]])
def test_partial_day_invalid_hours_are_reported_without_non_json_numbers(hours):
    payload, errors = request_payload(
        input_values({**CURRENT, "partial_hours": hours}), "sick_leave"
    )
    assert "partial_hours" in errors
    assert payload["details"]["partial_hours"] is None
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize("request_type", [None, "", "manager", []])
def test_invalid_request_type_has_predictable_error_contract(request_type):
    _, errors = request_payload(input_values(CURRENT), request_type)
    assert errors["start_date"] == "This request type is not supported."
    with pytest.raises(ValueError, match="Only employee PTO and sick leave"):
        merge_request_form_state(input_values(CURRENT), request_type)


def test_unknown_return_can_be_unchecked_but_then_requires_a_date():
    values = input_values(
        {**CURRENT, "expected_return_unknown": False, "expected_return_date": None},
        action_id="request_field_changed",
    )
    _, errors = request_payload(values, "sick_leave")
    assert "expected_return_date" in errors


def test_non_text_note_does_not_crash_validation():
    _, errors = request_payload(
        input_values({**CURRENT, "comment": {"wrong": "value"}}), "sick_leave"
    )
    assert errors["comment"] == "Enter a text note."
