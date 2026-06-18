from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("romyq")
except PackageNotFoundError:
    # Package metadata not available — running from source without pip install.
    # Use an obviously-invalid sentinel so callers can detect the misconfiguration.
    __version__ = "0.0.0+unknown"
