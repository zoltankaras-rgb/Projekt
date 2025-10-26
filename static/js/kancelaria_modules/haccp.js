// =================================================================
// === SUB-MODUL KANCELÁRIA: HACCP ===
// =================================================================

function initializeHaccpModule() {
    const container = document.getElementById('section-haccp');
    if (!container) return;
    container.innerHTML = `
        <h3>Správa HACCP Dokumentácie</h3>
        <div style="display: flex; gap: 2rem;">
            <div style="flex: 1;">
                <h4>Dokumenty</h4>
                <ul id="haccp-doc-list" class="sidebar-nav"><li>Načítavam...</li></ul>
                <button id="add-new-haccp-doc-btn" class="btn-success" style="width: 100%;"><i class="fas fa-plus"></i> Nový Dokument</button>
            </div>
            <div style="flex: 3;">
                <div class="form-group"><label for="haccp-doc-title">Názov Dokumentu</label><input type="text" id="haccp-doc-title"></div>
                <input type="hidden" id="haccp-doc-id">
                <textarea id="haccp-editor"></textarea>
                <button id="save-haccp-doc-btn" class="btn-primary" style="width: 100%; margin-top: 1rem;"><i class="fas fa-save"></i> Uložiť Dokument</button>
            </div>
        </div>
    `;
    const docList = document.getElementById('haccp-doc-list');
    try {
        const loadDocs = async () => {
            const docs = await apiRequest('/api/kancelaria/getHaccpDocs');
            docList.innerHTML = '';
            if (docs && docs.length > 0) { 
                docs.forEach(doc => { 
                    const li = document.createElement('li'); 
                    const a = document.createElement('a'); 
                    a.href = "#"; 
                    a.textContent = doc.title; 
                    a.dataset.id = doc.id; 
                    a.onclick = (e) => { 
                        e.preventDefault(); 
                        docList.querySelectorAll('a').forEach(link => link.classList.remove('active')); 
                        a.classList.add('active'); 
                        loadHaccpDoc(doc.id); 
                    }; 
                    li.appendChild(a); 
                    docList.appendChild(li); 
                }); 
                docList.querySelector('a').click(); 
            } else { 
                docList.innerHTML = '<li>Žiadne dokumenty.</li>'; 
                resetHaccpEditor(); 
            }
        };
        loadDocs();
        document.getElementById('add-new-haccp-doc-btn').onclick = () => { 
            resetHaccpEditor(); 
            docList.querySelectorAll('a').forEach(link => link.classList.remove('active')); 
        };
        document.getElementById('save-haccp-doc-btn').onclick = saveHaccpDoc;
    } catch (e) { 
        docList.innerHTML = `<li class="error">Chyba načítania: ${e.message}</li>`; 
    }
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
