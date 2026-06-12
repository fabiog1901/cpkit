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

The app should provide a small static webapp directory:

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

## Extension JavaScript Contract

`extension.js` registers the application extension on `window`:

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

Route `path` values are hash routes in the cpkit shell. Static routes match
exactly. If an app needs dynamic hash paths, such as `/app/items/<id>`, add a
`match(path)` function to the route and parse the selected ID from
`window.location.hash` or a helper method. API calls should be relative to
cpkit's `/api` prefix by using the shell-provided `apiFetch()` helper.

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
```

Use cpkit's existing shell classes where possible, such as `layout`, `sidebar`,
`main`, `section-head`, `table-wrap`, `btn`, `input`, `notice`, and `modal`.

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
