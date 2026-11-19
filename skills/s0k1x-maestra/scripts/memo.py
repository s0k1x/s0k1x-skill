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

Hooks (leen JSON por stdin): hook-start, hook-prompt, hook-read
  [--agent claude|codex|gemini|copilot|cursor|grok] [--sin-reglas].
Para configurar otros agentes: instalar.py.
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
    for var in ("CLAUDE_PROJECT_DIR", "GEMINI_PROJECT_DIR", "CURSOR_PROJECT_DIR", "GROK_WORKSPACE_ROOT"):
        if os.environ.get(var):
            return os.environ[var]
    return (data or {}).get("cwd") or os.getcwd()


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
        db.execute("ALTER TABLE lecturas ADD COLUMN uso TEXT")
    except sqlite3.OperationalError:
        pass  # ya existe
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
        d = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    if not isinstance(d, dict):
        return {}
    # normaliza camelCase (Copilot) y nombres de otros agentes
    for camel, snake in (("sessionId", "session_id"), ("toolName", "tool_name"), ("toolArgs", "tool_input"),
                         ("agentId", "agent_id"), ("conversation_id", "session_id")):
        if camel in d and snake not in d:
            d[snake] = d[camel]
    if isinstance(d.get("tool_input"), str):
        try:
            d["tool_input"] = json.loads(d["tool_input"])
        except ValueError:
            d["tool_input"] = {}
    if not d.get("cwd") and d.get("workspace_roots"):
        d["cwd"] = d["workspace_roots"][0]
    return d


def skill_md():
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SKILL.md")
    try:
        t = open(ruta, encoding="utf-8").read()
    except OSError:
        return ""
    if t.startswith("---"):
        t = t.split("---", 2)[2]
    return t.strip()


# Cómo entrega cada agente el contexto y las denegaciones.
#   claude: texto plano. codex/gemini: hookSpecificOutput. copilot: camelCase.
#   cursor: snake_case. grok/otros: texto plano (si el agente lo ignora, no pasa nada).
def emitir_contexto(agente, evento, texto):
    if not texto:
        if agente == "cursor" and evento == "prompt":
            print(json.dumps({"continue": True}))
        return
    if agente in ("codex", "gemini"):
        nombre = {"start": "SessionStart", "prompt": "BeforeAgent" if agente == "gemini" else "UserPromptSubmit"}[evento]
        print(json.dumps({"hookSpecificOutput": {"hookEventName": nombre, "additionalContext": texto}}))
    elif agente == "copilot":
        print(json.dumps({"additionalContext": texto}))
    elif agente == "cursor":
        out = {"additional_context": texto}
        if evento == "prompt":
            out["continue"] = True
        print(json.dumps(out))
    else:
        print(texto)


def emitir_denegacion(agente, razon):
    if agente == "gemini":
        out = {"decision": "deny", "reason": razon}
    elif agente == "copilot":
        out = {"permissionDecision": "deny", "permissionDecisionReason": razon}
    else:  # claude, codex, grok: formato de Claude Code
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": razon}}
    print(json.dumps(out))


def hook_start(agente, reglas=True):
    data = leer_stdin()
    script = os.path.abspath(__file__)
    partes = []
    if reglas:
        partes.append("s0k1x-maestra ACTIVE: follow these rules every reply until \"modo normal\". "
                      "Already loaded; do not load the skill again.\n\n" + skill_md())
    partes.append(f"Memo command: \"{sys.executable or 'python3'}\" \"{script}\" <add|done|forget|find|checkpoint|brief>")
    try:
        db = conectar(data)
        if data.get("source", "startup") in ("startup", "clear", "compact", "new"):
            # el contexto empieza de cero: lo leído antes ya no está en él
            db.execute("DELETE FROM lecturas WHERE clave LIKE ? OR ts < ?",
                       (str(data.get("session_id", "")) + "|%", time.time() - 86400))
            db.commit()
        if data.get("model"):
            db.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
            db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", ("modelo", str(data["model"]).lower()))
            db.commit()
        b = brief(db)
        if b:
            partes.append("## Memo (contexto guardado: úsalo antes de buscar)\n" + b)
    except Exception as e:
        print(f"s0k1x-maestra memo: {e}", file=sys.stderr)
    emitir_contexto(agente, "start", "\n\n".join(partes))


def hook_prompt(agente):
    data = leer_stdin()
    texto = data.get("prompt") or ""
    salida = ""
    if len(texto) >= 12:
        filas = [f for f in buscar(conectar(data), texto, 5) if f[1] != "checkpoint"]
        if filas:
            salida = ("Memo relevante (de la base del proyecto, puede estar desactualizado):\n" +
                      "\n".join(f"- #{i} [{t}] {x}" for i, t, x in filas))[:PROMPT_MAX]
    emitir_contexto(agente, "prompt", salida)


def hook_read(agente):
    if os.environ.get("S0K1X_MAESTRA_READS", "on") == "off":
        return
    data = leer_stdin()
    ti = data.get("tool_input") or {}
    if not isinstance(ti, dict):
        return
    ruta = next((ti[k] for k in ("file_path", "path", "absolute_path", "target_file", "filePath") if ti.get(k)), None)
    if not ruta or ti.get("pages"):
        return
    if not os.path.isabs(ruta):
        ruta = os.path.join(proyecto(data), ruta)
    try:
        st = os.stat(ruta)
    except OSError:
        return
    if st.st_size < 2048 or not os.path.isfile(ruta):
        return  # archivos pequeños o carpetas: no merece la pena
    tramo = [str(ti.get(k, "")) for k in ("offset", "limit", "start_line", "end_line", "view_range")]
    clave = "|".join([str(data.get("session_id", "")), str(data.get("agent_id") or "main"), os.path.abspath(ruta)] + tramo)
    firma = f"{st.st_mtime_ns}:{st.st_size}"
    db = conectar(data)
    uso = str(data.get("tool_use_id") or data.get("toolUseId") or data.get("tool_call_id") or "")
    fila = db.execute("SELECT firma, avisado, ts, uso FROM lecturas WHERE clave=?", (clave,)).fetchone()
    if fila and fila[0] == firma and ((uso and fila[3] == uso) or (not uso and time.time() - fila[2] < 1)):
        return  # la misma llamada vista por otro hook (Grok y Copilot también leen los de Claude/Cursor)
    if fila and fila[0] == firma and not fila[1]:
        db.execute("UPDATE lecturas SET avisado=1, ts=?, uso=? WHERE clave=?", (time.time(), uso, clave))
        db.commit()
        emitir_denegacion(agente, "s0k1x-maestra: este tramo de " + os.path.basename(ruta) +
                          " ya está en tu contexto y no ha cambiado. Úsalo sin releer. Si de verdad lo necesitas"
                          " otra vez, repite la misma lectura y se permitirá.")
        return
    db.execute("INSERT OR REPLACE INTO lecturas(clave, firma, avisado, ts, uso) VALUES (?,?,0,?,?)",
               (clave, firma, time.time(), uso))
    db.commit()


# --- Enrutador: modelo del subagente según la dificultad (Claude Code) -------
SOLO_LECTURA = {"explore", "claude-code-guide", "statusline-setup", "web-fetch", "s0k1x-breve-explorar"}
CON_MODELO_PROPIO = ("s0k1x-rapido", "s0k1x-medio", "s0k1x-equipo-")
DIFICIL = re.compile(r"diseñ|arquitect|design|architect|segur|secur|vulnerab|refactor|migra|depur|debug|"
                     r"race|concurren|rendimiento|performance|por qu[eé]|\bwhy\b|causa|root cause|investig|"
                     r"plan\b|planific|decid|revis|review|audit|optimi|ambig|complej|complex")
FACIL = re.compile(r"\bbusca|encuentra|localiza|d[oó]nde (est|se)|lista|cuenta|resume|resum|\blee\b|"
                   r"\bfind\b|search|locate|where is|\blist\b|count|summar|\bread\b|grep|renombr|rename|"
                   r"formatea|\bformat\b|traduce|translate|extrae|extract")
MEDIO = re.compile(r"implement|añade|agrega|escribe (el |los |un |unos )?test|write tests?|add tests?|"
                   r"arregla|\bfix\b|actualiza|update|crea (un|una|el|la)|create")


def elegir_modelo(tipo, texto, modelo_sesion):
    if tipo.lower() in SOLO_LECTURA:
        return "haiku", "subagente de solo lectura"
    if DIFICIL.search(texto):
        return None, "difícil: hereda el modelo principal"
    if FACIL.search(texto) and not MEDIO.search(texto):
        return "haiku", "fácil"
    if MEDIO.search(texto) and "opus" in modelo_sesion:
        return "sonnet", "media"
    return None, "sin señal clara: hereda"


def hook_agent(agente):
    if os.environ.get("S0K1X_MAESTRA_ROUTER", "on") == "off":
        return
    data = leer_stdin()
    ti = data.get("tool_input") or {}
    if not isinstance(ti, dict) or ti.get("model"):
        return  # quien lanza el subagente ya eligió
    tipo = str(ti.get("subagent_type") or "general-purpose")
    if tipo == "fork" or tipo.startswith(CON_MODELO_PROPIO):
        return
    texto = (str(ti.get("description", "")) + " " + str(ti.get("prompt", ""))[:1500]).lower()
    db = conectar(data)
    try:
        fila = db.execute("SELECT v FROM meta WHERE k='modelo'").fetchone()
    except sqlite3.OperationalError:
        fila = None
    modelo, motivo = elegir_modelo(tipo, texto, fila[0] if fila else "")
    try:
        with open(os.path.join(proyecto(data), ".claude", "maestra", "router.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {tipo} -> {modelo or 'hereda'} ({motivo}): "
                    f"{str(ti.get('description', ''))[:80]}\n")
    except OSError:
        pass
    if modelo:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                 "updatedInput": {**ti, "model": modelo}}}))


def main(argv):
    if os.environ.get("S0K1X_MAESTRA", "on") == "off":
        return 0
    if not argv:
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd in ("hook-start", "hook-prompt", "hook-read", "hook-agent"):
        agente = "claude"
        if "--agent" in args and args.index("--agent") + 1 < len(args):
            agente = args[args.index("--agent") + 1]
        try:
            if cmd == "hook-start":
                hook_start(agente, reglas="--sin-reglas" not in args)
            elif cmd == "hook-prompt":
                hook_prompt(agente)
            elif cmd == "hook-agent":
                hook_agent(agente)
            else:
                hook_read(agente)
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
