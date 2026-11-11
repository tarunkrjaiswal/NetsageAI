/**
 * app.js — NetSage AI client-side interactions
 */

/* ── Analyze form: loading spinner ───────────────────────────────────────── */
(function () {
  const form = document.getElementById('analyze-form');
  const btn  = document.getElementById('analyze-btn');
  if (form && btn) {
    form.addEventListener('submit', function (e) {
      // Basic validation
      const symptom     = document.getElementById('symptom');
      const show_output = document.getElementById('show_output');
      const category    = document.getElementById('category');

      if (!symptom.value.trim() || !show_output.value.trim() || !category.value) {
        return; // Let browser handle required validation
      }
      btn.classList.add('btn-loading');
      btn.disabled = true;
    });
  }
})();

/* ── Confidence bar: animate on load ─────────────────────────────────────── */
(function () {
  const fill = document.getElementById('conf-fill');
  if (!fill) return;
  // Width is set via CSS class (.conf-high / .conf-medium / .conf-low),
  // but we animate from 0 for a nice enter effect.
  fill.style.width = '0%';
  requestAnimationFrame(() => {
    setTimeout(() => { fill.style.width = ''; }, 100);
  });
})();

/* ── Flash auto-dismiss ───────────────────────────────────────────────────── */
(function () {
  const flashes = document.querySelectorAll('.flash');
  flashes.forEach(function (el) {
    setTimeout(function () {
      el.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
      el.style.opacity = '0';
      el.style.transform = 'translateY(-8px)';
      setTimeout(() => el.remove(), 400);
    }, 4500);
  });
})();

/* ── Keyboard shortcut: Ctrl+Enter submits the analyze form ─────────────── */
document.addEventListener('keydown', function (e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    const form = document.getElementById('analyze-form');
    if (form) form.requestSubmit();
  }
});

/* ── Smooth scroll to rule-checker section when conflict banner is present ── */
(function () {
  const banner = document.querySelector('.conflict-banner');
  if (banner && window.location.pathname.startsWith('/diagnosis')) {
    setTimeout(() => banner.scrollIntoView({ behavior: 'smooth', block: 'center' }), 600);
  }
})();

/* ── Copy-to-clipboard for next command ──────────────────────────────────── */
(function () {
  const cmdEl = document.querySelector('.next-cmd');
  if (!cmdEl) return;
  cmdEl.style.cursor = 'pointer';
  cmdEl.title = 'Click to copy command';
  cmdEl.addEventListener('click', function () {
    const text = cmdEl.textContent.replace(/^\$\s*/, '').trim();
    navigator.clipboard.writeText(text).then(() => {
      const orig = cmdEl.innerHTML;
      cmdEl.innerHTML = '<span>✅</span><span>Copied!</span>';
      setTimeout(() => { cmdEl.innerHTML = orig; }, 1500);
    }).catch(() => {});
  });
})();

/* ── Table row hover highlight (cases page) ──────────────────────────────── */
(function () {
  document.querySelectorAll('.data-table tbody tr[onclick]').forEach(row => {
    row.addEventListener('mouseenter', () => row.style.background = 'rgba(0,212,255,0.04)');
    row.addEventListener('mouseleave', () => row.style.background = '');
  });
})();
