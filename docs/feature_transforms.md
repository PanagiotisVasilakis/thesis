# Feature Transformation Registry

The ML service uses a central registry to map feature names to transformation
functions.  During feature extraction every registered transform is applied to
the corresponding feature, ensuring consistent data types and preprocessing.

## Built-in transforms

The registry ships with a small set of default transforms:

| Name     | Description                                   |
|----------|-----------------------------------------------|
| `identity` | Return the value unchanged.                  |
| `float`    | Convert the value to `float`, falling back to `0.0`. |
| `int`      | Convert the value to `int`, falling back to `0`.     |
| `bool`     | Convert truthy values to `True`/`False`.             |

## Registering via configuration

`app/config/features.yaml` associates each feature with an optional
`transform` field.  The value may be one of the built-in transform names or a
fully qualified Python path.  For example:

```yaml
base_features:
  - name: latitude
    transform: float
  - name: handover_count
    transform: int
  - name: altitude
    transform: math.sqrt  # resolved dynamically
```

When the model loads this configuration the registry resolves each `transform`
value.  If the value contains a dot it is treated as a Python import path and
loaded dynamically, allowing custom transforms to live anywhere on the
`PYTHONPATH`.

## Registering in code

Transforms can also be added programmatically:

```python
from ml_service.app.features.transform_registry import register_feature_transform

register_feature_transform("latitude", lambda v: float(v) * 10)
```

Once registered, the transform is applied automatically whenever `latitude`
appears in a feature dictionary.

To clear all custom registrations (useful in tests) call
`clear_feature_transforms()`.
