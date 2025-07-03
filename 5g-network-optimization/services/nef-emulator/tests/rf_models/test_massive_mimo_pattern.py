import math

from antenna_models.patterns import MassiveMIMOPattern


def test_massive_mimo_gain_is_finite():
    pattern = MassiveMIMOPattern()
    pattern.set_steering_direction(30, 15)

    angles = [
        (0, 0),
        (45, 0),
        (90, 0),
        (30, 15),
        (60, -15),
    ]

    for az, el in angles:
        gain = pattern.calculate_gain(az, el)
        assert math.isfinite(gain), f"gain not finite for az={az}, el={el}"
