import math
import numpy as np
import random
from datetime import datetime, timedelta

class MobilityModel:
    """Base class for all mobility models following 3GPP TR 38.901"""
    
    def __init__(self, ue_id, start_time=None, mobility_params=None):
        self.ue_id = ue_id
        self.start_time = start_time or datetime.now()
        self.mobility_params = mobility_params or {}
        self.current_position = None
        self.trajectory = []
    
    # def generate_trajectory(self, duration_seconds, time_step=1.0):
    #     """Generate trajectory points for the specified duration"""
    #     raise NotImplementedError("Subclasses must implement this method")
    
    # def get_position_at_time(self, query_time):
    #     """Return interpolated (x,y,z) at the given datetime."""
    #     # Ensure trajectory is sorted by timestamp
    #     traj = sorted(self.trajectory, key=lambda p: p['timestamp'])
    #     if not traj:
    #         return None

    #     # Before start or after end
    #     if query_time <= traj[0]['timestamp']:
    #         return traj[0]['position']
    #     if query_time >= traj[-1]['timestamp']:
    #         return traj[-1]['position']

    #     # Find bracketing points
    #     for i in range(len(traj)-1):
    #         p0, p1 = traj[i], traj[i+1]
    #         t0, t1 = p0['timestamp'], p1['timestamp']
    #         if t0 <= query_time <= t1:
    #             # Compute fraction between t0 and t1
    #             total = (t1 - t0).total_seconds()
    #             frac = (query_time - t0).total_seconds() / total if total > 0 else 0
    #             x0,y0,z0 = p0['position']
    #             x1,y1,z1 = p1['position']
    #             # Linear interpolation
    #             x = x0 + (x1 - x0)*frac
    #             y = y0 + (y1 - y0)*frac
    #             z = z0 + (z1 - z0)*frac
    #             return (x, y, z)

    #     # Fallback (shouldn't happen)
    #     return traj[-1]['position']


class LinearMobilityModel(MobilityModel):
    """Linear mobility model (3GPP TR 38.901 Section 7.6.3.2)"""
    
    def __init__(self, ue_id, start_position, end_position, speed, start_time=None):
        super().__init__(ue_id, start_time)
        self.start_position = start_position  # (x, y, z) in meters
        self.end_position = end_position  # (x, y, z) in meters
        self.speed = speed  # meters per second
        self.current_position = start_position
    
    def generate_trajectory(self, duration_seconds, time_step=1.0):
        """Generate trajectory points for linear movement, with correct timestamps."""
        # Calculate direction vector
        dx = self.end_position[0] - self.start_position[0]
        dy = self.end_position[1] - self.start_position[1]
        dz = self.end_position[2] - self.start_position[2]

        # Calculate total distance
        distance = math.sqrt(dx**2 + dy**2 + dz**2)

        # Normalize direction vector
        if distance > 0:
            dx, dy, dz = dx/distance, dy/distance, dz/distance

        # Prepare trajectory
        self.trajectory = []
        current_time = self.start_time

        # Determine number of steps
        max_steps = min(int(duration_seconds), int(distance/self.speed))
        for step in range(0, max_steps+1):
            d = min(step * self.speed, distance)
            x = self.start_position[0] + dx * d
            y = self.start_position[1] + dy * d
            z = self.start_position[2] + dz * d

            self.trajectory.append({
                'ue_id': self.ue_id,
                'timestamp': current_time,
                'position': (x, y, z),
                'speed': self.speed,
                'direction': (dx, dy, dz)
            })
            # Advance time
            current_time += timedelta(seconds=time_step)

        return self.trajectory

class LShapedMobilityModel(MobilityModel):
    """L-shaped mobility model with a 90-degree turn (3GPP TR 38.901)"""
    
    def __init__(self, ue_id, start_position, corner_position, end_position, speed, start_time=None):
        super().__init__(ue_id, start_time)
        self.start_position = start_position  # (x, y, z) in meters
        self.corner_position = corner_position  # (x, y, z) in meters
        self.end_position = end_position  # (x, y, z) in meters
        self.speed = speed  # meters per second
        self.current_position = start_position
    
    def generate_trajectory(self, duration_seconds, time_step=1.0):
        """Generate trajectory for L-shaped movement with 90-degree turn"""
        # Create linear models for each segment
        first_segment = LinearMobilityModel(
            self.ue_id, 
            self.start_position, 
            self.corner_position, 
            self.speed, 
            self.start_time
        )
        
        # Calculate when we reach the corner
        dx1 = self.corner_position[0] - self.start_position[0]
        dy1 = self.corner_position[1] - self.start_position[1]
        dz1 = self.corner_position[2] - self.start_position[2]
        segment1_distance = math.sqrt(dx1**2 + dy1**2 + dz1**2)
        segment1_time = segment1_distance / self.speed
        
        # Start time for second segment
        second_segment_start_time = self.start_time + timedelta(seconds=segment1_time)
        
        second_segment = LinearMobilityModel(
            self.ue_id, 
            self.corner_position, 
            self.end_position, 
            self.speed, 
            second_segment_start_time
        )
        
        # Generate trajectories for both segments
        first_traj = first_segment.generate_trajectory(segment1_time, time_step)
        
        # Remaining time for second segment
        remaining_time = max(0, duration_seconds - segment1_time)
        second_traj = []
        if remaining_time > 0:
            second_traj = second_segment.generate_trajectory(remaining_time, time_step)
            # Skip the first point as it's the same as the last point of first segment
            second_traj = second_traj[1:] if second_traj else []
        
        # Combine trajectories
        self.trajectory = first_traj + second_traj
        
        return self.trajectory

class RandomWaypointModel(MobilityModel):
    """
    3GPP TR 38.901 §7.6.3.3 compliant Random Waypoint:
    - Choose random target in area
    - Move there at random speed in [v_min, v_max]
    - Pause for pause_time seconds
    Repeat until duration ends.
    """
    def __init__(self, ue_id, area_bounds, v_min, v_max, pause_time, start_time=None):
        super().__init__(ue_id, start_time)
        self.area_bounds = area_bounds    # ((xmin,ymin,z),(xmax,ymax,z))
        self.v_min = v_min
        self.v_max = v_max
        self.pause_time = pause_time

    def generate_trajectory(self, duration_seconds, time_step=1.0):
        self.trajectory = []
        end_time = self.start_time + timedelta(seconds=duration_seconds)
        current_time = self.start_time
        pos = self._random_point()
        
        while current_time < end_time:
            # Choose next waypoint and speed
            next_wp = self._random_point()
            speed = random.uniform(self.v_min, self.v_max)
            # Travel
            dx, dy, dz = [nw - p for nw, p in zip(next_wp, pos)]
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            travel_time = dist / speed if speed>0 else 0
            steps = max(1, int(travel_time / time_step))
            for i in range(steps):
                if current_time >= end_time: break
                frac = (i+1)/steps
                x = pos[0] + dx*frac
                y = pos[1] + dy*frac
                z = pos[2] + dz*frac
                self.trajectory.append({
                    'ue_id': self.ue_id,
                    'timestamp': current_time,
                    'position': (x, y, z),
                    'speed': speed
                })
                current_time += timedelta(seconds=time_step)
            # Pause
            pause_steps = int(self.pause_time / time_step)
            for _ in range(pause_steps):
                if current_time >= end_time: break
                self.trajectory.append({
                    'ue_id': self.ue_id,
                    'timestamp': current_time,
                    'position': next_wp,
                    'speed': 0
                })
                current_time += timedelta(seconds=time_step)
            pos = next_wp
        return self.trajectory

    def _random_point(self):
        (xmin, ymin, zmin), (xmax, ymax, zmax) = self.area_bounds
        return (random.uniform(xmin, xmax),
                random.uniform(ymin, ymax),
                random.uniform(zmin, zmax))

class ManhattanGridMobilityModel(MobilityModel):
    """
    Urban “Manhattan” grid (3GPP realistic city grid):
    - Moves only along X or Y axis on a grid.
    - At intersections: P(straight)=0.5, P(left)=0.25, P(right)=0.25
    """
    def __init__(self, ue_id, grid_size, speed, start_time=None):
        super().__init__(ue_id, start_time)
        self.grid_size = grid_size  # (x_count, y_count, block_length)
        self.speed = speed
        # initialize at random grid intersection
        xi = random.randint(0, grid_size[0])
        yi = random.randint(0, grid_size[1])
        self.position = (xi * grid_size[2], yi * grid_size[2], 0)
        # random initial direction: (dx, dy)
        self.direction = random.choice([(1,0),(-1,0),(0,1),(0,-1)])

    def generate_trajectory(self, duration_seconds, time_step=1.0):
        self.trajectory = []
        end_time = self.start_time + timedelta(seconds=duration_seconds)
        current_time = self.start_time
        pos = list(self.position)
        dir_x, dir_y = self.direction
        
        while current_time < end_time:
            # Move one block
            block_dist = self.grid_size[2]
            travel_time = block_dist / self.speed
            steps = max(1, int(travel_time/time_step))
            for _ in range(steps):
                if current_time >= end_time: break
                pos[0] += dir_x * self.speed * time_step
                pos[1] += dir_y * self.speed * time_step
                self.trajectory.append({
                    'ue_id': self.ue_id,
                    'timestamp': current_time,
                    'position': tuple(pos),
                    'speed': self.speed
                })
                current_time += timedelta(seconds=time_step)
            if current_time >= end_time: break
            # At intersection: choose turn
            turn = random.random()
            if turn < 0.5:
                # straight: keep dir_x, dir_y
                pass
            elif turn < 0.75:
                dir_x, dir_y = -dir_y, dir_x   # left turn
            else:
                dir_x, dir_y = dir_y, -dir_x   # right turn
        return self.trajectory

class ReferencePointGroupMobilityModel(MobilityModel):
    """
    RPGM (Reference‑Point Group Mobility) per Hong et al.:
    - A logical group “center” moves by some base model (e.g. RandomWaypoint)
    - Each member’s position = group_center + random offset (<= d_max)
    """
    def __init__(self, ue_id, group_center_model, d_max, start_time=None):
        super().__init__(ue_id, start_time)
        self.group_center_model = group_center_model
        self.d_max = d_max  # maximum radius from group center

    def generate_trajectory(self, duration_seconds, time_step=1.0):
        self.trajectory = []
        # Generate center trajectory
        center_traj = self.group_center_model.generate_trajectory(duration_seconds, time_step)
        for point in center_traj:
            cx, cy, cz = point['position']
            # Add random offset inside circle of radius d_max
            angle = random.uniform(0, 2*math.pi)
            radius = random.uniform(0, self.d_max)
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            z = cz
            self.trajectory.append({
                'ue_id': self.ue_id,
                'timestamp': point['timestamp'],
                'position': (x, y, z),
                'speed': point['speed']
            })
        return self.trajectory

class RandomDirectionalMobilityModel(MobilityModel):
    """
    Random directional mobility model (3GPP TR 38.901 Section 7.6.3.3)
    
    The UE moves in random directions, changing direction at random intervals.
    """
    
    def __init__(self, ue_id, start_position, speed, area_bounds=None, 
                 direction_change_mean=30.0, start_time=None):
        """
        Initialize the random directional mobility model.
        
        Args:
            ue_id: UE identifier
            start_position: Starting position (x, y, z) in meters
            speed: Speed in meters per second
            area_bounds: Bounds of the movement area [(min_x, max_x), (min_y, max_y), (min_z, max_z)]
            direction_change_mean: Mean time between direction changes in seconds
            start_time: Starting time
        """
        super().__init__(ue_id, start_time)
        self.start_position = start_position
        self.current_position = start_position
        self.speed = speed
        
        # Default area bounds if not specified
        self.area_bounds = area_bounds or [
            (0, 1000),  # x bounds
            (0, 1000),  # y bounds
            (0, 0)      # z bounds (flat 2D by default)
        ]
        
        # Direction change parameters
        self.direction_change_mean = direction_change_mean
        
        # Initial random direction
        self._generate_random_direction()
    
    def _generate_random_direction(self):
        """Generate a random 3D unit vector for direction."""
        # Random angle in radians (0 to 2π)
        angle = random.uniform(0, 2 * np.pi)
        
        # Convert to unit vector
        self.direction = (np.cos(angle), np.sin(angle), 0)
    
    def _check_boundary_collision(self, position):
        """Check if position is within bounds, return True if collision occurred."""
        for i in range(3):
            if position[i] < self.area_bounds[i][0] or position[i] > self.area_bounds[i][1]:
                return True
        return False
    
    def _handle_boundary_collision(self, position):
        """Handle collision with area boundary by reflecting the direction."""
        new_direction = list(self.direction)
        
        # Check which boundary was hit and reflect
        for i in range(3):
            if position[i] < self.area_bounds[i][0] or position[i] > self.area_bounds[i][1]:
                new_direction[i] = -new_direction[i]
        
        # Update direction
        self.direction = tuple(new_direction)
        
        # Adjust position to be within bounds
        adjusted_position = list(position)
        for i in range(3):
            if adjusted_position[i] < self.area_bounds[i][0]:
                adjusted_position[i] = self.area_bounds[i][0]
            elif adjusted_position[i] > self.area_bounds[i][1]:
                adjusted_position[i] = self.area_bounds[i][1]
        
        return tuple(adjusted_position)
    
    def generate_trajectory(self, duration_seconds, time_step=1.0):
        """Generate trajectory points for random directional movement."""
        self.trajectory = []
        current_time = self.start_time or datetime.now()
        current_position = self.start_position
        
        # Time until next direction change
        time_to_change = np.random.exponential(self.direction_change_mean)
        
        for t in np.arange(0, duration_seconds, time_step):
            # Check if it's time to change direction
            if t >= time_to_change:
                self._generate_random_direction()
                time_to_change = t + np.random.exponential(self.direction_change_mean)
            
            # Calculate new position
            dx, dy, dz = self.direction
            new_position = (
                current_position[0] + dx * self.speed * time_step,
                current_position[1] + dy * self.speed * time_step,
                current_position[2] + dz * self.speed * time_step
            )
            
            # Check if position is within bounds
            if self._check_boundary_collision(new_position):
                new_position = self._handle_boundary_collision(new_position)
            
            current_position = new_position
            
            # Add to trajectory
            self.trajectory.append({
                'ue_id': self.ue_id,
                'timestamp': current_time + timedelta(seconds=t),
                'position': current_position,
                'speed': self.speed,
                'direction': self.direction
            })
        
        return self.trajectory


class UrbanGridMobilityModel(MobilityModel):
    """
    Urban grid mobility model for simulating UE movement in city streets.
    
    This model represents movement along a rectangular grid of streets
    with random turns at intersections.
    """
    
    def __init__(self, ue_id, start_position, speed, grid_size=50.0, 
                 turn_probability=0.3, start_time=None):
        """
        Initialize the urban grid mobility model.
        
        Args:
            ue_id: UE identifier
            start_position: Starting position (x, y, z) in meters
            speed: Speed in meters per second
            grid_size: Size of grid cells (distance between streets)
            turn_probability: Probability of turning at an intersection
            start_time: Starting time
        """
        super().__init__(ue_id, start_time)
        self.start_position = start_position
        self.current_position = start_position
        self.speed = speed
        self.grid_size = grid_size
        self.turn_probability = turn_probability
        
        # Snap start position to the grid
        self._snap_to_grid()
        
        # Initial direction (east, west, north, south)
        self.directions = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
        self.current_direction = random.choice(self.directions)
    
    def _snap_to_grid(self):
        """Snap the current position to the nearest grid line."""
        x, y, z = self.current_position
        
        # Determine closest grid lines
        x_mod = x % self.grid_size
        y_mod = y % self.grid_size
        
        # Snap to closest grid line
        if x_mod < self.grid_size / 2:
            x_snapped = x - x_mod
        else:
            x_snapped = x + (self.grid_size - x_mod)
        
        if y_mod < self.grid_size / 2:
            y_snapped = y - y_mod
        else:
            y_snapped = y + (self.grid_size - y_mod)
        
        self.current_position = (x_snapped, y_snapped, z)
    
    def _is_at_intersection(self, position):
        """Check if the position is at a grid intersection."""
        x, y, _ = position
        return (abs(x % self.grid_size) < 0.1 and 
                abs(y % self.grid_size) < 0.1)
    
    def _choose_new_direction(self, current_direction):
        """Choose a new direction at an intersection."""
        # At an intersection, can't go back the way we came
        dx, dy, dz = current_direction
        possible_directions = [d for d in self.directions if d[0] != -dx or d[1] != -dy]
        
        # With probability, change direction
        if random.random() < self.turn_probability:
            return random.choice(possible_directions)
        else:
            # Continue in same direction if possible, otherwise choose randomly
            if current_direction in possible_directions:
                return current_direction
            else:
                return random.choice(possible_directions)
    
    def generate_trajectory(self, duration_seconds, time_step=1.0):
        """Generate trajectory points for urban grid movement."""
        self.trajectory = []
        current_time = self.start_time or datetime.now()
        current_position = self.current_position
        current_direction = self.current_direction
        
        for t in np.arange(0, duration_seconds, time_step):
            # Check if at intersection
            if self._is_at_intersection(current_position):
                current_direction = self._choose_new_direction(current_direction)
            
            # Calculate new position
            dx, dy, dz = current_direction
            new_position = (
                current_position[0] + dx * self.speed * time_step,
                current_position[1] + dy * self.speed * time_step,
                current_position[2] + dz * self.speed * time_step
            )
            
            current_position = new_position
            
            # Add to trajectory
            self.trajectory.append({
                'ue_id': self.ue_id,
                'timestamp': current_time + timedelta(seconds=t),
                'position': current_position,
                'speed': self.speed,
                'direction': current_direction
            })
        
        return self.trajectory


# class GroupMobilityModel(MobilityModel):
#     """
#     Group mobility model for correlated UE movements.
    
#     This model represents a group of UEs moving together with a 
#     reference point following a specified mobility model.
#     """
    
#     def __init__(self, ue_id, reference_model, relative_position, 
#                 max_deviation=5.0, deviation_change_mean=10.0, start_time=None):
#         """
#         Initialize the group mobility model.
        
#         Args:
#             ue_id: UE identifier
#             reference_model: Reference mobility model to follow
#             relative_position: Position relative to the reference point (x, y, z)
#             max_deviation: Maximum random deviation from relative position
#             deviation_change_mean: Mean time between deviation changes
#             start_time: Starting time
#         """
#         super().__init__(ue_id, start_time)
#         self.reference_model = reference_model
#         self.relative_position = relative_position
#         self.max_deviation = max_deviation
#         self.deviation_change_mean = deviation_change_mean
        
#         # Current random deviation
#         self.current_deviation = (0, 0, 0)
        
#         # Time until next deviation change
#         self.time_to_change = np.random.exponential(self.deviation_change_mean)
    
#     def _generate_random_deviation(self):
#         """Generate a random deviation within max_deviation."""
#         return (
#             random.uniform(-self.max_deviation, self.max_deviation),
#             random.uniform(-self.max_deviation, self.max_deviation),
#             random.uniform(-self.max_deviation, self.max_deviation)
#         )
    
#     def generate_trajectory(self, duration_seconds, time_step=1.0):
#         """Generate trajectory points for group movement."""
#         # First generate reference trajectory
#         reference_trajectory = self.reference_model.generate_trajectory(
#             duration_seconds, time_step
#         )
        
#         self.trajectory = []
        
#         for i, ref_point in enumerate(reference_trajectory):
#             t = i * time_step
            
#             # Check if it's time to change deviation
#             if t >= self.time_to_change:
#                 self.current_deviation = self._generate_random_deviation()
#                 self.time_to_change = t + np.random.exponential(self.deviation_change_mean)
            
#             # Reference position
#             ref_position = ref_point['position']
            
#             # Calculate position with relative offset and current deviation
#             position = (
#                 ref_position[0] + self.relative_position[0] + self.current_deviation[0],
#                 ref_position[1] + self.relative_position[1] + self.current_deviation[1],
#                 ref_position[2] + self.relative_position[2] + self.current_deviation[2]
#             )
            
#             # Add to trajectory
#             self.trajectory.append({
#                 'ue_id': self.ue_id,
#                 'timestamp': ref_point['timestamp'],
#                 'position': position,
#                 'speed': ref_point['speed'],
#                 'direction': ref_point['direction']
#             })
        
#         return self.trajectory