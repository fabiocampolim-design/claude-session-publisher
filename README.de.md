# claude-session-publisher
<!-- source-digest: d529d9e1192c700d -->

[![Tests](https://github.com/fabiocampolim-design/claude-session-publisher/actions/workflows/tests.yml/badge.svg)](https://github.com/fabiocampolim-design/claude-session-publisher/actions/workflows/tests.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Dependencies: stdlib only](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen)](transcript_archiver.py)
[![Platform: Windows | Linux | macOS](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)](#voraussetzungen)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

[English](README.md) · [Português (Brasil)](README.pt-BR.md) · [Español](README.es.md) · **Deutsch** · [Français](README.fr.md)

*Übersetzung des englischen README, das die Referenz bleibt; Befehle, Dateinamen, Optionen und Codeblöcke stehen wie im Original.*

Verwandelt eine Claude-Code-Sitzung in ein einziges, in sich geschlossenes
Dokument — HTML, reiner Text, Markdown, LaTeX oder PDF — mit einem
Treuebericht, der belegt, dass nichts stillschweigend verloren ging.

> **Rückmeldungen sind sehr willkommen.** Dieses Werkzeug ist jung und
> Transkripte sind wild — wenn eine Ihrer Sitzungen seltsam dargestellt wird,
> eine Zahl im Treuebericht nicht aufgeht oder ein Format fehlt, das Sie
> brauchen, eröffnen Sie bitte
> [ein Issue](https://github.com/fabiocampolim-design/claude-session-publisher/issues).

**Warum es das gibt.** KI-gestützte Forschung braucht denselben
Dokumentationsstandard wie jede andere Methode: Wenn ein Ergebnis im Gespräch
mit einem Modell entstanden ist, hängen Transparenz und Reproduzierbarkeit der
Wissenschaft davon ab, dieses Gespräch zitieren und prüfen zu können —
wortgetreu, vollständig und in einer Form, auf die eine Publikation verweisen
kann. Dafür ist dieses Werkzeug da. *Doch* es zu bauen hat uns auch gelehrt,
dass die Aufzeichnungen selbst fragil sind: Im August 2026 löschte eine
Neuinstallation von Claude Desktop — vom Support nach einem fehlgeschlagenen
Tarifwechsel empfohlen — meine lokalen Agentensitzungen, und der
Kontodatenexport enthielt sie nicht. Ganze Projekte, endgültig verloren. Das
Werkzeug ist also über die Wissenschaft hinaus von Interesse: Wer immer seine
Gespräche für wichtig hält, sollte eine eigene Kopie behalten. Der Leitsatz:
**früh archivieren, oft archivieren** — ein Archiv existiert nur, wenn Sie es
anlegen, solange die Dateien noch da sind.

Claude Code schreibt jede Sitzung in eine JSON-Lines-Datei unter
`~/.claude/projects/`. Diese Datei ist vollständig, aber unlesbar: verschränkte
Datensätze, Werkzeug-Nutzlasten, Buchführung des Harness. Dieses Skript
zerlegt jeden Datensatztyp in ein typisiertes Modell, entscheidet pro Klasse,
ob **darzustellen**, **einzufalten** oder zu **zählen** ist, und druckt einen
Treuebericht, der die drei Zahlen gegen die Datensatzzahl der Quelle abgleicht
— sodass der Unterschied zwischen *„nicht im Transkript"* und *„nicht in der
Quelle"* immer auf der Seite sichtbar bleibt.

Eine Datei, nur Standardbibliothek, kein Installationsschritt.

```bash
python transcript_archiver.py <session-id>
python transcript_archiver.py <session-id> --format html,text,markdown,latex,pdf
python transcript_archiver.py --index          # Indexseite neu erzeugen
```

Vollständige Referenz: [`docs/USER_MANUAL.de.md`](docs/USER_MANUAL.de.md)
(auch als [HTML](docs/USER_MANUAL.de.html) und
[PDF](docs/USER_MANUAL.de.pdf)) führt jede Option, jede Ausgabe, jede
Funktion und jede bekannte Einschränkung auf. Sie steuern es mit einem
KI-Agenten? Geben Sie ihm [`AGENTS.md`](AGENTS.md). Änderungen stehen in
[`CHANGELOG.md`](CHANGELOG.md); wie man beiträgt, in
[`CONTRIBUTING.md`](CONTRIBUTING.md) und die Entwurfsabwägungen — samt der
Bedrohungsnotiz — in [`docs/DESIGN.md`](docs/DESIGN.md).
Sicherheitsrichtlinie: [`SECURITY.md`](SECURITY.md). Wovon es abhängt und was
es reproduziert: [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md). Wo es
tatsächlich gelaufen ist: [`docs/platforms.md`](docs/platforms.md).

## Funktionen

- **Fünf Formate aus einer Analyse** — HTML, reiner Text, Markdown, LaTeX und
  PDF entstehen alle aus demselben typisierten Transkriptmodell, sodass ein
  Beitrag nicht in einem Format erscheinen und in einem anderen verschwinden
  kann. `--fragment` liefert einen LaTeX-Rumpf, fertig zum `\input` in ein
  Manuskript, transliteriert, damit er auch unter pdflatex und nicht nur unter
  XeLaTeX kompiliert.
- **Subagenten-Transkripte gehören zur Aufzeichnung** — das Gespräch eines
  Hintergrundagenten (`<session-id>/subagents/agent-*.jsonl`) wird in jedem
  Format als verlinkter Anhang dargestellt, sein Verbrauch in die Kostentabelle
  eingerechnet und jede Datei im Treuebericht aufgeführt. `--subagents off`
  unterdrückt den Inhalt, nie aber die Offenlegung.
- **Drei Quellen** — Claude-Code-Sitzungen, *Cowork*-Sitzungen von Claude
  Desktop (lokaler Agentenmodus) über `--cowork-root` und claude.ai-Gespräche
  über `--import-claude-ai conversations.json` (aus Settings → Privacy → Export
  data), alle durch dieselbe Verarbeitungskette und dieselbe Treueberichtung.
- **Ein Treuebericht auf jeder Seite** — jeder Quelldatensatz wird dargestellt,
  in einen früheren Beitrag eingefaltet oder als bewusst nicht dargestellt
  gezählt, und die drei Zahlen werden gegen die Datensatzzahl der Quelle
  abgeglichen. Beschädigte Zeilen werden ebenfalls gezählt. Entgeht dem Parser
  etwas, sagt die Seite das, statt es zu verbergen.
- **Menschliche Beiträge sind wortgetreu** — Getipptes und Eingefügtes läuft
  nie durch einen Markdown-Renderer, sodass ein eingefügter *Traceback* oder
  ein spaltenförmiger *Benchmark* in jedem Format Byte für Byte erhalten
  bleibt.
- **Zitierfähige Referenzmarken** — jeder Prompt ist P1, P2, … und jede Antwort
  R1, R2, …, fortlaufend und im Dokument eindeutig (Beiträge von Subagenten
  bekommen das Präfix A1., A2., …), sodass eine Publikation „in Prompt P32"
  oder „in Antwort A2.R4" schreiben kann. Die Marken stehen in allen Formaten
  neben der Sprecherbezeichnung und sind im HTML Anker (`#P32` verlinkt direkt
  auf den Prompt).
- **Auflösung von Sitzungsketten** — ein fortgesetztes oder überbrücktes
  Gespräch wird in eine neue Datei geschrieben, die die früheren Datensätze
  wiederholt; der Archivar findet die vollständigste Datei durch Vergleich der
  Datensatz-UUID-Mengen, folgt echten Fortsetzungen und weigert sich,
  Abzweigungen zu folgen.
- **Verbrauchs- und Kostenrechnung** — Tokens pro Modell, dedupliziert nach
  `requestId` (naives Summieren der Datensätze überschätzt die Ausgabe bei
  werkzeuglastigen Sitzungen um ~2,3×), mit Cache-Lesevorgängen,
  5-Minuten- gegenüber 1-Stunden-Cache-Schreibvorgängen und einer
  Kostenschätzung zu Listenpreisen — **neben den von Claude Code selbst
  gemeldeten Kosten** aus dessen `cost-state`-Zähler (Claude Code ≥ 2.1.9x),
  über die Läufe der Sitzung summiert und über die Dateien einer fortgesetzten
  Sitzung zusammengetragen, und als *teilweise* gekennzeichnet, wenn die
  Sitzung vor ihrem ersten gemessenen Lauf begann.
- **Das Harness ist sichtbar** — Hook-Ausgaben, eingespielte Dateien,
  *Skill*-Ladevorgänge, Verdichtungszusammenfassungen und Systemdatensätze
  erscheinen in einer eingeklappten Spur samt der Klassifikationsbelege, statt
  zu verschwinden oder sich als Ihre Eingaben auszugeben.
- **Ehrlich über das Denken** — Claude Code fordert das Denken mit
  `display: "omitted"` an, also zeigt das Archiv, *dass* Claude an einer Stelle
  gedacht hat, und sagt klar, dass der Text nie ins Transkript gelangt.
- **In sich geschlossenes HTML** — Chat-Layout, helles und dunkles Thema mit
  einem Umschalter, den der Browser behält, ein Suchfeld, das nicht passende
  Beiträge ausblendet, filterbares Inhaltsverzeichnis, Umschalter pro Spur,
  Tastaturnavigation, keine externen Ressourcen. `--paginate N` teilt eine sehr
  große Sitzung in Seiten zu N Beiträgen, wobei Seitenleiste und
  Subagenten-Links über die Seiten hinweg verweisen.
- **Ein lebendiger Index mit Suche über alle Archive** — `--index` baut eine
  sortierbare Seite aller Sitzungen auf der Festplatte, mit einer
  Aktivitätsspalte, deren Altersangaben im Browser ohne Neuerzeugung altern,
  und einem Suchfeld über **jeden Prompt jedes Archivs** (beim Indizieren
  eingebettet, mit Direktlink auf den `#P`-Anker des Prompts auf seiner Seite);
  `--index --watch 300` erzeugt ihn in einer Schleife immer wieder neu, und die
  Seite lädt sich selbst nach — ein langsam getaktetes Dashboard, welche
  Gespräche gerade aktiv sind.
- **Vier weitere Sprachen für das Seitenmobiliar** — `--lang pt-BR|es|de|fr`
  (oder `CLAUDE_ARCHIVE_LANG`) setzt die eigenen Worte des Archivars —
  Beschriftungen, Überschriften, Hinweise, den Treuebericht, den Index — in
  brasilianisches Portugiesisch, Spanisch, Deutsch oder Französisch, in jedem
  Format. Das Gespräch wird nie übersetzt: Prompts, Antworten, Werkzeug-Ein-
  und -Ausgabe und Systemtext sind in jeder Sprache dieselben Bytes, und die
  Testsuite weist das Fragment für Fragment nach.
- **Werkzeugausgabe unter Ihrer Kontrolle** — `--tool-output on|off` unabhängig
  vom Format, und lange Ausgaben in der Mitte gekürzt (`--full`, um alles zu
  behalten), wobei jede Kürzung auf der Seite gezählt wird.
- **Übersteht echte Transkripte** — NUL-Bytes aus UTF-16-Konsolenmitschnitten,
  ANSI-Codes, Emoji, Zeilen mit 65.000 Zeichen, unaufgelöste Werkzeugaufrufe
  und nicht analysierbare Zeilen werden alle behandelt, gezählt und gemeldet.
- **Jeder Lauf ist aktenkundig** — `--verbose`/`--quiet` für die Konsole und
  ein Prüfprotokoll je Aufruf unter `<archive-dir>/logs/` (exakte Befehlszeile,
  Versionen, jede Meldung, Ausgang), mit `--log-dir` verschiebbar.
- **Geprüft wird, was kompiliert, nicht nur der Rückgabewert 0** — der
  LaTeX-Pfad teilt übergroße Beiträge und zerlegt lange oder breite Tabellen,
  damit nichts über die Seite hinausläuft, und die Suite kompiliert eine
  tabellenlastige Sitzung und zählt die Seiten, um zu belegen, dass die Zeilen
  angekommen sind. Ein sauberer Rückgabewert ist kein Beleg dafür, dass der
  Inhalt den Satz überstanden hat.
- Nur Standardbibliothek, eine Datei, 528 Prüfungen in der Testsuite, pyflakes
  und CI auf Linux/Windows/macOS.

## Wie sich das einordnet

[simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts)
ist das bekannteste Werkzeug in diesem Feld: per pip installierbar, mit
interaktiver Sitzungsauswahl, paginiertem, mobilfreundlichem HTML,
Git-Commit-Zeitleisten und Veröffentlichung in einem GitHub-Gist mit einem
Befehl. Andere Exporteure
([claude-session-exporter](https://github.com/rubicon/claude-session-exporter)
und mehrere ähnliche) zielen auf Markdown für Notiz-Sammlungen. Der Fokus
dieses Werkzeugs ist ein anderer: **Archivtreue und Druck** — der abgeglichene
Treuebericht, wortgetreue menschliche Beiträge, Verbrauchs- und
Kostenrechnung, Kettenauflösung und LaTeX/PDF-Ausgabe, die sich für den Anhang
einer Publikation eignet. Wenn Sie einen schnellen teilbaren Weblink wollen,
nehmen Sie Simons Werkzeug; wenn Sie eine vollständige, prüfbare Aufzeichnung
oder ein Dokument wollen, dieses.

## Fahrplan

Lücken, die zu schließen sich lohnt:

- **Erstklassige Unterstützung für Linux und macOS.** Die CI führt die Suite
  auf Linux und macOS aus. Linux hatte seinen ersten echten Lauf am 31.08.2026
  (WSL2 Ubuntu, Python 3.14): HTML, Text, Markdown und LaTeX einer echten
  Sitzung, `--index` über 88 Sitzungen und der Fehlerpfad ohne `xelatex`
  verhielten sich wie unter Windows. Im Feld noch unbestätigt:
  PDF-Kompilierung und TeX-Schriftpfade unter Linux, unter Linux erzeugte
  *Cowork*-Sitzungen und alles unter macOS. Berichte von Linux-/Mac-Nutzern
  sind besonders willkommen.
- **Skalierung.** Jeder Lauf liest alle Transkripte unter den Wurzeln erneut,
  um Ketten aufzulösen, und der Index vergleicht UUID-Mengen paarweise — gut
  für Hunderte von Sitzungen, langsam für Tausende. Ein zwischengespeicherter
  Scan ist der offensichtliche nächste Schritt.
- **Die Suche erfasst Prompts, nicht Antworten, über Archive hinweg.** Der
  Index durchsucht jeden menschlichen Prompt jedes Archivs; Claudes Antworten
  sind innerhalb einer Seite durchsuchbar. Auch die Antworten zu indizieren
  bedeutet eine viel größere Indexdatei und ist zurückgestellt, bis jemand es
  braucht.

(Subagenten-Darstellung, das Markdown-Format, die Erkennung von
*Cowork*-Sitzungen, der claude.ai-Importeur, die Paginierung, die Suche je
Seite und die Prompt-Suche über Archive hinweg, früher hier aufgeführt, sind
ausgeliefert. Jede Funktion und jede bekannte Einschränkung steht an einer
Stelle im [Benutzerhandbuch](docs/USER_MANUAL.de.md).) Zwei Vorbehalte zu den
Quellen: Der Aufbau des *Cowork*-Verzeichnisses folgt der dokumentierten
Struktur von Claude Desktop, wurde aber gegen synthetische Daten geprüft, und
der claude.ai-Importeur — inzwischen gegen einen echten Export vom August 2026
validiert (Treuebericht exakt abgeglichen, akzentuiertes UTF-8 unversehrt) —
zielt auf das Exportschema von Mitte 2026; jener Export enthielt keine
projektinternen Gespräche, daher sind Berichte über Exporte, die sich anders
analysieren lassen, besonders Projektgespräche, weiterhin willkommen.

## Wohin die Dateien gehen

Die Eingabe wird unter `--projects-root` (Vorgabe `~/.claude/projects`)
gefunden und, wenn das Verzeichnis existiert, unter `--cowork-root` (je
Plattform automatisch erkannt). Die Ausgabe landet in `--archive-dir` (Vorgabe
`~/claude-archives`, oder die Umgebungsvariable `CLAUDE_ARCHIVE_DIR`): jede
Sitzung wird dort zu `<session-id>_<title-slug>.<ext>`, eine Datei je Format
(claude.ai-Importe verwenden das UUID-Präfix des Gesprächs), `--index` schreibt
`index.html` in dasselbe Verzeichnis, und jeder Lauf hinterlässt ein
Prüfprotokoll in `logs/`. Um ein einzelnes Archiv genau zu platzieren, benennt
`--out pfad/zum/bericht` den Stamm — jedes Format hängt seine eigene Endung an.

## Reichweite

Der Archivar liest die Transkriptdateien, die Claude Code auf Ihre Festplatte
schreibt; was er archivieren kann, entscheidet sich also daran, wo das
Transkript einer Sitzung liegt:

| Claude-Oberfläche | Archivierbar? |
|---|---|
| Claude Code CLI | **Ja** — sein natives Format. |
| Claude-Code-Desktop-App | **Ja** — die Sitzungen laufen lokal und schreiben dieselben Dateien. |
| Claude Code Web/Mobil, zu Ihrem Rechner überbrückt | **Ja** — die lokale Seite schreibt ein Transkript, und die Brückendatensätze werden in der Kette aufgelöst, sodass die Teile als ein Gespräch herauskommen. |
| *Cowork* von Claude Desktop (lokaler Agentenmodus) | **Ja** — dasselbe Format unter einem anderen Basisverzeichnis, über `--cowork-root` (automatisch erkannt) in die Erkennung einbezogen. |
| claude.ai-Chats, Claude-Desktop-Chat, mobile App | **Über Export** — fordern Sie Ihren Datenexport an (Settings → Privacy → Export data) und führen Sie `--import-claude-ai conversations.json` aus. Der Export enthält weder Tokenverbrauch noch Modellnamen, und die Seite sagt das. |
| Claude-Code-Cloud-Sitzungen (nie überbrückt) | Nein — auf Ihre Festplatte wird nichts geschrieben. |

Zwei hart erarbeitete Tatsachen aus der Validierung gegen ein echtes Konto
(August 2026): Der claude.ai-Datenexport enthält **nur eigenständige Chats** —
Gespräche innerhalb von claude.ai-Projekten und *Cowork*-Sitzungen von Claude
Desktop stehen nicht darin — und der lokale *Cowork*-Speicher übersteht eine
Neuinstallation der App **nicht** — siehe *Warum es das gibt* oben.

## Ausprobieren

Ein vollständig erfundenes Schaugespräch liegt in `examples/` bei — eine Jagd
auf Nullmoden in einem Graphen-Nanoband, gebaut, um alles auszureizen:
Referenzmarken über zwei Modelle, ein fehlschlagender Werkzeugaufruf und sein
erneuter Versuch, eine wortgetreu eingefügte Tabelle, ein eingefügtes Bild,
Griechisch und Rahmenzeichen, ein Hintergrund-Subagent (markiert `A1.*`), eine
Kontextverdichtung, ein unaufgelöster Werkzeugaufruf und eine absichtlich
beschädigte Zeile, die der Treuebericht zählt.

```bash
python transcript_archiver.py 0000c0de-cafe-4000-8000-00000000f00d \
    --projects-root examples --archive-dir demo --format html,markdown,pdf
```

![Eine Seite des Schau-PDFs](docs/showcase-pdf.png)

## Formate

| | |
|---|---|
| `html` | Chat-Seite: Ihre Beiträge rechts, Claudes links, ein- und ausklappbare Werkzeug-Ein-/Ausgabe, filterbares Inhaltsverzeichnis, helles und dunkles Thema. In sich geschlossen — keine externen Ressourcen. |
| `text` | Reines UTF-8. Menschliche Beiträge und Werkzeugausgaben werden Byte für Byte wiedergegeben und nie neu umbrochen. |
| `markdown` | Für Notiz-Sammlungen (Obsidian usw.). Claudes Prosa ist Markdown und geht unverändert durch; menschliche Beiträge und Werkzeug-Ein-/Ausgabe stehen wortgetreu in Codeblöcken, deren Zäune länger sind als jede Backtick-Folge darin. |
| `latex` | Ein eigenständiges XeLaTeX-Dokument, oder mit `--fragment` ein Rumpf, den Sie in Ihre eigene Publikation `\input`en können. |
| `pdf` | Das mit `xelatex` kompilierte LaTeX (zwei Durchläufe, wegen des Inhaltsverzeichnisses). |

Alle fünf entstehen aus demselben analysierten Transkript, sodass ein Beitrag
nicht in einem Format erscheinen und in einem anderen verschwinden kann, und
jedes nennt in seinem eigenen Kopf, was sein Medium nicht tragen kann.

### Sprache

`--lang pt-BR|es|de|fr` übersetzt nur, was der Archivar selbst schreibt; das
Gespräch bleibt wortgetreu, das Prüfprotokoll bleibt englisch. Einzelheiten im
[Handbuch](docs/USER_MANUAL.de.md#sprache).

### Werkzeugausgabe

`--tool-output on|off` ist unabhängig von `--format`. Werkzeugargumente werden
überall lesbar aufbereitet, aber vollständige Ein- und Ausgabe macht aus einer
großen Sitzung ein Dokument von mehreren hundert Seiten, daher:

```bash
# ein lesbares PDF: Werkzeugaufrufe nur mit Namen, Nutzlasten weggelassen
python transcript_archiver.py <id> --format pdf --tool-output off

# die vollständige Aufzeichnung
python transcript_archiver.py <id> --format html --tool-output on
```

Eine Sitzung mit 1.655 Datensätzen umfasst 92 Seiten ohne Werkzeugausgabe und
260 mit ihr.

### Fragmente für eine Publikation

`--fragment` gibt den Rumpf ohne Präambel aus und transliteriert jedes Zeichen,
damit er auch unter **pdflatex** und nicht nur unter XeLaTeX kompiliert —
Griechisch wird zu Mathematik, Pfeile und Rahmenzeichen werden zu ASCII. Die
Präambel Ihres Wirtsdokuments braucht:

```latex
\usepackage{fvextra} \usepackage{xcolor} \usepackage{enumitem}
\usepackage{booktabs} \usepackage{array} \usepackage[most]{tcolorbox}
```

Die Beitragsumgebungen sind mit `\@ifundefined` definiert, sodass Sie jeden
Beitrag aus Ihrer eigenen Präambel umgestalten können, ohne die erzeugte Datei
zu bearbeiten.

## Was es richtig macht

Das waren alles echte Fehler, gefunden beim Lauf über Hunderttausende von
Datensätzen, und jeder ist jetzt durch einen Test abgedeckt:

- **Der Verbrauch wird nach `requestId` dedupliziert.** Eine API-Antwort wird
  als mehrere Datensätze geschrieben, die jeweils denselben kumulativen
  Verbrauch wiederholen; sie zu summieren überschätzt die Ausgabetokens bei
  einer werkzeuglastigen Sitzung um rund 2,3×.
- **Menschlich gegen eingespielt wird aus `promptSource`/`origin.kind`
  gelesen**, nicht aus dem Text erraten, damit vom Harness eingespielte Prompts
  nicht als Ihre Eingaben dargestellt werden.
- **Sitzungsketten werden aufgelöst.** Ein fortgesetztes oder überbrücktes
  Gespräch wird in eine *neue* Datei geschrieben, die die früheren Datensätze
  wiederholt; die zufällig genannte ID zu archivieren kann also ein halbes
  Gespräch erfassen. Vergleichen Sie UUID-Mengen, nicht Dateinamen oder
  Datensatzzahlen — die kürzere Datei kann mehr Gespräch enthalten.
- **Menschliche Beiträge laufen nie durch den Markdown-Renderer.** Sie sind
  getippter und eingefügter Text; sie zu interpretieren presst einen
  eingefügten *Traceback* zu Prosa zusammen.
- **Denkblöcke sind immer leer.** Claude Code fordert sie mit
  `display: "omitted"` an, sodass ein Archiv zeigen kann, *dass* Claude an
  einer Stelle gedacht hat, nie aber, was. Die Seite sagt das, statt das
  Gegenteil nahezulegen.

## Tests

```bash
python tests/test_archiver.py
```

528 Prüfungen, ausgeführt gegen die synthetischen Sitzungen in `examples/` — in
sich geschlossen, kein echtes Transkript nötig. Die LaTeX-/PDF-Prüfungen werden
übersprungen (nicht als Fehler gewertet), wenn keine TeX-Installation im `PATH`
liegt; alles Übrige braucht nur Python. Die Suite prüft außerdem, dass
Benutzerhandbuch und `AGENTS.md` jede Kommandozeilenoption dokumentieren und
dass die hier genannte Prüfungszahl aktuell ist. Um sie an einem großen,
unordentlichen eigenen Gespräch zu erproben:

```bash
CLAUDE_PROJECTS=~/.claude/projects SAMPLE_SESSION=<id> python tests/test_archiver.py
```

Das Muster erzeugt `examples/make_sample.py`; es ist bewusst so gebaut, dass es
trägt, was an echten Daten zerbrach: einen eingefügten Block, dessen Spalten
nicht neu umbrochen werden dürfen, Griechisch und Rahmenzeichen, NUL-Bytes aus
byteweise mitgeschnittener UTF-16-Ausgabe, eine Zeile mit 3.000 Zeichen, einen
leeren Denkblock, einen unaufgelösten Werkzeugaufruf, eine Markdown-Liste, die
mittendrin den Aufzählungszeichentyp wechselt, einen Beitrag, der die eigenen
Vorlagenplatzhalter des Archivars zitiert, und eine absichtlich beschädigte
Zeile, die der Treuebericht zählen und nicht stillschweigend überspringen muss.

## Voraussetzungen

Python 3.9+ für die Formate HTML und Text — nur Standardbibliothek.

LaTeX und PDF brauchen eine TeX-Installation, die `xelatex`, `fvextra`,
`tcolorbox`, `array` und die DejaVu-Schriften bereitstellt (TeX Lives
`scheme-full` hat alles davon). Schriften werden **nach Dateiname aus TeX
Live** geladen, nicht aus dem System, sodass die Ausgabe nicht von der
Schriftdatenbank des Rechners abhängt.

Die Kostenzahlen stammen aus der `PRICING`-Tabelle am Kopf des Skripts —
öffentliche Listenpreise, fest eingetragen mit Stand August 2026. Wenn sich die
Preise ändern, bearbeiten Sie diese Tabelle; Modelle, die sie nicht kennt,
werden als „kein Listenpreis" gemeldet statt falsch bepreist.

## Wie es gebaut wurde

Gewissermaßen unter eigener Beobachtung: Das gesamte Werkzeug entstand in
Claude Code (Opus 5 und Fable 5), und jede dieser Entwicklungssitzungen ist
durch das Ergebnis archivierbar. Der Aufwand, rekonstruiert aus den
Sitzungstranskripten: **zehn Tage vom ersten Prototyp bis zur Freigabe**
(16.–26. August 2026), über etwa acht lange Arbeitssitzungen — rund 40 MB
Rohtranskript — und 15 Commits. Der erste öffentliche Commit kam erst am
neunten Tag — alles davor war Überlebenstest. Es folgten zwei weitere Tage
prüfungsgetriebener Freigaben (2.4 → 2.6.6, 28.–31. August: drei vollständige
Projektdurchsichten, ein unabhängiger Code-Review-Durchgang, Überlebensläufe,
die sechs neue Datensatztypen aufdeckten, die Claude Code zu schreiben begonnen
hatte, und die Korrekturen, die jeder davon verlangte — die letzte davon eine
Tabelle, die sauber kompilierte und dabei ihre Zeilen verlor), was die
Historie auf 38 Commits brachte; die anschließende Pflege — den *vendorierten*
Konformitätsprüfer Byte für Byte identisch zum Publikationshandbuch zu halten —
bringt sie auf 61 Commits (2.7.2, eine Regression, die der Überlebenslauf mit
echten Daten nach einer durchweg grünen Suite aufdeckte, 2.7.3–2.7.7, fünf
Runden unabhängiger Durchsicht, von denen jede echte Fehler in der Korrektur
der vorigen Runde fand — stets in deren Fehlerpfad, nie im glücklichen Pfad —
und 2.8.0, das die Ablage auf den Produktstandard brachte
(Sicherheitsrichtlinie, Plattformnachweis, Drittanbieter-Inventar) und README
und Handbuch in vier weitere Sprachen übersetzte, sind die letzten sieben).

Die Arbeitsteilung, rekonstruiert aus denselben Transkripten und in
[CRediT](https://credit.niso.org/)-Begriffen ausgedrückt (der
Beitragsrollen-Taxonomie wissenschaftlicher Publikationen):

| CRediT-Rolle | Fabio | Claude |
|---|---|---|
| **Konzeption** | Die Prämisse — eine in sich geschlossene, vollständig getreue Aufzeichnung einer KI-gestützten Sitzung, tauglich für wissenschaftliche Berichterstattung — und die meisten Funktionsideen: P/R-Zitiermarken, der Werkzeugausgabe-Schalter, der Live-Aktivitätsindex, die Paginierung | Das Abgleichmodell darstellen/einfalten/zählen, aus dem der Treuebericht wurde |
| **Methodik** | Die Prioritätenfolge (zuerst Inhaltstreue, dann Quellen, dann Formate); die Anforderungen des wissenschaftlichen Publizierens, die das LaTeX-Fragment prägten | Kettenauflösung durch UUID-Mengenvergleich; Verbrauchsdeduplizierung je `requestId`; die Regel des wortgetreuen menschlichen Beitrags |
| **Software** | — | Alles |
| **Validierung** | Zerlegte jeden Build gegen Hunderttausende Datensätze eines echten Archivs; fand die Fehler bei veralteter Seite, Überlauf und Layout; setzte die Messlatte (*„das braucht hohe Genauigkeit"*); beauftragte die Durchsichts- und Code-Review-Durchgänge | Die Suite mit 296 Prüfungen und die CI; die prüfungsgetriebenen Überlebensläufe |
| **Untersuchung** | Leitete die Erhebung benachbarter Werkzeuge | Code- und Dokumentationsanalyse für den Vergleichsabschnitt |
| **Datenkuratierung** | — | Das synthetische Muster und das Schaugespräch, gebaut, um genau die Fälle zu tragen, die an echten Daten zerbrochen waren |
| **Visualisierung** | Das Chat-Layout (Mensch rechts, Claude links), der Kastenstil, die Platzierung von Marken und Zeitstempeln | Das HTML/CSS, das es umsetzt |
| **Schreiben** | Durchsicht und Redaktion | Erstentwurf (README, Commit-Nachrichten) |
| **Ressourcen · Betreuung · Projektverwaltung · Einwerbung von Mitteln** | Alles | — |

## Lizenz

Apache-Lizenz 2.0 — siehe `LICENSE` und `NOTICE`. Sie dürfen sie nutzen,
verändern und weitergeben, auch kommerziell, sofern Lizenz und Hinweis
mitreisen; Beiträge werden zu denselben Bedingungen angenommen (Abschnitt 5).

### Haftungsausschluss

Diese Software wird **wie besehen** bereitgestellt, ohne Gewährleistungen oder
Bedingungen irgendeiner Art, ausdrücklich oder stillschweigend, einschließlich,
aber nicht beschränkt auf Gewährleistungen der Marktgängigkeit, der Eignung für
einen bestimmten Zweck, der Rechtsinhaberschaft oder der Nichtverletzung von
Rechten. In keinem Fall haftet der Autor für Schäden irgendwelcher Art —
unmittelbare, mittelbare, besondere, beiläufig entstandene oder Folgeschäden —
oder für sonstige Ansprüche oder Haftung, sei es aus Vertrag, unerlaubter
Handlung oder anderweitig, die sich aus der Software oder ihrer Nutzung
ergeben oder damit zusammenhängen, selbst wenn auf die Möglichkeit solcher
Schäden hingewiesen wurde (Apache-Lizenz 2.0, Abschnitte 7 und 8). Allein Sie
sind dafür verantwortlich, sie rechtmäßig zu nutzen, für die Transkripte und
Daten, die Sie ihr zuführen und damit veröffentlichen, und für die Einhaltung
der Bedingungen jedes Dienstes und jedes Inhalts Dritter, den sie berührt.

Dies ist ein unabhängiges Projekt. Es ist nicht mit Anthropic verbunden, wird
von Anthropic weder unterstützt noch gefördert; *Claude* und *Claude Code*
sind Marken von Anthropic, PBC, hier nur verwendet, um die Software zu
benennen, deren Transkripte dieses Werkzeug archiviert.
