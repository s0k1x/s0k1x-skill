"""Tests de s0k1x-maestra: python -m unittest discover -s tests -v

Solo usan la biblioteca estándar. Cada test trabaja en carpetas temporales con
un HOME falso, así que no tocan tu configuración real.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(RAIZ, "skills", "s0k1x-maestra", "scripts")
MEMO = os.path.join(SCRIPTS, "memo.py")
INSTALAR = os.path.join(SCRIPTS, "instalar.py")
sys.dont_write_bytecode = True
sys.path.insert(0, SCRIPTS)
import memo  # noqa: E402


def bash_de_claude():
    """Claude Code usa Git Bash en Windows; el bash.exe de System32 es el lanzador de WSL."""
    if os.name == "nt":
        for ruta in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if os.path.exists(ruta):
                return ruta
        return None
    return shutil.which("bash")


BASH = bash_de_claude()


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def cargar(ruta):
    return json.loads(leer(ruta))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.home = tempfile.mkdtemp()
        self.env = {**os.environ, "HOME": self.home, "USERPROFILE": self.home, "PYTHONDONTWRITEBYTECODE": "1"}
        for v in ("CLAUDE_PROJECT_DIR", "GEMINI_PROJECT_DIR", "CURSOR_PROJECT_DIR", "GROK_WORKSPACE_ROOT", "S0K1X_MAESTRA"):
            self.env.pop(v, None)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def hook(self, sub, datos, agente="claude", *extra):
        datos = {"cwd": self.dir, **datos}
        r = subprocess.run([sys.executable, MEMO, sub, "--agent", agente, *extra], input=json.dumps(datos),
                           capture_output=True, text=True, env=self.env, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def json_hook(self, *a, **k):
        out = self.hook(*a, **k)
        return json.loads(out) if out else None

    def archivo(self, nombre="grande.txt", tam=30000):
        ruta = os.path.join(self.dir, nombre)
        with open(ruta, "w") as f:
            f.write("x" * tam)
        return ruta


class RecorteShell(unittest.TestCase):
    def test_casos(self):
        casos = {
            "npm install": "npm install --no-audit --no-fund --loglevel=error",
            "npm i lodash && npm test": "npm i --no-audit --no-fund --loglevel=error lodash && npm test",
            'echo "npm install"': 'echo "npm install"',
            "pip install -r r.txt": "pip install -q -r r.txt",
            "pip install -q x": "pip install -q x",
            "python -m pytest tests": "python -m pytest -q tests",
            "pytest -v": "pytest -v",
            "git clone u": "git clone -q u",
            "sudo apt-get install -y jq": "sudo apt-get -qq install -y jq",
            "cat <<EOF | npm install": "cat <<EOF | npm install",
            "ls | grep npm": "ls | grep npm",
        }
        for antes, despues in casos.items():
            self.assertEqual(memo.recortar_comando(antes), despues, antes)


class Hooks(Base):
    def test_inicio_formatos(self):
        for agente, clave in (("codex", "hookSpecificOutput"), ("gemini", "hookSpecificOutput"),
                              ("copilot", "additionalContext"), ("cursor", "additional_context")):
            d = self.json_hook("hook-start", {"source": "resume"}, agente)
            self.assertIn(clave, d, agente)
        self.assertIn("s0k1x-maestra ACTIVE", self.hook("hook-start", {"source": "resume"}, "grok"))

    def test_bienvenida_una_vez_y_novedades(self):
        d = self.json_hook("hook-start", {"source": "startup"})
        self.assertIn("Te damos la bienvenida", d["systemMessage"])
        self.assertIn("ACTIVE", d["hookSpecificOutput"]["additionalContext"])
        self.assertTrue(self.hook("hook-start", {"source": "startup"}).startswith("s0k1x-maestra ACTIVE"))
        with open(os.path.join(self.home, ".s0k1x-maestra", "estado.json"), "w") as f:
            json.dump({"bienvenida": "0.1.0"}, f)
        self.assertIn("actualizado", self.json_hook("hook-start", {"source": "startup"})["systemMessage"])
        d = self.json_hook("hook-start", {"source": "startup"}, "copilot") or {}
        self.assertNotIn("FIRST RUN", d.get("additionalContext", ""))

    def test_memo_y_prompt(self):
        subprocess.run([sys.executable, MEMO, "add", "donde", "pagos: api/pay.ts webhook"], cwd=self.dir,
                       env={**self.env, "CLAUDE_PROJECT_DIR": self.dir}, check=True, capture_output=True)
        self.assertIn("api/pay.ts", self.hook("hook-prompt", {"prompt": "arregla el webhook de pagos"}))
        d = self.json_hook("hook-prompt", {"prompt": "arregla el webhook de pagos"}, "cursor")
        self.assertTrue(d["continue"])
        self.assertEqual(self.json_hook("hook-prompt", {"prompt": "nada que ver con esto"}, "cursor"), {"continue": True})

    def test_relectura(self):
        ruta = self.archivo()
        base = {"session_id": "s", "tool_input": {"file_path": ruta}}
        self.assertEqual(self.hook("hook-read", {**base, "tool_use_id": "1"}), "")
        self.assertEqual(self.hook("hook-read", {**base, "tool_use_id": "1"}), "", "misma llamada, otro hook")
        d = self.json_hook("hook-read", {**base, "tool_use_id": "2"})
        self.assertEqual(d["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.hook("hook-read", {**base, "tool_use_id": "3"}), "", "el reintento pasa")
        with open(ruta, "a") as f:
            f.write("cambio")
        self.assertEqual(self.hook("hook-read", {**base, "tool_use_id": "4"}), "", "archivo cambiado")
        self.assertEqual(self.hook("hook-read", {**base, "tool_use_id": "5", "agent_id": "sub"}), "", "subagente aparte")

    def test_relectura_otros_formatos(self):
        ruta = self.archivo()
        g = {"session_id": "g", "tool_name": "read_file", "tool_input": {"file_path": ruta}}
        self.hook("hook-read", g, "gemini")
        time.sleep(1.1)  # sin tool_use_id, dos lecturas en menos de 1 s cuentan como la misma llamada
        self.assertEqual(self.json_hook("hook-read", g, "gemini")["decision"], "deny")
        c = {"sessionId": "c", "toolName": "view", "toolArgs": json.dumps({"path": os.path.basename(ruta)})}
        self.hook("hook-read", c, "copilot")
        time.sleep(1.1)
        self.assertEqual(self.json_hook("hook-read", c, "copilot")["permissionDecision"], "deny")

    def test_shell(self):
        d = self.json_hook("hook-shell", {"tool_input": {"command": "npm install"}})
        self.assertNotIn("permissionDecision", d["hookSpecificOutput"], "no debe aprobar comandos")
        self.assertIn("--loglevel=error", d["hookSpecificOutput"]["updatedInput"]["command"])
        self.assertIn("-q", self.json_hook("hook-shell", {"tool_input": {"command": "pytest"}}, "gemini")
                      ["hookSpecificOutput"]["tool_input"]["command"])
        self.assertIn("-q", self.json_hook("hook-shell", {"toolArgs": {"command": "pytest"}}, "copilot")
                      ["modifiedArgs"]["command"])
        self.assertEqual(self.hook("hook-shell", {"tool_input": {"command": "ls -la"}}), "")

    def test_aviso_chat_largo(self):
        tr = os.path.join(self.dir, "t.jsonl")

        def turno(tokens):
            with open(tr, "a") as f:
                f.write(json.dumps({"message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": tokens}}}) + "\n")
        datos = {"session_id": "s", "transcript_path": tr, "prompt": "hola"}
        turno(30_000)
        self.assertEqual(self.hook("hook-prompt", datos), "")
        turno(70_000)
        self.assertIn("/clear", self.hook("hook-prompt", datos))
        self.assertEqual(self.hook("hook-prompt", datos), "", "avisa una vez por nivel")
        turno(125_000)
        self.assertIn("125k", self.hook("hook-prompt", datos))


class Enrutador(Base):
    def entrada(self, desc, **extra):
        return {"tool_name": "Agent", "tool_input": {"description": desc, "prompt": desc, **extra}}

    def modelo(self, desc, **extra):
        d = self.json_hook("hook-agent", self.entrada(desc, **extra))
        return d["hookSpecificOutput"]["updatedInput"]["model"] if d else None

    def test_clasifica(self):
        self.assertEqual(self.modelo("Busca dónde se define checkToken"), "haiku")
        self.assertIsNone(self.modelo("Diseña la arquitectura de pagos"))
        self.assertIsNone(self.modelo("Busca algo", model="opus"))
        self.assertIsNone(self.modelo("Busca algo", subagent_type="s0k1x-rapido"))
        self.assertEqual(self.modelo("x", subagent_type="Explore"), "haiku")

    def test_no_aprueba_y_pide_escalar(self):
        d = self.json_hook("hook-agent", self.entrada("Busca los usos de foo"))
        self.assertNotIn("permissionDecision", d["hookSpecificOutput"])
        self.assertIn("Escalar:", d["hookSpecificOutput"]["updatedInput"]["prompt"])

    def test_aprende_de_escalados(self):
        desc = "Busca la configuración del servidor de pagos en config"
        self.assertEqual(self.modelo(desc), "haiku")
        self.hook("hook-agent-fin", {"tool_name": "Agent", "tool_input": {"description": desc, "prompt": desc},
                                     "tool_response": [{"type": "text", "text": "Escalar: hay tres configs"}]})
        self.assertIsNone(self.modelo(desc), "una parecida escaló: ya no va a Haiku")
        self.assertEqual(self.modelo("Lista los archivos de la carpeta docs"), "haiku", "las demás siguen igual")


class Instalador(Base):
    def instalar(self, *args):
        r = subprocess.run([sys.executable, INSTALAR, *args], cwd=self.dir, capture_output=True, text=True,
                           env=self.env, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def archivos(self):
        return sorted(os.path.relpath(os.path.join(r, f), self.dir) for r, _, fs in os.walk(self.dir) for f in fs
                      if os.sep + "maestra" + os.sep not in os.path.join(r, f) + os.sep)

    def test_todo_idempotente_y_quitar(self):
        os.makedirs(os.path.join(self.dir, ".gemini"))
        with open(os.path.join(self.dir, ".gemini", "settings.json"), "w") as f:
            json.dump({"ui": {"theme": "x"}}, f)
        with open(os.path.join(self.dir, "AGENTS.md"), "w") as f:
            f.write("# Mi proyecto\n")
        self.instalar("todos", "claude", "--modelo-rapido=m", "--sin-bienvenida")
        primera = {p: leer(os.path.join(self.dir, p)) for p in self.archivos()}
        self.instalar("todos", "claude", "--modelo-rapido=m", "--sin-bienvenida")
        segunda = {p: leer(os.path.join(self.dir, p)) for p in self.archivos()}
        self.assertEqual(primera, segunda, "repetir no cambia nada")
        self.assertEqual(cargar(os.path.join(self.dir, ".gemini", "settings.json"))["ui"], {"theme": "x"})
        self.instalar("todos", "claude", "--quitar")
        restantes = self.archivos()
        self.assertEqual(sorted(restantes), sorted([os.path.join(".gemini", "settings.json"), "AGENTS.md"]))
        self.assertEqual(leer(os.path.join(self.dir, "AGENTS.md")).strip(), "# Mi proyecto")

    def comandos(self):
        out = []
        for p in self.archivos():
            if p.endswith(".json"):
                for nombre, lista in cargar(os.path.join(self.dir, p)).get("hooks", {}).items():
                    for e in lista:
                        for h in e.get("hooks", [e]):
                            for k in ("command", "bash", "powershell"):
                                if h.get(k):
                                    out.append((p, k, h[k]))
        return out

    def test_los_comandos_generados_se_ejecutan(self):
        """Ejecuta cada comando como lo haría el agente: así se comprueban las comillas en cada sistema."""
        self.instalar("todos", "claude", "--sin-bienvenida")
        probados = 0
        for archivo, campo, comando in self.comandos():
            if campo == "powershell":
                if not shutil.which("powershell") and not shutil.which("pwsh"):
                    continue
                args = [shutil.which("powershell") or shutil.which("pwsh"), "-NoProfile", "-Command", comando]
                r = subprocess.run(args, input='{"source":"resume"}', capture_output=True, text=True, env=self.env, encoding="utf-8", errors="replace")
            else:
                r = subprocess.run(comando, shell=True, input='{"source":"resume"}', capture_output=True, text=True,
                                   env=self.env, cwd=self.dir, encoding="utf-8", errors="replace")
            self.assertEqual(r.returncode, 0, f"{archivo} [{campo}] {comando}\n{r.stderr}")
            if "hook-start" in comando:
                self.assertIn("s0k1x-maestra", r.stdout, f"{archivo}: {comando}")
            probados += 1
        self.assertGreater(probados, 8)

    def test_detecta_agentes(self):
        os.makedirs(os.path.join(self.home, ".gemini"))
        out = self.instalar("detectados", "--sin-bienvenida")
        self.assertIn("gemini", out)


class PluginClaude(unittest.TestCase):
    def test_nucleo_pequeno(self):
        """Medido: las reglas se pagan en cada turno, así que el núcleo debe seguir siendo corto."""
        self.assertLess(len(leer(os.path.join(RAIZ, "skills", "s0k1x-maestra", "SKILL.md")).encode()), 3500)

    def test_archivos_medianos_no_se_bloquean(self):
        d = tempfile.mkdtemp()
        try:
            ruta = os.path.join(d, "mediano.md")
            with open(ruta, "w") as f:
                f.write("x" * 10000)
            for uso in ("1", "2"):
                r = subprocess.run([sys.executable, MEMO, "hook-read"], capture_output=True, text=True, encoding="utf-8",
                                   input=json.dumps({"cwd": d, "session_id": "s", "tool_use_id": uso,
                                                     "tool_input": {"file_path": ruta}}))
                self.assertEqual(r.stdout.strip(), "")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_hooks_json_coherente(self):
        d = cargar(os.path.join(RAIZ, "hooks", "maestra.json"))
        texto = json.dumps(d)
        for sub in ("hook-start", "hook-prompt", "hook-read", "hook-agent", "hook-shell", "hook-agent-fin"):
            self.assertIn(sub, texto)
        copia = os.path.join(RAIZ, "plugins", "s0k1x-maestra", "hooks", "hooks.json")
        self.assertTrue(os.path.exists(copia), "regenera los plugins: python3 tools/generar-plugins.py")
        self.assertEqual(cargar(copia), d, "regenera los plugins: python3 tools/generar-plugins.py")

    @unittest.skipUnless(BASH, "sin bash")
    def test_comandos_del_plugin_se_ejecutan(self):
        """Claude Code ejecuta los hooks con bash (Git Bash en Windows): si falta python3, prueba python."""
        home = tempfile.mkdtemp()
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": RAIZ.replace("\\", "/"), "HOME": home, "USERPROFILE": home,
               "CLAUDE_PROJECT_DIR": home}
        try:
            for nombre, lista in cargar(os.path.join(RAIZ, "hooks", "maestra.json"))["hooks"].items():
                for g in lista:
                    for h in g["hooks"]:
                        r = subprocess.run([BASH, "-c", h["command"]], input='{"source":"resume","prompt":"hola"}',
                                           capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
                        self.assertEqual(r.returncode, 0, f"{nombre}: {r.stderr}")
                        if nombre == "SessionStart":
                            self.assertIn("s0k1x-maestra", r.stdout)
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
