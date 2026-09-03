#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
"""
transcript_archiver.py -- turn a Claude conversation into a self-contained
document (HTML, plain text, Markdown, LaTeX or PDF) with a fidelity report
proving nothing was silently dropped.

Every record in the source .jsonl is parsed into a typed model and either
rendered, folded into an earlier turn, or counted -- and the three numbers are
reconciled against the source record count on the page itself.

USAGE
    python transcript_archiver.py <session-id> [--title "..."] [options]
    python transcript_archiver.py <id> --format html,text,markdown,latex,pdf
    python transcript_archiver.py <id> --format latex --fragment   # body only
    python transcript_archiver.py --import-claude-ai conversations.json
    python transcript_archiver.py --index [--watch 300]

SOURCES
    Claude Code sessions (~/.claude/projects), Claude Desktop cowork sessions
    (--cowork-root, auto-detected) and claude.ai data exports
    (--import-claude-ai), all through one pipeline.

FORMATS
    All five render from the same parsed transcript, so a turn cannot appear in
    one format and vanish from another. pdf is the LaTeX compiled by xelatex;
    --fragment emits an engine-neutral body for \\input into your own paper.
    --tool-output on|off is independent of the format: full tool I/O turns a
    large session into a several-hundred-page document.

Human turns are reproduced verbatim in every format; every prompt and
response carries a citable tag (P1.., R1.., subagents A1.P1..). Thinking
blocks are empty in Claude Code transcripts (display=omitted) and the page
says so. The summary section is hand-written: pass --summary-file.

Full documentation: docs/USER_MANUAL.md (humans) and AGENTS.md (agents).
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import math
import os
import re
import sys
import subprocess
import shutil
import textwrap
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

esc = html.escape

VERSION = "2.7.2"

# ---------------------------------------------------------------------------
# Document language (--lang / CLAUDE_ARCHIVE_LANG)
#
# Only the archiver's own words change: headings, labels, notes, the index.
# The conversation -- prompts, answers, thinking, tool names, tool input and
# output, system text, model names, titles, paths -- is never touched, and
# the audit log, the console and --help stay English. Keys are the English
# text; a missing entry falls back to it at runtime, and the suite fails on
# any key that is not translated in every language, so no fallback ships.
# ---------------------------------------------------------------------------

LANGS = ("en", "pt-BR", "es", "de", "fr")
LANG = "en"


def _(s: str) -> str:
    if LANG == "en":
        return s
    return L10N[LANG].get(s, s)


# Parser labels (badges) are English identifiers at parse time and are
# translated where they are rendered, through the same lookup.
L10N_DYNAMIC_KEYS = (
    "Context compaction summary", "Background task notification",
    "Harness-injected prompt", "Scheduled continuation",
    "Instructions injected into the turn",
)

_TEX_LANGUAGE = {
    "pt-BR": "[variant=brazilian]{portuguese}",
    "es": "{spanish}", "de": "{german}", "fr": "{french}",
}
_TEX_LANGNAME = {"pt-BR": "portuguese", "es": "spanish", "de": "german", "fr": "french"}

_L10N_ROWS = [
    # (english, pt-BR, es, de, fr)
    # -- page shell -----------------------------------------------------
    ("Session Transcript", "Transcrição da sessão", "Transcripción de la sesión",
     "Sitzungstranskript", "Transcription de session"),
    (" — page {k}/{n}", " — página {k}/{n}", " — página {k}/{n}",
     " — Seite {k}/{n}", " — page {k}/{n}"),
    ("Search turns", "Buscar nos turnos", "Buscar en los turnos",
     "Beiträge durchsuchen", "Rechercher dans les tours"),
    ("Filter contents  ( / )", "Filtrar o sumário  ( / )", "Filtrar el contenido  ( / )",
     "Inhalt filtern  ( / )", "Filtrer le sommaire  ( / )"),
    ("Filter contents", "Filtrar o sumário", "Filtrar el contenido",
     "Inhalt filtern", "Filtrer le sommaire"),
    ("thinking", "raciocínio", "razonamiento", "Denken", "réflexion"),
    ("tools", "ferramentas", "herramientas", "Werkzeuge", "outils"),
    ("harness", "harness", "harness", "Harness", "harness"),
    ("events", "eventos", "eventos", "Ereignisse", "événements"),
    ("subagents", "subagentes", "subagentes", "Subagenten", "sous-agents"),
    ("Expand all", "Expandir tudo", "Expandir todo", "Alle aufklappen", "Tout déplier"),
    ("Collapse all", "Recolher tudo", "Contraer todo", "Alle einklappen", "Tout replier"),
    ("Dark theme", "Tema escuro", "Tema oscuro", "Dunkles Design", "Thème sombre"),
    ("Light theme", "Tema claro", "Tema claro", "Helles Design", "Thème clair"),
    ("{shown} of {total} turns match", "{shown} de {total} turnos correspondem",
     "{shown} de {total} turnos coinciden", "{shown} von {total} Beiträgen passen",
     "{shown} tours sur {total} correspondent"),
    ("Session", "Sessão", "Sesión", "Sitzung", "Session"),
    ("Contents", "Sumário", "Contenido", "Inhalt", "Sommaire"),
    ("Timestamps are local; hover for UTC. <kbd>j</kbd>/<kbd>k</kbd> jump between human turns, "
     "<kbd>/</kbd> filters the contents list, the search box hides turns that do not match. "
     "Thinking, tool I/O and harness events are collapsed &mdash; use the toggles to hide a lane entirely.",
     "Os horários são locais; passe o mouse para ver em UTC. <kbd>j</kbd>/<kbd>k</kbd> saltam entre "
     "turnos humanos, <kbd>/</kbd> filtra o sumário, a caixa de busca oculta os turnos que não "
     "correspondem. Raciocínio, E/S de ferramentas e eventos do harness ficam recolhidos &mdash; use "
     "as caixas de seleção para ocultar uma faixa inteira.",
     "Las horas son locales; pase el ratón para ver UTC. <kbd>j</kbd>/<kbd>k</kbd> saltan entre "
     "turnos humanos, <kbd>/</kbd> filtra el contenido, el cuadro de búsqueda oculta los turnos que "
     "no coinciden. Razonamiento, E/S de herramientas y eventos del harness están contraídos &mdash; "
     "use las casillas para ocultar una franja por completo.",
     "Zeitangaben sind lokal; UTC beim Überfahren. <kbd>j</kbd>/<kbd>k</kbd> springen zwischen "
     "menschlichen Beiträgen, <kbd>/</kbd> filtert das Inhaltsverzeichnis, das Suchfeld blendet "
     "nicht passende Beiträge aus. Denken, Werkzeug-E/A und Harness-Ereignisse sind eingeklappt "
     "&mdash; mit den Schaltern lässt sich eine Spur ganz ausblenden.",
     "Les horodatages sont locaux ; survolez pour l'UTC. <kbd>j</kbd>/<kbd>k</kbd> passent d'un tour "
     "humain à l'autre, <kbd>/</kbd> filtre le sommaire, le champ de recherche masque les tours sans "
     "correspondance. Réflexion, E/S des outils et événements du harness sont repliés &mdash; les "
     "cases à cocher masquent une voie entière."),
    ("Page {cur} of {n}", "Página {cur} de {n}", "Página {cur} de {n}",
     "Seite {cur} von {n}", "Page {cur} sur {n}"),
    ("&larr; prev", "&larr; anterior", "&larr; anterior", "&larr; zurück", "&larr; précédente"),
    ("next &rarr;", "próxima &rarr;", "siguiente &rarr;", "weiter &rarr;", "suivante &rarr;"),
    # -- turn labels ----------------------------------------------------
    ("Human", "Humano", "Humano", "Mensch", "Humain"),
    ("System", "Sistema", "Sistema", "System", "Système"),
    ("Event", "Evento", "Evento", "Ereignis", "Événement"),
    ("Thinking", "Raciocínio", "Razonamiento", "Denken", "Réflexion"),
    ("subagent", "subagente", "subagente", "Subagent", "sous-agent"),
    ("transcript &darr;", "transcrição &darr;", "transcripción &darr;",
     "Transkript &darr;", "transcription &darr;"),
    ("how this was classified", "como isto foi classificado", "cómo se clasificó esto",
     "wie dies eingeordnet wurde", "comment ceci a été classé"),
    ("pasted image", "imagem colada", "imagen pegada", "eingefügtes Bild", "image collée"),
    ("raw", "bruto", "bruto", "roh", "brut"),
    ("(no content)", "(sem conteúdo)", "(sin contenido)", "(kein Inhalt)", "(aucun contenu)"),
    ("Input", "Entrada", "Entrada", "Eingabe", "Entrée"),
    ("Output", "Saída", "Salida", "Ausgabe", "Sortie"),
    ("Output (error)", "Saída (erro)", "Salida (error)", "Ausgabe (Fehler)", "Sortie (erreur)"),
    ("{n} chars elided", "{n} caracteres omitidos", "{n} caracteres omitidos",
     "{n} Zeichen ausgelassen", "{n} caractères omis"),
    ("(empty result)", "(resultado vazio)", "(resultado vacío)", "(leeres Ergebnis)", "(résultat vide)"),
    ("No result in the source &mdash; this call was still running (or was interrupted) when the "
     "transcript was written.",
     "Sem resultado na fonte &mdash; esta chamada ainda estava em execução (ou foi interrompida) "
     "quando a transcrição foi gravada.",
     "Sin resultado en la fuente &mdash; esta llamada seguía en ejecución (o fue interrumpida) "
     "cuando se escribió la transcripción.",
     "Kein Ergebnis in der Quelle &mdash; dieser Aufruf lief noch (oder wurde unterbrochen), als "
     "das Transkript geschrieben wurde.",
     "Aucun résultat dans la source &mdash; cet appel était encore en cours (ou a été interrompu) "
     "quand la transcription a été écrite."),
    ("Screenshot", "Captura de tela", "Captura de pantalla", "Bildschirmfoto", "Capture d'écran"),
    ("tool screenshot", "captura de tela da ferramenta", "captura de pantalla de la herramienta",
     "Bildschirmfoto des Werkzeugs", "capture d'écran de l'outil"),
    # -- parser labels, translated where rendered ------------------------
    ("Context compaction summary", "Resumo de compactação do contexto",
     "Resumen de compactación del contexto", "Zusammenfassung der Kontextkompaktierung",
     "Résumé de compactage du contexte"),
    ("Background task notification", "Notificação de tarefa em segundo plano",
     "Notificación de tarea en segundo plano", "Benachrichtigung einer Hintergrundaufgabe",
     "Notification de tâche en arrière-plan"),
    ("Harness-injected prompt", "Prompt injetado pelo harness", "Prompt inyectado por el harness",
     "Vom Harness eingefügter Prompt", "Prompt injecté par le harness"),
    ("Scheduled continuation", "Continuação agendada", "Continuación programada",
     "Geplante Fortsetzung", "Reprise planifiée"),
    ("Instructions injected into the turn", "Instruções injetadas no turno",
     "Instrucciones inyectadas en el turno", "In den Beitrag eingefügte Anweisungen",
     "Instructions injectées dans le tour"),
    ("Hook", "Hook", "Hook", "Hook", "Hook"),
    ("Hook context injected", "Contexto de hook injetado", "Contexto de hook inyectado",
     "Hook-Kontext eingefügt", "Contexte de hook injecté"),
    ("Hook message", "Mensagem de hook", "Mensaje de hook", "Hook-Nachricht", "Message de hook"),
    ("Skill listing injected", "Lista de skills injetada", "Lista de skills inyectada",
     "Skill-Liste eingefügt", "Liste des skills injectée"),
    ("Skill invoked", "Skill invocada", "Skill invocada", "Skill aufgerufen", "Skill invoquée"),
    ("Project memory injected", "Memória do projeto injetada", "Memoria del proyecto inyectada",
     "Projektgedächtnis eingefügt", "Mémoire du projet injectée"),
    ("File injected", "Arquivo injetado", "Archivo inyectado", "Datei eingefügt", "Fichier injecté"),
    ("File edit snapshot", "Instantâneo de edição de arquivo", "Instantánea de edición de archivo",
     "Momentaufnahme einer Dateiänderung", "Instantané d'édition de fichier"),
    ("File carried through compaction", "Arquivo preservado na compactação",
     "Archivo conservado en la compactación", "Datei über die Kompaktierung mitgeführt",
     "Fichier conservé lors du compactage"),
    ("Read truncated", "Leitura truncada", "Lectura truncada", "Lesen abgeschnitten", "Lecture tronquée"),
    ("Deferred tools changed", "Ferramentas adiadas alteradas", "Herramientas diferidas modificadas",
     "Zurückgestellte Werkzeuge geändert", "Outils différés modifiés"),
    ("Agent listing changed", "Lista de agentes alterada", "Lista de agentes modificada",
     "Agentenliste geändert", "Liste des agents modifiée"),
    ("MCP instructions injected", "Instruções MCP injetadas", "Instrucciones MCP inyectadas",
     "MCP-Anweisungen eingefügt", "Instructions MCP injectées"),
    ("Command permissions", "Permissões de comando", "Permisos de comando",
     "Befehlsberechtigungen", "Permissions de commande"),
    ("Task reminder", "Lembrete de tarefa", "Recordatorio de tarea", "Aufgabenerinnerung", "Rappel de tâche"),
    ("Command queued", "Comando enfileirado", "Comando en cola", "Befehl eingereiht", "Commande mise en file"),
    ("Date changed", "Data alterada", "Fecha cambiada", "Datum geändert", "Date modifiée"),
    ("Token-budget reminder", "Lembrete de orçamento de tokens", "Recordatorio de presupuesto de tokens",
     "Erinnerung an das Token-Budget", "Rappel du budget de jetons"),
    ("Turn duration", "Duração do turno", "Duración del turno", "Beitragsdauer", "Durée du tour"),
    ("Local slash command", "Comando de barra local", "Comando de barra local",
     "Lokaler Slash-Befehl", "Commande slash locale"),
    ("Session bridged", "Sessão conectada por ponte", "Sesión enlazada", "Sitzung überbrückt", "Session pontée"),
    ("Scheduled task fired", "Tarefa agendada disparada", "Tarea programada ejecutada",
     "Geplante Aufgabe ausgelöst", "Tâche planifiée déclenchée"),
    ("Context compacted", "Contexto compactado", "Contexto compactado", "Kontext kompaktiert", "Contexte compacté"),
    ("Model fallback after a safeguard refusal", "Modelo substituído após uma recusa de segurança",
     "Modelo de respaldo tras un rechazo de seguridad", "Modellwechsel nach einer Schutzverweigerung",
     "Modèle de repli après un refus de sécurité"),
    ("Away summary", "Resumo de ausência", "Resumen de ausencia", "Abwesenheitszusammenfassung", "Résumé d'absence"),
    ("Harness nudge", "Lembrete do harness", "Aviso del harness", "Harness-Hinweis", "Rappel du harness"),
    ("Local command output", "Saída de comando local", "Salida de comando local",
     "Ausgabe eines lokalen Befehls", "Sortie de commande locale"),
    ("Local command caveat", "Ressalva de comando local", "Advertencia de comando local",
     "Vorbehalt zu einem lokalen Befehl", "Réserve de commande locale"),
    ("Prompt-submit hook", "Hook de envio de prompt", "Hook de envío de prompt",
     "Hook beim Absenden des Prompts", "Hook d'envoi de prompt"),
    ("Loop heartbeat", "Pulso do loop", "Latido del bucle", "Schleifen-Herzschlag", "Battement de boucle"),
    ("Skill already loaded", "Skill já carregada", "Skill ya cargada", "Skill bereits geladen", "Skill déjà chargée"),
    ("Interrupted by user", "Interrompido pelo usuário", "Interrumpido por el usuario",
     "Vom Benutzer unterbrochen", "Interrompu par l'utilisateur"),
    ("Image scaling note", "Nota de redimensionamento de imagem", "Nota de escalado de imagen",
     "Hinweis zur Bildskalierung", "Note de mise à l'échelle d'image"),
    ("{n} finding(s)", "{n} achado(s)", "{n} hallazgo(s)", "{n} Befund(e)", "{n} constat(s)"),
    ("{n} item(s)", "{n} item(ns)", "{n} elemento(s)", "{n} Eintrag/Einträge", "{n} élément(s)"),
    ("{n} message(s) were retracted by the harness after this refusal",
     "{n} mensagem(ns) foram retratadas pelo harness após esta recusa",
     "{n} mensaje(s) fueron retractados por el harness tras este rechazo",
     "{n} Nachricht(en) wurden vom Harness nach dieser Verweigerung zurückgenommen",
     "{n} message(s) ont été retirés par le harness après ce refus"),
    ("; {n} of them are not in the source transcript", "; {n} delas não estão na transcrição de origem",
     "; {n} de ellos no están en la transcripción de origen", "; {n} davon fehlen im Quelltranskript",
     " ; {n} d'entre eux ne sont pas dans la transcription source"),
    (". The conversation continued on {model}.", ". A conversa continuou em {model}.",
     ". La conversación continuó en {model}.", ". Das Gespräch wurde auf {model} fortgesetzt.",
     ". La conversation s'est poursuivie sur {model}."),
    # -- session info ---------------------------------------------------
    ("Session ID", "ID da sessão", "ID de la sesión", "Sitzungs-ID", "ID de session"),
    ("Requested", "Solicitada", "Solicitada", "Angefordert", "Demandée"),
    ("Started", "Início", "Inicio", "Beginn", "Début"),
    ("Last record", "Último registro", "Último registro", "Letzter Datensatz", "Dernier enregistrement"),
    ("Archived at", "Arquivada em", "Archivada el", "Archiviert am", "Archivée le"),
    ("Wall clock", "Tempo decorrido", "Tiempo transcurrido", "Gesamtdauer", "Durée totale"),
    ("Active time", "Tempo ativo", "Tiempo activo", "Aktive Zeit", "Temps actif"),
    ("summed from {n} turn_duration records", "somado de {n} registros turn_duration",
     "sumado de {n} registros turn_duration", "Summe aus {n} turn_duration-Datensätzen",
     "somme de {n} enregistrements turn_duration"),
    ("estimated (no turn_duration records; gaps over 20m ignored)",
     "estimado (sem registros turn_duration; intervalos acima de 20 min ignorados)",
     "estimado (sin registros turn_duration; pausas de más de 20 min ignoradas)",
     "geschätzt (keine turn_duration-Datensätze; Pausen über 20 min ignoriert)",
     "estimé (aucun enregistrement turn_duration ; pauses de plus de 20 min ignorées)"),
    ("Models", "Modelos", "Modelos", "Modelle", "Modèles"),
    ("Effort", "Esforço", "Esfuerzo", "Aufwand", "Effort"),
    ("Working dir", "Diretório de trabalho", "Directorio de trabajo", "Arbeitsverzeichnis", "Répertoire de travail"),
    ("Human turns", "Turnos humanos", "Turnos humanos", "Menschliche Beiträge", "Tours humains"),
    ("Claude messages", "Mensagens do Claude", "Mensajes de Claude", "Claude-Nachrichten", "Messages de Claude"),
    ("Thinking blocks", "Blocos de raciocínio", "Bloques de razonamiento", "Denkblöcke", "Blocs de réflexion"),
    ("{with} with text, {empty} empty", "{with} com texto, {empty} vazios",
     "{with} con texto, {empty} vacíos", "{with} mit Text, {empty} leer", "{with} avec texte, {empty} vides"),
    ("Claude Code requests thinking with display=omitted, so the reasoning text is never written "
     "to the transcript",
     "O Claude Code solicita o raciocínio com display=omitted, portanto o texto do raciocínio "
     "nunca é gravado na transcrição",
     "Claude Code solicita el razonamiento con display=omitted, así que el texto del razonamiento "
     "nunca se escribe en la transcripción",
     "Claude Code fordert das Denken mit display=omitted an, daher wird der Denktext nie ins "
     "Transkript geschrieben",
     "Claude Code demande la réflexion avec display=omitted, le texte du raisonnement n'est donc "
     "jamais écrit dans la transcription"),
    ("Tool calls", "Chamadas de ferramenta", "Llamadas a herramientas", "Werkzeugaufrufe", "Appels d'outils"),
    ("Subagents", "Subagentes", "Subagentes", "Subagenten", "Sous-agents"),
    ("{n} transcript(s), {records} records", "{n} transcrição(ões), {records} registros",
     "{n} transcripción(es), {records} registros", "{n} Transkript(e), {records} Datensätze",
     "{n} transcription(s), {records} enregistrements"),
    (" (not rendered: --subagents off)", " (não renderizadas: --subagents off)",
     " (no renderizadas: --subagents off)", " (nicht dargestellt: --subagents off)",
     " (non rendues : --subagents off)"),
    ("Harness events", "Eventos do harness", "Eventos del harness", "Harness-Ereignisse", "Événements du harness"),
    ("Output tokens", "Tokens de saída", "Tokens de salida", "Ausgabe-Tokens", "Jetons de sortie"),
    ("Cache reads", "Leituras de cache", "Lecturas de caché", "Cache-Lesezugriffe", "Lectures du cache"),
    ("List cost", "Custo de tabela", "Costo de lista", "Listenpreis", "Coût catalogue"),
    ("Reported cost", "Custo informado", "Costo informado", "Gemeldete Kosten", "Coût déclaré"),
    ("${usd} reported by Claude Code ({runs} run(s){partial})",
     "${usd} informados pelo Claude Code ({runs} execução(ões){partial})",
     "${usd} informados por Claude Code ({runs} ejecución(es){partial})",
     "${usd} von Claude Code gemeldet ({runs} Lauf/Läufe{partial})",
     "${usd} déclarés par Claude Code ({runs} exécution(s){partial})"),
    (", partial: earlier runs not covered", ", parcial: execuções anteriores não cobertas",
     ", parcial: ejecuciones anteriores no cubiertas", ", unvollständig: frühere Läufe nicht erfasst",
     ", partiel : exécutions antérieures non couvertes"),
    ("Compactions", "Compactações", "Compactaciones", "Kompaktierungen", "Compactages"),
    ("Harness retractions", "Retratações do harness", "Retractaciones del harness",
     "Harness-Rücknahmen", "Retraits par le harness"),
    ("{n} message(s) after a safeguard refusal at {time} UTC, {src} -> {dst}",
     "{n} mensagem(ns) após uma recusa de segurança às {time} UTC, {src} -> {dst}",
     "{n} mensaje(s) tras un rechazo de seguridad a las {time} UTC, {src} -> {dst}",
     "{n} Nachricht(en) nach einer Schutzverweigerung um {time} UTC, {src} -> {dst}",
     "{n} message(s) après un refus de sécurité à {time} UTC, {src} -> {dst}"),
    (", {n} absent from the source", ", {n} ausente(s) da fonte", ", {n} ausente(s) de la fuente",
     ", {n} nicht in der Quelle", ", {n} absent(s) de la source"),
    ("Skills used", "Skills usadas", "Skills usadas", "Verwendete Skills", "Skills utilisées"),
    ("{start} – {end} · {humans} human turns · {tools} tool calls · ",
     "{start} – {end} · {humans} turnos humanos · {tools} chamadas de ferramenta · ",
     "{start} – {end} · {humans} turnos humanos · {tools} llamadas a herramientas · ",
     "{start} – {end} · {humans} menschliche Beiträge · {tools} Werkzeugaufrufe · ",
     "{start} – {end} · {humans} tours humains · {tools} appels d'outils · "),
    ("${usd} reported by Claude Code", "${usd} informados pelo Claude Code",
     "${usd} informados por Claude Code", "${usd} von Claude Code gemeldet", "${usd} déclarés par Claude Code"),
    ("${usd} at list price", "${usd} a preço de tabela", "${usd} a precio de lista",
     "${usd} zum Listenpreis", "${usd} au prix catalogue"),
    # -- sections -------------------------------------------------------
    ("Session summary", "Resumo da sessão", "Resumen de la sesión", "Sitzungszusammenfassung", "Résumé de la session"),
    ("Usage &amp; cost", "Uso e custo", "Uso y costo", "Nutzung &amp; Kosten", "Utilisation &amp; coût"),
    ("Fidelity report", "Relatório de fidelidade", "Informe de fidelidad",
     "Bericht zur Wiedergabetreue", "Rapport de fidélité"),
    ("Subagent transcripts", "Transcrições de subagentes", "Transcripciones de subagentes",
     "Subagenten-Transkripte", "Transcriptions des sous-agents"),
    ("Conversations run by background agents this session spawned. Each lives in its own file "
     "beside the session and is rendered here in full, with the same rules as the main transcript.",
     "Conversas conduzidas por agentes em segundo plano criados nesta sessão. Cada uma fica em seu "
     "próprio arquivo ao lado da sessão e é renderizada aqui na íntegra, com as mesmas regras da "
     "transcrição principal.",
     "Conversaciones de los agentes en segundo plano creados en esta sesión. Cada una vive en su "
     "propio archivo junto a la sesión y se renderiza aquí completa, con las mismas reglas que la "
     "transcripción principal.",
     "Gespräche der Hintergrundagenten, die diese Sitzung gestartet hat. Jedes liegt in einer "
     "eigenen Datei neben der Sitzung und wird hier vollständig dargestellt, nach denselben Regeln "
     "wie das Haupttranskript.",
     "Conversations menées par les agents d'arrière-plan lancés par cette session. Chacune vit dans "
     "son propre fichier à côté de la session et est rendue ici intégralement, selon les mêmes "
     "règles que la transcription principale."),
    ("{records} records &middot; {turns} turns &middot; turns tagged A{k}.P/A{k}.R",
     "{records} registros &middot; {turns} turnos &middot; turnos marcados A{k}.P/A{k}.R",
     "{records} registros &middot; {turns} turnos &middot; turnos etiquetados A{k}.P/A{k}.R",
     "{records} Datensätze &middot; {turns} Beiträge &middot; Beiträge markiert A{k}.P/A{k}.R",
     "{records} enregistrements &middot; {turns} tours &middot; tours étiquetés A{k}.P/A{k}.R"),
    (" (archived here)", " (arquivada aqui)", " (archivada aquí)", " (hier archiviert)", " (archivée ici)"),
    ("{shared} shared records, {records} total", "{shared} registros em comum, {records} no total",
     "{shared} registros compartidos, {records} en total", "{shared} gemeinsame Datensätze, {records} gesamt",
     "{shared} enregistrements communs, {records} au total"),
    ("<strong>This conversation spans more than one transcript file.</strong> A resumed or bridged "
     "session is written to a new <code>.jsonl</code> that repeats the earlier records, so the most "
     "complete file is the one archived here.",
     "<strong>Esta conversa abrange mais de um arquivo de transcrição.</strong> Uma sessão retomada "
     "ou conectada por ponte é gravada em um novo <code>.jsonl</code> que repete os registros "
     "anteriores; por isso o arquivo mais completo é o arquivado aqui.",
     "<strong>Esta conversación abarca más de un archivo de transcripción.</strong> Una sesión "
     "reanudada o enlazada se escribe en un nuevo <code>.jsonl</code> que repite los registros "
     "anteriores, así que el archivo más completo es el archivado aquí.",
     "<strong>Dieses Gespräch erstreckt sich über mehr als eine Transkriptdatei.</strong> Eine "
     "fortgesetzte oder überbrückte Sitzung wird in eine neue <code>.jsonl</code> geschrieben, die "
     "die früheren Datensätze wiederholt; die vollständigste Datei ist daher die hier archivierte.",
     "<strong>Cette conversation s'étend sur plusieurs fichiers de transcription.</strong> Une "
     "session reprise ou pontée est écrite dans un nouveau <code>.jsonl</code> qui répète les "
     "enregistrements antérieurs ; le fichier le plus complet est donc celui archivé ici."),
    # -- usage table ----------------------------------------------------
    ("model", "modelo", "modelo", "Modell", "modèle"),
    ("requests", "requisições", "solicitudes", "Anfragen", "requêtes"),
    ("input", "entrada", "entrada", "Eingabe", "entrée"),
    ("output", "saída", "salida", "Ausgabe", "sortie"),
    ("cache read", "leitura de cache", "lectura de caché", "Cache-Lesen", "lecture cache"),
    ("cache write", "escrita de cache", "escritura de caché", "Cache-Schreiben", "écriture cache"),
    ("list cost", "custo de tabela", "costo de lista", "Listenpreis", "coût catalogue"),
    ("reported cost", "custo informado", "costo informado", "gemeldete Kosten", "coût déclaré"),
    ("no list price", "sem preço de tabela", "sin precio de lista", "kein Listenpreis", "pas de prix catalogue"),
    ("total", "total", "total", "gesamt", "total"),
    ("Usage is deduped per <code>requestId</code> (one API response is written as several records, "
     "each repeating that response's cumulative usage; summing them over-reports output by ~2.3&times; "
     "on a tool-heavy session). Cost is an estimate at public list rates &mdash; cache reads at "
     "0.1&times; input, 5-minute cache writes at 1.25&times;, 1-hour writes at 2&times; &mdash; not "
     "what a subscription bills.",
     "O uso é deduplicado por <code>requestId</code> (uma resposta da API é gravada como vários "
     "registros, cada um repetindo o uso acumulado daquela resposta; somá-los superestima a saída em "
     "~2,3&times; numa sessão com muitas ferramentas). O custo é uma estimativa às tarifas públicas de "
     "tabela &mdash; leituras de cache a 0,1&times; a entrada, escritas de cache de 5 minutos a "
     "1,25&times;, escritas de 1 hora a 2&times; &mdash; não o que uma assinatura cobra.",
     "El uso se deduplica por <code>requestId</code> (una respuesta de la API se escribe como varios "
     "registros, cada uno repitiendo el uso acumulado de esa respuesta; sumarlos sobreestima la salida "
     "en ~2,3&times; en una sesión con muchas herramientas). El costo es una estimación a tarifas "
     "públicas de lista &mdash; lecturas de caché a 0,1&times; la entrada, escrituras de caché de 5 "
     "minutos a 1,25&times;, escrituras de 1 hora a 2&times; &mdash; no lo que factura una suscripción.",
     "Die Nutzung ist je <code>requestId</code> dedupliziert (eine API-Antwort wird als mehrere "
     "Datensätze geschrieben, die jeweils die kumulierte Nutzung dieser Antwort wiederholen; ihre "
     "Summe überschätzt die Ausgabe in einer werkzeugreichen Sitzung um ~2,3&times;). Die Kosten "
     "sind eine Schätzung zu öffentlichen Listenpreisen &mdash; Cache-Lesen zu 0,1&times; Eingabe, "
     "5-Minuten-Cache-Schreiben zu 1,25&times;, 1-Stunden-Schreiben zu 2&times; &mdash; nicht das, "
     "was ein Abonnement abrechnet.",
     "L'utilisation est dédupliquée par <code>requestId</code> (une réponse de l'API est écrite en "
     "plusieurs enregistrements, chacun répétant l'utilisation cumulée de cette réponse ; les "
     "additionner surestime la sortie de ~2,3&times; sur une session riche en outils). Le coût est "
     "une estimation aux tarifs catalogue publics &mdash; lectures cache à 0,1&times; l'entrée, "
     "écritures cache de 5 minutes à 1,25&times;, écritures d'une heure à 2&times; &mdash; et non ce "
     "qu'un abonnement facture."),
    (" No list price on file for: {models}.", " Sem preço de tabela registrado para: {models}.",
     " Sin precio de lista registrado para: {models}.", " Kein Listenpreis hinterlegt für: {models}.",
     " Aucun prix catalogue enregistré pour : {models}."),
    ("<b>Reported cost</b> is Claude Code's own meter (<code>cost-state</code> records): ${usd} "
     "reported by Claude Code over {runs} run(s) of this session",
     "<b>Custo informado</b> é o medidor do próprio Claude Code (registros <code>cost-state</code>): "
     "${usd} informados pelo Claude Code em {runs} execução(ões) desta sessão",
     "<b>Costo informado</b> es el medidor propio de Claude Code (registros <code>cost-state</code>): "
     "${usd} informados por Claude Code en {runs} ejecución(es) de esta sesión",
     "<b>Gemeldete Kosten</b> sind Claude Codes eigener Zähler (<code>cost-state</code>-Datensätze): "
     "${usd} von Claude Code über {runs} Lauf/Läufe dieser Sitzung gemeldet",
     "<b>Coût déclaré</b> : le compteur propre de Claude Code (enregistrements <code>cost-state</code>) : "
     "${usd} déclarés par Claude Code sur {runs} exécution(s) de cette session"),
    ("; {added} lines added, {removed} removed by tools",
     "; {added} linhas adicionadas, {removed} removidas por ferramentas",
     "; {added} líneas añadidas, {removed} eliminadas por herramientas",
     "; {added} Zeilen hinzugefügt, {removed} durch Werkzeuge entfernt",
     " ; {added} lignes ajoutées, {removed} supprimées par des outils"),
    (". The meter restarts on every resume and only runs on Claude Code &ge; 2.1.9x write it",
     ". O medidor reinicia a cada retomada e só execuções no Claude Code &ge; 2.1.9x o gravam",
     ". El medidor se reinicia en cada reanudación y solo las ejecuciones en Claude Code &ge; 2.1.9x lo escriben",
     ". Der Zähler startet bei jeder Fortsetzung neu, und nur Läufe unter Claude Code &ge; 2.1.9x schreiben ihn",
     ". Le compteur redémarre à chaque reprise et seules les exécutions sous Claude Code &ge; 2.1.9x l'écrivent"),
    (" &mdash; <b>this session began before its first metered run ({first}); spend before that is not "
     "covered</b>, so the list-price estimate is the figure for the whole session.",
     " &mdash; <b>esta sessão começou antes da primeira execução medida ({first}); o gasto anterior não "
     "está coberto</b>, portanto a estimativa a preço de tabela é o valor para a sessão inteira.",
     " &mdash; <b>esta sesión comenzó antes de su primera ejecución medida ({first}); el gasto anterior "
     "no está cubierto</b>, así que la estimación a precio de lista es la cifra de toda la sesión.",
     " &mdash; <b>diese Sitzung begann vor ihrem ersten gemessenen Lauf ({first}); Ausgaben davor sind "
     "nicht erfasst</b>, daher ist die Listenpreis-Schätzung der Wert für die ganze Sitzung.",
     " &mdash; <b>cette session a commencé avant sa première exécution mesurée ({first}) ; la dépense "
     "antérieure n'est pas couverte</b>, l'estimation au prix catalogue est donc le chiffre de toute la session."),
    (", and here the meter covers the whole session.", ", e aqui o medidor cobre a sessão inteira.",
     ", y aquí el medidor cubre toda la sesión.", ", und hier erfasst der Zähler die ganze Sitzung.",
     ", et ici le compteur couvre toute la session."),
    (" Claude Code flagged a model it could not price; the reported total is a floor.",
     " O Claude Code sinalizou um modelo que não conseguiu precificar; o total informado é um piso.",
     " Claude Code señaló un modelo que no pudo tarificar; el total informado es un mínimo.",
     " Claude Code hat ein Modell gemeldet, das es nicht bepreisen konnte; die gemeldete Summe ist eine Untergrenze.",
     " Claude Code a signalé un modèle qu'il n'a pas pu tarifer ; le total déclaré est un plancher."),
    ("Totals include {n} subagent transcript(s).", "Os totais incluem {n} transcrição(ões) de subagente.",
     "Los totales incluyen {n} transcripción(es) de subagente.", "Die Summen enthalten {n} Subagenten-Transkript(e).",
     "Les totaux incluent {n} transcription(s) de sous-agent."),
    # -- fidelity report ------------------------------------------------
    ("records that produced one or more turns below", "registros que produziram um ou mais turnos abaixo",
     "registros que produjeron uno o más turnos abajo", "Datensätze, die unten einen oder mehrere Beiträge ergaben",
     "enregistrements ayant produit un ou plusieurs tours ci-dessous"),
    ("records folded into an earlier turn (tool results)", "registros incorporados a um turno anterior (resultados de ferramenta)",
     "registros incorporados a un turno anterior (resultados de herramienta)",
     "Datensätze, die in einen früheren Beitrag eingefaltet wurden (Werkzeugergebnisse)",
     "enregistrements repliés dans un tour antérieur (résultats d'outil)"),
    ("records counted only (no transcript content)", "registros apenas contados (sem conteúdo de transcrição)",
     "registros solo contados (sin contenido de transcripción)", "Datensätze nur gezählt (kein Transkriptinhalt)",
     "enregistrements seulement comptés (sans contenu de transcription)"),
    ("total records in the source", "total de registros na fonte", "total de registros en la fuente",
     "Datensätze in der Quelle insgesamt", "total des enregistrements dans la source"),
    ("<strong>These do not add up</strong> — a record class is escaping the parser. Treat the transcript "
     "below as incomplete.",
     "<strong>As contas não fecham</strong> — uma classe de registro está escapando do parser. Trate a "
     "transcrição abaixo como incompleta.",
     "<strong>Las cuentas no cuadran</strong> — una clase de registro se escapa del analizador. Trate la "
     "transcripción de abajo como incompleta.",
     "<strong>Das geht nicht auf</strong> — eine Datensatzklasse entgeht dem Parser. Betrachten Sie das "
     "Transkript unten als unvollständig.",
     "<strong>Le compte n'y est pas</strong> — une classe d'enregistrement échappe à l'analyseur. Considérez "
     "la transcription ci-dessous comme incomplète."),
    ("{n} thinking blocks are present in the source with <em>no text</em>. Claude Code requests thinking "
     "with <code>display: \"omitted\"</code>, so the reasoning itself never reaches the transcript — this "
     "archive can show that Claude thought at a given point, never what it thought. Nothing was lost in archiving.",
     "{n} blocos de raciocínio estão presentes na fonte <em>sem texto</em>. O Claude Code solicita o "
     "raciocínio com <code>display: \"omitted\"</code>, portanto o raciocínio em si nunca chega à "
     "transcrição — este arquivo pode mostrar que o Claude pensou num dado momento, nunca o que pensou. "
     "Nada se perdeu no arquivamento.",
     "{n} bloques de razonamiento están presentes en la fuente <em>sin texto</em>. Claude Code solicita el "
     "razonamiento con <code>display: \"omitted\"</code>, así que el razonamiento en sí nunca llega a la "
     "transcripción — este archivo puede mostrar que Claude pensó en un punto dado, nunca qué pensó. "
     "Nada se perdió al archivar.",
     "{n} Denkblöcke sind in der Quelle <em>ohne Text</em> vorhanden. Claude Code fordert das Denken mit "
     "<code>display: \"omitted\"</code> an, daher erreicht die Überlegung selbst nie das Transkript — "
     "dieses Archiv kann zeigen, dass Claude an einer Stelle gedacht hat, nie was. Beim Archivieren ging "
     "nichts verloren.",
     "{n} blocs de réflexion sont présents dans la source <em>sans texte</em>. Claude Code demande la "
     "réflexion avec <code>display: \"omitted\"</code>, le raisonnement lui-même n'atteint donc jamais la "
     "transcription — cette archive peut montrer que Claude a réfléchi à un moment donné, jamais ce qu'il "
     "a pensé. Rien n'a été perdu à l'archivage."),
    ("{n} tool call(s) have no result in the source (still running, or interrupted, when this file was written).",
     "{n} chamada(s) de ferramenta não têm resultado na fonte (ainda em execução, ou interrompidas, quando "
     "este arquivo foi gravado).",
     "{n} llamada(s) a herramientas no tienen resultado en la fuente (aún en ejecución, o interrumpidas, "
     "cuando se escribió este archivo).",
     "{n} Werkzeugaufruf(e) haben kein Ergebnis in der Quelle (liefen noch oder wurden unterbrochen, als "
     "diese Datei geschrieben wurde).",
     "{n} appel(s) d'outil n'ont pas de résultat dans la source (encore en cours, ou interrompus, quand ce "
     "fichier a été écrit)."),
    ("{humans} human turns rendered vs {typed} distinct prompts in the session's own <code>last-prompt</code> "
     "index &mdash; worth a look.",
     "{humans} turnos humanos renderizados contra {typed} prompts distintos no índice <code>last-prompt</code> "
     "da própria sessão &mdash; vale conferir.",
     "{humans} turnos humanos renderizados frente a {typed} prompts distintos en el índice "
     "<code>last-prompt</code> de la propia sesión &mdash; merece una mirada.",
     "{humans} menschliche Beiträge dargestellt gegenüber {typed} verschiedenen Prompts im "
     "<code>last-prompt</code>-Index der Sitzung &mdash; einen Blick wert.",
     "{humans} tours humains rendus contre {typed} prompts distincts dans l'index <code>last-prompt</code> "
     "de la session &mdash; mérite un coup d'œil."),
    ("No record in the source carries a timestamp, so when the conversation happened cannot be established "
     "from this file.",
     "Nenhum registro na fonte tem carimbo de tempo, portanto não é possível estabelecer por este arquivo "
     "quando a conversa aconteceu.",
     "Ningún registro de la fuente lleva marca de tiempo, así que no se puede establecer a partir de este "
     "archivo cuándo ocurrió la conversación.",
     "Kein Datensatz in der Quelle trägt einen Zeitstempel, daher lässt sich aus dieser Datei nicht "
     "feststellen, wann das Gespräch stattfand.",
     "Aucun enregistrement de la source ne porte d'horodatage ; ce fichier ne permet donc pas d'établir "
     "quand la conversation a eu lieu."),
    ("This archive was written while the session was still active, so records created after {when} are not "
     "in it. Re-run to refresh.",
     "Este arquivo foi gravado enquanto a sessão ainda estava ativa, portanto registros criados após {when} "
     "não estão nele. Execute novamente para atualizar.",
     "Este archivo se escribió mientras la sesión seguía activa, así que los registros creados después de "
     "{when} no están en él. Vuelva a ejecutar para actualizar.",
     "Dieses Archiv wurde geschrieben, während die Sitzung noch aktiv war; Datensätze nach {when} sind "
     "nicht enthalten. Zum Aktualisieren erneut ausführen.",
     "Cette archive a été écrite alors que la session était encore active ; les enregistrements créés après "
     "{when} n'y figurent pas. Relancez pour actualiser."),
    ("Snapshot taken {when}; the source's last record is {last}. Anything written to the session after that "
     "is not in this file. Re-run to refresh.",
     "Instantâneo tirado em {when}; o último registro da fonte é de {last}. O que foi gravado na sessão "
     "depois disso não está neste arquivo. Execute novamente para atualizar.",
     "Instantánea tomada el {when}; el último registro de la fuente es de {last}. Lo escrito en la sesión "
     "después de eso no está en este archivo. Vuelva a ejecutar para actualizar.",
     "Momentaufnahme vom {when}; der letzte Datensatz der Quelle stammt von {last}. Was danach in die "
     "Sitzung geschrieben wurde, fehlt in dieser Datei. Zum Aktualisieren erneut ausführen.",
     "Instantané pris le {when} ; le dernier enregistrement de la source date de {last}. Ce qui a été écrit "
     "dans la session après cela n'est pas dans ce fichier. Relancez pour actualiser."),
    ("Every record in the source, and what happened to it. Nothing is dropped silently: a record is either "
     "rendered below, folded into an earlier turn, or counted here as deliberately not rendered.",
     "Cada registro da fonte, e o que aconteceu com ele. Nada é descartado em silêncio: um registro ou é "
     "renderizado abaixo, ou incorporado a um turno anterior, ou contado aqui como deliberadamente não renderizado.",
     "Cada registro de la fuente, y qué pasó con él. Nada se descarta en silencio: un registro o se "
     "renderiza abajo, o se incorpora a un turno anterior, o se cuenta aquí como deliberadamente no renderizado.",
     "Jeder Datensatz der Quelle und was mit ihm geschah. Nichts fällt stillschweigend weg: ein Datensatz "
     "wird entweder unten dargestellt, in einen früheren Beitrag eingefaltet oder hier als bewusst nicht "
     "dargestellt gezählt.",
     "Chaque enregistrement de la source, et ce qu'il est devenu. Rien n'est écarté en silence : un "
     "enregistrement est soit rendu ci-dessous, soit replié dans un tour antérieur, soit compté ici comme "
     "délibérément non rendu."),
    ("Record disposition", "Destino dos registros", "Destino de los registros", "Verbleib der Datensätze",
     "Sort des enregistrements"),
    ("Source records by type", "Registros da fonte por tipo", "Registros de la fuente por tipo",
     "Quelldatensätze nach Typ", "Enregistrements source par type"),
    ("Content blocks", "Blocos de conteúdo", "Bloques de contenido", "Inhaltsblöcke", "Blocs de contenu"),
    ("Rendered ({n} turns)", "Renderizados ({n} turnos)", "Renderizados ({n} turnos)",
     "Dargestellt ({n} Beiträge)", "Rendus ({n} tours)"),
    ("Counted, not rendered ({n})", "Contados, não renderizados ({n})", "Contados, no renderizados ({n})",
     "Gezählt, nicht dargestellt ({n})", "Comptés, non rendus ({n})"),
    ("Human-vs-injected evidence", "Evidência humano-vs-injetado", "Evidencia humano-vs-inyectado",
     "Belege: Mensch vs. eingefügt", "Preuves humain-vs-injecté"),
    ("Which signal classified each string-content user record. <code>promptSource</code> and "
     "<code>origin.kind</code> are authoritative; the rest are fallbacks for older records.",
     "Qual sinal classificou cada registro de usuário com conteúdo textual. <code>promptSource</code> e "
     "<code>origin.kind</code> são autoritativos; os demais são alternativas para registros mais antigos.",
     "Qué señal clasificó cada registro de usuario con contenido de texto. <code>promptSource</code> y "
     "<code>origin.kind</code> son autoritativos; el resto son alternativas para registros más antiguos.",
     "Welches Signal jeden Benutzerdatensatz mit Textinhalt eingeordnet hat. <code>promptSource</code> "
     "und <code>origin.kind</code> sind maßgeblich; der Rest sind Rückfalloptionen für ältere Datensätze.",
     "Quel signal a classé chaque enregistrement utilisateur à contenu textuel. <code>promptSource</code> "
     "et <code>origin.kind</code> font foi ; le reste sert de repli pour les enregistrements plus anciens."),
    ("Caveats", "Ressalvas", "Advertencias", "Vorbehalte", "Réserves"),
    ("Source: <code>{path}</code> &middot; archiver v{version}", "Fonte: <code>{path}</code> &middot; archiver v{version}",
     "Fuente: <code>{path}</code> &middot; archiver v{version}", "Quelle: <code>{path}</code> &middot; archiver v{version}",
     "Source : <code>{path}</code> &middot; archiver v{version}"),
    ("Rendered in full in the Subagent transcripts section below.",
     "Renderizadas na íntegra na seção Transcrições de subagentes abaixo.",
     "Renderizadas completas en la sección Transcripciones de subagentes de abajo.",
     "Vollständig im Abschnitt Subagenten-Transkripte unten dargestellt.",
     "Rendues intégralement dans la section Transcriptions des sous-agents ci-dessous."),
    ("<strong>Not rendered</strong> (--subagents off) — listed here so the omission is on the record. Their "
     "token usage is still counted above.",
     "<strong>Não renderizadas</strong> (--subagents off) — listadas aqui para que a omissão fique "
     "registrada. Seu uso de tokens continua contado acima.",
     "<strong>No renderizadas</strong> (--subagents off) — listadas aquí para que la omisión quede "
     "registrada. Su uso de tokens sigue contado arriba.",
     "<strong>Nicht dargestellt</strong> (--subagents off) — hier aufgeführt, damit die Auslassung "
     "aktenkundig ist. Ihre Token-Nutzung ist oben weiterhin gezählt.",
     "<strong>Non rendues</strong> (--subagents off) — listées ici pour que l'omission soit consignée. "
     "Leur consommation de jetons reste comptée ci-dessus."),
    ("Subagent transcripts ({n})", "Transcrições de subagentes ({n})", "Transcripciones de subagentes ({n})",
     "Subagenten-Transkripte ({n})", "Transcriptions des sous-agents ({n})"),
    ("file", "arquivo", "archivo", "Datei", "fichier"),
    ("records", "registros", "registros", "Datensätze", "enregistrements"),
    ("turns", "turnos", "turnos", "Beiträge", "tours"),
    # -- summaries the CLI writes when none is given ---------------------
    ("No summary provided. Write one covering Activities, Key findings, What this allows going forward, and "
     "Generated artifacts, save it as an HTML fragment, and re-run with <code>--summary-file</code>.",
     "Nenhum resumo fornecido. Escreva um cobrindo Atividades, Principais achados, O que isto permite daqui "
     "em diante e Artefatos gerados, salve-o como fragmento HTML e execute novamente com "
     "<code>--summary-file</code>.",
     "No se proporcionó resumen. Escriba uno que cubra Actividades, Hallazgos clave, Qué permite esto en "
     "adelante y Artefactos generados, guárdelo como fragmento HTML y vuelva a ejecutar con "
     "<code>--summary-file</code>.",
     "Keine Zusammenfassung angegeben. Schreiben Sie eine zu Tätigkeiten, Kernergebnissen, was dies künftig "
     "ermöglicht und erzeugten Artefakten, speichern Sie sie als HTML-Fragment und führen Sie mit "
     "<code>--summary-file</code> erneut aus.",
     "Aucun résumé fourni. Rédigez-en un couvrant Activités, Résultats clés, Ce que cela permet ensuite et "
     "Artefacts produits, enregistrez-le comme fragment HTML et relancez avec <code>--summary-file</code>."),
    ("Imported from a claude.ai data export. Pass <code>--summary-file</code> for a hand-written summary.",
     "Importado de uma exportação de dados do claude.ai. Passe <code>--summary-file</code> para um resumo escrito à mão.",
     "Importado de una exportación de datos de claude.ai. Pase <code>--summary-file</code> para un resumen escrito a mano.",
     "Importiert aus einem claude.ai-Datenexport. Mit <code>--summary-file</code> eine handgeschriebene Zusammenfassung angeben.",
     "Importé d'un export de données claude.ai. Passez <code>--summary-file</code> pour un résumé rédigé à la main."),
    # -- text / Markdown / LaTeX ----------------------------------------
    ("Every turn in the HTML archive is present here, with tool input and output in full. Images embedded in "
     "tool results cannot travel in this format and are marked as omitted; ANSI colour codes are stripped. "
     "Human turns and tool output are reproduced verbatim and are never re-wrapped.",
     "Todo turno do arquivo HTML está presente aqui, com a entrada e a saída das ferramentas na íntegra. "
     "Imagens embutidas em resultados de ferramenta não viajam neste formato e são marcadas como omitidas; "
     "códigos de cor ANSI são removidos. Turnos humanos e saída de ferramentas são reproduzidos literalmente "
     "e nunca reformatados.",
     "Cada turno del archivo HTML está presente aquí, con la entrada y la salida de las herramientas completas. "
     "Las imágenes incrustadas en resultados de herramienta no viajan en este formato y se marcan como omitidas; "
     "los códigos de color ANSI se eliminan. Los turnos humanos y la salida de herramientas se reproducen "
     "textualmente y nunca se reajustan.",
     "Jeder Beitrag des HTML-Archivs ist hier vorhanden, mit vollständiger Werkzeug-Ein- und -Ausgabe. In "
     "Werkzeugergebnisse eingebettete Bilder können in diesem Format nicht mitreisen und sind als ausgelassen "
     "markiert; ANSI-Farbcodes sind entfernt. Menschliche Beiträge und Werkzeugausgabe sind wörtlich "
     "wiedergegeben und werden nie neu umbrochen.",
     "Chaque tour de l'archive HTML est présent ici, avec l'entrée et la sortie des outils en entier. Les "
     "images incluses dans les résultats d'outil ne peuvent pas voyager dans ce format et sont marquées "
     "comme omises ; les codes couleur ANSI sont retirés. Les tours humains et la sortie des outils sont "
     "reproduits mot pour mot et jamais réagencés."),
    ("Every turn in the HTML archive is present here, but tool calls are reduced to a single labelled line: "
     "their input and output are omitted, because a page-based format renders them as unreadable walls of "
     "escaped JSON. The HTML archive holds all of it. Human turns and Claude's prose are complete and "
     "reproduced verbatim.",
     "Todo turno do arquivo HTML está presente aqui, mas as chamadas de ferramenta são reduzidas a uma única "
     "linha rotulada: sua entrada e saída são omitidas, porque um formato paginado as renderiza como muros "
     "ilegíveis de JSON escapado. O arquivo HTML contém tudo. Turnos humanos e a prosa do Claude estão "
     "completos e reproduzidos literalmente.",
     "Cada turno del archivo HTML está presente aquí, pero las llamadas a herramientas se reducen a una sola "
     "línea etiquetada: su entrada y salida se omiten, porque un formato paginado las renderiza como muros "
     "ilegibles de JSON escapado. El archivo HTML lo contiene todo. Los turnos humanos y la prosa de Claude "
     "están completos y reproducidos textualmente.",
     "Jeder Beitrag des HTML-Archivs ist hier vorhanden, doch Werkzeugaufrufe sind auf eine einzige "
     "beschriftete Zeile reduziert: Ein- und Ausgabe fehlen, weil ein seitenbasiertes Format sie als "
     "unlesbare Wände aus escaptem JSON setzt. Das HTML-Archiv enthält alles. Menschliche Beiträge und "
     "Claudes Prosa sind vollständig und wörtlich wiedergegeben.",
     "Chaque tour de l'archive HTML est présent ici, mais les appels d'outils sont réduits à une seule ligne "
     "étiquetée : leur entrée et leur sortie sont omises, car un format paginé les rend comme des murs "
     "illisibles de JSON échappé. L'archive HTML contient tout. Les tours humains et la prose de Claude sont "
     "complets et reproduits mot pour mot."),
    (" {n} tool calls are shown by name only.", " {n} chamadas de ferramenta aparecem apenas pelo nome.",
     " {n} llamadas a herramientas se muestran solo por su nombre.", " {n} Werkzeugaufrufe sind nur mit Namen aufgeführt.",
     " {n} appels d'outils ne sont indiqués que par leur nom."),
    ("HUMAN", "HUMANO", "HUMANO", "MENSCH", "HUMAIN"),
    ("THINKING", "RACIOCÍNIO", "RAZONAMIENTO", "DENKEN", "RÉFLEXION"),
    ("TOOL", "FERRAMENTA", "HERRAMIENTA", "WERKZEUG", "OUTIL"),
    ("[ERROR]", "[ERRO]", "[ERROR]", "[FEHLER]", "[ERREUR]"),
    ("HUMAN - PASTED IMAGE", "HUMANO - IMAGEM COLADA", "HUMANO - IMAGEN PEGADA",
     "MENSCH - EINGEFÜGTES BILD", "HUMAIN - IMAGE COLLÉE"),
    ("(no text: display=omitted)", "(sem texto: display=omitted)", "(sin texto: display=omitted)",
     "(kein Text: display=omitted)", "(pas de texte : display=omitted)"),
    ("(image omitted in this format; the HTML archive holds it)",
     "(imagem omitida neste formato; o arquivo HTML a contém)",
     "(imagen omitida en este formato; el archivo HTML la contiene)",
     "(Bild in diesem Format ausgelassen; das HTML-Archiv enthält es)",
     "(image omise dans ce format ; l'archive HTML la contient)"),
    ("(image omitted in this format)", "(imagem omitida neste formato)", "(imagen omitida en este formato)",
     "(Bild in diesem Format ausgelassen)", "(image omise dans ce format)"),
    ("[image omitted]", "[imagem omitida]", "[imagen omitida]", "[Bild ausgelassen]", "[image omise]"),
    ("(no result in the source)", "(sem resultado na fonte)", "(sin resultado en la fuente)",
     "(kein Ergebnis in der Quelle)", "(aucun résultat dans la source)"),
    ("input:", "entrada:", "entrada:", "Eingabe:", "entrée :"),
    ("output:", "saída:", "salida:", "Ausgabe:", "sortie :"),
    ("session", "sessão", "sesión", "Sitzung", "session"),
    ("SESSION SUMMARY", "RESUMO DA SESSÃO", "RESUMEN DE LA SESIÓN", "SITZUNGSZUSAMMENFASSUNG", "RÉSUMÉ DE LA SESSION"),
    ("FIDELITY REPORT", "RELATÓRIO DE FIDELIDADE", "INFORME DE FIDELIDAD", "BERICHT ZUR WIEDERGABETREUE",
     "RAPPORT DE FIDÉLITÉ"),
    ("subagent transcript agent-{aid}", "transcrição de subagente agent-{aid}", "transcripción de subagente agent-{aid}",
     "Subagenten-Transkript agent-{aid}", "transcription de sous-agent agent-{aid}"),
    (" (not rendered)", " (não renderizada)", " (no renderizada)", " (nicht dargestellt)", " (non rendue)"),
    ("SUBAGENT TRANSCRIPT A{k}: agent-{aid}  ({records} records; turns tagged A{k}.P / A{k}.R)",
     "TRANSCRIÇÃO DE SUBAGENTE A{k}: agent-{aid}  ({records} registros; turnos marcados A{k}.P / A{k}.R)",
     "TRANSCRIPCIÓN DE SUBAGENTE A{k}: agent-{aid}  ({records} registros; turnos etiquetados A{k}.P / A{k}.R)",
     "SUBAGENTEN-TRANSKRIPT A{k}: agent-{aid}  ({records} Datensätze; Beiträge markiert A{k}.P / A{k}.R)",
     "TRANSCRIPTION DE SOUS-AGENT A{k} : agent-{aid}  ({records} enregistrements ; tours étiquetés A{k}.P / A{k}.R)"),
    ("Session: `{sid}`", "Sessão: `{sid}`", "Sesión: `{sid}`", "Sitzung: `{sid}`", "Session : `{sid}`"),
    ("Human turns and tool I/O are fenced verbatim below; Claude's own prose is markdown and is left live, "
     "so its headings appear in this document's outline.",
     "Turnos humanos e E/S de ferramentas estão cercados literalmente abaixo; a prosa do próprio Claude é "
     "markdown e fica ativa, de modo que seus títulos aparecem na estrutura deste documento.",
     "Los turnos humanos y la E/S de herramientas van cercados textualmente abajo; la prosa propia de "
     "Claude es markdown y se deja activa, así que sus encabezados aparecen en el esquema de este documento.",
     "Menschliche Beiträge und Werkzeug-E/A sind unten wörtlich eingezäunt; Claudes eigene Prosa ist "
     "Markdown und bleibt aktiv, sodass ihre Überschriften in der Gliederung dieses Dokuments erscheinen.",
     "Les tours humains et les E/S des outils sont clôturés mot pour mot ci-dessous ; la prose de Claude "
     "est du markdown laissé actif, ses titres apparaissent donc dans le plan de ce document."),
    ("Human — pasted image", "Humano — imagem colada", "Humano — imagen pegada", "Mensch — eingefügtes Bild",
     "Humain — image collée"),
    ("Tool", "Ferramenta", "Herramienta", "Werkzeug", "Outil"),
    ("Subagent transcript A{k}: agent-{aid}", "Transcrição de subagente A{k}: agent-{aid}",
     "Transcripción de subagente A{k}: agent-{aid}", "Subagenten-Transkript A{k}: agent-{aid}",
     "Transcription de sous-agent A{k} : agent-{aid}"),
    ("({records} records; a background agent's own conversation)",
     "({records} registros; a conversa própria de um agente em segundo plano)",
     "({records} registros; la conversación propia de un agente en segundo plano)",
     "({records} Datensätze; das eigene Gespräch eines Hintergrundagenten)",
     "({records} enregistrements ; la conversation propre d'un agent d'arrière-plan)"),
    ("Transcript", "Transcrição", "Transcripción", "Transkript", "Transcription"),
    (" (part {k}/{n})", " (parte {k}/{n})", " (parte {k}/{n})", " (Teil {k}/{n})", " (partie {k}/{n})"),
    ("Subagent A{k}: agent-{aid}", "Subagente A{k}: agent-{aid}", "Subagente A{k}: agent-{aid}",
     "Subagent A{k}: agent-{aid}", "Sous-agent A{k} : agent-{aid}"),
    ("({records} records; a background agent's own conversation, archived from its transcript file beside the session)",
     "({records} registros; a conversa própria de um agente em segundo plano, arquivada a partir de seu arquivo de transcrição ao lado da sessão)",
     "({records} registros; la conversación propia de un agente en segundo plano, archivada desde su archivo de transcripción junto a la sesión)",
     "({records} Datensätze; das eigene Gespräch eines Hintergrundagenten, archiviert aus seiner Transkriptdatei neben der Sitzung)",
     "({records} enregistrements ; la conversation propre d'un agent d'arrière-plan, archivée depuis son fichier de transcription à côté de la session)"),
    ("Subagent transcripts (not rendered)", "Transcrições de subagentes (não renderizadas)",
     "Transcripciones de subagentes (no renderizadas)", "Subagenten-Transkripte (nicht dargestellt)",
     "Transcriptions des sous-agents (non rendues)"),
    ("{n} subagent transcript file(s) exist for this session but were not rendered (--subagents off): {files}. "
     "Their token usage is included in the usage table.",
     "{n} arquivo(s) de transcrição de subagente existem para esta sessão mas não foram renderizados "
     "(--subagents off): {files}. Seu uso de tokens está incluído na tabela de uso.",
     "{n} archivo(s) de transcripción de subagente existen para esta sesión pero no se renderizaron "
     "(--subagents off): {files}. Su uso de tokens está incluido en la tabla de uso.",
     "{n} Subagenten-Transkriptdatei(en) existieren für diese Sitzung, wurden aber nicht dargestellt "
     "(--subagents off): {files}. Ihre Token-Nutzung ist in der Nutzungstabelle enthalten.",
     "{n} fichier(s) de transcription de sous-agent existent pour cette session mais n'ont pas été rendus "
     "(--subagents off) : {files}. Leur consommation de jetons est incluse dans le tableau d'utilisation."),
    ("{n} characters (emoji and other glyphs no installed TeX font can set)",
     "{n} caracteres (emoji e outros glifos que nenhuma fonte TeX instalada consegue compor)",
     "{n} caracteres (emoji y otros glifos que ninguna fuente TeX instalada puede componer)",
     "{n} Zeichen (Emoji und andere Glyphen, die keine installierte TeX-Schrift setzen kann)",
     "{n} caractères (émoji et autres glyphes qu'aucune police TeX installée ne peut composer)"),
    ("{n} control bytes (NUL, backspace and similar, which TeX refuses to read)",
     "{n} bytes de controle (NUL, backspace e similares, que o TeX se recusa a ler)",
     "{n} bytes de control (NUL, retroceso y similares, que TeX se niega a leer)",
     "{n} Steuerbytes (NUL, Backspace und Ähnliches, die TeX nicht liest)",
     "{n} octets de contrôle (NUL, retour arrière et similaires, que TeX refuse de lire)"),
    ("This rendering removed {what}.", "Esta renderização removeu {what}.", "Esta renderización eliminó {what}.",
     "Diese Darstellung hat {what} entfernt.", "Ce rendu a retiré {what}."),
    (" and ", " e ", " y ", " und ", " et "),
    ("This fragment is engine-neutral, so it compiles under pdflatex as well as XeLaTeX: {n} characters were "
     "transliterated (Greek to math or its name, arrows and box drawing to ASCII).",
     "Este fragmento é neutro quanto ao motor, portanto compila tanto com pdflatex quanto com XeLaTeX: {n} "
     "caracteres foram transliterados (grego para matemática ou seu nome, setas e caracteres de caixa para ASCII).",
     "Este fragmento es neutral respecto al motor, así que compila tanto con pdflatex como con XeLaTeX: {n} "
     "caracteres fueron transliterados (griego a matemáticas o su nombre, flechas y dibujo de cajas a ASCII).",
     "Dieses Fragment ist engine-neutral und kompiliert daher mit pdflatex wie mit XeLaTeX: {n} Zeichen "
     "wurden transliteriert (Griechisch zu Mathematik oder seinem Namen, Pfeile und Rahmenzeichen zu ASCII).",
     "Ce fragment est neutre quant au moteur et compile donc sous pdflatex comme sous XeLaTeX : {n} "
     "caractères ont été translittérés (grec en mathématiques ou en son nom, flèches et tracés de boîtes en ASCII)."),
    ("{n} very long lines were hard-wrapped at {w} characters so TeX could typeset them.",
     "{n} linhas muito longas foram quebradas forçadamente em {w} caracteres para que o TeX pudesse compô-las.",
     "{n} líneas muy largas se cortaron forzosamente a {w} caracteres para que TeX pudiera componerlas.",
     "{n} sehr lange Zeilen wurden bei {w} Zeichen hart umbrochen, damit TeX sie setzen konnte.",
     "{n} lignes très longues ont été coupées de force à {w} caractères pour que TeX puisse les composer."),
    ("{n} very large turn(s) were split into consecutive boxes of at most {m} lines each, titled (part k/n), "
     "so TeX could hold them in memory; nothing was omitted.",
     "{n} turno(s) muito grande(s) foram divididos em caixas consecutivas de no máximo {m} linhas cada, "
     "intituladas (parte k/n), para que o TeX pudesse mantê-los em memória; nada foi omitido.",
     "{n} turno(s) muy grande(s) se dividieron en cajas consecutivas de como máximo {m} líneas cada una, "
     "tituladas (parte k/n), para que TeX pudiera mantenerlos en memoria; nada se omitió.",
     "{n} sehr große Beiträge wurden in aufeinanderfolgende Kästen von höchstens {m} Zeilen aufgeteilt, "
     "betitelt (Teil k/n), damit TeX sie im Speicher halten konnte; nichts wurde ausgelassen.",
     "{n} tour(s) très volumineux ont été découpés en boîtes consécutives d'au plus {m} lignes chacune, "
     "intitulées (partie k/n), pour que TeX puisse les garder en mémoire ; rien n'a été omis."),
    ("The HTML archive holds all of it unaltered.", "O arquivo HTML contém tudo inalterado.",
     "El archivo HTML lo contiene todo sin alterar.", "Das HTML-Archiv enthält alles unverändert.",
     "L'archive HTML contient tout, inchangé."),
    # -- index ----------------------------------------------------------
    ("Claude Code session archive", "Arquivo de sessões do Claude Code", "Archivo de sesiones de Claude Code",
     "Claude-Code-Sitzungsarchiv", "Archive des sessions Claude Code"),
    ("Generated {when}. &ldquo;Covered&rdquo; means the session was resumed into another transcript that "
     "<em>is</em> archived, so its records live in that file.",
     "Gerado em {when}. &ldquo;Coberta&rdquo; significa que a sessão foi retomada em outra transcrição que "
     "<em>está</em> arquivada, portanto seus registros vivem naquele arquivo.",
     "Generado el {when}. &ldquo;Cubierta&rdquo; significa que la sesión se reanudó en otra transcripción "
     "que <em>sí</em> está archivada, así que sus registros viven en ese archivo.",
     "Erzeugt am {when}. &ldquo;Abgedeckt&rdquo; heißt, die Sitzung wurde in ein anderes Transkript "
     "fortgesetzt, das archiviert <em>ist</em>; ihre Datensätze liegen in jener Datei.",
     "Généré le {when}. &ldquo;Couverte&rdquo; signifie que la session a été reprise dans une autre "
     "transcription qui, elle, <em>est</em> archivée ; ses enregistrements vivent dans ce fichier."),
    ("Search every prompt across all archives ({n} prompts)", "Buscar em todos os prompts de todos os arquivos ({n} prompts)",
     "Buscar en todos los prompts de todos los archivos ({n} prompts)", "Alle Prompts aller Archive durchsuchen ({n} Prompts)",
     "Rechercher dans tous les prompts de toutes les archives ({n} prompts)"),
    ("Search prompts across all archives", "Buscar prompts em todos os arquivos", "Buscar prompts en todos los archivos",
     "Prompts in allen Archiven suchen", "Rechercher des prompts dans toutes les archives"),
    ("status", "status", "estado", "Status", "état"),
    ("activity", "atividade", "actividad", "Aktivität", "activité"),
    ("id", "id", "id", "ID", "id"),
    ("started", "início", "inicio", "Beginn", "début"),
    ("last record", "último registro", "último registro", "letzter Datensatz", "dernier enregistrement"),
    ("legacy v1", "legado v1", "heredado v1", "Altformat v1", "ancien v1"),
    ("stale", "desatualizada", "desactualizada", "veraltet", "périmée"),
    ("archived", "arquivada", "archivada", "archiviert", "archivée"),
    ("covered", "coberta", "cubierta", "abgedeckt", "couverte"),
    ("not archived", "não arquivada", "no archivada", "nicht archiviert", "non archivée"),
    ("written by the v1 archiver &mdash; no embedded metadata, and its counts and token figures are known to be "
     "wrong. Re-run to replace it.",
     "gravada pelo archiver v1 &mdash; sem metadados embutidos, e suas contagens e números de tokens são "
     "sabidamente errados. Execute novamente para substituí-la.",
     "escrita por el archiver v1 &mdash; sin metadatos incrustados, y sus recuentos y cifras de tokens son "
     "erróneos. Vuelva a ejecutar para reemplazarla.",
     "vom Archiver v1 geschrieben &mdash; ohne eingebettete Metadaten, und seine Zählungen und Token-Zahlen "
     "sind bekanntermaßen falsch. Zum Ersetzen erneut ausführen.",
     "écrite par l'archiver v1 &mdash; sans métadonnées intégrées, et ses décomptes et chiffres de jetons "
     "sont connus pour être faux. Relancez pour la remplacer."),
    ("${usd} reported", "${usd} informados", "${usd} informados", "${usd} gemeldet", "${usd} déclarés"),
    ("{records} records &middot; {tools} tool calls &middot; {cost} &middot; {mb} MB &middot; archiver v{version}",
     "{records} registros &middot; {tools} chamadas de ferramenta &middot; {cost} &middot; {mb} MB &middot; archiver v{version}",
     "{records} registros &middot; {tools} llamadas a herramientas &middot; {cost} &middot; {mb} MB &middot; archiver v{version}",
     "{records} Datensätze &middot; {tools} Werkzeugaufrufe &middot; {cost} &middot; {mb} MB &middot; archiver v{version}",
     "{records} enregistrements &middot; {tools} appels d'outils &middot; {cost} &middot; {mb} Mo &middot; archiver v{version}"),
    ("continued into <code>{sid}</code>, archived there", "continuada em <code>{sid}</code>, arquivada lá",
     "continuada en <code>{sid}</code>, archivada allí", "fortgesetzt in <code>{sid}</code>, dort archiviert",
     "poursuivie dans <code>{sid}</code>, archivée là"),
    (" &middot; {n} record(s) not carried over (bookkeeping only)", " &middot; {n} registro(s) não transportado(s) (apenas contabilidade)",
     " &middot; {n} registro(s) no trasladado(s) (solo contabilidad)", " &middot; {n} Datensatz/-sätze nicht übernommen (nur Buchführung)",
     " &middot; {n} enregistrement(s) non reporté(s) (comptabilité seulement)"),
    ("{n} records on disk", "{n} registros em disco", "{n} registros en disco", "{n} Datensätze auf der Festplatte",
     "{n} enregistrements sur disque"),
    (" &middot; {n} subagent transcript(s)", " &middot; {n} transcrição(ões) de subagente", " &middot; {n} transcripción(es) de subagente",
     " &middot; {n} Subagenten-Transkript(e)", " &middot; {n} transcription(s) de sous-agent"),
    (" &middot; source: {source}", " &middot; fonte: {source}", " &middot; fuente: {source}", " &middot; Quelle: {source}",
     " &middot; source : {source}"),
    ("source transcript not on disk", "transcrição de origem não está em disco", "transcripción de origen no está en disco",
     "Quelltranskript nicht auf der Festplatte", "transcription source absente du disque"),
    ("{records} records &middot; {mb} MB &middot; archiver v{version} &middot; source: {source}",
     "{records} registros &middot; {mb} MB &middot; archiver v{version} &middot; fonte: {source}",
     "{records} registros &middot; {mb} MB &middot; archiver v{version} &middot; fuente: {source}",
     "{records} Datensätze &middot; {mb} MB &middot; archiver v{version} &middot; Quelle: {source}",
     "{records} enregistrements &middot; {mb} Mo &middot; archiver v{version} &middot; source : {source}"),
    ("{n} sessions on disk &middot; {archived} archived &middot; {missing} not archived directly",
     "{n} sessões em disco &middot; {archived} arquivadas &middot; {missing} não arquivadas diretamente",
     "{n} sesiones en disco &middot; {archived} archivadas &middot; {missing} no archivadas directamente",
     "{n} Sitzungen auf der Festplatte &middot; {archived} archiviert &middot; {missing} nicht direkt archiviert",
     "{n} sessions sur disque &middot; {archived} archivées &middot; {missing} non archivées directement"),
    (" &middot; {n} archived from imports or deleted sources", " &middot; {n} arquivadas de importações ou fontes excluídas",
     " &middot; {n} archivadas desde importaciones o fuentes eliminadas", " &middot; {n} aus Importen oder gelöschten Quellen archiviert",
     " &middot; {n} archivées depuis des imports ou des sources supprimées"),
    ("now", "agora", "ahora", "jetzt", "maintenant"),
    ("{total} matching prompt(s) in {sessions} session(s)", "{total} prompt(s) correspondente(s) em {sessions} sessão(ões)",
     "{total} prompt(s) coincidente(s) en {sessions} sesión(es)", "{total} passende(r) Prompt(s) in {sessions} Sitzung(en)",
     "{total} prompt(s) correspondant(s) dans {sessions} session(s)"),
    (" (first 200 shown)", " (primeiros 200 exibidos)", " (se muestran los primeros 200)", " (erste 200 angezeigt)",
     " (200 premiers affichés)"),
]

L10N = {lang: {row[0]: row[i] for row in _L10N_ROWS}
        for i, lang in enumerate(LANGS) if lang != "en"}

# Where archives go unless --archive-dir says otherwise. CLAUDE_ARCHIVE_DIR in
# the environment overrides the built-in default so a personal location never
# has to be hard-coded.
DEFAULT_ARCHIVE_DIR = Path(os.environ.get("CLAUDE_ARCHIVE_DIR")
                           or (Path.home() / "claude-archives"))


# ---------------------------------------------------------------------------
# Console output and the per-run audit log.
#   say()    -- normal progress, silenced by --quiet
#   detail() -- only with --verbose
#   note()   -- warnings, always shown (stderr)
# Everything said is also kept for the audit log written at the end of a run.
# ---------------------------------------------------------------------------

class _Console:
    def __init__(self):
        self.verbose = False
        self.quiet = False
        self.lines: list[str] = []

    def _keep(self, level: str, msg: str) -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.lines.append(f"{stamp} {level:<6} {msg}")

    def say(self, msg: str = "") -> None:
        self._keep("info", msg)
        if not self.quiet:
            print(msg)

    def detail(self, msg: str) -> None:
        self._keep("detail", msg)
        if self.verbose and not self.quiet:
            print(msg)

    def note(self, msg: str) -> None:
        self._keep("note", msg)
        print(msg, file=sys.stderr)


CON = _Console()


def write_audit_log(log_dir: Path, argv: list[str], started: datetime.datetime,
                    outcome: str, label: str = "run") -> Path | None:
    """One file per invocation: exact command line, versions, everything the
    run said, and how it ended. Never lets a logging failure kill the run."""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        name = f"{started.strftime('%Y%m%d-%H%M%S')}_{slugify(label)[:40]}.log"
        ended = datetime.datetime.now()
        body = [
            f"transcript_archiver v{VERSION}",
            f"python {sys.version.split()[0]} on {sys.platform}",
            "command: " + " ".join(argv),
            f"cwd: {os.getcwd()}",
            f"started: {started.isoformat(timespec='seconds')}",
            f"ended:   {ended.isoformat(timespec='seconds')}",
            "",
            *CON.lines,
            "",
            f"outcome: {outcome}",
        ]
        path = log_dir / name
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        return path
    except OSError as e:
        print(f"note: could not write audit log: {e}", file=sys.stderr)
        return None

# ---------------------------------------------------------------------------
# Pricing (USD per million tokens, public list rates). Cost is an estimate at
# list price: it is not what a subscription actually bills, but it is the only
# figure that makes cache reads legible next to output tokens.
# ---------------------------------------------------------------------------

PRICING = {
    "claude-fable-5":            (10.00, 50.00),
    "claude-mythos-5":           (10.00, 50.00),
    "claude-opus-5":             (5.00, 25.00),
    "claude-opus-4-8":           (5.00, 25.00),
    "claude-opus-4-7":           (5.00, 25.00),
    "claude-opus-4-6":           (5.00, 25.00),
    "claude-opus-4-5":           (5.00, 25.00),
    "claude-sonnet-5":           (3.00, 15.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-sonnet-4-5":         (3.00, 15.00),
    "claude-haiku-4-5":          (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}
# Introductory rates that expire; (input, output, through-date).
INTRO_PRICING = {
    "claude-sonnet-5": (2.00, 10.00, datetime.date(2026, 8, 31)),
}
CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = {"5m": 1.25, "1h": 2.00}


def model_rates(model: str, on: datetime.date) -> tuple[float, float] | None:
    intro = INTRO_PRICING.get(model)
    if intro and on <= intro[2]:
        return intro[0], intro[1]
    return PRICING.get(model)


# ---------------------------------------------------------------------------
# Attachment / system record policy.
#   render   -> shown as a collapsed harness row
#   count    -> counted in the fidelity report only (pure plumbing, no content)
# ---------------------------------------------------------------------------

ATTACHMENT_POLICY = {
    "hook_success":            ("render", "Hook"),
    "hook_additional_context": ("render", "Hook context injected"),
    "hook_system_message":     ("render", "Hook message"),
    "skill_listing":           ("render", "Skill listing injected"),
    "invoked_skills":          ("render", "Skill invoked"),
    "nested_memory":           ("render", "Project memory injected"),
    "file":                    ("render", "File injected"),
    "edited_text_file":        ("render", "File edit snapshot"),
    "compact_file_reference":  ("render", "File carried through compaction"),
    "read_truncation_notice":  ("render", "Read truncated"),
    "deferred_tools_delta":    ("render", "Deferred tools changed"),
    "agent_listing_delta":     ("render", "Agent listing changed"),
    "mcp_instructions_delta":  ("render", "MCP instructions injected"),
    "command_permissions":     ("render", "Command permissions"),
    "task_reminder":           ("render", "Task reminder"),
    "queued_command":          ("render", "Command queued"),
    "date_change":             ("render", "Date changed"),
    "total_tokens_reminder":   ("count", "Token-budget reminder"),
}

SYSTEM_SUBTYPE_POLICY = {
    "turn_duration":       ("count", "Turn duration"),   # consumed as a metric
    "local_command":       ("render", "Local slash command"),
    "bridge_status":       ("render", "Session bridged"),
    "scheduled_task_fire": ("render", "Scheduled task fired"),
    "compact_boundary":    ("render", "Context compacted"),
    # Claude Code 2.1.25x: a safeguard refusal that retracts messages and
    # continues on a fallback model, and the away-summary recap. Both carry
    # transcript content and render as events (seen 2026-08-31, Fable 5).
    "model_refusal_fallback": ("render", "Model fallback after a safeguard refusal"),
    "away_summary":        ("render", "Away summary"),
}

# Record types that carry no transcript content: UI state, indexes, snapshots.
METADATA_RECORD_TYPES = {
    "last-prompt", "mode", "permission-mode", "ai-title", "queue-operation",
    "file-history-snapshot", "file-history-delta", "bridge-session",
    "frame-link", "agent-name", "summary",
    # worktree bookkeeping (Claude Code 2.1.x): where the session's cwd moved
    # to and which git worktree it entered -- state, not conversation
    "worktree-state", "relocated", "atis-latch",
    # Claude Code 2.1.9x: running cost/usage snapshot and artifact-comment
    # bookkeeping (which artifacts are watched, what has been replied to)
    "cost-state", "artifact-comment-monitor", "artifact-autoreact-ledger",
}


# ---------------------------------------------------------------------------
# Markdown -> HTML. Same scope as v1 (this is Claude's own prose, not arbitrary
# CommonMark) plus indentation-aware nested lists, which v1 flattened.
# ---------------------------------------------------------------------------

def inline_md(s: str) -> str:
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\*\w])\*([^*\n]+)\*(?![\*\w])", r"<em>\1</em>", s)
    s = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s


# A numbered item is at most three digits: "2024. was a good year" is prose
# opening with a year, not item 2024 of a list.
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$")
_FENCE_RE = re.compile(r"^(`{3,})\s*(.*)$")


def _render_list(items: list[tuple[int, bool, str]], start: int = 0) -> tuple[str, int]:
    """items = [(indent, ordered, text)]; returns (html, index consumed)."""
    if not items:
        return "", start
    indent = items[start][0]
    ordered = items[start][1]
    tag = "ol" if ordered else "ul"
    out = [f"<{tag}>"]
    i = start
    while i < len(items):
        ind, orderd, text = items[i]
        if ind < indent:
            break
        if ind > indent:
            nested, i = _render_list(items, i)
            out.append(nested)
            continue
        if orderd != ordered:
            break
        out.append("<li>" + inline_md(text))
        # a deeper block immediately after belongs inside this <li>
        if i + 1 < len(items) and items[i + 1][0] > indent:
            nested, i = _render_list(items, i + 1)
            out.append(nested)
        else:
            i += 1
        out.append("</li>")
    out.append(f"</{tag}>")
    return "".join(out), i


def md_tokens(text: str) -> list[tuple]:
    """Scan markdown into typed blocks.

    Split out of md_to_html so HTML and LaTeX render from one parse instead of
    two copies that drift. Token shapes:
        ("para", str) ("code", lang, str) ("heading", level, str) ("hr",)
        ("table", header, rows) ("list", items) ("quote", str)
    """
    if not text:
        return []
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[tuple] = []
    para: list[str] = []
    i, n = 0, len(lines)

    def flush():
        if para:
            out.append(("para", " ".join(para)))
            para.clear()

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        fence = _FENCE_RE.match(stripped)
        if fence:
            # The closing fence must be at least as long as the opening one, so
            # a ```` block can quote ``` without ending early, and the language
            # is whatever follows the run -- never a stray backtick.
            flush()
            ticks, lang = fence.group(1), fence.group(2).strip()
            close = re.compile(r"^`{%d,}\s*$" % len(ticks))
            i += 1
            code = []
            while i < n and not close.match(lines[i].strip()):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(("code", lang, "\n".join(code)))
            continue

        if re.match(r"^#{1,6}\s+", stripped):
            flush()
            level = min(len(stripped) - len(stripped.lstrip("#")), 5)
            out.append(("heading", level, stripped.lstrip("#").strip()))
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush()
            out.append(("hr",))
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|?[\s:|-]+\|?$", lines[i + 1].strip()):
            flush()
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append(("table", header, rows))
            continue

        if _LIST_RE.match(raw):
            flush()
            items: list[tuple[int, bool, str]] = []
            while i < n:
                m = _LIST_RE.match(lines[i])
                if not m:
                    if lines[i].strip() == "" and i + 1 < n and _LIST_RE.match(lines[i + 1]):
                        i += 1
                        continue
                    break
                indent = len(m.group(1).expandtabs(4))
                ordered = bool(re.match(r"^\d", m.group(2)))
                items.append((indent, ordered, m.group(3)))
                i += 1
            out.append(("list", items))
            continue

        if stripped.startswith(">"):
            flush()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(("quote", " ".join(quote)))
            continue

        if stripped == "":
            flush()
            i += 1
            continue

        para.append(stripped)
        i += 1

    flush()
    return out


def md_to_html(text: str) -> str:
    out = []
    for tok in md_tokens(text):
        if tok[0] == "para":
            out.append("<p>" + inline_md(tok[1]) + "</p>")
        elif tok[0] == "code":
            cls = f' data-lang="{esc(tok[1])}"' if tok[1] else ""
            out.append(f'<pre class="code-block"{cls}><code>' + esc(tok[2]) + "</code></pre>")
        elif tok[0] == "heading":
            out.append(f"<h{tok[1] + 1}>{inline_md(tok[2])}</h{tok[1] + 1}>")
        elif tok[0] == "hr":
            out.append("<hr>")
        elif tok[0] == "table":
            header, rows = tok[1], tok[2]
            tbl = ['<div class="table-wrap"><table><thead><tr>']
            tbl += [f"<th>{inline_md(c)}</th>" for c in header]
            tbl.append("</tr></thead><tbody>")
            for r in rows:
                tbl.append("<tr>" + "".join(f"<td>{inline_md(c)}</td>" for c in r) + "</tr>")
            tbl.append("</tbody></table></div>")
            out.append("".join(tbl))
        elif tok[0] == "list":
            # _render_list stops at a marker-type switch or a dedent below its
            # starting indent; loop until every item is consumed, or a list
            # that switches from bullets to numbers loses its tail.
            items, i = tok[1], 0
            parts = []
            while i < len(items):
                listing, j = _render_list(items, i)
                parts.append(listing)
                i = j if j > i else i + 1
            out.append("".join(parts))
        elif tok[0] == "quote":
            out.append("<blockquote>" + inline_md(tok[1]) + "</blockquote>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Tool-call one-liners
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Human turns are reproduced verbatim.
#
# A user message is typed text and pastes -- console output, tracebacks, log
# lines, columnar benchmark results -- not authored markdown. v2.0 ran it through
# md_to_html, which joined consecutive lines into run-on paragraphs and turned a
# traceback's dashed separator into an <hr>: a pasted benchmark table came out
# reading like prose, indistinguishable from Claude's own writing. Nothing is
# interpreted here now; only bare URLs become links.
#
# The monospace switch is presentation only -- it decides whether a paste's
# columns line up, never what the text says -- so a wrong guess costs alignment
# and nothing else.
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"(https?://[^\s<>\"')]*[^\s<>\"')\.,;:!?])")
_CONSOLE_RE = re.compile(
    r"(Traceback \(most recent call last\)|^\s*File \"|^\s*at [\w.$]+\(|^\s*\$ |^\s*> |^PS [A-Z]:|"
    r"^\s*(Cell In\[|-{3,}>|\w+Error\b|\w+Exception\b))")


def looks_columnar(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    if any(_CONSOLE_RE.search(ln) for ln in lines):
        return True
    aligned = sum(1 for ln in lines
                  if re.search(r"\S {2,}\S", ln) or ln.startswith(("  ", "\t", "|")))
    return aligned >= max(2, len(lines) // 3)


def human_html(text: str) -> str:
    # Link on the raw text and escape each piece afterwards: escaping first
    # turns a trailing apostrophe into &#x27; and the URL swallows it.
    parts = []
    for i, piece in enumerate(URL_RE.split(text)):
        if i % 2:
            parts.append(f'<a href="{esc(piece)}" target="_blank" rel="noopener">{esc(piece)}</a>')
        else:
            parts.append(esc(piece))
    body = "".join(parts)
    cls = "raw mono" if looks_columnar(text) else "raw"
    return f'<div class="{cls}">{body}</div>'


def truncate(s: str, n: int = 100) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def shorten(text: str, width: int = 72) -> str:
    """One-line, bounded label for a box title.

    A tcolorbox title does not wrap: a PowerShell call whose label is the whole
    command ran off the right edge of the page on 95 blocks of one archive.
    Newlines are collapsed first, because a title spanning lines breaks the box.
    """
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 3].rstrip() + "..."


def pretty_tool_input(raw: str) -> str:
    """Render a tool call's arguments so a human can read them.

    json.dumps keeps a multi-line string on one line with its newlines written
    as \n, so a Write call carrying a whole source file arrives as a single
    escaped string thousands of characters long -- pages of unreadable wrapping
    in any page-based format. Long or multi-line values are broken out as
    indented blocks instead, with the real line breaks restored.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if not isinstance(data, dict):
        return raw
    out = []
    for key, val in data.items():
        if isinstance(val, str):
            text = val
        elif isinstance(val, (dict, list)):
            text = json.dumps(val, indent=2, ensure_ascii=False)
        else:
            text = json.dumps(val, ensure_ascii=False)
        if "\n" in text or len(text) > 88:
            out.append(f"{key}:")
            out.extend("    " + ln for ln in text.replace("\r\n", "\n").split("\n"))
        else:
            out.append(f"{key}: {text}")
    return "\n".join(out)


def describe_tool(name: str, inp: dict) -> tuple[str, str]:
    inp = inp or {}
    simple = {
        "Bash": "command", "PowerShell": "command", "Read": "file_path",
        "Write": "file_path", "Edit": "file_path", "NotebookEdit": "notebook_path",
        "Grep": "pattern", "Glob": "pattern", "WebSearch": "query",
        "WebFetch": "url", "ToolSearch": "query", "Skill": "skill",
        "Agent": "description", "Task": "description", "ScheduleWakeup": "reason",
        "Artifact": "file_path", "SendMessage": "message", "Monitor": "command",
        "CronCreate": "prompt", "TaskOutput": "task_id", "TaskStop": "task_id",
        "SendUserFile": "files",
    }
    if name in simple:
        v = inp.get(simple[name], "")
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        if name == "Artifact" and not v:
            v = inp.get("action", "publish")
        return name, truncate(v)
    if name == "AskUserQuestion":
        qs = inp.get("questions") or []
        return name, truncate("; ".join(q.get("question", "") for q in qs))
    if name == "ReportFindings":
        return name, _("{n} finding(s)").format(n=len(inp.get("findings") or []))
    if name == "TodoWrite":
        return name, _("{n} item(s)").format(n=len(inp.get("todos") or []))
    if name.startswith("mcp__"):
        parts = name.split("__")
        short = parts[-1]
        server = parts[1] if len(parts) > 2 else ""
        detail = (inp.get("url") or inp.get("query") or inp.get("text")
                  or inp.get("prompt") or inp.get("action") or "")
        if not detail and inp:
            detail = json.dumps(inp)[:160]
        label = f"{server}/{short}" if server else short
        return label, truncate(detail)
    return name, truncate(json.dumps(inp, ensure_ascii=False)[:200])


# ---------------------------------------------------------------------------
# Human vs injected classification.
#
# Authoritative signals, in order:
#   1. record.origin.kind          -> "human" | "task-notification" | ...
#   2. record.promptSource         -> "typed" | "suggestion_accepted" | "system"
#   3. record.isCompactSummary     -> compaction continuation blob
#   4. text markers (older records written before those fields existed)
#   5. a ScheduleWakeup prompt seen earlier in this same session
#
# (5) is what closes v1's documented "known gap": the archiver now remembers
# what the assistant actually scheduled, so a wakeup prompt firing back as a
# user turn is recognised without any adjacency guessing.
# ---------------------------------------------------------------------------

TEXT_MARKERS = (
    ("<task-notification>",           "Background task notification"),
    ("[SYSTEM NOTIFICATION",          "Background task notification"),
    ("[Your previous response had no visible output", "Harness nudge"),
    ("<command-name>",                "Local slash command"),
    ("<local-command-stdout>",        "Local command output"),
    ("<local-command-caveat>",        "Local command caveat"),
    ("<user-prompt-submit-hook>",     "Prompt-submit hook"),
    ("This session is being continued from a previous conversation",
                                      "Context compaction summary"),
)

# Older records predate promptSource/origin, and a few injected shapes are
# templated rather than prefixed. These were derived by auditing every record
# the field-based signals left unclassified.
REGEX_MARKERS = (
    (re.compile(r"^\[\d+ prior /loop wakeups? found nothing actionable"), "Loop heartbeat"),
    (re.compile(r"^Skill /\S+ is already loaded above"),                  "Skill already loaded"),
    (re.compile(r"^\[Request interrupted"),                               "Interrupted by user"),
    (re.compile(r"^\[Image: original \d+x\d+"),                           "Image scaling note"),
)


def classify_user_string(rec: dict, text: str, scheduled_prompts: set[str]) -> tuple[str, str, str]:
    """-> (kind, badge, evidence). kind is 'human' or 'system'."""
    if rec.get("isCompactSummary"):
        return "system", "Context compaction summary", "isCompactSummary"

    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        kind = origin["kind"]
        if kind == "human":
            return "human", "", "origin.kind=human"
        if kind == "task-notification":
            return "system", "Background task notification", "origin.kind=task-notification"
        return "system", kind.replace("-", " ").capitalize(), f"origin.kind={kind}"

    src = rec.get("promptSource")
    if src in ("typed", "suggestion_accepted"):
        return "human", "", f"promptSource={src}"
    if src == "system":
        for marker, badge in TEXT_MARKERS:
            if text.startswith(marker) or marker in text[:200]:
                return "system", badge, f"promptSource=system + {marker}"
        return "system", "Harness-injected prompt", "promptSource=system"

    for marker, badge in TEXT_MARKERS:
        if text.startswith(marker) or marker in text[:200]:
            return "system", badge, f"text marker {marker}"

    for rx, badge in REGEX_MARKERS:
        if rx.match(text):
            return "system", badge, f"pattern {rx.pattern[:34]}"

    norm = " ".join(text.split())
    for prompt in scheduled_prompts:
        if norm and norm == " ".join(prompt.split()):
            return "system", "Scheduled continuation", "matches a ScheduleWakeup prompt"

    return "human", "", "default (no promptSource/origin on this record)"


# ---------------------------------------------------------------------------
# Session discovery + chain resolution
# ---------------------------------------------------------------------------

class SessionFile:
    __slots__ = ("sid", "path", "uuids", "first", "last", "records", "title",
                 "subagents", "source", "conv_uuids")

    def __init__(self, sid, path, uuids, first, last, records, title, conv_uuids=None):
        self.sid, self.path = sid, path
        self.uuids, self.first, self.last = uuids, first, last
        self.records, self.title = records, title
        self.subagents = 0          # subagent transcripts filed under this session
        self.source = "claude-code"  # or "cowork" (Claude Desktop local agent)
        # The exchanges themselves: assistant records and typed prompts. A
        # resume after /compact carries these forward but not the old file's
        # compaction tail, so continuation-vs-fork is judged on them alone.
        self.conv_uuids = conv_uuids if conv_uuids is not None else set(uuids)


def _is_conversation_record(obj: dict) -> bool:
    rtype = obj.get("type")
    if rtype == "assistant":
        return True
    if rtype != "user" or obj.get("isCompactSummary"):
        return False
    msg = obj.get("message") or {}
    if not isinstance(msg.get("content"), str):
        return False                      # tool results, injected blocks
    origin = obj.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return origin["kind"] == "human"
    src = obj.get("promptSource")
    if src:
        return src in ("typed", "suggestion_accepted")
    return not msg["content"].lstrip().startswith("<")   # older records: markers are injected


def scan_sessions(root: Path) -> dict[str, SessionFile]:
    """Sessions only.

    A subagent's transcript lives at <project>/<session-id>/subagents/agent-*.jsonl.
    It is a *part* of its parent session, not a conversation of its own, so it is
    counted against the parent rather than listed as a session -- globbing **/*.jsonl
    blindly reported 178 "sessions" on this machine when there were 40.
    """
    found: dict[str, SessionFile] = {}
    subagents: Counter = Counter()
    for path in sorted(root.glob("**/*.jsonl")):
        if path.name == "audit.jsonl":     # cowork bookkeeping, not a session
            continue
        if "subagents" in path.parts:
            i = path.parts.index("subagents")
            if i:
                subagents[path.parts[i - 1]] += 1
            continue
        uuids: set[str] = set()
        conv: set[str] = set()
        first = last = None
        count = 0
        title = None
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    count += 1
                    u = obj.get("uuid")
                    if u:
                        uuids.add(u)
                        if _is_conversation_record(obj):
                            conv.add(u)
                    ts = obj.get("timestamp")
                    if ts:
                        if first is None or ts < first:
                            first = ts
                        if last is None or ts > last:
                            last = ts
                    if obj.get("type") == "ai-title" and obj.get("aiTitle"):
                        title = obj["aiTitle"]
        except OSError:
            continue
        found[path.stem] = SessionFile(path.stem, path, uuids, first, last, count, title, conv)
    for sid, n in subagents.items():
        if sid in found:
            found[sid].subagents = n
    return found


def default_cowork_root() -> Path:
    """Where Claude Desktop's cowork (local agent mode) keeps its sessions.

    Same record schema, same <...>/.claude/projects/<proj>/<sid>.jsonl layout,
    different base directory per platform."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Claude" / "local-agent-mode-sessions"
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "Claude"
                / "local-agent-mode-sessions")
    return Path.home() / ".config" / "Claude" / "local-agent-mode-sessions"


def scan_all_sessions(projects_root: Path, cowork_root: Path | None) -> dict[str, SessionFile]:
    """Claude Code sessions, plus cowork sessions when that root exists.

    Session ids are uuids, so a cross-source collision is not expected; if one
    ever happens the Claude Code file wins and the clash is reported."""
    sessions = scan_sessions(projects_root)
    if cowork_root and cowork_root.is_dir():
        for sid, info in scan_sessions(cowork_root).items():
            info.source = "cowork"
            if sid in sessions:
                print(f"note: session {sid} exists in both {projects_root} and "
                      f"{cowork_root}; using the Claude Code copy", file=sys.stderr)
                continue
            sessions[sid] = info
    return sessions


def resolve_chain(sid: str, sessions: dict[str, SessionFile]) -> tuple[str, list[dict]]:
    """Find the most complete file sharing this session's history.

    A resumed session (or one bridged to web/mobile via /remote-control) is
    written to a *new* .jsonl that repeats the earlier records. Archiving the
    id the user happens to name can therefore capture half a conversation and
    label it with the wrong id -- which is exactly what happened to the v1
    archive of 3c2a527b (its file held 6eb46cd7, a 256-record superset).
    """
    base = sessions[sid]
    related: list[dict] = []
    best = sid
    for other, info in sessions.items():
        if other == sid or not info.uuids or not base.uuids:
            continue
        shared = len(base.uuids & info.uuids)
        if not shared:
            continue
        overlap = shared / min(len(base.uuids), len(info.uuids))
        if overlap < 0.5:
            continue
        # A continuation can drop bookkeeping: a stray bridge_status record, an
        # empty thinking block, or -- after /compact -- the whole compaction
        # tail (attachments, the boundary, the summary; 18 records on one real
        # pair). Strict set containment mislabels those a "fork". So the
        # judgement is made on the *exchanges*: a file that carries every
        # prompt and response of this one (give or take a couple) and goes on
        # is the same conversation continued; one missing exchanges diverged.
        dropped = len(base.uuids - info.uuids)
        base_conv = getattr(base, "conv_uuids", base.uuids)
        info_conv = getattr(info, "conv_uuids", info.uuids)
        dropped_conv = len(base_conv - info.uuids)
        tolerance = max(2, len(base_conv) // 100)
        if dropped == 0 or (dropped_conv <= tolerance and len(info_conv) > len(base_conv)):
            rel = "superset"
        elif base.uuids >= info.uuids:
            rel = "subset"
        else:
            rel = "fork"
        related.append({
            "session_id": other, "shared": shared, "records": info.records,
            "own_uuids": len(info.uuids), "relation": rel, "dropped": dropped,
        })
        # Only a superset is the same conversation continued. A fork shares
        # history but then diverges: archiving it in place of the requested id
        # would silently swap in a different conversation, however large.
        # Compared on exchanges, not raw uuids: the old file's compaction tail
        # can make it the *larger* file while holding less conversation.
        best_conv = getattr(sessions[best], "conv_uuids", sessions[best].uuids)
        if rel == "superset" and len(info_conv) > len(best_conv):
            best = other
    related.sort(key=lambda r: -r["own_uuids"])
    return best, related


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_ts(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


class Transcript:
    def __init__(self):
        self.turns: list[dict] = []
        self.counts = Counter()
        self.record_types = Counter()
        self.rendered_types = Counter()
        self.counted_only = Counter()
        self.blocks = Counter()
        self.models = Counter()
        self.usage_by_model: dict[str, Counter] = defaultdict(Counter)
        self.timestamps: list[str] = []
        self.turn_durations_ms = 0
        self.turn_duration_records = 0
        self.version = None
        self.cwd = None
        self.git_branch = None
        self.title_hint = None
        self.typed_prompts: list[str] = []
        self.scheduled_prompts: set[str] = set()
        self.unresolved_tools = 0
        self.classification = Counter()
        self.bridges: list[str] = []
        self.compactions: list[dict] = []
        # Harness retractions: messages a safeguard refusal withdrew. They are
        # named by uuid in the fallback record and usually absent from the
        # source file, so the page must report them -- a gap the record count
        # cannot show.
        self.retractions: list[dict] = []
        self.effort = Counter()
        self.skills = Counter()
        self.mcp_servers = Counter()
        self.disposition = Counter()   # per-record: rendered / folded / counted
        self.empty_thinking = 0
        # cost-state snapshots keyed by process startTime (ms): Claude Code
        # restarts its meter on every resume, so one session has many runs.
        self.cost_states: dict[int, dict] = {}


def parse_transcript(path: Path, max_tool_output: int) -> Transcript:
    t = Transcript()
    with path.open(encoding="utf-8") as fh:
        objs = []
        for line in fh:
            if line.strip():
                try:
                    objs.append(json.loads(line))
                except json.JSONDecodeError:
                    # A line the parser cannot even read is still a line of the
                    # source. It enters the record count and the disposition so
                    # the fidelity report shows it -- "no silent drops" must
                    # cover corruption, not just record classes.
                    t.record_types["(unparseable line)"] += 1
                    t.counted_only["unparseable line (invalid JSON)"] += 1
                    t.disposition["counted"] += 1

    # Pass 1: collect ScheduleWakeup prompts so a firing wakeup can be
    # recognised later even on records with no promptSource field.
    for obj in objs:
        if obj.get("type") != "assistant":
            continue
        for b in ((obj.get("message") or {}).get("content") or []):
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "ScheduleWakeup":
                p = (b.get("input") or {}).get("prompt")
                if isinstance(p, str) and p.strip():
                    t.scheduled_prompts.add(p.strip())

    file_uuids = {o.get("uuid") for o in objs if isinstance(o.get("uuid"), str)}
    tool_index: dict[str, dict] = {}
    seen_requests: set[str] = set()

    for obj in objs:
        rtype = obj.get("type")
        t.record_types[rtype] += 1
        ts = obj.get("timestamp")
        if ts:
            t.timestamps.append(ts)
        if obj.get("version"):
            t.version = obj["version"]
        if obj.get("cwd"):
            t.cwd = obj["cwd"]
        if obj.get("gitBranch"):
            t.git_branch = obj["gitBranch"]
        if rtype == "ai-title" and obj.get("aiTitle"):
            t.title_hint = obj["aiTitle"]
        if rtype == "last-prompt" and obj.get("lastPrompt"):
            t.typed_prompts.append(obj["lastPrompt"])
        if rtype == "bridge-session" and obj.get("bridgeSessionId"):
            if obj["bridgeSessionId"] not in t.bridges:
                t.bridges.append(obj["bridgeSessionId"])

        # ---- assistant ------------------------------------------------
        if rtype == "assistant":
            turns_before = len(t.turns)
            msg = obj.get("message") or {}
            model = msg.get("model") or "unknown"
            t.models[model] += 1
            if obj.get("effort"):
                t.effort[obj["effort"]] += 1
            if obj.get("attributionSkill"):
                t.skills[obj["attributionSkill"]] += 1
            if obj.get("attributionMcpServer"):
                t.mcp_servers[obj["attributionMcpServer"]] += 1

            rid = obj.get("requestId") or msg.get("id")
            if rid and rid not in seen_requests:
                seen_requests.add(rid)
                u = msg.get("usage") or {}
                agg = t.usage_by_model[model]
                agg["requests"] += 1
                agg["input"] += u.get("input_tokens", 0) or 0
                agg["output"] += u.get("output_tokens", 0) or 0
                agg["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
                cc = u.get("cache_creation") or {}
                w5 = cc.get("ephemeral_5m_input_tokens")
                w1h = cc.get("ephemeral_1h_input_tokens")
                if w5 is None and w1h is None:
                    agg["cache_write_5m"] += u.get("cache_creation_input_tokens", 0) or 0
                else:
                    agg["cache_write_5m"] += w5 or 0
                    agg["cache_write_1h"] += w1h or 0
            elif not rid:
                t.counts["assistant_records_without_request_id"] += 1

            content = msg.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for c in content or []:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                t.blocks[ctype] += 1
                if ctype == "text":
                    txt = c.get("text", "")
                    if txt.strip():
                        t.turns.append({
                            "kind": "assistant", "ts": ts, "model": model,
                            "html": md_to_html(txt), "text": txt,
                            "sidechain": bool(obj.get("isSidechain")),
                        })
                        t.rendered_types["assistant text"] += 1
                    else:
                        t.counted_only["empty assistant text block"] += 1
                elif ctype == "thinking":
                    txt = c.get("thinking", "")
                    if txt.strip():
                        t.turns.append({
                            "kind": "thinking", "ts": ts, "model": model,
                            "html": md_to_html(txt), "text": txt,
                        })
                        t.rendered_types["thinking"] += 1
                    else:
                        # display:"omitted" -- the block exists, the text never
                        # reaches the transcript. Claude Code runs this way, so
                        # in practice every thinking block is empty: the archive
                        # can show *that* Claude thought, never what it thought.
                        t.empty_thinking += 1
                        t.counted_only["thinking block with no text (display=omitted)"] += 1
                elif ctype == "redacted_thinking":
                    t.turns.append({
                        "kind": "thinking", "ts": ts, "model": model,
                        "html": "<p><em>Redacted thinking (encrypted by the API).</em></p>",
                        "text": "", "redacted": True,
                    })
                    t.rendered_types["redacted thinking"] += 1
                elif ctype == "tool_use":
                    name = c.get("name", "tool")
                    inp = c.get("input", {})
                    chip, label = describe_tool(name, inp)
                    turn = {
                        "kind": "tool", "ts": ts, "chip": chip, "label": label,
                        "tool_name": name,
                        "input": json.dumps(inp, indent=2, ensure_ascii=False),
                        "output_text": None, "output_images": [],
                        "is_error": False, "resolved": False,
                        "sidechain": bool(obj.get("isSidechain")),
                    }
                    tool_index[c.get("id")] = turn
                    t.turns.append(turn)
                    t.rendered_types["tool call"] += 1
                else:
                    t.turns.append({
                        "kind": "raw_block", "ts": ts,
                        "badge": f"assistant block: {ctype}",
                        "text": json.dumps(c, indent=2, ensure_ascii=False)[:4000],
                    })
                    t.rendered_types[f"assistant block ({ctype})"] += 1
            t.disposition["rendered" if len(t.turns) > turns_before else "counted"] += 1
            continue

        # ---- user -----------------------------------------------------
        if rtype == "user":
            turns_before = len(t.turns)
            folded = False
            msg = obj.get("message") or {}
            content = msg.get("content")

            if isinstance(content, str):
                text = content.strip()
                if not text:
                    t.counted_only["empty user record"] += 1
                    t.disposition["counted"] += 1
                    continue
                kind, badge, evidence = classify_user_string(obj, text, t.scheduled_prompts)
                t.classification[evidence] += 1
                if kind == "human":
                    t.turns.append({"kind": "human", "ts": ts, "text": text,
                                    "html": human_html(text)})
                    t.rendered_types["human turn"] += 1
                else:
                    body = text
                    if badge == "Background task notification":
                        m = re.search(r"<task-notification>.*?</task-notification>", text, re.S)
                        body = m.group(0) if m else text
                    t.turns.append({"kind": "system", "ts": ts, "badge": badge,
                                    "text": body, "evidence": evidence})
                    t.rendered_types[f"system turn ({badge})"] += 1
                t.disposition["rendered"] += 1
                continue

            if isinstance(content, list):
                # A text block in list content is normally harness text riding
                # beside a tool result. Only positive provenance (origin.kind or
                # promptSource on the record) makes it a human prompt -- the
                # shape Claude Code uses when text and an image are typed together.
                origin_kind = (obj.get("origin") or {}).get("kind") \
                    if isinstance(obj.get("origin"), dict) else None
                typed_here = (origin_kind == "human"
                              or obj.get("promptSource") in ("typed", "suggestion_accepted"))
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    ctype = c.get("type")
                    t.blocks[f"user:{ctype}"] += 1
                    if ctype == "text":
                        txt = (c.get("text") or "").strip()
                        if txt and typed_here:
                            evidence = ("origin.kind=human" if origin_kind == "human"
                                        else f"promptSource={obj.get('promptSource')}")
                            t.classification[evidence + " (list content)"] += 1
                            t.turns.append({"kind": "human", "ts": ts, "text": txt,
                                            "html": human_html(txt)})
                            t.rendered_types["human turn"] += 1
                        elif txt:
                            t.turns.append({
                                "kind": "system", "ts": ts,
                                "badge": "Instructions injected into the turn",
                                "text": txt, "evidence": "user content-block text",
                            })
                            t.rendered_types["system turn (injected instructions)"] += 1
                    elif ctype == "image":
                        src = c.get("source") or {}
                        if src.get("data"):
                            t.turns.append({
                                "kind": "user_image", "ts": ts,
                                "media": src.get("media_type", "image/png"),
                                "data": src["data"],
                            })
                            t.rendered_types["pasted image"] += 1
                    elif ctype == "tool_result":
                        turn = tool_index.get(c.get("tool_use_id"))
                        if not turn:
                            t.counted_only["tool_result with no matching tool_use"] += 1
                            continue
                        parts: list[str] = []
                        cc = c.get("content")
                        if isinstance(cc, str):
                            parts.append(cc)
                        elif isinstance(cc, list):
                            for x in cc:
                                if not isinstance(x, dict):
                                    continue
                                xt = x.get("type")
                                if xt == "text":
                                    parts.append(x.get("text", ""))
                                elif xt == "image":
                                    isrc = x.get("source") or {}
                                    if isrc.get("data"):
                                        turn["output_images"].append(
                                            (isrc.get("media_type", "image/png"), isrc["data"]))
                                elif xt == "tool_result":
                                    inner = x.get("content")
                                    if isinstance(inner, str):
                                        parts.append(inner)
                                elif xt == "tool_reference":
                                    parts.append(f"[tool loaded: {x.get('tool_name', '?')}]")
                                else:
                                    parts.append(json.dumps(x, ensure_ascii=False)[:2000])
                        elif cc is not None:
                            parts.append(json.dumps(cc, ensure_ascii=False))
                        text = "\n".join(p for p in parts if p)
                        if max_tool_output and len(text) > max_tool_output:
                            head = text[: int(max_tool_output * 0.75)]
                            tail = text[-int(max_tool_output * 0.25):]
                            elided = len(text) - len(head) - len(tail)
                            text = (f"{head}\n\n… [{elided:,} characters elided by "
                                    f"--max-tool-output; re-run with --full for everything] …\n\n{tail}")
                            turn["elided"] = elided
                        turn["output_text"] = text
                        turn["is_error"] = bool(c.get("is_error"))
                        turn["resolved"] = True
                        folded = True
                        # The record carrying an Agent tool's result names the
                        # spawned agent in a top-level toolUseResult.agentId --
                        # the only durable link between the parent conversation
                        # and <session-id>/subagents/agent-<id>.jsonl.
                        tur = obj.get("toolUseResult")
                        if isinstance(tur, dict) and tur.get("agentId"):
                            turn["agent_id"] = tur["agentId"]
                    else:
                        t.turns.append({
                            "kind": "raw_block", "ts": ts,
                            "badge": f"user block: {ctype}",
                            "text": json.dumps(c, indent=2, ensure_ascii=False)[:4000],
                        })
                        t.rendered_types[f"user block ({ctype})"] += 1
                if len(t.turns) > turns_before:
                    t.disposition["rendered"] += 1
                elif folded:
                    t.disposition["folded"] += 1
                else:
                    t.disposition["counted"] += 1
                continue

            t.counted_only["user record with no content"] += 1
            t.disposition["counted"] += 1
            continue

        # ---- attachment ------------------------------------------------
        if rtype == "attachment":
            att = obj.get("attachment") or {}
            atype = att.get("type", "unknown")
            policy, label = ATTACHMENT_POLICY.get(atype, ("render", atype.replace("_", " ")))
            if policy == "count":
                t.counted_only[f"attachment: {atype}"] += 1
                t.disposition["counted"] += 1
                continue
            t.disposition["rendered"] += 1
            detail, body = summarize_attachment(atype, att)
            t.turns.append({
                "kind": "harness", "ts": ts, "badge": label,
                "detail": detail, "text": body, "atype": atype,
            })
            t.rendered_types[f"harness ({atype})"] += 1
            continue

        # ---- system ----------------------------------------------------
        if rtype == "system":
            sub = obj.get("subtype") or "unknown"
            policy, label = SYSTEM_SUBTYPE_POLICY.get(sub, ("render", sub.replace("_", " ")))
            if sub == "turn_duration":
                t.turn_durations_ms += obj.get("durationMs") or 0
                t.turn_duration_records += 1
                t.counted_only["system: turn_duration (used for duration metric)"] += 1
                t.disposition["counted"] += 1
                continue
            if policy == "count":
                t.counted_only[f"system: {sub}"] += 1
                t.disposition["counted"] += 1
                continue
            t.disposition["rendered"] += 1
            body = obj.get("content")
            if not isinstance(body, str):
                body = json.dumps(body, ensure_ascii=False) if body is not None else ""
            detail = ""
            if sub == "compact_boundary":
                meta = obj.get("compactMetadata") or {}
                pre, post = meta.get("preTokens"), meta.get("postTokens")
                dropped = meta.get("cumulativeDroppedTokens")
                detail = (f"trigger={meta.get('trigger')} "
                          f"{pre:,} → {post:,} tokens" if pre and post else str(meta.get("trigger", "")))
                t.compactions.append({"trigger": meta.get("trigger"), "pre": pre,
                                      "post": post, "dropped": dropped})
                body = body or "Conversation compacted"
            elif sub == "scheduled_task_fire":
                detail = obj.get("cronKind") or ""
            elif sub == "bridge_status":
                detail = obj.get("url") or ""
            elif sub == "model_refusal_fallback":
                orig = obj.get("originalModel") or "?"
                fb = obj.get("fallbackModel") or "?"
                cat = obj.get("apiRefusalCategory") or ""
                gone = [u for u in (obj.get("retractedMessageUuids") or []) if isinstance(u, str)]
                absent = [u for u in gone if u not in file_uuids]
                detail = f"{orig} -> {fb}" + (f" (category: {cat})" if cat else "")
                if gone:
                    detail += f", {len(gone)} message(s) retracted"
                    body = ((body + "\n\n") if body else "") + (
                        _("{n} message(s) were retracted by the harness after this refusal").format(n=len(gone))
                        + (_("; {n} of them are not in the source transcript").format(n=len(absent))
                           if absent else "")
                        + _(". The conversation continued on {model}.").format(model=fb))
                t.retractions.append({"ts": ts, "from": orig, "to": fb, "category": cat,
                                      "retracted": len(gone), "absent": len(absent),
                                      "refused": obj.get("refusedUserMessageUuid")})
            t.turns.append({"kind": "system_record", "ts": ts, "badge": label,
                            "detail": detail, "text": body, "subtype": sub})
            t.rendered_types[f"system record ({sub})"] += 1
            continue

        # ---- everything else -------------------------------------------
        t.disposition["counted"] += 1
        if rtype in METADATA_RECORD_TYPES:
            t.counted_only[f"metadata: {rtype}"] += 1
            if rtype == "cost-state":
                # cumulative within a run: the last snapshot per run wins
                key = _cost_state_key(obj)
                if key is not None:
                    t.cost_states[key] = obj
        else:
            t.counted_only[f"unhandled record type: {rtype}"] += 1

    t.unresolved_tools = sum(1 for turn in t.turns
                             if turn["kind"] == "tool" and not turn["resolved"])
    return t


def summarize_attachment(atype: str, att: dict) -> tuple[str, str]:
    """-> (one-line detail, expandable body)."""
    if atype == "hook_success":
        detail = f"{att.get('hookName', '?')} exit={att.get('exitCode')}"
        body = "\n".join(x for x in (att.get("stdout"), att.get("stderr")) if x)
        if att.get("command"):
            body = f"$ {att['command']}\n{body}"
        return detail, body or "(no output)"
    if atype in ("hook_additional_context", "hook_system_message", "skill_listing", "task_reminder"):
        content = att.get("content")
        if isinstance(content, list):
            content = "\n".join(str(x) for x in content)
        extra = ""
        if atype == "skill_listing":
            extra = f"{att.get('skillCount', '?')} skills"
        elif atype in ("hook_additional_context", "hook_system_message"):
            extra = att.get("hookName", "")
        elif atype == "task_reminder":
            extra = f"{att.get('itemCount', 0)} items"
        return extra, str(content or "")
    if atype == "invoked_skills":
        skills = att.get("skills") or []
        names = ", ".join(s.get("name", "?") for s in skills if isinstance(s, dict))
        body = "\n\n".join(
            f"--- {s.get('name')} ({s.get('path')}) ---\n{(s.get('content') or '')[:6000]}"
            for s in skills if isinstance(s, dict))
        return names, body
    if atype in ("nested_memory", "file"):
        content = att.get("content")
        if isinstance(content, dict):
            inner = content.get("file") if isinstance(content.get("file"), dict) else None
            content = (inner or content).get("content", json.dumps(content)[:4000])
        return att.get("displayPath") or att.get("filename", ""), str(content or "")[:20000]
    if atype == "edited_text_file":
        return att.get("displayPath") or att.get("filename", ""), str(att.get("snippet") or "")
    if atype == "compact_file_reference":
        return att.get("displayPath") or att.get("filename", ""), ""
    if atype == "read_truncation_notice":
        return "", str(att.get("banner") or "")
    if atype == "deferred_tools_delta":
        added, removed = att.get("addedNames") or [], att.get("removedNames") or []
        detail = f"+{len(added)} / -{len(removed)} tools"
        return detail, "added: " + ", ".join(added) + ("\nremoved: " + ", ".join(removed) if removed else "")
    if atype == "agent_listing_delta":
        added = att.get("addedTypes") or []
        return f"+{len(added)} agents", "\n".join(att.get("addedLines") or [])
    if atype == "mcp_instructions_delta":
        names = att.get("addedNames") or []
        return ", ".join(names), "\n\n".join(att.get("addedBlocks") or [])
    if atype == "command_permissions":
        tools = att.get("allowedTools") or []
        return f"{len(tools)} allowed", ", ".join(tools)
    if atype == "queued_command":
        return att.get("commandMode", ""), str(att.get("prompt") or "")
    if atype == "date_change":
        return str(att.get("newDate", "")), ""
    return "", json.dumps(att, indent=2, ensure_ascii=False)[:8000]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_dur_ms(ms: int) -> str:
    total = int(ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def fmt_local(dt: datetime.datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def fmt_utc(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def tokens(n: int) -> str:
    return f"{n:,}"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# Claude Code >= 2.1.9x writes `cost-state`: its own cost meter, per process.
# Every `claude --resume` starts a new counter (new startTime), and runs made
# before the record existed wrote none -- so the reported figure is the sum of
# the last snapshot of each run, and it can cover only part of a session.
COVERAGE_SLACK_S = 60


def _cost_state_key(obj: dict) -> int | None:
    """The run a cost-state snapshot belongs to, or None if the record is
    unusable (missing, non-numeric or non-finite startTime). A malformed
    bookkeeping record must never abort an export."""
    st = obj.get("startTime")
    if isinstance(st, bool) or not isinstance(st, (int, float)):
        return None
    if isinstance(st, float) and not math.isfinite(st):
        return None
    return int(st)


def _num(v, cast=float):
    try:
        out = cast(v or 0)
    except (TypeError, ValueError):
        return cast(0)
    return out if math.isfinite(float(out)) else cast(0)


def cost_states_of(path: Path) -> dict[int, dict]:
    """Only the cost-state snapshots of a transcript file, last per run.

    A resumed session's continuation file repeats the conversation records
    but not the earlier process's cost-state, so build() gathers the meter
    from every file in the chain. This reads just those lines, cheaply."""
    found: dict[int, dict] = {}
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if '"cost-state"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "cost-state":
                    continue
                key = _cost_state_key(obj)
                if key is not None:
                    found[key] = obj
    except OSError:
        pass
    return found


def reported_cost(t: Transcript, started: datetime.datetime | None = None) -> dict | None:
    if not t.cost_states:
        return None
    runs = [t.cost_states[k] for k in sorted(t.cost_states)]
    by_model: Counter = Counter()
    for r in runs:
        mu_all = r.get("modelUsage")
        if not isinstance(mu_all, dict):
            continue
        for model, mu in mu_all.items():
            if isinstance(mu, dict):
                by_model[str(model)] += _num(mu.get("costUSD"))
    first_start = datetime.datetime.fromtimestamp(min(t.cost_states) / 1000,
                                                  datetime.timezone.utc)
    partial = bool(started is not None
                   and (first_start - started).total_seconds() > COVERAGE_SLACK_S)
    return {
        "usd": sum(_num(r.get("totalCostUSD")) for r in runs),
        "runs": len(runs),
        "first_start": first_start,
        "partial": partial,
        "unknown_model_cost": any(r.get("hasUnknownModelCost") for r in runs),
        "lines_added": sum(_num(r.get("totalLinesAdded"), int) for r in runs),
        "lines_removed": sum(_num(r.get("totalLinesRemoved"), int) for r in runs),
        "by_model": dict(by_model),
    }


def reported_cost_html(rc: dict) -> str:
    """The reported-cost paragraph (inner HTML): the meter's figure, what it
    covers, and the floor caveat. The one phrasing every format states."""
    return (
        _("<b>Reported cost</b> is Claude Code's own meter (<code>cost-state</code> records): "
          "${usd} reported by Claude Code over {runs} run(s) of this session").format(
              usd=f'{rc["usd"]:,.2f}', runs=rc["runs"])
        + (_("; {added} lines added, {removed} removed by tools").format(
            added=f'{rc["lines_added"]:,}', removed=f'{rc["lines_removed"]:,}')
           if rc["lines_added"] or rc["lines_removed"] else "")
        + _(". The meter restarts on every resume and only runs on Claude Code &ge; 2.1.9x write it")
        + (_(" &mdash; <b>this session began before its first metered run ({first}); spend "
             "before that is not covered</b>, so the list-price estimate is the figure for the "
             "whole session.").format(first=fmt_local(rc["first_start"]))
           if rc["partial"] else
           _(", and here the meter covers the whole session."))
        + (_(" Claude Code flagged a model it could not price; the reported total is a floor.")
           if rc["unknown_model_cost"] else ""))


def reported_cost_note(rc: dict | None) -> str:
    """The same paragraph flattened, for the text, Markdown and LaTeX formats
    -- one family of sentences, so no format can drift from the HTML."""
    return html_fragment_to_text(reported_cost_html(rc)) if rc else ""


def usage_table(t: Transcript, on: datetime.date,
                rc: dict | None = None) -> tuple[str, dict]:
    rows = []
    totals = Counter()
    total_cost = 0.0
    unpriced = []
    for model, agg in sorted(t.usage_by_model.items(), key=lambda kv: -kv[1]["output"]):
        rates = model_rates(model, on)
        for k, v in agg.items():
            totals[k] += v
        if rates:
            in_rate, out_rate = rates
            cost = (agg["input"] * in_rate
                    + agg["output"] * out_rate
                    + agg["cache_read"] * in_rate * CACHE_READ_MULTIPLIER
                    + agg["cache_write_5m"] * in_rate * CACHE_WRITE_MULTIPLIER["5m"]
                    + agg["cache_write_1h"] * in_rate * CACHE_WRITE_MULTIPLIER["1h"]) / 1_000_000
            total_cost += cost
            cost_cell = f"${cost:,.2f}"
        else:
            unpriced.append(model)
            cost_cell = f'<span class="muted">{_("no list price")}</span>'
        rep_cell = ""
        if rc:
            rv = rc["by_model"].get(model)
            rep_cell = ("<td class=num>" + (f"${rv:,.2f}" if rv is not None
                                            else '<span class="muted">&mdash;</span>') + "</td>")
        rows.append(
            "<tr><td><code>{m}</code></td><td class=num>{req}</td><td class=num>{inp}</td>"
            "<td class=num>{out}</td><td class=num>{cr}</td><td class=num>{cw}</td>"
            "<td class=num>{cost}</td>{rep}</tr>".format(
                m=esc(model), req=tokens(agg["requests"]), inp=tokens(agg["input"]),
                out=tokens(agg["output"]), cr=tokens(agg["cache_read"]),
                cw=tokens(agg["cache_write_5m"] + agg["cache_write_1h"]), cost=cost_cell,
                rep=rep_cell))
    if rc:
        # models Claude Code priced that never produced a rendered response
        for model in sorted(set(rc["by_model"]) - set(t.usage_by_model)):
            rows.append(f"<tr><td><code>{esc(model)}</code></td>"
                        + '<td class=num>&mdash;</td>' * 5
                        + '<td class=num><span class="muted">&mdash;</span></td>'
                        + f'<td class=num>${rc["by_model"][model]:,.2f}</td></tr>')
    foot = (
        "<tr class=total><td>{total}</td><td class=num>{req}</td><td class=num>{inp}</td>"
        "<td class=num>{out}</td><td class=num>{cr}</td><td class=num>{cw}</td>"
        "<td class=num>${cost:,.2f}</td>{rep}</tr>".format(
            total=_("total"),
            req=tokens(totals["requests"]), inp=tokens(totals["input"]),
            out=tokens(totals["output"]), cr=tokens(totals["cache_read"]),
            cw=tokens(totals["cache_write_5m"] + totals["cache_write_1h"]),
            cost=total_cost,
            rep=(f'<td class=num>${rc["usd"]:,.2f}</td>' if rc else "")))
    table = (
        '<div class="table-wrap"><table class="usage"><thead><tr>'
        + f"<th>{_('model')}</th><th>{_('requests')}</th><th>{_('input')}</th>"
        + f"<th>{_('output')}</th><th>{_('cache read')}</th><th>{_('cache write')}</th>"
        + f"<th>{_('list cost')}</th>"
        + (f"<th>{_('reported cost')}</th>" if rc else "")
        + "</tr></thead><tbody>" + "".join(rows) + foot + "</tbody></table></div>")
    note = (
        '<p class="muted small">'
        + _("Usage is deduped per <code>requestId</code> (one API response is written as several "
            "records, each repeating that response's cumulative usage; summing them over-reports "
            "output by ~2.3&times; on a tool-heavy session). Cost is an estimate at public list "
            "rates &mdash; cache reads at 0.1&times; input, 5-minute cache writes at 1.25&times;, "
            "1-hour writes at 2&times; &mdash; not what a subscription bills.")
        + (_(" No list price on file for: {models}.").format(
            models=esc(", ".join(sorted(set(unpriced))))) if unpriced else "")
        + "</p>")
    if rc:
        note += '<p class="muted small">' + reported_cost_html(rc) + '</p>'
    # A session with no assistant response at all (opened, never answered) leaves
    # `totals` empty; callers index these keys directly, so seed them.
    out = {k: 0 for k in ("requests", "input", "output", "cache_read",
                          "cache_write_5m", "cache_write_1h")}
    out.update(totals)
    out["cost"] = total_cost
    out["reported"] = rc
    return table + note, out


def fidelity_section(t: Transcript, path: Path, archived_at: datetime.datetime,
                     agents: list = (), subagents_on: bool = True) -> str:
    rendered = sum(t.rendered_types.values())
    counted = sum(t.counted_only.values())

    def rows(counter: Counter) -> str:
        return "".join(f"<tr><td>{esc(k)}</td><td class=num>{v:,}</td></tr>"
                       for k, v in sorted(counter.items(), key=lambda kv: -kv[1]))

    total_records = sum(t.record_types.values())
    disp = t.disposition
    reconciles = (disp["rendered"] + disp["folded"] + disp["counted"]) == total_records
    fl = fidelity_lines(t)
    disposition_html = (
        '<div class="table-wrap"><table class="mini"><tbody>'
        + "".join(f'<tr><td>{label}</td><td class=num>{n:,}</td></tr>' for label, n in fl[:3])
        + f'<tr class="total"><td>{fl[3][0]}</td><td class=num>{total_records:,}</td></tr>'
        "</tbody></table></div>"
        + ("" if reconciles else
           '<p class="callout">'
           + _("<strong>These do not add up</strong> — a record class is escaping the parser. "
               "Treat the transcript below as incomplete.") + '</p>'))

    warn = []
    if t.empty_thinking:
        warn.append(_(
            "{n} thinking blocks are present in the source with <em>no text</em>. Claude Code "
            "requests thinking with <code>display: \"omitted\"</code>, so the reasoning itself "
            "never reaches the transcript — this archive can show that Claude thought at a given "
            "point, never what it thought. Nothing was lost in archiving.").format(
                n=f"{t.empty_thinking:,}"))
    if t.unresolved_tools:
        warn.append(_("{n} tool call(s) have no result in the source (still running, or "
                      "interrupted, when this file was written).").format(n=t.unresolved_tools))
    typed = len({" ".join(p.split()) for p in t.typed_prompts})
    humans = t.rendered_types.get("human turn", 0)
    if typed and abs(typed - humans) > 2:
        warn.append(_("{humans} human turns rendered vs {typed} distinct prompts in the session's "
                      "own <code>last-prompt</code> index &mdash; worth a look.").format(
                          humans=humans, typed=typed))
    # Only claim self-archiving when the source is still being written; archiving a
    # finished session from a different session is the common case.
    ends = sorted(parse_ts(x) for x in t.timestamps)
    last_record = ends[-1] if ends else None
    live = bool(last_record) and (archived_at - last_record).total_seconds() < 600
    if last_record is None:
        warn.append(_("No record in the source carries a timestamp, so when the conversation "
                      "happened cannot be established from this file."))
    elif live:
        warn.append(_("This archive was written while the session was still active, so records "
                      "created after {when} are not in it. Re-run to refresh.").format(
                          when=esc(fmt_local(archived_at))))
    else:
        warn.append(_("Snapshot taken {when}; the source's last record is {last}. Anything "
                      "written to the session after that is not in this file. Re-run to "
                      "refresh.").format(when=esc(fmt_local(archived_at)),
                                         last=esc(fmt_local(last_record))))

    L = {
        "title": _("Fidelity report"),
        "lead": _("Every record in the source, and what happened to it. Nothing is dropped "
                  "silently: a record is either rendered below, folded into an earlier turn, or "
                  "counted here as deliberately not rendered."),
        "disposition": _("Record disposition"),
        "by_type": _("Source records by type"),
        "blocks": _("Content blocks"),
        "rendered": _("Rendered ({n} turns)").format(n=f"{rendered:,}"),
        "counted": _("Counted, not rendered ({n})").format(n=f"{counted:,}"),
        "evidence": _("Human-vs-injected evidence"),
        "evidence_note": _("Which signal classified each string-content user record. "
                           "<code>promptSource</code> and <code>origin.kind</code> are "
                           "authoritative; the rest are fallbacks for older records."),
        "caveats": _("Caveats"),
        "source": _("Source: <code>{path}</code> &middot; archiver v{version}").format(
            path=esc(str(path)), version=VERSION),
    }
    return f"""
<section class="turn report-turn" id="fidelity">
  <div class="turn-label"><span class="who">{L["title"]}</span></div>
  <div class="turn-body report-body">
    <p>{L["lead"]}</p>
    <h4>{L["disposition"]}</h4>
    {disposition_html}
    <div class="report-grid">
      <div>
        <h4>{L["by_type"]}</h4>
        <div class="table-wrap"><table class="mini"><tbody>{rows(t.record_types)}</tbody></table></div>
        <h4>{L["blocks"]}</h4>
        <div class="table-wrap"><table class="mini"><tbody>{rows(t.blocks)}</tbody></table></div>
      </div>
      <div>
        <h4>{L["rendered"]}</h4>
        <div class="table-wrap"><table class="mini"><tbody>{rows(t.rendered_types)}</tbody></table></div>
        <h4>{L["counted"]}</h4>
        <div class="table-wrap"><table class="mini"><tbody>{rows(t.counted_only)}</tbody></table></div>
      </div>
    </div>
    <h4>{L["evidence"]}</h4>
    <p class="muted small">{L["evidence_note"]}</p>
    <div class="table-wrap"><table class="mini"><tbody>{rows(t.classification)}</tbody></table></div>
    {subagent_block(agents, subagents_on)}
    <h4>{L["caveats"]}</h4>
    <ul>{''.join(f'<li>{w}</li>' for w in warn)}</ul>
    <p class="muted small">{L["source"]}</p>
  </div>
</section>"""


def assign_tags(t: Transcript, prefix: str = "") -> None:
    """Give every prompt and response a citable id: P1, P2, ... / R1, R2, ...

    Sequential within one transcript; subagent transcripts get a prefix
    (A1., A2., ...) so a tag is unique across the whole document and main
    text can say "in prompt P32" or "in response A2.R4" unambiguously."""
    p = r = 0
    for turn in t.turns:
        if turn["kind"] == "human":
            p += 1
            turn["tag"] = f"{prefix}P{p}"
        elif turn["kind"] == "assistant":
            r += 1
            turn["tag"] = f"{prefix}R{r}"


def subagent_block(agents: list, subagents_on: bool) -> str:
    """Fidelity-report table of the session's subagent transcript files.

    Listed whether or not they are rendered: an omitted transcript the report
    does not mention would be exactly the silent drop this tool exists to
    prevent."""
    if not agents:
        return ""
    note = (_("Rendered in full in the Subagent transcripts section below.")
            if subagents_on else
            _("<strong>Not rendered</strong> (--subagents off) — listed here so the omission is "
              "on the record. Their token usage is still counted above."))
    rows = "".join(
        f"<tr><td><code>agent-{esc(aid)}</code></td>"
        f"<td class=num>{sum(at.record_types.values()):,}</td>"
        f"<td class=num>{len(at.turns):,}</td></tr>"
        for aid, _af, at in agents)
    return (f"<h4>{_('Subagent transcripts ({n})').format(n=len(agents))}</h4>"
            f'<p class="muted small">{note}</p>'
            '<div class="table-wrap"><table class="mini"><tbody>'
            f"<tr><th>{_('file')}</th><th>{_('records')}</th><th>{_('turns')}</th></tr>"
            f"{rows}</tbody></table></div>")


def render_turns(t: Transcript, anchor_prefix: str = "",
                 agent_href: dict | None = None
                 ) -> tuple[list, list[tuple[str, str, str]]]:
    """-> (units, toc): one (html, anchor-or-None) unit per turn, so a caller
    can join them into one page or chunk them across several."""
    body: list[str] = []
    anchors: list = []
    toc: list[tuple[str, str, str]] = []
    counter = 0

    for turn in t.turns:
        kind = turn["kind"]
        cur_anchor = None
        ts_attr = ""
        ts_disp = ""
        if turn.get("ts"):
            dt = parse_ts(turn["ts"])
            ts_disp = fmt_local(dt)
            ts_attr = f' title="{fmt_utc(dt)}"'

        if kind == "human":
            counter += 1
            anchor = f"{anchor_prefix}turn-{counter}"
            cur_anchor = anchor
            tag = turn.get("tag", "")
            tag_html = f' <span class="rtag" id="{esc(tag)}">{esc(tag)}</span>' if tag else ""
            toc.append((anchor, (f"{tag} · " if tag else "") + truncate(turn["text"], 66), "human"))
            body.append(f"""
<section class="turn human-turn" id="{anchor}" data-lane="human">
  <div class="turn-label"><span class="who">{_("Human")}{tag_html}</span><span class="ts"{ts_attr}>{ts_disp}</span></div>
  <div class="turn-body">{turn["html"]}</div>
</section>""")

        elif kind == "system":
            counter += 1
            anchor = f"{anchor_prefix}turn-{counter}"
            cur_anchor = anchor
            toc.append((anchor, _(turn["badge"]), "system"))
            ev = f'<span class="evidence" title="{_("how this was classified")}">{esc(turn.get("evidence", ""))}</span>'
            body.append(f"""
<section class="turn system-turn" id="{anchor}" data-lane="system">
  <div class="turn-label"><span class="who">{_("System")}</span><span class="badge">{esc(_(turn["badge"]))}</span>{ev}<span class="ts"{ts_attr}>{ts_disp}</span></div>
  <div class="turn-body"><details><summary>{esc(truncate(turn["text"], 110))}</summary><pre class="plain">{esc(turn["text"])}</pre></details></div>
</section>""")

        elif kind == "system_record":
            counter += 1
            anchor = f"{anchor_prefix}turn-{counter}"
            cur_anchor = anchor
            label = _(turn["badge"]) + (f" — {turn['detail']}" if turn.get("detail") else "")
            toc.append((anchor, label, "system"))
            body_html = (f'<pre class="plain">{esc(turn["text"])}</pre>' if turn["text"] else "")
            body.append(f"""
<section class="turn event-turn" id="{anchor}" data-lane="system">
  <div class="turn-label"><span class="who">{_("Event")}</span><span class="badge">{esc(_(turn["badge"]))}</span><span class="evidence">{esc(turn.get("detail", ""))}</span><span class="ts"{ts_attr}>{ts_disp}</span></div>
  <div class="turn-body">{body_html}</div>
</section>""")

        elif kind == "assistant":
            side = f' <span class="badge side">{_("subagent")}</span>' if turn.get("sidechain") else ""
            tag = turn.get("tag", "")
            tag_html = f' <span class="rtag" id="{esc(tag)}">{esc(tag)}</span>' if tag else ""
            body.append(f"""
<section class="turn assistant-turn" data-lane="assistant">
  <div class="turn-label"><span class="who">Claude{tag_html}</span>{side}<span class="ts"{ts_attr}>{ts_disp}</span></div>
  <div class="turn-body">{turn["html"]}</div>
</section>""")

        elif kind == "thinking":
            body.append(f"""
<section class="turn thinking-turn" data-lane="thinking">
  <details>
    <summary><span class="who">{_("Thinking")}</span><span class="ts"{ts_attr}>{ts_disp}</span></summary>
    <div class="turn-body">{turn["html"]}</div>
  </details>
</section>""")

        elif kind == "user_image":
            body.append(f"""
<section class="turn human-turn" data-lane="human">
  <div class="turn-label"><span class="who">{_("Human")}</span><span class="badge">{_("pasted image")}</span><span class="ts"{ts_attr}>{ts_disp}</span></div>
  <div class="turn-body"><img loading="lazy" src="data:{esc(turn["media"])};base64,{esc(turn["data"])}" alt="{_("pasted image")}"></div>
</section>""")

        elif kind == "harness":
            detail = f'<span class="evidence">{esc(turn.get("detail", ""))}</span>' if turn.get("detail") else ""
            inner = f'<pre class="plain">{esc(turn["text"])}</pre>' if turn["text"] else f"<p class=muted>{_('(no content)')}</p>"
            body.append(f"""
<section class="turn harness-turn" data-lane="harness">
  <details>
    <summary><span class="chip harness-chip">{_("harness")}</span> {esc(_(turn["badge"]))} {detail}<span class="ts"{ts_attr}>{ts_disp}</span></summary>
    <div class="io">{inner}</div>
  </details>
</section>""")

        elif kind == "tool":
            classes = "tool-turn"
            if turn["is_error"]:
                classes += " tool-error"
            if not turn["resolved"]:
                classes += " tool-pending"
            side = f' <span class="badge side">{_("subagent")}</span>' if turn.get("sidechain") else ""
            # Link only to transcripts that are actually on this page; an
            # agent id with no discovered file would be a dead anchor.
            if agent_href and turn.get("agent_id") in agent_href:
                side += (f' <a class="badge side" href="{esc(agent_href[turn["agent_id"]])}">'
                         f"{_('transcript &darr;')}</a>")
            io = [f"""
      <div class="io-block"><div class="io-label">{_("Input")}</div>
        <pre class="plain">{esc(pretty_tool_input(turn["input"]))}</pre></div>"""]
            if turn["output_text"]:
                lbl = _("Output (error)") if turn["is_error"] else _("Output")
                extra = ""
                if turn.get("elided"):
                    extra = (' <span class="evidence">'
                             + _("{n} chars elided").format(n=f'{turn["elided"]:,}') + '</span>')
                io.append(f"""
      <div class="io-block"><div class="io-label">{lbl}{extra}</div>
        <pre class="plain">{esc(turn["output_text"])}</pre></div>""")
            elif turn["resolved"]:
                io.append(f'<div class="io-block"><div class="io-label">{_("Output")}</div>'
                          f'<p class="muted">{_("(empty result)")}</p></div>')
            else:
                io.append(f'<div class="io-block"><div class="io-label">{_("Output")}</div>'
                          '<p class="muted">'
                          + _("No result in the source &mdash; this call was still running (or was "
                              "interrupted) when the transcript was written.") + '</p></div>')
            for media, data in turn["output_images"]:
                io.append(f"""
      <div class="io-block"><div class="io-label">{_("Screenshot")}</div>
        <img loading="lazy" src="data:{esc(media)};base64,{esc(data)}" alt="{_("tool screenshot")}"></div>""")
            body.append(f"""
<section class="turn {classes}" data-lane="tool">
  <details>
    <summary><span class="chip tool-chip">{esc(turn["chip"])}</span> <code>{esc(turn["label"])}</code>{side}<span class="ts"{ts_attr}>{ts_disp}</span></summary>
    <div class="io">{''.join(io)}</div>
  </details>
</section>""")

        elif kind == "raw_block":
            body.append(f"""
<section class="turn harness-turn" data-lane="harness">
  <details>
    <summary><span class="chip harness-chip">{_("raw")}</span> {esc(_(turn["badge"]))}<span class="ts"{ts_attr}>{ts_disp}</span></summary>
    <div class="io"><pre class="plain">{esc(turn["text"])}</pre></div>
  </details>
</section>""")

        while len(anchors) < len(body):
            anchors.append(cur_anchor)

    return list(zip(body, anchors)), toc


def build(session_id: str, title: str, out_path: Path, summary_inner: str,
          projects_root: Path, follow_chain: bool, max_tool_output: int,
          formats: tuple = ("html",), fragment: bool = False,
          tool_output: str = "on", sessions: dict | None = None,
          subagents: str = "on", paginate: int = 0,
          source_kind: str | None = None) -> dict:
    # scan_sessions reads every .jsonl under the root; the caller usually has
    # the scan already, so reuse it rather than reading them all a second time.
    if sessions is None:
        sessions = scan_sessions(projects_root)
    if session_id not in sessions:
        sys.exit(f"No {session_id}.jsonl under {projects_root}")

    requested = session_id
    chain_best, related = resolve_chain(session_id, sessions)
    used = chain_best if follow_chain else session_id
    if follow_chain and used != requested:
        CON.note(f"note: {requested} is continued by {used} "
                 f"({len(sessions[used].uuids):,} conversation records vs "
                 f"{len(sessions[requested].uuids):,}); archiving {used}")

    path = sessions[used].path
    CON.detail(f"parsing {path}")
    t = parse_transcript(path, max_tool_output)
    archived_at = datetime.datetime.now(datetime.timezone.utc)

    # Subagent transcripts live beside the session at
    # <session-id>/subagents/agent-<id>.jsonl, in the same record schema, and
    # share no uuids with the parent file -- they are conversation the parent
    # only points at. Parse them all regardless of the --subagents flag: their
    # usage is real spend either way, and the fidelity report must list the
    # files even when their content is not rendered.
    #
    # A resumed session's continuation file repeats the records but the
    # subagent directory stays under the id that spawned them, so look beside
    # every file in the chain (the archived one, the requested one, and any
    # earlier/later half), deduplicating by agent id.
    agents: list[tuple[str, Path, Transcript]] = []
    chain_ids = [used, requested] + [r["session_id"] for r in related
                                      if r["relation"] in ("superset", "subset")]
    seen_agents: set[str] = set()
    for cid in chain_ids:
        if cid not in sessions:
            continue
        cpath = sessions[cid].path
        ag_dir = cpath.parent / cpath.stem / "subagents"
        if not ag_dir.is_dir():
            continue
        for af in sorted(ag_dir.glob("agent-*.jsonl")):
            aid = af.stem[len("agent-"):]
            if aid in seen_agents:
                continue
            seen_agents.add(aid)
            CON.detail(f"parsing subagent {af}")
            agents.append((aid, af, parse_transcript(af, max_tool_output)))
    # The cost meter is per process and a continuation file does not repeat
    # the earlier process's snapshots, so gather them from every file in the
    # chain. Keyed by startTime, duplicates collapse; the archived file wins.
    for cid in chain_ids:
        if cid in sessions and sessions[cid].path != path:
            for key, rec in cost_states_of(sessions[cid].path).items():
                t.cost_states.setdefault(key, rec)
    include_agents = subagents == "on"
    assign_tags(t)
    for _k, (_aid2, _af2, _at2) in enumerate(agents, 1):
        assign_tags(_at2, prefix=f"A{_k}.")
    for _aid, _af, at in agents:
        for model, agg in at.usage_by_model.items():
            for k, v in agg.items():
                t.usage_by_model[model][k] += v

    ts_dt = sorted(parse_ts(s) for s in t.timestamps)
    started, ended = (ts_dt[0], ts_dt[-1]) if ts_dt else (archived_at, archived_at)
    wall = ended - started

    if t.turn_duration_records:
        active = fmt_dur_ms(t.turn_durations_ms)
        active_note = _("summed from {n} turn_duration records").format(n=t.turn_duration_records)
    else:
        gap_cap = datetime.timedelta(minutes=20)
        acc = sum(((b - a) for a, b in zip(ts_dt, ts_dt[1:]) if (b - a) <= gap_cap),
                  datetime.timedelta())
        active = fmt_dur_ms(int(acc.total_seconds() * 1000))
        active_note = _("estimated (no turn_duration records; gaps over 20m ignored)")

    # ---- pagination layout, decided before any HTML is rendered ------------
    # Units: one per main turn, then (when rendered) one subagent header and
    # one per subagent block. Knowing each unit's page up front lets links to
    # a subagent transcript carry the right page file with no post-editing.
    n_turn_units = len(t.turns)
    have_blocks = bool(agents) and include_agents
    total_units = n_turn_units + (1 + len(agents) if have_blocks else 0)
    per_page = max(0, paginate)
    n_pages = max(1, -(-total_units // per_page)) if per_page else 1

    def page_of(unit_idx: int) -> int:
        return unit_idx // per_page + 1 if per_page else 1

    def page_file(k: int) -> str:
        return out_path.name if k == 1 else f"{out_path.stem}_p{k}.html"

    agent_href = {}
    if have_blocks:
        for i, (aid, _af, _at) in enumerate(agents):
            k = page_of(n_turn_units + 1 + i)
            agent_href[aid] = ("" if k == 1 else page_file(k)) + f"#subagent-{aid}"

    units, toc = render_turns(t, agent_href=agent_href)
    rc = reported_cost(t, started)
    usage_html, usage_totals = usage_table(t, started.date(), rc)
    if agents:
        usage_html += ('<p class="muted small">'
                       + _("Totals include {n} subagent transcript(s).").format(n=len(agents))
                       + '</p>')

    sub_toc: list[tuple[str, str, str]] = []
    if have_blocks:
        units.append((
            '<section class="turn report-turn" id="subagents">'
            f'<div class="turn-label"><span class="who">{_("Subagent transcripts")}</span></div>'
            '<div class="turn-body report-body"><p>'
            + _("Conversations run by background agents this session spawned. Each lives in its "
                "own file beside the session and is rendered here in full, with the same rules as "
                "the main transcript.")
            + '</p></div></section>', "subagents"))
        for k, (aid, af, at) in enumerate(agents, 1):
            inner_units, _toc = render_turns(at, anchor_prefix=f"sa-{aid}-")
            inner = "".join(h for h, _a in inner_units)
            n_rec = sum(at.record_types.values())
            sa_note = _("{records} records &middot; {turns} turns &middot; turns tagged A{k}.P/A{k}.R").format(
                records=f"{n_rec:,}", turns=f"{len(at.turns):,}", k=k)
            units.append((f"""
<section class="turn subagent-block" id="subagent-{esc(aid)}" data-lane="subagent">
  <details>
    <summary><span class="chip harness-chip">{_("subagent")}</span> <span class="rtag">A{k}</span> <code>agent-{esc(aid)}</code>
      <span class="evidence">{sa_note}</span></summary>
    <div class="subagent-body">{inner}</div>
  </details>
</section>""", f"subagent-{aid}"))
            sub_toc.append((f"subagent-{aid}", f"A{k} · agent-{aid[:8]}", "system"))

    chain_html = ""
    if related:
        items = []
        for r in related:
            mark = _(" (archived here)") if r["session_id"] == used else ""
            items.append(
                f"<li><code>{esc(r['session_id'][:8])}</code> &mdash; {r['relation']}, "
                + _("{shared} shared records, {records} total").format(
                    shared=f"{r['shared']:,}", records=f"{r['records']:,}")
                + f"{mark}</li>")
        chain_html = (
            '<div class="callout">'
            + _("<strong>This conversation spans more than one transcript file.</strong> A resumed "
                "or bridged session is written to a new <code>.jsonl</code> that repeats the "
                "earlier records, so the most complete file is the one archived here.")
            + f'<ul>{"".join(items)}</ul></div>')

    def info_row(k, v, title_attr=""):
        ta = f' title="{esc(title_attr)}"' if title_attr else ""
        return f"<dt>{esc(k)}</dt><dd{ta}>{v}</dd>"

    models_str = ", ".join(f"{esc(m)}" for m in sorted(t.models))
    session_info = "".join([
        info_row(_("Session ID"), f"<code>{esc(used)}</code>"),
        info_row(_("Requested"), f"<code>{esc(requested)}</code>") if used != requested else "",
        info_row(_("Started"), esc(fmt_local(started)), fmt_utc(started)),
        info_row(_("Last record"), esc(fmt_local(ended)), fmt_utc(ended)),
        info_row(_("Archived at"), esc(fmt_local(archived_at)), fmt_utc(archived_at)),
        info_row(_("Wall clock"), esc(fmt_dur_ms(int(wall.total_seconds() * 1000)))),
        info_row(_("Active time"), esc(active), active_note),
        info_row(_("Models"), models_str),
        info_row(_("Effort"), ", ".join(f"{k} ×{v}" for k, v in t.effort.most_common())) if t.effort else "",
        info_row("Claude Code", f"v{esc(t.version or '?')}"),
        info_row(_("Working dir"), f"<code>{esc(t.cwd or '')}</code>"),
        info_row(_("Human turns"), f"{t.rendered_types.get('human turn', 0):,}"),
        info_row(_("Claude messages"), f"{t.rendered_types.get('assistant text', 0):,}"),
        info_row(_("Thinking blocks"),
                 _("{with} with text, {empty} empty").format(
                     **{"with": f"{t.rendered_types.get('thinking', 0):,}",
                        "empty": f"{t.empty_thinking:,}"}),
                 _("Claude Code requests thinking with display=omitted, so the reasoning text is "
                   "never written to the transcript")),
        info_row(_("Tool calls"), f"{t.rendered_types.get('tool call', 0):,}"),
        info_row(_("Subagents"),
                 _("{n} transcript(s), {records} records").format(
                     n=len(agents),
                     records=f"{sum(sum(at.record_types.values()) for _a, _f, at in agents):,}")
                 + ("" if include_agents else _(" (not rendered: --subagents off)")))
        if agents else "",
        info_row(_("Harness events"),
                 f"{sum(v for k, v in t.rendered_types.items() if k.startswith(('harness', 'system'))):,}"),
        info_row(_("Output tokens"), f"{usage_totals['output']:,}"),
        info_row(_("Cache reads"), f"{usage_totals['cache_read']:,}"),
        info_row(_("List cost"), f"${usage_totals['cost']:,.2f}"),
        info_row(_("Reported cost"),
                 _("${usd} reported by Claude Code ({runs} run(s){partial})").format(
                     usd=f"{rc['usd']:,.2f}", runs=rc["runs"],
                     partial=_(", partial: earlier runs not covered") if rc["partial"] else ""))
        if rc else "",
        info_row(_("Compactions"), f"{len(t.compactions):,}") if t.compactions else "",
        info_row(_("Harness retractions"), esc("; ".join(
            _("{n} message(s) after a safeguard refusal at {time} UTC, {src} -> {dst}").format(
                n=r["retracted"], time=(r["ts"] or "")[11:19], src=r["from"], dst=r["to"])
            + (_(", {n} absent from the source").format(n=r["absent"]) if r["absent"] else "")
            for r in t.retractions))) if t.retractions else "",
        info_row(_("Skills used"), esc(", ".join(sorted(t.skills)))) if t.skills else "",
    ])

    anchor_page = {"summary": 1, "usage": 1, "fidelity": 1}
    for i, (_h, a) in enumerate(units):
        if a:
            anchor_page[a] = page_of(i)

    def href_to(anchor: str, cur_page: int) -> str:
        p = anchor_page.get(anchor, 1)
        return f"#{anchor}" if p == cur_page else f"{page_file(p)}#{anchor}"

    def toc_for(cur_page: int) -> str:
        items = [
            f'<a href="{href_to("summary", cur_page)}" class="toc-item toc-key">{_("Session summary")}</a>',
            f'<a href="{href_to("usage", cur_page)}" class="toc-item toc-key">{_("Usage &amp; cost")}</a>',
            f'<a href="{href_to("fidelity", cur_page)}" class="toc-item toc-key">{_("Fidelity report")}</a>']
        for anchor, label, cls in toc + sub_toc:
            items.append(f'<a href="{href_to(anchor, cur_page)}" '
                         f'class="toc-item toc-{cls}">{esc(label)}</a>')
        return "\n".join(items)

    def nav_for(cur_page: int) -> str:
        if n_pages == 1:
            return ""
        parts = [_("Page {cur} of {n}").format(cur=cur_page, n=n_pages)]
        if cur_page > 1:
            parts.append(f'<a href="{page_file(cur_page - 1)}">{_("&larr; prev")}</a>')
        for k in range(1, n_pages + 1):
            parts.append(f"<strong>{k}</strong>" if k == cur_page
                         else f'<a href="{page_file(k)}">{k}</a>')
        if cur_page < n_pages:
            parts.append(f'<a href="{page_file(cur_page + 1)}">{_("next &rarr;")}</a>')
        return '<nav class="page-nav">' + " &middot; ".join(parts) + "</nav>"

    meta = {
        "archiver_version": VERSION,
        "lang": LANG,
        "session_id": used,
        "requested_session_id": requested,
        "title": title,
        "started": started.isoformat(),
        "last_record": ended.isoformat(),
        "archived_at": archived_at.isoformat(),
        "source": str(path),
        "source_kind": source_kind or sessions[used].source,
        "records": sum(t.record_types.values()),
        "human_turns": t.rendered_types.get("human turn", 0),
        "assistant_messages": t.rendered_types.get("assistant text", 0),
        "thinking_blocks": t.rendered_types.get("thinking", 0),
        "tool_calls": t.rendered_types.get("tool call", 0),
        "output_tokens": usage_totals["output"],
        "cache_read_tokens": usage_totals["cache_read"],
        "list_cost_usd": round(usage_totals["cost"], 4),
        "reported_cost_usd": round(rc["usd"], 4) if rc else None,
        "reported_cost_runs": rc["runs"] if rc else 0,
        "reported_cost_partial": rc["partial"] if rc else None,
        "lines_added": rc["lines_added"] if rc else None,
        "lines_removed": rc["lines_removed"] if rc else None,
        "models": sorted(t.models),
        "chain": related,
        "subagents": [{"agent_id": aid,
                       "records": sum(at.record_types.values()),
                       "turns": len(at.turns),
                       "rendered": include_agents}
                      for aid, _af, at in agents],
        "pages": [page_file(k) for k in range(1, n_pages + 1)],
    }

    subtitle = (_("{start} – {end} · {humans} human turns · {tools} tool calls · ").format(
                    start=fmt_local(started), end=fmt_local(ended),
                    humans=t.rendered_types.get("human turn", 0),
                    tools=t.rendered_types.get("tool call", 0))
                + (_("${usd} reported by Claude Code").format(usd=f"{rc['usd']:,.2f}")
                   if rc and not rc["partial"] else
                   _("${usd} at list price").format(usd=f"{usage_totals['cost']:,.2f}")))

    lead_html = (chain_html
                 + '<section class="turn summary-turn" id="summary">'
                   f'<div class="turn-label"><span class="who">{_("Session summary")}</span></div>'
                   f'<div class="turn-body summary-body">{summary_inner}</div></section>'
                 + '<section class="turn usage-turn" id="usage">'
                   f'<div class="turn-label"><span class="who">{_("Usage &amp; cost")}</span></div>'
                   f'<div class="turn-body usage-body">{usage_html}</div></section>'
                 + fidelity_section(t, path, archived_at, agents=agents,
                                    subagents_on=include_agents))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = []
    if "html" in formats:
        # CSS and JS ride in as .format *values*: format never scans values
        # for braces or fields, so neither their own braces nor any
        # placeholder-looking text inside the transcript body can trigger a
        # second substitution. "</" is escaped in the embedded JSON ("<\/" is
        # valid JSON) so a title containing "</script>" cannot terminate the
        # metadata block early.
        for k in range(1, n_pages + 1):
            chunk = (units[(k - 1) * per_page: k * per_page] if per_page
                     else units)
            page = _TEMPLATE.format(
                title=esc(title) + (_(" — page {k}/{n}").format(k=k, n=n_pages) if n_pages > 1 else ""),
                lang=LANG,
                i18n_json=json.dumps({
                    "light": _("Light theme"), "dark": _("Dark theme"),
                    "match": _("{shown} of {total} turns match")}, ensure_ascii=False
                    ).replace("</", "<\\/"),
                shell=_shell_words(),
                session_info=session_info,
                toc_html=toc_for(k),
                page_nav=nav_for(k),
                lead_html=lead_html if k == 1 else "",
                body_html="\n".join(h for h, _a in chunk),
                meta_json=(json.dumps(meta, ensure_ascii=False)
                           if k == 1 else
                           json.dumps({"continuation_of": used, "page": k},
                                      ensure_ascii=False)
                           ).replace("</", "<\\/"),
                subtitle=esc(subtitle),
                css=_CSS,
                js=_JS,
            )
            q = out_path if k == 1 else out_path.with_name(page_file(k))
            q.write_text(page, encoding="utf-8")
            written.append((q, len(page)))

    ctx = {"title": title, "session_id": used, "subtitle": subtitle,
           "summary_text": html_fragment_to_text(summary_inner) if summary_inner else "",
           "cost_note": reported_cost_note(rc)}

    # Format and tool-output are independent: the script does not infer one from
    # the other. Tool arguments are pretty-printed wherever they appear, so this
    # is purely a question of length -- full I/O turns a 1,600-record session
    # into a several-hundred-page PDF.
    include_io = tool_output == "on"

    if "text" in formats:
        body = emit_text(t, ctx, tool_output=include_io, agents=agents,
                         subagents_on=include_agents)
        q = out_path.with_suffix(".txt")
        q.write_text(body, encoding="utf-8")
        written.append((q, len(body)))

    if "markdown" in formats:
        body = emit_markdown(t, ctx, tool_output=include_io, agents=agents,
                             subagents_on=include_agents)
        q = out_path.with_suffix(".md")
        q.write_text(body, encoding="utf-8")
        written.append((q, len(body)))

    if "latex" in formats or "pdf" in formats:
        src, tally = emit_latex(t, ctx, fragment=fragment,
                                tool_output=include_io, agents=agents,
                                subagents_on=include_agents)
        stem = out_path.stem + ("_fragment" if fragment else "")
        q = out_path.with_name(stem + ".tex")
        q.write_text(src, encoding="utf-8")
        written.append((q, len(src)))
        if tally["glyphs"] or tally["controls"]:
            CON.say(f"  note: LaTeX rendering dropped {tally['glyphs']:,} unsettable glyphs "
                    f"and {tally['controls']:,} control bytes (recorded in the document)")
        if "pdf" in formats:
            if fragment:
                sys.exit("--fragment cannot be compiled: it has no preamble. "
                         "Drop --fragment to build a PDF.")
            CON.detail(f"compiling {q.name} with xelatex (two passes)")
            pdf = compile_pdf(q)
            written.append((pdf, pdf.stat().st_size))
            if "latex" not in formats:
                q.unlink(missing_ok=True)
                written = [w for w in written if w[0] != q]

    for q, size in written:
        CON.say(f"wrote {q} ({size / 1e6:.2f} MB)")
    CON.say(f"  human={t.rendered_types.get('human turn', 0)} "
            f"assistant={t.rendered_types.get('assistant text', 0)} "
            f"thinking={t.rendered_types.get('thinking', 0)} "
            f"tools={t.rendered_types.get('tool call', 0)} "
            f"harness={sum(v for k, v in t.rendered_types.items() if k.startswith('harness'))} "
            f"events={sum(v for k, v in t.rendered_types.items() if k.startswith('system'))}")
    CON.say(f"  records={sum(t.record_types.values())} rendered={sum(t.rendered_types.values())} "
            f"counted-only={sum(t.counted_only.values())} unresolved-tools={t.unresolved_tools}")
    if agents:
        CON.say(f"  subagents={len(agents)} transcript(s), "
                f"{sum(sum(at.record_types.values()) for _a, _f, at in agents)} records"
                + ("" if include_agents else " (not rendered: --subagents off)"))
    CON.say(f"  output={usage_totals['output']:,} tok  cache-read={usage_totals['cache_read']:,} tok  "
            f"list-cost=${usage_totals['cost']:,.2f}"
            + (f"  reported=${rc['usd']:,.2f} ({rc['runs']} run(s)"
               f"{', partial' if rc['partial'] else ''})" if rc else ""))
    disp = t.disposition
    if disp["rendered"] + disp["folded"] + disp["counted"] != sum(t.record_types.values()):
        CON.note("warning: fidelity report does not reconcile -- a record class is "
                 "escaping the parser; the page says so")
    for k, v in t.counted_only.items():
        if k.startswith("unhandled record type"):
            CON.note(f"warning: {v} record(s) of an unhandled type were counted, not rendered: {k}")
    if t.retractions:
        n = sum(r["retracted"] for r in t.retractions)
        a = sum(r["absent"] for r in t.retractions)
        CON.note(f"  note: {n} message(s) retracted by the harness after a safeguard refusal"
                 + (f", {a} absent from the source" if a else "") + " (recorded in the document)")
    return meta


# ---------------------------------------------------------------------------
# Alternate output formats
#
# All of these render from the same parsed Transcript the HTML uses, so a turn
# cannot appear in one format and vanish from another. Each states what its own
# medium cannot carry -- the no-silent-drops contract applies per format, not
# just to the HTML.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Engine-neutral transliteration (--fragment)
#
# The standalone document is XeLaTeX and sets Unicode as itself. A fragment is
# different: it is \input into someone else's manuscript, and that manuscript
# picks the engine. pdflatex is 8-bit and stops the run on any character it has
# no declaration for -- across this machine's 37 conversations that is 209
# distinct characters, 14,962 occurrences, including the Greek that carries the
# physics. So a fragment transliterates.
#
# Two targets, because they have different rules:
#   prose    -- math mode is available, so Gamma becomes $\Gamma$
#   verbatim -- no macros, no math, no escapes at all: pure ASCII
# ---------------------------------------------------------------------------

_GREEK_NAMES = {
    0x391: "Alpha", 0x392: "Beta", 0x393: "Gamma", 0x394: "Delta",
    0x395: "Epsilon", 0x396: "Zeta", 0x397: "Eta", 0x398: "Theta",
    0x399: "Iota", 0x39A: "Kappa", 0x39B: "Lambda", 0x39C: "Mu",
    0x39D: "Nu", 0x39E: "Xi", 0x39F: "Omicron", 0x3A0: "Pi",
    0x3A1: "Rho", 0x3A3: "Sigma", 0x3A4: "Tau", 0x3A5: "Upsilon",
    0x3A6: "Phi", 0x3A7: "Chi", 0x3A8: "Psi", 0x3A9: "Omega",
    0x3B1: "alpha", 0x3B2: "beta", 0x3B3: "gamma", 0x3B4: "delta",
    0x3B5: "epsilon", 0x3B6: "zeta", 0x3B7: "eta", 0x3B8: "theta",
    0x3B9: "iota", 0x3BA: "kappa", 0x3BB: "lambda", 0x3BC: "mu",
    0x3BD: "nu", 0x3BE: "xi", 0x3BF: "omicron", 0x3C0: "pi",
    0x3C1: "rho", 0x3C3: "sigma", 0x3C4: "tau", 0x3C5: "upsilon",
    0x3C6: "phi", 0x3C7: "chi", 0x3C8: "psi", 0x3C9: "omega",
    0x3C2: "varsigma",
}

# ASCII-only, safe inside Verbatim.
_ASCII_MAP = {
    "\u2192": "->", "\u2190": "<-", "\u2194": "<->", "\u21d2": "=>",
    "\u21d0": "<=", "\u21d4": "<=>", "\u2191": "^", "\u2193": "v",
    "\u2248": "~=", "\u2260": "!=", "\u2264": "<=", "\u2265": ">=",
    "\u00b1": "+/-", "\u00d7": "x", "\u00f7": "/", "\u2212": "-",
    "\u221e": "inf", "\u2211": "sum", "\u220f": "prod", "\u222b": "int",
    "\u221a": "sqrt", "\u2202": "d", "\u2207": "grad", "\u2208": "in",
    "\u2209": "notin", "\u2282": "subset", "\u2286": "subseteq",
    "\u222a": "union", "\u2229": "intersect", "\u2205": "empty",
    "\u2261": "===", "\u221d": "prop", "\u22c5": ".", "\u00b7": ".",
    "\u2022": "*", "\u25e6": "o", "\u25aa": "-", "\u25cf": "*", "\u25cb": "o",
    "\u2713": "[ok]", "\u2714": "[ok]", "\u2705": "[ok]",
    "\u2717": "[x]", "\u2718": "[x]", "\u274c": "[x]", "\u2611": "[x]",
    "\u2612": "[x]", "\u26a0": "[!]", "\u2757": "[!]", "\u2139": "[i]",
    "\u2026": "...", "\u2013": "-", "\u2014": "--", "\u2018": "'",
    "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " ",
    "\u23af": "-", "\u2500": "-", "\u2501": "=", "\u2502": "|", "\u2503": "|",
    "\u250c": "+", "\u2510": "+", "\u2514": "+", "\u2518": "+",
    "\u251c": "+", "\u2524": "+", "\u252c": "+", "\u2534": "+", "\u253c": "+",
    "\u2550": "=", "\u2551": "|", "\u2554": "+", "\u2557": "+",
    "\u255a": "+", "\u255d": "+", "\u2560": "+", "\u2563": "+",
    "\u2566": "+", "\u2569": "+", "\u256c": "+",
    "\u2588": "#", "\u2589": "#", "\u258c": "#", "\u2590": "#",
    "\u2580": "#", "\u2584": "#", "\u2591": ".", "\u2592": ":", "\u2593": "#",
    "\u00b0": "deg", "\u00b5": "u", "\u2032": "'", "\u2033": '"',
    "\ufffd": "?", "\u200b": "", "\ufeff": "",
}
_SUPER = {"\u2070": "0", "\u00b9": "1", "\u00b2": "2", "\u00b3": "3",
          "\u2074": "4", "\u2075": "5", "\u2076": "6", "\u2077": "7",
          "\u2078": "8", "\u2079": "9", "\u207a": "+", "\u207b": "-",
          "\u207f": "n", "\u2071": "i"}
_SUB = {"\u2080": "0", "\u2081": "1", "\u2082": "2", "\u2083": "3",
        "\u2084": "4", "\u2085": "5", "\u2086": "6", "\u2087": "7",
        "\u2088": "8", "\u2089": "9", "\u208a": "+", "\u208b": "-"}

# Prose versions can use real math.
_MATH_MAP = {
    "\u2192": r"$\rightarrow$", "\u2190": r"$\leftarrow$",
    "\u2194": r"$\leftrightarrow$", "\u21d2": r"$\Rightarrow$",
    "\u21d0": r"$\Leftarrow$", "\u21d4": r"$\Leftrightarrow$",
    "\u2191": r"$\uparrow$", "\u2193": r"$\downarrow$",
    "\u2248": r"$\approx$", "\u2260": r"$\neq$", "\u2264": r"$\leq$",
    "\u2265": r"$\geq$", "\u00b1": r"$\pm$", "\u00d7": r"$\times$",
    "\u00f7": r"$\div$", "\u2212": r"$-$", "\u221e": r"$\infty$",
    "\u2211": r"$\sum$", "\u220f": r"$\prod$", "\u222b": r"$\int$",
    "\u221a": r"$\sqrt{\ }$", "\u2202": r"$\partial$", "\u2207": r"$\nabla$",
    "\u2208": r"$\in$", "\u2209": r"$\notin$", "\u2282": r"$\subset$",
    "\u2286": r"$\subseteq$", "\u222a": r"$\cup$", "\u2229": r"$\cap$",
    "\u2205": r"$\emptyset$", "\u2261": r"$\equiv$", "\u221d": r"$\propto$",
    "\u22c5": r"$\cdot$", "\u00b7": r"$\cdot$", "\u2022": r"$\bullet$",
    "\u2026": r"\ldots{}", "\u2013": "--", "\u2014": "---",
    "\u00b0": r"$^\circ$", "\u00b5": r"$\mu$", "\u2032": r"$'$",
}


def _greek(ch, verbatim):
    name = _GREEK_NAMES.get(ord(ch))
    if not name:
        return None
    return name if verbatim else "$\\" + name + "$"


def transliterate(s: str, tally, verbatim: bool) -> str:
    """Reduce text to what any TeX engine can set.

    verbatim=True yields pure ASCII (no macros survive a Verbatim body);
    verbatim=False may use math mode, which reads far better in prose.
    """
    # Collapse runs first: 10⁻⁶ should become 10$^{-6}$, not 10$^{-}$$^{6}$.
    def _run(m, table, mark):
        tally["transliterated"] += len(m.group(0))
        body = "".join(table[c] for c in m.group(0))
        return mark + body if verbatim else "$" + mark + "{" + body + "}$"

    s = re.sub("[" + "".join(_SUPER) + "]+",
               lambda m: _run(m, _SUPER, "^"), s)
    s = re.sub("[" + "".join(_SUB) + "]+",
               lambda m: _run(m, _SUB, "_"), s)

    out = []
    for ch in s:
        cp = ord(ch)
        if cp < 0x80:
            out.append(ch)
            continue
        g = _greek(ch, verbatim)
        if g is not None:
            tally["transliterated"] += 1
            out.append(g)
            continue
        table = _ASCII_MAP if verbatim else {**_ASCII_MAP, **_MATH_MAP}
        if ch in table:
            tally["transliterated"] += 1
            out.append(table[ch])
            continue
        if ch in _SUPER:
            tally["transliterated"] += 1
            out.append("^" + _SUPER[ch] if verbatim else "$^{" + _SUPER[ch] + "}$")
            continue
        if ch in _SUB:
            tally["transliterated"] += 1
            out.append("_" + _SUB[ch] if verbatim else "$_{" + _SUB[ch] + "}$")
            continue
        # Accented Latin: keep the base letter rather than lose the word.
        decomposed = unicodedata.normalize("NFD", ch)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        if stripped and all(ord(c) < 0x80 for c in stripped):
            if stripped != ch:
                tally["transliterated"] += 1
            out.append(stripped)
            continue
        tally["glyphs"] += 1
    return "".join(out)


_ANSI_RE = re.compile("\x1b\\[[0-9;?]*[a-zA-Z]")
_TEX_SPECIALS = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$",
                 "&": r"\&", "#": r"\#", "^": r"\textasciicircum{}",
                 "_": r"\_", "~": r"\textasciitilde{}", "%": r"\%"}


_TEX_ACCENT = {"\u0301": "'", "\u0300": "`", "\u0302": "^", "\u0303": "~",
               "\u0308": '"', "\u0327": "c"}
_TEX_LIGATURE = {"ß": "\\ss{}", "œ": "\\oe{}", "Œ": "\\OE{}", "æ": "\\ae{}", "Æ": "\\AE{}",
                 "ª": "\\textordfeminine{}", "º": "\\textordmasculine{}"}


def tex_accents(s: str) -> str:
    """Accented Latin letters as accent macros (\\'{e}, \\"{a}, \\c{c}, \\ss{}),
    so the archiver's own words survive pdflatex unchanged; anything else
    above ASCII is transliterated without touching the caller's tally.
    Applied after escaping: the macros it emits must not be escaped again."""
    out = []
    for ch in s:
        if ord(ch) < 0x80:
            out.append(ch)
            continue
        if ch in _TEX_LIGATURE:
            out.append(_TEX_LIGATURE[ch])
            continue
        d = unicodedata.normalize("NFD", ch)
        if len(d) == 2 and d[1] in _TEX_ACCENT and ord(d[0]) < 0x80:
            m = _TEX_ACCENT[d[1]]
            out.append("\\c{" + d[0] + "}" if m == "c" else "\\" + m + "{" + d[0] + "}")
            continue
        out.append(transliterate(ch, Counter(), verbatim=False))
    return "".join(out)


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def tex_escape(s: str) -> str:
    return "".join(_TEX_SPECIALS.get(ch, ch) for ch in s)


_TEX_CHAR_MAP = {"\u2713": "[ok]", "\u2714": "[ok]", "\u2717": "[x]",
                 "\u2718": "[x]", "\u2611": "[x]", "\u2612": "[x]"}


def tex_drop_unprintable(s: str, tally) -> str:
    """Remove codepoints no TeX font on this machine can set.

    Missing glyphs are only warnings to XeTeX, but emoji render as blanks and
    astral-plane characters can upset the shaper. They are counted so the
    document can say how many it dropped instead of dropping them quietly.
    """
    out = []
    for ch in s:
        if ch in _TEX_CHAR_MAP:
            out.append(_TEX_CHAR_MAP[ch])
            continue
        cp = ord(ch)
        # C0/C1 control bytes. Real tool output carries them: a Windows command
        # emitting UTF-16LE, captured byte-wise, interleaves a NUL between every
        # letter (1,701 of them in one session), and backspaces show up in
        # progress output. A browser ignores them in a text node; TeX stops with
        # "Text line contains an invalid character".
        if (cp < 0x20 and ch not in "\n\t") or 0x7F <= cp <= 0x9F:
            tally["controls"] += 1
            continue
        if cp >= 0x1F000 or 0xFE00 <= cp <= 0xFE0F or cp == 0x200D:
            tally["glyphs"] += 1
            continue
        out.append(ch)
    return "".join(out)


def tex_inline(s: str, tally, neutral: bool = False) -> str:
    """Markdown inline spans -> LaTeX, applied after escaping."""
    s = tex_drop_unprintable(strip_ansi(s), tally)
    # Escape BEFORE transliterating. tex_escape only rewrites ASCII specials and
    # transliterate only rewrites characters above U+007F, so the two never
    # touch the same character and the order is safe. Doing it the other way
    # round meant the emitted math had to be shielded from the escaper by a
    # regex -- and that regex could not tell a macro this code generated from a
    # literal \mathbf{r} quoted in the transcript, so real prose about LaTeX
    # escaped unescaped and stopped the compile.
    s = tex_escape(s)
    if neutral:
        s = transliterate(s, tally, verbatim=False)
    s = s.replace("\\textbackslash{}", "\\textbackslash{}\\allowbreak{}")
    # Never inside math: a transliterated subscript is $_{12}$, and an
    # \allowbreak between the "_" and its brace stops pdflatex.
    s = re.sub(r"(?<=[/_])(?!\{)(?=[^\s/_]{6})", lambda m: "\\allowbreak{}", s)
    s = re.sub(r"`([^`]+)`", r"\\texttt{\1}", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\\emph{\1}", s)
    return s


_TEX_HARD_WRAP = 500

# A breakable tcolorbox first typesets its whole content into one box, so a
# single enormous verbatim turn exhausts TeX's main memory: on the real
# archive a 9,614-line paste failed with "TeX capacity exceeded" while 4,000
# lines in one box compiled and the same paste as consecutive 1,500-line
# boxes compiled. Turns beyond this many (wrapped) lines are split into
# consecutive boxes titled "(part k/n)", and the document says so.
_TEX_BOX_MAX_LINES = 1500

# Prose is set at the box's own measure, not hard-wrapped like verbatim, so an
# _Atomic block's typeset height is its character count over roughly this many
# characters a line -- not its newline count. Costing a paragraph by newlines
# alone let one 300,000-character reply cost two lines and claim a whole box.
# The figure runs a little short of the real measure on purpose: LaTeX markup
# inflates the source, and over-costing only buys an extra box, while
# under-costing buys "TeX capacity exceeded".
_TEX_PROSE_WRAP = 100

# A tabular cannot break across a page and takes its width from its content,
# so a long or wide markdown table silently loses whatever runs past the paper
# (measured: 300 rows -> 0 survived; 12 columns -> 35 of 60 cells off the
# right edge, xelatex exiting 0 either way). Tables are cut into chunks of at
# most this many typeset rows -- consecutive tabulars a breakable box can
# break between -- and get wrapping p-columns when their natural width does
# not fit the line.
_TEX_TABLE_MAX_LINES = 30
_TEX_TABLE_LINE_CHARS = 90


class _Atomic(str):
    """A block already rendered to LaTeX (a paragraph, list, table) that a
    box split may not cut; it costs its typeset height."""


def _atomic_cost(text: str) -> int:
    """Typeset lines an already-rendered block will occupy: every source line
    counts at least one, and a long one counts the lines it will wrap to."""
    return sum(max(1, -(-len(ln) // _TEX_PROSE_WRAP)) for ln in text.split("\n"))


def _pack_verbatim(segments) -> list[list[str]]:
    """Plan how a turn's segments fill consecutive boxes of at most
    _TEX_BOX_MAX_LINES typeset lines. A plain str is verbatim text that may be
    cut between lines (a tool call's input, then its output; a fenced block),
    counting the hard wrap a long line will get; an _Atomic is placed whole.
    Returns the boxes; each is the list of pieces it holds, one per segment
    it has a part of, in order, so the input/output boundary stays a block
    boundary. One box holding every segment whole for the common case.

    A final remainder of blank lines only (a trailing newline pushed just
    over the limit) joins the previous box instead of becoming an '(empty)'
    part of its own."""
    def cost(ln):
        return max(1, -(-len(ln) // _TEX_HARD_WRAP))
    boxes, cur, n = [], [], 0          # cur: [[segment index, lines | atomic], ...]

    def place(seg, unit, c):
        nonlocal cur, n
        if cur and n + c > _TEX_BOX_MAX_LINES:
            boxes.append(cur)
            cur, n = [], 0
        if cur and cur[-1][0] == seg and not isinstance(unit, _Atomic):
            cur[-1][1].append(unit)
        else:
            cur.append([seg, unit if isinstance(unit, _Atomic) else [unit]])
        n += c

    for seg, text in enumerate(segments):
        if isinstance(text, _Atomic):
            place(seg, text, _atomic_cost(text))
        else:
            for ln in text.split("\n"):
                place(seg, ln, cost(ln))
    if cur:
        boxes.append(cur)

    def blank(piece):
        return not isinstance(piece, _Atomic) and not any(ln.strip() for ln in piece)
    if len(boxes) > 1 and all(blank(piece) for _, piece in boxes[-1]):
        prev, last = boxes[-2], boxes.pop()
        for seg, lines in last:
            if prev[-1][0] == seg and not isinstance(prev[-1][1], _Atomic):
                prev[-1][1].extend(lines)
            else:
                prev.append([seg, lines])
    return [[piece if isinstance(piece, _Atomic) else "\n".join(piece)
             for _, piece in b] for b in boxes]


def tex_verbatim(body: str, tally, neutral: bool = False) -> str:
    body = tex_drop_unprintable(strip_ansi(body), tally)
    if neutral:
        body = transliterate(body, tally, verbatim=True)
    body = body.replace("\\end{Verbatim}", "\\end{Verb atim}")
    # breakanywhere gives TeX a break opportunity after every character, so a
    # single enormous line becomes one paragraph with tens of thousands of them
    # and the line breaker crawls: one session with a 65,110-character line took
    # 928s to typeset 57 pages. Pre-splitting keeps each paragraph bounded. The
    # visual result is the same wrap fvextra would have chosen.
    if any(len(ln) > _TEX_HARD_WRAP for ln in body.split("\n")):
        wrapped = []
        for ln in body.split("\n"):
            if len(ln) <= _TEX_HARD_WRAP:
                wrapped.append(ln)
            else:
                tally["hardwrapped"] += 1
                wrapped += [ln[i:i + _TEX_HARD_WRAP]
                            for i in range(0, len(ln), _TEX_HARD_WRAP)]
        body = "\n".join(wrapped)
    if not body.strip():
        body = "(empty)"
    opts = "breaklines=true,breakanywhere=true,fontsize=\\small,xleftmargin=6pt"
    return "\\begin{Verbatim}[" + opts + "]\n" + body + "\n\\end{Verbatim}\n"


def _tex_table(header, rows, inl) -> str:
    """A markdown table as one or more consecutive tabulars.

    A tabular is unbreakable and unbounded: it takes its width from its
    content and never splits across a page, so on the real archive a long or
    wide table lost every row that ran past the paper while xelatex still
    exited 0. So the table is cut into chunks of at most _TEX_TABLE_MAX_LINES
    typeset rows -- separate tabulars, which the breakable box around them may
    break between -- and, when the natural width does not fit the line, the
    columns become equal wrapping p-columns so no cell runs off the edge.
    Every chunk repeats the header, and every chunk after the first says it is
    a continuation, so the pieces still read as one table.
    """
    ncol = max(1, len(header))
    body = [(list(r) + [""] * ncol)[:ncol] for r in rows]
    widest = [max([len(str(header[c])) if c < len(header) else 0]
                  + [len(str(r[c])) for r in body]) for c in range(ncol)]
    # +3 for the column separation a natural-width tabular adds per column.
    wrap = sum(widest) + 3 * ncol > _TEX_TABLE_LINE_CHARS
    if wrap:
        # p-columns of an equal share of the line. \linewidth is the enclosing
        # box's inner width, so this fits inside a turn box as well as on the
        # page, and 2\tabcolsep per column is exactly what tabular adds.
        cell = ("\\dimexpr\\linewidth/" + str(ncol)
                + " - 2\\tabcolsep - \\arrayrulewidth\\relax")
        spec = (">{\\raggedright\\arraybackslash}p{" + cell + "}") * ncol
        colchars = max(8, _TEX_TABLE_LINE_CHARS // ncol)
    else:
        spec = "l" * ncol
        colchars = 0

    def height(cells):
        if not wrap:
            return 1
        return max(1, max(-(-len(str(c)) // colchars) for c in cells))

    chunks, cur, n = [], [], 0
    for r in body:
        h = height(r)
        if cur and n + h > _TEX_TABLE_MAX_LINES:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(r)
        n += h
    if cur or not chunks:
        chunks.append(cur)

    head = " & ".join(inl(str(c)) for c in header) + " \\\\\n\\midrule\n"
    out = []
    for k, chunk in enumerate(chunks):
        if k:
            out.append("\\smallskip\\noindent{\\footnotesize\\itshape "
                       "(table continued)}\\par\\nobreak\n")
        out.append("\\begin{tabular}{" + spec + "}\n\\toprule\n" + head)
        for r in chunk:
            out.append(" & ".join(inl(str(c)) for c in r) + " \\\\\n")
        out.append("\\bottomrule\n\\end{tabular}\n\n")
    return "".join(out)


def md_to_tex_blocks(text: str, tally, neutral: bool = False) -> list[str]:
    """Render markdown to LaTeX block by block for _pack_verbatim: a fenced
    block is returned as its raw text (a plain str, still to be set verbatim,
    which the packer may cut between lines); every other block is an _Atomic
    piece of finished LaTeX."""
    def inl(x):
        return tex_inline(x, tally, neutral)

    blocks = []
    for tok in md_tokens(text):
        out = []
        if tok[0] == "para":
            out.append(inl(tok[1]) + "\n\n")
        elif tok[0] == "code":
            blocks.append(tok[2])
            continue
        elif tok[0] == "heading":
            cmd = ["\\subsection*", "\\subsubsection*", "\\paragraph"][min(tok[1] - 1, 2)]
            out.append(cmd + "{" + inl(tok[2]) + "}\n")
        elif tok[0] == "hr":
            out.append("\\medskip\\hrule\\medskip\n")
        elif tok[0] == "table":
            out.append(_tex_table(tok[1], tok[2], inl))
        elif tok[0] == "list":
            # Group consecutive items by marker type so a list that switches
            # from bullets to numbers gets enumerate for the numbered run
            # instead of one flattened itemize. (Nesting stays flat here; the
            # HTML keeps the hierarchy.)
            items, j = tok[1], 0
            while j < len(items):
                ordered = items[j][1]
                env = "enumerate" if ordered else "itemize"
                out.append("\\begin{" + env + "}[leftmargin=*,itemsep=1pt]\n")
                while j < len(items) and items[j][1] == ordered:
                    out.append("  \\item " + inl(items[j][2]) + "\n")
                    j += 1
                out.append("\\end{" + env + "}\n")
        elif tok[0] == "quote":
            out.append("\\begin{quote}\n" + inl(tok[1]) + "\n\\end{quote}\n")
        if out:
            blocks.append(_Atomic("".join(out)))
    return blocks


def _set_pieces(pieces, tally, neutral) -> str:
    """Finish packed pieces to LaTeX: raw verbatim text is set in a Verbatim
    block, an _Atomic piece is already done."""
    return "".join(x if isinstance(x, _Atomic) else tex_verbatim(x, tally, neutral)
                   for x in pieces)


def md_to_tex(text: str, tally, neutral: bool = False) -> str:
    return _set_pieces(md_to_tex_blocks(text, tally, neutral), tally, neutral)


def html_fragment_to_text(frag: str) -> str:
    """Flatten a hand-written summary fragment to readable plain text."""
    s = re.sub(r"(?is)<(h[1-6])[^>]*>(.*?)</\1>",
               lambda m: "\n\n" + m.group(2).upper() + "\n", frag)
    s = re.sub(r"(?is)<li[^>]*>", "\n  - ", s)
    s = re.sub(r"(?is)</(p|div|ul|ol|li|section)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    for a, b in (("&mdash;", "--"), ("&ndash;", "-"), ("&nbsp;", " "),
                 ("&ldquo;", '"'), ("&rdquo;", '"'), ("&rsquo;", "'"),
                 ("&lsquo;", "'"), ("&middot;", "-"), ("&hellip;", "..."),
                 ("&times;", "x"), ("&asymp;", "~"), ("&le;", "<="),
                 ("&ge;", ">="), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        s = s.replace(a, b)
    s = re.sub(r"&[a-zA-Z]+;", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def fidelity_lines(t) -> list:
    """The four reconciliation numbers, identical in every format."""
    d = t.disposition
    return [(_("records that produced one or more turns below"), d["rendered"]),
            (_("records folded into an earlier turn (tool results)"), d["folded"]),
            (_("records counted only (no transcript content)"), d["counted"]),
            (_("total records in the source"), sum(t.record_types.values()))]


def soft_wrap(text: str, width: int = 100) -> str:
    """Wrap over-long prose lines; leave columnar or already-short lines alone."""
    out = []
    for line in text.split("\n"):
        if len(line) <= width or "  " in line.strip() or "\t" in line:
            out.append(line)
        else:
            out.extend(textwrap.wrap(line, width=width) or [""])
    return "\n".join(out)


def wrap_prose(text: str, width: int = 100, indent: str = "") -> str:
    """Wrap authored prose. Never applied to human turns or tool I/O."""
    out = []
    for block in text.split("\n\n"):
        para = " ".join(block.split())
        out.append(textwrap.fill(para, width=width, initial_indent=indent,
                                 subsequent_indent=indent) if para else "")
    return "\n\n".join(out)


def _format_note(tool_output: bool, omitted: int) -> str:
    if tool_output:
        return _("Every turn in the HTML archive is present here, with tool input and output in "
                 "full. Images embedded in tool results cannot travel in this format and are "
                 "marked as omitted; ANSI colour codes are stripped. Human turns and tool output "
                 "are reproduced verbatim and are never re-wrapped.")
    return (_("Every turn in the HTML archive is present here, but tool calls are reduced to a "
              "single labelled line: their input and output are omitted, because a page-based "
              "format renders them as unreadable walls of escaped JSON. The HTML archive holds "
              "all of it. Human turns and Claude's prose are complete and reproduced verbatim.")
            + (_(" {n} tool calls are shown by name only.").format(n=f"{omitted:,}")
               if omitted else ""))


def _turn_rule(label: str, ts: str, width: int, right: bool) -> list:
    """A boxed turn header, right-shifted for human turns.

    The header moves; the body never does. Human turns and tool output are
    reproduced byte-for-byte, so indenting their content would break the one
    guarantee this format exists to give -- a chat look is not worth that.
    """
    tag = f"[ {label} - {ts} ]" if ts else f"[ {label} ]"
    fill = "=" if right else "-"
    if right:
        pad = max(0, width - len(tag))
        return [" " * pad + tag, " " * max(0, pad - 2) + fill * (len(tag) + 2)]
    return [tag, fill * min(width, max(len(tag), 60))]


def _text_turns(turns, L, W, tool_output):
    for turn in turns:
        ts = (turn.get("ts") or "")[:19].replace("T", " ")
        kind = turn["kind"]
        if kind == "human":
            label = _("HUMAN") + (f" - {turn['tag']}" if turn.get("tag") else "")
            L += [""] + _turn_rule(label, ts, W, right=True) + ["", turn["text"].rstrip(), ""]
        elif kind == "assistant":
            label = ("CLAUDE" + (f" - {turn['tag']}" if turn.get("tag") else "")
                     + " " + str(turn.get("model", "")))
            L += [""] + _turn_rule(label, ts, W, right=False)
            L += ["", wrap_prose(turn.get("text", ""), W), ""]
        elif kind == "thinking":
            L += [""] + _turn_rule(_("THINKING"), ts, W, right=False)
            L += ["", wrap_prose(turn.get("text", "") or _("(no text: display=omitted)"), W), ""]
        elif kind == "user_image":
            L += [""] + _turn_rule(_("HUMAN - PASTED IMAGE"), ts, W, right=True)
            L += ["", "  " + _("(image omitted in this format; the HTML archive holds it)"), ""]
        elif kind == "tool":
            err = "  " + _("[ERROR]") if turn.get("is_error") else ""
            head = shorten(_("TOOL") + " " + str(turn.get("chip", "")) + " - "
                           + str(turn.get("label", "")) + err, 84)
            if not tool_output:
                L += ["", "  . " + head + "   " + ts]
                continue
            L += [""] + _turn_rule(head, ts, W, right=False) + ["", "  " + _("input:")]
            L += ["    " + ln
                  for ln in pretty_tool_input(turn.get("input") or "").splitlines()]
            if turn.get("output_text"):
                L += ["", "  " + _("output:")]
                L += ["    " + ln for ln in turn["output_text"].splitlines()]
            elif not turn.get("resolved"):
                L += ["", "  " + _("output:") + " " + _("(no result in the source)")]
            for _img in turn.get("output_images") or []:
                L.append("    " + _("[image omitted]"))
            L.append("")
        else:
            label = _(str(turn.get("badge", kind))).upper()
            if turn.get("detail"):
                label += " - " + str(turn["detail"])
            L += [""] + _turn_rule(label, ts, W, right=False)
            L += ["", soft_wrap((turn.get("text") or "").rstrip(), W), ""]


def emit_text(t, ctx: dict, tool_output: bool = True, agents: list = (),
              subagents_on: bool = True) -> str:
    W = 100
    bar = "=" * W
    L = [bar, "  " + ctx["title"], "  " + _("session") + " " + ctx["session_id"],
         "  " + ctx["subtitle"], bar, ""]
    if ctx["summary_text"]:
        h = _("SESSION SUMMARY")
        L += [h, "-" * len(h), "", wrap_prose(ctx["summary_text"], W), ""]
    h = _("FIDELITY REPORT")
    L += [h, "-" * len(h), ""]
    fl = fidelity_lines(t)
    sub = [(_("subagent transcript agent-{aid}").format(aid=aid)
            + ("" if subagents_on else _(" (not rendered)")), sum(at.record_types.values()))
           for aid, _af, at in agents]
    # The label column follows the longest label: a translated one can run
    # past the English width and must not push the numbers out of line.
    col = max(52, max(len(lbl) for lbl, _n in fl + sub) + 2)
    for label, n in fl:
        L.append("  " + label.ljust(col) + format(n, ",").rjust(9))
    L.append(f"  archiver v{VERSION}")
    for label, n in sub:
        L.append("  " + label.ljust(col) + format(n, ",").rjust(9))
    n_tools = sum(1 for x in t.turns if x["kind"] == "tool")
    if ctx.get("cost_note"):
        L += ["", wrap_prose(ctx["cost_note"], W)]
    L += ["", wrap_prose(_format_note(tool_output, n_tools), W), ""]
    _text_turns(t.turns, L, W, tool_output)
    if agents and subagents_on:
        for k, (aid, _af, at) in enumerate(agents, 1):
            L += ["", bar,
                  "  " + _("SUBAGENT TRANSCRIPT A{k}: agent-{aid}  ({records} records; turns "
                           "tagged A{k}.P / A{k}.R)").format(
                               k=k, aid=aid, records=f"{sum(at.record_types.values()):,}"), bar]
            _text_turns(at.turns, L, W, tool_output)
    return "\n".join(L) + "\n"


def _md_fence(text: str, lang: str = "") -> str:
    """Fence verbatim content with more backticks than any run inside it."""
    longest = max((len(r) for r in re.findall(r"`+", text)), default=0)
    f = "`" * max(3, longest + 1)
    return f"{f}{lang}\n{text}\n{f}"


def emit_markdown(t, ctx: dict, tool_output: bool = True, agents: list = (),
                  subagents_on: bool = True) -> str:
    """Markdown for note vaults. Claude's prose IS markdown and passes through
    live; human turns and tool I/O are fenced so nothing in them can be
    reinterpreted -- the same verbatim guarantee the text format gives."""
    L = [f"# {ctx['title']}", "",
         "- " + _("Session: `{sid}`").format(sid=ctx["session_id"]),
         f"- {ctx['subtitle']}", ""]
    if ctx["summary_text"]:
        L += ["## " + _("Session summary"), "", ctx["summary_text"], ""]
    L += ["## " + _("Fidelity report"), ""]
    for label, n in fidelity_lines(t):
        L.append(f"- {label}: {n:,}")
    L.append(f"- archiver v{VERSION}")
    for aid, _af, at in agents:
        L.append("- " + _("subagent transcript agent-{aid}").format(aid=aid)
                 + ("" if subagents_on else _(" (not rendered)")) + ": "
                 f"{sum(at.record_types.values()):,}")
    n_tools = sum(1 for x in t.turns if x["kind"] == "tool")
    if ctx.get("cost_note"):
        L += ["", ctx["cost_note"]]
    L += ["", _format_note(tool_output, n_tools),
          _("Human turns and tool I/O are fenced verbatim below; Claude's own prose is markdown "
            "and is left live, so its headings appear in this document's outline."), ""]

    def turns_md(turns):
        for turn in turns:
            ts = (turn.get("ts") or "")[:19].replace("T", " ")
            kind = turn["kind"]
            if kind == "human":
                tg = f" - {turn['tag']}" if turn.get("tag") else ""
                L.extend([f"## {_('Human')}{tg} — {ts}", "",
                          _md_fence(turn["text"].rstrip()), ""])
            elif kind == "assistant":
                tg = f" - {turn['tag']}" if turn.get("tag") else ""
                L.extend([f"## Claude{tg} — {ts}", "", turn.get("text", ""), ""])
            elif kind == "thinking":
                L.extend([f"### {_('Thinking')} — {ts}", "",
                          turn.get("text", "") or f"*{_('(no text: display=omitted)')}*", ""])
            elif kind == "user_image":
                L.extend([f"## {_('Human — pasted image')} — {ts}", "",
                          f"*{_('(image omitted in this format; the HTML archive holds it)')}*", ""])
            elif kind == "tool":
                err = f" **{_('[ERROR]')}**" if turn.get("is_error") else ""
                head = shorten(str(turn.get("chip", "")) + " — "
                               + str(turn.get("label", "")), 90)
                L.append(f"**{_('Tool')} · {head}**{err} · {ts}")
                if tool_output:
                    L.extend(["", _md_fence(pretty_tool_input(turn.get("input") or ""))])
                    if turn.get("output_text"):
                        L.extend(["", _md_fence(turn["output_text"])])
                    elif not turn.get("resolved"):
                        L.extend(["", f"*{_('(no result in the source)')}*"])
                    for _img in turn.get("output_images") or []:
                        L.extend(["", f"*{_('(image omitted in this format)')}*"])
                L.append("")
            else:
                badge = _(str(turn.get("badge", kind)))
                if turn.get("detail"):
                    badge += " — " + str(turn["detail"])
                L.append(f"> **{badge}** · {ts}")
                if turn.get("text"):
                    L.extend(["", _md_fence(turn["text"].rstrip())])
                L.append("")

    turns_md(t.turns)
    if agents and subagents_on:
        for k, (aid, _af, at) in enumerate(agents, 1):
            L.extend(["", "---", "",
                      "# " + _("Subagent transcript A{k}: agent-{aid}").format(k=k, aid=aid),
                      "*" + _("({records} records; a background agent's own conversation)").format(
                          records=f"{sum(at.record_types.values()):,}") + "*", ""])
            turns_md(at.turns)
    return "\n".join(L) + "\n"


_TEX_PREAMBLE = r"""\documentclass[10pt,a4paper]{article}
\usepackage{fontspec}
\usepackage{fvextra}
\usepackage[margin=20mm]{geometry}
\usepackage{booktabs}
\usepackage{array}
\usepackage{enumitem}
\usepackage{xcolor}
\usepackage[colorlinks=true,linkcolor=black,urlcolor=blue!60!black]{hyperref}
\IfFontExistsTF{DejaVuSerif.ttf}{%
  \setmainfont{DejaVuSerif.ttf}[BoldFont=DejaVuSerif-Bold.ttf,
    ItalicFont=DejaVuSerif-Italic.ttf,Scale=0.92]%
  \setsansfont{DejaVuSans.ttf}[BoldFont=DejaVuSans-Bold.ttf]%
  \setmonofont{DejaVuSansMono.ttf}[BoldFont=DejaVuSansMono-Bold.ttf,
    ItalicFont=DejaVuSansMono-Oblique.ttf,Scale=0.85]%
}{}
\usepackage[most]{tcolorbox}
\definecolor{paper}{HTML}{FAF7F0}
\pagecolor{paper}
\definecolor{humanc}{HTML}{2F6F4F}\definecolor{humanbg}{HTML}{E9F3ED}
\definecolor{claudec}{HTML}{44578C}\definecolor{claudebg}{HTML}{ECEFF8}
\definecolor{toolc}{HTML}{5C5750}\definecolor{toolbg}{HTML}{F1EFE9}
\definecolor{sysc}{HTML}{96762C}\definecolor{sysbg}{HTML}{F7EFDD}
\definecolor{thinkc}{HTML}{6B5B95}\definecolor{thinkbg}{HTML}{F0ECF6}
\newtcolorbox{humanturn}[1]{breakable,enhanced,colback=humanbg,colframe=humanc,
  boxrule=0.9pt,arc=3mm,left skip=0.16\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=humanc,coltitle=white,
  title={#1}}
\newtcolorbox{claudeturn}[1]{breakable,enhanced,colback=claudebg,colframe=claudec,
  boxrule=0.9pt,arc=3mm,right skip=0.10\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=claudec,coltitle=white,
  title={#1}}
\newtcolorbox{thinkturn}[1]{breakable,enhanced,colback=thinkbg,colframe=thinkc,
  boxrule=0.6pt,arc=2mm,right skip=0.10\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=thinkc,coltitle=white,
  title={#1}}
\newtcolorbox{toolturn}[1]{breakable,enhanced,colback=toolbg,colframe=toolc,
  boxrule=0.5pt,arc=1mm,fonttitle=\bfseries\scriptsize,colbacktitle=toolc,
  coltitle=white,title={#1}}
\newtcolorbox{systurn}[1]{breakable,enhanced,colback=sysbg,colframe=sysc,
  boxrule=0.5pt,arc=1mm,fonttitle=\bfseries\scriptsize,colbacktitle=sysc,
  coltitle=white,title={#1}}
\setlength{\parindent}{0pt}
\setlength{\parskip}{4pt}
\sloppy
\setlength{\emergencystretch}{4em}
"""


_FRAGMENT_HEAD = r"""% Transcript body only -- \input this into your own document.
%
% Engine-neutral: every character has been reduced to something pdflatex can
% set, so this compiles under pdflatex, xelatex or lualatex alike.
%
% It needs these packages in your preamble:
%     \usepackage{fvextra}   \usepackage{xcolor}   \usepackage{enumitem}
%     \usepackage{booktabs}  \usepackage{array}    \usepackage[most]{tcolorbox}
%
% No \pagecolor is set here -- a fragment must not repaint its host's pages.
% The turn environments are defined only if you have not defined your own,
% so you can restyle every turn from your preamble without editing this file.
\providecolor{humanc}{HTML}{2F6F4F}\providecolor{humanbg}{HTML}{E9F3ED}
\providecolor{claudec}{HTML}{44578C}\providecolor{claudebg}{HTML}{ECEFF8}
\providecolor{toolc}{HTML}{5C5750}\providecolor{toolbg}{HTML}{F1EFE9}
\providecolor{sysc}{HTML}{96762C}\providecolor{sysbg}{HTML}{F7EFDD}
\providecolor{thinkc}{HTML}{6B5B95}\providecolor{thinkbg}{HTML}{F0ECF6}
\makeatletter
\@ifundefined{humanturn}{%
\newtcolorbox{humanturn}[1]{breakable,enhanced,colback=humanbg,colframe=humanc,
  boxrule=0.9pt,arc=3mm,left skip=0.16\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=humanc,coltitle=white,
  title={#1}}
\newtcolorbox{claudeturn}[1]{breakable,enhanced,colback=claudebg,colframe=claudec,
  boxrule=0.9pt,arc=3mm,right skip=0.10\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=claudec,coltitle=white,
  title={#1}}
\newtcolorbox{thinkturn}[1]{breakable,enhanced,colback=thinkbg,colframe=thinkc,
  boxrule=0.6pt,arc=2mm,right skip=0.10\linewidth,
  fonttitle=\bfseries\footnotesize,colbacktitle=thinkc,coltitle=white,
  title={#1}}
\newtcolorbox{toolturn}[1]{breakable,enhanced,colback=toolbg,colframe=toolc,
  boxrule=0.5pt,arc=1mm,fonttitle=\bfseries\scriptsize,colbacktitle=toolc,
  coltitle=white,title={#1}}
\newtcolorbox{systurn}[1]{breakable,enhanced,colback=sysbg,colframe=sysc,
  boxrule=0.5pt,arc=1mm,fonttitle=\bfseries\scriptsize,colbacktitle=sysc,
  coltitle=white,title={#1}}
}{}
\makeatother

"""


def emit_latex(t, ctx: dict, fragment: bool = False, tool_output: bool = False,
               agents: list = (), subagents_on: bool = True):
    # A fragment goes into someone else's document, so it must survive whatever
    # engine that document uses -- pdflatex included. The standalone stays
    # XeLaTeX and keeps Unicode as itself.
    neutral = fragment
    tally = Counter()

    def inl(x):
        return tex_inline(x, tally, neutral)

    def md(x):
        return md_to_tex(x, tally, neutral)

    def chrome(x, protect=False):
        """The archiver's own words -- a heading, a note, a label.

        Never counted in the drop-note (they are not conversation), set as
        accent macros in a fragment (pdflatex has no idea what "é" is), and
        in a standalone wrapped in the document language so polyglossia
        hyphenates and spaces them by its rules while the conversation keeps
        the default language, English. `protect` for moving arguments."""
        s = tex_inline(x, Counter(), False)
        if neutral:
            return tex_accents(s)
        if LANG in _TEX_LANGNAME:
            return ("\\protect" if protect else "") + "\\text" + _TEX_LANGNAME[LANG] + "{" + s + "}"
        return s

    def clabel(x):
        """A box title or table label: chrome without the language wrapper."""
        s = tex_inline(x, Counter(), False)
        return tex_accents(s) if neutral else s

    def heading(x):
        return ("\\section*{" + chrome(x) + "}\n\\addcontentsline{toc}{section}{"
                + chrome(x, protect=True) + "}\n")

    def esc(x):
        """Escape a bare string -- a turn label, badge or id.

        These bypassed transliteration when they went straight to tex_escape,
        which let a tool label carrying a Greek capital or a subscript leak an
        un-settable character into an otherwise ASCII fragment.
        """
        x = tex_drop_unprintable(strip_ansi(str(x)), tally)
        if neutral:
            x = transliterate(x, tally, verbatim=True)
        return tex_escape(x)

    B = []
    if fragment:
        B.append(_FRAGMENT_HEAD)
    if not fragment:
        pre = _TEX_PREAMBLE
        if LANG in _TEX_LANGUAGE:
            # Hyphenation and typographic conventions of the document language;
            # only when polyglossia is installed, so a lean TeX still compiles.
            # The conversation is set in the default language, English; only
            # the archiver's own words (\text<lang>{...}) switch. Without
            # polyglossia the wrapper is defined as the identity.
            pre = pre.replace(
                "\\usepackage{fontspec}\n",
                "\\usepackage{fontspec}\n\\IfFileExists{polyglossia.sty}{\\usepackage{polyglossia}"
                "\\setdefaultlanguage{english}\\setotherlanguage" + _TEX_LANGUAGE[LANG]
                + "}{\\newcommand{\\text" + _TEX_LANGNAME[LANG] + "}[1]{#1}}\n", 1)
        B.append(pre)
        B.append("\\title{" + inl(ctx["title"]) + "}\n\\date{}\n")
        B.append("\\begin{document}\n\\maketitle\n")
        B.append("\\begin{center}\\texttt{" + esc(ctx["session_id"]) + "}\\\\\n")
        B.append(inl(ctx["subtitle"]) + "\\end{center}\n")
        B.append("\\tableofcontents\n\\newpage\n")
    if ctx["summary_text"]:
        B.append(heading(_("Session summary")))
        B.append(md(ctx["summary_text"]))
    B.append(heading(_("Fidelity report")))
    B.append("\\begin{tabular}{lr}\n\\toprule\n")
    for lbl, n in fidelity_lines(t):
        B.append(clabel(lbl) + " & " + format(n, ",") + " \\\\\n")
    B.append("\\multicolumn{2}{l}{archiver v" + esc(VERSION) + "} \\\\\n")
    B.append("\\bottomrule\n\\end{tabular}\n\n")
    n_tools = sum(1 for x in t.turns if x["kind"] == "tool")
    if ctx.get("cost_note"):
        B.append(chrome(ctx["cost_note"]) + "\n\n")
    B.append(chrome(_format_note(tool_output, n_tools)) + "\n\n")
    # The drop-note's numbers are only known once the whole body is rendered,
    # so reserve a slot and assign it afterwards. Filling it by string
    # replacement over the finished source once clobbered a transcript that
    # itself contained the placeholder text.
    B.append("")
    dropnote_slot = len(B) - 1
    B.append(heading(_("Transcript")))
    def box(env, title, inner):
        return ("\\begin{" + env + "}{" + title + "}\n" + inner
                + "\\end{" + env + "}\n")

    def stamp(ts):
        return " \\hfill {\\normalfont\\scriptsize\\ttfamily " + esc(ts) + "}"

    def part_boxes(env, label, ts, boxes, tail=""):
        """Emit one box, or consecutive boxes titled '(part k/n)' when the
        content was packed into several. `tail` (inline notes) goes after
        the last one."""
        if len(boxes) > 1:
            tally["split_boxes"] += 1
        for k, pieces in enumerate(boxes, 1):
            part = clabel(_(" (part {k}/{n})").format(k=k, n=len(boxes))) if len(boxes) > 1 else ""
            B.append(box(env, label + part + stamp(ts),
                         _set_pieces(pieces, tally, neutral)
                         + (tail if k == len(boxes) else "")))

    def verbatim_boxes(env, label, ts, *segments, tail=""):
        """Box(es) holding the verbatim segments (a tool call's input, then
        its output) in order, split when together they exceed what one
        breakable box can hold."""
        part_boxes(env, label, ts, _pack_verbatim(segments), tail=tail)

    def md_boxes(env, label, ts, text):
        """Box(es) holding a markdown turn: a Claude reply that prints a
        whole file in a fenced block is as large as any paste, so its
        blocks are packed the same way."""
        part_boxes(env, label, ts,
                   _pack_verbatim(md_to_tex_blocks(text, tally, neutral)))

    def emit_turns(turns):
        for turn in turns:
            ts = (turn.get("ts") or "")[:19].replace("T", " ")
            kind = turn["kind"]
            if kind == "human":
                tg = (" - " + esc(turn["tag"])) if turn.get("tag") else ""
                verbatim_boxes("humanturn", clabel(_("HUMAN")) + tg, ts, turn["text"].rstrip())
            elif kind == "assistant":
                tg = (" - " + esc(turn["tag"])) if turn.get("tag") else ""
                md_boxes("claudeturn", "CLAUDE" + tg, ts, turn.get("text", ""))
            elif kind == "thinking":
                md_boxes("thinkturn", clabel(_("THINKING")), ts,
                         turn.get("text", "") or _("(no text: display=omitted)"))
            elif kind == "tool":
                err = " " + _("[ERROR]") if turn.get("is_error") else ""
                head = esc(shorten(str(turn.get("chip", "")) + " - "
                                   + str(turn.get("label", "")) + err))
                tool_head = clabel(_("TOOL")) + ": " + head
                title = tool_head + stamp(ts)
                if not tool_output:
                    # A bare title box: the call is on the record, its payload is not.
                    B.append("\\begin{toolturn}{" + title + "}\\end{toolturn}\n")
                    continue
                tail = ""
                if not turn.get("output_text") and not turn.get("resolved"):
                    tail += chrome(_("(no result in the source)")) + "\n\n"
                for _img in turn.get("output_images") or []:
                    tail += chrome(_("[image omitted]")) + "\n\n"
                segments = [pretty_tool_input(turn.get("input") or "")]
                if turn.get("output_text"):
                    segments.append(turn["output_text"])
                verbatim_boxes("toolturn", tool_head, ts, *segments, tail=tail)
            elif kind == "user_image":
                B.append(box("humanturn",
                             clabel(_("HUMAN - PASTED IMAGE")) + stamp(ts),
                             chrome(_("(image omitted in this format; the HTML archive holds it)"))
                             + "\n\n"))
            else:
                # Shorten the raw words, then escape: a cut through an escaped
                # string can land inside \textbackslash{} (2.7.1 left a bare
                # \tex in every Windows file-edit snapshot title).
                raw_badge = _(str(turn.get("badge", kind)))
                badge = clabel(raw_badge)
                if turn.get("detail"):
                    detail = shorten(str(turn["detail"]), max(12, 72 - len(raw_badge) - 3))
                    badge += " - " + esc(detail)
                verbatim_boxes("systurn", badge, ts, (turn.get("text") or "").rstrip())

    emit_turns(t.turns)
    if agents and subagents_on:
        for k, (aid, _af, at) in enumerate(agents, 1):
            B.append("\\section*{" + chrome(_("Subagent transcript A{k}: agent-{aid}").format(k=k, aid=aid))
                     + "}\n\\addcontentsline{toc}{section}{"
                     + chrome(_("Subagent A{k}: agent-{aid}").format(k=k, aid=aid[:8]), protect=True)
                     + "}\n")
            B.append(chrome(_("({records} records; a background agent's own conversation, archived "
                              "from its transcript file beside the session)").format(
                                  records=f"{sum(at.record_types.values()):,}")) + "\n\n")
            emit_turns(at.turns)
    elif agents:
        B.append("\\section*{" + chrome(_("Subagent transcripts (not rendered)")) + "}\n")
        B.append(chrome(_("{n} subagent transcript file(s) exist for this session but were not "
                          "rendered (--subagents off): {files}. Their token usage is included in "
                          "the usage table.").format(
                              n=len(agents), files=", ".join(f"agent-{a}" for a, _f, _t in agents)))
                 + "\n\n")
    if not fragment:
        B.append("\\end{document}\n")
    removed = []
    if tally["glyphs"]:
        removed.append(_("{n} characters (emoji and other glyphs no installed TeX font can set)")
                       .format(n=format(tally["glyphs"], ",")))
    if tally["controls"]:
        removed.append(_("{n} control bytes (NUL, backspace and similar, which TeX refuses to read)")
                       .format(n=format(tally["controls"], ",")))
    notes = []
    if removed:
        notes.append(_("This rendering removed {what}.").format(what=_(" and ").join(removed)))
    if tally["transliterated"]:
        notes.append(_("This fragment is engine-neutral, so it compiles under pdflatex as well as "
                       "XeLaTeX: {n} characters were transliterated (Greek to math or its name, "
                       "arrows and box drawing to ASCII).").format(
                           n=format(tally["transliterated"], ",")))
    if tally["hardwrapped"]:
        notes.append(_("{n} very long lines were hard-wrapped at {w} characters so TeX could "
                       "typeset them.").format(n=format(tally["hardwrapped"], ","), w=_TEX_HARD_WRAP))
    if tally["split_boxes"]:
        notes.append(_("{n} very large turn(s) were split into consecutive boxes of at most {m} "
                       "lines each, titled (part k/n), so TeX could hold them in memory; nothing "
                       "was omitted.").format(n=format(tally["split_boxes"], ","),
                                              m=format(_TEX_BOX_MAX_LINES, ",")))
    if notes:
        notes.append(_("The HTML archive holds all of it unaltered."))
        B[dropnote_slot] = chrome(" ".join(notes)) + "\n\n"
    return "".join(B), tally


def compile_pdf(tex_path):
    """Two XeLaTeX passes: the second resolves the table of contents."""
    exe = shutil.which("xelatex")
    if not exe:
        sys.exit("xelatex not found on PATH -- required for --format pdf")
    for run in (1, 2):
        # xelatex writes font names and file paths in whatever encoding the OS
        # hands it; decoding that as the Windows default raises inside
        # subprocess's reader thread and buries the real result in a traceback.
        p = subprocess.run([exe, "-interaction=nonstopmode", "-halt-on-error",
                            tex_path.name], cwd=str(tex_path.parent),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if p.returncode != 0:
            log = tex_path.with_suffix(".log")
            tail = ""
            if log.exists():
                tail = "\n".join(log.read_text(encoding="utf-8", errors="replace")
                                 .splitlines()[-30:])
            sys.exit("xelatex failed on pass " + str(run) + ":\n" + tail)
    for ext in (".aux", ".log", ".out", ".toc"):
        tex_path.with_suffix(ext).unlink(missing_ok=True)
    (tex_path.parent / "missfont.log").unlink(missing_ok=True)
    return tex_path.with_suffix(".pdf")


# ---------------------------------------------------------------------------
# claude.ai import
#
# claude.ai's data export (Settings -> Privacy -> Export data) ships a
# conversations.json in its own schema: a list of conversations, each with
# chat_messages carrying sender/text/content/attachments. The adapter converts
# one conversation into this tool's record model and lets the normal pipeline
# do everything else -- discovery, fidelity, all four formats -- unchanged.
# The export carries no usage data and no model name; the page says so.
# ---------------------------------------------------------------------------

WEB_EXPORT_MODEL = "claude.ai (model not in export)"


def claude_ai_records(conv: dict) -> list[dict]:
    sid = conv.get("uuid") or "claude-ai-import"
    name = conv.get("name") or sid
    msgs = conv.get("chat_messages") or []
    recs: list[dict] = [
        {"type": "ai-title", "aiTitle": name, "sessionId": sid},
        {"type": "attachment", "sessionId": sid, "uuid": f"{sid}-import-note",
         "timestamp": conv.get("created_at"),
         "attachment": {"type": "hook_system_message",
                        "hookName": "claude.ai import",
                        "content": (f"Imported from a claude.ai data export "
                                    f"(conversations.json): conversation "
                                    f"“{name}”, {len(msgs)} messages. "
                                    "The export records no token usage and no "
                                    "model name.")}},
    ]
    for i, msg in enumerate(msgs):
        if not isinstance(msg, dict):
            continue
        base = {"sessionId": sid, "uuid": msg.get("uuid") or f"{sid}-msg-{i}",
                "timestamp": msg.get("created_at") or conv.get("created_at"),
                "version": "claude.ai export"}
        text = msg.get("text") or ""
        content = msg.get("content")
        blocks = [b for b in content if isinstance(b, dict)] \
            if isinstance(content, list) else []

        if msg.get("sender") == "human":
            htext = text or "\n\n".join(
                b.get("text", "") for b in blocks if b.get("type") == "text")
            if htext.strip():
                recs.append({**base, "type": "user", "promptSource": "typed",
                             "origin": {"kind": "human"},
                             "message": {"role": "user", "content": htext}})
            for j, att in enumerate(msg.get("attachments") or []):
                if not isinstance(att, dict):
                    continue
                recs.append({**base, "uuid": f"{base['uuid']}-att-{j}",
                             "type": "attachment",
                             "attachment": {"type": "file",
                                            "filename": att.get("file_name", ""),
                                            "content": att.get("extracted_content")
                                            or f"({att.get('file_type', 'file')}; "
                                               "content not included in the export)"}})
            for j, f_ in enumerate(msg.get("files") or []):
                if not isinstance(f_, dict):
                    continue
                recs.append({**base, "uuid": f"{base['uuid']}-file-{j}",
                             "type": "attachment",
                             "attachment": {"type": "file",
                                            "filename": f_.get("file_name", ""),
                                            "content": "(binary file; content not "
                                                       "included in claude.ai exports)"}})
            continue

        # Assistant. tool_result blocks belong to user records in the Claude
        # Code model, so split the stream there and the tool call still folds.
        if not blocks and text:
            blocks = [{"type": "text", "text": text}]
        pending: list[dict] = []
        part = 0

        def flush(kind_blocks, rtype):
            nonlocal part
            if not kind_blocks:
                return
            rec = {**base, "uuid": f"{base['uuid']}-p{part}" if part else base["uuid"],
                   "type": rtype,
                   "message": ({"role": "assistant", "model": WEB_EXPORT_MODEL,
                                "content": list(kind_blocks)} if rtype == "assistant"
                               else {"role": "user", "content": list(kind_blocks)})}
            recs.append(rec)
            part += 1

        for b in blocks:
            if b.get("type") == "tool_result":
                flush(pending, "assistant")
                pending = []
                flush([b], "user")
            else:
                pending.append(b)
        flush(pending, "assistant")
    return recs


def load_claude_ai_export(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("conversations") or [data]
    return [c for c in data if isinstance(c, dict) and c.get("chat_messages") is not None]


# ---------------------------------------------------------------------------
# Index mode
# ---------------------------------------------------------------------------

def is_legacy_version(v) -> bool:
    """v1 archives carry no usable metadata; anything from 2.0 on does.
    Compare the major number, not the first character -- '3.0' is not v1."""
    try:
        return int(str(v).split(".")[0]) < 2
    except (ValueError, TypeError):
        return True


def _age_label(seconds: float) -> str:
    if seconds < 90:
        return _("now")
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


_HUMAN_TURN_RE = re.compile(
    r'<section class="turn human-turn" id="([^"]+)"[^>]*>.*?'
    r'<span class="who">[^<]*(?: <span class="rtag" id="([^"]+)">[^<]*</span>)?</span>.*?'
    r'<div class="turn-body"><div class="raw(?: mono)?">(.*?)</div></div>', re.S)
_SEARCH_TEXT_CAP = 400


def prompt_index_entry(archive_dir: Path, meta: dict) -> dict:
    """Every human prompt of one archive, with a deep link, for the index
    page's cross-archive search. Read back from the archive's own HTML (all
    pages of a paginated one), so archives written by earlier versions and
    imports are covered alike; prompts without a P tag link to their turn."""
    prompts: list[dict] = []
    for page_name in (meta.get("pages") or [meta["file"]]):
        pf = archive_dir / page_name
        try:
            text = pf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for anchor, tag, body in _HUMAN_TURN_RE.findall(text):
            plain = html.unescape(re.sub(r"<[^>]+>", "", body))
            plain = " ".join(plain.split())
            if not plain:
                continue
            prompts.append({"tag": tag or "", "href": f"{page_name}#{tag or anchor}",
                            "text": plain[:_SEARCH_TEXT_CAP]})
    return {"session_id": meta.get("session_id", ""), "title": meta.get("title") or "",
            "file": meta["file"], "prompts": prompts}


def build_index(archive_dir: Path, projects_root: Path, out_path: Path,
                sessions: dict | None = None, refresh: int | None = None) -> None:
    if sessions is None:
        sessions = scan_sessions(projects_root)
    now = datetime.datetime.now(datetime.timezone.utc)
    # A first --index into a fresh directory must simply create it, as an
    # export does; the archive is empty, not an error.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    archived: dict[str, dict] = {}
    for f in sorted(archive_dir.glob("*.html")):
        if f.name == out_path.name:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r'<script type="application/json" id="archive-meta">(.*?)</script>', text, re.S)
        meta = {}
        if m:
            try:
                meta = json.loads(m.group(1))
            except json.JSONDecodeError:
                meta = {}
        if not meta:
            sid = f.name.split("_")[0]
            meta = {"session_id": sid, "title": f.stem, "archiver_version": "1.x (no metadata)"}
        if meta.get("continuation_of"):
            continue                     # page 2+ of a paginated archive
        meta["file"] = f.name
        meta["size_mb"] = f.stat().st_size / 1e6
        archived[meta["session_id"]] = meta

    rows = []
    for sid, info in sorted(sessions.items(), key=lambda kv: (kv[1].last or ""), reverse=True):
        meta = archived.get(sid)
        chain_best, related = resolve_chain(sid, sessions)
        covered_by = None
        covered_dropped = 0
        if not meta:
            for r in related:
                if r["session_id"] in archived and r["relation"] == "superset":
                    covered_by = r["session_id"]
                    covered_dropped = r.get("dropped", 0)
                    break
        # Match the archive pages, which print local time; sort on the raw UTC ISO.
        def _local(iso):
            if not iso:
                return ""
            try:
                return fmt_local(parse_ts(iso))
            except ValueError:
                return iso[:19].replace("T", " ")
        last = _local(info.last)
        started = _local(info.first)
        duration = ""
        if info.first and info.last:
            try:
                t0 = datetime.datetime.fromisoformat(info.first.replace("Z", "+00:00"))
                t1 = datetime.datetime.fromisoformat(info.last.replace("Z", "+00:00"))
                mins = max(0, int((t1 - t0).total_seconds() // 60))
                duration = f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins}m"
            except ValueError:
                duration = ""
        if meta:
            legacy = is_legacy_version(meta.get("archiver_version", ""))
            stale = bool(meta.get("last_record") and info.last and meta["last_record"][:19] < info.last[:19])
            if legacy:
                status = f'<span class="pill stale">{_("legacy v1")}</span>'
            elif stale:
                status = f'<span class="pill stale">{_("stale")}</span>'
            else:
                status = f'<span class="pill ok">{_("archived")}</span>'
            link = f'<a href="{esc(meta["file"])}">{esc(meta.get("title") or sid)}</a>'
            if legacy:
                detail = _("written by the v1 archiver &mdash; no embedded metadata, and its "
                           "counts and token figures are known to be wrong. Re-run to replace it.")
            else:
                # Metadata is read back from files on disk, so a field may be
                # absent or hand-edited; never let one entry abort the index.
                def _n(key, spec=","):
                    v = meta.get(key)
                    return format(v, spec) if isinstance(v, (int, float)) else "?"
                # The meter's figure is shown only when it covers the whole
                # session; otherwise the list-price estimate is the honest one.
                metered = (isinstance(meta.get("reported_cost_usd"), (int, float))
                           and meta.get("reported_cost_partial") is False)
                cost_txt = (_("${usd} reported").format(usd=_n("reported_cost_usd", ",.2f")) if metered
                            else _("${usd} at list price").format(usd=_n("list_cost_usd", ",.2f")))
                detail = _("{records} records &middot; {tools} tool calls &middot; {cost} &middot; "
                           "{mb} MB &middot; archiver v{version}").format(
                               records=_n("records"), tools=_n("tool_calls"), cost=cost_txt,
                               mb=f'{meta["size_mb"]:.1f}', version=meta.get("archiver_version"))
        elif covered_by:
            status = f'<span class="pill covered">{_("covered")}</span>'
            link = esc(info.title or sid)
            detail = _("continued into <code>{sid}</code>, archived there").format(sid=esc(covered_by[:8]))
            if covered_dropped:
                detail += _(" &middot; {n} record(s) not carried over (bookkeeping only)").format(
                    n=covered_dropped)
        else:
            status = f'<span class="pill missing">{_("not archived")}</span>'
            link = esc(info.title or sid)
            detail = _("{n} records on disk").format(n=f"{info.records:,}")
            if info.subagents:
                detail += _(" &middot; {n} subagent transcript(s)").format(n=info.subagents)
        if info.source != "claude-code":
            detail += _(" &middot; source: {source}").format(source=esc(info.source))
        status_key = re.sub(r"<[^>]+>", "", status).strip()
        title_key = re.sub(r"<[^>]+>", "", link).strip().lower()
        # Activity: computed at generation time, then left to decay in the
        # browser -- the page's JS recomputes the age from data-ts, so a
        # session can only go quiet on screen, never freshly "active", until
        # the index is regenerated (see --watch).
        age = None
        if info.last:
            try:
                age = (now - parse_ts(info.last)).total_seconds()
            except ValueError:
                age = None
        if age is None:
            act_cell = '<td class="activity" data-k="~"></td>'
        else:
            cls = "act" if age < 600 else "quiet"
            dot = "&#9679; " if age < 600 else ""
            act_cell = (f'<td class="activity" data-ts="{esc(info.last)}" '
                        f'data-k="{esc(info.last)}">'
                        f'<span class="pill {cls}">{dot}{_age_label(age)}</span></td>')
        rows.append(
            f'<tr><td data-k="{esc(status_key)}">{status}</td>'
            + act_cell +
            f'<td data-k="{esc(sid)}"><code>{esc(sid[:8])}</code></td>'
            f'<td data-k="{esc(title_key)}">{link}<div class="muted small">{detail}</div></td>'
            f'<td class="num" data-k="{esc(info.first or "")}" title="{esc((info.first or "")[:19])} UTC">{esc(started)}'
            f'<div class="muted small">{esc(duration)}</div></td>'
            f'<td class="num" data-k="{esc(info.last or "")}" title="{esc((info.last or "")[:19])} UTC">{esc(last)}</td></tr>')

    # Archives whose source is not a session on disk: claude.ai imports, or
    # sessions whose transcript has since been deleted. They are still part of
    # the archive and belong on its index.
    n_imported = 0
    for sid, meta in sorted(archived.items(),
                            key=lambda kv: kv[1].get("last_record") or "", reverse=True):
        if sid in sessions:
            continue
        n_imported += 1
        kind = meta.get("source_kind") or _("source transcript not on disk")
        link = f'<a href="{esc(meta["file"])}">{esc(meta.get("title") or sid)}</a>'
        detail = _("{records} records &middot; {mb} MB &middot; archiver v{version} &middot; "
                   "source: {source}").format(
                       records=meta.get("records", "?"), mb=f'{meta["size_mb"]:.1f}',
                       version=esc(str(meta.get("archiver_version"))), source=esc(str(kind)))
        title_key = re.sub(r"<[^>]+>", "", link).strip().lower()

        def _loc(iso):
            try:
                return fmt_local(parse_ts(iso)) if iso else ""
            except ValueError:
                return str(iso)[:19].replace("T", " ")
        rows.append(
            f'<tr><td data-k="{_("archived")}"><span class="pill ok">{_("archived")}</span></td>'
            '<td class="activity" data-k="~"></td>'
            f'<td data-k="{esc(sid)}"><code>{esc(sid[:8])}</code></td>'
            f'<td data-k="{esc(title_key)}">{link}<div class="muted small">{detail}</div></td>'
            f'<td class="num" data-k="{esc(meta.get("started") or "")}">{esc(_loc(meta.get("started")))}</td>'
            f'<td class="num" data-k="{esc(meta.get("last_record") or "")}">{esc(_loc(meta.get("last_record")))}</td></tr>')

    counts = Counter()
    for sid in sessions:
        if sid in archived:
            counts["archived"] += 1
        else:
            counts["missing"] += 1
    search_index = [prompt_index_entry(archive_dir, meta)
                    for _sid, meta in sorted(archived.items(),
                                             key=lambda kv: kv[1].get("last_record") or "",
                                             reverse=True)]
    n_prompts = sum(len(e["prompts"]) for e in search_index)
    page = _INDEX_TEMPLATE.format(
        rows="".join(rows),
        search_json=json.dumps(search_index, ensure_ascii=False).replace("</", "<\\/"),
        lang=LANG,
        title=_("Claude Code session archive"),
        note=_("Generated {when}. &ldquo;Covered&rdquo; means the session was resumed into another "
               "transcript that <em>is</em> archived, so its records live in that file.").format(
                   when=esc(fmt_local(datetime.datetime.now(datetime.timezone.utc)))),
        placeholder=_("Search every prompt across all archives ({n} prompts)").format(n=f"{n_prompts:,}"),
        aria=_("Search prompts across all archives"),
        h_status=_("status"), h_activity=_("activity"), h_id=_("id"), h_session=_("session"),
        h_started=_("started"), h_last=_("last record"),
        i18n_json=json.dumps({
            "now": _("now"),
            "status": _("{total} matching prompt(s) in {sessions} session(s)"),
            "first200": _(" (first 200 shown)")}, ensure_ascii=False).replace("</", "<\\/"),
        summary=(_("{n} sessions on disk &middot; {archived} archived &middot; {missing} not "
                   "archived directly").format(n=len(sessions), archived=counts["archived"],
                                               missing=counts["missing"])
                 + (_(" &middot; {n} archived from imports or deleted sources").format(n=n_imported)
                    if n_imported else "")),
        refresh_meta=(f'<meta http-equiv="refresh" content="{int(refresh)}">\n'
                      if refresh else ""),
        css=_CSS,
        index_css=_INDEX_CSS,
        index_js=_INDEX_JS,
    )
    out_path.write_text(page, encoding="utf-8")
    CON.say(f"wrote {out_path} ({len(sessions)} sessions, {counts['archived']} archived"
            + (f", {n_imported} imported" if n_imported else "") + ")")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_CSS = """
:root{
  --paper:#faf7f0; --ink:#22221f; --ink-soft:#5d5b53; --ink-faint:#8d8a7f;
  --line:#dcd9cf; --line-soft:#ebe8e0; --card:#fffdf8; --code-bg:#eeebe2;
  --human:#2f6f4f; --human-bg:#e9f3ed;
  --claude:#44578c; --claude-bg:#eceff8;
  --think:#6b5b95; --think-bg:#f0ecf6;
  --system:#96762c; --system-bg:#f7efdd;
  --harness:#6f6a62; --harness-bg:#f1efe8;
  --tool:#5c5750; --tool-bg:#f0eee7;
  --error:#a33f2f; --error-bg:#fbeae6;
  --shadow:0 1px 2px rgba(20,20,15,.05), 0 2px 10px rgba(20,20,15,.04);
  --bubble:0 1px 2px rgba(20,20,15,.06), 0 3px 12px rgba(20,20,15,.05);
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --paper:#14140f; --ink:#e9e6dc; --ink-soft:#a29c8c; --ink-faint:#7d7768;
  --line:#332f25; --line-soft:#252219; --card:#1b1914; --code-bg:#201e17;
  --human:#7fc79f; --human-bg:#17251f;
  --claude:#9db0e8; --claude-bg:#191d2b;
  --think:#b8a6e0; --think-bg:#201b2b;
  --system:#e0b95a; --system-bg:#231e10;
  --harness:#a29c8c; --harness-bg:#1d1b15;
  --tool:#a29c8c; --tool-bg:#1d1b15;
  --error:#e08a76; --error-bg:#2a1712;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 2px 14px rgba(0,0,0,.35);
  --bubble:0 1px 2px rgba(0,0,0,.45), 0 3px 16px rgba(0,0,0,.3);
}}
:root[data-theme="dark"]{
  --paper:#14140f; --ink:#e9e6dc; --ink-soft:#a29c8c; --ink-faint:#7d7768;
  --line:#332f25; --line-soft:#252219; --card:#1b1914; --code-bg:#201e17;
  --human:#7fc79f; --human-bg:#17251f;
  --claude:#9db0e8; --claude-bg:#191d2b;
  --think:#b8a6e0; --think-bg:#201b2b;
  --system:#e0b95a; --system-bg:#231e10;
  --harness:#a29c8c; --harness-bg:#1d1b15;
  --tool:#a29c8c; --tool-bg:#1d1b15;
  --error:#e08a76; --error-bg:#2a1712;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 2px 14px rgba(0,0,0,.35);
  --bubble:0 1px 2px rgba(0,0,0,.45), 0 3px 16px rgba(0,0,0,.3);
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif;font-size:15.5px;line-height:1.62}
code,pre,.mono{font-family:"Cascadia Code","JetBrains Mono","SF Mono",Consolas,monospace}
a{color:var(--claude)}
.layout{display:grid;grid-template-columns:308px 1fr;max-width:1500px;margin:0 auto;min-height:100vh}
@media (max-width:960px){.layout{grid-template-columns:1fr}.sidebar{position:relative;height:auto}}
.sidebar{position:sticky;top:0;height:100vh;overflow-y:auto;border-right:1px solid var(--line);
  padding:20px 16px;background:var(--card)}
.sidebar h2{font-size:10.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--ink-faint);
  margin:20px 0 8px;font-weight:700}
.session-info{font-size:12.5px;margin:0}
.session-info dt{color:var(--ink-soft);margin-top:7px}
.session-info dd{margin:0;font-family:"Cascadia Code","JetBrains Mono",monospace;font-size:12px;word-break:break-word}
.controls{display:flex;flex-direction:column;gap:7px}
.controls input[type=search]{font:inherit;font-size:13px;padding:7px 9px;border-radius:7px;
  border:1px solid var(--line);background:var(--paper);color:var(--ink);width:100%}
.toggles{display:flex;flex-wrap:wrap;gap:5px}
.toggles label{font-size:11.5px;display:inline-flex;align-items:center;gap:4px;padding:3px 7px;
  border:1px solid var(--line);border-radius:20px;cursor:pointer;user-select:none;color:var(--ink-soft)}
.toggles label:hover{background:var(--line-soft)}
.toggles input{margin:0}
.btnrow{display:flex;gap:6px}
.btnrow button{flex:1;font:inherit;font-size:11.5px;padding:5px 8px;border-radius:6px;
  border:1px solid var(--line);background:var(--paper);color:var(--ink);cursor:pointer}
.btnrow button:hover{background:var(--line-soft)}
.toc{display:flex;flex-direction:column;gap:2px;font-size:12.5px}
.toc-item{padding:5px 8px;border-radius:6px;text-decoration:none;color:var(--ink);
  border-left:3px solid transparent;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.toc-item:hover{background:var(--line-soft)}
.toc-item.toc-human{border-left-color:var(--human);font-weight:600}
.toc-item.toc-system{border-left-color:var(--system);color:var(--ink-soft);font-size:11.5px}
.toc-item.toc-key{border-left-color:var(--claude);font-weight:700}
.toc-item.hidden{display:none}
.main{padding:30px 40px 120px;max-width:940px}
@media (max-width:760px){
  .human-turn{margin-left:0}
  .assistant-turn{margin-right:0}
}
header.mast{margin-bottom:28px;padding-bottom:18px;border-bottom:1px solid var(--line)}
header.mast h1{font-size:25px;margin:0 0 6px}
header.mast p{color:var(--ink-soft);margin:0;font-size:13.5px}
.turn{margin-bottom:12px}
.turn.filtered,.turn.unmatched{display:none}
.search-count{font-size:11px;color:var(--ink-faint);min-height:1em}
.turn-label{display:flex;align-items:center;gap:9px;margin-bottom:5px;font-size:12.5px;flex-wrap:wrap}
.turn-label .who{font-weight:700;font-family:"Cascadia Code","JetBrains Mono",monospace}
.rtag{font-size:10px;font-weight:700;padding:1px 6px;border-radius:9px;background:var(--code-bg);
  color:var(--ink-soft);letter-spacing:.04em;vertical-align:1px}
.turn-label .ts{color:var(--ink-faint);margin-left:auto;font-family:"Cascadia Code",monospace;font-size:11px}
.badge{font-size:10.5px;padding:1px 7px;border-radius:10px;background:var(--system-bg);color:var(--system)}
.badge.side{background:var(--claude-bg);color:var(--claude)}
.evidence{font-size:10.5px;color:var(--ink-faint);font-family:"Cascadia Code",monospace}
/* Chat layout: what you typed sits right, Claude answers from the left, the
   way a messaging app reads. Tool, system and harness turns stay full width --
   they are machinery, not dialogue, and indenting them would imply a speaker. */
.human-turn{margin-left:16%}
.human-turn .turn-label{flex-direction:row-reverse}
.human-turn .turn-label .ts{margin-left:0;margin-right:auto}
.human-turn .turn-label .who{color:var(--human)}
.human-turn .turn-body{background:var(--human-bg);border:1.5px solid var(--human);
  border-radius:12px 12px 4px 12px;padding:12px 16px;box-shadow:var(--bubble)}
/* Verbatim: what you typed or pasted, newlines and all. */
.human-turn .raw{white-space:pre-wrap;word-break:break-word}
.human-turn .raw.mono{font-family:"Cascadia Code","JetBrains Mono","SF Mono",Consolas,monospace;
  font-size:12.8px;line-height:1.5}
.assistant-turn{margin-right:10%}
.assistant-turn .turn-label .who{color:var(--claude)}
.assistant-turn .turn-body{background:var(--claude-bg);border:1.5px solid var(--claude);
  border-radius:12px 12px 12px 4px;padding:12px 16px;box-shadow:var(--bubble)}
.assistant-turn .turn-body>*:first-child{margin-top:0}
.assistant-turn .turn-body>*:last-child{margin-bottom:0}
.thinking-turn details{background:var(--think-bg);border-left:3px solid var(--think);
  border-radius:0 8px 8px 0}
.thinking-turn summary{cursor:pointer;padding:6px 14px;list-style:none;display:flex;gap:9px;
  align-items:center;font-size:12.5px}
.thinking-turn summary::-webkit-details-marker{display:none}
.thinking-turn summary::before{content:"\\25B8";color:var(--think)}
.thinking-turn details[open] summary::before{content:"\\25BE"}
.thinking-turn .who{color:var(--think);font-weight:700;font-family:"Cascadia Code",monospace}
.thinking-turn .turn-body{padding:2px 16px 12px;font-size:14.5px;color:var(--ink-soft)}
.system-turn .turn-label .who,.event-turn .turn-label .who{color:var(--system)}
.tool-turn>details{border:1px solid var(--line);border-radius:9px;overflow:hidden}
.system-turn .turn-body,.event-turn .turn-body{border:1px solid var(--line);
  border-radius:9px;background:var(--system-bg);
  border-left:3px solid var(--system);border-radius:0 8px 8px 0;padding:6px 14px}
.system-turn summary{cursor:pointer;font-size:12.5px;color:var(--ink-soft)}
.system-turn pre,.event-turn pre{font-size:11.5px;max-height:340px;overflow:auto}
.harness-turn details{background:var(--harness-bg);border:1px dashed var(--line);border-radius:7px}
.harness-turn summary{cursor:pointer;padding:5px 12px;font-size:12px;color:var(--ink-soft);
  list-style:none;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.harness-turn summary::-webkit-details-marker{display:none}
.harness-turn .io{padding:0 12px 10px}
.harness-turn pre{font-size:11.5px;max-height:400px;overflow:auto}
.tool-turn{margin-bottom:7px}
.tool-turn details{background:var(--tool-bg);border:1px solid var(--line);border-radius:8px}
.tool-turn.tool-error details{background:var(--error-bg);border-color:var(--error)}
.tool-turn.tool-pending details{border-style:dashed}
.tool-turn summary{cursor:pointer;padding:7px 13px;font-size:13px;list-style:none;
  display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tool-turn summary::-webkit-details-marker{display:none}
.tool-turn summary::before{content:"\\25B8";color:var(--ink-faint);flex:0 0 auto}
.tool-turn details[open] summary::before{content:"\\25BE"}
.tool-turn summary code{background:none;padding:0;color:var(--ink-soft);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;min-width:0}
.chip{font-family:"Cascadia Code","JetBrains Mono",monospace;font-size:10.5px;font-weight:700;
  letter-spacing:.03em;padding:2px 7px;border-radius:5px;background:var(--code-bg);
  color:var(--tool);flex:0 0 auto}
.harness-chip{background:var(--code-bg);color:var(--harness)}
.tool-turn.tool-error .chip{background:var(--error-bg);color:var(--error)}
.io{padding:0 13px 13px;display:grid;gap:9px}
.io-label{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-faint);margin-bottom:3px}
.io-block pre{margin:0}
pre.plain,pre.code-block{background:var(--code-bg);border:1px solid var(--line);border-radius:6px;
  padding:9px 12px;overflow-x:auto;font-size:12.5px;line-height:1.5;margin:9px 0;
  white-space:pre-wrap;word-break:break-word;max-height:640px;overflow-y:auto}
code{background:var(--code-bg);padding:1px 5px;border-radius:4px;font-size:.9em}
pre code{background:none;padding:0}
img{max-width:100%;border:1px solid var(--line);border-radius:6px}
.summary-turn,.report-turn,.usage-turn{margin-bottom:26px}
.summary-turn .who,.report-turn .who,.usage-turn .who{color:var(--ink);font-size:11px;
  letter-spacing:.08em;text-transform:uppercase}
.summary-body,.report-body,.usage-body{background:var(--card);border:1px solid var(--line);
  border-left:4px solid var(--claude);border-radius:0 10px 10px 0;padding:6px 22px 16px;box-shadow:var(--shadow)}
.report-body{border-left-color:var(--system)}
.usage-body{border-left-color:var(--human)}
.summary-body h3,.report-body h3{font-size:12.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--claude);margin:18px 0 8px}
.report-body h4{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-soft);
  margin:16px 0 6px}
.report-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media (max-width:760px){.report-grid{grid-template-columns:1fr}}
.table-wrap{overflow-x:auto;margin:9px 0}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid var(--line);padding:4px 9px;text-align:left;vertical-align:top}
th{background:var(--code-bg);font-size:11.5px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;
  font-family:"Cascadia Code",monospace;font-size:12px}
table.mini{font-size:12px}
table.mini td{padding:2px 8px}
table.usage td{font-size:12.5px}
table.usage tr.total td{font-weight:700;background:var(--line-soft)}
.callout{border-left:3px solid var(--system);background:var(--system-bg);border-radius:0 8px 8px 0;
  padding:10px 16px;margin:14px 0;font-size:13.5px}
.callout ul{margin:6px 0 0;padding-left:20px}
.muted{color:var(--ink-soft)}
.small{font-size:12px}
blockquote{border-left:3px solid var(--line);margin:9px 0;padding:2px 14px;color:var(--ink-soft)}
ul,ol{margin:8px 0;padding-left:22px}
li{margin:3px 0}
h1,h2,h3,h4,h5,h6{margin:15px 0 7px;line-height:1.3}
hr{border:none;border-top:1px solid var(--line);margin:16px 0}
del{opacity:.65}
.subagent-block>details{background:var(--card);border:1px solid var(--line);
  border-left:4px solid var(--claude);border-radius:0 10px 10px 0;box-shadow:var(--shadow)}
.subagent-block>details>summary{cursor:pointer;padding:9px 14px;font-size:13px;list-style:none;
  display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.subagent-block>details>summary::-webkit-details-marker{display:none}
.subagent-block>details>summary::before{content:"\\25B8";color:var(--ink-faint)}
.subagent-block>details[open]>summary::before{content:"\\25BE"}
.subagent-body{padding:4px 14px 14px;border-top:1px dashed var(--line)}
.page-nav{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:13px;
  padding:8px 14px;margin:0 0 18px;border:1px solid var(--line);border-radius:9px;
  background:var(--card);color:var(--ink-soft)}
.page-nav a{text-decoration:none}
.page-nav strong{color:var(--ink)}
.pill{font-size:10.5px;padding:2px 8px;border-radius:11px;font-weight:700;white-space:nowrap}
.pill.ok{background:var(--human-bg);color:var(--human)}
.pill.act{background:var(--human-bg);color:var(--human);animation:actpulse 2.4s ease-in-out infinite}
.pill.quiet{background:var(--line-soft);color:var(--ink-faint);font-weight:600}
@keyframes actpulse{0%,100%{opacity:1}50%{opacity:.55}}
.pill.stale{background:var(--system-bg);color:var(--system)}
.pill.covered{background:var(--claude-bg);color:var(--claude)}
.pill.missing{background:var(--error-bg);color:var(--error)}
"""

_JS = """
(function(){
  /* Theme: follow the OS unless the reader chose; the choice is remembered
     per browser in localStorage (wrapped: storage can be unavailable). */
  var root = document.documentElement;
  var I18N = {};
  try { I18N = JSON.parse(document.getElementById('archive-i18n').textContent) || {}; } catch (e) { I18N = {}; }
  var themeBtn = document.getElementById('theme-toggle');
  function currentDark(){
    var t = root.getAttribute('data-theme');
    if (t) return t === 'dark';
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function applyTheme(t){
    if (t) root.setAttribute('data-theme', t); else root.removeAttribute('data-theme');
    if (themeBtn) themeBtn.textContent = currentDark() ? (I18N.light || 'Light theme') : (I18N.dark || 'Dark theme');
  }
  try { applyTheme(localStorage.getItem('archive-theme') || ''); } catch (e) { applyTheme(''); }
  if (themeBtn) themeBtn.addEventListener('click', function(){
    var next = currentDark() ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem('archive-theme', next); } catch (e) {}
  });

  /* Turn search: hide every turn whose text does not contain the query.
     Lead sections (summary, usage, fidelity) always stay. */
  var search = document.getElementById('search');
  var count = document.getElementById('search-count');
  if (search) search.addEventListener('input', function(){
    var q = search.value.toLowerCase();
    var shown = 0, total = 0;
    document.querySelectorAll('.turn').forEach(function(el){
      if (el.classList.contains('summary-turn') || el.classList.contains('usage-turn')
          || el.classList.contains('report-turn')) return;
      total++;
      var hit = q === '' || el.textContent.toLowerCase().indexOf(q) !== -1;
      el.classList.toggle('unmatched', !hit);
      if (hit) shown++;
    });
    if (count) count.textContent = q === '' ? '' :
      (I18N.match || '{shown} of {total} turns match').replace('{shown}', shown).replace('{total}', total);
  });

  var lanes = ['thinking','tool','harness','system','subagent'];
  lanes.forEach(function(lane){
    var box = document.getElementById('lane-' + lane);
    if (!box) return;
    box.addEventListener('change', function(){
      document.querySelectorAll('.turn[data-lane="' + lane + '"]').forEach(function(el){
        el.classList.toggle('filtered', !box.checked);
      });
    });
  });
  var expand = document.getElementById('expand-all');
  var collapse = document.getElementById('collapse-all');
  if (expand) expand.addEventListener('click', function(){
    document.querySelectorAll('.turn details').forEach(function(d){ d.open = true; });
  });
  if (collapse) collapse.addEventListener('click', function(){
    document.querySelectorAll('.turn details').forEach(function(d){ d.open = false; });
  });
  var search = document.getElementById('filter');
  if (search) search.addEventListener('input', function(){
    var q = search.value.toLowerCase();
    document.querySelectorAll('.toc-item').forEach(function(a){
      if (a.classList.contains('toc-key')) return;
      a.classList.toggle('hidden', q !== '' && a.textContent.toLowerCase().indexOf(q) === -1);
    });
  });
  function jump(dir){
    var anchors = Array.prototype.slice.call(
      document.querySelectorAll('.human-turn[id], .system-turn[id], .event-turn[id]'))
      .filter(function(el){ return !el.classList.contains('filtered'); });
    if (!anchors.length) return;
    var y = window.scrollY + 8, target = null;
    if (dir > 0) { for (var i=0;i<anchors.length;i++){ if (anchors[i].offsetTop > y + 4){ target = anchors[i]; break; } } }
    else { for (var j=anchors.length-1;j>=0;j--){ if (anchors[j].offsetTop < y - 4){ target = anchors[j]; break; } } }
    if (target) window.scrollTo({top: target.offsetTop - 8, behavior: 'smooth'});
  }
  document.addEventListener('keydown', function(e){
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (e.key === 'j') { jump(1); e.preventDefault(); }
    if (e.key === 'k') { jump(-1); e.preventDefault(); }
    if (e.key === '/') { var s = document.getElementById('filter'); if (s) { s.focus(); e.preventDefault(); } }
  });
})();
"""

def _shell_words() -> dict:
    """The page shell's own words, in the document language."""
    return {
        "transcript": _("Session Transcript"),
        "search": _("Search turns"),
        "filter": _("Filter contents  ( / )"),
        "filter_short": _("Filter contents"),
        "thinking": _("thinking"), "tools": _("tools"), "harness": _("harness"),
        "events": _("events"), "subagents": _("subagents"),
        "expand": _("Expand all"), "collapse": _("Collapse all"), "dark": _("Dark theme"),
        "session": _("Session"), "contents": _("Contents"),
        "note": _("Timestamps are local; hover for UTC. <kbd>j</kbd>/<kbd>k</kbd> jump between "
                  "human turns, <kbd>/</kbd> filters the contents list, the search box hides turns "
                  "that do not match. Thinking, tool I/O and harness events are collapsed &mdash; "
                  "use the toggles to hide a lane entirely."),
    }


_TEMPLATE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{title} — {shell[transcript]}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{css}</style>
</head>
<body>
<script type="application/json" id="archive-meta">{meta_json}</script>
<script type="application/json" id="archive-i18n">{i18n_json}</script>
<div class="layout">
  <nav class="sidebar">
    <div class="controls">
      <input type="search" id="search" placeholder="{shell[search]}" aria-label="{shell[search]}">
      <div class="search-count" id="search-count"></div>
      <input type="search" id="filter" placeholder="{shell[filter]}" aria-label="{shell[filter_short]}">
      <div class="toggles">
        <label><input type="checkbox" id="lane-thinking" checked> {shell[thinking]}</label>
        <label><input type="checkbox" id="lane-tool" checked> {shell[tools]}</label>
        <label><input type="checkbox" id="lane-harness" checked> {shell[harness]}</label>
        <label><input type="checkbox" id="lane-system" checked> {shell[events]}</label>
        <label><input type="checkbox" id="lane-subagent" checked> {shell[subagents]}</label>
      </div>
      <div class="btnrow">
        <button id="expand-all" type="button">{shell[expand]}</button>
        <button id="collapse-all" type="button">{shell[collapse]}</button>
        <button id="theme-toggle" type="button">{shell[dark]}</button>
      </div>
    </div>
    <h2>{shell[session]}</h2>
    <dl class="session-info">{session_info}</dl>
    <h2>{shell[contents]}</h2>
    <div class="toc">{toc_html}</div>
  </nav>
  <main class="main">
    <header class="mast">
      <h1>{title}</h1>
      <p>{subtitle}</p>
      <p class="muted small">{shell[note]}</p>
    </header>
    {page_nav}
    {lead_html}
    {body_html}
    {page_nav}
  </main>
</div>
<script>{js}</script>
</body>
</html>
"""

_INDEX_TEMPLATE = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
{refresh_meta}<style>{css}
{index_css}
</style>
</head>
<body>
<div class="layout"><main class="main">
<header class="mast">
  <h1>{title}</h1>
  <p>{summary}</p>
  <p class="muted small">{note}</p>
</header>
<div class="archive-search">
  <input type="search" id="archive-search" placeholder="{placeholder}"
         aria-label="{aria}">
  <div class="muted small" id="search-status"></div>
  <div id="search-results" class="search-results" hidden></div>
</div>
<script type="application/json" id="search-index">{search_json}</script>
<script type="application/json" id="archive-i18n">{i18n_json}</script>
<div class="table-wrap"><table>
<thead><tr><th class="sortable" data-i="0">{h_status}</th>
<th class="sortable" data-i="1">{h_activity}</th>
<th class="sortable" data-i="2">{h_id}</th>
<th class="sortable" data-i="3">{h_session}</th>
<th class="sortable num" data-i="4">{h_started}</th>
<th class="sortable num sorted-desc" data-i="5">{h_last}</th></tr></thead>
<tbody>{rows}</tbody>
</table></div>
</main></div>
<script>{index_js}</script>
</body>
</html>
"""

_INDEX_JS = """
(function () {
  var I18N = {};
  try { I18N = JSON.parse(document.getElementById('archive-i18n').textContent) || {}; } catch (e) { I18N = {}; }
  /* Activity ages decay live: recompute from data-ts once a minute. The page
     cannot see new records without regeneration (see --watch), so a session
     can only go quiet on screen, never freshly active. */
  function ageLabel(s) {
    if (s < 90) return I18N.now || 'now';
    if (s < 3600) return Math.floor(s / 60) + 'm';
    if (s < 86400) return Math.floor(s / 3600) + 'h';
    return Math.floor(s / 86400) + 'd';
  }
  function tick() {
    document.querySelectorAll('td.activity[data-ts]').forEach(function (td) {
      var t = Date.parse(td.getAttribute('data-ts'));
      if (isNaN(t)) return;
      var s = (Date.now() - t) / 1000;
      var pill = td.querySelector('.pill');
      if (!pill) return;
      var active = s < 600;
      pill.className = 'pill ' + (active ? 'act' : 'quiet');
      pill.innerHTML = (active ? '\\u25CF ' : '') + ageLabel(s);
    });
  }
  tick();
  setInterval(tick, 60000);

  /* Cross-archive search: every human prompt of every archive is embedded
     as JSON at index time (see prompt_index_entry); matches deep-link to
     the prompt's anchor on its page, and the session table narrows to the
     sessions that matched. */
  var idxEl = document.getElementById('search-index');
  var box = document.getElementById('archive-search');
  var out = document.getElementById('search-results');
  var status = document.getElementById('search-status');
  var entries = [];
  try { entries = JSON.parse(idxEl ? idxEl.textContent : '[]'); } catch (e) { entries = []; }
  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function snippet(text, q) {
    var i = text.toLowerCase().indexOf(q), a = Math.max(0, i - 70), b = Math.min(text.length, i + q.length + 90);
    return (a > 0 ? '\\u2026' : '') + escapeHtml(text.slice(a, i)) + '<mark>' + escapeHtml(text.slice(i, i + q.length))
      + '</mark>' + escapeHtml(text.slice(i + q.length, b)) + (b < text.length ? '\\u2026' : '');
  }
  function narrowTable(sids) {
    document.querySelectorAll('table tbody tr').forEach(function (tr) {
      var cell = tr.cells[2];
      var sid = cell ? (cell.getAttribute('data-k') || '') : '';
      tr.hidden = sids !== null && !sids[sid];
    });
  }
  if (box) box.addEventListener('input', function () {
    var q = box.value.trim().toLowerCase();
    if (q.length < 2) { out.hidden = true; out.innerHTML = ''; status.textContent = ''; narrowTable(null); return; }
    var hits = [], sids = {}, total = 0;
    entries.forEach(function (e) {
      var inTitle = e.title.toLowerCase().indexOf(q) !== -1;
      e.prompts.forEach(function (p) {
        if (p.text.toLowerCase().indexOf(q) !== -1) {
          total++; sids[e.session_id] = true;
          if (hits.length < 200) hits.push({e: e, p: p});
        }
      });
      if (inTitle) sids[e.session_id] = true;
    });
    status.textContent = (I18N.status || '{total} matching prompt(s) in {sessions} session(s)')
      .replace('{total}', total).replace('{sessions}', Object.keys(sids).length)
      + (total > 200 ? (I18N.first200 || ' (first 200 shown)') : '');
    out.innerHTML = hits.map(function (h) {
      return '<a class="hit" href="' + escapeHtml(h.p.href) + '"><span class="hit-meta"><code>'
        + escapeHtml(h.e.session_id.slice(0, 8)) + '</code> ' + (h.p.tag ? '<span class="rtag">' + escapeHtml(h.p.tag) + '</span> ' : '')
        + escapeHtml(h.e.title) + '</span><span class="hit-text">' + snippet(h.p.text, q) + '</span></a>';
    }).join('');
    out.hidden = hits.length === 0;
    narrowTable(sids);
  });

  var table = document.querySelector('table');
  if (!table) return;
  var tbody = table.tBodies[0];
  var heads = table.querySelectorAll('th.sortable');
  function key(row, i) {
    var cell = row.cells[i];
    return cell ? (cell.getAttribute('data-k') || cell.textContent).trim().toLowerCase() : '';
  }
  heads.forEach(function (th) {
    th.addEventListener('click', function () {
      var i = +th.getAttribute('data-i');
      var desc = !th.classList.contains('sorted-desc');
      heads.forEach(function (h) { h.classList.remove('sorted-asc', 'sorted-desc'); });
      th.classList.add(desc ? 'sorted-desc' : 'sorted-asc');
      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function (a, b) {
        var x = key(a, i), y = key(b, i);
        if (x === y) return 0;
        if (x === '') return 1;          /* blanks always last */
        if (y === '') return -1;
        return (x < y ? -1 : 1) * (desc ? -1 : 1);
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });
})();
"""

_INDEX_CSS = """
.layout{grid-template-columns:1fr}
.main{max-width:1150px;margin:0 auto;padding:44px 28px 90px}
th.sortable{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable:hover{text-decoration:underline}
th.sortable::after{content:"\\2195";opacity:.25;margin-left:.4em;font-size:.85em}
th.sorted-asc::after{content:"\\2191";opacity:.8}
th.sorted-desc::after{content:"\\2193";opacity:.8}
.archive-search{margin:0 0 18px}
.archive-search input{font:inherit;font-size:14px;padding:9px 12px;border-radius:8px;width:100%;
  border:1px solid var(--line);background:var(--card);color:var(--ink)}
.search-results{display:flex;flex-direction:column;gap:6px;margin-top:10px;max-height:60vh;overflow:auto}
.search-results .hit{display:block;text-decoration:none;color:var(--ink);padding:8px 12px;border-radius:8px;
  border:1px solid var(--line);background:var(--card)}
.search-results .hit:hover{background:var(--line-soft)}
.search-results .hit-meta{display:block;font-size:11.5px;color:var(--ink-soft);margin-bottom:3px}
.search-results .hit-text{display:block;font-size:13px}
.search-results mark{background:var(--system-bg);color:var(--ink);padding:0 2px;border-radius:3px}
tr[hidden]{display:none}
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def slugify(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:60] or "session"


_KNOWN_EXT = {".html", ".htm", ".txt", ".md", ".tex", ".pdf"}


def out_stem(arg: str) -> Path:
    """--out names the output *stem*: each format adds its own extension.

    'report.pdf' and 'report' both mean report.html / report.txt / ...; an
    unfamiliar suffix ('v2.3') is kept as part of the name."""
    p = Path(arg)
    if p.suffix.lower() in _KNOWN_EXT:
        p = p.with_suffix("")
    return p.with_name(p.name + ".html")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session_id", nargs="?", help="transcript UUID (the .jsonl filename)")
    ap.add_argument("--version", action="version", version=f"transcript_archiver {VERSION}")
    ap.add_argument("--title", default=None, help="page title; defaults to the session's own ai-title")
    ap.add_argument("--lang", default=None, choices=LANGS,
                    help="language of the archiver's own words (headings, labels, notes, the "
                         "index); the conversation itself is never translated. Default: "
                         "$CLAUDE_ARCHIVE_LANG, else en")
    ap.add_argument("--out", default=None,
                    help="output path stem for a single archive (each format adds its "
                         "own extension); overrides --archive-dir naming")
    ap.add_argument("--summary-file", default=None,
                    help="HTML fragment (h3/ul blocks) rendered as the session summary")
    ap.add_argument("--projects-root", default=str(Path.home() / ".claude" / "projects"),
                    help="where Claude Code writes sessions (default: ~/.claude/projects)")
    ap.add_argument("--cowork-root", default=str(default_cowork_root()),
                    help="base directory of Claude Desktop cowork (local agent mode) "
                         "sessions, merged into discovery when it exists; pass an "
                         "empty string to disable")
    ap.add_argument("--archive-dir", default=str(DEFAULT_ARCHIVE_DIR),
                    help="where archives and index.html go (default: $CLAUDE_ARCHIVE_DIR "
                         "or ~/claude-archives)")
    ap.add_argument("--no-follow-chain", action="store_true",
                    help="archive exactly the id given, even if a more complete continuation exists")
    ap.add_argument("--max-tool-output", type=int, default=16384,
                    help="elide the middle of tool output longer than this many chars (0 = never)")
    ap.add_argument("--full", action="store_true", help="never elide tool output")
    ap.add_argument("--format", default="html",
                    help="comma-separated: html, text, markdown (md), latex, pdf "
                         "(default: html). pdf compiles the LaTeX with xelatex")
    ap.add_argument("--tool-output", choices=("on", "off"), default="on",
                    help="include tool input and output (default: on). Independent of "
                         "--format. With it off, a tool call is a single labelled line, "
                         "which is usually what you want for latex and pdf: full I/O turns "
                         "a large session into a several-hundred-page document")
    ap.add_argument("--fragment", action="store_true",
                    help="LaTeX body only, no preamble -- ready to \\input into another "
                         "document (requires --format latex)")
    ap.add_argument("--paginate", type=int, default=0, metavar="N",
                    help="split the HTML into pages of N turns (0 = single page). "
                         "Page 1 keeps the summary, usage and fidelity sections; "
                         "the sidebar contents link across pages")
    ap.add_argument("--subagents", choices=("on", "off"), default="on",
                    help="render subagent transcripts (<session>/subagents/agent-*.jsonl) "
                         "as appendix sections (default: on). With off, the files are "
                         "still listed in the fidelity report and their usage still "
                         "counts, but their content is not rendered")
    ap.add_argument("--index", action="store_true",
                    help="rebuild index.html for the archive directory and exit")
    ap.add_argument("--watch", type=int, default=None, metavar="SECONDS",
                    help="with --index: regenerate every SECONDS (min 30) until "
                         "interrupted, and stamp the page to reload itself, so "
                         "the activity column stays fresh")
    ap.add_argument("--import-claude-ai", metavar="CONVERSATIONS_JSON",
                    help="import conversations from a claude.ai data export "
                         "(conversations.json) instead of a local session")
    ap.add_argument("--conversation", default=None,
                    help="with --import-claude-ai: only conversations whose name or "
                         "uuid contains this (case-insensitive)")
    ap.add_argument("--list-conversations", action="store_true",
                    help="with --import-claude-ai: list the export's conversations "
                         "and exit")
    ap.add_argument("--verbose", action="store_true",
                    help="print per-step detail (files parsed, compile passes)")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing but warnings; the audit log still records everything")
    ap.add_argument("--log-dir", default=None,
                    help="where the per-run audit log goes (default: <archive-dir>/logs)")
    return ap


def _validate(ap: argparse.ArgumentParser, args: argparse.Namespace, formats: tuple) -> None:
    """Reject option combinations that would otherwise be silently ignored."""
    if args.watch is not None and not args.index:
        ap.error("--watch only makes sense with --index")
    if (args.conversation or args.list_conversations) and not args.import_claude_ai:
        ap.error("--conversation and --list-conversations require --import-claude-ai")
    if args.fragment and "pdf" in formats:
        ap.error("--fragment cannot be compiled (it has no preamble); "
                 "use --format latex, or drop --fragment for a PDF")
    if args.fragment and "latex" not in formats:
        ap.error("--fragment applies to --format latex")
    if args.verbose and args.quiet:
        ap.error("--verbose and --quiet are mutually exclusive")


def main(argv: list[str] | None = None) -> None:
    ap = build_parser()
    args = ap.parse_args(argv)
    CON.verbose, CON.quiet = args.verbose, args.quiet
    lang = args.lang or os.environ.get("CLAUDE_ARCHIVE_LANG") or "en"
    if lang not in LANGS:
        ap.error(f"CLAUDE_ARCHIVE_LANG={lang!r} is not one of {', '.join(LANGS)}")
    global LANG
    LANG = lang

    projects_root = Path(args.projects_root)
    cowork_root = Path(args.cowork_root) if args.cowork_root else None
    archive_dir = Path(args.archive_dir)
    log_dir = Path(args.log_dir) if args.log_dir else archive_dir / "logs"
    run_started = datetime.datetime.now()
    label = args.session_id or ("index" if args.index else "import")

    formats = tuple("markdown" if f.strip().lower() == "md" else f.strip().lower()
                    for f in args.format.split(",") if f.strip())
    unknown = [f for f in formats
               if f not in ("html", "text", "markdown", "latex", "pdf")]
    if unknown:
        ap.error(f"unknown --format value(s): {', '.join(unknown)} "
                 "(choose from html, text, markdown, latex, pdf)")
    _validate(ap, args, formats)

    outcome = "ok"
    try:
        _run(args, ap, projects_root, cowork_root, archive_dir, formats)
    except SystemExit as e:
        if e.code not in (None, 0):
            outcome = f"failed: {e.code}"
            CON.note(str(e.code)) if isinstance(e.code, str) else None
        raise
    except KeyboardInterrupt:
        outcome = "interrupted"
        raise
    except Exception as e:
        outcome = f"crashed: {type(e).__name__}: {e}"
        raise
    finally:
        path = write_audit_log(log_dir, sys.argv, run_started, outcome, label)
        if path:
            CON.detail(f"audit log: {path}")


def _run(args, ap, projects_root: Path, cowork_root, archive_dir: Path, formats: tuple) -> None:
    if args.index:
        if args.watch:
            import time
            period = max(30, args.watch)
            CON.say(f"watching: regenerating the index every {period}s (Ctrl+C to stop)")
            try:
                while True:
                    build_index(archive_dir, projects_root, archive_dir / "index.html",
                                sessions=scan_all_sessions(projects_root, cowork_root),
                                refresh=period)
                    time.sleep(period)
            except KeyboardInterrupt:
                return
        build_index(archive_dir, projects_root, archive_dir / "index.html",
                    sessions=scan_all_sessions(projects_root, cowork_root))
        return

    if args.import_claude_ai:
        convs = load_claude_ai_export(Path(args.import_claude_ai))
        if args.conversation:
            q = args.conversation.lower()
            convs = [c for c in convs
                     if q in (c.get("name") or "").lower()
                     or q in (c.get("uuid") or "").lower()]
        if args.list_conversations or not convs:
            if not convs:
                CON.say("no conversation matches; the export contains:")
            for c in load_claude_ai_export(Path(args.import_claude_ai)):
                CON.say(f"  {(c.get('uuid') or '?')[:8]}  "
                        f"{(c.get('created_at') or '')[:10]}  "
                        f"{len(c.get('chat_messages') or []):4d} msgs  "
                        f"{c.get('name') or '(untitled)'}")
            if not args.list_conversations and not convs:
                sys.exit(1)
            return
        import tempfile
        with tempfile.TemporaryDirectory(prefix="claude-ai-import-") as td:
            troot = Path(td)
            for c in convs:
                sid = c.get("uuid") or "claude-ai-import"
                recs = claude_ai_records(c)
                (troot / f"{sid}.jsonl").write_text(
                    "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                    encoding="utf-8")
            summary_inner = (Path(args.summary_file).read_text(encoding="utf-8")
                             if args.summary_file else
                             "<p><em>" + _("Imported from a claude.ai data export. Pass "
                                           "<code>--summary-file</code> for a hand-written "
                                           "summary.") + "</em></p>")
            for c in convs:
                sid = c.get("uuid") or "claude-ai-import"
                title = args.title or c.get("name") or sid
                out = (out_stem(args.out) if args.out and len(convs) == 1 else
                       archive_dir / f"{sid[:8]}_{slugify(title)}.html")
                build(sid, title, out, summary_inner, troot,
                      follow_chain=False,
                      max_tool_output=0 if args.full else args.max_tool_output,
                      formats=formats, fragment=args.fragment,
                      tool_output=args.tool_output, subagents=args.subagents,
                      paginate=args.paginate, source_kind="claude.ai")
        return

    if not args.session_id:
        ap.error("a session id is required (or use --index or --import-claude-ai)")

    sessions = scan_all_sessions(projects_root, cowork_root)
    CON.detail(f"{len(sessions)} sessions found under {projects_root}"
               + (f" and {cowork_root}" if cowork_root and cowork_root.is_dir() else ""))
    if args.session_id not in sessions:
        sys.exit(f"No {args.session_id}.jsonl under {projects_root}"
                 + (f" or {cowork_root}" if cowork_root and cowork_root.is_dir() else ""))
    title = args.title or sessions[args.session_id].title or args.session_id

    if args.summary_file:
        summary_inner = Path(args.summary_file).read_text(encoding="utf-8")
    else:
        summary_inner = (
            "<p><em>" + _("No summary provided. Write one covering Activities, Key findings, What "
                          "this allows going forward, and Generated artifacts, save it as an HTML "
                          "fragment, and re-run with <code>--summary-file</code>.") + "</em></p>")

    # Name the file after the transcript actually archived, not the id typed in --
    # otherwise a resumed session gets filed under the id of its own earlier half.
    naming_id = args.session_id
    if not args.no_follow_chain:
        naming_id, _rel = resolve_chain(args.session_id, sessions)
    out_path = out_stem(args.out) if args.out else (
        archive_dir / f"{naming_id}_{slugify(title)}.html")

    build(args.session_id, title, out_path, summary_inner, projects_root,
          follow_chain=not args.no_follow_chain,
          max_tool_output=0 if args.full else args.max_tool_output,
          formats=formats, fragment=args.fragment,
          tool_output=args.tool_output, sessions=sessions,
          subagents=args.subagents, paginate=args.paginate)


if __name__ == "__main__":
    main()
