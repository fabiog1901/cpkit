# Settings

The settings package owns framework settings stored in `cpkit.settings`.
Settings are editable through the admin webapp and used by framework services
such as auth and logging.

## Files

- `keys.py`: Framework setting keys.
- `types.py`: Setting records and API request/response models.
- `repository.py`: Repository mixin for reading and writing settings.
- `service.py`: Setting update/reset rules and audit hooks.
- `router.py`: Admin settings API routes.

## Runtime Flow

1. Framework code asks the configured repository for a setting value.
2. Admin routes list or modify settings through `SettingsService`.
3. Updates and resets emit audit events.
4. The webapp settings page renders the resulting rows and handles secret-ish
   values according to metadata.

