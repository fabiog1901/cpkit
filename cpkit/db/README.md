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

## Explicit Transactions

Use `transaction()` when several statements must commit or roll back together.
The yielded object exposes the same query helpers, all bound to one connection:

```python
from cpkit.db import transaction

with transaction(operation="widgets.transfer") as tx:
    tx.execute_stmt(
        "UPDATE widgets SET owner_id = %s WHERE widget_id = %s",
        (new_owner_id, widget_id),
    )
    widget = tx.fetch_one(
        "SELECT * FROM widgets WHERE widget_id = %s",
        (widget_id,),
        Widget,
    )
```

The context commits after a normal exit and rolls back if an exception escapes.
Database failures use the same repository-error translation as the standalone
helpers.
