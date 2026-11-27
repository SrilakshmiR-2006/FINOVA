/* Shared helpers: toasts, flashes, password UI, money + date formatting, API calls. */
(function () {
  const csrf = (document.querySelector('meta[name="csrf"]') || {}).content;

  window.toast = function (msg, kind) {
    const box = document.getElementById('toasts');
    if (!box) return;
    const el = document.createElement('div');
    el.className = 'toast ' + (kind || '');
    el.textContent = msg;
    box.appendChild(el);
    setTimeout(() => { el.style.transition = 'opacity .3s'; el.style.opacity = '0'; }, 3500);
    setTimeout(() => el.remove(), 3900);
  };

  (window.__FLASH__ || []).forEach(([cat, msg]) => toast(msg, cat === 'error' ? 'error' : cat === 'success' ? 'success' : ''));

  window.api = async function (method, url, body) {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'finova' },
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'same-origin',
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (res.status === 401) { location.href = '/auth'; throw new Error('Not signed in'); }
    if (!res.ok) throw new Error((data && data.error) || 'Something went wrong');
    return data;
  };

  /* ---- currency: amounts are stored in USD and shown in the user's chosen currency ---- */
  const C = window.__CURRENCY__ || { code: 'USD', rates: { USD: 1 } };
  const rate = Number(C.rates[C.code]) || 1;
  window.CUR = { code: C.code, rate, live: !!C.live, symbol: (0).toLocaleString('en', { style: 'currency', currency: C.code, maximumFractionDigits: 0 }).replace(/[\d\s.,]/g, '') };
  const loc = C.code === 'INR' ? 'en-IN' : 'en-US';
  const fmt = new Intl.NumberFormat(loc, { style: 'currency', currency: C.code });
  const fmtShort = new Intl.NumberFormat(loc, { style: 'currency', currency: C.code, notation: 'compact', maximumFractionDigits: 1 });
  window.formatMoney = n => fmt.format(Number(n) * rate);          // USD -> display currency
  window.formatMoneyShort = n => fmtShort.format(Number(n) * rate);
  window.toBase = v => Number(v) / rate;                            // display currency -> USD
  window.fromBase = v => Math.round(Number(v) * rate * 100) / 100;  // USD -> display (for edit fields)
  document.querySelectorAll('[data-cur-sym]').forEach(el => el.textContent = CUR.symbol || CUR.code);
  document.querySelectorAll('[data-cur-code]').forEach(el => el.textContent = CUR.code);
  const sel = document.getElementById('currency-select');
  if (sel) sel.addEventListener('change', async () => {
    try { await api('POST', '/api/currency', { currency: sel.value }); location.reload(); }
    catch (e) { toast(e.message, 'error'); }
  });

  window.toISODate = function (d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  };
  window.parseISODate = function (s) {
    const [y, m, d] = s.split('-').map(Number);
    return new Date(y, m - 1, d);
  };
  window.escapeHtml = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ---- finance rules (mirror of finance.py) ---- */
  window.PASSWORD_RULES = {
    len: p => p.length >= 8,
    upper: p => /[A-Z]/.test(p),
    lower: p => /[a-z]/.test(p),
    num: p => /\d/.test(p),
    special: p => /[^A-Za-z0-9]/.test(p),
  };
  window.totals = function (txns) {
    const t = { income: 0, expense: 0, saving: 0 };
    txns.forEach(x => { t[x.type] += Number(x.amount); });
    return t;
  };
  window.financeScore = function (t, goalPct) {
    if (t.income <= 0) return 0;
    const goal = Math.max(goalPct, 1) / 100;
    const clamp = n => Math.min(1, Math.max(0, n));
    const kept = (t.income - t.expense) / t.income;
    return Math.round(clamp(kept / goal) * 60 + clamp(1 - t.expense / t.income) * 25 + clamp(t.saving / (t.income * goal)) * 15);
  };
  window.scoreLabel = s => s >= 80 ? 'Excellent' : s >= 60 ? 'Good' : s >= 40 ? 'Fair' : 'Needs care';
  window.ageFromDob = function (dob) {
    if (!dob) return null;
    const d = parseISODate(dob), t = new Date();
    let age = t.getFullYear() - d.getFullYear();
    const m = t.getMonth() - d.getMonth();
    if (m < 0 || (m === 0 && t.getDate() < d.getDate())) age--;
    return age >= 0 ? age : null;
  };

  /* ---- password show/hide ---- */
  document.querySelectorAll('[data-toggle-pw]').forEach(btn => btn.addEventListener('click', () => {
    const inp = document.getElementById(btn.dataset.togglePw);
    const show = inp.type === 'password';
    inp.type = show ? 'text' : 'password';
    btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    btn.style.color = show ? 'var(--primary)' : '';
  }));

  /* ---- password checklist + submit gating ---- */
  window.FinovaPasswordForm = function (o) {
    const pw = document.querySelector(o.password), cf = document.querySelector(o.confirm), btn = document.querySelector(o.button);
    const list = document.getElementById('pw-checklist');
    function update() {
      let all = true;
      list.querySelectorAll('li').forEach(li => {
        const id = li.dataset.rule;
        const ok = id === 'match' ? (pw.value.length > 0 && pw.value === cf.value) : PASSWORD_RULES[id](pw.value);
        li.classList.toggle('ok', ok);
        li.querySelector('.dot').textContent = ok ? '✓' : '✕';
        if (!ok) all = false;
      });
      btn.disabled = !all;
    }
    pw.addEventListener('input', update);
    cf.addEventListener('input', update);
    update();
  };

  /* ---- social sign-in placeholder (needs OAuth credentials) ---- */
  document.querySelectorAll('[data-social]').forEach(b => b.addEventListener('click', () =>
    toast('Google sign-in needs OAuth credentials. Use email + password locally.', '')));
})();
