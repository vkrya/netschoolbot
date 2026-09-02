"""Управление службой, потоковые логи journalctl и PTY-терминал."""

import os
import pty
import re
import select
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import jsonify, request, session
from flask_socketio import disconnect, emit

from ..config import INPUT_FIFO as FORWARDER_INPUT_FIFO, SERVICE_NAME, WEB_JOURNAL_TAIL as JOURNAL_TAIL
from .app import _check_auth, _pty_sessions, app, socketio


@app.route("/api/service/control", methods=["POST"])
def service_control():
    """Управление systemd сервисами"""
    _check_auth()
    try:
        data = request.get_json()
        service = data.get("service", "")
        action = data.get("action", "")
        
        # Whitelist разрешенных сервисов
        allowed_services = [SERVICE_NAME, "netschoolbot", "nginx"]
        if service not in allowed_services:
            return jsonify({"error": f"Сервис '{service}' не разрешен"}), 403
        
        service_name = f"{service}.service" if not service.endswith(".service") else service
        
        # Выполняем команду (webterm работает под root, sudo не нужен)
        if action == "start":
            result = subprocess.run(
                ["systemctl", "start", service_name],
                capture_output=True, text=True, timeout=10
            )
            message = f"Сервис {service} запущен"
        elif action == "stop":
            result = subprocess.run(
                ["systemctl", "stop", service_name],
                capture_output=True, text=True, timeout=10
            )
            message = f"Сервис {service} остановлен"
        elif action == "restart":
            result = subprocess.run(
                ["systemctl", "restart", service_name],
                capture_output=True, text=True, timeout=15
            )
            message = f"Сервис {service} перезапущен"
        elif action == "kill":
            # Kill отправляет SIGKILL процессам сервиса
            result = subprocess.run(
                ["systemctl", "kill", "-s", "SIGKILL", service_name],
                capture_output=True, text=True, timeout=10
            )
            message = f"Процесс {service} убит (SIGKILL)"
        else:
            return jsonify({"error": f"Неизвестное действие: {action}"}), 400
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Неизвестная ошибка"
            return jsonify({"error": error_msg}), 500
        
        return jsonify({"message": message, "output": result.stdout})
    
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Таймаут выполнения команды"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Log streaming ─────────────────────────────────────────────
_log_threads: dict = {}  # sid+service -> thread

_log_procs: dict = {}    # sid+service -> subprocess.Popen

SERVICE_UNITS = {
  "arsbb": "nginx.service",
  "arsbb_webhook": "arsbb-webhook.service",
  "netschoolbot": f"{SERVICE_NAME}.service",
}

_ANSI_COLORS = {
  "INFO": "32",
  "WARNING": "33",
  "ERROR": "31",
  "DEBUG": "36",
  "CRITICAL": "35",
}

_LEVEL_RE = re.compile(r"\b(INFO|WARNING|ERROR|DEBUG|CRITICAL)\b")

_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{4}|[+-]\d{2}:\d{2})?)")

def _color(text: str, code: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m"

def _normalize_ts(ts: str) -> str:
    ts = ts.replace("T", " ").replace(",", ".")
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    if re.search(r"[+-]\d{4}$", ts):
        ts = ts[:-5] + ts[-5:-2] + ":" + ts[-2:]
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts

def _format_log_line(line: str) -> str:
    has_nl = line.endswith("\n")
    line = line.rstrip("\n")
    m = _TS_RE.match(line)
    if m:
        ts = _normalize_ts(m.group(1))
        line = _color(ts, "90") + line[len(m.group(1)) :]
    line = _LEVEL_RE.sub(lambda m: _color(m.group(1), _ANSI_COLORS.get(m.group(1), "0")), line)
    return line + ("\n" if has_nl else "")

def _stream_journal(sid: str, service: str, unit: str, tail: int):
    """Stream journalctl -f to client."""
    key = f"{sid}:{service}"
    proc = None
    try:
        tail = max(50, min(int(tail), 5000))
        proc = subprocess.Popen(
            ["journalctl", "-n", str(tail), "-fu", unit, "--no-pager", "--output=short-iso"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        _log_procs[key] = proc
        fd = proc.stdout.fileno()
        buffer = ""
        while True:
            if _log_procs.get(key) != proc:
                break
            ready, _, _ = select.select([fd], [], [], 1.0)
            if not ready:
                if _log_procs.get(key) != proc:
                    break
                continue
            raw = os.read(fd, 4096)
            if not raw:
                break
            buffer += raw.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                socketio.emit(
                    "log_output",
                    {"service": service, "data": _format_log_line(line + "\n")},
                    to=sid,
                )
        if buffer and _log_procs.get(key) == proc:
            socketio.emit(
                "log_output",
                {"service": service, "data": _format_log_line(buffer)},
                to=sid,
            )
    except Exception:
        pass
    finally:
        if _log_procs.get(key) == proc:
            _log_procs.pop(key, None)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=0.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

@socketio.on("log_subscribe")
def on_log_subscribe(data):
    if not session.get("logged_in"):
        disconnect()
        return
    service = data.get("service", "")
    tail = data.get("tail", JOURNAL_TAIL)
    unit = SERVICE_UNITS.get(service)
    if not unit:
        return
    sid = request.sid
    key = f"{sid}:{service}"
    # Kill existing thread if any
    old = _log_threads.pop(key, None)
    # Start new stream in background
    t = socketio.start_background_task(_stream_journal, sid, service, unit, tail)
    _log_threads[key] = t

def _run_command(sid: str, service: str, cmd: str):
    try:
        socketio.emit("log_output", {"service": service, "data": f"\r\n$ {cmd}\r\n"}, to=sid)
        proc = subprocess.Popen(
            ["/bin/bash", "-lc", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        fd = proc.stdout.fileno()
        buffer = ""
        while True:
            ready, _, _ = select.select([fd], [], [], 1.0)
            if not ready:
                if proc.poll() is not None:
                    break
                continue
            raw = os.read(fd, 4096)
            if not raw:
                break
            buffer += raw.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                socketio.emit(
                    "log_output",
                    {"service": service, "data": _format_log_line(line + "\n")},
                    to=sid,
                )
        if buffer:
            socketio.emit(
                "log_output",
                {"service": service, "data": _format_log_line(buffer)},
                to=sid,
            )
        proc.wait()
    except Exception:
        pass

@socketio.on("log_command")
def on_log_command(data):
    if not session.get("logged_in"):
        disconnect()
        return
    service = data.get("service", "")
    cmd = (data.get("cmd") or "").strip()
    if service not in SERVICE_UNITS or not cmd:
        return
    sid = request.sid
    socketio.start_background_task(_run_command, sid, service, cmd)

@socketio.on("script_input")
def on_script_input(data):
    if not session.get("logged_in"):
        disconnect()
        return
    service = data.get("service", "")
    text = (data.get("text") or "").strip()
    if service != "netschoolbot" or not text:
        return
    socketio.start_background_task(_write_fifo_input, request.sid, text)

def _write_fifo_input(sid: str, text: str):
    try:
        # Blocking open waits for a reader; retry a few times
        for _ in range(5):
            try:
                with open(FORWARDER_INPUT_FIFO, "w", encoding="utf-8") as f:
                    f.write(text + "\n")
                socketio.emit(
                    "log_output",
                    {"service": "netschoolbot", "data": _format_log_line(f"[input] {text}\n")},
                    to=sid,
                )
                return
            except OSError:
                time.sleep(0.2)
        raise OSError("No reader for FIFO")
    except Exception as e:
      socketio.emit(
        "log_output",
        {"service": "netschoolbot", "data": _format_log_line(f"[input-error] {e}\n")},
        to=sid,
      )

@socketio.on("pty_create")
def on_pty_create():
    if not session.get("logged_in"):
        disconnect()
        return
    sid = request.sid
    _kill_pty(sid)

    pid, fd = pty.fork()
    if pid == 0:
        # Child: exec bash
        env = os.environ.copy()
        env.update({
            "TERM": "xterm-256color",
            "LANG": "en_US.UTF-8",
            "HOME": os.path.expanduser("~"),
        })
        os.chdir(env.get("HOME", "/"))
        os.execvpe("/bin/bash", ["/bin/bash", "--login"], env)
    else:
        _pty_sessions[sid] = {"fd": fd, "pid": pid}
        emit("pty_created")
        socketio.start_background_task(_pty_reader, sid, fd)

def _pty_reader(sid: str, fd: int):
    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 1.0)
            if not ready:
                if sid not in _pty_sessions:
                    break
                continue
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            socketio.emit("pty_output",
                          {"data": data.decode("utf-8", errors="replace")},
                          to=sid)
    except Exception:
        pass
    finally:
        socketio.emit("pty_closed", {}, to=sid)
        _kill_pty(sid)

def _kill_pty(sid: str):
    sess = _pty_sessions.pop(sid, None)
    if sess:
        try:
            os.kill(sess["pid"], 9)
        except Exception:
            pass
        try:
            os.close(sess["fd"])
        except Exception:
            pass
        try:
            os.waitpid(sess["pid"], os.WNOHANG)
        except Exception:
            pass

@socketio.on("pty_input")
def on_pty_input(data):
    if not session.get("logged_in"):
        return
    sid = request.sid
    sess = _pty_sessions.get(sid)
    if sess:
        try:
            os.write(sess["fd"], data["data"].encode("utf-8"))
        except Exception:
            pass

@socketio.on("pty_resize")
def on_pty_resize(data):
    if not session.get("logged_in"):
        return
    sid = request.sid
    sess = _pty_sessions.get(sid)
    if sess:
        import fcntl
        import termios
        import struct
        cols = data.get("cols", 80)
        rows = data.get("rows", 24)
        try:
            fcntl.ioctl(sess["fd"], termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))
        except Exception:
            pass

@socketio.on("pty_kill")
def on_pty_kill():
    _kill_pty(request.sid)

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    _kill_pty(sid)
    for k in list(_log_procs.keys()):
        if k.startswith(f"{sid}:"):
            p = _log_procs.pop(k, None)
            if p:
                try:
                    p.terminate()
                    p.wait(timeout=0.5)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass

