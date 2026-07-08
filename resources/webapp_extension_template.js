// Minimal cpkit webapp extension template.
//
// Copy this file to an application's webapp/extension.js and replace the TODO
// examples with app-specific routes, state, and methods. Do not define
// window.app; cpkit owns the shell.

window.cpkitWebappExtension = {
  htmlPath: "/app/extension.html",

  navItems: [
    { view: "todos", label: "TODOs" },
  ],

  adminItems: [
    {
      view: "todo_admin",
      label: "TODO Admin",
      kicker: "Application",
      description: "Manage TODO app settings.",
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
      window.location.hash = `/todos/${encodeURIComponent(this.selectedTodoId)}`;
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
