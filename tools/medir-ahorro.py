#!/usr/bin/env python3
"""Mide cuánto ahorra s0k1x-maestra en Claude Code con tareas reales.

Ejecuta cada tarea dos veces (sin la skill y con ella) con `claude -p`, cada vez
en una copia limpia de este repositorio, y compara tokens, coste y turnos según
lo que el propio Claude Code informa. Gasta créditos de tu cuenta.

Uso, desde la raíz del repositorio:
    python3 tools/medir-ahorro.py [--repeticiones N] [--salida informe.json]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(RAIZ, "plugins", "s0k1x-maestra")

TAREAS = [
    ("Localizar", "¿En qué archivo y línea se define la función `brief` de la skill s0k1x-maestra y qué devuelve?"),
    ("Explicar", "Explica para qué sirve tools/generar-plugins.py y cómo decide qué incluye cada plugin."),
    ("Subagente", "Usa un subagente para encontrar todos los archivos que mencionan «Portero» y dame la lista."),
    ("Releer", "Lee README.md entero. Después vuelve a leer README.md para comprobar cuántas skills dice que tiene el kit y respóndeme el número."),
    ("Editar", "En AVISOS.md, cambia el título principal «# Avisos, créditos y licencias» por «# Avisos y créditos». Solo eso."),
]


def copia_limpia():
    destino = tempfile.mkdtemp(prefix="medir-")
    shutil.copytree(RAIZ, os.path.join(destino, "repo"), symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "maestra"))
    return os.path.join(destino, "repo")


def ejecutar(prompt, con_skill):
    carpeta = copia_limpia()
    args = ["claude", "-p", prompt, "--output-format", "json", "--allowedTools", "Read,Grep,Glob,Edit,Agent,Bash"]
    if con_skill:
        args += ["--plugin-dir", PLUGIN]
    t = time.time()
    r = subprocess.run(args, cwd=carpeta, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600)
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        d = {"is_error": True, "result": r.stderr[-300:]}
    u = d.get("usage") or {}
    entrada = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    shutil.rmtree(os.path.dirname(carpeta), ignore_errors=True)
    return {"coste": float(d.get("total_cost_usd") or 0), "entrada": entrada,
            "salida": int(u.get("output_tokens") or 0), "turnos": int(d.get("num_turns") or 0),
            "segundos": round(time.time() - t, 1), "error": bool(d.get("is_error")),
            "modelos": sorted((d.get("modelUsage") or {}).keys()), "respuesta": str(d.get("result", ""))[:300]}


def media(filas, campo):
    vals = [f[campo] for f in filas if not f["error"]]
    return sum(vals) / len(vals) if vals else 0


def main(argv):
    reps = int(argv[argv.index("--repeticiones") + 1]) if "--repeticiones" in argv else 1
    salida = argv[argv.index("--salida") + 1] if "--salida" in argv else None
    if not shutil.which("claude"):
        sys.exit("Necesitas el comando claude en el PATH.")
    if not os.path.isdir(PLUGIN):
        sys.exit("Falta plugins/s0k1x-maestra: ejecuta python3 tools/generar-plugins.py")
    informe = []
    for nombre, prompt in TAREAS:
        fila = {"tarea": nombre, "sin": [], "con": []}
        for _ in range(reps):
            for modo in ("sin", "con"):
                res = ejecutar(prompt, modo == "con")
                fila[modo].append(res)
                print(f"{nombre:10} {modo:3} ${res['coste']:.4f} entrada={res['entrada']:>7} salida={res['salida']:>5} "
                      f"turnos={res['turnos']:>2} {'ERROR' if res['error'] else ''}", flush=True)
        informe.append(fila)
    print("\n| Tarea | Coste sin | Coste con | Ahorro | Tokens de salida sin → con |")
    print("|---|---|---|---|---|")
    tot_sin = tot_con = 0.0
    for f in informe:
        cs, cc = media(f["sin"], "coste"), media(f["con"], "coste")
        tot_sin, tot_con = tot_sin + cs, tot_con + cc
        ahorro = f"{(1 - cc / cs) * 100:+.0f} %".replace("+", "−") if cs and cc <= cs else (f"{(cc / cs - 1) * 100:.0f} % más" if cs else "—")
        print(f"| {f['tarea']} | ${cs:.4f} | ${cc:.4f} | {ahorro} | {media(f['sin'], 'salida'):.0f} → {media(f['con'], 'salida'):.0f} |")
    if tot_sin:
        print(f"| **Total** | ${tot_sin:.4f} | ${tot_con:.4f} | **{(1 - tot_con / tot_sin) * 100:.0f} %** | |")
    if salida:
        with open(salida, "w", encoding="utf-8") as fh:
            json.dump(informe, fh, indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
