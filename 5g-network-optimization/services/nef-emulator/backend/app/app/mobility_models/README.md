# Mobility Models

This directory hosts lightweight mobility models used by the NEF emulator. Each model exposes `generate_trajectory(duration_seconds, time_step=1.0)` and returns a list of points in `(x, y, z)` coordinates with timestamps.

## Available classes

### `LinearMobilityModel`
Moves a UE from `start_position` to `end_position` at constant speed following 3GPP TR 38.901 §7.6.3.2.

### `LShapedMobilityModel`
Represents a 90‑degree turn. The path is formed by two linear segments: start → corner → end.

### `RandomWaypointModel`
Chooses random waypoints inside the given bounds, travels at a random speed between `v_min` and `v_max`, then pauses for `pause_time` before selecting the next waypoint.

### `ManhattanGridMobilityModel`
Simulates movement along orthogonal city blocks. The UE travels along X/Y axes on a grid and randomly turns left, right, or continues straight at intersections.

### `ReferencePointGroupMobilityModel`
Follows a moving group centre (itself driven by another mobility model). Each UE position is the group centre plus a random offset up to `d_max` metres.

### `RandomDirectionalMobilityModel`
Moves in a randomly chosen direction with constant speed, changing direction after exponentially distributed time intervals. The direction is reflected when hitting the area bounds.

### `UrbanGridMobilityModel`
A more flexible grid model parameterised by block `grid_size` and `turn_probability` at intersections.

## `nef_adapter.py`

The helper `nef_adapter.py` converts trajectories into NEF‑friendly JSON. `generate_nef_path_points(model_type, **kwargs)` builds the requested mobility class, calls `generate_trajectory`, and formats each point as:
```json
{
  "latitude": X,
  "longitude": Y,
  "description": "<model>_<index>"
}
```
`save_path_to_json(points, filename)` simply dumps this list to a file.

> **Tip:** Before running any tests, install the required Python dependencies (e.g. `pip install -r requirements.txt`). Some libraries are optional but tests may fail without them.
