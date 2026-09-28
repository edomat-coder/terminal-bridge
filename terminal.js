// static/js/terminal.js — Odysseus Terminal-Plugin (Frontend)
// Zeigt ein xterm.js-Overlay, verbindet über den Odysseus-Backend-Proxy
// (/api/terminal/ws/{session}) zur Terminal-Bridge (tmux).
// Verdrahtet den Sidebar-Button #tool-terminal-btn.
//
// Hinweise:
//  - Die WebSocket-Verbindung geht relativ zum aktuellen Host -> wandert durch
//    Odysseus-Auth + Reverse-Proxy; kein Client-Token nötig.
//  - Resize wird als "RESIZE:cols:rows" an den Proxy geschickt.

(function () {
  const BTN_ID = 'tool-terminal-btn';
  const OVERLAY_ID = 'terminal-overlay';
  const SELECT = 'terminal-session-select';
  const CONNECT = 'terminal-connect-btn';
  const CLOSE = 'terminal-close-btn';
  const HOST = 'terminal-host';
  const STATUS = 'terminal-status';

  let term = null;
  let socket = null;
  let currentSession = '';
  let fitInterval = null;

  function el(id) { return document.getElementById(id); }

  function setStatus(msg, color) {
    const s = el(STATUS);
    if (s) {
      s.textContent = msg;
      s.style.color = color || 'inherit';
    }
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error('Fehler beim Laden von ' + src));
      document.head.appendChild(s);
    });
  }

  async function ensureXterm() {
    if (window.Terminal) return window.Terminal;
    await loadScript('/static/vendor/xterm/xterm.js');
    if (window.Terminal) return window.Terminal;
    throw new Error('xterm nicht ladbar');
  }

  function destroyTerminal() {
    clearInterval(fitInterval);
    fitInterval = null;
    if (socket) {
      try { socket.close(); } catch (_) {}
      socket = null;
    }
    if (term) {
      try { term.dispose(); } catch (_) {}
      term = null;
    }
    currentSession = '';
  }

  function resizeTerm() {
    if (!term || !socket) return;
    try {
      const cols = term.cols;
      const rows = term.rows;
      if (socket.readyState === WebSocket.OPEN) {
        socket.send('RESIZE:' + cols + ':' + rows);
      }
    } catch (_) {}
  }

  async function connectSession(name) {
    if (!name) { setStatus('Keine Session gewählt', 'var(--red)'); return; }
    destroyTerminal();
    const host = el(HOST);
    host.innerHTML = '';
    setStatus('Verbinde ' + name + ' ...');

    try {
      const TerminalCtor = await ensureXterm();
      term = new TerminalCtor({
        cursorBlink: true,
        fontSize: 13,
        theme: { background: '#0b0f14', foreground: '#d6dce4' },
        scrollback: 2000,
      });
      term.open(host);

      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = proto + '//' + location.host + '/api/terminal/ws/' + encodeURIComponent(name);
      socket = new WebSocket(url);
      currentSession = name;

      socket.onopen = () => {
        setStatus('Verbunden (' + name + ')', 'var(--green,#50fa7b)');
        // Sofort initial resizen, damit tmux die Session-Spalten korrekt stellt
        // (verhindert das WWW…-Wrap-Artefakt beim Verdrahten des PTY).
        setTimeout(() => { resizeTerm(); term.focus(); }, 0);
        setTimeout(resizeTerm, 80);
        fitInterval = setInterval(resizeTerm, 800);
      };
      socket.onmessage = (ev) => {
        if (ev.data instanceof Blob) {
          ev.data.arrayBuffer().then(buf => term.write(new Uint8Array(buf)));
        } else {
          term.write(ev.data);
        }
      };
      socket.onclose = (ev) => {
        clearInterval(fitInterval);
        fitInterval = null;
        const reason = ev.reason ? ' (' + ev.reason + ')' : (ev.code === 1000 ? '' : ' (Code ' + ev.code + ')');
        setStatus('Verbindung geschlossen' + reason, 'var(--red)');
      };
      socket.onerror = () => setStatus('Fehler bei der Verbindung', 'var(--red)');

      term.onData((data) => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(data);
        }
      });
    } catch (e) {
      setStatus('Init-Fehler: ' + e.message, 'var(--red)');
    }
  }

  async function refreshSessions(select) {
    try {
      const r = await fetch('/api/terminal/sessions', { credentials: 'same-origin' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      const sessions = (data.sessions || []).map(s => s.name);
      select.innerHTML = '';
      if (!sessions.length) {
        const o = document.createElement('option');
        o.textContent = 'Keine Sessions';
        select.appendChild(o);
        return;
      }
      for (const name of sessions) {
        const o = document.createElement('option');
        o.value = name;
        o.textContent = name + ' (tmux)';
        select.appendChild(o);
      }
      setStatus(sessions.length + ' Sessions verfügbar', 'inherit');
    } catch (e) {
      setStatus('Sessions nicht ladbar: ' + e.message, 'var(--red)');
    }
  }

  function wire() {
    const btn = el(BTN_ID);
    if (!btn) return;
    btn.addEventListener('click', async () => {
      const overlay = el(OVERLAY_ID);
      if (!overlay) return;
      overlay.style.display = 'flex';
      const select = el(SELECT);
      await refreshSessions(select);
    });

    const closeBtn = el(CLOSE);
    if (closeBtn) {
      closeBtn.addEventListener('click', () => {
        destroyTerminal();
        const overlay = el(OVERLAY_ID);
        if (overlay) overlay.style.display = 'none';
      });
    }

    const connectBtn = el(CONNECT);
    if (connectBtn) {
      connectBtn.addEventListener('click', () => {
        const select = el(SELECT);
        const name = select ? select.value : '';
        connectSession(name);
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
