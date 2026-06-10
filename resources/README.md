# cpkit Resources

Framework-owned schema and seed resources live here.

| File | Purpose |
| --- | --- |
| `ddl.sql` | cpkit schema and framework-owned tables. Run before application schema setup. |
| `webapp_extension_guide.md` | Reusable guide for porting an app webapp to cpkit's template extension model. |

Application-owned schema should stay outside cpkit, such as CP's `resources/ddl.sql`.
