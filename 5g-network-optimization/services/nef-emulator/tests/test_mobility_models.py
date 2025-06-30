# services/nef-emulator/tests/test_mobility_models.py

import math
from datetime import datetime

from backend.app.app.mobility_models.models import (
    LinearMobilityModel,
    LShapedMobilityModel,
    RandomWaypointModel,
    ManhattanGridMobilityModel,
    ReferencePointGroupMobilityModel,
    RandomDirectionalMobilityModel,
    UrbanGridMobilityModel,
)

def test_linear_mobility():
    """Linear model should travel from start towards end at approximately constant speed."""
    start = (0, 0, 0)
    end = (1000, 500, 0)
    speed = 10.0  # m/s
    # Compute duration so that start->end at this speed takes roughly this long
    straight_dist = math.hypot(end[0]-start[0], end[1]-start[1])
    duration = straight_dist / speed
    model = LinearMobilityModel(
        ue_id="ue_linear",
        start_position=start,
        end_position=end,
        speed=speed,
        start_time=datetime(2025, 1, 1)
    )
    traj = model.generate_trajectory(duration, time_step=1.0)
    assert traj, "Trajectory should not be empty"
    # first point is exact start
    assert traj[0]['position'] == start

    # last point should be within one step's travel of the true end
    last_pos = traj[-1]['position']
    dist_to_end = math.hypot(last_pos[0]-end[0], last_pos[1]-end[1])
    # allow up to one time_step*speed tolerance
    assert dist_to_end <= speed + 1e-6, f"End point {last_pos} too far from {end}"

    # check approximate constant speed
    times = [p['timestamp'] for p in traj]
    dts = [(times[i+1]-times[i]).total_seconds() for i in range(len(times)-1)]
    poss = [p['position'] for p in traj]
    dists = [
        math.hypot(poss[i+1][0]-poss[i][0], poss[i+1][1]-poss[i][1])
        for i in range(len(poss)-1)
    ]
    speeds = [dist/dt for dist, dt in zip(dists, dts) if dt > 0]
    avg_speed = sum(speeds) / len(speeds)
    assert abs(avg_speed - speed) < 0.1, f"Average speed {avg_speed:.2f} deviates from {speed}"

def test_l_shaped_mobility():
    """L‑shaped model must pass near the corner point."""
    start = (0, 0, 0)
    corner = (200, 0, 0)
    end = (200, 300, 0)
    speed = 10.0
    # duration long enough for both legs
    leg1 = math.hypot(corner[0]-start[0], corner[1]-start[1]) / speed
    leg2 = math.hypot(end[0]-corner[0], end[1]-corner[1]) / speed
    duration = leg1 + leg2 + 1
    model = LShapedMobilityModel(
        ue_id="ue_lshape",
        start_position=start,
        corner_position=corner,
        end_position=end,
        speed=speed,
        start_time=datetime(2025, 1, 1)
    )
    traj = model.generate_trajectory(duration, time_step=1.0)
    assert traj, "Trajectory should not be empty"
    # check that corner is reached within one step tolerance
    distances = [
        math.hypot(p['position'][0]-corner[0], p['position'][1]-corner[1])
        for p in traj
    ]
    assert min(distances) <= speed + 1e-6, "Did not pass near corner"

def test_random_waypoint_mobility():
    """Random Waypoint stays within bounds and speeds in [v_min, v_max]."""
    bounds = ((0, 0, 0), (500, 500, 0))
    v_min, v_max = 1.0, 5.0
    pause = 2.0
    model = RandomWaypointModel(
        ue_id="ue_rwp",
        area_bounds=bounds,
        v_min=v_min,
        v_max=v_max,
        pause_time=pause,
        start_time=datetime(2025, 1, 1)
    )
    traj = model.generate_trajectory(60, time_step=1.0)
    assert traj, "Trajectory should not be empty"
    # positions in bounds
    for p in traj:
        x, y, _ = p['position']
        assert bounds[0][0] <= x <= bounds[1][0]
        assert bounds[0][1] <= y <= bounds[1][1]
    # speeds are either 0 (pause) or between v_min and v_max
    for p in traj:
        s = p['speed']
        assert (s == 0) or (v_min <= s <= v_max)

def test_manhattan_grid_mobility():
    """Manhattan grid moves along grid lines only."""
    # 5×5 blocks of length 100 m
    grid = (5, 5, 100)
    speed = 10.0
    model = ManhattanGridMobilityModel(
        ue_id="ue_manhattan",
        grid_size=grid,
        speed=speed,
        start_time=datetime(2025, 1, 1)
    )
    traj = model.generate_trajectory(100, time_step=1.0)
    assert traj, "Trajectory should not be empty"
    # each position should lie on a multiple of block length on at least one axis
    for p in traj:
        x, y, _ = p['position']
        on_x = abs(x % grid[2]) < 1e-6
        on_y = abs(y % grid[2]) < 1e-6
        assert on_x or on_y

def test_reference_point_group_mobility():
    """RPGM: each UE point within d_max of its group center."""
    center = LinearMobilityModel(
        ue_id="group_center",
        start_position=(0,0,0),
        end_position=(300,300,0),
        speed=10.0,
        start_time=datetime(2025,1,1)
    )
    # generate center trajectory
    dur = math.hypot(300, 300)/10.0 + 1
    center_traj = center.generate_trajectory(dur, time_step=1.0)
    d_max = 20.0
    model = ReferencePointGroupMobilityModel(
        ue_id="ue_group",
        group_center_model=center,
        d_max=d_max,
        start_time=datetime(2025,1,1)
    )
    traj = model.generate_trajectory(dur, time_step=1.0)
    assert len(traj) == len(center_traj)
    # check distances
    for p, c in zip(traj, center_traj):
        x, y, _ = p['position']
        cx, cy, _ = c['position']
        dist = math.hypot(x-cx, y-cy)
        assert dist <= d_max


def test_random_directional_mobility():
    """Random Directional model stays in bounds with consistent timing."""
    import random
    import numpy as np

    random.seed(0)
    np.random.seed(0)

    bounds = [(0, 100), (0, 100), (0, 0)]
    start = (50, 50, 0)
    speed = 5.0
    model = RandomDirectionalMobilityModel(
        ue_id="ue_random_dir",
        start_position=start,
        speed=speed,
        area_bounds=bounds,
        direction_change_mean=5.0,
        start_time=datetime(2025, 1, 1),
    )
    traj = model.generate_trajectory(30, time_step=1.0)
    assert traj

    # positions stay within bounds
    for p in traj:
        x, y, z = p["position"]
        assert bounds[0][0] <= x <= bounds[0][1]
        assert bounds[1][0] <= y <= bounds[1][1]
        assert z == 0

    # timestamps spaced by exactly the step
    times = [p["timestamp"] for p in traj]
    for t0, t1 in zip(times, times[1:]):
        assert abs((t1 - t0).total_seconds() - 1.0) < 1e-6

    # step distance should not exceed speed*time_step
    poss = [p["position"] for p in traj]
    for p0, p1 in zip(poss, poss[1:]):
        dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        assert dist <= speed * 1.0 + 1e-6

    # should have at least one direction change
    dirs = [p["direction"] for p in traj]
    assert len(set(dirs)) > 1


def test_urban_grid_mobility():
    """Urban grid obeys turning probability and grid alignment."""
    import random

    random.seed(1)

    grid = 20.0
    model = UrbanGridMobilityModel(
        ue_id="ue_urban",
        start_position=(10, 10, 0),
        speed=10.0,
        grid_size=grid,
        turn_probability=1.0,
        start_time=datetime(2025, 1, 1),
    )

    traj = model.generate_trajectory(20, time_step=1.0)
    assert traj

    # every position lies on a grid line on at least one axis
    for p in traj:
        x, y, _ = p["position"]
        on_x = abs(x % grid) < 1e-6
        on_y = abs(y % grid) < 1e-6
        assert on_x or on_y

    # timestamps spaced correctly and speed honored
    times = [p["timestamp"] for p in traj]
    poss = [p["position"] for p in traj]
    for (t0, t1), (p0, p1) in zip(zip(times, times[1:]), zip(poss, poss[1:])):
        dt = (t1 - t0).total_seconds()
        dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        assert abs(dt - 1.0) < 1e-6
        assert abs(dist - model.speed * dt) < 1e-6

    # With turn_probability=1.0 the model should change direction often.
    # Verify at least one change occurs when crossing an intersection.
    dirs = [p["direction"] for p in traj]
    changed = False
    for i in range(1, len(traj)):
        x_prev, y_prev, _ = traj[i-1]["position"]
        at_intersection = abs(x_prev % grid) < 0.1 and abs(y_prev % grid) < 0.1
        if at_intersection and dirs[i] != dirs[i-1]:
            changed = True
    assert changed, "Direction never changed at intersections despite probability=1"

