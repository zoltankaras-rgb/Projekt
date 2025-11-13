// =================================================================
// === SUB-MODUL KANCELÁRIA: SMS CONNECTOR (O2/smstools.sk) ========
// =================================================================
(function () {
  window.initializeSMSConnectorModule = function () {
    const section = document.getElementById('section-sms-connector');
    if (!section) return;

    section.innerHTML = `
      <h3>SMS Connector</h3>
      <div class="two-col">
        <div class="card">
          <h4>Správa</h4>
          <label>Odosielateľ (max 11, bez medzier/diakritiky)</label>
          <input id="sms-sender" class="form-control" placeholder="MIK" value="MIK" />
          <label style="margin-top:8px">Text správy</label>
          <textarea id="sms-text" rows="6" class="form-control" placeholder="Sem napíšte text..."></textarea>
          <div class="muted" id="sms-stats" style="margin-top:6px">0 znakov • 0 segmentov</div>
          <label style="display:flex;gap:6px;align-items:center;margin-top:8px">
            <input type="checkbox" id="sms-simple" checked /> Normalizovať text (bez diakritiky)
          </label>
          <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn-secondary" data-tpl="confirm">Tpl: Potvrdenie objednávky</button>
            <button class="btn-secondary" data-tpl="ready">Tpl: Objednávka pripravená</button>
            <button class="btn-secondary" data-tpl="points">Tpl: Vernostné body</button>
          </div>
          <hr>
          <div style="display:flex;gap:6px;align-items:center;">
            <input id="sms-test-number" class="form-control" style="max-width:220px" placeholder="+4219..." />
            <button id="sms-send-test" class="btn-info">Poslať TEST SMS</button>
          </div>
        </div>
        <div class="card">
          <h4>Príjemcovia</h4>
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
            <input id="sms-q" class="form-control" placeholder="Hľadať (meno/e-mail/telefón)">
            <label style="display:flex;gap:6px;align-items:center">
              <input type="checkbox" id="sms-marketing-only" checked> len so súhlasom marketingu
            </label>
            <button id="sms-load" class="btn-primary">Načítať</button>
          </div>
          <div id="sms-rec-count" class="muted"></div>
          <div class="table-container" style="max-height:360px;overflow:auto">
            <table class="table">
              <thead><tr>
                <th><input type="checkbox" id="sms-check-all"></th>
                <th>Meno</th><th>Telefón</th><th>E164</th>
              </tr></thead>
              <tbody id="sms-rec-tbody"><tr><td colspan="4" class="muted">Načítajte príjemcov…</td></tr></tbody>
            </table>
          </div>
          <div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <button id="sms-send" class="btn-success">Odoslať</button>
            <span class="muted" id="sms-send-status"></span>
          </div>
        </div>
      </div>
    `;

    // --- Helpers -------------------------------------------------
    const el = sel => section.querySelector(sel);
    const tArea = el('#sms-text');
    const sStats = el('#sms-stats');

    function sanitizeSender(s) {
      const up = String(s || '').toUpperCase();
      return up.replace(/[^A-Z0-9._-]/g, '').slice(0, 11) || 'MIK';
    }

    function isGsmChar(ch) {
      // hrubý odhad GSM 03.38 (postačuje pre segmentáciu)
      return /^[A-Za-z0-9 @£$¥èéùìòÇ\n\rØøÅåΔ_ΦΓΛΩΠΨΣΘΞ^{}\\[~]|[!"#%&'()*+,.\-\/:;<=>?]*$/.test(ch);
    }

    function stripDiacritics(str) {
      try {
        // moderné prehliadače
        return str.normalize('NFD').replace(/\p{Diacritic}/gu, '');
      } catch {
        // fallback
        return str.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
      }
    }

    function segmentsInfo(txt, normalize) {
      let t = String(txt || '');
      if (normalize) t = stripDiacritics(t);
      let unicode = false;
      for (const ch of t) { if (!isGsmChar(ch)) { unicode = true; break; } }
      const single = unicode ? 70 : 160;
      const concat = unicode ? 67 : 153;
      const len = t.length;
      const segs = len === 0 ? 0 : (len <= single ? 1 : Math.ceil(len / concat));
      const remain = (segs <= 1) ? (single - len) : (segs * concat - len);
      return { len, segs, remain, unicode, text: t };
    }

    function updateStats() {
      const info = segmentsInfo(tArea.value, el('#sms-simple').checked);
      sStats.textContent = `${info.len} znakov • ${info.segs} segmentov ${info.unicode ? '(Unicode)' : '(GSM 03.38)'}`;
    }

    // --- Bindings ------------------------------------------------
    // Odosielateľ – sanitácia vstupu
    el('#sms-sender').addEventListener('input', (e) => {
      const caret = e.target.selectionStart;
      const val = sanitizeSender(e.target.value);
      e.target.value = val;
      try { e.target.setSelectionRange(caret, caret); } catch (_) {}
    });

    // Segmenty
    tArea.addEventListener('input', updateStats);
    el('#sms-simple').addEventListener('change', updateStats);
    updateStats();

    // Šablóny
    section.querySelectorAll('button[data-tpl]').forEach(b => {
      b.onclick = () => {
        const t = b.dataset.tpl;
        if (t === 'confirm') tArea.value = 'Ďakujeme za objednávku {{order_no}}. Suma k úhrade {{amount}} €. Viac v e-maile. MIK.';
        if (t === 'ready')   tArea.value = 'Objednávka {{order_no}} je pripravená na vyzdvihnutie. Ďakujeme, MIK.';
        if (t === 'points')  tArea.value = 'Boli pripísané vernostné body: {{points}}. Ďakujeme za nákup, MIK.';
        updateStats();
      };
    });

    // Načítanie príjemcov
    el('#sms-load').onclick = async () => {
      const q = el('#sms-q').value.trim();
      const mo = el('#sms-marketing-only').checked ? '1' : '0';
      const tbody = el('#sms-rec-tbody');
      const cnt = el('#sms-rec-count');

      tbody.innerHTML = `<tr><td colspan="4" class="muted">Načítavam…</td></tr>`;
      try {
        const data = await apiRequest(`/api/kancelaria/sms/recipients?marketing_only=${mo}&q=${encodeURIComponent(q)}&limit=1000`);
        tbody.innerHTML = '';
        if (!data || data.error || !Array.isArray(data) || data.length === 0) {
          tbody.innerHTML = `<tr><td colspan="4" class="muted">${data && data.error ? escapeHtml(data.error) : 'Nenašli sa žiadni príjemcovia.'}</td></tr>`;
          cnt.textContent = '';
          return;
        }
        cnt.textContent = `Načítaných ${data.length} príjemcov.`;
        for (const r of data) {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td><input type="checkbox" class="sms-chk"></td>
            <td>${escapeHtml(r.name || '')}</td>
            <td>${escapeHtml(r.phone || '')}</td>
            <td>${escapeHtml(r.msisdn || '')}</td>
          `;
          tr.dataset.msisdn = r.msisdn || '';
          tbody.appendChild(tr);
        }
        el('#sms-check-all').checked = false;
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" class="muted">Chyba pri načítaní príjemcov.</td></tr>`;
        cnt.textContent = '';
      }
    };

    // Select all
    el('#sms-check-all').onchange = () => {
      const ok = el('#sms-check-all').checked;
      section.querySelectorAll('.sms-chk').forEach(c => c.checked = ok);
    };

    // Odoslanie
    async function send(toNumbers) {
      const msg = (el('#sms-text').value || '').trim();
      const sender = sanitizeSender(el('#sms-sender').value || 'MIK');
      const simple = !!el('#sms-simple').checked;

      if (!msg) {
        showStatus('Zadajte text správy.', true);
        return;
      }
      if (!Array.isArray(toNumbers) || toNumbers.length === 0) {
        showStatus('Vyberte aspoň jedného príjemcu.', true);
        return;
      }

      const payload = {
        message: msg,
        sender: sender,
        simple_text: simple,
        recipients: toNumbers
      };

      const btn = el('#sms-send');
      const statusEl = el('#sms-send-status');
      if (btn) btn.disabled = true;
      if (statusEl) statusEl.textContent = 'Odosielam…';

      try {
        const res = await apiRequest('/api/kancelaria/sms/send', { method: 'POST', body: payload });
        if (res && !res.error) {
          showStatus(res.message || 'Odoslané.', false);
          if (statusEl) statusEl.textContent = `OK, batch ${res.batch_id}, doručí sa ${(res.accepted || []).length} príjemcom.`;
        } else {
          const m = (res && res.error) ? res.error : 'Odoslanie zlyhalo.';
          showStatus(m, true);
          if (statusEl) statusEl.textContent = m;
        }
      } catch (e) {
        showStatus('Chyba pri odosielaní SMS.', true);
        if (statusEl) statusEl.textContent = 'Chyba pri odosielaní.';
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    // Klik „Odoslať“
    el('#sms-send').onclick = () => {
      const nums = [];
      section.querySelectorAll('#sms-rec-tbody tr').forEach(tr => {
        const chk = tr.querySelector('.sms-chk');
        if (chk && chk.checked && tr.dataset.msisdn) nums.push(tr.dataset.msisdn);
      });
      if (nums.length === 0) { showStatus('Vyberte aspoň jedného príjemcu.', true); return; }
      // rýchlo uvoľniť click handler; samotný POST nech beží async
      setTimeout(() => send(nums), 0);
    };

    // TEST SMS na jedno číslo
    el('#sms-send-test').onclick = () => {
      const n = (el('#sms-test-number').value || '').trim();
      if (!n) { showStatus('Zadajte testovacie číslo.', true); return; }
      setTimeout(() => send([n]), 0);
    };
  };
})();
