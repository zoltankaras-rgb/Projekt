// =================================================================
// === SUB-MODUL KANCELÁRIA: HACCP ===
// =================================================================
let activeTinyMceEditor = null;
function initializeHaccpModule() {
  const container = document.getElementById('section-haccp');
  if (!container) return;

  container.innerHTML = `
    <h3>Správa HACCP Dokumentácie</h3>
    <div style="display:flex; gap:2rem;">
      <div style="flex:1;">
        <h4>Dokumenty</h4>
        <ul id="haccp-doc-list" class="sidebar-nav"><li>Načítavam...</li></ul>
        <button id="add-new-haccp-doc-btn" class="btn btn-success" style="width:100%; margin-top:.5rem;">
          <i class="fas fa-plus"></i> Nový Dokument
        </button>
        <div style="margin-top:1rem;">
          <input type="file" id="haccp-import-input" accept=".docx" style="display:none;">
          <button id="haccp-import-btn" class="btn btn-secondary" style="width:100%;">
            <i class="fas fa-file-import"></i> Import DOCX
          </button>
        </div>
      </div>

      <div style="flex:3;">
        <div class="form-group" style="display:flex; gap:.5rem; align-items:center;">
          <label for="haccp-doc-title" style="min-width:140px;">Názov dokumentu</label>
          <input type="text" id="haccp-doc-title">
          <input type="hidden" id="haccp-doc-id">
          <div style="margin-left:auto; display:flex; gap:.5rem;">
            <button id="haccp-export-btn" class="btn btn-primary" disabled>
              <i class="fas fa-file-export"></i> Export DOCX
            </button>
            <button id="haccp-export-original-btn" class="btn btn-soft" disabled>
              Originál DOCX
            </button>
          </div>
        </div>

        <textarea id="haccp-editor"></textarea>
        <button id="save-haccp-doc-btn" class="btn btn-primary" style="margin-top:1rem;">
          <i class="fas fa-save"></i> Uložiť Dokument
        </button>
      </div>
    </div>
  `;

  const docList = container.querySelector('#haccp-doc-list');
  const titleEl = container.querySelector('#haccp-doc-title');
  const idEl    = container.querySelector('#haccp-doc-id');
  const btnSave = container.querySelector('#save-haccp-doc-btn');
  const btnNew  = container.querySelector('#add-new-haccp-doc-btn');
  const btnImp  = container.querySelector('#haccp-import-btn');
  const inpImp  = container.querySelector('#haccp-import-input');
  const btnExp  = container.querySelector('#haccp-export-btn');
  const btnExpOrig = container.querySelector('#haccp-export-original-btn');

  // ===== Editor
  const ensureEditor = (content) => {
    if (window.activeTinyMceEditor) {
      window.activeTinyMceEditor.setContent(content || '');
      return;
    }
    tinymce.init({
      selector: '#haccp-editor',
      plugins: 'anchor autolink charmap codesample emoticons image link lists media searchreplace table visualblocks wordcount',
      toolbar: 'undo redo | blocks fontfamily fontsize | bold italic underline | align | link image | numlist bullist indent outdent | removeformat',
      height: 520,
      setup: (editor) => {
        editor.on('init', () => {
          editor.setContent(content || '');
          window.activeTinyMceEditor = editor;
        });
      }
    });
  };

  // ===== Načítanie zoznamu
  const loadDocs = async () => {
    const docs = await apiRequest('/api/kancelaria/getHaccpDocs');
    docList.innerHTML = '';
    if (docs && docs.length) {
      docs.forEach(doc => {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = '#';
        a.textContent = doc.title;
        a.dataset.id = doc.id;
        a.onclick = async (e) => {
          e.preventDefault();
          docList.querySelectorAll('a').forEach(x => x.classList.remove('active'));
          a.classList.add('active');

          const data = await apiRequest('/api/kancelaria/getHaccpDocContent', {
            method:'POST', body:{ id: doc.id }
          });
          titleEl.value = data.title || '';
          idEl.value    = data.id || '';
          ensureEditor(data.content || '');

          // enable export (máme otvorený dokument)
          btnExp.disabled = !data.id;
          // originál docx len ak existuje v attachments
          const hasOrig = data.attachments && data.attachments.original_docx;
          btnExpOrig.disabled = !hasOrig;
          btnExpOrig.dataset.url = hasOrig ? data.attachments.original_docx : '';
        };
        li.appendChild(a);
        docList.appendChild(li);
      });
      // auto-otvor prvý
      docList.querySelector('a')?.click();
    } else {
      docList.innerHTML = '<li>Žiadne dokumenty.</li>';
      titleEl.value = '';
      idEl.value = '';
      ensureEditor('');
      btnExp.disabled = true;
      btnExpOrig.disabled = true;
    }
  };

  // ===== Nový dokument (prázdny)
  btnNew.onclick = () => {
    docList.querySelectorAll('a').forEach(x => x.classList.remove('active'));
    titleEl.value = 'Nový HACCP dokument';
    idEl.value = '';
    ensureEditor('');
    btnExp.disabled = true;
    btnExpOrig.disabled = true;
  };

  // ===== Uložiť dokument
  btnSave.onclick = async () => {
    const title = titleEl.value.trim();
    const id    = idEl.value || null;
    const content = window.activeTinyMceEditor ? window.activeTinyMceEditor.getContent() : '';
    if (!title) { alert('Názov je povinný.'); return; }

    const res = await apiRequest('/api/kancelaria/saveHaccpDoc', {
      method:'POST', body:{ id, title, content }
    });
    if (res && res.doc && res.doc.id) {
      idEl.value = res.doc.id;
    }
    await loadDocs();
  };

  // ===== Import DOCX
  btnImp.onclick = () => inpImp.click();
  inpImp.onchange = async (e) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    if (!/\.docx$/i.test(f.name)) { alert('Nahraj súbor vo formáte .docx'); return; }
    const fd = new FormData();
    fd.append('file', f);
    // optional: fd.append('title', 'HACCP – ' + f.name.replace(/\.docx$/i,''));
    const res = await fetch('/api/kancelaria/haccp/import_docx', { method:'POST', body: fd });
    const data = await res.json().catch(()=>({error:'Chybná odpoveď servera.'}));
    if (!res.ok || data.error) { alert(data.error || 'Import zlyhal.'); return; }
    await loadDocs();
  };

  // ===== Export DOCX (z aktuálne otvoreného)
  btnExp.onclick = () => {
    const id = idEl.value;
    if (!id) return;
    window.open(`/api/kancelaria/haccp/export_docx?id=${encodeURIComponent(id)}`, '_blank');
  };

  // ===== Stiahnuť originál (ak vznikol importom)
  btnExpOrig.onclick = () => {
    const id = idEl.value;
    if (!id) return;
    // použijeme parameter use_original=1 (ak originál existuje, route vráti originál)
    window.open(`/api/kancelaria/haccp/export_docx?id=${encodeURIComponent(id)}&use_original=1`, '_blank');
  };

  // štart
  ensureEditor('');
  loadDocs();
}

function resetHaccpEditor() { 
    document.getElementById('haccp-doc-id').value = ''; 
    document.getElementById('haccp-doc-title').value = 'Nový dokument'; 
    initializeTinyMceEditor(''); 
}

async function loadHaccpDoc(docId) { 
    try { 
        const doc = await apiRequest('/api/kancelaria/getHaccpDocContent', { method: 'POST', body: { id: docId } }); 
        document.getElementById('haccp-doc-id').value = doc.id; 
        document.getElementById('haccp-doc-title').value = doc.title; 
        initializeTinyMceEditor(doc.content || ''); 
    } catch (e) { 
        showStatus('Nepodarilo sa načítať obsah dokumentu.', true); 
    } 
}

async function saveHaccpDoc() { 
    const data = { 
        id: document.getElementById('haccp-doc-id').value || null, 
        title: document.getElementById('haccp-doc-title').value, 
        content: activeTinyMceEditor ? activeTinyMceEditor.getContent() : '' 
    }; 
    if (!data.title) return showStatus('Názov dokumentu je povinný.', true); 
    try { 
        await apiRequest('/api/kancelaria/saveHaccpDoc', { method: 'POST', body: data }); 
        initializeHaccpModule(); 
    } catch (e) { } 
}

function initializeTinyMceEditor(content) { 
    if (tinymce.get('haccp-editor')) { 
        tinymce.remove('#haccp-editor'); 
    } 
    tinymce.init({ 
        selector: '#haccp-editor', 
        plugins: 'anchor autolink charmap codesample emoticons image link lists media searchreplace table visualblocks wordcount', 
        toolbar: 'undo redo | blocks fontfamily fontsize | bold italic underline strikethrough | link image media table | align lineheight | numlist bullist indent outdent | emoticons charmap | removeformat', 
        height: 500, 
        setup: editor => { 
            editor.on('init', () => { 
                editor.setContent(content || ''); 
                activeTinyMceEditor = editor; 
            }); 
        } 
    }); 
}
