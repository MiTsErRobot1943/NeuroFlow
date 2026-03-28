/* ============================================================
   NEUROFLOW — app.js
   Dashboard interactions + accessibility toggles + task/chat APIs
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  const html = document.documentElement;
  const savedTheme = localStorage.getItem('nf-theme') || 'light';
  html.setAttribute('data-theme', savedTheme);

  const state = {
    username: 'User',
    csrfToken: '',
    lists: [],
    tasks: [],
    chatHistory: []
  };

  function getCsrfToken() {
    return state.csrfToken || (document.querySelector('meta[name="csrf-token"]')?.content || '');
  }

  async function apiFetch(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (!headers.has('Content-Type') && options.body) {
      headers.set('Content-Type', 'application/json');
    }
    const csrf = getCsrfToken();
    if (csrf) {
      headers.set('X-CSRF-Token', csrf);
    }

    const response = await fetch(path, {
      credentials: 'same-origin',
      ...options,
      headers
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `Request failed (${response.status})`);
    }
    return payload;
  }

  function initToggle(id, onActivate, onDeactivate) {
    const el = document.getElementById(id);
    if (!el) return;

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
      if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        toggle();
      }
    });
  }

  initToggle(
    'toggle-dark',
    () => { html.setAttribute('data-theme', 'dark'); localStorage.setItem('nf-theme', 'dark'); },
    () => { html.setAttribute('data-theme', 'light'); localStorage.setItem('nf-theme', 'light'); }
  );

  if (savedTheme === 'dark') {
    const el = document.getElementById('toggle-dark');
    if (el) el.setAttribute('aria-checked', 'true');
  }

  initToggle(
    'toggle-dyslexic',
    () => document.body.classList.add('a11y-dyslexic'),
    () => document.body.classList.remove('a11y-dyslexic')
  );
  initToggle(
    'toggle-focus',
    () => document.body.classList.add('a11y-focus'),
    () => document.body.classList.remove('a11y-focus')
  );
  initToggle(
    'toggle-spacing',
    () => document.body.classList.add('a11y-spacing'),
    () => document.body.classList.remove('a11y-spacing')
  );

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
      if (screen) screen.hidden = true;
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
  const projectTemplateButtons = Array.from(document.querySelectorAll('.project-template-btn'));
  const openProjectConfigBtn = document.getElementById('open-project-config-btn');
  const projectConfigSection = document.getElementById('project-config-section');
  const projectConfigForm = document.getElementById('project-config-form');

  const chatbotPanels = Array.from(document.querySelectorAll('.chatbot-panel'));

  function getListNameById(listId) {
    const list = state.lists.find(item => Number(item.id) === Number(listId));
    return list ? list.name : 'General';
  }

  function countCompletedTasks() {
    return state.tasks.filter(task => task.done).length;
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
      taskListSelect.innerHTML = state.lists
        .map(list => `<option value="${list.id}">${escapeHtml(list.name)}</option>`)
        .join('');
      if (previouslySelected && state.lists.some(list => String(list.id) === previouslySelected)) {
        taskListSelect.value = previouslySelected;
      }
    }

    if (taskLists) {
      taskLists.innerHTML = state.lists
        .map(list => `<span class="list-chip" role="listitem">${escapeHtml(list.name)}</span>`)
        .join('');
    }
  }

  function renderTaskBoard() {
    if (!taskBoard) return;

    if (!state.tasks.length) {
      taskBoard.innerHTML = '';
      if (tasksEmptyState) tasksEmptyState.hidden = false;
      return;
    }

    if (tasksEmptyState) tasksEmptyState.hidden = true;

    taskBoard.innerHTML = state.tasks
      .slice()
      .sort((a, b) => Number(b.id) - Number(a.id))
      .map(task => {
        const completedSubtasks = (task.subtasks || []).filter(subtask => subtask.done).length;
        const totalSubtasks = (task.subtasks || []).length;
        const subtaskProgress = totalSubtasks ? `${completedSubtasks}/${totalSubtasks} subtasks` : 'No subtasks';

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
            <p class="task-item__meta">${task.done ? 'Completed' : 'In progress'} · ${escapeHtml(subtaskProgress)} · <span class="tag tag--sky">${escapeHtml(task.list_name || getListNameById(task.list_id))}</span> ${task.source === 'chatbot' ? '<span class="tag tag--mint">AI</span>' : ''}</p>
            ${task.notes ? `<p class="task-note">${escapeHtml(task.notes)}</p>` : ''}
            <ul class="task-subtask-list">
              ${(task.subtasks || []).map(subtask => `
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

    if (!state.tasks.length) {
      recentTaskList.innerHTML = '<li class="task-item" role="listitem"><div class="task-item__body"><p class="task-item__title">No tasks yet</p><p class="task-item__meta">Create your first task in New Task.</p></div></li>';
      return;
    }

    recentTaskList.innerHTML = state.tasks
      .slice()
      .sort((a, b) => Number(b.id) - Number(a.id))
      .slice(0, 4)
      .map(task => {
        const completedSubtasks = (task.subtasks || []).filter(subtask => subtask.done).length;
        const totalSubtasks = (task.subtasks || []).length;
        return `<li class="task-item ${task.done ? 'task-item--done' : 'task-item--active'}" role="listitem">
          <div class="task-item__status" aria-label="${task.done ? 'Completed' : 'In progress'}">
            <span class="status-dot ${task.done ? 'status-dot--done' : 'status-dot--active'}" aria-hidden="true"></span>
          </div>
          <div class="task-item__body">
            <p class="task-item__title">${escapeHtml(task.title)}</p>
            <p class="task-item__meta">${task.done ? 'Completed' : 'In progress'} · ${completedSubtasks}/${totalSubtasks} subtasks · <span class="tag tag--sky">${escapeHtml(task.list_name || getListNameById(task.list_id))}</span></p>
          </div>
        </li>`;
      })
      .join('');
  }

  function renderChatPanels() {
    chatbotPanels.forEach(panel => {
      const messagesEl = panel.querySelector('[data-chatbot-messages]');
      if (!messagesEl) return;

      messagesEl.innerHTML = state.chatHistory
        .map(item => `<div class="chatbot-message chatbot-message--${item.role}">${escapeHtml(item.message)}</div>`)
        .join('');
      messagesEl.scrollTop = messagesEl.scrollHeight;
    });
  }

  function renderTaskUi() {
    renderListControls();
    renderDraftSubtasks();
    renderTaskBoard();
    renderRecentTasks();
    renderChatPanels();
    updateTaskStatCounter();
  }

  function upsertTask(task) {
    const idx = state.tasks.findIndex(item => Number(item.id) === Number(task.id));
    if (idx >= 0) {
      state.tasks[idx] = task;
    } else {
      state.tasks.push(task);
    }
  }

  async function refreshTaskData() {
    const payload = await apiFetch('/api/tasks');
    state.lists = payload.lists || [];
    state.tasks = payload.tasks || [];
    renderTaskUi();
  }

  async function bootstrap() {
    const payload = await apiFetch('/api/bootstrap');
    state.username = payload.username || 'User';
    state.csrfToken = payload.csrf_token || state.csrfToken;
    state.lists = payload.lists || [];
    state.tasks = payload.tasks || [];
    state.chatHistory = payload.chat_history || [];
    renderTaskUi();
  }

  function addPendingSubtask() {
    if (!newSubtaskTitleInput) return;
    const title = newSubtaskTitleInput.value.trim();
    if (!title) return;
    pendingSubtasks.push({ id: generateId('draft-subtask'), title });
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
    createListForm.addEventListener('submit', async event => {
      event.preventDefault();
      if (!listNameInput) return;

      const name = listNameInput.value.trim();
      if (!name) return;

      try {
        const payload = await apiFetch('/api/lists', {
          method: 'POST',
          body: JSON.stringify({ name })
        });
        state.lists = [...state.lists.filter(item => Number(item.id) !== Number(payload.list.id)), payload.list];
        state.lists.sort((a, b) => Number(a.id) - Number(b.id));
        renderTaskUi();
        if (taskListSelect) taskListSelect.value = String(payload.list.id);
        listNameInput.value = '';
      } catch (error) {
        window.alert(error.message);
      }
    });
  }

  if (createTaskForm) {
    createTaskForm.addEventListener('submit', async event => {
      event.preventDefault();
      if (!taskTitleInput || !taskListSelect) return;

      const title = taskTitleInput.value.trim();
      if (!title) return;

      try {
        const payload = await apiFetch('/api/tasks', {
          method: 'POST',
          body: JSON.stringify({
            title,
            notes: taskNotesInput ? taskNotesInput.value.trim() : '',
            list_id: Number(taskListSelect.value),
            subtasks: pendingSubtasks.map(item => item.title),
            source: 'manual'
          })
        });

        upsertTask(payload.task);
        createTaskForm.reset();
        pendingSubtasks = [];
        renderTaskUi();
        taskTitleInput.focus();
      } catch (error) {
        window.alert(error.message);
      }
    });
  }

  if (taskBoard) {
    taskBoard.addEventListener('click', async event => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;

      const item = target.closest('[data-task-id]');
      if (!item) return;
      const taskId = Number(item.getAttribute('data-task-id'));
      if (!taskId) return;

      try {
        if (target.dataset.action === 'delete-task') {
          await apiFetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
          state.tasks = state.tasks.filter(entry => Number(entry.id) !== taskId);
        }

        if (target.dataset.action === 'add-subtask') {
          const input = item.querySelector('[data-role="subtask-input"]');
          if (input instanceof HTMLInputElement) {
            const title = input.value.trim();
            if (title) {
              await apiFetch(`/api/tasks/${taskId}/subtasks`, {
                method: 'POST',
                body: JSON.stringify({ title })
              });
              input.value = '';
              await refreshTaskData();
              return;
            }
          }
        }

        renderTaskUi();
      } catch (error) {
        window.alert(error.message);
      }
    });

    taskBoard.addEventListener('keydown', async event => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (target.dataset.role !== 'subtask-input' || event.key !== 'Enter') return;

      event.preventDefault();
      const item = target.closest('[data-task-id]');
      if (!item) return;
      const taskId = Number(item.getAttribute('data-task-id'));
      const title = target.value.trim();
      if (!taskId || !title) return;

      try {
        await apiFetch(`/api/tasks/${taskId}/subtasks`, {
          method: 'POST',
          body: JSON.stringify({ title })
        });
        target.value = '';
        await refreshTaskData();
      } catch (error) {
        window.alert(error.message);
      }
    });

    taskBoard.addEventListener('change', async event => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;

      const item = target.closest('[data-task-id]');
      if (!item) return;
      const taskId = Number(item.getAttribute('data-task-id'));
      if (!taskId) return;

      try {
        if (target.dataset.action === 'toggle-task') {
          const payload = await apiFetch(`/api/tasks/${taskId}/done`, {
            method: 'POST',
            body: JSON.stringify({ done: target.checked })
          });
          upsertTask(payload.task);
        }

        if (target.dataset.action === 'toggle-subtask') {
          const subtaskId = Number(target.dataset.subtaskId);
          if (!subtaskId) return;
          const payload = await apiFetch(`/api/subtasks/${subtaskId}/done`, {
            method: 'POST',
            body: JSON.stringify({ done: target.checked })
          });
          upsertTask(payload.task);
        }

        renderTaskUi();
      } catch (error) {
        window.alert(error.message);
      }
    });
  }

  projectTemplateButtons.forEach(button => {
    button.addEventListener('click', async () => {
      const template = button.dataset.template;
      if (!template) return;

      button.disabled = true;
      try {
        await apiFetch('/api/projects/predefined', {
          method: 'POST',
          body: JSON.stringify({ template })
        });
        await refreshTaskData();
      } catch (error) {
        window.alert(error.message);
      } finally {
        button.disabled = false;
      }
    });
  });

  if (openProjectConfigBtn && projectConfigSection) {
    openProjectConfigBtn.addEventListener('click', () => {
      projectConfigSection.hidden = false;
      projectConfigSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  if (projectConfigForm) {
    projectConfigForm.addEventListener('submit', async event => {
      event.preventDefault();

      const payload = {
        project_name: String(document.getElementById('project-name')?.value || '').trim(),
        web_experience: String(document.getElementById('experience-web')?.value || 'beginner'),
        desktop_experience: String(document.getElementById('experience-desktop')?.value || 'beginner'),
        architecture_experience: String(document.getElementById('experience-architecture')?.value || 'beginner'),
        database_experience: String(document.getElementById('experience-database')?.value || 'beginner'),
        notes: String(document.getElementById('project-config-notes')?.value || '').trim()
      };

      try {
        await apiFetch('/api/projects/configure', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        projectConfigForm.reset();
        await refreshTaskData();
      } catch (error) {
        window.alert(error.message);
      }
    });
  }

  async function sendChatbotMessage(panel, message) {
    const messagesEl = panel.querySelector('[data-chatbot-messages]');
    if (!messagesEl) return;

    const userBubble = document.createElement('div');
    userBubble.className = 'chatbot-message chatbot-message--user';
    userBubble.textContent = message;
    messagesEl.appendChild(userBubble);

    const loadingBubble = document.createElement('div');
    loadingBubble.className = 'chatbot-message chatbot-message--loading';
    loadingBubble.innerHTML = 'Working on it <span class="chatbot-loading-dots"><span></span><span></span><span></span></span>';
    messagesEl.appendChild(loadingBubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
      const profilePayload = {
        web_experience: String(document.getElementById('experience-web')?.value || 'beginner'),
        desktop_experience: String(document.getElementById('experience-desktop')?.value || 'beginner'),
        architecture_experience: String(document.getElementById('experience-architecture')?.value || 'beginner'),
        database_experience: String(document.getElementById('experience-database')?.value || 'beginner')
      };

      const payload = await apiFetch('/api/chatbot', {
        method: 'POST',
        body: JSON.stringify({ message, profile: profilePayload })
      });

      state.chatHistory.push({ role: 'user', message });
      state.chatHistory.push({ role: 'assistant', message: payload.response?.message || 'Done.' });

      if (payload.created_task) {
        upsertTask(payload.created_task);
      }
      await refreshTaskData();
    } catch (error) {
      state.chatHistory.push({ role: 'assistant', message: `Error: ${error.message}` });
    } finally {
      loadingBubble.remove();
      renderChatPanels();
    }
  }

  chatbotPanels.forEach(panel => {
    const form = panel.querySelector('[data-chatbot-form]');
    const input = panel.querySelector('[data-chatbot-input]');
    if (!form || !(input instanceof HTMLInputElement)) return;

    form.addEventListener('submit', async event => {
      event.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      input.value = '';
      await sendChatbotMessage(panel, message);
    });
  });

  const progressFill = document.getElementById('level-progress');
  if (progressFill) {
    const target = progressFill.style.getPropertyValue('--progress') || '76%';
    progressFill.style.setProperty('--progress', '0%');
    requestAnimationFrame(() => {
      setTimeout(() => {
        progressFill.style.setProperty('--progress', target);
      }, 200);
    });
  }

  function animateCount(el, target, suffix = '') {
    if (!el) return;
    const duration = 900;
    const start = performance.now();
    const from = 0;
    const to = parseInt(String(target).replace(/,/g, ''), 10) || 0;

    function step(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = Math.round(from + (to - from) * eased);
      el.textContent = value.toLocaleString() + suffix;
      if (progress < 1) requestAnimationFrame(step);
    }

    requestAnimationFrame(step);
  }

  function animateStats() {
    setTimeout(() => {
      animateCount(document.getElementById('stat-xp'), '1240');
      animateCount(document.getElementById('stat-streak'), '5');
      animateCount(document.getElementById('stat-tasks'), String(countCompletedTasks()));
      animateCount(document.getElementById('stat-badges'), '4');
    }, 300);
  }

  bootstrap()
    .then(animateStats)
    .catch(error => {
      window.console.error('Bootstrap failed:', error);
      renderTaskUi();
      animateStats();
    });
});

