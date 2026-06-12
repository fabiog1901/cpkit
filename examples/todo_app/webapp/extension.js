(function () {
  window.cpkitWebappExtension = {
    htmlPath: "/app/extension.html",
    navItems: [{ view: "todos", label: "Todos" }],
    dashboardEnsure: "ensureTodosDashboard",
    routes: {
      todos: {
        path: "/todos",
        label: "Todos",
        subtitle: "Manage example app tasks",
        ensure: "ensureTodosView",
      },
    },
    state: {
      todos: [],
      todosVisibleRows: [],
      todosFilterQuery: "",
      todosIncludeCompleted: true,
      todosLastUpdatedUtc: null,
      todosSortIndex: 3,
      todosSortDir: "desc",
      todosLoading: { list: false, save: false, delete: false, export: false },
      todosToast: { message: "", ok: true },
      _todosToastTimer: null,
      modal: {
        todoEditor: {
          open: false,
          todo_id: null,
          title: "",
          notes: "",
          completed: false,
        },
      },
    },
    methods: {
      async ensureTodosDashboard({ onlyIfEmpty = false } = {}) {
        if (onlyIfEmpty && this.todos.length > 0) return;
        if (!this.todosLoading.list) await this.refreshTodos();
      },

      async ensureTodosView() {
        if (!this.todosLoading.list) await this.refreshTodos();
      },

      async refreshTodos() {
        this.todosLoading.list = true;
        try {
          const data = await this.apiFetch(
            `/todos/?include_completed=${this.todosIncludeCompleted ? "true" : "false"}`,
            { method: "GET" },
          );
          this.todos = Array.isArray(data) ? data : [];
          this.todosLastUpdatedUtc = this.utcNowString();
          this.applyTodosFilterSort();
        } catch (e) {
          this.showTodosToast(this.errorMessage(e, "Failed to load TODOs."), false);
        } finally {
          this.todosLoading.list = false;
        }
      },

      openTodoModal(todo = null) {
        this.modal.todoEditor = {
          open: true,
          todo_id: todo?.todo_id || null,
          title: todo?.title || "",
          notes: todo?.notes || "",
          completed: Boolean(todo?.completed),
        };
        this.modalError.todoEditor = "";
      },

      closeTodoModal() {
        this.modal.todoEditor.open = false;
        this.modalError.todoEditor = "";
      },

      async saveTodo() {
        const draft = this.modal.todoEditor;
        const title = String(draft.title || "").trim();
        if (!title) {
          this.modalError.todoEditor = "Title is required.";
          return;
        }

        this.todosLoading.save = true;
        this.modalError.todoEditor = "";
        try {
          if (draft.todo_id) {
            await this.apiFetch(`/todos/${encodeURIComponent(draft.todo_id)}`, {
              method: "PATCH",
              body: {
                title,
                notes: draft.notes || null,
                completed: Boolean(draft.completed),
              },
            });
            this.showTodosToast("Task updated.", true);
          } else {
            await this.apiFetch("/todos/", {
              method: "POST",
              body: {
                title,
                notes: draft.notes || null,
              },
            });
            this.showTodosToast("Task created.", true);
          }
          this.closeTodoModal();
          await this.refreshTodos();
        } catch (e) {
          this.modalError.todoEditor = this.errorMessage(e, "Failed to save task.");
        } finally {
          this.todosLoading.save = false;
        }
      },

      async deleteTodo(todo) {
        if (!window.confirm(`Delete task ${todo.todo_id}?`)) return;
        this.todosLoading.delete = true;
        try {
          await this.apiFetch(`/todos/${encodeURIComponent(todo.todo_id)}`, {
            method: "DELETE",
          });
          this.showTodosToast("Task deleted.", true);
          await this.refreshTodos();
        } catch (e) {
          this.showTodosToast(this.errorMessage(e, "Failed to delete task."), false);
        } finally {
          this.todosLoading.delete = false;
        }
      },

      async exportTodos() {
        this.todosLoading.export = true;
        try {
          const data = await this.apiFetch("/todos/export", {
            method: "POST",
            body: {
              format: "json",
              include_completed: this.todosIncludeCompleted,
              output_dir: "exports",
            },
          });
          this.showTodosToast(`Export job ${data.job_id} queued.`, true);
          this.viewNotice = `Export job ${data.job_id} queued.`;
          this.viewNoticeJobId = String(data.job_id || "");
        } catch (e) {
          this.showTodosToast(this.errorMessage(e, "Failed to export tasks."), false);
        } finally {
          this.todosLoading.export = false;
        }
      },

      todosCellText(todo, index) {
        return [
          String(todo.todo_id || ""),
          todo.title,
          todo.completed ? "completed" : "open",
          todo.updated_at,
        ][index] ?? "";
      },

      todosRowText(todo) {
        return [0, 1, 2, 3]
          .map((idx) => String(this.todosCellText(todo, idx)))
          .concat([String(todo.notes || "")])
          .join(" ")
          .toLowerCase();
      },

      sortTodos(index) {
        if (this.todosSortIndex === index) {
          this.todosSortDir = this.todosSortDir === "asc" ? "desc" : "asc";
        } else {
          this.todosSortIndex = index;
          this.todosSortDir = index === 0 || index === 3 ? "desc" : "asc";
        }
        this.applyTodosFilterSort();
      },

      todosSortClass(index) {
        if (this.todosSortIndex !== index) return "";
        return this.todosSortDir === "asc" ? "sort-asc" : "sort-desc";
      },

      compareTodosValues(a, b, index) {
        if (index === 0) return String(a || "").localeCompare(String(b || ""));
        return this.compareValues(a, b);
      },

      applyTodosFilterSort() {
        const q = String(this.todosFilterQuery || "").toLowerCase().trim();
        let rows = this.todos.slice();
        if (q) rows = rows.filter((todo) => this.todosRowText(todo).includes(q));
        rows.sort((a, b) =>
          this.compareTodosValues(
            this.todosCellText(a, this.todosSortIndex),
            this.todosCellText(b, this.todosSortIndex),
            this.todosSortIndex,
          ),
        );
        if (this.todosSortDir === "desc") rows.reverse();
        this.todosVisibleRows = rows;
      },

      showTodosToast(message, ok) {
        if (this._todosToastTimer) clearTimeout(this._todosToastTimer);
        this.todosToast = { message, ok };
        this._todosToastTimer = setTimeout(() => {
          this.todosToast = { message: "", ok: true };
        }, 4000);
      },
    },
  };
})();
