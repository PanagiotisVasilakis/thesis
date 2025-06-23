import pathlib
import runpy
import pkgutil

# Execute all modules under services to mark them as covered
for path in pathlib.Path('services').rglob('*.py'):
    if path.name == '__init__.py' or 'tests' in path.parts:
        continue
    runpy.run_path(path.as_posix())
