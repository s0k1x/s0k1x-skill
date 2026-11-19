#!/usr/bin/env python3
"""s0k1x-maestra memo: mini base de datos SQLite por proyecto.

Guarda hechos, decisiones, ubicaciones y puntos de control para que Claude no
tenga que re-buscar ni arrastrar el chat entero: tras /clear, la sesión nueva
arranca con un resumen corto. También evita releer archivos sin cambios.

Uso (desde Claude o a mano):
  memo.py add <tipo> <texto>     tipo: dato|decision|donde|tarea|error
  memo.py done <id>              cierra una tarea
  memo.py forget <id>            borra una entrada
  memo.py find <consulta>        busca (FTS5)
  memo.py checkpoint <texto>     guarda el punto de control de la sesión
  memo.py brief                  resumen corto (lo que se inyecta al empezar)
  memo.py list                   todo

Hooks (leen JSON por stdin): hook-start, hook-prompt, hook-read.
Base: <proyecto>/.claude/maestra/memo.db (ignorada por git).
Desactivar: S0K1X_MAESTRA=off. Sin deduplicar lecturas: S0K1X_MAESTRA_READS=off.
"""
import json
import os
import re
import sqlite3
import sys
import time

TIPOS = ("dato", "decision", "donde", "tarea", "error")
BRIEF_MAX = 1800
PROMPT_MAX = 700


def proyecto(data=None):
    d = (data or {}).get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.environ.get("CLAUDE_PROJECT_DIR") or d


def conectar(data=None):
    carpeta = os.path.join(proyecto(data), ".claude", "maestra")
    os.makedirs(carpeta, exist_ok=True)
    gi = os.path.join(carpeta, ".gitignore")
    if not os.path.exists(gi):
        open(gi, "w").write("*\n")
    db = sqlite3.connect(os.path.join(carpeta, "memo.db"), timeout=3)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS memo(id INTEGER PRIMARY KEY, tipo TEXT, texto TEXT,
        abierto INTEGER DEFAULT 1, ts REAL);
    CREATE TABLE IF NOT EXISTS lecturas(clave TEXT PRIMARY KEY, firma TEXT,
        avisado INTEGER DEFAULT 0, ts REAL);
    """)
    try:
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memo_fts USING fts5(texto, content='memo', content_rowid='id')")
        db.executescript("""
        CREATE TRIGGER IF NOT EXISTS memo_ai AFTER INSERT ON memo BEGIN
          INSERT INTO memo_fts(rowid, texto) VALUES (new.id, new.texto); END;
        CREATE TRIGGER IF NOT EXISTS memo_ad AFTER DELETE ON memo BEGIN
          INSERT INTO memo_fts(memo_fts, rowid, texto) VALUES('delete', old.id, old.texto); END;
        """)
    except sqlite3.OperationalError:
        pass  # sin FTS5: find usa LIKE
    return db


def tiene_fts(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='memo_fts'").fetchone())


def buscar(db, consulta, limite=8):
    palabras = [p for p in re.findall(r"[\w./-]{3,}", consulta.lower())][:12]
    if not palabras:
        return []
    if tiene_fts(db):
        q = " OR ".join('"%s"' % p.replace('"', "") for p in palabras)
        try:
            return db.execute("""SELECT m.id, m.tipo, m.texto FROM memo_fts f JOIN memo m ON m.id=f.rowid
                WHERE memo_fts MATCH ? AND m.abierto>=0 ORDER BY bm25(memo_fts) LIMIT ?""", (q, limite)).fetchall()
        except sqlite3.OperationalError:
            pass
    cond = " OR ".join("lower(texto) LIKE ?" for _ in palabras)
    return db.execute(f"SELECT id, tipo, texto FROM memo WHERE {cond} ORDER BY ts DESC LIMIT ?",
                      [f"%{p}%" for p in palabras] + [limite]).fetchall()


def brief(db):
    partes = []
    cp = db.execute("SELECT texto, ts FROM memo WHERE tipo='checkpoint' ORDER BY ts DESC LIMIT 1").fetchone()
    if cp:
        partes.append("Último punto de control (%s):\n%s" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(cp[1])), cp[0]))
    tareas = db.execute("SELECT id, texto FROM memo WHERE tipo='tarea' AND abierto=1 ORDER BY ts DESC LIMIT 8").fetchall()
    if tareas:
        partes.append("Tareas abiertas:\n" + "\n".join(f"- #{i} {t}" for i, t in tareas))
    hechos = db.execute("""SELECT id, tipo, texto FROM memo WHERE tipo IN ('decision','donde','dato','error')
        ORDER BY ts DESC LIMIT 15""").fetchall()
    if hechos:
        partes.append("Memoria del proyecto:\n" + "\n".join(f"- #{i} [{t}] {x}" for i, t, x in hechos))
    texto = "\n\n".join(partes)
    return texto[:BRIEF_MAX] + ("\n…(memo.py find <consulta> para más)" if len(texto) > BRIEF_MAX else "")


def leer_stdin():
    try:
        return json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}


def skill_md():
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SKILL.md")
    try:
        t = open(ruta, encoding="utf-8").read()
    except OSError:
        return ""
    if t.startswith("---"):
        t = t.split("---", 2)[2]
    return t.strip()


def hook_start():
    data = leer_stdin()
    script = os.path.abspath(__file__)
    print("s0k1x-maestra ACTIVE: follow these rules every reply until \"modo normal\". "
          "Already loaded; do not call the Skill tool for it.\n\n" + skill_md() +
          f"\n\nMemo command: python3 \"{script}\" <add|done|forget|find|checkpoint|brief>")
    sys.stdout.flush()
    db = conectar(data)
    origen = data.get("source", "startup")
    if origen in ("startup", "clear", "compact"):
        # el contexto empieza de cero: lo leído antes ya no está en él
        db.execute("DELETE FROM lecturas WHERE clave LIKE ? OR ts < ?",
                   (data.get("session_id", "") + "|%", time.time() - 86400))
        db.commit()
    b = brief(db)
    if b:
        print("\n## Memo (contexto guardado: úsalo antes de buscar)\n" + b)


def hook_prompt():
    data = leer_stdin()
    texto = data.get("prompt", "")
    if len(texto) < 12:
        return
    db = conectar(data)
    filas = [f for f in buscar(db, texto, 5) if f[1] != "checkpoint"]
    if not filas:
        return
    s = "Memo relevante (de la base del proyecto, puede estar desactualizado):\n" + \
        "\n".join(f"- #{i} [{t}] {x}" for i, t, x in filas)
    print(s[:PROMPT_MAX])


def hook_read():
    if os.environ.get("S0K1X_MAESTRA_READS", "on") == "off":
        return
    data = leer_stdin()
    ti = data.get("tool_input") or {}
    ruta = ti.get("file_path")
    if not ruta or ti.get("pages"):
        return
    try:
        st = os.stat(ruta)
    except OSError:
        return
    if st.st_size < 2048:
        return  # archivos pequeños: no merece la pena
    clave = "|".join([data.get("session_id", ""), data.get("agent_id", "main"), os.path.abspath(ruta),
                      str(ti.get("offset", "")), str(ti.get("limit", ""))])
    firma = f"{st.st_mtime_ns}:{st.st_size}"
    db = conectar(data)
    fila = db.execute("SELECT firma, avisado FROM lecturas WHERE clave=?", (clave,)).fetchone()
    if fila and fila[0] == firma and not fila[1]:
        db.execute("UPDATE lecturas SET avisado=1, ts=? WHERE clave=?", (time.time(), clave))
        db.commit()
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "s0k1x-maestra: este tramo de " + os.path.basename(ruta) +
            " ya está en tu contexto y no ha cambiado. Úsalo sin releer. Si de verdad lo necesitas otra vez, repite la misma lectura y se permitirá."}}))
        return
    db.execute("INSERT OR REPLACE INTO lecturas(clave, firma, avisado, ts) VALUES (?,?,0,?)", (clave, firma, time.time()))
    db.commit()


def main(argv):
    if os.environ.get("S0K1X_MAESTRA", "on") == "off":
        return 0
    if not argv:
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    hooks = {"hook-start": hook_start, "hook-prompt": hook_prompt, "hook-read": hook_read}
    if cmd in hooks:
        try:
            hooks[cmd]()
        except Exception as e:  # un hook nunca debe romper la sesión
            print(f"s0k1x-maestra memo: {e}", file=sys.stderr)
        return 0
    db = conectar()
    if cmd == "add" and len(args) >= 2 and args[0] in TIPOS:
        cur = db.execute("INSERT INTO memo(tipo, texto, ts) VALUES (?,?,?)", (args[0], " ".join(args[1:]), time.time()))
        db.commit()
        print(f"#{cur.lastrowid}")
    elif cmd == "checkpoint" and args:
        db.execute("INSERT INTO memo(tipo, texto, ts) VALUES ('checkpoint',?,?)", (" ".join(args), time.time()))
        db.execute("DELETE FROM memo WHERE tipo='checkpoint' AND id NOT IN (SELECT id FROM memo WHERE tipo='checkpoint' ORDER BY ts DESC LIMIT 5)")
        db.commit()
        print("ok")
    elif cmd == "done" and args:
        db.execute("UPDATE memo SET abierto=0 WHERE id=?", (args[0].lstrip("#"),))
        db.commit()
        print("ok")
    elif cmd == "forget" and args:
        db.execute("DELETE FROM memo WHERE id=?", (args[0].lstrip("#"),))
        db.commit()
        print("ok")
    elif cmd == "find" and args:
        for i, t, x in buscar(db, " ".join(args)):
            print(f"#{i} [{t}] {x}")
    elif cmd == "brief":
        print(brief(db) or "(vacío)")
    elif cmd == "list":
        for i, t, x, a in db.execute("SELECT id, tipo, texto, abierto FROM memo ORDER BY ts"):
            print(f"#{i} [{t}{'' if a else ', hecha'}] {x}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
