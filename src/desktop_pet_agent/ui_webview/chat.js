/* ═══════════════════════════════════════════════════
   Desktop Pet Agent — Chat Window Logic
   Streaming, thinking blocks, multi-line input
   ═══════════════════════════════════════════════════ */

// ── Chat State ──
var chat = {
    sessionId: '',
    thinkBuf: '',
    replyBuf: '',
    thinkBlocks: [],
    streamTimer: null,
    busy: false,
    totalTokens: 0,
};

// ── Auto-resize textarea ──
var _chatInput = null;
function autoResize() {
    if (!_chatInput) _chatInput = document.getElementById('chat-input');
    _chatInput.style.height = 'auto';
    _chatInput.style.height = Math.min(_chatInput.scrollHeight, 120) + 'px';
    updateSendButton();
}

function updateSendButton() {
    var inp = document.getElementById('chat-input');
    var btn = document.getElementById('chat-send-btn');
    if (chat.busy) return;
    btn.disabled = !inp.value.trim();
}

// ── Keyboard ──
function onInputKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChat();
    }
    // Auto-resize after a tick so the char lands first
    setTimeout(autoResize, 0);
}

// ── Send / Stop ──
function sendChat() {
    if (chat.busy) return;
    var inp = document.getElementById('chat-input');
    var text = inp.value.trim();
    if (!text) return;
    inp.value = '';
    autoResize();
    setChatBusy(true);
    appendUserMsg(text);
    updateStatus('Sending...');
    window.pywebview.api.on_chat_send(text);
}

function stopChat() {
    window.pywebview.api.on_chat_stop();
}

function newChatSession() {
    if (chat.busy) { stopChat(); }
    chat.sessionId = '';
    chat.thinkBlocks = [];
    chat.totalTokens = 0;
    document.getElementById('chat-session-label').textContent = 'New Session';
    document.getElementById('chat-messages').innerHTML =
        '<div class="msg-welcome">' +
        '<div class="welcome-icon">' +
        '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#89B4FA" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M12 2a4 4 0 0 1 4 4v1h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h2V6a4 4 0 0 1 4-4z"/>' +
        '<circle cx="9" cy="13" r="1" fill="#89B4FA"/><circle cx="15" cy="13" r="1" fill="#89B4FA"/>' +
        '<path d="M9 17c.83.67 1.83 1 3 1s2.17-.33 3-1"/>' +
        '</svg></div>' +
        '<div class="welcome-title">Sumi Chat</div>' +
        '<div class="welcome-sub">Enter 发送 &middot; Shift+Enter 换行 &middot; Esc 关闭</div>' +
        '</div>';
    updateStatus('Ready');
    document.getElementById('chat-status-tokens').textContent = '';
    window.pywebview.api.on_chat_new_session();
}

// ── Busy state ──
function setChatBusy(busy) {
    chat.busy = busy;
    var btn = document.getElementById('chat-send-btn');
    var inp = document.getElementById('chat-input');
    if (busy) {
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>';
        btn.classList.add('stop');
        btn.disabled = false;
        btn.onclick = stopChat;
        inp.placeholder = 'Claude 正在回复...';
    } else {
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M2 21l21-9L2 3v7l15 2-15 2v7z"/></svg>';
        btn.classList.remove('stop');
        btn.disabled = true;
        btn.onclick = sendChat;
        inp.placeholder = '输入消息...';
    }
}

// ── Status bar ──
function updateStatus(text) {
    var el = document.getElementById('chat-status-text');
    if (el) el.textContent = text;
}
function updateTokens(tokens) {
    chat.totalTokens = tokens || 0;
    var el = document.getElementById('chat-status-tokens');
    if (el && chat.totalTokens > 0) {
        el.textContent = chat.totalTokens + ' tokens';
    }
}

// ── Scroll management ──
function scrollToBottom() {
    var msgs = document.getElementById('chat-messages');
    msgs.scrollTop = msgs.scrollHeight;
    document.getElementById('chat-scroll-btn').classList.remove('show');
}

function _autoScrollCheck() {
    var msgs = document.getElementById('chat-messages');
    var btn = document.getElementById('chat-scroll-btn');
    if (!msgs || !btn) return;
    var dist = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight;
    if (dist > 120) {
        btn.classList.add('show');
    } else {
        btn.classList.remove('show');
    }
}

// ── Message builders ──
function appendUserMsg(text) {
    var now = new Date();
    var ts = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');
    var msgs = document.getElementById('chat-messages');
    msgs.insertAdjacentHTML('beforeend',
        '<div class="msg-user">' +
        '<div class="msg-user-label">' + ts + ' You</div>' +
        '<div class="msg-user-text">' + escHtml(text) + '</div>' +
        '</div>'
    );
    scrollToBottom();
}

// ── Python bridge callbacks ──
function onChatInit(sessionId) {
    chat.sessionId = sessionId;
    var short = sessionId ? sessionId.substring(0, 8) : '';
    document.getElementById('chat-session-label').textContent = short ? 'Session ' + short + '...' : 'New Session';
    updateStatus('Ready');
}

function onChatThinking(text) {
    flushReply();
    updateStatus('Thinking...');
    if (!document.getElementById('chat-thinking-block')) {
        var idx = chat.thinkBlocks.length;
        chat.thinkBlocks.push({start: 0, collapsed: false, fullHtml: ''});
        document.getElementById('chat-messages').insertAdjacentHTML('beforeend',
            '<div id="chat-thinking-block" class="think-block" data-think-idx="' + idx + '">' +
            '<div class="think-label"><span class="dots"></span> Thinking</div>' +
            '<div id="chat-thinking-content" class="think-content"></div>' +
            '</div>'
        );
    }
    chat.thinkBuf += text;
    if (!chat.streamTimer) chat.streamTimer = setInterval(streamTick, 15);
}

function onChatText(text) {
    flushThink();
    updateStatus('Replying...');
    chat.replyBuf += text;
    if (!chat.streamTimer) chat.streamTimer = setInterval(streamTick, 15);
    var msgs = document.getElementById('chat-messages');
    if (!document.getElementById('chat-assist-label')) {
        var now = new Date();
        var ts = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0');
        msgs.insertAdjacentHTML('beforeend',
            '<div class="msg-assistant" id="chat-assist-label">' +
            '<div class="msg-assistant-label">Assistant <span class="ts">' + ts + '</span></div>' +
            '</div>'
        );
    }
    if (!document.getElementById('chat-reply-text')) {
        msgs.insertAdjacentHTML('beforeend',
            '<span id="chat-reply-text" style="color:var(--text);font-weight:600;white-space:pre-wrap;"></span>'
        );
    }
}

var _lastToolBlock = null;

function onChatToolUse(name, inp) {
    flushThink(); flushReply(); closeThinkBlock(); closeReplyBlock();
    var msgs = document.getElementById('chat-messages');
    updateStatus('Tool: ' + name);
    var inpStr = '';
    if (inp) {
        try { inpStr = typeof inp === 'string' ? inp : JSON.stringify(inp, null, 2); }
        catch(e) { inpStr = String(inp); }
    }
    var html = '<div class="tool-block">' +
        '<div class="tool-header" onclick="toggleToolBlock(this)">' +
        '<span class="tool-arrow">▶</span> Tool: ' + escHtml(name) +
        '</div>' +
        '<div class="tool-body" style="display:none">' +
        (inpStr ? '<div class="msg-tool-input">' + escHtml(inpStr).substring(0, 3000) + '</div>' : '') +
        '<div class="tool-result-placeholder"></div>' +
        '</div></div>';
    msgs.insertAdjacentHTML('beforeend', html);
    _lastToolBlock = msgs.lastElementChild;
    scrollToBottom();
}

function onChatToolResult(content) {
    flushThink(); flushReply(); closeThinkBlock();
    var str = String(content || '').substring(0, 3000);
    if (_lastToolBlock) {
        var placeholder = _lastToolBlock.querySelector('.tool-result-placeholder');
        if (placeholder) {
            placeholder.outerHTML = '<div class="msg-tool-result">' + escHtml(str) + '</div>';
        }
    }
    if (!_lastToolBlock || !_lastToolBlock.querySelector('.tool-result-placeholder')) {
        // Fallback: standalone result
        document.getElementById('chat-messages').insertAdjacentHTML('beforeend',
            '<div class="msg-tool-result">' + escHtml(str) + '</div>'
        );
    }
    scrollToBottom();
}

function toggleToolBlock(header) {
    var body = header.nextElementSibling;
    var arrow = header.querySelector('.tool-arrow');
    if (body.style.display === 'none') {
        body.style.display = '';
        arrow.textContent = '▼';
    } else {
        body.style.display = 'none';
        arrow.textContent = '▶';
    }
}

function onChatResult(sessionId, cost) {
    if (sessionId) onChatInit(sessionId);
    if (cost > 0) {
        document.getElementById('chat-messages').insertAdjacentHTML('beforeend',
            '<div class="msg-cost">Cost: $' + cost.toFixed(4) + '</div>'
        );
    }
    scrollToBottom();
}

function onChatError(msg) {
    flushThink(); flushReply(); closeThinkBlock(); closeReplyBlock();
    document.getElementById('chat-messages').insertAdjacentHTML('beforeend',
        '<div class="msg-error">Error: ' + escHtml(msg) + '</div>'
    );
    updateStatus('Error');
    scrollToBottom();
}

function onChatInfo(msg) {
    document.getElementById('chat-messages').insertAdjacentHTML('beforeend',
        '<div class="msg-info">' + escHtml(msg) + '</div>'
    );
    scrollToBottom();
}

function onChatFinished() {
    flushThink(); flushReply(); closeThinkBlock(); closeReplyBlock();
    collapseAllThinks();
    setChatBusy(false);
    updateStatus('Ready');
    updateSendButton();
}

// ── Stream flushing ──
function flushThink() {
    if (chat.thinkBuf) {
        var el = document.getElementById('chat-thinking-content');
        if (el) { el.textContent += chat.thinkBuf; }
        chat.thinkBuf = '';
        _autoScrollCheck();
        if (document.getElementById('chat-scroll-btn').classList.contains('show') === false) {
            scrollToBottom();
        }
    }
}

function flushReply() {
    if (chat.replyBuf) {
        var el = document.getElementById('chat-reply-text');
        if (el) { el.textContent += chat.replyBuf; }
        chat.replyBuf = '';
        _autoScrollCheck();
        if (document.getElementById('chat-scroll-btn').classList.contains('show') === false) {
            scrollToBottom();
        }
    }
}

function closeThinkBlock() {
    var block = document.getElementById('chat-thinking-block');
    if (block) {
        block.removeAttribute('id');
        var content = document.getElementById('chat-thinking-content');
        if (content) content.removeAttribute('id');
        var last = chat.thinkBlocks[chat.thinkBlocks.length - 1];
        if (last) last.fullHtml = block.outerHTML;
    }
}

function closeReplyBlock() {
    var el = document.getElementById('chat-reply-text');
    if (el) {
        el.removeAttribute('id');
        // Add copy button after reply text
        var copyBtn = '<button class="msg-copy-btn" onclick="copyReply(this)" title="复制">' +
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>' +
            '</svg></button>';
        el.insertAdjacentHTML('afterend', copyBtn);
    }
    var label = document.getElementById('chat-assist-label');
    if (label) {
        label.removeAttribute('id');
        label.insertAdjacentHTML('afterend', '<div class="msg-sep">---</div>');
    }
}

function copyReply(btn) {
    var text = btn.previousElementSibling.textContent;
    navigator.clipboard.writeText(text).then(function() {
        btn.classList.add('copied');
        btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
        setTimeout(function() {
            btn.classList.remove('copied');
            btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
        }, 1500);
    }).catch(function() {
        // Fallback for older browsers
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
    });
}

// ── Think collapse / expand ──
function collapseAllThinks() {
    var msgs = document.getElementById('chat-messages');
    var blocks = msgs.querySelectorAll('.think-block');
    blocks.forEach(function(block) {
        var idx = parseInt(block.getAttribute('data-think-idx'));
        if (isNaN(idx) || !chat.thinkBlocks[idx] || chat.thinkBlocks[idx].collapsed) return;
        var raw = (block.textContent || '').trim();
        var summary = raw ? (raw.substring(0, 60) + (raw.length > 60 ? '...' : '')) : 'Thinking...';
        block.outerHTML =
            '<div class="think-collapsed" data-think-idx="' + idx + '">' +
            '<span>' + escHtml(summary) + '</span> ' +
            '<a class="think-link" onclick="expandThink(' + idx + ')">Show</a>' +
            '</div>';
        chat.thinkBlocks[idx].collapsed = true;
    });
}

function expandThink(idx) {
    if (!chat.thinkBlocks[idx] || !chat.thinkBlocks[idx].collapsed) return;
    var blk = chat.thinkBlocks[idx];
    var msgs = document.getElementById('chat-messages');
    var collapsed = msgs.querySelector('[data-think-idx="' + idx + '"]');
    if (collapsed) {
        collapsed.outerHTML =
            '<div class="think-block" data-think-idx="' + idx + '">' +
            '<div class="think-label">Thinking</div>' +
            '<div class="think-content">' + (blk.fullHtml ? extractThinkContent(blk.fullHtml) : '') + '</div>' +
            ' <a class="think-link" onclick="collapseThink(' + idx + ')">Hide</a>' +
            '</div>';
        chat.thinkBlocks[idx].collapsed = false;
    }
}

function collapseThink(idx) {
    if (!chat.thinkBlocks[idx] || chat.thinkBlocks[idx].collapsed) return;
    var blk = chat.thinkBlocks[idx];
    var msgs = document.getElementById('chat-messages');
    var blocks = msgs.querySelectorAll('.think-block');
    blocks.forEach(function(block) {
        if (block.textContent.indexOf((blk.fullHtml ? extractThinkContent(blk.fullHtml).substring(0, 20) : '')) !== -1) {
            var raw = (block.textContent || '').trim();
            var summary = raw ? (raw.substring(0, 60) + (raw.length > 60 ? '...' : '')) : 'Thinking...';
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
    var m = fullHtml.match(/<div class="think-content"[^>]*>([\s\S]*?)<\/div>/);
    return m ? m[1] : '';
}

// ── Stream tick (character-at-a-time animation) ──
function streamTick() {
    var ch = null;
    var isThink = false;
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
    var el = isThink ? document.getElementById('chat-thinking-content') : document.getElementById('chat-reply-text');
    if (el) {
        el.textContent += ch;
        _autoScrollCheck();
        if (document.getElementById('chat-scroll-btn').classList.contains('show') === false) {
            scrollToBottom();
        }
    }
}

// ── Settings / Reminder Dialogs ──

function openSettings() {
    window.pywebview.api.on_open_settings();
}

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

function hideChatDialogs() {
    document.getElementById('chat-overlay').classList.remove('show');
    setTimeout(function() {
        document.getElementById('chat-settings-dialog').style.display = 'none';
    }, 200);
}

function submitChatSettings() {
    var data = {
        pet_id: document.getElementById('chat-set-pet').value,
        ui_scale: parseInt(document.getElementById('chat-set-scale').value),
        theme: document.getElementById('chat-set-theme').value,
        tavily_api_key: document.getElementById('chat-set-tavily').value,
    };
    window.pywebview.api.on_save_settings(JSON.stringify(data));
    hideChatDialogs();
}

function setChatSettingsValues(cfg) {
    document.getElementById('chat-set-scale').value = cfg.ui_scale || 40;
    document.getElementById('chat-scale-label').textContent = cfg.ui_scale || 40;
    document.getElementById('chat-set-theme').value = cfg.theme || 'dark';
    if (cfg.tavily_api_key) document.getElementById('chat-set-tavily').value = cfg.tavily_api_key || '';
}

// ── HTML escape ──
function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Theme ──
function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme || 'dark');
}

// ── Init ──
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        hideChatDialogs();
        window.pywebview.api.on_chat_close();
    }
    // Ctrl+, for settings
    if (e.ctrlKey && e.key === ',') {
        e.preventDefault();
    }
});

// Scroll detection
document.addEventListener('DOMContentLoaded', function() {
    var msgs = document.getElementById('chat-messages');
    msgs.addEventListener('scroll', _autoScrollCheck);
    autoResize();
});

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
