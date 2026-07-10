# cpkit Resources

Framework-owned schema and seed resources live here.

| File | Purpose |
| --- | --- |
| `repository_maintenance_guide.md` | Shared Makefile/codemap/pre-commit workflow for cpkit-based projects. |
| `webapp_extension_guide.md` | Reusable guide for porting an app webapp to cpkit's template extension model. |

The framework DDL is packaged at `cpkit.resources/ddl.sql`. Code should use
`cpkit.cpkit_ddl_path()` or
`cpkit.resources.cpkit_ddl_path()` instead of walking the source checkout.

Application-owned schema should stay outside cpkit, such as CP's `resources/ddl.sql`.
When an app is packaged for pip, that app should include its own DDL as package
data or expose an app-owned resource helper for its schema.

Installed applications should depend on cpkit from PyPI, while examples inside
this repository may use a local editable path dependency for framework
development.
