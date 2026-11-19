# s0k1x-skill

Un kit de 36 skills para **Claude Code**, **Codex**, **Gemini CLI**, **Grok** y más de 70 agentes compatibles con `npx skills`, con 5 subagentes y 3 mods para Claude Code. Puedes instalarlo entero, y entonces la skill `s0k1x-skill` coordina todas las demás, o instalar cada skill por separado. La skill **`s0k1x-skill`** decide cuál usar en cada momento, las encadena y resuelve los choques entre ellas. Cada skill sigue funcionando por separado.

## Qué incluye

| Área | Skills |
|---|---|
| Diseño web | `s0k1x-estilo`, `s0k1x-componentes` (piezas con oficio, no genéricas), `s0k1x-pulido`, `s0k1x-movimiento` (animaciones) |
| Todo en una (escritura humana + ahorro) | `s0k1x-maestra` |
| Escritura | `s0k1x-humano` |
| Respuestas escuetas y ahorro | `s0k1x-breve`, `s0k1x-breve-ultra`, `s0k1x-breve-mega`, `s0k1x-breve-commit`, `s0k1x-breve-revisar`, `s0k1x-breve-explorar`, `s0k1x-breve-stats`, `s0k1x-breve-comprimir`, `s0k1x-breve-ayuda`, `s0k1x-equipo` |
| Nube externa (opcional, servicio de terceros) | `s0k1x-breve-configurar`, `s0k1x-breve-descubrir`, `s0k1x-breve-evidencias`, `s0k1x-breve-gestionar`, `s0k1x-breve-optimizar`, `s0k1x-breve-aprender` |
| Tokens y contexto | `s0k1x-tokens`, `s0k1x-tokens-salida`, `s0k1x-tokens-coach`, `s0k1x-tokens-panel`, `s0k1x-flota`, `s0k1x-retomar` |
| Ingeniería | `s0k1x-investigar`, `s0k1x-parche`, `s0k1x-construir`, `s0k1x-refactor`, `s0k1x-migrar`, `s0k1x-verificar` |
| Memoria | `s0k1x-memoria` |
| Coordinación | `s0k1x-skill` |

**Subagentes** (`agents/`): `s0k1x-equipo-investigador`, `s0k1x-equipo-constructor` y `s0k1x-equipo-revisor`, que usa la skill `s0k1x-equipo`, y `s0k1x-rapido` (Haiku) y `s0k1x-medio` (Sonnet), que usa `s0k1x-maestra` para dar a cada tarea el modelo más barato que la resuelve.

**Mods** (`hooks/register.tsx`):
- **Portero**: manda a Haiku los subagentes de tareas fáciles.
- **Vigilante**: avisa cuando la caché se ha enfriado antes de enviar un mensaje largo.
- **Panel**: el comando `/consumo` abre un panel con los tokens por agente.

`skill-creator` no está incluida porque ya viene con Claude.

## Instalación en Claude Code

Kit completo:

```
/plugin marketplace add s0k1x/s0k1x-skill
/plugin install s0k1x-skill@s0k1x-skill
```

O en un paso, en Claude Code 2.1.275 o posterior:

```
/plugin install s0k1x-skill --marketplace s0k1x/s0k1x-skill
```

### Instalar solo una skill

Después de añadir el marketplace, instala la skill que quieras por su nombre:

```
/plugin install s0k1x-maestra@s0k1x-skill
/plugin install s0k1x-componentes@s0k1x-skill
/plugin install s0k1x-pulido@s0k1x-skill
```

Cada skill es un plugin propio y trae lo que necesita para funcionar: `s0k1x-flota`, `s0k1x-retomar`, `s0k1x-tokens-panel` y `s0k1x-tokens-coach` incluyen `s0k1x-tokens`, y `s0k1x-equipo` incluye sus 3 subagentes. La skill coordinadora `s0k1x-skill` y los mods solo vienen con el kit completo.

### `s0k1x-maestra` se activa sola

En Claude Code, al instalar el kit completo o `s0k1x-maestra@s0k1x-skill`, un hook `SessionStart` la carga en cada sesión nueva, y otra vez tras `/clear`, `/compact` o al reanudar. No hace falta pedirla. Para apagarla en una sesión, di "modo normal".

Trae una **mini base de datos** SQLite por proyecto (`.claude/maestra/memo.db`, ignorada por git; necesita Python 3) para que Claude no tenga que volver a buscar ni arrastrar el chat entero:
- Guarda dónde está cada cosa, las decisiones, las tareas y los puntos de control. Al empezar cada sesión se inyecta un resumen corto, y con cada mensaje tuyo, las entradas que coinciden.
- Al acabar una tarea, Claude guarda un punto de control y te sugiere `/clear`. La sesión nueva sigue desde ahí sin releer el chat anterior, que es lo que más tokens gasta.
- Bloquea una vez la relectura de un archivo que ya está en el contexto y no ha cambiado. Para desactivarlo, `S0K1X_MAESTRA_READS=off`. Para que no se cargue nunca, define `S0K1X_MAESTRA=off` en el `env` de tu `settings.json`.

**En Codex, Gemini, Copilot, Cursor, Grok y los demás**, instálala con `npx skills` y ejecuta una vez su instalador desde la carpeta del proyecto (necesita Python 3):

```
npx skills add s0k1x/s0k1x-skill -a codex -s s0k1x-maestra
python3 .agents/skills/s0k1x-maestra/scripts/instalar.py todos
```

Con Grok la ruta es `.grok/skills/s0k1x-maestra/scripts/instalar.py`. Si solo quieres algunos agentes, pon sus nombres en vez de `todos` (`codex gemini copilot cursor grok otros`). Con `--global` vale para todos tus proyectos, y con `--quitar` se deshace. Lo que hace en cada agente:

| Agente | Reglas siempre | Memo al empezar | Memo con cada mensaje | Sin relecturas |
|---|---|---|---|---|
| Claude Code | hook | hook | hook | hook |
| Codex | hook + `AGENTS.md` | hook | hook | — (sus hooks de herramientas solo cubren la shell) |
| Gemini CLI | hook + `GEMINI.md` | hook | hook | hook (`read_file`) |
| GitHub Copilot CLI | hook + `copilot-instructions.md` | hook | — (Copilot no deja añadir contexto ahí) | hook (`view`) |
| Cursor | regla `.cursor/rules/s0k1x-maestra.mdc` | hook | hook | — |
| Grok | `.grok/rules/s0k1x-maestra.md` | lo pide la regla (`brief`) | — | hook |
| Otros | `AGENTS.md` | lo pide `AGENTS.md` | — | — |

En Codex, confía en los hooks con `/hooks` la primera vez; en Grok, con `/hooks-trust`.

**Modelo según la dificultad.** Las tareas fáciles (buscar, listar, resumir) van a un modelo barato, las medianas (cambios bien definidos, tests) a uno intermedio, y las difíciles (diseño, bugs ambiguos, seguridad) se quedan en el principal:
- **Claude Code**: un hook pone el modelo a cada subagente que se lanza sin indicarlo. Los fáciles van a Haiku, y los medianos a Sonnet si la sesión va en Opus. Lo que decide queda en `.claude/maestra/router.log`. Para desactivarlo, `S0K1X_MAESTRA_ROUTER=off`.
- **Gemini**: crea el subagente `s0k1x-rapido` con `gemini-3-flash-preview`.
- **Copilot**: crea `s0k1x-rapido` si le das el modelo barato que quieras, con `--modelo-rapido=<id>`.
- **Codex, Cursor, Grok y otros**: la skill les pide el mínimo esfuerzo de razonamiento en lo fácil y que te sugieran cambiar a un modelo más barato en tramos largos fáciles.

Instala **el kit completo o skills sueltas, no las dos cosas**: si no, la misma skill aparece dos veces con nombres distintos.

## Instalación en Codex

Codex usa las skills desde `.agents/skills/` del proyecto (o `~/.agents/skills/` con `-g`). Se instalan con `npx skills`:

```
# Todas, con la coordinadora s0k1x-skill
npx skills add s0k1x/s0k1x-skill -a codex -s '*'

# Solo una
npx skills add s0k1x/s0k1x-skill -a codex -s s0k1x-componentes

# Para todos tus proyectos, añade -g
npx skills add s0k1x/s0k1x-skill -a codex -g -s '*'
```

Si instalas sueltas `s0k1x-flota`, `s0k1x-retomar`, `s0k1x-tokens-panel` o `s0k1x-tokens-coach`, añade también `-s s0k1x-tokens`, porque usan su código. En Codex no hay subagentes ni mods: la coordinadora explica cómo hacer ese trabajo en el hilo principal. En Codex una skill se invoca con `$nombre`, por ejemplo `$s0k1x-pulido`.

Para que Codex use siempre el kit coordinado, puedes añadir esta línea al `AGENTS.md` de tu proyecto (en Claude Code, al `CLAUDE.md`):

```
Para cualquier tarea, usa la skill s0k1x-skill para elegir y encadenar las skills del kit.
```

## Instalación en Gemini, Grok y otros agentes

Igual que en Codex, cambiando el agente tras `-a`:

```
npx skills add s0k1x/s0k1x-skill -a gemini-cli -s '*'      # Gemini CLI (.agents/skills)
npx skills add s0k1x/s0k1x-skill -a grok -s '*'            # Grok (.grok/skills)
npx skills add s0k1x/s0k1x-skill -a cursor -s '*'          # Cursor
npx skills add s0k1x/s0k1x-skill -a github-copilot -s '*'  # GitHub Copilot
```

Añade `-g` para tenerlas en todos tus proyectos. El instalador admite más de 70 agentes.

## Descarga

```
git clone https://github.com/s0k1x/s0k1x-skill.git
```

O descarga el [ZIP](https://github.com/s0k1x/s0k1x-skill/archive/refs/heads/main.zip). Para probarlo sin instalarlo, desde la carpeta descargada: `claude --plugin-dir .`

## Web

La página del kit está en [`docs/index.html`](docs/index.html). Para publicarla, activa GitHub Pages en *Settings → Pages* con la rama `main` y la carpeta `/docs`.

## Uso

Pide la tarea con normalidad ("hazme una landing para una peluquería") y `s0k1x-skill` elige el flujo. También puedes nombrar una skill concreta, por ejemplo `/s0k1x-skill:s0k1x-pulido`.

Algunas skills necesitan tu permiso explícito: las skills de la nube externa y `s0k1x-breve-comprimir` envían datos fuera, y los arreglos de `s0k1x-tokens` cambian tu configuración.

## Requisitos

- Los mods necesitan una versión de Claude Code con soporte de mods (`hooks.json` con `modules`). Sin ella, las skills funcionan igual.
- Algunas skills usan Python 3 (`s0k1x-tokens`, `s0k1x-flota`, `s0k1x-retomar`) o descargan un binario la primera vez (`s0k1x-pulido`).

## Licencia

**Uso restringido.** Puedes instalar y usar `s0k1x-skill` tal cual. Está prohibido modificarlo, crear versiones derivadas, redistribuirlo o publicarlo como propio sin permiso escrito de s0k1x. Los términos completos están en [LICENSE](LICENSE).

Las skills de otros autores incluidas en el kit conservan sus propias licencias, indicadas en [AVISOS.md](AVISOS.md). `s0k1x-tokens` y sus skills hermanas usan PolyForm Noncommercial, que no permite el uso comercial.
