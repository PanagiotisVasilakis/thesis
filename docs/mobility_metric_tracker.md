# MobilityMetricTracker Algorithm

`MobilityMetricTracker` incrementally computes the heading change rate and path curvature for a stream of coordinate samples. Instead of recomputing metrics from the full history of positions, each update only relies on the previous segment.

For every new position `(x, y)` the tracker:
1. Calculates the vector and length from the previous point.
2. Updates the total path length with this segment length.
3. If a valid previous heading exists, computes the angular difference to the new heading and accumulates the absolute change.
4. If a previous movement vector exists, derives the turning angle at the intermediate point and adds it to the running total.

The heading change rate is the cumulative absolute heading change divided by the number of valid changes. Path curvature is the total turning angle divided by the path length. Both metrics can therefore be read in constant time after each `update()` call.

This incremental approach matches the results of `compute_heading_change_rate` and `compute_path_curvature` while running in O(1) for each new sample.
