// ── Settings Page Logic ──

function initSettings(pets) {
    var sel = document.getElementById('set-pet');
    sel.innerHTML = '';
    (pets || []).forEach(function(p) {
        var opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.display_name || p.id;
        if (p.selected) opt.selected = true;
        sel.appendChild(opt);
    });
}

function setSettingsValues(cfg) {
    document.getElementById('set-scale').value = cfg.ui_scale || 40;
    document.getElementById('scale-label').textContent = cfg.ui_scale || 40;
    document.getElementById('set-theme').value = cfg.theme || 'dark';
    if (cfg.tavily_api_key) document.getElementById('set-tavily').value = cfg.tavily_api_key || '';
}

function submitSettings() {
    var data = {
        pet_id: document.getElementById('set-pet').value,
        ui_scale: parseInt(document.getElementById('set-scale').value),
        theme: document.getElementById('set-theme').value,
        tavily_api_key: document.getElementById('set-tavily').value,
    };
    window.pywebview.api.on_save(JSON.stringify(data));
}

function closeSettings() {
    window.pywebview.api.on_close();
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme || 'dark');
}

// Notify Python when ready, then hide
function _notifyReady() {
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.on_ready();
    } else {
        setTimeout(_notifyReady, 100);
    }
}
if (document.readyState === 'complete') {
    _notifyReady();
} else {
    window.addEventListener('load', _notifyReady);
}

// ESC to close
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { closeSettings(); }
});
