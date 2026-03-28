/* ============================================================
   NEUROFLOW — app.js
   Dashboard interactions + accessibility toggles
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {

  const TASKS_STORAGE_KEY = 'nf-task-state-v1';

  /* ── Theme ── */
  const html = document.documentElement;
  const savedTheme = localStorage.getItem('nf-theme') || 'light';
  html.setAttribute('data-theme', savedTheme);

  /* ── Toggle helper ── */
  function initToggle(id, onActivate, onDeactivate) {
    const el = document.getElementById(id);
    if (!el) return;

    // Restore saved state
    const saved = localStorage.getItem(`nf-${id}`) === 'true';
    if (saved) {
      el.setAttribute('aria-checked', 'true');
      onActivate();
    }

    function toggle() {
      const active = el.getAttribute('aria-checked') === 'true';
      el.setAttribute('aria-checked', String(!active));
      localStorage.setItem(`nf-${id}`, String(!active));
      if (!active) onActivate(); else onDeactivate();
    }

    el.addEventListener('click', toggle);
    el.addEventListener('keydown', e => {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(); }
    });
  }

  /* ── Dark mode ── */
  initToggle(
    'toggle-dark',
    () => { html.setAttribute('data-theme', 'dark');  localStorage.setItem('nf-theme', 'dark');  },
    () => { html.setAttribute('data-theme', 'light'); localStorage.setItem('nf-theme', 'light'); }
  );
  // Sync toggle UI to saved theme on load
  if (savedTheme === 'dark') {
    const el = document.getElementById('toggle-dark');
    if (el) el.setAttribute('aria-checked', 'true');
  }

  /* ── OpenDyslexic ── */
  initToggle(
    'toggle-dyslexic',
    () => document.body.classList.add('a11y-dyslexic'),
    () => document.body.classList.remove('a11y-dyslexic')
  );

  /* ── Focus mode ── */
  initToggle(
    'toggle-focus',
    () => document.body.classList.add('a11y-focus'),
    () => document.body.classList.remove('a11y-focus')
  );

  /* ── Extra spacing ── */
  initToggle(
    'toggle-spacing',
    () => document.body.classList.add('a11y-spacing'),
    () => document.body.classList.remove('a11y-spacing')
  );

  /* ── Screen navigation (dashboard/tasks/profile/achievements) ── */
  const screens = {
    dashboard: document.getElementById('screen-dashboard'),
    tasks: document.getElementById('screen-tasks'),
    profile: document.getElementById('screen-profile'),
    achievements: document.getElementById('screen-achievements')
  };

  const sidebarToggle = document.getElementById('sidebar-toggle');
  const savedSidebarCollapsed = localStorage.getItem('nf-sidebar-collapsed') === 'true';

  function setSidebarCollapsed(collapsed) {
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    localStorage.setItem('nf-sidebar-collapsed', String(collapsed));
    if (sidebarToggle) {
      const expanded = !collapsed;
      sidebarToggle.setAttribute('aria-expanded', String(expanded));
      sidebarToggle.setAttribute('aria-label', expanded ? 'Close navigation menu' : 'Open navigation menu');
    }
  }

  setSidebarCollapsed(savedSidebarCollapsed);

  if (sidebarToggle) {
    sidebarToggle.addEventListener('click', () => {
      const isCollapsed = document.body.classList.contains('sidebar-collapsed');
      setSidebarCollapsed(!isCollapsed);
    });
  }

  function showScreen(screenName) {
    if (!screens[screenName]) return;

    Object.values(screens).forEach(screen => {
      if (!screen) return;
      screen.hidden = true;
    });

    screens[screenName].hidden = false;

    document.querySelectorAll('.nav-link').forEach(link => {
      const isActive = link.dataset.screen === screenName;
      link.classList.toggle('nav-link--active', isActive);
      if (isActive) {
        link.setAttribute('aria-current', 'page');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  }

  document.querySelectorAll('[data-screen]').forEach(link => {
    link.addEventListener('click', e => {
      const screenName = link.dataset.screen;
      if (!screenName || !screens[screenName]) return;
      e.preventDefault();
      showScreen(screenName);
    });
  });

  // Ensure the dashboard starts visible if no hash-based navigation is present.
  showScreen('dashboard');

  function generateId(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function createInitialTaskState() {
    return {
      lists: [{ id: 'list-general', name: 'General' }],
      tasks: []
    };
  }

  function loadTaskState() {
    try {
      const raw = localStorage.getItem(TASKS_STORAGE_KEY);
      if (!raw) return createInitialTaskState();
      const parsed = JSON.parse(raw);
      if (!parsed || !Array.isArray(parsed.lists) || !Array.isArray(parsed.tasks)) {
        return createInitialTaskState();
      }
      if (!parsed.lists.length) {
        parsed.lists.push({ id: 'list-general', name: 'General' });
      }
      return parsed;
    } catch (error) {
      return createInitialTaskState();
    }
  }

  function saveTaskState() {
    localStorage.setItem(TASKS_STORAGE_KEY, JSON.stringify(taskState));
  }

  let taskState = loadTaskState();
  let pendingSubtasks = [];

  const createListForm = document.getElementById('create-list-form');
  const createTaskForm = document.getElementById('create-task-form');
  const listNameInput = document.getElementById('new-list-name');
  const taskTitleInput = document.getElementById('task-title');
  const taskListSelect = document.getElementById('task-list-select');
  const taskNotesInput = document.getElementById('task-notes');
  const newSubtaskTitleInput = document.getElementById('new-subtask-title');
  const addSubtaskBtn = document.getElementById('add-subtask-btn');
  const newSubtaskList = document.getElementById('new-subtask-list');
  const taskLists = document.getElementById('task-lists');
  const taskBoard = document.getElementById('task-board');
  const tasksEmptyState = document.getElementById('tasks-empty-state');
  const recentTaskList = document.getElementById('task-list');

  function getListNameById(listId) {
    const list = taskState.lists.find(item => item.id === listId);
    return list ? list.name : 'General';
  }

  function countCompletedTasks() {
    return taskState.tasks.filter(task => task.done).length;
  }

  function updateTaskStatCounter() {
    const statTasks = document.getElementById('stat-tasks');
    if (!statTasks) return;
    statTasks.textContent = String(countCompletedTasks());
  }

  function renderDraftSubtasks() {
    if (!newSubtaskList) return;
    if (!pendingSubtasks.length) {
      newSubtaskList.innerHTML = '';
      return;
    }

    newSubtaskList.innerHTML = pendingSubtasks
      .map((subtask, index) => (
        `<li class="subtask-draft-item">
          <span>${escapeHtml(subtask.title)}</span>
          <button type="button" class="task-action-btn" data-action="remove-draft-subtask" data-index="${index}">Remove</button>
        </li>`
      ))
      .join('');
  }

  function renderListControls() {
    if (taskListSelect) {
      const previouslySelected = taskListSelect.value;
      taskListSelect.innerHTML = taskState.lists
        .map(list => `<option value="${list.id}">${escapeHtml(list.name)}</option>`)
        .join('');
      if (previouslySelected && taskState.lists.some(list => list.id === previouslySelected)) {
        taskListSelect.value = previouslySelected;
      }
    }

    if (taskLists) {
      taskLists.innerHTML = taskState.lists
        .map(list => `<span class="list-chip" role="listitem">${escapeHtml(list.name)}</span>`)
        .join('');
    }
  }

  function renderTaskBoard() {
    if (!taskBoard) return;

    if (!taskState.tasks.length) {
      taskBoard.innerHTML = '';
      if (tasksEmptyState) tasksEmptyState.hidden = false;
      return;
    }

    if (tasksEmptyState) tasksEmptyState.hidden = true;

    taskBoard.innerHTML = taskState.tasks
      .slice()
      .sort((a, b) => b.createdAt - a.createdAt)
      .map(task => {
        const completedSubtasks = task.subtasks.filter(subtask => subtask.done).length;
        const subtaskProgress = task.subtasks.length
          ? `${completedSubtasks}/${task.subtasks.length} subtasks`
          : 'No subtasks';

        return `<li class="task-item ${task.done ? 'task-item--done' : 'task-item--active'}" role="listitem" data-task-id="${task.id}">
          <div class="task-item__status" aria-label="${task.done ? 'Completed' : 'In progress'}">
            <span class="status-dot ${task.done ? 'status-dot--done' : 'status-dot--active'}" aria-hidden="true"></span>
          </div>
          <div class="task-item__body">
            <div class="task-item__title-row">
              <label class="task-checkbox-label">
                <input type="checkbox" data-action="toggle-task" ${task.done ? 'checked' : ''} />
                <span class="task-item__title">${escapeHtml(task.title)}</span>
              </label>
              <button type="button" class="task-action-btn" data-action="delete-task">Delete</button>
            </div>
            <p class="task-item__meta">${task.done ? 'Completed' : 'In progress'} · ${escapeHtml(subtaskProgress)} · <span class="tag tag--sky">${escapeHtml(getListNameById(task.listId))}</span></p>
            ${task.notes ? `<p class="task-note">${escapeHtml(task.notes)}</p>` : ''}
            <ul class="task-subtask-list">
              ${task.subtasks.map(subtask => `
                <li class="task-subtask-item">
                  <label class="task-checkbox-label">
                    <input type="checkbox" data-action="toggle-subtask" data-subtask-id="${subtask.id}" ${subtask.done ? 'checked' : ''} />
                    <span class="task-subtask-title ${subtask.done ? 'task-subtask-title--done' : ''}">${escapeHtml(subtask.title)}</span>
                  </label>
                </li>
              `).join('')}
            </ul>
            <div class="task-inline-row task-inline-row--subtask">
              <input class="task-input task-input--inline" type="text" placeholder="Add subtask" data-role="subtask-input" maxlength="120" />
              <button type="button" class="btn" data-action="add-subtask">Add</button>
            </div>
          </div>
        </li>`;
      })
      .join('');
  }

  function renderRecentTasks() {
    if (!recentTaskList) return;

    if (!taskState.tasks.length) {
      recentTaskList.innerHTML = '<li class="task-item" role="listitem"><div class="task-item__body"><p class="task-item__title">No tasks yet</p><p class="task-item__meta">Create your first task in New Task.</p></div></li>';
      return;
    }

    recentTaskList.innerHTML = taskState.tasks
      .slice()
      .sort((a, b) => b.createdAt - a.createdAt)
      .slice(0, 4)
      .map(task => {
        const completedSubtasks = task.subtasks.filter(subtask => subtask.done).length;
        return `<li class="task-item ${task.done ? 'task-item--done' : 'task-item--active'}" role="listitem">
          <div class="task-item__status" aria-label="${task.done ? 'Completed' : 'In progress'}">
            <span class="status-dot ${task.done ? 'status-dot--done' : 'status-dot--active'}" aria-hidden="true"></span>
          </div>
          <div class="task-item__body">
            <p class="task-item__title">${escapeHtml(task.title)}</p>
            <p class="task-item__meta">${task.done ? 'Completed' : 'In progress'} · ${completedSubtasks}/${task.subtasks.length} subtasks · <span class="tag tag--sky">${escapeHtml(getListNameById(task.listId))}</span></p>
          </div>
        </li>`;
      })
      .join('');
  }

  function renderTaskUi() {
    renderListControls();
    renderDraftSubtasks();
    renderTaskBoard();
    renderRecentTasks();
    updateTaskStatCounter();
  }

  function addPendingSubtask() {
    if (!newSubtaskTitleInput) return;
    const title = newSubtaskTitleInput.value.trim();
    if (!title) return;
    pendingSubtasks.push({ id: generateId('draft-subtask'), title, done: false });
    newSubtaskTitleInput.value = '';
    renderDraftSubtasks();
  }

  if (addSubtaskBtn) {
    addSubtaskBtn.addEventListener('click', addPendingSubtask);
  }

  if (newSubtaskTitleInput) {
    newSubtaskTitleInput.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        addPendingSubtask();
      }
    });
  }

  if (newSubtaskList) {
    newSubtaskList.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.dataset.action !== 'remove-draft-subtask') return;

      const index = Number(target.dataset.index);
      if (Number.isNaN(index)) return;
      pendingSubtasks = pendingSubtasks.filter((_, itemIndex) => itemIndex !== index);
      renderDraftSubtasks();
    });
  }

  if (createListForm) {
    createListForm.addEventListener('submit', event => {
      event.preventDefault();
      if (!listNameInput) return;

      const name = listNameInput.value.trim();
      if (!name) return;

      const exists = taskState.lists.some(list => list.name.toLowerCase() === name.toLowerCase());
      if (exists) {
        listNameInput.focus();
        return;
      }

      const list = { id: generateId('list'), name };
      taskState.lists.push(list);
      saveTaskState();
      renderTaskUi();
      if (taskListSelect) taskListSelect.value = list.id;
      listNameInput.value = '';
    });
  }

  if (createTaskForm) {
    createTaskForm.addEventListener('submit', event => {
      event.preventDefault();
      if (!taskTitleInput || !taskListSelect) return;

      const title = taskTitleInput.value.trim();
      if (!title) return;

      const task = {
        id: generateId('task'),
        title,
        notes: taskNotesInput ? taskNotesInput.value.trim() : '',
        listId: taskListSelect.value,
        done: false,
        createdAt: Date.now(),
        subtasks: pendingSubtasks.map(subtask => ({
          id: generateId('subtask'),
          title: subtask.title,
          done: false
        }))
      };

      taskState.tasks.push(task);
      saveTaskState();

      createTaskForm.reset();
      pendingSubtasks = [];
      renderTaskUi();
      taskTitleInput.focus();
    });
  }

  if (taskBoard) {
    taskBoard.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;

      const item = target.closest('[data-task-id]');
      if (!item) return;
      const taskId = item.getAttribute('data-task-id');
      if (!taskId) return;

      const task = taskState.tasks.find(entry => entry.id === taskId);
      if (!task) return;

      if (target.dataset.action === 'delete-task') {
        taskState.tasks = taskState.tasks.filter(entry => entry.id !== taskId);
      }

      if (target.dataset.action === 'add-subtask') {
        const input = item.querySelector('[data-role="subtask-input"]');
        if (input instanceof HTMLInputElement) {
          const title = input.value.trim();
          if (title) {
            task.subtasks.push({ id: generateId('subtask'), title, done: false });
            input.value = '';
          }
        }
      }

      saveTaskState();
      renderTaskUi();
    });

    taskBoard.addEventListener('keydown', event => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (target.dataset.role !== 'subtask-input' || event.key !== 'Enter') return;

      event.preventDefault();
      const item = target.closest('[data-task-id]');
      if (!item) return;
      const taskId = item.getAttribute('data-task-id');
      if (!taskId) return;

      const task = taskState.tasks.find(entry => entry.id === taskId);
      const title = target.value.trim();
      if (!task || !title) return;

      task.subtasks.push({ id: generateId('subtask'), title, done: false });
      target.value = '';
      saveTaskState();
      renderTaskUi();
    });

    taskBoard.addEventListener('change', event => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;

      const item = target.closest('[data-task-id]');
      if (!item) return;
      const taskId = item.getAttribute('data-task-id');
      if (!taskId) return;

      const task = taskState.tasks.find(entry => entry.id === taskId);
      if (!task) return;

      if (target.dataset.action === 'toggle-task') {
        task.done = target.checked;
      }

      if (target.dataset.action === 'toggle-subtask') {
        const subtask = task.subtasks.find(entry => entry.id === target.dataset.subtaskId);
        if (subtask) {
          subtask.done = target.checked;
          const hasSubtasks = task.subtasks.length > 0;
          task.done = hasSubtasks && task.subtasks.every(entry => entry.done);
        }
      }

      saveTaskState();
      renderTaskUi();
    });
  }

  renderTaskUi();

  /* ── Animate progress bar on load ── */
  const progressFill = document.getElementById('level-progress');
  if (progressFill) {
    // Start at 0, animate to target
    const target = progressFill.style.getPropertyValue('--progress') || '76%';
    progressFill.style.setProperty('--progress', '0%');
    requestAnimationFrame(() => {
      setTimeout(() => {
        progressFill.style.setProperty('--progress', target);
      }, 200);
    });
  }

  /* ── XP counter animation ── */
  function animateCount(el, target, suffix = '') {
    if (!el) return;
    const duration = 900;
    const start = performance.now();
    const from = 0;
    const to = parseInt(target.replace(/,/g, ''), 10);

    function step(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // ease out
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = Math.round(from + (to - from) * eased);
      el.textContent = value.toLocaleString() + suffix;
      if (progress < 1) requestAnimationFrame(step);
    }

    requestAnimationFrame(step);
  }

  // Small delay so animation is visible after page load
  setTimeout(() => {
    animateCount(document.getElementById('stat-xp'),     '1240');
    animateCount(document.getElementById('stat-streak'),  '5');
    animateCount(document.getElementById('stat-tasks'),   String(countCompletedTasks()));
    animateCount(document.getElementById('stat-badges'),  '4');
  }, 300);

});