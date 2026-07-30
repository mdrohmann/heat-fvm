import math

from api.simulate import simulate_from_request


def _sample_payload() -> dict:
    return {
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
        "heatSource": {"xM": 2.0, "yM": 1.5, "maxPowerW": 1500.0},
        "climate": {
            "id": "temperate_winter",
            "label": "Temperate winter",
            "meanOutdoorTempC": 2.0,
            "diurnalAmplitudeC": 5.0,
            "peakHour": 15.0,
        },
        "thermostat": {
            "dayTargetC": 20.5,
            "nightTargetC": 17.0,
            "dayStartHour": 6.0,
            "nightStartHour": 22.0,
        },
    }


def test_simulate_from_request_end_to_end():
    result = simulate_from_request(_sample_payload(), nx=8, ny=6)

    assert result["grid"]["nx"] == 8
    assert result["grid"]["ny"] == 6
    assert len(result["representativeDay"]) > 0

    first_frame = result["representativeDay"][0]
    assert "hour" in first_frame
    assert len(first_frame["temperatureC"]) == 8 * 6
    assert all(math.isfinite(t) for t in first_frame["temperatureC"])

    assert result["monthlyEnergyKWh"] > 0


def test_simulate_from_request_rejects_wall_element_past_wall_end():
    payload = _sample_payload()
    payload["room"]["walls"]["south"] = [{"type": "door", "offsetM": 3.5, "lengthM": 1.0}]

    try:
        simulate_from_request(payload, nx=6, ny=5)
        assert False, "expected a ValueError for an out-of-bounds wall element"
    except ValueError as exc:
        assert "past wall end" in str(exc)
