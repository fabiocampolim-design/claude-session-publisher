---
title: "claude-session-publisher — Manual de Usuario"
subtitle: "transcript_archiver.py v2.8.0"
source-digest: "cb33ce2647306476"
---

# claude-session-publisher — Manual de Usuario

[English](USER_MANUAL.md) · [Português (Brasil)](USER_MANUAL.pt-BR.md) · **Español** · [Deutsch](USER_MANUAL.de.md) · [Français](USER_MANUAL.fr.md)

*Traducción del manual en inglés, que es la referencia; los comandos, nombres de archivo, opciones y bloques de código se mantienen como en el original.*

`transcript_archiver.py` convierte una conversación de Claude en un documento
autocontenido — HTML, texto plano, Markdown, LaTeX o PDF — con un informe de
fidelidad que reconcilia cada registro de origen con lo que muestra la página.
Este manual es la referencia completa: todas las opciones, todas las salidas,
todas las características y todas las limitaciones conocidas. El README es la
página del producto; `AGENTS.md` es la misma información escrita para un agente
de IA que maneje la herramienta.

Un solo fichero, Python 3.9+, solo biblioteca estándar. Sin paso de
instalación:

```bash
python transcript_archiver.py --version
python transcript_archiver.py --help
```

## 1. Inicio rápido

```bash
# archiva una sesión de Claude Code en HTML (el formato por defecto)
python transcript_archiver.py <session-id>

# todos los formatos a la vez
python transcript_archiver.py <session-id> --format html,text,markdown,latex,pdf

# reconstruye la página índice de todo lo que hay en disco
python transcript_archiver.py --index

# pruébalo con la conversación de escaparate incluida
python transcript_archiver.py 0000c0de-cafe-4000-8000-00000000f00d \
    --projects-root examples --archive-dir demo --format html,markdown,pdf
```

El id de sesión es el nombre del fichero `.jsonl` bajo
`~/.claude/projects/<project>/`. `--index` lista todas las sesiones que
encuentra con su id y título, así que ejecútalo primero si no conoces el id.

## 2. Orígenes

| Origen | Cómo | Notas |
|---|---|---|
| Claude Code CLI / aplicación de escritorio | por defecto; sesiones bajo `--projects-root` (`~/.claude/projects`) | formato nativo |
| Claude Code web/móvil puenteado a tu máquina | igual | los registros del puente se resuelven en cadena en una sola conversación |
| *Cowork* de Claude Desktop (modo de agente local) | `--cowork-root` (autodetectado por plataforma) | mismo esquema de registros, directorio base distinto; `audit.jsonl` se omite. Probado solo con datos sintéticos |
| Conversaciones de claude.ai, chat de Claude Desktop, aplicación móvil | `--import-claude-ai conversations.json` | desde Settings → Privacy → Export data. Solo conversaciones sueltas; sin conversaciones de Proyecto, sin datos de uso ni de modelo (la página lo dice) |
| Sesiones en la nube de Claude Code nunca puenteadas | no archivable | no se escribe nada en tu disco |

Autodetección de *cowork*: `%APPDATA%\Claude\local-agent-mode-sessions` en
Windows, `~/Library/Application Support/Claude/local-agent-mode-sessions` en
macOS, `~/.config/Claude/local-agent-mode-sessions` en el resto. Pasa
`--cowork-root ""` para desactivarlo.

## 3. Referencia de línea de comandos

Toda entrada y toda salida son accesibles desde la línea de comandos; nada está
fijado en el código. `--help` imprime cada opción con su valor por defecto.

### Posicional

| | |
|---|---|
| `session_id` | UUID de la transcripción (el nombre del fichero `.jsonl`). Opcional con `--index` o `--import-claude-ai`. |

### Descubrimiento y ubicación

| Opción | Por defecto | Significado |
|---|---|---|
| `--projects-root DIR` | `~/.claude/projects` | dónde escribe Claude Code las sesiones |
| `--cowork-root DIR` | automático por plataforma | sesiones *cowork* de Claude Desktop, incorporadas al descubrimiento cuando el directorio existe; `""` lo desactiva |
| `--archive-dir DIR` | `$CLAUDE_ARCHIVE_DIR` o `~/claude-archives` | dónde van los archivos, `index.html` y `logs/` |
| `--out PATH` | — | **raíz** de la ruta de salida para un solo archivo; cada formato añade su propia extensión (`--out report.pdf --format html` escribe `report.html`). Anula la nomenclatura de `--archive-dir` |
| `--title TEXT` | el propio `ai-title` de la sesión | título de la página; también determina el *slug* del nombre de fichero. Volver a archivar con otro título escribe un fichero nuevo |
| `--summary-file FILE` | texto de ejemplo | fragmento HTML (bloques `h3`/`ul`) renderizado como el resumen de sesión escrito a mano |

### Contenido

| Opción | Por defecto | Significado |
|---|---|---|
| `--format LIST` | `html` | separado por comas: `html`, `text`, `markdown` (o `md`), `latex`, `pdf` |
| `--tool-output on\|off` | `on` | incluye la entrada y la salida de las herramientas. Independiente de `--format`. `off` reduce cada llamada a una línea etiquetada — normalmente lo que quieres para LaTeX/PDF |
| `--max-tool-output N` | `16384` | elide el centro de cualquier salida de herramienta más larga que N caracteres; cada elisión se cuenta en la página. `0` = nunca |
| `--full` | desactivado | nunca elide (igual que `--max-tool-output 0`) |
| `--subagents on\|off` | `on` | renderiza las transcripciones de subagentes como secciones de apéndice. Con `off` siguen listadas en el informe de fidelidad y su uso sigue contando |
| `--no-follow-chain` | desactivado | archiva exactamente el id indicado aunque exista una continuación más completa |
| `--fragment` | desactivado | con `--format latex`: solo el cuerpo, sin preámbulo, transliterado para compilar con pdflatex además de XeLaTeX. No se puede combinar con `pdf` |
| `--paginate N` | `0` | divide el HTML en páginas de N turnos; la página 1 conserva las secciones de resumen, uso y fidelidad; la barra lateral enlaza entre páginas |
| `--lang CODE` | `$CLAUDE_ARCHIVE_LANG` o `en` | `en`, `pt-BR`, `es`, `de`, `fr`: el idioma de las palabras del propio archivador en todos los formatos y en el índice. La conversación nunca se traduce (véase §4, *Idioma*) |

### Índice

| Opción | Significado |
|---|---|
| `--index` | reconstruye `index.html` en `--archive-dir` y sale |
| `--watch SECONDS` | con `--index`: regenera cada SECONDS (mínimo 30) hasta Ctrl+C, y marca la página para que se recargue; al detenerse, el índice se escribe una vez más para que ya no se recargue |

### Importación de claude.ai

| Opción | Significado |
|---|---|
| `--import-claude-ai FILE` | importa conversaciones de un `conversations.json` de claude.ai |
| `--conversation TEXT` | solo conversaciones cuyo nombre o uuid contenga TEXT (sin distinguir mayúsculas) |
| `--list-conversations` | lista las conversaciones de la exportación y sale |

### Control de salida y registro

| Opción | Significado |
|---|---|
| `--verbose` | detalle por paso (ficheros analizados, pasadas de compilación, ruta del registro de auditoría) |
| `--quiet` | no imprime más que avisos; el registro de auditoría lo sigue recogiendo todo |
| `--log-dir DIR` | dónde va el registro de auditoría de cada ejecución (por defecto `<archive-dir>/logs/`) |
| `--version` | imprime la versión del archivador y sale |
| `--help` | referencia de opciones |

Las combinaciones inválidas se rechazan antes de escribir nada: `--watch` sin
`--index`; `--conversation`/`--list-conversations` sin `--import-claude-ai`;
`--fragment` sin `latex` o junto con `pdf`; `--verbose` con `--quiet`; un valor
desconocido de `--format`.

## 4. Qué se produce

### Ficheros

En `--archive-dir` (o en la raíz de `--out`), un fichero por formato:
`<session-id>_<title-slug>.html|.txt|.md|.tex|.pdf`. Un cuerpo LaTeX de
`--fragment` es `<stem>_fragment.tex`. El HTML paginado añade
`<stem>_p2.html`, `<stem>_p3.html`, …. Las importaciones de claude.ai se llaman
`<uuid-prefix>_<slug>`. `--index` escribe `index.html`. Cada ejecución escribe
`logs/<timestamp>_<label>.log`.

Cuando una sesión es una conversación reanudada o puenteada, el fichero recibe
el nombre de la transcripción realmente archivada (el fichero más completo de
la cadena), y la página registra qué id se solicitó.

### La página

Todos los formatos llevan, en este orden: el **resumen de la sesión** (escrito
a mano mediante `--summary-file`, o un texto de ejemplo), **uso y coste**, el
**informe de fidelidad**, luego la **transcripción**, y luego las
**transcripciones de subagentes** como apéndices.

Tipos de turno y cómo los muestra cada formato:

| Turno | HTML | texto / Markdown | LaTeX / PDF |
|---|---|---|---|
| Prompt humano (P*n*) | burbuja alineada a la derecha, literal, monoespaciada cuando va en columnas, URLs enlazadas | literal, nunca reajustado (Markdown: en bloque) | caja literal |
| Respuesta de Claude (R*n*) | markdown renderizado | prosa reajustada (Markdown: markdown vivo) | markdown → LaTeX |
| Pensamiento | plegado; vacío en la práctica (véase §7) | etiquetado | caja etiquetada |
| Llamada a herramienta | entrada/salida plegada, estados de error y pendiente, capturas de pantalla | entrada/salida completa o una línea (`--tool-output`) | entrada/salida completa o caja solo con título |
| Imagen pegada | incrustada | anunciada como omitida | anunciada como omitida |
| Harness / sistema / evento | carril plegado con la evidencia de clasificación | bloques etiquetados | cajas etiquetadas |
| Transcripción de subagente | apéndice plegable, enlazado desde la llamada que lo creó | sección de apéndice | sección de apéndice |

### Idioma

`--lang pt-BR|es|de|fr` (o la variable de entorno `CLAUDE_ARCHIVE_LANG`; la
opción manda; por defecto `en`) fija el idioma de todo lo que escribe el propio
archivador: el armazón de la página y sus controles, las etiquetas de los
turnos, la información de la sesión, las notas de uso y coste, el informe de
fidelidad, el apéndice de subagentes, las notas de formato de las salidas en
texto/Markdown/LaTeX, y la página índice. `<html lang>` y el campo `lang` de
los metadatos incrustados registran la elección; el LaTeX autónomo carga
polyglossia cuando está instalado, mantiene el **inglés como idioma por
defecto** — la prosa de la conversación se silabea y espacia como inglés, de
modo que una página en francés nunca inserta espacios antes del `!` de Claude —
y envuelve solo las palabras del propio archivador en el idioma del documento.
Un `--fragment` compone esas palabras con macros de acento (`\'{e}`, `\"{a}`,
`\ss{}`) para que pdflatex las imprima intactas, y nunca las cuenta en la nota
de descarte del fragmento.

La conversación nunca se traduce. Prompts, respuestas, pensamiento, nombres de
herramientas, entrada y salida de herramientas, texto de sistema y del
*harness*, nombres de modelos, títulos, rutas, fechas (ISO) y números son los
mismos bytes en todos los idiomas — la batería renderiza el fichero de prueba
en los cinco y comprueba que cada fragmento de conversación de la página en
inglés está presente literalmente en las demás. Las insignias de evento y las
etiquetas de adjuntos se traducen donde se renderizan; los nombres de tipo de
registro de las tablas de fidelidad (`human turn`, `tool_use`, …) son
vocabulario del analizador y se quedan en inglés, igual que el sello
`archiver v…` que el índice vuelve a leer. El registro de auditoría, la consola
(`--verbose`) y `--help` se quedan en inglés sea cual sea el idioma. Un código
desconocido — en la opción o en la variable — se rechaza antes de escribir
nada.

### Etiquetas de referencia

Cada prompt humano es `P1, P2, …` y cada respuesta `R1, R2, …`, secuenciales
dentro del documento; los turnos de subagentes llevan el prefijo `A1.`, `A2.`
(así, `A2.R4`). En HTML las etiquetas son anclas: `page.html#P32` enlaza
directamente al prompt.

### Informe de fidelidad

Cada registro de origen se **renderiza** (produjo uno o más turnos), se
**pliega** (un resultado de herramienta absorbido por su llamada) o se
**cuenta** (metadatos sin contenido de transcripción — y líneas corruptas). Los
tres números se reconcilian con el recuento de registros del origen en la
página; si no cuadran, la página lo dice en lugar de ocultarlo. El informe
también lista los registros por tipo, los bloques de contenido, lo que se
renderizó y lo que se contó, la evidencia humano-frente-a-inyectado por
registro, los ficheros de subagentes, y las salvedades (bloques de pensamiento
vacíos, llamadas a herramientas sin resolver, hora de la instantánea frente al
último registro del origen).

### Uso y coste

Tokens por modelo deduplicados por `requestId` — una respuesta de la API se
escribe como varios registros que repiten el mismo uso, y sumarlos sobreestima
la salida ~2,3× en sesiones con muchas herramientas. Las lecturas de caché y
las escrituras de caché de 5 minutos y de 1 hora se separan, y se estima un
coste a **tarifas públicas** desde la tabla `PRICING` de la cabecera del script
(lecturas de caché a 0,1× la entrada, escrituras a 1,25× / 2×). No es lo que
factura una suscripción. Los modelos que la tabla no conoce se informan como
"sin precio de tarifa". El uso de los subagentes se incorpora.

**Coste informado.** Claude Code ≥ 2.1.9x también escribe su propio medidor en
el fichero de sesión (registros `cost-state`: coste acumulado, coste por
modelo, líneas añadidas y eliminadas por las herramientas). Cuando está
presente, la página muestra esa cifra como columna de *coste informado* junto a
la estimación de tarifa, una fila en la información de sesión, y
`reported_cost_usd`, `reported_cost_runs`, `reported_cost_partial`,
`lines_added`, `lines_removed` en los metadatos incrustados; los formatos
texto, Markdown y LaTeX llevan la misma frase. El medidor es **por proceso**:
cada `claude --resume` inicia un contador nuevo, y las ejecuciones anteriores a
la existencia del registro no escribieron ninguno — así que la cifra es la suma
de la última instantánea de cada ejecución (reunida de todos los ficheros de la
cadena de una sesión reanudada) y se marca como **parcial** cuando la sesión
empezó más de un minuto antes de su primera ejecución medida. En ese caso la
página dice qué gasto no queda cubierto y el índice sigue mostrando la
estimación de tarifa; en caso contrario el índice muestra "$X informado". Una
ejecución que Claude Code no pudo tarificar por completo se anota ("el total
informado es un suelo"). En la práctica el medidor ha salido ~30 % por debajo
de la estimación de tarifa en una sesión de una sola ejecución.

### Los controles de la página HTML

Barra lateral: **búsqueda** (oculta los turnos cuyo texto no coincide),
**filtro** (estrecha la lista del índice; tecla `/`), conmutadores de carril
(pensamiento, herramientas, *harness*, eventos, subagentes),
desplegar/plegar todo, **conmutador de tema** (claro u oscuro, recordado por
navegador; sigue al sistema hasta que elijas), datos de la sesión, índice.
Teclas: `j`/`k` saltan entre turnos humanos.

Una **negativa de salvaguarda con cambio de modelo** (Claude Code escribe un
registro `system/model_refusal_fallback` cuando se rechaza un mensaje y la
sesión continúa en otro modelo) se renderiza como evento en todos los formatos:
la insignia *Model fallback after a safeguard refusal*, el detalle
`<original> -> <fallback> (category: …), N message(s) retracted`, y un cuerpo
que declara cuántos de los mensajes retirados faltan en el fichero de origen.
La información de sesión en HTML añade una fila *Harness retractions*. El
resumen que Claude Code imprime cuando vuelves (`away_summary`) es el evento
*Away summary*.

### El índice

`--index` recorre todas las sesiones en disco y marca cada una como
**archivada**, **obsoleta** (el origen tiene registros más nuevos que el
archivo), **cubierta** (reanudada en otra transcripción que sí está
archivada), **heredada v1**, o **no archivada**; lista los archivos cuyo origen
no está en disco (importaciones de claude.ai, transcripciones borradas); y
muestra una columna de actividad cuyas edades envejecen en el navegador. Las
cabeceras ordenan al hacer clic. `--watch` lo mantiene regenerándose: cada
página que escribe lleva un `<meta http-equiv="refresh">` para que un navegador
abierto siga el ritmo. Cuando la vigilancia se detiene — Ctrl+C, una consola
cerrada, un `taskkill` sobre su PID — el índice se escribe una vez más sin esa
marca, de modo que una página abierta ya no recargue un índice congelado cada N
segundos. Si esa última escritura no puede hacerse (el fichero está bloqueado,
el disco lleno) la ejecución lo dice y nombra lo que sigue en disco; vuelve a
ejecutar `--index` para reemplazarlo. Un primer `--index` en un directorio que
todavía no existe lo crea.

**Búsqueda en todos los archivos.** La página índice lleva un cuadro de
búsqueda sobre todos los prompts humanos de todos los archivos — incluidas
todas las páginas de un archivo paginado y los prompts de subagentes (`A1.P1`)
— leídos del propio HTML de los archivos al indexar, de modo que los archivos
escritos por versiones anteriores y las importaciones de claude.ai quedan
igualmente cubiertos. Al escribir dos o más caracteres se listan los prompts
coincidentes (sesión, etiqueta, título, fragmento resaltado; se muestran los
200 primeros), cada uno enlazando directamente al ancla del prompt en su
página, y se estrecha la tabla de sesiones a las que han coincidido. Los
prompts se limitan a 400 caracteres en el índice; las respuestas de Claude son
buscables dentro de cada página, no entre archivos (véanse las limitaciones).

## 5. LaTeX y PDF

Requisitos: una instalación TeX que proporcione `xelatex`, `fvextra`,
`tcolorbox`, `booktabs`, `array`, `enumitem`, `xcolor`, `hyperref` y las
fuentes DejaVu (el `scheme-full` de TeX Live las tiene todas). Las fuentes se
cargan **por nombre de fichero desde TeX Live**, no del sistema, de modo que la
salida no depende de la base de fuentes de la máquina.

- `pdf` = el LaTeX autónomo compilado por `xelatex` dos veces (por el índice);
  `.aux/.log/.out/.toc` se eliminan si todo va bien y el `.tex` se conserva
  solo si también se pidió `latex`. Si falla, se imprimen las últimas 30 líneas
  del log y el `.tex` se queda para inspección.
- `--fragment` emite un cuerpo para `\input` en tu propio documento. Es neutral
  respecto al motor: el griego pasa a matemáticas (`Γ` → `$\Gamma$`), los
  sub/superíndices pasan a matemáticas, las flechas y el dibujo de cajas pasan
  a ASCII, los acentos se reducen a la letra base. Tu preámbulo necesita
  `\usepackage{fvextra} \usepackage{xcolor} \usepackage{enumitem}
  \usepackage{booktabs} \usepackage{array} \usepackage[most]{tcolorbox}`.
  Los entornos de turno se definen con `\@ifundefined`, así que puedes
  reestilizarlos desde tu preámbulo.
- Los emoji y otros glifos que ninguna fuente TeX puede componer, y los bytes
  de control C0/C1 (NUL de capturas de consola en UTF-16, retrocesos), se
  eliminan y se **cuentan en el documento**. Las líneas de más de 500
  caracteres se parten a la fuerza para que TeX pueda componerlas; el recuento
  se indica.
- Un turno de más de 1.500 líneas compuestas (un pegado enorme o una salida de
  herramienta) se divide en cajas consecutivas tituladas *(part k/n)*: una sola
  caja divisible que lo contenga entero agota la memoria de TeX. El documento
  indica cuántos turnos se dividieron; no se omite nada.
- **Las tablas markdown se cortan en trozos de como mucho 30 filas
  compuestas**, cada uno su propio `tabular` que repite la cabecera y va
  marcado *(table continued)*, porque un solo `tabular` no puede partirse entre
  páginas. Una tabla cuyo ancho natural exceda la línea recibe columnas `p` con
  ajuste equitativo en lugar de columnas naturales, de modo que ninguna celda
  se salga del papel. Ambas eran pérdidas silenciosas antes de la 2.6.4.
- Validado por una pasada completa sobre un archivo real de 64 sesiones (6.245
  páginas, 69 minutos, `--tool-output off`, 64/64 compiladas, agosto de 2026),
  y por una comprobación de compilar-y-contar en la batería: una respuesta que
  es una tabla de 300 filas tiene que ocupar las páginas que sus filas
  necesitan, no meramente salir con código 0.
- Coste de la entrada/salida completa de herramientas, medido: una sesión de
  636 registros → 643 páginas en unos cuatro minutos; una sesión de 1.655
  registros son 92 páginas con `--tool-output off` y 260 con él activado.

## 6. Registro y auditoría

Consola: líneas de progreso por defecto; `--quiet` las silencia; `--verbose`
añade detalle por paso. Los avisos van siempre a stderr. Cada invocación
escribe `<archive-dir>/logs/<YYYYMMDD-HHMMSS>_<label>.log` (o bajo
`--log-dir`) con las versiones del archivador y de Python, la línea de comandos
exacta, el directorio de trabajo, las horas de inicio y fin, todos los mensajes
de consola, y el desenlace (`ok`, `failed: …`, `crashed: …`, `interrupted`). El
registro nunca aborta una ejecución.

## 7. Limitaciones conocidas

Estos son los bordes honestos. Cada uno se declara en la página donde aplica.

- **El texto del pensamiento nunca está en la transcripción.** Claude Code pide
  el pensamiento con `display: "omitted"`; todo bloque de pensamiento en disco
  está vacío. El archivo muestra *que* Claude pensó en un punto, nunca qué
  pensó.
- **El coste de tarifa es una estimación**, no una factura; la tabla `PRICING`
  está fijada en el código (tarifas de agosto de 2026) y hay que editarla
  cuando cambien las tarifas. El **coste informado** es la cifra del propio
  Claude Code, pero es por proceso: las sesiones reanudadas a lo largo de
  varias ejecuciones, o iniciadas antes de Claude Code 2.1.9x, quedan cubiertas
  solo en parte y lo dicen (`partial`).
- **Una sesión en vivo va desfasada en una llamada a herramienta**: archivar
  desde dentro de la sesión deja sin resolver la llamada del propio archivador;
  la página lo dice.
- **La exportación de claude.ai contiene solo conversaciones sueltas** — sin
  conversaciones de Proyecto, sin sesiones *cowork*, sin uso ni nombres de
  modelos. Apunta al esquema de exportación de mediados de 2026.
- **El descubrimiento de *cowork* sigue la disposición documentada** pero se
  probó solo con datos sintéticos; el almacén local de *cowork* no sobrevive a
  una reinstalación de la aplicación.
- **Las sesiones en la nube nunca puenteadas a tu máquina no se pueden
  archivar.**
- **Texto y Markdown no pueden llevar imágenes**; se anuncian como omitidas.
  LaTeX/PDF igual; el HTML sí las contiene.
- **El renderizado de markdown cubre la prosa propia de Claude** (títulos,
  listas incl. anidadas, tablas, bloques de código de cualquier longitud,
  citas, código/negrita/cursiva/tachado/enlaces en línea), no CommonMark
  arbitrario: sin HTML incrustado, sin enlaces de referencia, sin notas al pie;
  las celdas de tabla se parten en cada `|`. En LaTeX y PDF una tabla se trocea
  y, cuando es ancha, se ajusta (§5): todas las celdas sobreviven, pero una
  tabla muy ancha queda igualada por columnas en vez de maquetada al gusto.
- **La clasificación humano-frente-a-inyectado** es autoritativa en los
  registros que llevan `promptSource` / `origin.kind`; los registros más
  antiguos recurren a marcadores de texto, y la evidencia usada se lista por
  registro en el informe de fidelidad.
- **Las marcas de tiempo son locales** a la máquina que archiva (pasa el ratón
  para ver UTC en el HTML).
- **Volver a archivar con un `--title` distinto escribe un fichero nuevo** junto
  al antiguo en vez de sobrescribirlo.
- **Escala**: cada ejecución vuelve a leer todos los ficheros `.jsonl` bajo las
  raíces para resolver cadenas; el índice compara conjuntos de uuid por pares.
  Bien para cientos de sesiones; lento para miles.
- **Plataformas**: desarrollado y validado en Windows; la batería y una
  comprobación estática con pyflakes se ejecutan en Linux, Windows y macOS en
  CI. Linux tuvo una ejecución real (31/08/2026, WSL2 Ubuntu, Python 3.14:
  todos los formatos no-PDF de una sesión real, `--index`, y el fallo ruidoso
  sin `xelatex`). Sin verificar sobre el terreno: PDF y rutas de fuentes TeX en
  Linux, sesiones *cowork* producidas en Linux, y macOS por completo. Bajo WSL,
  leer las transcripciones a través de `/mnt/c` hizo el escaneo unas cuatro
  veces más lento que de forma nativa (18 s frente a 4 s para 281
  transcripciones) — mantén las raíces del lado Linux.
- **El envejecimiento del índice en vivo es unidireccional**: una sesión puede
  quedar en silencio en pantalla, pero no puede volver a estar activa sin
  regeneración (`--watch`).
- **La búsqueda entre archivos cubre prompts, no respuestas** (y los primeros
  400 caracteres de cada prompt). Las respuestas son buscables dentro de una
  página. Indexar las respuestas multiplicaría el tamaño del fichero de índice
  y queda aplazado.

## 8. Pruebas

```bash
python tests/test_archiver.py
```

528 comprobaciones contra las sesiones sintéticas de `examples/` (sin
necesidad de transcripción real). Las comprobaciones de compilación LaTeX/PDF
se omiten, no fallan, cuando no hay TeX en el `PATH`. Para ejercitarlo sobre
una conversación tuya:

```bash
CLAUDE_PROJECTS=~/.claude/projects SAMPLE_SESSION=<id> python tests/test_archiver.py
```

La batería también comprueba que este manual y `AGENTS.md` documenten todas las
opciones de línea de comandos y que el recuento de comprobaciones indicado en
el README esté al día.

## 9. Construir este manual

```bash
python docs/build_manual.py
```

Renderiza `USER_MANUAL.md` — y cada traducción — a `.html` y `.pdf` con pandoc
(y xelatex para el PDF) cuando están disponibles, y en caso contrario con el
renderizador de Markdown del propio archivador para el HTML y una nota de que
el PDF se omitió. Los ficheros construidos se versionan para que los lectores
no necesiten herramienta alguna.

El inglés es el texto de referencia. Cada traducción registra el *digest* del
texto en inglés del que se hizo, y la batería falla cuando el inglés se ha
movido y la traducción no; `python docs/build_manual.py --stamp` escribe esos
*digests*, después de haber puesto al día la traducción — nunca en su lugar.
