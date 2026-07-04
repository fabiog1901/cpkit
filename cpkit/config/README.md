# Config

The config package contains small helpers for reading environment-backed
configuration.

At the moment this package is intentionally tiny:

- `env.py`: Environment lookup helpers.

Keep broad framework wiring in `bundle.py` or capability-specific config modules
such as `auth/config.py`. Use this package for generic configuration helpers
that do not belong to a single capability.

