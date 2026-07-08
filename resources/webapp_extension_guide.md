# cpkit Webapp Extension Guide

This guide describes how an application should use cpkit's template webapp
without copying or forking the framework-owned shell.

Use this document as the instruction source when asking Codex to port an app
webapp, such as Kloigos, to cpkit.

## Goal

The application uses cpkit's webapp as the main shell. cpkit owns the shared
pages and browser plumbing for:

- Authentication/session visibility
- Dashboard
- Jobs
- Events
- Settings
- API keys
- Playbooks

The application contributes only business-specific views, admin views, styles,
and browser logic through extension assets.

## Expected App Structure

The app must provide a small static webapp directory:

```text
webapp/
  extension.html
  extension.css
  extension.js
```

The app bootstrap should pass that directory to cpkit:

```python
from cpkit import create_cpkit_app, template_webapp_directory

app = create_cpkit_app(
    title="my-app",
    version="0.1.0",
    repo_class=Repo,
    db_url=CPKIT_DB_URL,
    capabilities=(app_capabilities,),
    routers=(app_router,),
    static_directory=template_webapp_directory(),
    app_static_directory="webapp",
)
```

cpkit mounts the app webapp directory at `/app`.

## App Extension Checklist

Read this checklist before migrating or editing an app webapp:

- Keep cpkit's template webapp as the shell.
- Create exactly these app-owned extension files:
  - `webapp/extension.html`
  - `webapp/extension.css`
  - `webapp/extension.js`
- Register the app once with `window.cpkitWebappExtension`.
- Put only app-specific markup in `extension.html`.
- Put only app-specific state and methods in `extension.js`.
- Put only app-specific styles in `extension.css`.
- Use cpkit hash routes for app pages.
- Use shell helpers such as `apiFetch()`, `showNotice()`, and
  `parseHashRoute()` instead of copying shell behavior.
- Keep large database IDs as strings in JSON and JavaScript.
- Run `node --check webapp/extension.js` after editing.

## Extension JavaScript Contract

`extension.js` registers the application extension on `window`. This is the
single app registration object. Do not define `window.app`.

```javascript
window.cpkitWebappExtension = {
  htmlPath: "/app/extension.html",
  navItems: [{ view: "app_view", label: "App" }],
  dashboardEnsure: "ensureAppDashboard",
  dashboardItems: [
    {
      key: "open-tasks",
      label: "Open Tasks",
      kicker: "TODO",
      description: "Tasks that still need work.",
      valueKey: "openTodoCount",
      view: "app_view",
    },
  ],
  adminItems: [
    {
      view: "app_admin",
      label: "App Admin",
      kicker: "Application",
      description: "Manage application-specific settings.",
    },
  ],
  routes: {
    app_view: {
      path: "/app-view",
      label: "App",
      subtitle: "Application view",
      ensure: "ensureAppView",
    },
    app_admin: {
      path: "/admin/app",
      label: "App Admin",
      subtitle: "Application administration",
      adminOnly: true,
      ensure: "ensureAppAdmin",
    },
    app_item: {
      path: "/app/items/detail",
      label: "App Item",
      subtitle: "Application item details",
      ensure: "ensureAppItem",
      match: (path) => /^\/app\/items\/[^/]+$/.test(path),
    },
  },
  state: {
    rows: [],
    adminRows: [],
    openTodoCount: 0,
    loading: { list: false },
  },
  methods: {
    async ensureAppDashboard() {
      const data = await this.apiFetch("/app/dashboard", { method: "GET" });
      this.openTodoCount = data.open_todo_count || 0;
    },
    async ensureAppView() {
      await this.refreshAppRows();
    },
    async refreshAppRows() {
      this.loading.list = true;
      try {
        this.rows = await this.apiFetch("/app/resources", { method: "GET" });
      } finally {
        this.loading.list = false;
      }
    },
    async ensureAppAdmin() {
      this.adminRows = await this.apiFetch("/app/admin/resources", { method: "GET" });
    },
  },
};
```

Supported top-level keys:

- `htmlPath`: Path to app markup, normally `/app/extension.html`.
- `navItems`: App-owned primary navigation entries.
- `adminItems`: App-owned admin landing-page entries.
- `dashboardItems`: Simple app metric cards on cpkit's Dashboard.
- `dashboardEnsure`: Name of an extension method that loads app dashboard data.
- `routes`: App hash-route definitions keyed by view name.
- `state`: App-owned Alpine state merged into the cpkit shell state.
- `methods`: App-owned Alpine methods merged into the cpkit shell methods.

Route `path` values are hash routes in the cpkit shell. Static routes match
exactly. If an app needs dynamic hash paths, such as `/app/items/<id>`, add a
`match(path)` function to the route and parse the selected ID from
`window.location.hash` or a helper method. API calls should be relative to
cpkit's `/api` prefix by using the shell-provided `apiFetch()` helper.

Timestamp values should use the shell formatter instead of rendering raw ISO
strings. Inside extension templates and methods, call
`this.formatDateTime(value)` to display UTC timestamps as
`yyyy-mm-dd hh:mm:ss`. Plain extension JavaScript can call
`window.cpkitFormatDateTime(value)` with the same behavior. Pass
`{ utc: false }` only when the app intentionally wants browser-local time.

Use `navItems` for primary topbar pages. Use `adminItems` for application
pages that should appear inside cpkit's Admin surfaces. Each `adminItems`
entry must reference a key in `routes`. Admin routes should normally use an
`/admin/...` path and `adminOnly: true`; cpkit also treats any route referenced
by `adminItems` as requiring `CP_ADMIN`.

Use `dashboardItems` for simple application metric cards on cpkit's default
Dashboard. cpkit renders application dashboard cards first by default and keeps
its built-in Jobs and Events cards at the bottom. Users can drag cards to
reorder them; the order is stored in browser local storage. Set a stable `key`
on each item so saved ordering survives label or route changes. Each item can
use `value`, `valueKey`, or `countKey`; `valueKey` and `countKey` read from the
Alpine state object. Set `view` when clicking the card should navigate to an
extension route.

If the app needs richer dashboard content, such as charts, images, maps, or
custom multi-card layouts, add a template with `id="cpkit-extension-dashboard"`
to `extension.html`. Each top-level child in that template becomes a draggable
dashboard card sibling next to app metric cards and cpkit's built-in Jobs and
Events cards. If the template contains a single `.dashboard-grid` wrapper,
cpkit unwraps that one level and treats each child in the grid as its own card.
Add `data-dashboard-key` to template cards when you want saved ordering to
survive title or markup changes. Use `dashboardEnsure` to name an extension
method that should refresh application dashboard data when the Dashboard loads.

## Shell-Provided Helpers

Extension methods run on the same Alpine component as the cpkit shell. Use these
helpers from `methods` with `this.<helper>()`:

- `apiFetch(path, options)`: authenticated JSON API calls under cpkit's API
  prefix.
- `showNotice(message, options)`: display a cpkit banner that auto-dismisses.
  Pass `{ jobId }` to include an "Open Job" link, or `{ timeoutMs: 0 }` to keep
  the notice visible until cleared.
- `clearNotice()`: clear the current cpkit banner and linked job id.
- `routeForView(view)`: return the shell hash route for a registered view.
- `setView(view)`: navigate to a shell or extension view.
- `parseHashRoute()`: parse `window.location.hash` into `{ path, parts, query }`.
- `canViewAdmin()`: whether the current user can see admin pages.
- `hasRole(role)`: whether the current user has a role.
- `authGroups()`: current user's groups/roles from auth claims.
- `errorMessage(error, fallback)`: extract a readable error message.
- `utcNowString()`: current UTC timestamp formatted as `yyyy-mm-dd hh:mm:ss`.
- `toUtcStringMaybe(value)`: format a timestamp as `yyyy-mm-dd hh:mm:ss`, or
  return `-`/the original value when empty/invalid.
- `formatDateTime(value, options)`: timestamp formatter used by
  `toUtcStringMaybe()`.
- Ace helpers:
  - `isAceAvailable()`
  - `createAceEditor(elementOrRef, options)`
  - `setAceValue(editor, value)`
  - `destroyAceEditor(editor)`

Plain extension JavaScript can also call
`window.cpkitFormatDateTime(value, options)`.

## Extension Rules

Do:

- Use `window.cpkitWebappExtension` as the only app registration point.
- Use cpkit hash routing for app pages.
- Use `this.apiFetch()` for app API calls.
- Use `this.showNotice()` and `this.clearNotice()` for shell notices.
- Use `this.formatDateTime()`/`this.toUtcStringMaybe()` for timestamps.
- Treat large DB-generated IDs as strings in JSON and JavaScript.

Do not:

- Do not define `window.app`.
- Do not copy cpkit's Dashboard, Jobs, Events, Settings, API Keys, Playbooks,
  login/session UI, topbar, or Admin landing page into the app extension.
- Do not write directly to shell-owned state such as `viewNotice`,
  `viewNoticeJobId`, `view`, `authClaims`, or built-in page arrays.
- Do not add app-specific hardcoded behavior to cpkit-owned pages.
- Do not add duplicate Ace script tags.
- Do not rely on JavaScript numbers for large `INT8` database IDs.

## Optional Ace Editor Helper

The cpkit template loads Ace once from the shell HTML before `/script.js` runs.
Extensions should not add their own Ace script tags. If an extension needs a
code editor, call the shell helper methods from extension methods:

```javascript
methods: {
  ensureSqlEditor() {
    if (this.sqlEditor) return;
    this.sqlEditor = this.createAceEditor(this.$refs.sqlEditor, {
      mode: "sql",
      theme: "cobalt",
      value: this.sqlText,
      readOnly: false,
      wrap: true,
      minLines: 8,
      maxLines: 18,
      onChange: (value) => {
        this.sqlText = value;
      },
    });
  },
  syncSqlEditor(value) {
    this.sqlText = String(value || "");
    this.setAceValue(this.sqlEditor, this.sqlText);
  },
  destroySqlEditor() {
    this.destroyAceEditor(this.sqlEditor);
    this.sqlEditor = null;
  },
}
```

Available helpers:

- `isAceAvailable()` returns `true` when Ace is loaded.
- `createAceEditor(elementOrRef, options)` returns an Ace editor or `null`.
- `setAceValue(editor, value)` safely updates an existing Ace editor.
- `destroyAceEditor(editor)` tears down an editor without removing the caller's
  DOM element.

Keep Ace optional. `createAceEditor(...)` returns `null` when Ace or the target
element is unavailable, so extension markup should keep a textarea or plain text
fallback for important content.

## Extension HTML Contract

`extension.html` contains app-specific Alpine markup. It can also declare app
branding:

```html
<template
  id="cpkit-extension-brand"
  data-logo-text="kg"
  data-app-name="Kloigos"
  data-login-subtitle="Authenticate to manage Kloigos"
></template>

<template id="cpkit-extension-dashboard">
  <div class="dashboard-grid">
    <article class="dashboard-card" data-dashboard-key="custom-dashboard-object">
      <div class="dashboard-card-head">
        <div>
          <div class="dashboard-card-kicker">Application</div>
          <h3>Custom dashboard object</h3>
        </div>
        <div class="dashboard-stat" x-text="openTodoCount"></div>
      </div>
      <p>Apps can place charts, images, or richer dashboard objects here.</p>
    </article>
  </div>
</template>

<main class="layout" x-show="view === 'app_view'">
  <aside class="sidebar">
    <section>
      <h2>Actions</h2>
      <div class="metric button-stack">
        <button class="btn primary" @click="refreshAppRows()">Refresh</button>
      </div>
    </section>
  </aside>

  <section class="main">
    <div class="section-head">
      <div>
        <h2>App</h2>
        <p>Application-specific data.</p>
      </div>
    </div>
  </section>
</main>

<main class="layout" x-show="view === 'app_admin'">
  <aside class="sidebar">
    <section>
      <h2>App Admin</h2>
      <div class="metric button-stack">
        <button class="btn primary" @click="ensureAppAdmin()">Refresh</button>
      </div>
    </section>
  </aside>

  <section class="main">
    <div class="section-head">
      <div>
        <h2>App Admin</h2>
        <p>Application-specific administration.</p>
      </div>
    </div>
  </section>
</main>

<main class="layout" x-show="view === 'app_item'">
  <aside class="sidebar">
    <section>
      <h2>Item</h2>
      <div class="metric">
        <div class="metric-label">Selected ID</div>
        <div class="metric-value" x-text="selectedTodoId || '-'"></div>
      </div>
    </section>
  </aside>

  <section class="main">
    <div class="section-head">
      <div>
        <h2 x-text="selectedTodo?.title || 'Item'"></h2>
        <p x-text="selectedTodo?.created_at ? toUtcStringMaybe(selectedTodo.created_at) : '-'"></p>
      </div>
    </div>
  </section>
</main>
```

Use cpkit's existing shell classes where possible, such as `layout`, `sidebar`,
`main`, `section-head`, `table-wrap`, `btn`, `input`, `notice`, and `modal`.

## Minimal TODO-Style Example

This is a compact example showing a normal TODO page, an admin page, dashboard
cards, a richer dashboard template, a dynamic route, and a notice with a job
link.

`webapp/extension.js`:

```javascript
window.cpkitWebappExtension = {
  htmlPath: "/app/extension.html",
  navItems: [{ view: "todos", label: "TODOs" }],
  adminItems: [
    {
      view: "todo_admin",
      label: "TODO Admin",
      kicker: "Application",
      description: "Review TODO app settings.",
    },
  ],
  dashboardEnsure: "ensureTodoDashboard",
  dashboardItems: [
    {
      key: "todo-open-count",
      label: "Open TODOs",
      kicker: "TODO",
      valueKey: "todoStats.open",
      view: "todos",
    },
  ],
  routes: {
    todos: {
      path: "/todos",
      label: "TODOs",
      subtitle: "Application TODOs",
      ensure: "ensureTodos",
    },
    todo_admin: {
      path: "/admin/todos",
      label: "TODO Admin",
      subtitle: "TODO administration",
      adminOnly: true,
      ensure: "ensureTodoAdmin",
    },
    todo_detail: {
      path: "/todos/detail",
      label: "TODO Detail",
      subtitle: "TODO item",
      ensure: "ensureTodoDetail",
      match: (path) => /^\/todos\/[^/]+$/.test(path),
    },
  },
  state: {
    todos: [],
    todoAdminRows: [],
    todoStats: { open: 0 },
    selectedTodoId: "",
    selectedTodo: null,
    todoLoading: { list: false, detail: false, export: false },
  },
  methods: {
    async ensureTodoDashboard() {
      const stats = await this.apiFetch("/todos/stats", { method: "GET" });
      this.todoStats = { ...this.todoStats, ...(stats || {}) };
    },

    async ensureTodos() {
      await this.refreshTodos();
    },

    async refreshTodos() {
      this.todoLoading.list = true;
      try {
        const rows = await this.apiFetch("/todos/", { method: "GET" });
        this.todos = Array.isArray(rows) ? rows : [];
      } catch (error) {
        this.showNotice(this.errorMessage(error, "Failed to load TODOs."));
      } finally {
        this.todoLoading.list = false;
      }
    },

    openTodo(todoId) {
      this.selectedTodoId = String(todoId || "");
      this.setView("todo_detail");
    },

    async ensureTodoDetail() {
      const route = this.parseHashRoute();
      this.selectedTodoId = String(route.parts[1] || this.selectedTodoId || "");
      if (!this.selectedTodoId) return;
      this.todoLoading.detail = true;
      try {
        this.selectedTodo = await this.apiFetch(
          `/todos/${encodeURIComponent(this.selectedTodoId)}`,
          { method: "GET" },
        );
      } catch (error) {
        this.showNotice(this.errorMessage(error, "Failed to load TODO."));
      } finally {
        this.todoLoading.detail = false;
      }
    },

    async ensureTodoAdmin() {
      if (!this.canViewAdmin()) return;
      const rows = await this.apiFetch("/todos/admin/settings", { method: "GET" });
      this.todoAdminRows = Array.isArray(rows) ? rows : [];
    },

    async exportTodos() {
      this.todoLoading.export = true;
      try {
        const result = await this.apiFetch("/todos/export", { method: "POST" });
        this.showNotice(`Created export job ${result.job_id}.`, {
          jobId: result.job_id,
        });
      } catch (error) {
        this.showNotice(this.errorMessage(error, "Failed to export TODOs."));
      } finally {
        this.todoLoading.export = false;
      }
    },
  },
};
```

`webapp/extension.html`:

```html
<template id="cpkit-extension-dashboard">
  <article class="dashboard-card" data-dashboard-key="todo-latest">
    <div class="dashboard-card-head">
      <div>
        <div class="dashboard-card-kicker">TODO</div>
        <h3>Latest TODOs</h3>
      </div>
      <button type="button" class="dashboard-link-button" @click="setView('todos')">Open</button>
    </div>
    <div class="table-wrap dashboard-table-wrap">
      <table class="data-table dashboard-table">
        <tbody>
          <template x-for="todo in todos.slice(0, 5)" :key="`todo-dashboard-${todo.todo_id}`">
            <tr>
              <td>
                <a href="#" class="dashboard-link" @click.prevent="openTodo(todo.todo_id)">
                  <span x-text="todo.title"></span>
                </a>
              </td>
              <td x-text="toUtcStringMaybe(todo.updated_at || todo.created_at)"></td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </article>
</template>

<main class="layout" x-show="view === 'todos'">
  <aside class="sidebar">
    <section>
      <h2>TODOs</h2>
      <div class="metric button-stack">
        <button type="button" class="btn primary" @click="refreshTodos()">Refresh</button>
        <button type="button" class="btn" @click="exportTodos()">Export</button>
      </div>
    </section>
  </aside>

  <section class="main">
    <div class="section-head">
      <div>
        <h2>TODOs</h2>
        <p>Application-owned work items.</p>
      </div>
    </div>
    <div class="table-container">
      <div class="table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Status</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            <template x-for="todo in todos" :key="`todo-${todo.todo_id}`">
              <tr>
                <td>
                  <a href="#" class="dashboard-link" @click.prevent="openTodo(todo.todo_id)">
                    <span x-text="todo.title"></span>
                  </a>
                </td>
                <td><span class="service-pill" x-text="todo.completed ? 'Done' : 'Open'"></span></td>
                <td x-text="toUtcStringMaybe(todo.updated_at || todo.created_at)"></td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</main>

<main class="layout" x-show="view === 'todo_admin'">
  <aside class="sidebar">
    <section>
      <h2>TODO Admin</h2>
    </section>
  </aside>
  <section class="main">
    <div class="section-head">
      <div>
        <h2>TODO Admin</h2>
        <p>Application admin data.</p>
      </div>
    </div>
  </section>
</main>
```

## Extension CSS Contract

`extension.css` should only style app-specific content. Prefer additive class
names that belong to the app view:

```css
.app-title-cell {
  min-width: 16rem;
}

.app-actions {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}
```

Avoid restyling the cpkit shell globally unless the app intentionally owns a
broader visual theme.

## Porting Checklist

1. Map the existing app webapp.
   - Identify old shell code.
   - Identify pages already provided by cpkit.
   - Identify true app-specific pages.
   - List API endpoints each app page calls.

2. Update the app bootstrap.
   - Use `template_webapp_directory()` for cpkit's static shell.
   - Pass `app_static_directory="webapp"` or the app's equivalent path.
   - Keep app API routers mounted through cpkit.

3. Create extension assets.
   - Move app-specific markup into `webapp/extension.html`.
   - Move app-specific state, route registration, and methods into
     `webapp/extension.js`.
   - Define `window.cpkitWebappExtension`; do not define `window.app`.
   - Register app admin pages in `adminItems` and back them with routes marked
     `adminOnly: true`.
   - Move app-specific styles into `webapp/extension.css`.

4. Remove duplicate shell code.
   - Do not copy cpkit's topbar, auth/login panel, admin overview, jobs page,
     events page, settings page, API keys page, or playbooks page.
   - App-specific admin pages should be extension pages registered through
     `adminItems`, not copies of cpkit's Admin page.
   - Do not reimplement session/auth UI in the app extension.

5. Preserve API behavior.
   - Keep existing app-specific endpoints unless the migration explicitly
     changes them.
   - Use `this.apiFetch()` from extension methods for authenticated API calls.
   - Use `this.showNotice()` and `this.clearNotice()` for cpkit notices.
   - Use `this.toUtcStringMaybe()` or `this.formatDateTime()` for timestamps.

6. Handle database IDs carefully.
   - Database-generated `INT8` IDs can exceed JavaScript's safe integer range.
   - Serialize large IDs as strings in JSON responses.
   - Treat IDs as strings in JavaScript and path construction.

7. Verify the port.
   - Run `node --check webapp/extension.js`.
   - Run Python compile/import checks for the app.
   - Start the app and confirm the `/app` static mount is present.
   - Confirm each app route renders once and only once.
   - Confirm each `adminItems` route appears on the Admin page and is hidden
     from users without `CP_ADMIN`.
   - Confirm app actions call the expected `/api/...` endpoints.

## Recommended Codex Prompt

```text
Read resources/webapp_extension_guide.md and port this app's webapp to cpkit's
template extension model.

Preserve app-specific behavior, remove duplicate shell code, do not fork
cpkit's webapp, and work in small verifiable steps. Keep large database IDs as
strings in JavaScript-facing JSON.
```

Before starting a larger port, add a short app-specific map to the prompt:

```text
Current webapp map:
- webapp/index.html: old app shell and page markup
- webapp/script.js: old app state/actions
- webapp/style.css: reusable app styles
- /api/example: endpoint used by Example page
```
