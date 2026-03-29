/* ============================================================
   NEUROFLOW — app.js
   Dashboard interactions + accessibility toggles
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {

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
    animateCount(document.getElementById('stat-tasks'),   '18');
    animateCount(document.getElementById('stat-badges'),  '4');
  }, 300);

});