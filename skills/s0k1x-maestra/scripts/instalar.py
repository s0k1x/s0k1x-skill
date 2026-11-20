#!/usr/bin/env python3
"""Activa s0k1x-maestra siempre (reglas + memo + sin relecturas) en cada agente.

Uso, desde la carpeta del proyecto:
  python3 instalar.py                    # asistente con menú (bienvenida y elegir agentes)
  python3 instalar.py detectados         # los agentes que tengas instalados
  python3 instalar.py todos              # todos los agentes, en este proyecto
  python3 instalar.py codex gemini       # solo algunos
  python3 instalar.py todos --global     # para todos tus proyectos
  python3 instalar.py todos --quitar     # deshacer
  python3 instalar.py copilot --modelo-rapido=<id>   # subagente barato en Copilot

Además crea subagentes baratos por dificultad donde el agente lo admite:
Claude Code (Haiku/Sonnet + hook que elige modelo), Gemini (Flash) y Copilot
(si le das --modelo-rapido, porque sus nombres de modelo cambian a menudo).

Agentes: claude codex gemini copilot cursor grok otros.
En Claude Code no hace falta si instalaste el plugin: ya trae sus hooks.
Es idempotente: repetirlo reemplaza lo suyo y no toca nada más.
"""
import json
import os
import re
import shlex
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(AQUI)
MEMO = os.path.join(AQUI, "memo.py")
PY = sys.executable or "python3"
MARCA = "s0k1x-maestra"
INI, FIN = "<!-- s0k1x-maestra:inicio -->", "<!-- s0k1x-maestra:fin -->"
MODELO_GEMINI = "gemini-3-flash-preview"
RAPIDO = ("Subagente barato para tareas fáciles y acotadas: buscar o localizar código, listar archivos, "
          "leer y resumir, contar, comprobar un dato, renombrados mecánicos. No para diseño, bugs difíciles "
          "ni seguridad.")
RAPIDO_CUERPO = ("Haz solo lo pedido, con el mínimo de lecturas: busca antes de abrir, lee tramos, acota la salida "
                 "de los comandos.\n\nDevuelve solo el resultado: rutas como `path:line`, datos exactos, sin prosa. "
                 "Si no encuentras nada, responde `No match.` Si la tarea necesita decidir diseño, depurar algo "
                 "ambiguo o tocar seguridad, para y responde `Escalar: <motivo en una línea>`.\n")
MEDIO = ("Subagente de coste medio para cambios bien especificados: implementar un arreglo ya diagnosticado, "
         "escribir o ajustar tests, cambios mecánicos en varios archivos. Lo difícil se queda en el modelo principal.")
MEDIO_CUERPO = ("Haz el cambio pedido y nada más: edición mínima, sin mejoras de paso, sin releer lo editado. "
                "Ejecuta la comprobación más corta que demuestre que funciona.\n\nDevuelve: archivos cambiados "
                "(`path:line`), comprobación y resultado. Si falta una decisión, responde `Escalar: <motivo>`.\n")
AGENTES = ("claude", "codex", "gemini", "copilot", "cursor", "grok", "otros")


def q(ruta):
    if os.name != "nt":
        return shlex.quote(ruta)
    ruta = ruta.replace("\\", "/")  # las barras normales valen en cmd, PowerShell y bash
    return '"%s"' % ruta if re.search(r"[\s&()^%!'\"]", ruta) else ruta


def ps(comando):
    """PowerShell no ejecuta una ruta entre comillas sin el operador &."""
    return "& " + comando if comando.startswith('"') else comando


def cmd(sub, agente, *extra):
    return " ".join([q(PY), q(MEMO), sub, "--agent", agente] + list(extra))


def es_nuestro(h):
    return MARCA in json.dumps(h) and "memo.py" in json.dumps(h)


def leer_json(ruta):
    if not os.path.exists(ruta):
        return {}
    try:
        return json.load(open(ruta, encoding="utf-8"))
    except ValueError:
        sys.exit(f"No toco {ruta}: no es JSON válido. Arréglalo y repite.")


def escribir_json(ruta, datos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("  ✓", ruta)


def fusionar(ruta, eventos, base=None, quitar=False):
    """Mete los hooks en eventos {nombre: [grupo]} quitando antes los nuestros."""
    datos = leer_json(ruta) or dict(base or {})
    hooks = datos.setdefault("hooks", {})
    for nombre in list(hooks):
        hooks[nombre] = [g for g in hooks[nombre] if not es_nuestro(g)]
        if not hooks[nombre]:
            del hooks[nombre]
    if not quitar:
        for nombre, grupos in eventos.items():
            hooks.setdefault(nombre, []).extend(grupos)
    if quitar and not hooks and set(datos) <= {"hooks", "version"}:
        if os.path.exists(ruta):
            os.remove(ruta)
            print("  ✗", ruta)
        return
    escribir_json(ruta, datos)


def grupo(comando, matcher=None, timeout=10, ms=False):
    g = {"hooks": [{"type": "command", "command": comando, "timeout": timeout * 1000 if ms else timeout}]}
    if matcher:
        g = {"matcher": matcher, **g}
    return g


def reglas():
    t = open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8").read()
    return t.split("---", 2)[2].strip() if t.startswith("---") else t


def bloque(con_reglas):
    memo = f"{q(PY)} {q(MEMO)}"
    texto = [INI, "## s0k1x-maestra (siempre activa)", ""]
    if con_reglas:
        texto.append(reglas())
    else:
        texto.append(f"Sigue siempre la skill s0k1x-maestra (`{os.path.join(SKILL, 'SKILL.md')}`) en cada respuesta. "
                     "Si sus reglas no están ya en tu contexto, léela una vez al empezar.")
    texto += ["", f"Memo del proyecto: `{memo} <brief|find|add|done|checkpoint>`. "
              "Si no ves una sección «Memo» en tu contexto, ejecuta `brief` una vez al empezar.", FIN]
    return "\n".join(texto) + "\n"


def poner_bloque(ruta, contenido, quitar=False, archivo_propio=False):
    if archivo_propio:
        if quitar:
            if os.path.exists(ruta):
                os.remove(ruta)
                print("  ✗", ruta)
            return
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        open(ruta, "w", encoding="utf-8").write(contenido)
        print("  ✓", ruta)
        return
    viejo = open(ruta, encoding="utf-8").read() if os.path.exists(ruta) else ""
    if INI in viejo and FIN in viejo:
        viejo = viejo[:viejo.index(INI)] + viejo[viejo.index(FIN) + len(FIN):].lstrip("\n")
    nuevo = viejo if quitar else (viejo.rstrip() + "\n\n" if viejo.strip() else "") + contenido
    if quitar and not nuevo.strip():
        if os.path.exists(ruta):
            os.remove(ruta)
            print("  ✗", ruta)
        return
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    open(ruta, "w", encoding="utf-8").write(nuevo)
    print("  ✓", ruta)


def subagente(ruta, cabecera, cuerpo, quitar):
    poner_bloque(ruta, "---\n" + cabecera + "\n---\n\n" + cuerpo, quitar, archivo_propio=True)


def instalar(agente, raiz, glob, quitar, modelo_rapido=None):
    home = os.path.expanduser("~")
    print(f"{'Quitando de' if quitar else 'Configurando'} {agente}:")
    if agente == "claude":
        fusionar(os.path.join(home if glob else raiz, ".claude", "settings.json"), {
            "SessionStart": [grupo(cmd("hook-start", "claude"))],
            "UserPromptSubmit": [grupo(cmd("hook-prompt", "claude"), timeout=5)],
            "PreToolUse": [grupo(cmd("hook-read", "claude"), "Read", 5),
                           grupo(cmd("hook-agent", "claude"), "Agent|Task", 5),
                           grupo(cmd("hook-shell", "claude"), "Bash", 5)],
            "PostToolUse": [grupo(cmd("hook-agent-fin", "claude"), "Agent|Task", 5)],
        }, quitar=quitar)
        d = os.path.join(home if glob else raiz, ".claude", "agents")
        subagente(os.path.join(d, "s0k1x-rapido.md"), "name: s0k1x-rapido\ndescription: " + json.dumps(RAPIDO, ensure_ascii=False) +
                  "\ntools: Read, Grep, Glob, Bash\nmodel: haiku", RAPIDO_CUERPO, quitar)
        subagente(os.path.join(d, "s0k1x-medio.md"), "name: s0k1x-medio\ndescription: " + json.dumps(MEDIO, ensure_ascii=False) +
                  "\nmodel: sonnet", MEDIO_CUERPO, quitar)
    elif agente == "codex":
        # PreToolUse de Codex solo cubre la shell: no hay lectura que deduplicar.
        fusionar(os.path.join(home if glob else raiz, ".codex", "hooks.json"), {
            "SessionStart": [grupo(cmd("hook-start", "codex"), "startup|resume|clear")],
            "UserPromptSubmit": [grupo(cmd("hook-prompt", "codex"), timeout=5)],
            "PreToolUse": [grupo(cmd("hook-shell", "codex"), "Bash", 5)],
        }, quitar=quitar)
        poner_bloque(os.path.join(home, ".codex", "AGENTS.md") if glob else os.path.join(raiz, "AGENTS.md"),
                     bloque(False), quitar)
    elif agente == "gemini":
        fusionar(os.path.join(home if glob else raiz, ".gemini", "settings.json"), {
            "SessionStart": [grupo(cmd("hook-start", "gemini"), ms=True)],
            "BeforeAgent": [grupo(cmd("hook-prompt", "gemini"), timeout=5, ms=True)],
            "BeforeTool": [grupo(cmd("hook-read", "gemini"), "read_file", 5, ms=True),
                           grupo(cmd("hook-shell", "gemini"), "run_shell_command", 5, ms=True)],
        }, quitar=quitar)
        poner_bloque(os.path.join(home if glob else raiz, ".gemini" if glob else "", "GEMINI.md"), bloque(False), quitar)
        subagente(os.path.join(home if glob else raiz, ".gemini", "agents", "s0k1x-rapido.md"),
                  "name: s0k1x-rapido\ndescription: " + json.dumps(RAPIDO, ensure_ascii=False) + "\nkind: local\ntools:\n  - read_file\n"
                  "  - grep_search\n  - glob\n  - list_directory\nmodel: " + MODELO_GEMINI + "\nmax_turns: 15",
                  RAPIDO_CUERPO, quitar)
    elif agente == "copilot":
        # userPromptSubmitted no puede añadir contexto en Copilot: solo inicio y lecturas.
        ruta = os.path.join(home, ".copilot", "hooks", "s0k1x-maestra.json") if glob else \
            os.path.join(raiz, ".github", "hooks", "s0k1x-maestra.json")
        if quitar:
            poner_bloque(ruta, "", True, archivo_propio=True)
        else:
            escribir_json(ruta, {"version": 1, "hooks": {
                "sessionStart": [{"type": "command", "bash": cmd("hook-start", "copilot"),
                                  "powershell": ps(cmd("hook-start", "copilot")), "timeoutSec": 10}],
                "preToolUse": [{"type": "command", "matcher": "view", "bash": cmd("hook-read", "copilot"),
                                "powershell": ps(cmd("hook-read", "copilot")), "timeoutSec": 5},
                               {"type": "command", "matcher": "bash", "bash": cmd("hook-shell", "copilot"),
                                "powershell": ps(cmd("hook-shell", "copilot")), "timeoutSec": 5}],
            }})
        if not glob:
            poner_bloque(os.path.join(raiz, ".github", "copilot-instructions.md"), bloque(False), quitar)
        if modelo_rapido or quitar:
            d = os.path.join(home, ".copilot", "agents") if glob else os.path.join(raiz, ".github", "agents")
            subagente(os.path.join(d, "s0k1x-rapido.agent.md"), "name: s0k1x-rapido\ndescription: " + json.dumps(RAPIDO, ensure_ascii=False) +
                      "\ntools: [\"read\", \"search\", \"execute\"]\nmodel: " + str(modelo_rapido), RAPIDO_CUERPO, quitar)
        else:
            print("  · Subagente barato no creado: pásale --modelo-rapido=<id de un modelo barato de Copilot>.")
    elif agente == "cursor":
        # En proyecto, las reglas van en una regla siempre activa (lo más fiable en Cursor)
        # y el hook solo añade el memo; en global no hay reglas en archivo, así que las mete el hook.
        extra = () if glob else ("--sin-reglas",)
        fusionar(os.path.join(home if glob else raiz, ".cursor", "hooks.json"), {
            "sessionStart": [{"command": ps(cmd("hook-start", "cursor", *extra)) if os.name == "nt" else cmd("hook-start", "cursor", *extra)}],
            "beforeSubmitPrompt": [{"command": ps(cmd("hook-prompt", "cursor")) if os.name == "nt" else cmd("hook-prompt", "cursor")}],
        }, base={"version": 1}, quitar=quitar)
        if not glob:
            mdc = "---\ndescription: s0k1x-maestra, siempre activa\nalwaysApply: true\n---\n\n" + bloque(True)
            poner_bloque(os.path.join(raiz, ".cursor", "rules", "s0k1x-maestra.mdc"), mdc, quitar, archivo_propio=True)
    elif agente == "grok":
        # En Grok, SessionStart y UserPromptSubmit no añaden contexto: las reglas van en .grok/rules
        # y el memo se pide con `brief`. PreToolUse sí puede bloquear relecturas.
        base_dir = os.path.join(home if glob else raiz, ".grok")
        ruta = os.path.join(base_dir, "hooks", "s0k1x-maestra.json")
        if quitar:
            poner_bloque(ruta, "", True, archivo_propio=True)
        else:
            escribir_json(ruta, {"hooks": {"PreToolUse": [grupo(cmd("hook-read", "grok"), "Read", 5),
                                                          grupo(cmd("hook-shell", "grok"), "Bash", 5)]}})
        poner_bloque(os.path.join(base_dir, "rules", "s0k1x-maestra.md"), bloque(True), quitar, archivo_propio=True)
    elif agente == "otros":
        poner_bloque(os.path.join(raiz, "AGENTS.md"), bloque(False), quitar)


NOMBRES = {"claude": "Claude Code", "codex": "Codex", "gemini": "Gemini CLI", "copilot": "GitHub Copilot CLI",
           "cursor": "Cursor", "grok": "Grok", "otros": "Otros (AGENTS.md)"}
SENALES = {"claude": (".claude", "claude"), "codex": (".codex", "codex"), "gemini": (".gemini", "gemini"),
           "copilot": (".copilot", "copilot"), "cursor": (".cursor", "cursor"), "grok": (".grok", "grok")}


def detectar():
    import shutil
    home = os.path.expanduser("~")
    return [a for a, (carpeta, binario) in SENALES.items()
            if os.path.isdir(os.path.join(home, carpeta)) or shutil.which(binario)]


def memo_mod():
    sys.dont_write_bytecode = True
    sys.path.insert(0, AQUI)
    import memo
    return memo


def menu():
    """Asistente interactivo: se abre al ejecutar el instalador sin argumentos."""
    memo = memo_mod()
    print(memo.bienvenida())
    vistos = detectar()
    print("\n  ¿En qué agentes la activo?\n")
    for i, a in enumerate(AGENTES, 1):
        marca = "  ✓ detectado" if a in vistos else ""
        nota = "  (el plugin ya la activa sola)" if a == "claude" else ""
        print(f"   {i}. {NOMBRES[a]}{marca}{nota}")
    defecto = [a for a in vistos if a != "claude"] or ["otros"]
    print(f"\n   Enter = los detectados ({', '.join(NOMBRES[a] for a in defecto)}) · t = todos · q = salir")
    r = input("   Elige (por ejemplo 2,3): ").strip().lower()
    if r == "q":
        print("  Nada instalado.")
        return 0
    if r == "t":
        elegidos = [a for a in AGENTES if a != "claude"]
    elif r:
        try:
            elegidos = [AGENTES[int(x) - 1] for x in r.replace(" ", "").split(",") if x]
        except (ValueError, IndexError):
            print("  No entiendo esa opción. Vuelve a ejecutar el instalador.")
            return 1
    else:
        elegidos = defecto
    g = input("\n   ¿Solo este proyecto (Enter) o todos tus proyectos (g)? ").strip().lower() == "g"
    modelo = None
    if "copilot" in elegidos:
        modelo = input("   Modelo barato para el subagente de Copilot (Enter = ninguno): ").strip() or None
    print()
    for a in elegidos:
        instalar(a, os.getcwd(), g, False, modelo)
    memo.marcar_vista()  # ya vio la bienvenida aquí: el agente no la repite
    despedida(elegidos, g)
    return 0


def despedida(pedidos, glob):
    print("\n  Listo. Abre una sesión nueva en tu agente y trabaja como siempre.")
    if "codex" in pedidos:
        print("  · Codex: la primera vez, revisa y confía en los hooks con /hooks.")
    if "grok" in pedidos and not glob:
        print("  · Grok: confía en el proyecto con /hooks-trust (o arranca con --trust).")
    print("  · Para deshacerlo: python3 instalar.py todos --quitar")


def main(argv):
    if not argv and sys.stdin.isatty():
        return menu()
    quitar = "--quitar" in argv
    modelo_rapido = next((a.split("=", 1)[1] for a in argv if a.startswith("--modelo-rapido=")), None)
    glob = "--global" in argv
    pedidos = [a for a in argv if not a.startswith("--")]
    if not pedidos or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "detectados" in pedidos:
        pedidos = [a for a in detectar() if a != "claude"] or ["otros"]
    if "todos" in pedidos:
        pedidos = [a for a in AGENTES if a != "claude"] + [a for a in pedidos if a == "claude"]
    malos = [a for a in pedidos if a not in AGENTES]
    if malos:
        sys.exit(f"Agente desconocido: {', '.join(malos)}. Válidos: {', '.join(AGENTES)}, todos, detectados.")
    raiz = os.getcwd()
    if not quitar and "--sin-bienvenida" not in argv:
        print(memo_mod().bienvenida() + "\n")
        memo_mod().marcar_vista()
    for a in dict.fromkeys(pedidos):
        instalar(a, raiz, glob, quitar, modelo_rapido)
    if not quitar:
        despedida(pedidos, glob)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
