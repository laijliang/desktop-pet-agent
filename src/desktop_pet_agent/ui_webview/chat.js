/* ═══════════════════════════════════════════════════
   Desktop Pet Agent — Chat Window Logic
   Streaming, thinking blocks, Python bridge
   ═══════════════════════════════════════════════════ */

// ── Chat State ──
const chat = {
    sessionId: '',
    thinkBuf: '',
    replyBuf: '',
    thinkBlocks: [],
    streamTimer: null,
    busy: false,
};

function sendChat() {
    if (chat.busy) return;
    const inp = document.getElementById('chat-input');
    const text = inp.value.trim();
    if (!text) return;
    inp.value = '';
    setChatBusy(true);
    appendUserMsg(text);
    window.pywebview.api.on_chat_send(text);
}

function newChatSession() {
    if (chat.busy) {
        window.pywebview.api.on_chat_stop();
    }
    chat.sessionId = '';
    chat.thinkBlocks = [];
    document.getElementById('chat-session-label').textContent = 'New Session';
    document.getElementById('chat-messages').innerHTML =
        '<div class="msg-welcome">Claude Code ready. Enter a message to start.</div>';
    window.pywebview.api.on_chat_new_session();
}

function setChatBusy(busy) {
    chat.busy = busy;
    const btn = document.getElementById('chat-send-btn');
    const inp = document.getElementById('chat-input');
    if (busy) {
        btn.textContent = 'Stop';
        btn.classList.add('stop');
        btn.onclick = stopChat;
        inp.disabled = true;
        inp.placeholder = 'Claude is replying...';
    } else {
        btn.textContent = 'Send';
        btn.classList.remove('stop');
        btn.onclick = sendChat;
        inp.disabled = false;
        inp.placeholder = 'Enter message... (Enter to send, Esc to close)';
    }
}

function stopChat() {
    window.pywebview.api.on_chat_stop();
}

function appendUserMsg(text) {
    const now = new Date();
    const ts = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');
    const msgs = document.getElementById('chat-messages');
    msgs.insertAdjacentHTML('beforeend',
        '<div class="msg-user">' +
        '<div class="msg-user-label">' + ts + ' You</div>' +
        '<div class="msg-user-text">' + escHtml(text) + '</div>' +
        '</div>'
    );
    msgs.scrollTop = msgs.scrollHeight;
}

function onChatInit(sessionId) {
    chat.sessionId = sessionId;
    const short = sessionId ? sessionId.substring(0, 8) : '';
    document.getElementById('chat-session-label').textContent = short ? 'Session ' + short + '...' : 'New Session';
}

function onChatThinking(text) {
    flushReply();
    if (!document.getElementById('chat-thinking-block')) {
        chat.thinkBlocks.push({start: 0, collapsed: false, fullHtml: ''});
        document.getElementById('chat-messages').insertAdjacentHTML('beforeend',
            '<div id="chat-thinking-block" class="think-block">' +
            '<div class="think-label">Thinking...</div>' +
            '<div id="chat-thinking-content" class="think-content"></div>' +
            '</div>'
        );
    }
    chat.thinkBuf += text;
    if (!chat.streamTimer) chat.streamTimer = setInterval(streamTick, 15);
}

function onChatText(text) {
    flushThink();
    chat.replyBuf += text;
    if (!chat.streamTimer) chat.streamTimer = setInterval(streamTick, 15);
    const msgs = document.getElementById('chat-messages');
    if (!document.getElementById('chat-assist-label')) {
        const now = new Date();
        const ts = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');
        msgs.insertAdjacentHTML('beforeend',
            '<div class="msg-assistant" id="chat-assist-label">' +
            '<div class="msg-assistant-label">Assistant <span class="ts">' + ts + '</span></div>' +
            '</div>'
        );
    }
    if (!document.getElementById('chat-reply-text')) {
        msgs.insertAdjacentHTML('beforeend',
            '<span id="chat-reply-text" style="color:#CDD6F4;font-weight:bold;white-space:pre-wrap;"></span>'
        );
    }
}

function onChatToolUse(name, inp) {
    flushThink(); flushReply(); closeThinkBlock(); closeReplyBlock();
    const msgs = document.getElementById('chat-messages');
    let html = '<div class="msg-tool">Tool: ' + escHtml(name) + '</div>';
    if (inp) {
        try { var inpStr = typeof inp === 'string' ? inp : JSON.stringify(inp, null, 2); }
        catch(e) { inpStr = String(inp); }
        html += '<div class="msg-tool-input">' + escHtml(inpStr).substring(0, 2000) + '</div>';
    }
    msgs.insertAdjacentHTML('beforeend', html);
    msgs.scrollTop = msgs.scrollHeight;
}

function onChatToolResult(content) {
    flushThink(); flushReply(); closeThinkBlock(); closeReplyBlock();
    const str = String(content || '').substring(0, 2000);
    document.getElementById('chat-messages').insertAdjacentHTML('beforeend',
        '<div class="msg-tool-result">' + escHtml(str) + '</div>'
    );
    const msgs = document.getElementById('chat-messages');
    msgs.scrollTop = msgs.scrollHeight;
}

function onChatResult(sessionId, cost) {
    if (sessionId) onChatInit(sessionId);
    if (cost > 0) {
        document.getElementById('chat-messages').insertAdjacentHTML('beforeend',
            '<div class="msg-cost">Cost: $' + cost.toFixed(4) + '</div>'
        );
    }
    const msgs = document.getElementById('chat-messages');
    msgs.scrollTop = msgs.scrollHeight;
}

function onChatError(msg) {
    flushThink(); flushReply(); closeThinkBlock(); closeReplyBlock();
    document.getElementById('chat-messages').insertAdjacentHTML('beforeend',
        '<div class="msg-error">Error: ' + escHtml(msg) + '</div>'
    );
    const msgs = document.getElementById('chat-messages');
    msgs.scrollTop = msgs.scrollHeight;
}

function onChatInfo(msg) {
    document.getElementById('chat-messages').insertAdjacentHTML('beforeend',
        '<div class="msg-info">' + escHtml(msg) + '</div>'
    );
    const msgs = document.getElementById('chat-messages');
    msgs.scrollTop = msgs.scrollHeight;
}

function onChatFinished() {
    flushThink(); flushReply(); closeThinkBlock(); closeReplyBlock();
    collapseAllThinks();
    setChatBusy(false);
}

function flushThink() {
    if (chat.thinkBuf) {
        const el = document.getElementById('chat-thinking-content');
        if (el) { el.textContent += chat.thinkBuf; }
        chat.thinkBuf = '';
        document.getElementById('chat-messages').scrollTop = document.getElementById('chat-messages').scrollHeight;
    }
}

function flushReply() {
    if (chat.replyBuf) {
        const el = document.getElementById('chat-reply-text');
        if (el) { el.textContent += chat.replyBuf; }
        chat.replyBuf = '';
        document.getElementById('chat-messages').scrollTop = document.getElementById('chat-messages').scrollHeight;
    }
}

function closeThinkBlock() {
    const block = document.getElementById('chat-thinking-block');
    if (block) {
        block.removeAttribute('id');
        const content = document.getElementById('chat-thinking-content');
        if (content) content.removeAttribute('id');
        const last = chat.thinkBlocks[chat.thinkBlocks.length - 1];
        if (last) last.fullHtml = block.outerHTML;
    }
}

function closeReplyBlock() {
    const el = document.getElementById('chat-reply-text');
    if (el) el.removeAttribute('id');
    const label = document.getElementById('chat-assist-label');
    if (label) {
        label.removeAttribute('id');
        label.insertAdjacentHTML('afterend', '<div class="msg-sep">---</div>');
    }
}

function collapseAllThinks() {
    const msgs = document.getElementById('chat-messages');
    const blocks = msgs.querySelectorAll('.think-block');
    blocks.forEach((block, i) => {
        if (chat.thinkBlocks[i] && !chat.thinkBlocks[i].collapsed) {
            const raw = (block.textContent || '').trim();
            const summary = raw ? (raw.substring(0, 60) + (raw.length > 60 ? '...' : '')) : 'Thinking...';
            const idx = i;
            block.outerHTML =
                '<div class="think-collapsed" data-think-idx="' + idx + '">' +
                '<span>' + escHtml(summary) + '</span> ' +
                '<a class="think-link" onclick="expandThink(' + idx + ')">Show</a>' +
                '</div>';
            chat.thinkBlocks[i].collapsed = true;
        }
    });
}

function expandThink(idx) {
    if (!chat.thinkBlocks[idx] || !chat.thinkBlocks[idx].collapsed) return;
    const blk = chat.thinkBlocks[idx];
    const msgs = document.getElementById('chat-messages');
    const collapsed = msgs.querySelector('[data-think-idx="' + idx + '"]');
    if (collapsed) {
        collapsed.outerHTML =
            '<div class="think-block">' +
            '<div class="think-label">Thinking...</div>' +
            '<div class="think-content">' + (blk.fullHtml ? extractThinkContent(blk.fullHtml) : '') + '</div>' +
            ' <a class="think-link" onclick="collapseThink(' + idx + ')">Hide</a>' +
            '</div>';
        chat.thinkBlocks[idx].collapsed = false;
    }
}

function collapseThink(idx) {
    if (!chat.thinkBlocks[idx] || chat.thinkBlocks[idx].collapsed) return;
    const blk = chat.thinkBlocks[idx];
    const msgs = document.getElementById('chat-messages');
    const blocks = msgs.querySelectorAll('.think-block');
    blocks.forEach(block => {
        if (block.textContent.includes(blk.fullHtml ? extractThinkContent(blk.fullHtml).substring(0, 20) : '')) {
            const raw = (block.textContent || '').trim();
            const summary = raw ? (raw.substring(0, 60) + (raw.length > 60 ? '...' : '')) : 'Thinking...';
            block.outerHTML =
                '<div class="think-collapsed" data-think-idx="' + idx + '">' +
                '<span>' + escHtml(summary) + '</span> ' +
                '<a class="think-link" onclick="expandThink(' + idx + ')">Show</a>' +
                '</div>';
            chat.thinkBlocks[idx].collapsed = true;
        }
    });
}

function extractThinkContent(fullHtml) {
    const m = fullHtml.match(/<div class="think-content"[^>]*>([\s\S]*?)<\/div>/);
    return m ? m[1] : '';
}

function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function streamTick() {
    let ch = null;
    let isThink = false;
    if (chat.thinkBuf) {
        ch = chat.thinkBuf[0];
        chat.thinkBuf = chat.thinkBuf.slice(1);
        isThink = true;
    } else if (chat.replyBuf) {
        ch = chat.replyBuf[0];
        chat.replyBuf = chat.replyBuf.slice(1);
    }
    if (ch === null) {
        clearInterval(chat.streamTimer);
        chat.streamTimer = null;
        return;
    }
    const el = isThink ? document.getElementById('chat-thinking-content') : document.getElementById('chat-reply-text');
    if (el) {
        el.textContent += ch;
        document.getElementById('chat-messages').scrollTop = document.getElementById('chat-messages').scrollHeight;
    }
}

// ── Settings / Reminder Dialogs ──

function showChatSettings(pets) {
    var sel = document.getElementById('chat-set-pet');
    sel.innerHTML = '';
    (pets || []).forEach(function(p) {
        var opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.display_name || p.id;
        if (p.selected) opt.selected = true;
        sel.appendChild(opt);
    });
    document.getElementById('chat-settings-dialog').style.display = '';
    document.getElementById('chat-overlay').classList.add('show');
}

function showChatReminder() {
    document.getElementById('chat-reminder-dialog').style.display = '';
    document.getElementById('chat-overlay').classList.add('show');
    // Set default due time to 1 hour from now
    var now = new Date();
    now.setHours(now.getHours() + 1);
    var iso = now.toISOString().slice(0, 16);
    document.getElementById('chat-rem-due').value = iso;
}

function hideChatDialogs() {
    document.getElementById('chat-overlay').classList.remove('show');
    document.getElementById('chat-settings-dialog').style.display = 'none';
    document.getElementById('chat-reminder-dialog').style.display = 'none';
}

function submitChatSettings() {
    var data = {
        pet_id: document.getElementById('chat-set-pet').value,
        ui_scale: parseInt(document.getElementById('chat-set-scale').value),
        deepseek_api_key: document.getElementById('chat-set-deepseek').value,
        tavily_api_key: document.getElementById('chat-set-tavily').value,
    };
    window.pywebview.api.on_save_settings(JSON.stringify(data));
    hideChatDialogs();
}

function submitChatReminder() {
    var data = {
        title: document.getElementById('chat-rem-title').value.trim(),
        due_at: document.getElementById('chat-rem-due').value,
        message: document.getElementById('chat-rem-msg').value.trim(),
    };
    if (!data.title) { alert('请输入提醒标题'); return; }
    window.pywebview.api.on_add_reminder(JSON.stringify(data));
    hideChatDialogs();
}

// Called from Python to pre-fill settings values
function setChatSettingsValues(cfg) {
    document.getElementById('chat-set-scale').value = cfg.ui_scale || 40;
    document.getElementById('chat-scale-label').textContent = cfg.ui_scale || 40;
    if (cfg.deepseek_api_key) document.getElementById('chat-set-deepseek').value = cfg.deepseek_api_key;
    if (cfg.tavily_api_key) document.getElementById('chat-set-tavily').value = cfg.tavily_api_key || '';
}

// ── Init ──
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        hideChatDialogs();
        window.pywebview.api.on_chat_close();
    }
});

// Notify Python when ready
function _notifyReady() {
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.on_chat_ready();
    } else {
        setTimeout(_notifyReady, 100);
    }
}
if (document.readyState === 'complete') {
    _notifyReady();
} else {
    window.addEventListener('load', _notifyReady);
}
