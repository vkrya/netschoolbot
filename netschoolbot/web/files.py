"""Файловый менеджер веб-панели."""

import io
import json
import mimetypes
import os
import shutil
import tarfile
from pathlib import Path

from flask import abort, jsonify, request, send_file

from .app import _check_auth, _safe_path, app


@app.route("/api/fm/list", methods=["POST"])
def fm_list():
    _check_auth()
    try:
        data = request.get_json()
        p = _safe_path(data.get("path", "/"))
        if not p.is_dir():
            return jsonify({"error": "Не директория"})
        entries = []
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                stat = child.stat()
                entries.append({
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                })
            except Exception:
                entries.append({"name": child.name, "is_dir": child.is_dir(), "size": 0, "mtime": None})
        return jsonify({"path": str(p), "entries": entries})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/fm/read", methods=["POST"])
def fm_read():
    _check_auth()
    try:
        data = request.get_json()
        p = _safe_path(data["path"])
        if not p.is_file():
            return jsonify({"error": "Файл не найден"})
        if p.stat().st_size > 5 * 1024 * 1024:
            return jsonify({"error": "Файл слишком большой для редактора (>5 МБ)"})
        try:
            return jsonify({"content": p.read_text(encoding="utf-8", errors="replace")})
        except Exception:
            return jsonify({"error": "Не удалось прочитать файл (бинарный?)"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/fm/write", methods=["POST"])
def fm_write():
    _check_auth()
    try:
        data = request.get_json()
        p = _safe_path(data["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data.get("content", ""), encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/fm/delete", methods=["POST"])
def fm_delete():
    _check_auth()
    try:
        data = request.get_json()
        p = _safe_path(data["path"])
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/fm/rename", methods=["POST"])
def fm_rename():
    _check_auth()
    try:
        data = request.get_json()
        src = _safe_path(data["src"])
        dst = _safe_path(data["dst"])
        shutil.move(str(src), str(dst))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/fm/mkdir", methods=["POST"])
def fm_mkdir():
    _check_auth()
    try:
        data = request.get_json()
        p = _safe_path(data["path"])
        p.mkdir(parents=True, exist_ok=True)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/fm/download")
def fm_download():
    _check_auth()
    try:
        path = request.args.get("path", "")
        p = _safe_path(path)
        if not p.is_file():
            abort(404)
        return send_file(str(p), as_attachment=True, download_name=p.name)
    except Exception as e:
        return str(e), 400

@app.route("/api/fm/upload", methods=["POST"])
def fm_upload():
    _check_auth()
    try:
        dest = _safe_path(request.form.get("path", "/"))
        dest.mkdir(parents=True, exist_ok=True)
        uploaded = []
        for f in request.files.getlist("files"):
            if f.filename:
                save_path = dest / Path(f.filename).name
                f.save(str(save_path))
                uploaded.append(f.filename)
        return jsonify({"uploaded": uploaded})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/fm/archive", methods=["POST"])
def fm_archive():
    _check_auth()
    try:
        data = request.get_json()
        p = _safe_path(data["path"])
        archive_path = p.parent / (p.name + ".tar.gz")
        with tarfile.open(str(archive_path), "w:gz") as tf:
            tf.add(str(p), arcname=p.name)
        return jsonify({"archive": str(archive_path)})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/fm/extract", methods=["POST"])
def fm_extract():
    _check_auth()
    try:
        data = request.get_json()
        p = _safe_path(data["path"])
        dest = _safe_path(data.get("dest", str(p.parent)))
        dest.mkdir(parents=True, exist_ok=True)
        if p.suffix in (".gz", ".bz2", ".xz") or p.name.endswith(".tar.gz"):
            with tarfile.open(str(p), "r:*") as tf:
                tf.extractall(str(dest))
        elif p.suffix == ".zip":
            import zipfile
            with zipfile.ZipFile(str(p), "r") as zf:
                zf.extractall(str(dest))
        else:
            return jsonify({"error": "Неизвестный формат архива"})
        return jsonify({"dest": str(dest)})
    except Exception as e:
        return jsonify({"error": str(e)})

