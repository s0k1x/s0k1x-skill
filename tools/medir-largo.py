#!/usr/bin/env python3
"""Mide s0k1x-maestra en una sesión LARGA de Claude Code (10 peticiones seguidas).

Sin la skill, las 10 peticiones van en la misma conversación, que crece.
Con la skill, si el agente sugiere /clear, se hace lo que haría una persona:
la siguiente petición abre sesión nueva (y arranca desde el punto de control).
Al final comprueba que el trabajo quedó hecho, no solo el coste. Gasta créditos.

Uso:  python3 tools/medir-largo.py [--modo sin|con|ambos] [--salida informe.json]
Variables que se prueban: S0K1X_MAESTRA_AVISO_TOKENS, etc. (se heredan del entorno).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(RAIZ, "plugins", "s0k1x-maestra")

PETICIONES = [
    "Explícame en pocas líneas cómo está organizado este repositorio.",
    "¿Cómo genera tools/generar-plugins.py los plugins? Dime qué archivos y carpetas toca.",
    "Añade a tools/generar-plugins.py una opción --solo <skill> que regenere solo el plugin de esa skill "
    "sin borrar los demás. Impleméntalo.",
    "Ejecuta python3 tools/generar-plugins.py --solo s0k1x-maestra y comprueba que funciona y que los demás "
    "plugins siguen ahí.",
    "Otra cosa: en skills/s0k1x-maestra/scripts/memo.py, ¿dónde se construye el resumen (brief) y qué incluye?",
    "Cambia BRIEF_MAX a 1500 en ese archivo.",
    "Ejecuta los tests con python3 -m unittest discover -s tests y dime si pasan.",
    "Revisa README.md: si no menciona la opción --solo de generar-plugins.py, añádela en una línea en la "
    "sección «Tests y medición».",
    "Resume en tres líneas todo lo que hemos cambiado hoy en el repositorio.",
    "Escribe el mensaje de commit para estos cambios. No hagas el commit.",
]


def comprobar(carpeta):
    def leer(r):
        try:
            with open(os.path.join(carpeta, r), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""
    gen, memo, readme = leer("tools/generar-plugins.py"), leer("skills/s0k1x-maestra/scripts/memo.py"), leer("README.md")
    return {
        "opcion_solo": "--solo" in gen,
        "otros_plugins_intactos": os.path.isdir(os.path.join(carpeta, "plugins", "s0k1x-breve")),
        "brief_1500": bool(re.search(r"^BRIEF_MAX = 1500", memo, re.M)),
        "readme_solo": "--solo" in readme,
    }


def sesion(con_skill, registro):
    base = tempfile.mkdtemp(prefix="largo-")
    carpeta = os.path.join(base, "repo")
    shutil.copytree(RAIZ, carpeta, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__", "maestra"))
    subprocess.run(["git", "init", "-q"], cwd=carpeta)
    subprocess.run(["git", "add", "-A"], cwd=carpeta)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"], cwd=carpeta)
    sid, total, filas, limpiezas = None, 0.0, [], 0
    for n, peticion in enumerate(PETICIONES, 1):
        args = ["claude", "-p", peticion, "--output-format", "json", "--permission-mode", "acceptEdits",
                "--allowedTools", "Read,Grep,Glob,Edit,Write,Agent,Bash"]
        if con_skill:
            args += ["--plugin-dir", PLUGIN]
        if sid:
            args += ["--resume", sid]
        r = subprocess.run(args, cwd=carpeta, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900)
        try:
            d = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            d = {"is_error": True, "result": r.stderr[-300:]}
        u = d.get("usage") or {}
        coste = float(d.get("total_cost_usd") or 0)
        total += coste
        ctx = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        respuesta = str(d.get("result", ""))
        sid = d.get("session_id") or sid
        limpia = con_skill and "/clear" in respuesta
        if limpia:
            sid, limpiezas = None, limpiezas + 1  # la persona hace /clear: la siguiente empieza de cero
        filas.append({"n": n, "coste": round(coste, 4), "entrada": ctx, "salida": int(u.get("output_tokens") or 0),
                      "turnos": d.get("num_turns"), "clear": limpia, "error": bool(d.get("is_error")),
                      "modelos": sorted((d.get("modelUsage") or {}).keys()), "respuesta": respuesta[:400]})
        print(f"{'con' if con_skill else 'sin'} #{n:>2} ${coste:.4f} entrada={ctx:>7} salida={filas[-1]['salida']:>5}"
              f"{' /clear' if limpia else ''}{' ERROR' if filas[-1]['error'] else ''}", flush=True)
    ok = comprobar(carpeta)
    memo_db = os.path.isfile(os.path.join(carpeta, ".claude", "maestra", "memo.db"))
    shutil.rmtree(base, ignore_errors=True)
    registro["con" if con_skill else "sin"] = {"total": round(total, 4), "limpiezas": limpiezas, "checks": ok,
                                               "memo": memo_db, "peticiones": filas}


def main(argv):
    modo = argv[argv.index("--modo") + 1] if "--modo" in argv else "ambos"
    salida = argv[argv.index("--salida") + 1] if "--salida" in argv else None
    registro = {}
    hilos = [threading.Thread(target=sesion, args=(m == "con", registro))
             for m in (("sin", "con") if modo == "ambos" else (modo,))]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    for m, r in registro.items():
        print(f"\n{m}: total ${r['total']:.4f} · /clear {r['limpiezas']} · checks {r['checks']} · memo {r['memo']}")
    if "sin" in registro and "con" in registro and registro["sin"]["total"]:
        print(f"Ahorro: {(1 - registro['con']['total'] / registro['sin']['total']) * 100:.1f} %")
    if salida:
        with open(salida, "w", encoding="utf-8") as f:
            json.dump(registro, f, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
