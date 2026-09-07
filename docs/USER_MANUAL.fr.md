---
title: "claude-session-publisher — Manuel de l'utilisateur"
subtitle: "transcript_archiver.py v2.8.0"
source-digest: "cb33ce2647306476"
---

# claude-session-publisher — Manuel de l'utilisateur

[English](USER_MANUAL.md) · [Português (Brasil)](USER_MANUAL.pt-BR.md) · [Español](USER_MANUAL.es.md) · [Deutsch](USER_MANUAL.de.md) · **Français**

*Traduction du manuel anglais, qui fait référence ; les commandes, noms de fichiers, options et blocs de code restent comme dans l'original.*

`transcript_archiver.py` transforme une conversation Claude en un document
autonome — HTML, texte brut, Markdown, LaTeX ou PDF — accompagné d'un rapport
de fidélité qui rapproche chaque enregistrement source de ce que la page
montre. Ce manuel est la référence complète : chaque option, chaque sortie,
chaque fonctionnalité et chaque limite connue. Le README est la page produit ;
`AGENTS.md` reprend la même information rédigée pour un agent IA qui pilote
l'outil.

Un seul fichier, Python 3.9+, bibliothèque standard uniquement. Aucune
installation :

```bash
python transcript_archiver.py --version
python transcript_archiver.py --help
```

## 1. Démarrage rapide

```bash
# archiver une session Claude Code en HTML (le format par défaut)
python transcript_archiver.py <session-id>

# tous les formats d'un coup
python transcript_archiver.py <session-id> --format html,text,markdown,latex,pdf

# reconstruire la page d'index de tout ce qui est sur le disque
python transcript_archiver.py --index

# l'essayer sur la conversation-vitrine fournie
python transcript_archiver.py 0000c0de-cafe-4000-8000-00000000f00d \
    --projects-root examples --archive-dir demo --format html,markdown,pdf
```

L'identifiant de session est le nom du fichier `.jsonl` sous
`~/.claude/projects/<project>/`. `--index` liste toutes les sessions qu'il
trouve avec leur identifiant et leur titre : lancez-le d'abord si vous ne
connaissez pas l'identifiant.

## 2. Sources

| Source | Comment | Remarques |
|---|---|---|
| Claude Code CLI / application de bureau | par défaut ; sessions sous `--projects-root` (`~/.claude/projects`) | format natif |
| Claude Code web/mobile ponté vers votre machine | idem | les enregistrements du pont voient leur chaîne résolue en une seule conversation |
| *Cowork* de Claude Desktop (mode agent local) | `--cowork-root` (détecté automatiquement selon la plateforme) | même schéma d'enregistrements, répertoire de base différent ; `audit.jsonl` est ignoré. Testé uniquement sur données synthétiques |
| Conversations claude.ai, chat Claude Desktop, application mobile | `--import-claude-ai conversations.json` | depuis Settings → Privacy → Export data. Conversations autonomes seulement ; pas de conversations de Projet, pas de données de consommation ni de modèle (la page le dit) |
| Sessions Claude Code dans le nuage jamais pontées | non archivable | rien n'est écrit sur votre disque |

Détection automatique du *cowork* :
`%APPDATA%\Claude\local-agent-mode-sessions` sous Windows,
`~/Library/Application Support/Claude/local-agent-mode-sessions` sous macOS,
`~/.config/Claude/local-agent-mode-sessions` ailleurs. Passez
`--cowork-root ""` pour désactiver.

## 3. Référence de la ligne de commande

Toute entrée et toute sortie sont accessibles depuis la ligne de commande ;
rien n'est figé dans le code. `--help` affiche chaque option avec sa valeur par
défaut.

### Positionnel

| | |
|---|---|
| `session_id` | UUID de la transcription (le nom du fichier `.jsonl`). Facultatif avec `--index` ou `--import-claude-ai`. |

### Découverte et emplacement

| Option | Par défaut | Signification |
|---|---|---|
| `--projects-root DIR` | `~/.claude/projects` | où Claude Code écrit les sessions |
| `--cowork-root DIR` | automatique selon la plateforme | sessions *cowork* de Claude Desktop, intégrées à la découverte quand le répertoire existe ; `""` désactive |
| `--archive-dir DIR` | `$CLAUDE_ARCHIVE_DIR` ou `~/claude-archives` | où vont les archives, `index.html` et `logs/` |
| `--out PATH` | — | **racine** du chemin de sortie pour une archive unique ; chaque format ajoute sa propre extension (`--out report.pdf --format html` écrit `report.html`). Remplace la nomenclature de `--archive-dir` |
| `--title TEXT` | l'`ai-title` de la session elle-même | titre de la page ; détermine aussi le *slug* du nom de fichier. Réarchiver avec un titre différent écrit un nouveau fichier |
| `--summary-file FILE` | texte d'exemple | fragment HTML (blocs `h3`/`ul`) rendu comme résumé de session écrit à la main |

### Contenu

| Option | Par défaut | Signification |
|---|---|---|
| `--format LIST` | `html` | séparé par des virgules : `html`, `text`, `markdown` (ou `md`), `latex`, `pdf` |
| `--tool-output on\|off` | `on` | inclure l'entrée et la sortie des outils. Indépendant de `--format`. `off` réduit chaque appel d'outil à une ligne étiquetée — en général ce que l'on veut pour LaTeX/PDF |
| `--max-tool-output N` | `16384` | élider le milieu de toute sortie d'outil dépassant N caractères ; chaque élision est comptée sur la page. `0` = jamais |
| `--full` | désactivé | ne jamais élider (équivaut à `--max-tool-output 0`) |
| `--subagents on\|off` | `on` | rendre les transcriptions de sous-agents en sections d'annexe. Avec `off` elles restent listées dans le rapport de fidélité et leur consommation compte toujours |
| `--no-follow-chain` | désactivé | archiver exactement l'identifiant donné même s'il existe une continuation plus complète |
| `--fragment` | désactivé | avec `--format latex` : le corps seul, sans préambule, translittéré pour compiler sous pdflatex comme sous XeLaTeX. Ne peut pas être combiné avec `pdf` |
| `--paginate N` | `0` | découpe le HTML en pages de N tours ; la page 1 conserve les sections résumé, consommation et fidélité ; la barre latérale relie les pages |
| `--lang CODE` | `$CLAUDE_ARCHIVE_LANG` ou `en` | `en`, `pt-BR`, `es`, `de`, `fr` : la langue des mots propres à l'archiveur dans tous les formats et dans l'index. La conversation n'est jamais traduite (voir §4, *Langue*) |

### Index

| Option | Signification |
|---|---|
| `--index` | reconstruire `index.html` dans `--archive-dir` et quitter |
| `--watch SECONDS` | avec `--index` : régénérer toutes les SECONDS (minimum 30) jusqu'à Ctrl+C, et marquer la page pour qu'elle se recharge ; à l'arrêt, l'index est écrit une fois de plus afin de ne plus se recharger |

### Import claude.ai

| Option | Signification |
|---|---|
| `--import-claude-ai FILE` | importer des conversations depuis un `conversations.json` de claude.ai |
| `--conversation TEXT` | seulement les conversations dont le nom ou l'uuid contient TEXT (sans distinction de casse) |
| `--list-conversations` | lister les conversations de l'export et quitter |

### Contrôle de sortie et journalisation

| Option | Signification |
|---|---|
| `--verbose` | détail par étape (fichiers analysés, passes de compilation, chemin du journal d'audit) |
| `--quiet` | n'afficher que les avertissements ; le journal d'audit enregistre toujours tout |
| `--log-dir DIR` | où va le journal d'audit de chaque exécution (par défaut `<archive-dir>/logs/`) |
| `--version` | afficher la version de l'archiveur et quitter |
| `--help` | référence des options |

Les combinaisons invalides sont rejetées avant toute écriture : `--watch` sans
`--index` ; `--conversation`/`--list-conversations` sans
`--import-claude-ai` ; `--fragment` sans `latex` ou avec `pdf` ; `--verbose`
avec `--quiet` ; une valeur inconnue de `--format`.

## 4. Ce qui est produit

### Fichiers

Dans `--archive-dir` (ou à la racine de `--out`), un fichier par format :
`<session-id>_<title-slug>.html|.txt|.md|.tex|.pdf`. Un corps LaTeX issu de
`--fragment` est `<stem>_fragment.tex`. Le HTML paginé ajoute
`<stem>_p2.html`, `<stem>_p3.html`, …. Les imports claude.ai sont nommés
`<uuid-prefix>_<slug>`. `--index` écrit `index.html`. Chaque exécution écrit
`logs/<timestamp>_<label>.log`.

Lorsqu'une session est une conversation reprise ou pontée, le fichier prend le
nom de la transcription réellement archivée (le fichier le plus complet de la
chaîne), et la page consigne quel identifiant a été demandé.

### La page

Chaque format porte, dans cet ordre : le **résumé de session** (écrit à la main
via `--summary-file`, sinon un texte d'exemple), la **consommation et le
coût**, le **rapport de fidélité**, puis la **transcription**, puis les
**transcriptions de sous-agents** en annexes.

Types de tours et façon dont chaque format les montre :

| Tour | HTML | texte / Markdown | LaTeX / PDF |
|---|---|---|---|
| Invite humaine (P*n*) | bulle alignée à droite, mot pour mot, chasse fixe si en colonnes, URL liées | mot pour mot, jamais remis en forme (Markdown : encadré) | encadré mot pour mot |
| Réponse de Claude (R*n*) | markdown rendu | prose remise en forme (Markdown : markdown vivant) | markdown → LaTeX |
| Réflexion | replié ; vide en pratique (voir §7) | étiquetée | encadré étiqueté |
| Appel d'outil | entrée/sortie repliée, états d'erreur et en attente, captures d'écran | entrée/sortie complète ou une ligne (`--tool-output`) | entrée/sortie complète ou encadré au titre seul |
| Image collée | intégrée | annoncée comme omise | annoncée comme omise |
| Harness / système / événement | voie repliée avec la preuve de classification | blocs étiquetés | encadrés étiquetés |
| Transcription de sous-agent | annexe repliable, liée depuis l'appel qui l'a créée | section d'annexe | section d'annexe |

### Langue

`--lang pt-BR|es|de|fr` (ou la variable d'environnement
`CLAUDE_ARCHIVE_LANG` ; l'option l'emporte ; par défaut `en`) fixe la langue de
tout ce que l'archiveur écrit lui-même : l'habillage de la page et ses
commandes, les libellés des tours, les informations de session, les notes de
consommation et de coût, le rapport de fidélité, l'annexe des sous-agents, les
notes de format des sorties texte/Markdown/LaTeX, et la page d'index.
`<html lang>` et le champ `lang` des métadonnées intégrées consignent le choix ;
le LaTeX autonome charge polyglossia quand il est installé, garde **l'anglais
comme langue par défaut** — la prose de la conversation est coupée et espacée
comme de l'anglais, de sorte qu'une page en français n'insère jamais d'espaces
avant le `!` de Claude — et n'enveloppe dans la langue du document que les mots
propres à l'archiveur. Un `--fragment` compose ces mots avec des macros
d'accent (`\'{e}`, `\"{a}`, `\ss{}`) pour que pdflatex les imprime intacts, et
ne les compte jamais dans la note de perte du fragment.

La conversation n'est jamais traduite. Invites, réponses, réflexion, noms
d'outils, entrées et sorties d'outils, texte système et du *harness*, noms de
modèles, titres, chemins, dates (ISO) et nombres sont les mêmes octets dans
toutes les langues — la suite rend le fichier de test dans les cinq et vérifie
que chaque fragment de conversation de la page anglaise est présent mot pour
mot dans les autres. Les badges d'événements et les libellés de pièces jointes
sont traduits là où ils sont rendus ; les noms de types d'enregistrements des
tableaux de fidélité (`human turn`, `tool_use`, …) relèvent du vocabulaire de
l'analyseur et restent en anglais, tout comme l'estampille `archiver v…` que
l'index relit. Le journal d'audit, la console (`--verbose`) et `--help`
restent en anglais quelle que soit la langue. Un code inconnu — dans l'option
ou dans la variable — est refusé avant toute écriture.

### Étiquettes de référence

Chaque invite humaine est `P1, P2, …` et chaque réponse `R1, R2, …`,
séquentielles au sein du document ; les tours de sous-agents sont préfixés
`A1.`, `A2.` (d'où `A2.R4`). En HTML, les étiquettes sont des ancres :
`page.html#P32` mène directement à l'invite.

### Rapport de fidélité

Chaque enregistrement source est **rendu** (a produit un ou plusieurs tours),
**replié** (un résultat d'outil absorbé dans son appel), ou **compté**
(métadonnées sans contenu de transcription — et lignes corrompues). Les trois
nombres sont rapprochés du nombre d'enregistrements de la source sur la page ;
s'ils ne s'additionnent pas, la page le dit au lieu de le cacher. Le rapport
liste aussi les enregistrements par type, les blocs de contenu, ce qui a été
rendu et ce qui a été compté, la preuve humain-contre-injecté par
enregistrement, les fichiers de sous-agents, et les réserves (blocs de
réflexion vides, appels d'outils non résolus, heure de l'instantané comparée au
dernier enregistrement de la source).

### Consommation et coût

Jetons par modèle dédoublonnés par `requestId` — une réponse de l'API est
écrite sous forme de plusieurs enregistrements répétant la même consommation,
et les sommer surestime la sortie d'environ 2,3× sur les sessions riches en
outils. Les lectures de cache et les écritures de cache à 5 minutes et à
1 heure sont séparées, et un coût est estimé aux **tarifs publics** d'après la
table `PRICING` en tête du script (lectures de cache à 0,1× l'entrée, écritures
à 1,25× / 2×). Ce n'est pas ce que facture un abonnement. Les modèles que la
table ne connaît pas sont signalés « pas de tarif public ». La consommation des
sous-agents est intégrée.

**Coût rapporté.** Claude Code ≥ 2.1.9x écrit aussi son propre compteur dans le
fichier de session (enregistrements `cost-state` : coût courant, coût par
modèle, lignes ajoutées et supprimées par les outils). Lorsqu'il est présent,
la page affiche ce chiffre en colonne *coût rapporté* à côté de l'estimation
tarifaire, en ligne dans les informations de session, et sous
`reported_cost_usd`, `reported_cost_runs`, `reported_cost_partial`,
`lines_added`, `lines_removed` dans les métadonnées intégrées ; les formats
texte, Markdown et LaTeX portent la même phrase. Le compteur est **par
processus** : chaque `claude --resume` démarre un nouveau compteur, et les
exécutions antérieures à l'existence de l'enregistrement n'en ont écrit aucun —
le chiffre est donc la somme du dernier instantané de chaque exécution
(rassemblé depuis tous les fichiers de la chaîne d'une session reprise) et il
est signalé **partiel** lorsque la session a commencé plus d'une minute avant
sa première exécution mesurée. Dans ce cas la page indique quelle dépense n'est
pas couverte et l'index continue d'afficher l'estimation tarifaire ; sinon
l'index affiche « $X rapporté ». Une exécution que Claude Code n'a pas pu
tarifer entièrement est signalée (« le total rapporté est un plancher »). En
pratique le compteur est ressorti ~30 % sous l'estimation tarifaire sur une
session à exécution unique.

### Les commandes de la page HTML

Barre latérale : **recherche** (masque les tours dont le texte ne correspond
pas), **filtre** (restreint la table des matières ; touche `/`), bascules de
voie (réflexion, outils, *harness*, événements, sous-agents), tout
déplier/replier, **bascule de thème** (clair ou sombre, mémorisée par
navigateur ; suit le système jusqu'à votre choix), faits de la session, table
des matières. Touches : `j`/`k` sautent d'un tour humain à l'autre.

Un **refus de sauvegarde avec repli sur un autre modèle** (Claude Code écrit un
enregistrement `system/model_refusal_fallback` lorsqu'un message est refusé et
que la session se poursuit sur un autre modèle) est rendu comme un événement
dans tous les formats : le badge *Model fallback after a safeguard refusal*, le
détail `<original> -> <fallback> (category: …), N message(s) retracted`, et un
corps indiquant combien des messages retirés sont absents du fichier source.
Les informations de session en HTML ajoutent une ligne *Harness retractions*.
Le récapitulatif que Claude Code affiche à votre retour (`away_summary`) est
l'événement *Away summary*.

### L'index

`--index` parcourt toutes les sessions présentes sur le disque et marque
chacune **archivée**, **périmée** (la source a des enregistrements plus récents
que l'archive), **couverte** (reprise dans une autre transcription qui, elle,
est archivée), **héritée v1**, ou **non archivée** ; liste les archives dont la
source n'est pas sur le disque (imports claude.ai, transcriptions supprimées) ;
et affiche une colonne d'activité dont les âges vieillissent dans le
navigateur. Les en-têtes trient au clic. `--watch` le régénère en continu :
chaque page écrite porte un `<meta http-equiv="refresh">` pour qu'un navigateur
ouvert suive. Quand la surveillance s'arrête — Ctrl+C, une console fermée, un
`taskkill` sur son PID — l'index est écrit une fois de plus sans cette marque,
de sorte qu'une page laissée ouverte ne recharge plus un index figé toutes les
N secondes. Si cette dernière écriture est impossible (fichier verrouillé,
disque plein), l'exécution le signale et nomme ce qui reste sur le disque ;
relancez `--index` pour le remplacer. Un premier `--index` dans un répertoire
qui n'existe pas encore le crée.

**Recherche dans toutes les archives.** La page d'index porte un champ de
recherche sur chaque invite humaine de chaque archive — toutes les pages d'une
archive paginée et les invites de sous-agents (`A1.P1`) comprises — relues
depuis le HTML des archives au moment de l'indexation, de sorte que les
archives écrites par des versions antérieures et les imports claude.ai soient
couverts de la même façon. Dès deux caractères saisis, les invites
correspondantes sont listées (session, étiquette, titre, extrait surligné ; les
200 premières sont affichées), chacune renvoyant directement à l'ancre de
l'invite sur sa page, et le tableau des sessions est restreint à celles qui ont
correspondu. Les invites sont limitées à 400 caractères dans l'index ; les
réponses de Claude sont cherchables au sein de chaque page, non d'une archive à
l'autre (voir les limites).

## 5. LaTeX et PDF

Prérequis : une installation TeX fournissant `xelatex`, `fvextra`,
`tcolorbox`, `booktabs`, `array`, `enumitem`, `xcolor`, `hyperref` et les
polices DejaVu (le `scheme-full` de TeX Live les a toutes). Les polices sont
chargées **par nom de fichier depuis TeX Live**, non depuis le système, de
sorte que la sortie ne dépend pas de la base de polices de la machine.

- `pdf` = le LaTeX autonome compilé deux fois par `xelatex` (pour la table des
  matières) ; `.aux/.log/.out/.toc` sont supprimés en cas de succès et le
  `.tex` n'est conservé que si `latex` a aussi été demandé. En cas d'échec, les
  30 dernières lignes du journal sont affichées et le `.tex` reste pour
  inspection.
- `--fragment` produit un corps à `\input` dans votre propre document. Il est
  neutre quant au moteur : le grec devient des mathématiques
  (`Γ` → `$\Gamma$`), les indices et exposants deviennent des mathématiques,
  les flèches et les caractères de cadre deviennent de l'ASCII, les accents
  sont ramenés à la lettre de base. Votre préambule a besoin de
  `\usepackage{fvextra} \usepackage{xcolor} \usepackage{enumitem}
  \usepackage{booktabs} \usepackage{array} \usepackage[most]{tcolorbox}`.
  Les environnements de tour sont définis avec `\@ifundefined`, vous pouvez
  donc les restyler depuis votre préambule.
- Les émoji et autres glyphes qu'aucune police TeX ne peut composer, ainsi que
  les octets de contrôle C0/C1 (NUL issus de captures de console en UTF-16,
  retours arrière), sont retirés et **comptés dans le document**. Les lignes de
  plus de 500 caractères sont coupées de force pour que TeX puisse les
  composer ; le compte est indiqué.
- Un tour de plus de 1 500 lignes composées (un collage énorme ou une sortie
  d'outil) est découpé en encadrés successifs intitulés *(part k/n)* : un seul
  encadré sécable le contenant en entier épuise la mémoire de TeX. Le document
  indique combien de tours ont été découpés ; rien n'est omis.
- **Les tableaux markdown sont coupés en tronçons d'au plus 30 lignes
  composées**, chacun formant son propre `tabular` qui répète l'en-tête et
  porte la mention *(table continued)*, car un seul `tabular` ne peut pas se
  couper entre deux pages. Un tableau dont la largeur naturelle dépasse la
  ligne reçoit des colonnes `p` à répartition égale plutôt que des colonnes
  naturelles, de sorte qu'aucune cellule ne déborde du papier. Les deux étaient
  des pertes silencieuses avant la 2.6.4.
- Validé par une passe complète sur une archive réelle de 64 sessions (6 245
  pages, 69 minutes, `--tool-output off`, 64/64 compilées, août 2026), et par
  un contrôle compiler-et-compter dans la suite : une réponse qui est un
  tableau de 300 lignes doit occuper les pages que ses lignes exigent, et pas
  seulement sortir avec le code 0.
- Coût des entrées/sorties d'outils complètes, mesuré : une session de 636
  enregistrements → 643 pages en environ quatre minutes ; une session de 1 655
  enregistrements fait 92 pages avec `--tool-output off` et 260 avec.

## 6. Journalisation et audit

Console : lignes de progression par défaut ; `--quiet` les fait taire ;
`--verbose` ajoute le détail par étape. Les avertissements vont toujours sur
stderr. Chaque invocation écrit
`<archive-dir>/logs/<YYYYMMDD-HHMMSS>_<label>.log` (ou sous `--log-dir`)
contenant les versions de l'archiveur et de Python, la ligne de commande
exacte, le répertoire de travail, les heures de début et de fin, chaque message
de console, et l'issue (`ok`, `failed: …`, `crashed: …`, `interrupted`). La
journalisation n'interrompt jamais une exécution.

## 7. Limites connues

Ce sont les bords honnêtes. Chacun est indiqué sur la page où il s'applique.

- **Le texte de la réflexion n'est jamais dans la transcription.** Claude Code
  demande la réflexion avec `display: "omitted"` ; tout bloc de réflexion sur
  le disque est vide. L'archive montre *que* Claude a réfléchi à un endroit,
  jamais ce qu'il a pensé.
- **Le coût tarifaire est une estimation**, pas une facture ; la table
  `PRICING` est inscrite en dur (tarifs d'août 2026) et doit être modifiée
  quand les tarifs changent. Le **coût rapporté** est le chiffre de Claude Code
  lui-même, mais il est par processus : les sessions reprises sur plusieurs
  exécutions, ou commencées avant Claude Code 2.1.9x, ne sont couvertes qu'en
  partie et le disent (`partial`).
- **Une session en cours est décalée d'un appel d'outil** : archiver depuis
  l'intérieur de la session laisse l'appel de l'archiveur lui-même non
  résolu ; la page le dit.
- **L'export claude.ai ne contient que des conversations autonomes** — pas de
  conversations de Projet, pas de sessions *cowork*, pas de consommation ni de
  noms de modèles. Il vise le schéma d'export de mi-2026.
- **La découverte du *cowork* suit la disposition documentée** mais n'a été
  testée que sur des données synthétiques ; le stockage local *cowork* ne
  survit pas à une réinstallation de l'application.
- **Les sessions dans le nuage jamais pontées vers votre machine ne peuvent pas
  être archivées.**
- **Le texte et le Markdown ne peuvent pas porter d'images** ; elles sont
  annoncées comme omises. LaTeX/PDF de même ; le HTML les contient.
- **Le rendu markdown couvre la prose propre de Claude** (titres, listes y
  compris imbriquées, tableaux, blocs de code de toute longueur, citations,
  code/gras/italique/barré/liens en ligne), non un CommonMark quelconque : pas
  de HTML transmis tel quel, pas de liens de référence, pas de notes de bas de
  page ; les cellules de tableau sont coupées à chaque `|`. En LaTeX et PDF un
  tableau est tronçonné et, s'il est large, mis à la ligne (§5) : toutes les
  cellules survivent, mais un tableau très large est égalisé par colonnes
  plutôt que mis en page au goût.
- **La classification humain-contre-injecté** fait autorité sur les
  enregistrements portant `promptSource` / `origin.kind` ; les enregistrements
  plus anciens se rabattent sur des marqueurs textuels, et la preuve utilisée
  est listée par enregistrement dans le rapport de fidélité.
- **Les horodatages sont locaux** à la machine qui archive (survolez pour l'UTC
  en HTML).
- **Réarchiver avec un `--title` différent écrit un nouveau fichier** à côté de
  l'ancien plutôt que de l'écraser.
- **Passage à l'échelle** : chaque exécution relit tous les fichiers `.jsonl`
  sous les racines pour résoudre les chaînes ; l'index compare les ensembles
  d'uuid deux à deux. Convenable pour des centaines de sessions ; lent pour des
  milliers.
- **Plateformes** : développé et validé sous Windows ; la suite et un contrôle
  statique pyflakes s'exécutent sous Linux, Windows et macOS en intégration
  continue. Linux a connu une exécution réelle (31/08/2026, WSL2 Ubuntu,
  Python 3.14 : tous les formats hors PDF d'une session réelle, `--index`, et
  l'échec bruyant sans `xelatex`). Non vérifiés sur le terrain : le PDF et les
  chemins de polices TeX sous Linux, les sessions *cowork* produites sous
  Linux, et macOS dans son ensemble. Sous WSL, lire les transcriptions à
  travers `/mnt/c` a rendu le balayage environ quatre fois plus lent qu'en
  natif (18 s contre 4 s pour 281 transcriptions) — gardez les racines du côté
  Linux.
- **Le vieillissement de l'index vivant est à sens unique** : une session peut
  devenir silencieuse à l'écran, mais ne peut redevenir active sans
  régénération (`--watch`).
- **La recherche entre archives couvre les invites, pas les réponses** (et les
  400 premiers caractères de chaque invite). Les réponses sont cherchables au
  sein d'une page. Indexer les réponses multiplierait la taille du fichier
  d'index et reste différé.

## 8. Tests

```bash
python tests/test_archiver.py
```

528 vérifications sur les sessions synthétiques de `examples/` (aucune
transcription réelle nécessaire). Les vérifications de compilation LaTeX/PDF
sont ignorées, et non mises en échec, lorsqu'aucun TeX n'est dans le `PATH`.
Pour l'exercer sur une conversation qui vous appartient :

```bash
CLAUDE_PROJECTS=~/.claude/projects SAMPLE_SESSION=<id> python tests/test_archiver.py
```

La suite vérifie aussi que ce manuel et `AGENTS.md` documentent chaque option
de ligne de commande et que le nombre de vérifications annoncé dans le README
est à jour.

## 9. Construire ce manuel

```bash
python docs/build_manual.py
```

Rend `USER_MANUAL.md` — et chaque traduction — en `.html` et `.pdf` avec
pandoc (et xelatex pour le PDF) lorsqu'ils sont disponibles, sinon avec le
moteur de rendu Markdown de l'archiveur lui-même pour le HTML et une note
indiquant que le PDF a été ignoré. Les fichiers construits sont versionnés pour
que les lecteurs n'aient besoin d'aucun outil.

L'anglais est le texte de référence. Chaque traduction enregistre l'empreinte
du texte anglais dont elle est issue, et la suite échoue lorsque l'anglais a
bougé et pas la traduction ; `python docs/build_manual.py --stamp` écrit ces
empreintes, après qu'une traduction a été mise à jour — jamais à la place.
