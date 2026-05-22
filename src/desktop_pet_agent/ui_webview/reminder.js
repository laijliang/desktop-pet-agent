// ── Reminder Page Logic ──

function setPresetTime(minutes) {
    var d = new Date();
    if (minutes === 'tomorrow') {
        d.setDate(d.getDate() + 1);
        d.setHours(9, 0, 0, 0);
    } else {
        d.setMinutes(d.getMinutes() + minutes);
    }
    document.getElementById('rem-due').value = d.toISOString().slice(0, 16);
}

function initReminder() {
    setPresetTime(60);
    document.getElementById('rem-title').focus();
}

function submitReminder() {
    var title = document.getElementById('rem-title').value.trim();
    if (!title) { return; }
    var data = {
        title: title,
        due_at: document.getElementById('rem-due').value,
        message: document.getElementById('rem-msg').value.trim(),
    };
    window.pywebview.api.on_submit(JSON.stringify(data));
}

function closeReminder() {
    window.pywebview.api.on_close();
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

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme || 'dark');
}

// ESC to close
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { closeReminder(); }
    if (e.key === 'Enter' && e.ctrlKey) { submitReminder(); }
});
