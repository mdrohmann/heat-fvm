import math

from api.simulate import available_climates, simulate_from_request


def _sample_payload(**overrides) -> dict:
    payload = {
        "room": {
            "widthM": 4.0,
            "heightM": 3.0,
            "walls": {
                "north": [],
                "south": [{"type": "door", "offsetM": 1.0, "lengthM": 1.0}],
                "east": [{"type": "window", "offsetM": 0.5, "lengthM": 1.2}],
                "west": [],
            },
        },
        "heatSource": {"xM": 2.0, "yM": 1.5, "maxPowerW": 600.0},
        "climateId": "berlin",
        "viewMonthIndex": 0,
        "thermostat": {
            "dayTargetC": 20.5,
            "nightTargetC": 17.0,
            "dayStartHour": 6.0,
            "nightStartHour": 22.0,
        },
    }
    payload.update(overrides)
    return payload


def _fast(payload: dict) -> dict:
    return simulate_from_request(
        payload, view_nx=8, view_ny=6, linearization_nx=6, linearization_ny=5
    )


def test_simulate_from_request_end_to_end():
    result = _fast(_sample_payload())

    assert result["grid"] == {"nx": 8, "ny": 6}

    view_day = result["viewDay"]
    assert view_day["monthIndex"] == 0
    assert view_day["monthName"] == "January"
    assert view_day["frames"], "expected at least one animation frame"
    first_frame = view_day["frames"][0]
    assert len(first_frame["temperatureC"]) == 8 * 6
    assert all(math.isfinite(t) for t in first_frame["temperatureC"])

    annual = result["annual"]
    assert len(annual["monthlyKWh"]) == 12
    assert len(annual["dailyKWh"]) == 365
    assert annual["totalKWh"] > 0
    # Northern-hemisphere heating demand peaks in winter.
    assert annual["monthlyKWh"][0] > annual["monthlyKWh"][6]

    assert result["climate"]["id"] == "berlin"
    assert result["validation"], "expected baked ROM validation for this climate"
    assert result["climateDataMeta"]["source"]


def test_annual_result_is_independent_of_the_month_being_viewed():
    # The linearisation day is a property of the climate, not of the UI state, so
    # browsing to a different month must not move the annual energy number.
    january = _fast(_sample_payload(viewMonthIndex=0))
    july = _fast(_sample_payload(viewMonthIndex=6))

    assert january["annual"]["totalKWh"] == july["annual"]["totalKWh"]
    assert january["viewDay"]["dayOfYear"] != july["viewDay"]["dayOfYear"]
    # ...but the day actually shown does change, and January should be colder.
    assert january["viewDay"]["meanOutdoorTempC"] < july["viewDay"]["meanOutdoorTempC"]


def test_simulate_from_request_rejects_bad_input():
    for payload, expected in [
        (_sample_payload(climateId="atlantis"), "unknown climate location"),
        (_sample_payload(viewMonthIndex=12), "viewMonthIndex"),
    ]:
        try:
            _fast(payload)
            assert False, f"expected a ValueError mentioning {expected!r}"
        except ValueError as exc:
            assert expected in str(exc)


def test_simulate_from_request_rejects_wall_element_past_wall_end():
    payload = _sample_payload()
    payload["room"]["walls"]["south"] = [{"type": "door", "offsetM": 3.5, "lengthM": 1.0}]

    try:
        _fast(payload)
        assert False, "expected a ValueError for an out-of-bounds wall element"
    except ValueError as exc:
        assert "past wall end" in str(exc)


def test_available_climates_are_exposed_for_the_ui():
    climates = available_climates()
    assert climates
    assert {"id", "label"} <= set(climates[0])
    assert any(c["id"] == "berlin" for c in climates)
