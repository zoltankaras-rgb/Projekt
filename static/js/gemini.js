// static/js/gemini.js
document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  // ---- Stabilné ID konverzácie (drž kontext medzi správami) ----
  const conversationId = (() => {
    let id = localStorage.getItem('geminiSessionId');
    if (!id) {
      id = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
      localStorage.setItem('geminiSessionId', id);
    }
    return id;
  })();

  // ---- Zisti, či je app zobrazená (widget iba po prihlásení) ----
  function isHidden(el) {
    if (!el) return true;
    const s = getComputedStyle(el);
    return s.display === 'none' || s.visibility === 'hidden' || el.classList.contains('hidden');
  }
  function isAppVisible() {
    const app   = document.getElementById('app-container');
    const login = document.getElementById('login-wrapper');
    return app && !isHidden(app) && (!login || isHidden(login));
  }

  // ---- API wrapper (použi apiRequest, inak fetch JSON) ----
  function apiReq(url, opts) {
    if (typeof window.apiRequest === 'function') return window.apiRequest(url, opts || {});
    opts = opts || {};
    const body = opts.body ? JSON.stringify(opts.body) : undefined;
    return fetch(url, {
      method: opts.method || 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body
    }).then(r => r.json());
  }

  // ---- Uzamkni polohu vpravo dole (prebij aj agresívne CSS) ----
  function lockRight(fab, panel) {
    if (fab) {
      fab.style.setProperty('position', 'fixed', 'important');
      fab.style.setProperty('inset', 'auto 20px 20px auto', 'important');
      fab.style.setProperty('right', '20px', 'important');
      fab.style.setProperty('left', 'auto', 'important');
      fab.style.setProperty('bottom', '20px', 'important');
      fab.style.margin = '0';
    }
    if (panel) {
      panel.style.setProperty('position', 'fixed', 'important');
      panel.style.setProperty('inset', 'auto 20px 80px auto', 'important');
      panel.style.setProperty('right', '20px', 'important');
      panel.style.setProperty('left', 'auto', 'important');
      panel.style.setProperty('bottom', '80px', 'important');
      panel.style.margin = '0';
    }
  }

  // ---- Stav + UI referencie ----
  let styleEl = null, fab = null, panel = null, msgs = null, ta = null, send = null;
  const history = [];
  let sending = false;

  // ---- Vytvor UI (len po prihlásení) ----
  function buildUI() {
    if (document.getElementById('gemini-fab')) return;

    // CSS (vzhľad + tabuľky + SQL block + tlačidlá akcií)
    const css = `
      #gemini-panel .ai-meta{margin:.35rem 0 .5rem 0; font-weight:700}
      #gemini-panel .ai-table-wrap{max-height:52vh; overflow:auto; border:1px solid #eee; border-radius:10px}
      #gemini-panel .ai-table{width:100%; border-collapse:collapse; font-size:12.8px}
      #gemini-panel .ai-table thead th{position:sticky; top:0; background:#f8fafc; z-index:1}
      #gemini-panel .ai-table th, #gemini-panel .ai-table td{padding:6px 8px; border-bottom:1px solid #eee; text-align:left; white-space:nowrap}
      #gemini-panel .ai-table td.num{text-align:right}
      #gemini-panel .ai-sql summary{cursor:pointer; margin-top:.5rem; font-weight:600}
      #gemini-panel .ai-sql pre{background:#0b1020; color:#e5e7eb; padding:.5rem .7rem; border-radius:8px; overflow:auto; white-space:pre}
      #gemini-panel .ai-warn{background:#fff7ed; border:1px solid #fdba74; color:#7c2d12; padding:.5rem .6rem; border-radius:8px; margin:.4rem 0}
      #gemini-panel .ai-actions{display:flex; gap:.5rem; margin-top:.5rem}
      #gemini-panel .ai-btn{background:#2563eb; color:#fff; border:0; border-radius:10px; padding:.45rem .65rem; cursor:pointer}
      #gemini-panel .ai-btn.secondary{background:#e2e8f0; color:#111827}
      #gemini-panel .ai-btn[disabled]{opacity:.65; cursor:not-allowed}

      #gemini-fab{
        z-index:10000; display:flex; align-items:center; gap:.5rem;
        background:#2563eb; color:#fff; border:0; border-radius:9999px;
        padding:.6rem .9rem; cursor:pointer; box-shadow:0 8px 24px rgba(0,0,0,.18);
        font-family:inherit; font-weight:600;
      }
      #gemini-fab i{font-size:16px}
      #gemini-panel{
        width:360px; max-height:65vh; background:#fff; border:1px solid #e5e7eb; border-radius:12px;
        box-shadow:0 12px 28px rgba(0,0,0,.18); display:none; flex-direction:column; overflow:hidden; z-index:10000;
      }
      #gemini-head{padding:.6rem .8rem; border-bottom:1px solid #eee; background:#f8fafc; font-weight:700}
      #gemini-msgs{padding:.7rem; overflow:auto; flex:1}
      .gm-msg{margin:.35rem 0; max-width:85%}
      .gm-user{margin-left:auto; background:#ecfeff; border:1px solid #bae6fd; border-radius:12px 12px 0 12px; padding:.45rem .55rem}
      .gm-bot{margin-right:auto; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:12px 12px 12px 0; padding:.45rem .55rem}
      #gemini-input{display:flex; gap:.4rem; padding:.6rem; border-top:1px solid #eee}
      #gemini-input textarea{flex:1; resize:none; height:52px; padding:.5rem; border:1px solid #e5e7eb; border-radius:10px}
      #gemini-send{background:#2563eb; color:#fff; border:none; border-radius:10px; padding:.5rem .7rem; cursor:pointer}
      #gemini-send[disabled]{opacity:.65; cursor:not-allowed}
      #gemini-typing{font-size:12px; color:#6b7280; margin:.2rem 0 .1rem 0}
    `;
    styleEl = document.createElement('style');
    styleEl.id = 'gemini-style';
    styleEl.textContent = css;
    document.head.appendChild(styleEl);

    // FAB
    fab = document.createElement('button');
    fab.id = 'gemini-fab';
    fab.innerHTML = '<i class="fas fa-robot"></i> Asistent Gemini';
    document.body.appendChild(fab);

    // Panel
    panel = document.createElement('div');
    panel.id = 'gemini-panel';
    panel.innerHTML = `
      <div id="gemini-head">Dobrý deň, som virtuálny asistent spoločnosti Mik s.r.o.</div>
      <div id="gemini-msgs"></div>
      <div id="gemini-input">
        <textarea id="gemini-text" placeholder="Opýtajte sa na čokoľvek z ERP… (Shift+Enter = nový riadok)"></textarea>
        <button id="gemini-send" title="Odoslať (Enter)"> <i class="fas fa-paper-plane"></i> </button>
      </div>`;
    document.body.appendChild(panel);

    // Refs + pozícia
    msgs = panel.querySelector('#gemini-msgs');
    ta   = panel.querySelector('#gemini-text');
    send = panel.querySelector('#gemini-send');
    lockRight(fab, panel);

    // Render správy
    function addMsg(text, who) {
      const d = document.createElement('div');
      d.className = 'gm-msg ' + (who === 'user' ? 'gm-user' : 'gm-bot');
      d.textContent = String(text || '');
      msgs.appendChild(d);
      msgs.scrollTop = msgs.scrollHeight;
      return d;
    }
    function addMsgHtml(html) {
      const d = document.createElement('div');
      d.className = 'gm-msg gm-bot';
      d.innerHTML = html;
      msgs.appendChild(d);
      msgs.scrollTop = msgs.scrollHeight;
      return d;
    }
    function addTyping() {
      const t = document.createElement('div');
      t.id = 'gemini-typing';
      t.textContent = 'Asistent píše…';
      msgs.appendChild(t);
      msgs.scrollTop = msgs.scrollHeight;
      return t;
    }

    // Blok s akciami (napr. Potvrdiť zápis)
    function addActions(actions = []) {
      if (!actions.length) return null;
      const wrap = document.createElement('div');
      wrap.className = 'gm-msg gm-bot';
      const inner = document.createElement('div');
      inner.className = 'ai-actions';
      actions.forEach(a => inner.appendChild(a));
      wrap.appendChild(inner);
      msgs.appendChild(wrap);
      msgs.scrollTop = msgs.scrollHeight;
      return wrap;
    }
    function makeBtn(label, {variant='primary', onClick, disabled=false} = {}) {
      const b = document.createElement('button');
      b.className = 'ai-btn' + (variant === 'secondary' ? ' secondary' : '');
      b.textContent = label;
      if (disabled) b.setAttribute('disabled', 'true');
      b.onclick = onClick;
      return b;
    }

    // Odošle otázku na backend
    async function ask() {
      if (sending) return;
      const q = (ta.value || '').trim(); if (!q) return;
      ta.value = '';
      sending = true;
      ta.setAttribute('disabled', 'true');
      send.setAttribute('disabled', 'true');

      addMsg(q, 'user');
      const typingEl = addTyping();

      try {
        const body = { question: q, history, conversation_id: conversationId };
        const res  = await apiReq('/api/gemini/agent', { method:'POST', body });

        // odstráň "píše…"
        if (typingEl && typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);

        const ans  = (res && res.answer) ? String(res.answer) : '';
        const ansH = (res && res.answer_html) ? String(res.answer_html) : '';
        const err  = (res && res.error) ? String(res.error) : '';

        if (ansH) addMsgHtml(ansH);
        else if (ans) addMsg(ans, 'bot');
        else if (err) addMsg('Chyba: ' + err, 'bot');
        else addMsg('Nemám odpoveď.', 'bot');

        // História
        history.push({ role:'user', content:q }, { role:'assistant', content: ansH ? '[html]' : (ans || err) });

        // --- Podpora potvrdenia zápisu (pending_write) ---
        if (res && res.pending_write && res.pending_write.sql) {
          // upozornenie
          addMsgHtml(`<div class="ai-warn"><b>POZOR:</b> Asistent navrhol <i>zápis do databázy</i>. Pred vykonaním je potrebné potvrdenie.</div>`);
          // tlačidlá
          const confirmBtn = makeBtn('Potvrdiť vykonanie SQL zápisu', {
            onClick: async () => {
              confirmBtn.setAttribute('disabled', 'true');
              try {
                const res2 = await apiReq('/api/gemini/agent', {
                  method: 'POST',
                  body: { question: q, history, conversation_id: conversationId, confirm: true }
                });
                const ans2  = (res2 && res2.answer) ? String(res2.answer) : '';
                const ans2H = (res2 && res2.answer_html) ? String(res2.answer_html) : '';
                const err2  = (res2 && res2.error) ? String(res2.error) : '';
                if (ans2H) addMsgHtml(ans2H);
                else if (ans2) addMsg(ans2, 'bot');
                else if (err2) addMsg('Chyba: ' + err2, 'bot');
                else addMsg('Hotovo.', 'bot');
                history.push({ role:'assistant', content: ans2H ? '[html]' : (ans2 || err2 || 'OK') });
              } catch (e) {
                addMsg('Chyba pri potvrdzovaní zápisu.', 'bot');
              } finally {
                // nechávame tlačidlo disabled, aby sa to nespúšťalo viackrát
              }
            }
          });
          addActions([confirmBtn]);
        }

      } catch (e) {
        if (typingEl && typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);
        addMsg('Chyba pri volaní asistenta.', 'bot');
      } finally {
        sending = false;
        ta.removeAttribute('disabled');
        send.removeAttribute('disabled');
        ta.focus();
      }
    }

    // Handlery
    fab.onclick = () => {
      panel.style.display = (panel.style.display === 'flex' ? 'none' : 'flex');
      lockRight(fab, panel); // poistka po toggli
      if (panel.style.display === 'flex' && !msgs.childElementCount) {
        addMsg('Dobrý deň, som virtuálny asistent spoločnosti Mik s.r.o. Rád vám pomôžem s vašimi požiadavkami.', 'bot');
      }
    };
    send.onclick = ask;
    ta.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); }
    });
    window.addEventListener('resize', () => lockRight(fab, panel));
    window.addEventListener('scroll', () => lockRight(fab, panel));
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && panel && panel.style.display === 'flex') {
        panel.style.display = 'none';
      }
    });

    // Keď sa používateľ odhlási, UI zmizne
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('#logout-button');
      if (btn) setTimeout(sync, 100);
    });
  }

  // ---- Zruš UI (pri logine) ----
  function destroyUI() {
    try {
      const f = document.getElementById('gemini-fab');
      const p = document.getElementById('gemini-panel');
      if (f && f.parentNode) f.parentNode.removeChild(f);
      if (p && p.parentNode) p.parentNode.removeChild(p);
      const st = document.getElementById('gemini-style');
      if (st && st.parentNode) st.parentNode.removeChild(st);
    } catch (_) {}
    styleEl = fab = panel = msgs = ta = send = null;
    history.length = 0;
  }

  // ---- Toggle podľa stavu app/login ----
  function sync() {
    if (isAppVisible()) buildUI(); else destroyUI();
  }

  // Spusti a krátko polluj pri prepínaní login/app
  sync();
  let n = 0;
  const t = setInterval(() => { sync(); if (++n > 40) clearInterval(t); }, 200);
});
