# claude-session-publisher
<!-- source-digest: 7393d862a28bb989 -->

[![Tests](https://github.com/fabiocampolim-design/claude-session-publisher/actions/workflows/tests.yml/badge.svg)](https://github.com/fabiocampolim-design/claude-session-publisher/actions/workflows/tests.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Dependencies: stdlib only](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen)](transcript_archiver.py)
[![Platform: Windows | Linux | macOS](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)](#requisitos)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

[English](README.md) · [Português (Brasil)](README.pt-BR.md) · **Español** · [Deutsch](README.de.md) · [Français](README.fr.md)

*Traducción del README en inglés, que es la referencia; los comandos, nombres de archivo, opciones y bloques de código se mantienen como en el original.*

Convierte una sesión de Claude Code en un único documento autocontenido — HTML,
texto plano, Markdown, LaTeX o PDF — con un informe de fidelidad que demuestra
que nada se descartó en silencio.

> **Los comentarios se agradecen mucho.** Esta herramienta es joven y las
> transcripciones son salvajes: si alguna sesión tuya se renderiza de forma
> extraña, si un número del informe de fidelidad no cuadra, o si falta un
> formato que necesitas, por favor
> [abre una incidencia](https://github.com/fabiocampolim-design/claude-session-publisher/issues).

**Por qué existe.** La investigación asistida por IA necesita el mismo estándar
de registro que cualquier otro método: cuando un resultado se alcanzó en
conversación con un modelo, la transparencia y la reproducibilidad de la
ciencia dependen de poder citar y auditar esa conversación — literal, completa
y en una forma que un artículo pueda referenciar. Para eso sirve esta
herramienta. *Pero* construirla también nos enseñó que los propios registros
son frágiles: en agosto de 2026 una reinstalación de Claude Desktop —
recomendada por el soporte tras un fallo al mejorar el plan — borró mis
sesiones de agente local, y la exportación de datos de la cuenta resultó no
incluirlas. Proyectos enteros, perdidos para siempre. Así que la herramienta
interesa más allá de la ciencia: cualquiera cuyas conversaciones importen
debería guardar su propia copia. El lema: **archiva pronto, archiva a menudo**
— un archivo solo existe si lo haces mientras los ficheros todavía existen.

Claude Code escribe cada sesión en un fichero JSON Lines bajo
`~/.claude/projects/`. Ese fichero es completo pero ilegible: registros
entremezclados, cargas útiles de herramientas, contabilidad interna del
*harness*. Este script analiza cada tipo de registro y lo convierte en un
modelo tipado, decide por clase si **renderizarlo**, **plegarlo** o
**contarlo**, e imprime un informe de fidelidad que reconcilia los tres números
con el recuento de registros del origen — de modo que la diferencia entre *"no
está en la transcripción"* y *"no está en el origen"* siempre sea visible en la
página.

Un solo fichero, solo biblioteca estándar, sin paso de instalación.

```bash
python transcript_archiver.py <session-id>
python transcript_archiver.py <session-id> --format html,text,markdown,latex,pdf
python transcript_archiver.py --index          # reconstruye la página índice
```

Referencia completa: [`docs/USER_MANUAL.es.md`](docs/USER_MANUAL.es.md)
(también en [HTML](docs/USER_MANUAL.es.html) y
[PDF](docs/USER_MANUAL.es.pdf)) enumera todas las opciones, salidas,
características y limitaciones conocidas. ¿La vas a manejar con un agente de
IA? Entrégale [`AGENTS.md`](AGENTS.md). Los cambios están en
[`CHANGELOG.md`](CHANGELOG.md); cómo contribuir en
[`CONTRIBUTING.md`](CONTRIBUTING.md) y las decisiones de diseño — incluida la
nota de amenazas — en [`docs/DESIGN.md`](docs/DESIGN.md). Política de
seguridad: [`SECURITY.md`](SECURITY.md). De qué depende y qué reproduce:
[`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md). Dónde se ha ejecutado
realmente: [`docs/platforms.md`](docs/platforms.md).

## Características

- **Cinco formatos a partir de un solo análisis** — HTML, texto plano,
  Markdown, LaTeX y PDF se renderizan todos desde el mismo modelo tipado de la
  transcripción, de modo que un turno no puede aparecer en un formato y
  desaparecer en otro. `--fragment` emite un cuerpo LaTeX listo para `\input`
  en un manuscrito, transliterado para compilar tanto con pdflatex como con
  XeLaTeX.
- **Las transcripciones de subagentes forman parte del registro** — la
  conversación de un agente en segundo plano
  (`<session-id>/subagents/agent-*.jsonl`) se renderiza como apéndice enlazado
  en todos los formatos, su uso se suma a la tabla de costes, y cada fichero se
  lista en el informe de fidelidad. `--subagents off` suprime el contenido,
  pero nunca la declaración.
- **Tres orígenes** — sesiones de Claude Code, sesiones *cowork* de Claude
  Desktop (modo de agente local) vía `--cowork-root`, y conversaciones de
  claude.ai vía `--import-claude-ai conversations.json` (desde Settings →
  Privacy → Export data), todas por la misma tubería y con el mismo informe de
  fidelidad.
- **Un informe de fidelidad en cada página** — cada registro de origen se
  renderiza, se pliega en un turno anterior, o se cuenta como deliberadamente
  no renderizado, y los tres números se reconcilian con el recuento de
  registros del origen. Las líneas corruptas también se cuentan. Si algo se le
  escapa al analizador, la página lo dice en lugar de ocultarlo.
- **Los turnos humanos son literales** — el texto escrito y lo pegado nunca
  pasan por un renderizador de markdown, así que un *traceback* pegado o un
  *benchmark* en columnas se mantiene byte a byte intacto en todos los
  formatos.
- **Etiquetas de referencia citables** — cada prompt es P1, P2, … y cada
  respuesta R1, R2, …, secuenciales y únicos dentro del documento (los turnos
  de subagentes llevan el prefijo A1., A2., …), de modo que un artículo pueda
  decir "en el prompt P32" o "en la respuesta A2.R4". Las etiquetas aparecen
  junto a la etiqueta del interlocutor en todos los formatos y son anclas en el
  HTML (`#P32` enlaza directamente al prompt).
- **Resolución de cadenas de sesión** — una conversación reanudada o puenteada
  se escribe en un fichero nuevo que repite los registros anteriores; el
  archivador encuentra el fichero más completo comparando conjuntos de uuids de
  registro, sigue continuaciones genuinas y se niega a seguir bifurcaciones.
- **Contabilidad de uso y coste** — tokens por modelo, deduplicados por
  `requestId` (sumar los registros de forma ingenua sobreestima la salida ~2,3×
  en sesiones con muchas herramientas), con lecturas de caché, escrituras de
  caché de 5 minutos frente a 1 hora, y una estimación de coste a precio de
  tarifa — **junto al coste que informa el propio Claude Code** desde su
  medidor `cost-state` (Claude Code ≥ 2.1.9x), sumado a lo largo de las
  ejecuciones de la sesión y reunido entre los ficheros de una sesión
  reanudada, y marcado como *parcial* cuando la sesión empezó antes de su
  primera ejecución medida.
- **El harness es visible** — la salida de los hooks, los ficheros inyectados,
  las cargas de *skills*, los resúmenes de compactación y los registros de
  sistema se renderizan en un carril plegado con la evidencia de clasificación
  de cada uno, en vez de desaparecer o hacerse pasar por cosas que escribiste
  tú.
- **Honesto sobre el pensamiento** — Claude Code solicita el pensamiento con
  `display: "omitted"`, así que el archivo muestra *que* Claude pensó en un
  punto dado y dice claramente que el texto nunca llega a la transcripción.
- **HTML autocontenido** — disposición estilo chat, temas claro y oscuro con un
  conmutador que el navegador recuerda, un cuadro de búsqueda que oculta los
  turnos que no coinciden, índice filtrable, conmutadores por carril,
  navegación por teclado, ningún recurso externo. `--paginate N` divide una
  sesión muy grande en páginas de N turnos, con el índice lateral y los enlaces
  de subagentes apuntando entre páginas.
- **Un índice vivo con búsqueda en todos los archivos** — `--index` construye
  una página ordenable de todas las sesiones en disco, con una columna de
  actividad cuyas edades envejecen en el navegador sin regeneración, y un
  cuadro de búsqueda sobre **todos los prompts de todos los archivos**
  (incrustados al indexar, con enlace directo al ancla `#P` del prompt en su
  página); `--index --watch 300` lo mantiene regenerándose en bucle y la página
  se recarga sola, dando un panel de ritmo lento de qué conversaciones están
  activas ahora mismo.
- **Cuatro idiomas más para el mobiliario de la página** — `--lang
  pt-BR|es|de|fr` (o `CLAUDE_ARCHIVE_LANG`) pone las palabras del propio
  archivador — etiquetas, títulos, notas, el informe de fidelidad, el índice —
  en portugués de Brasil, español, alemán o francés, en todos los formatos. La
  conversación nunca se traduce: prompts, respuestas, entrada/salida de
  herramientas y texto de sistema son los mismos bytes en cualquier idioma, y
  la batería de pruebas lo demuestra fragmento a fragmento.
- **Salida de herramientas bajo tu control** — `--tool-output on|off`
  independiente del formato, y salidas largas elididas por el medio (`--full`
  para conservarlo todo), con cada elisión contada en la página.
- **Sobrevive a transcripciones reales** — bytes NUL de capturas de consola en
  UTF-16, códigos ANSI, emoji, líneas de 65.000 caracteres, llamadas a
  herramientas sin resolver y líneas no analizables se manejan, se cuentan y se
  informan.
- **Cada ejecución queda registrada** — `--verbose`/`--quiet` para la consola,
  y un registro de auditoría por invocación en `<archive-dir>/logs/` (línea de
  comandos exacta, versiones, todos los mensajes, desenlace), con `--log-dir`
  para moverlo.
- **Se comprueba lo que compila, no solo el código de salida 0** — la ruta
  LaTeX divide los turnos demasiado grandes y trocea las tablas largas o anchas
  para que nada se salga de la página, y la batería compila una sesión cargada
  de tablas y cuenta las páginas para demostrar que las filas llegaron. Un
  código de salida limpio no es prueba de que el contenido sobreviviera al
  tipógrafo.
- Solo biblioteca estándar, un fichero, 528 comprobaciones en la batería de
  pruebas, pyflakes y CI en Linux/Windows/macOS.

## Cómo se compara

[simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts)
es la herramienta más conocida de este ámbito: instalable con pip, con selector
interactivo de sesiones, HTML paginado y apto para móvil, cronologías de
commits de git y publicación en un Gist de GitHub con una orden. Otros
exportadores ([claude-session-exporter](https://github.com/rubicon/claude-session-exporter)
y varios parecidos) apuntan a Markdown para bóvedas de notas. El foco de esta
herramienta es otro: **fidelidad de archivo e impresión** — el informe de
fidelidad reconciliado, turnos humanos literales, contabilidad de uso y coste,
resolución de cadenas y salida LaTeX/PDF apta para el apéndice de un artículo.
Si quieres un enlace web rápido para compartir, usa la herramienta de Simon; si
quieres un registro completo y auditable o un documento, usa esta.

## Hoja de ruta

Lagunas que merece la pena cerrar:

- **Soporte de primera clase en Linux y macOS.** La CI ejecuta la batería en
  Linux y macOS. Linux tuvo su primera ejecución real el 31/08/2026 (WSL2
  Ubuntu, Python 3.14): HTML, texto, Markdown y LaTeX de una sesión real,
  `--index` sobre 88 sesiones, y la ruta de fallo sin `xelatex` se comportaron
  como en Windows. Todavía sin verificar sobre el terreno: la compilación de
  PDF y las rutas de fuentes TeX en Linux, las sesiones *cowork* producidas en
  Linux, y todo en macOS. Los informes de usuarios de Linux/Mac son
  especialmente bienvenidos.
- **Escala.** Cada ejecución vuelve a leer todas las transcripciones bajo las
  raíces para resolver cadenas, y el índice compara conjuntos de uuid por
  pares: bien para cientos de sesiones, lento para miles. Un escaneo con caché
  es el siguiente paso evidente.
- **La búsqueda cubre prompts, no respuestas, entre archivos.** El índice busca
  todos los prompts humanos de todos los archivos; las respuestas de Claude son
  buscables dentro de una página. Indexar también las respuestas implica un
  fichero de índice mucho mayor y se aplaza hasta que alguien lo necesite.

(La renderización de subagentes, el formato Markdown, el descubrimiento de
sesiones *cowork*, el importador de claude.ai, la paginación, la búsqueda por
página y la búsqueda de prompts entre archivos, antes listados aquí, ya se
entregaron. Todas las características y todas las limitaciones conocidas están
reunidas en un solo sitio en el
[manual de usuario](docs/USER_MANUAL.es.md).) Dos salvedades sobre los
orígenes: la disposición del directorio *cowork* sigue la estructura
documentada de Claude Desktop, pero se probó con datos sintéticos, y el
importador de claude.ai — ahora validado contra una exportación real de agosto
de 2026 (informe de fidelidad reconciliado exactamente, UTF-8 acentuado
intacto) — apunta al esquema de exportación de mediados de 2026; aquella
exportación no contenía conversaciones dentro de proyectos, así que los
informes de exportaciones que se analicen de otro modo, en especial las
conversaciones de proyecto, siguen siendo bienvenidos.

## Dónde van los ficheros

La entrada se descubre bajo `--projects-root` (por defecto
`~/.claude/projects`) y, cuando el directorio existe, `--cowork-root`
(autodetectado por plataforma). La salida aterriza en `--archive-dir` (por
defecto `~/claude-archives`, o la variable de entorno `CLAUDE_ARCHIVE_DIR`):
cada sesión se convierte allí en `<session-id>_<title-slug>.<ext>`, un fichero
por formato (las importaciones de claude.ai usan el prefijo del uuid de la
conversación), `--index` escribe `index.html` en el mismo directorio, y cada
ejecución deja un registro de auditoría en `logs/`. Para colocar un único
archivo con exactitud, `--out ruta/al/informe` nombra la raíz — cada formato
añade su propia extensión.

## Alcance

El archivador lee los ficheros de transcripción que Claude Code escribe en tu
disco, así que lo que puede archivar lo decide dónde vive la transcripción de
una sesión:

| Superficie de Claude | ¿Archivable? |
|---|---|
| Claude Code CLI | **Sí** — es su formato nativo. |
| Aplicación de escritorio de Claude Code | **Sí** — las sesiones se ejecutan localmente y escriben los mismos ficheros. |
| Claude Code web/móvil, puenteado a tu máquina | **Sí** — el lado local escribe una transcripción, y los registros del puente se resuelven en cadena, de modo que las piezas salen como una sola conversación. |
| *Cowork* de Claude Desktop (modo de agente local) | **Sí** — mismo formato bajo un directorio base distinto, incorporado al descubrimiento vía `--cowork-root` (autodetectado). |
| Conversaciones de claude.ai, chat de Claude Desktop, aplicación móvil | **Vía exportación** — solicita la exportación de tus datos (Settings → Privacy → Export data) y ejecuta `--import-claude-ai conversations.json`. La exportación no trae uso de tokens ni nombres de modelos, y la página lo dice. |
| Sesiones en la nube de Claude Code (nunca puenteadas) | No — no se escribe nada en tu disco. |

Dos hechos ganados a pulso al validar contra una cuenta real (agosto de 2026):
la exportación de datos de claude.ai contiene **solo conversaciones sueltas** —
las conversaciones dentro de Proyectos de claude.ai y las sesiones *cowork* de
Claude Desktop no están en ella — y el almacén local de *cowork* **no**
sobrevive a una reinstalación de la aplicación — véase *Por qué existe*, arriba.

## Pruébalo

Una conversación-escaparate totalmente inventada acompaña a `examples/` — una
caza de modos de energía cero en una nanocinta de grafeno, construida para
ejercitarlo todo: etiquetas de referencia en dos modelos, una llamada a
herramienta que falla y su reintento, una tabla pegada literalmente, una imagen
pegada, griego y dibujo de cajas, un subagente en segundo plano (etiquetado
`A1.*`), una compactación de contexto, una llamada a herramienta sin resolver y
una línea deliberadamente corrupta que el informe de fidelidad cuenta.

```bash
python transcript_archiver.py 0000c0de-cafe-4000-8000-00000000f00d \
    --projects-root examples --archive-dir demo --format html,markdown,pdf
```

![Una página del PDF del escaparate](docs/showcase-pdf.png)

## Formatos

| | |
|---|---|
| `html` | Página estilo chat: tus turnos a la derecha, los de Claude a la izquierda, entrada/salida de herramientas plegable, índice filtrable, temas claro y oscuro. Autocontenida — sin recursos externos. |
| `text` | UTF-8 puro. Los turnos humanos y la salida de herramientas se reproducen byte a byte y nunca se rehacen los saltos de línea. |
| `markdown` | Para bóvedas de notas (Obsidian, etc.). La prosa de Claude es markdown y pasa tal cual; los turnos humanos y la entrada/salida de herramientas van en bloques literales, con vallas dimensionadas por encima de cualquier serie de acentos graves interna. |
| `latex` | Un documento XeLaTeX autónomo, o — con `--fragment` — un cuerpo que puedes `\input` en tu propio artículo. |
| `pdf` | El LaTeX compilado con `xelatex` (dos pasadas, por el índice). |

Los cinco se renderizan desde la misma transcripción analizada, de modo que un
turno no puede aparecer en un formato y desaparecer en otro, y cada uno declara
en su propia cabecera lo que su medio no puede transportar.

### Idioma

`--lang pt-BR|es|de|fr` traduce solo lo que escribe el propio archivador; la
conversación se mantiene literal y el registro de auditoría se mantiene en
inglés. Detalles en el [manual](docs/USER_MANUAL.es.md#idioma).

### Salida de herramientas

`--tool-output on|off` es independiente de `--format`. Los argumentos de las
herramientas se formatean con claridad en todos los casos, pero la entrada y la
salida completas convierten una sesión grande en un documento de varios cientos
de páginas, así que:

```bash
# un PDF legible: llamadas a herramientas listadas por nombre, cargas omitidas
python transcript_archiver.py <id> --format pdf --tool-output off

# el registro completo
python transcript_archiver.py <id> --format html --tool-output on
```

Una sesión de 1.655 registros ocupa 92 páginas con la salida de herramientas
desactivada y 260 con ella activada.

### Fragmentos para un artículo

`--fragment` emite el cuerpo sin preámbulo y translitera cada carácter para que
compile tanto con **pdflatex** como con XeLaTeX — el griego pasa a matemáticas,
las flechas y el dibujo de cajas pasan a ASCII. El preámbulo de tu documento
anfitrión necesita:

```latex
\usepackage{fvextra} \usepackage{xcolor} \usepackage{enumitem}
\usepackage{booktabs} \usepackage{array} \usepackage[most]{tcolorbox}
```

Los entornos de turno se definen con `\@ifundefined`, así que puedes
reestilizar cada turno desde tu propio preámbulo sin editar el fichero
generado.

## Lo que hace bien

Todos estos fueron defectos reales encontrados al ejecutarlo sobre cientos de
miles de registros, y cada uno está ahora cubierto por una prueba:

- **El uso se deduplica por `requestId`.** Una respuesta de la API se escribe
  como varios registros que repiten cada uno el mismo uso acumulado; sumarlos
  sobreestima los tokens de salida en aproximadamente 2,3× en una sesión con
  muchas herramientas.
- **Humano frente a inyectado se lee de `promptSource`/`origin.kind`**, no se
  adivina del texto, de modo que los prompts inyectados por el *harness* no se
  rendericen como cosas que escribiste tú.
- **Las cadenas de sesión se resuelven.** Una conversación reanudada o
  puenteada se escribe en un fichero *nuevo* que repite los registros
  anteriores, así que archivar el id que por casualidad nombraste puede
  capturar media conversación. Compara conjuntos de uuid, no nombres de fichero
  ni recuentos de registros — el fichero más corto puede contener más
  conversación.
- **Los turnos humanos nunca pasan por el renderizador de markdown.** Son texto
  escrito y pegado; interpretarlos aplasta un *traceback* pegado en prosa.
- **Los bloques de pensamiento están siempre vacíos.** Claude Code los solicita
  con `display: "omitted"`, así que un archivo puede mostrar *que* Claude pensó
  en un punto dado, nunca qué pensó. La página lo dice en lugar de dar a
  entender lo contrario.

## Pruebas

```bash
python tests/test_archiver.py
```

528 comprobaciones, ejecutadas contra las sesiones sintéticas de `examples/` —
autocontenidas, sin necesidad de transcripción real. Las comprobaciones de
compilación LaTeX/PDF se omiten (no fallan) cuando no hay instalación TeX en el
`PATH`; todo lo demás solo necesita Python. La batería también verifica que el
manual de usuario y `AGENTS.md` documenten todas las opciones de línea de
comandos y que el recuento de comprobaciones indicado aquí esté al día. Para
ejercitarla sobre una conversación grande y desordenada tuya:

```bash
CLAUDE_PROJECTS=~/.claude/projects SAMPLE_SESSION=<id> python tests/test_archiver.py
```

La muestra la genera `examples/make_sample.py` y está construida
deliberadamente para llevar las cosas que se rompieron con datos reales: un
bloque pegado cuyas columnas no deben rehacerse, griego y dibujo de cajas,
bytes NUL de salida UTF-16 capturada byte a byte, una línea de 3.000
caracteres, un bloque de pensamiento vacío, una llamada a herramienta sin
resolver, una lista markdown que cambia de tipo de marcador a mitad, un turno
que cita los propios marcadores de plantilla del archivador, y una línea
deliberadamente corrupta que el informe de fidelidad debe contar en vez de
saltarse en silencio.

## Requisitos

Python 3.9+ para los formatos HTML y texto — solo biblioteca estándar.

LaTeX y PDF necesitan una instalación TeX que proporcione `xelatex`, `fvextra`,
`tcolorbox`, `array` y las fuentes DejaVu (el `scheme-full` de TeX Live las
tiene todas). Las fuentes se cargan **por nombre de fichero desde TeX Live**, no
del sistema, de modo que la salida no depende de la base de fuentes de la
máquina.

Las cifras de coste vienen de la tabla `PRICING` en la cabecera del script —
tarifas públicas, fijadas en el código en agosto de 2026. Cuando las tarifas
cambien, edita esa tabla; los modelos que no conoce se informan como "sin
precio de tarifa" en vez de tarificarse mal.

## Cómo se construyó

Con él mismo mirando, en cierto sentido: toda la herramienta se desarrolló en
Claude Code (Opus 5 y Fable 5), y cada una de esas sesiones de desarrollo es
archivable por el resultado. El esfuerzo, reconstruido a partir de las
transcripciones de las sesiones: **diez días desde el primer prototipo hasta el
lanzamiento** (16–26 de agosto de 2026), a lo largo de unas ocho sesiones
largas de trabajo — unos 40 MB de transcripción en bruto — y 15 commits. El
primer commit público llegó solo el noveno día — todo lo anterior fue prueba de
supervivencia. Siguieron dos días más de lanzamientos guiados por revisión (2.4
→ 2.6.6, 28–31 de agosto: tres revisiones completas del proyecto, una pasada
independiente de revisión de código, ejecuciones de supervivencia que
detectaron seis tipos de registro nuevos que Claude Code había empezado a
escribir, y las correcciones que cada una exigió — la última de ellas una tabla
que compilaba limpiamente mientras perdía sus filas), llevando el historial a
38 commits; el mantenimiento que siguió — mantener el verificador de
conformidad *vendorizado* byte a byte idéntico al manual de publicación — lo
lleva a 59 commits (2.7.2, una regresión que la ejecución de supervivencia con
datos reales detectó tras una batería toda verde, 2.7.3–2.7.7, cinco rondas
de revisión independiente, cada una encontrando defectos reales en la
corrección de la ronda anterior — siempre en su ruta de fallo, nunca en la ruta
feliz — y 2.8.0, que llevó el repositorio al estándar de producto (política de
seguridad, registro de plataformas, inventario de terceros) y tradujo el README
y el manual a cuatro idiomas más, son los últimos siete).

El reparto del trabajo, reconstruido a partir de esas mismas transcripciones y
expresado en términos [CRediT](https://credit.niso.org/) (la taxonomía de roles
de contribuyentes que usan los artículos científicos):

| Rol CRediT | Fabio | Claude |
|---|---|---|
| **Conceptualización** | La premisa — un registro autocontenido y de fidelidad total de una sesión asistida por IA, apto para el informe científico — y la mayoría de las ideas de características: etiquetas de cita P/R, el conmutador de salida de herramientas, el índice de actividad en vivo, la paginación | El modelo de reconciliación renderizar/plegar/contar que se convirtió en el informe de fidelidad |
| **Metodología** | El orden de prioridad (primero fidelidad de contenido, luego orígenes, luego formatos); los requisitos de publicación académica que dieron forma al fragmento LaTeX | Resolución de cadenas por comparación de conjuntos de uuid; deduplicación de uso por `requestId`; la regla del turno humano literal |
| **Software** | — | Todo |
| **Validación** | Rompió cada compilación contra cientos de miles de registros de un archivo real; detectó los defectos de página obsoleta, desbordamiento y disposición; fijó el listón (*"esto necesita alta exactitud"*); encargó las pasadas de revisión y de revisión de código | La batería de 296 comprobaciones y la CI; las ejecuciones de supervivencia guiadas por revisión |
| **Investigación** | Dirigió el estudio de herramientas vecinas | Análisis de código y documentación para la sección de comparación |
| **Curación de datos** | — | La muestra sintética y la conversación-escaparate, construidas para llevar exactamente los casos que se habían roto con datos reales |
| **Visualización** | La disposición de chat (humano a la derecha, Claude a la izquierda), el estilo de las cajas, la colocación de etiquetas y marcas de tiempo | El HTML/CSS que lo realiza |
| **Redacción** | Revisión y edición | Borrador original (README, mensajes de commit) |
| **Recursos · Supervisión · Administración del proyecto · Obtención de financiación** | Todo | — |

## Licencia

Licencia Apache 2.0 — véanse `LICENSE` y `NOTICE`. Puedes usarlo, modificarlo y
redistribuirlo, incluso comercialmente, siempre que la licencia y el aviso
viajen con él; las contribuciones se aceptan bajo los mismos términos
(sección 5).

### Descargo de responsabilidad

Este software se proporciona **tal cual**, sin garantías ni condiciones de
ningún tipo, expresas o implícitas, incluidas, entre otras, cualquier garantía
de comerciabilidad, idoneidad para un fin determinado, titularidad o no
infracción. En ningún caso el autor será responsable de daños de ningún tipo —
directos, indirectos, especiales, incidentales o consecuentes — ni de ninguna
otra reclamación o responsabilidad, ya sea contractual, extracontractual o de
otro tipo, derivada de o en conexión con el software o su uso, incluso si se
hubiera advertido de la posibilidad de tales daños (Licencia Apache 2.0,
secciones 7 y 8). Solo tú eres responsable de usarlo lícitamente, de las
transcripciones y datos que le proporciones y publiques con él, y de cumplir
los términos de cualquier servicio o contenido de terceros que toque.

Este es un proyecto independiente. No está afiliado, respaldado ni apoyado por
Anthropic; *Claude* y *Claude Code* son marcas de Anthropic, PBC, usadas aquí
solo para nombrar el software cuyas transcripciones archiva esta herramienta.
