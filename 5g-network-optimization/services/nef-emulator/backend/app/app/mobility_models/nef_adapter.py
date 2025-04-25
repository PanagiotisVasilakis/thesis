# mobility_models/nef_adapter.py
import json
from .models import LinearMobilityModel, LShapedMobilityModel
from ..network.state_manager import NetworkStateManager

def generate_nef_path_points(model_type, **kwargs):
    # choose the right class
    cls = {
      'linear': LinearMobilityModel,
      'l_shaped': LShapedMobilityModel
    }[model_type]
    model = cls(**{k: v for k, v in kwargs.items() if k in cls.__init__.__code__.co_varnames})
    traj = model.generate_trajectory(kwargs['duration'], kwargs.get('time_step', 1.0))
    # convert into NEF JSON shape
    points = [
      {
        'latitude': p['position'][0],
        'longitude': p['position'][1],
        'description': f"{model_type}_{i}"
      } for i, p in enumerate(traj)
    ]
    return points

def save_path_to_json(points, filename):
    with open(filename, 'w') as f:
        json.dump(points, f, indent=2)
    return filename
