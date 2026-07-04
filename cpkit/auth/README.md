# Auth

The auth package owns cpkit's authentication and authorization features:
OIDC browser login, signed API keys, role/group mapping, session storage, and
FastAPI dependencies such as `require_admin`.

Auth is bundled before most other capabilities because routes and services rely
on it for access checks and audit actor identity.

## Files

- `bundle.py`: Creates the auth bundle: OIDC manager, dependencies, auth router,
  and auth audit hooks.
- `oidc.py`: OIDC login, callback, session validation, logout, and API key
  request validation mechanics.
- `dependencies.py`: FastAPI dependencies for authenticated, readonly, user, and
  admin access.
- `router.py`: OIDC/session routes.
- `api_key_router.py`: Admin API key routes.
- `api_key_service.py`: API key creation/deletion rules.
- `api_keys.py`: API key generation and signing helpers.
- `repositories.py`: Repository mixins for API keys, OIDC sessions, and
  role-to-group mappings.
- `claims.py`: Helpers for interpreting identity/provider claims.
- `config.py`: OIDC and auth-related configuration access.
- `redirects.py`: Login redirect helpers.
- `secrets.py`: Secret encryption/decryption helpers.
- `types.py`: Auth models and records.

## Runtime Flow

1. `create_auth_bundle()` builds the OIDC manager and dependency set.
2. Routers use dependencies like `require_admin` to enforce access.
3. The OIDC manager persists sessions through repository mixins.
4. API key requests are verified using stored encrypted secrets and request
   signatures.
5. Login/logout and API key mutations emit audit events.

