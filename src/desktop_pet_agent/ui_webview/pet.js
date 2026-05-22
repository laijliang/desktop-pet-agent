/* ═══════════════════════════════════════════════════
   Desktop Pet Agent — WebView2 UI Logic
   Animation, drag, bubbles, dialogs, Python bridge
   ═══════════════════════════════════════════════════ */

// ── State ──
let frameIdx = 0;
let animTimer = null;
let status = 'idle';
let paused = false;
let scaleVal = 40;
let showingBubble = null;      // 'reminder' | 'perm' | 'status' | null
let currentReminderId = '';
let currentPermId = '';
const PET_MARGIN = 8;

// ── Sprite Animation ──
function startAnim(frames, tickMs) {
    if (!frames || frames.length === 0) return;
    if (animTimer) clearInterval(animTimer);
    const pet = document.getElementById('pet');
    animTimer = setInterval(() => {
        if (paused) { frameIdx = 0; pet.src = frames[0]; return; }
        frameIdx = (frameIdx + 1) % frames.length;
        if (frames[frameIdx]) pet.src = frames[frameIdx];
    }, tickMs || 180);
}

function stopAnim() {
    if (animTimer) { clearInterval(animTimer); animTimer = null; }
}

// ── Status ──
function setStatus(s) {
    status = s;
    const dot = document.getElementById('status-dot');
    dot.className = '';
    if (s === 'reminding') dot.className = 'reminding';
    else if (s === 'thinking') dot.className = 'thinking';
    else if (s === 'paused' || paused) dot.className = 'paused';
    else dot.className = 'active';
}

function setPaused(p) {
    paused = p;
    const pet = document.getElementById('pet');
    if (p) { pet.classList.add('paused'); } else { pet.classList.remove('paused'); }
    setStatus(p ? 'paused' : 'idle');
}

// ── Scale ──
function setScale(v) {
    scaleVal = v;
    const pet = document.getElementById('pet');
    const frames = pet._frames || [];
    const applySize = (base) => {
        let mult;
        if (base <= 64) {
            mult = 1.0 + v / 100 * 5.0;
        } else {
            mult = 0.3 + v / 100 * 1.2;
        }
        const size = Math.max(48, Math.round(base * mult));
        pet.style.width = size + 'px';
        pet.style.height = size + 'px';

        const dot = document.getElementById('status-dot');
        dot.style.left = (PET_MARGIN + size + 4) + 'px';
        dot.style.top = (PET_MARGIN + size * 0.1) + 'px';
        const dsize = Math.max(6, Math.round(size * 0.1));
        dot.style.width = dsize + 'px';
        dot.style.height = dsize + 'px';
        reportPetSize(size, dsize);
    };

    const naturalBase = Math.max(pet.naturalWidth || 0, pet.naturalHeight || 0);
    if (naturalBase > 0) {
        applySize(naturalBase);
        return;
    }
    if (frames.length > 0) {
        const img = new Image();
        img.onload = () => applySize(Math.max(img.naturalWidth, img.naturalHeight, 32));
        img.src = frames[0];
        return;
    }
    applySize(32);
}

function reportPetSize(size, dotSize) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.on_pet_size) {
        window.pywebview.api.on_pet_size(size, dotSize);
    }
}

// ── Drag ──
// Window movement is delegated to Python because WebView/browser moveTo is unreliable.
function setupDrag() {
    const pet = document.getElementById('pet');
    let dragging = false;

    pet.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        dragging = true;
        window.pywebview.api.on_drag_start(e.screenX, e.screenY);
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        e.preventDefault();
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        window.pywebview.api.on_drag_end(window.screenX, window.screenY);
    });
}

// ── Context Menu ──
function setupContextMenu() {
    document.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        // request pending reminders from Python → populated in updateMenuItems
        window.pywebview.api.on_context_menu(e.clientX, e.clientY);
    });
    document.addEventListener('click', (e) => {
        const menu = document.getElementById('ctx-menu');
        if (menu && menu.style.display === 'block' && !menu.contains(e.target)) {
            hideCtxMenu();
        }
    });
}

function showCtxMenu(x, y, pendingItems) {
    const menu = document.getElementById('ctx-menu');
    // rebuild pending submenu
    const pendingEl = document.getElementById('ctx-pending-items');
    if (pendingEl) {
        if (pendingItems.length === 0) {
            pendingEl.innerHTML = '<div class="ctx-item disabled">(暂无待办)</div>';
        } else {
            pendingEl.innerHTML = pendingItems.map(it =>
                `<div class="ctx-item disabled">${it.icon} ${it.title} — ${it.due}</div>`
            ).join('');
        }
    }
    menu.style.display = 'block';
    menu.style.left = Math.min(x, window.innerWidth - 210) + 'px';
    menu.style.top  = Math.min(y, window.innerHeight - 300) + 'px';
}

function hideCtxMenu() {
    const menu = document.getElementById('ctx-menu');
    if (menu) menu.style.display = 'none';
}

// ── Bubbles ──
function showReminderBubble(title, msg, reminderId) {
    hideBubbles();
    currentReminderId = reminderId;
    document.getElementById('reminder-title').textContent = title || '提醒';
    document.getElementById('reminder-msg').textContent = msg || '';
    positionAndShow('reminder-bubble');
    showingBubble = 'reminder';
}

function showPermissionBubble(toolName, detail, requestId) {
    hideBubbles();
    currentPermId = requestId;
    document.getElementById('perm-title').textContent = '权限请求 · ' + (toolName || '');
    document.getElementById('perm-tool').textContent = detail || '';
    positionAndShow('perm-bubble');
    showingBubble = 'perm';
}

function showStatusBubble(title, msg) {
    hideBubbles();
    document.getElementById('status-title').textContent = title || '';
    document.getElementById('status-msg').textContent = msg || '';
    positionAndShow('status-bubble');
    showingBubble = 'status';
}

function positionAndShow(id) {
    const pet = document.getElementById('pet');
    const bub = document.getElementById(id);
    if (!bub) return;
    bub.style.display = 'block';
    const left = Math.max(10, pet.offsetLeft + pet.offsetWidth + 10);
    const top  = Math.max(10, pet.offsetTop + 8);
    bub.style.left = left + 'px';
    bub.style.top  = top + 'px';
}

function hideBubbles() {
    ['reminder-bubble', 'perm-bubble', 'status-bubble'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    showingBubble = null;
}

// ── Bubble Button Handlers ──
function onReminder(action) {
    window.pywebview.api.on_reminder_action(action, currentReminderId);
    hideBubbles();
}
function onPermission(action) {
    window.pywebview.api.on_permission_action(action, currentPermId);
    hideBubbles();
}
function onStatusDismiss() {
    window.pywebview.api.on_status_dismiss();
    hideBubbles();
}

// ── Menu Actions ──
function onMenu(action) {
    hideCtxMenu();
    switch(action) {
        case 'chat':      window.pywebview.api.on_menu_action('chat'); break;
        case 'add_rem':   showReminderDialog(); break;
        case 'settings':  showSettingsDialog(); break;
        case 'pause':     window.pywebview.api.on_menu_action('pause'); break;
        case 'top':       window.pywebview.api.on_menu_action('top'); break;
        case 'quit':      window.pywebview.api.on_menu_action('quit'); break;
    }
}

// ── Double Click → Chat ──
function setupDoubleClick() {
    document.getElementById('pet').addEventListener('dblclick', () => {
        window.pywebview.api.on_menu_action('chat');
    });
}

// ── Esc HTML helper ──
function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ═══════════════════════════════════════════
// Dialogs (overlay-based)
// ═══════════════════════════════════════════

// ── Settings ──
function showSettingsDialog() {
    hideCtxMenu();
    window.pywebview.api.on_panel_open();
    document.getElementById('settings-overlay').classList.add('show');
    document.getElementById('settings-dialog').style.display = 'block';
    document.getElementById('reminder-dialog').style.display = 'none';
    // Request current settings from Python
    window.pywebview.api.on_settings_open();
}

function hideSettingsDialog() {
    document.getElementById('settings-overlay').classList.remove('show');
    window.pywebview.api.on_panel_close();
}

function populateSettings(scale, deepseekKey, tavilyKey, petsJson, currentPetId) {
    document.getElementById('set-scale').value = scale;
    document.getElementById('scale-label').textContent = scale;
    document.getElementById('set-deepseek').value = deepseekKey || '';
    document.getElementById('set-tavily').value = tavilyKey || '';

    const sel = document.getElementById('set-pet');
    sel.innerHTML = '';
    try {
        const pets = JSON.parse(petsJson);
        pets.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name + (p.id === currentPetId ? ' (current)' : '');
            if (p.id === currentPetId) opt.selected = true;
            sel.appendChild(opt);
        });
    } catch(e) {}
}

function submitSettings() {
    const sel = document.getElementById('set-pet');
    const data = {
        scale: parseInt(document.getElementById('set-scale').value) || 40,
        deepseekKey: document.getElementById('set-deepseek').value || '',
        tavilyKey: document.getElementById('set-tavily').value || '',
        petId: sel.value || 'sumi',
    };
    window.pywebview.api.on_settings_save(JSON.stringify(data));
    hideSettingsDialog();
}

// ── Reminder ──
function showReminderDialog() {
    hideCtxMenu();
    window.pywebview.api.on_panel_open();
    // set default time = now + 10 min
    const now = new Date(Date.now() + 10 * 60 * 1000);
    document.getElementById('rem-due').value = now.toISOString().slice(0, 16);
    document.getElementById('settings-overlay').classList.add('show');
    document.getElementById('settings-dialog').style.display = 'none';
    document.getElementById('reminder-dialog').style.display = 'block';
}

function hideReminderDialog() {
    document.getElementById('settings-overlay').classList.remove('show');
    window.pywebview.api.on_panel_close();
}

function submitReminder() {
    const data = {
        title: document.getElementById('rem-title').value || '提醒',
        message: document.getElementById('rem-msg').value || '',
        due_at: document.getElementById('rem-due').value || '',
    };
    window.pywebview.api.on_reminder_add(JSON.stringify(data));
    hideReminderDialog();
    hideSettingsDialog();
}

// ── Toast ──
let toastTimer = null;
function showToast(msg) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.remove('show');
    void el.offsetWidth; // reflow
    el.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

// ── Keyboard ──
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        hideBubbles();
        hideCtxMenu();
        hideSettingsDialog();
        hideReminderDialog();
    }
});

// ── Init ──
// 页面完全加载后通知 Python；如果已加载则立即触发
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

// ── Init ──
setupDrag();
setupContextMenu();
setupDoubleClick();
// Start animation with the frames loaded on the pet element
(function initAnim() {
    const frames = document.getElementById('pet')._frames;
    if (frames && frames.length > 0) {
        startAnim(frames, 180);
    }
})();
