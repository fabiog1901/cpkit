# DB

The DB package owns the shared database connection pool and low-level query
helpers used by repository mixins.

cpkit currently targets Cockroach/Postgres-style SQL. The helper functions hide
some repetitive details: pool access, cursor row mapping, JSON/list dumpers,
statement normalization, and translation from database exceptions into
repository exceptions.

## Files

- `postgres.py`: Pool lifecycle, query helpers, custom dumpers, and database
  error translation.
- `__init__.py`: Public exports.

## Runtime Flow

1. `create_cpkit_app()` calls `initialize_postgres(db_url)` during app startup.
2. Repository mixins call helpers such as `fetch_one()`, `fetch_all()`,
   `fetch_scalar()`, and `execute_stmt()`.
3. Database exceptions are translated into `cpkit.errors.repository` types.
4. Service layers translate repository errors into user-facing service errors.

