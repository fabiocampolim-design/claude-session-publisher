# claude-session-publisher
<!-- source-digest: d529d9e1192c700d -->

[![Tests](https://github.com/fabiocampolim-design/claude-session-publisher/actions/workflows/tests.yml/badge.svg)](https://github.com/fabiocampolim-design/claude-session-publisher/actions/workflows/tests.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Dependencies: stdlib only](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen)](transcript_archiver.py)
[![Platform: Windows | Linux | macOS](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)](#prérequis)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

[English](README.md) · [Português (Brasil)](README.pt-BR.md) · [Español](README.es.md) · [Deutsch](README.de.md) · **Français**

*Traduction du README anglais, qui fait référence ; les commandes, noms de fichiers, options et blocs de code restent comme dans l'original.*

Transforme une session Claude Code en un document unique et autonome — HTML,
texte brut, Markdown, LaTeX ou PDF — accompagné d'un rapport de fidélité qui
prouve que rien n'a été silencieusement perdu.

> **Vos retours sont très appréciés.** Cet outil est jeune et les
> transcriptions sont sauvages : si une de vos sessions s'affiche bizarrement,
> si un chiffre du rapport de fidélité ne tombe pas juste, ou s'il manque un
> format dont vous avez besoin, merci
> [d'ouvrir un ticket](https://github.com/fabiocampolim-design/claude-session-publisher/issues).

**Pourquoi cet outil existe.** La recherche assistée par IA a besoin du même
niveau de traçabilité que toute autre méthode : lorsqu'un résultat a été obtenu
en conversant avec un modèle, la transparence et la reproductibilité de la
science dépendent de la possibilité de citer et d'auditer cette conversation —
mot pour mot, complète, et sous une forme qu'un article puisse référencer.
C'est à cela que sert cet outil. *Mais* le construire nous a aussi appris que
les enregistrements eux-mêmes sont fragiles : en août 2026, une réinstallation
de Claude Desktop — conseillée par le support après l'échec d'un changement
d'offre — a effacé mes sessions d'agent local, et l'export des données du
compte s'est révélé ne pas les contenir. Des projets entiers, perdus pour de
bon. L'outil dépasse donc le seul intérêt scientifique : quiconque tient à ses
conversations devrait en garder sa propre copie. La devise : **archivez tôt,
archivez souvent** — une archive n'existe que si vous la faites tant que les
fichiers existent encore.

Claude Code écrit chaque session dans un fichier JSON Lines sous
`~/.claude/projects/`. Ce fichier est complet mais illisible : enregistrements
entrelacés, charges utiles d'outils, comptabilité interne du *harness*. Ce
script analyse chaque type d'enregistrement pour en faire un modèle typé,
décide par classe s'il faut le **rendre**, le **replier** ou le **compter**, et
imprime un rapport de fidélité qui rapproche les trois chiffres du nombre
d'enregistrements de la source — de sorte que la différence entre « *pas dans
la transcription* » et « *pas dans la source* » reste toujours visible sur la
page.

Un seul fichier, bibliothèque standard uniquement, aucune installation.

```bash
python transcript_archiver.py <session-id>
python transcript_archiver.py <session-id> --format html,text,markdown,latex,pdf
python transcript_archiver.py --index          # reconstruit la page d'index
```

Référence complète : [`docs/USER_MANUAL.fr.md`](docs/USER_MANUAL.fr.md) (aussi
en [HTML](docs/USER_MANUAL.fr.html) et [PDF](docs/USER_MANUAL.fr.pdf))
recense chaque option, chaque sortie, chaque fonctionnalité et chaque limite
connue. Vous le pilotez avec un agent IA ? Donnez-lui
[`AGENTS.md`](AGENTS.md). Les changements sont dans
[`CHANGELOG.md`](CHANGELOG.md) ; comment contribuer dans
[`CONTRIBUTING.md`](CONTRIBUTING.md) et les arbitrages de conception — dont la
note sur les menaces — dans [`docs/DESIGN.md`](docs/DESIGN.md). Politique de
sécurité : [`SECURITY.md`](SECURITY.md). Ce dont il dépend et ce qu'il
reproduit : [`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md). Où il a réellement
été exécuté : [`docs/platforms.md`](docs/platforms.md).

## Fonctionnalités

- **Cinq formats à partir d'une seule analyse** — HTML, texte brut, Markdown,
  LaTeX et PDF sont tous rendus depuis le même modèle typé de la transcription,
  de sorte qu'un tour ne peut pas apparaître dans un format et disparaître d'un
  autre. `--fragment` produit un corps LaTeX prêt à être `\input` dans un
  manuscrit, translittéré pour compiler sous pdflatex aussi bien que sous
  XeLaTeX.
- **Les transcriptions de sous-agents font partie de l'enregistrement** — la
  conversation d'un agent en arrière-plan
  (`<session-id>/subagents/agent-*.jsonl`) est rendue comme une annexe liée
  dans chaque format, sa consommation fusionnée dans le tableau des coûts, et
  chaque fichier listé dans le rapport de fidélité. `--subagents off` supprime
  le contenu, jamais la mention.
- **Trois sources** — sessions Claude Code, sessions *cowork* de Claude Desktop
  (mode agent local) via `--cowork-root`, et conversations claude.ai via
  `--import-claude-ai conversations.json` (depuis Settings → Privacy → Export
  data), toutes par la même chaîne de traitement et le même rapport de
  fidélité.
- **Un rapport de fidélité sur chaque page** — chaque enregistrement source est
  rendu, replié dans un tour antérieur, ou compté comme délibérément non rendu,
  et les trois nombres sont rapprochés du nombre d'enregistrements de la
  source. Les lignes corrompues sont comptées elles aussi. Si quelque chose
  échappe à l'analyseur, la page le dit au lieu de le cacher.
- **Les tours humains sont mot pour mot** — le texte saisi et les collages ne
  passent jamais par un moteur de rendu markdown, de sorte qu'une *trace
  d'appels* collée ou un *benchmark* en colonnes reste intact octet par octet
  dans tous les formats.
- **Des étiquettes de référence citables** — chaque invite est P1, P2, … et
  chaque réponse R1, R2, …, séquentielles et uniques dans le document (les
  tours de sous-agents sont préfixés A1., A2., …), de sorte qu'un article
  puisse dire « à l'invite P32 » ou « dans la réponse A2.R4 ». Les étiquettes
  figurent à côté du nom du locuteur dans tous les formats et servent d'ancres
  en HTML (`#P32` mène directement à l'invite).
- **Résolution des chaînes de session** — une conversation reprise ou pontée
  est écrite dans un nouveau fichier qui répète les enregistrements antérieurs ;
  l'archiveur trouve le fichier le plus complet en comparant les ensembles
  d'uuid d'enregistrements, suit les continuations véritables et refuse de
  suivre les bifurcations.
- **Comptabilité de la consommation et du coût** — jetons par modèle,
  dédoublonnés par `requestId` (sommer naïvement les enregistrements surestime
  la sortie d'environ 2,3× sur les sessions riches en outils), avec les
  lectures de cache, les écritures de cache à 5 minutes contre 1 heure, et une
  estimation de coût au tarif public — **à côté du coût rapporté par Claude
  Code lui-même** depuis son compteur `cost-state` (Claude Code ≥ 2.1.9x),
  cumulé sur les exécutions de la session et rassemblé entre les fichiers d'une
  session reprise, et signalé comme *partiel* lorsque la session a commencé
  avant sa première exécution mesurée.
- **Le harness est visible** — sorties de hooks, fichiers injectés, chargements
  de *skills*, résumés de compactage et enregistrements système sont rendus
  dans une voie repliée avec, pour chacun, la preuve de sa classification, au
  lieu de disparaître ou de se faire passer pour ce que vous avez saisi.
- **Honnête sur la réflexion** — Claude Code demande la réflexion avec
  `display: "omitted"`, donc l'archive montre *que* Claude a réfléchi à un
  endroit donné et dit clairement que le texte n'atteint jamais la
  transcription.
- **HTML autonome** — mise en page de type conversation, thèmes clair et
  sombre avec un sélecteur que le navigateur mémorise, un champ de recherche
  qui masque les tours non concordants, une table des matières filtrable, des
  bascules par voie, une navigation au clavier, aucune ressource externe.
  `--paginate N` découpe une très grande session en pages de N tours, le
  sommaire latéral et les liens de sous-agents pointant d'une page à l'autre.
- **Un index vivant avec recherche dans toutes les archives** — `--index`
  construit une page triable de toutes les sessions présentes sur le disque,
  avec une colonne d'activité dont les âges vieillissent dans le navigateur
  sans régénération, et un champ de recherche portant sur **chaque invite de
  chaque archive** (intégrées au moment de l'indexation, avec lien direct vers
  l'ancre `#P` de l'invite sur sa page) ; `--index --watch 300` le régénère en
  boucle et la page se recharge d'elle-même, offrant un tableau de bord au
  rythme lent des conversations actives à l'instant présent.
- **Quatre langues de plus pour l'habillage des pages** — `--lang
  pt-BR|es|de|fr` (ou `CLAUDE_ARCHIVE_LANG`) met les mots propres à
  l'archiveur — libellés, titres, notes, le rapport de fidélité, l'index — en
  portugais du Brésil, espagnol, allemand ou français, dans tous les formats.
  La conversation n'est jamais traduite : invites, réponses, entrées/sorties
  d'outils et texte système sont les mêmes octets quelle que soit la langue, et
  la suite de tests le prouve fragment par fragment.
- **Sortie des outils sous votre contrôle** — `--tool-output on|off`
  indépendant du format, et les sorties longues élidées en leur milieu
  (`--full` pour tout conserver), chaque élision étant comptée sur la page.
- **Résiste aux transcriptions réelles** — octets NUL issus de captures de
  console en UTF-16, codes ANSI, émoji, lignes de 65 000 caractères, appels
  d'outils non résolus et lignes non analysables sont tous traités, comptés et
  signalés.
- **Chaque exécution est consignée** — `--verbose`/`--quiet` pour la console,
  et un journal d'audit par invocation sous `<archive-dir>/logs/` (ligne de
  commande exacte, versions, chaque message, issue), déplaçable avec
  `--log-dir`.
- **On vérifie ce qui compile, pas seulement le code de retour 0** — le chemin
  LaTeX découpe les tours trop grands et fractionne les tableaux longs ou
  larges pour que rien ne déborde de la page, et la suite compile une session
  chargée de tableaux puis compte les pages pour prouver que les lignes sont
  bien arrivées. Un code de retour propre ne prouve pas que le contenu a
  survécu au compositeur.
- Bibliothèque standard uniquement, un fichier, 528 vérifications dans la suite
  de tests, pyflakes et intégration continue sous Linux/Windows/macOS.

## Comparaison

[simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts)
est l'outil le plus connu du domaine : installable par pip, avec sélecteur
interactif de sessions, HTML paginé et adapté au mobile, chronologies de
commits git, et publication en un Gist GitHub d'une seule commande. D'autres
exportateurs ([claude-session-exporter](https://github.com/rubicon/claude-session-exporter)
et plusieurs semblables) visent le Markdown pour les coffres de notes. Cet
outil a une autre visée : **la fidélité d'archive et l'impression** — le
rapport de fidélité rapproché, les tours humains mot pour mot, la comptabilité
de consommation et de coût, la résolution des chaînes, et une sortie LaTeX/PDF
digne de l'annexe d'un article. Si vous voulez un lien web rapide à partager,
prenez l'outil de Simon ; si vous voulez un enregistrement complet et
auditable, ou un document, prenez celui-ci.

## Feuille de route

Manques qu'il vaut la peine de combler :

- **Prise en charge de première classe de Linux et macOS.** L'intégration
  continue exécute la suite sous Linux et macOS. Linux a connu sa première
  exécution réelle le 31/08/2026 (WSL2 Ubuntu, Python 3.14) : HTML, texte,
  Markdown et LaTeX d'une session réelle, `--index` sur 88 sessions, et le
  chemin d'échec sans `xelatex` se sont comportés comme sous Windows. Toujours
  non vérifiés sur le terrain : la compilation PDF et les chemins de polices
  TeX sous Linux, les sessions *cowork* produites sous Linux, et tout ce qui
  concerne macOS. Les retours d'utilisateurs Linux/Mac sont particulièrement
  bienvenus.
- **Passage à l'échelle.** Chaque exécution relit toutes les transcriptions
  sous les racines pour résoudre les chaînes, et l'index compare les ensembles
  d'uuid deux à deux — convenable pour des centaines de sessions, lent pour des
  milliers. Un balayage mis en cache est la prochaine étape évidente.
- **La recherche couvre les invites, pas les réponses, d'une archive à
  l'autre.** L'index cherche dans chaque invite humaine de chaque archive ; les
  réponses de Claude sont cherchables à l'intérieur d'une page. Indexer aussi
  les réponses suppose un fichier d'index bien plus gros et reste différé
  jusqu'à ce que quelqu'un en ait besoin.

(Le rendu des sous-agents, le format Markdown, la découverte des sessions
*cowork*, l'importateur claude.ai, la pagination, la recherche par page et la
recherche d'invites entre archives, autrefois listés ici, sont livrés. Chaque
fonctionnalité et chaque limite connue sont réunies en un seul endroit dans le
[manuel de l'utilisateur](docs/USER_MANUAL.fr.md).) Deux réserves sur les
sources : la disposition du répertoire *cowork* suit la structure documentée de
Claude Desktop mais a été testée sur des données synthétiques, et l'importateur
claude.ai — désormais validé sur un export réel d'août 2026 (rapport de
fidélité rapproché exactement, UTF-8 accentué intact) — vise le schéma d'export
de mi-2026 ; cet export ne contenait aucune conversation de projet, donc les
signalements d'exports qui s'analysent différemment, en particulier les
conversations de projet, restent bienvenus.

## Où vont les fichiers

L'entrée est découverte sous `--projects-root` (par défaut
`~/.claude/projects`) et, lorsque le répertoire existe, `--cowork-root`
(détecté automatiquement selon la plateforme). La sortie atterrit dans
`--archive-dir` (par défaut `~/claude-archives`, ou la variable
d'environnement `CLAUDE_ARCHIVE_DIR`) : chaque session y devient
`<session-id>_<title-slug>.<ext>`, un fichier par format (les imports
claude.ai utilisent le préfixe d'uuid de la conversation), `--index` écrit
`index.html` dans le même répertoire, et chaque exécution laisse un journal
d'audit dans `logs/`. Pour placer une archive unique avec précision,
`--out chemin/vers/rapport` nomme la racine — chaque format ajoute sa propre
extension.

## Portée

L'archiveur lit les fichiers de transcription que Claude Code écrit sur votre
disque ; ce qu'il peut archiver dépend donc de l'endroit où vit la
transcription d'une session :

| Surface Claude | Archivable ? |
|---|---|
| Claude Code CLI | **Oui** — c'est son format natif. |
| Application de bureau Claude Code | **Oui** — les sessions s'exécutent localement et écrivent les mêmes fichiers. |
| Claude Code web/mobile, ponté vers votre machine | **Oui** — le côté local écrit une transcription, et les enregistrements du pont voient leur chaîne résolue, de sorte que les morceaux ressortent comme une seule conversation. |
| *Cowork* de Claude Desktop (mode agent local) | **Oui** — même format sous un répertoire de base différent, intégré à la découverte via `--cowork-root` (détecté automatiquement). |
| Conversations claude.ai, chat Claude Desktop, application mobile | **Via export** — demandez l'export de vos données (Settings → Privacy → Export data) et lancez `--import-claude-ai conversations.json`. L'export ne porte ni consommation de jetons ni noms de modèles, et la page le dit. |
| Sessions Claude Code dans le nuage (jamais pontées) | Non — rien n'est écrit sur votre disque. |

Deux faits chèrement acquis lors de la validation sur un compte réel (août
2026) : l'export de données claude.ai ne contient **que les conversations
autonomes** — les conversations à l'intérieur des Projets claude.ai et les
sessions *cowork* de Claude Desktop n'y sont pas — et le stockage local
*cowork* **ne** survit **pas** à une réinstallation de l'application — voir
*Pourquoi cet outil existe*, en haut.

## Essayez-le

Une conversation-vitrine entièrement inventée accompagne `examples/` — une
chasse aux modes d'énergie nulle dans un nanoruban de graphène, construite pour
tout exercer : étiquettes de référence sur deux modèles, un appel d'outil qui
échoue et sa reprise, un tableau collé mot pour mot, une image collée, du grec
et des caractères de cadre, un sous-agent en arrière-plan (étiqueté `A1.*`), un
compactage de contexte, un appel d'outil non résolu et une ligne délibérément
corrompue que le rapport de fidélité compte.

```bash
python transcript_archiver.py 0000c0de-cafe-4000-8000-00000000f00d \
    --projects-root examples --archive-dir demo --format html,markdown,pdf
```

![Une page du PDF de la vitrine](docs/showcase-pdf.png)

## Formats

| | |
|---|---|
| `html` | Page de type conversation : vos tours à droite, ceux de Claude à gauche, entrées/sorties d'outils repliables, table des matières filtrable, thèmes clair et sombre. Autonome — aucune ressource externe. |
| `text` | UTF-8 pur. Les tours humains et les sorties d'outils sont reproduits octet par octet et jamais remis en forme. |
| `markdown` | Pour les coffres de notes (Obsidian, etc.). La prose de Claude est du markdown et passe telle quelle ; les tours humains et les entrées/sorties d'outils sont encadrés mot pour mot, avec des clôtures plus longues que toute suite d'accents graves qu'ils contiennent. |
| `latex` | Un document XeLaTeX autonome, ou — avec `--fragment` — un corps que vous pouvez `\input` dans votre propre article. |
| `pdf` | Le LaTeX compilé avec `xelatex` (deux passes, pour la table des matières). |

Les cinq sont rendus depuis la même transcription analysée, de sorte qu'un tour
ne peut pas apparaître dans un format et disparaître d'un autre, et chacun
déclare dans son propre en-tête ce que son support ne peut pas porter.

### Langue

`--lang pt-BR|es|de|fr` ne traduit que ce que l'archiveur écrit lui-même ; la
conversation reste mot pour mot et le journal d'audit reste en anglais.
Détails dans le [manuel](docs/USER_MANUAL.fr.md#langue).

### Sortie des outils

`--tool-output on|off` est indépendant de `--format`. Les arguments des outils
sont mis en forme partout, mais les entrées et sorties complètes transforment
une grande session en un document de plusieurs centaines de pages, d'où :

```bash
# un PDF lisible : appels d'outils listés par nom, charges utiles omises
python transcript_archiver.py <id> --format pdf --tool-output off

# l'enregistrement complet
python transcript_archiver.py <id> --format html --tool-output on
```

Une session de 1 655 enregistrements fait 92 pages sans la sortie des outils et
260 avec.

### Fragments pour un article

`--fragment` produit le corps sans préambule et translittère chaque caractère
pour qu'il compile sous **pdflatex** aussi bien que sous XeLaTeX — le grec
devient des mathématiques, les flèches et les caractères de cadre deviennent de
l'ASCII. Le préambule de votre document hôte a besoin de :

```latex
\usepackage{fvextra} \usepackage{xcolor} \usepackage{enumitem}
\usepackage{booktabs} \usepackage{array} \usepackage[most]{tcolorbox}
```

Les environnements de tour sont définis avec `\@ifundefined`, vous pouvez donc
restyler chaque tour depuis votre propre préambule sans modifier le fichier
généré.

## Ce qu'il fait bien

Ce sont tous des défauts réels, découverts en le passant sur des centaines de
milliers d'enregistrements, et chacun est désormais couvert par un test :

- **La consommation est dédoublonnée par `requestId`.** Une réponse de l'API
  est écrite sous forme de plusieurs enregistrements qui répètent chacun la
  même consommation cumulée ; les sommer surestime les jetons de sortie
  d'environ 2,3× sur une session riche en outils.
- **Humain contre injecté se lit dans `promptSource`/`origin.kind`**, et ne se
  devine pas d'après le texte, de sorte que les invites injectées par le
  *harness* ne soient pas rendues comme ce que vous avez saisi.
- **Les chaînes de session sont résolues.** Une conversation reprise ou pontée
  est écrite dans un *nouveau* fichier qui répète les enregistrements
  antérieurs ; archiver l'identifiant que vous avez nommé par hasard peut donc
  ne capturer qu'une moitié de conversation. Comparez les ensembles d'uuid, pas
  les noms de fichiers ni les nombres d'enregistrements — le fichier le plus
  court peut contenir davantage de conversation.
- **Les tours humains ne passent jamais par le moteur de rendu markdown.** Ce
  sont du texte saisi et des collages ; les interpréter écrase une *trace
  d'appels* collée en prose.
- **Les blocs de réflexion sont toujours vides.** Claude Code les demande avec
  `display: "omitted"`, de sorte qu'une archive peut montrer *que* Claude a
  réfléchi à un endroit donné, jamais ce qu'il a pensé. La page le dit au lieu
  de laisser croire le contraire.

## Tests

```bash
python tests/test_archiver.py
```

528 vérifications, exécutées sur les sessions synthétiques de `examples/` —
autonomes, aucune transcription réelle nécessaire. Les vérifications de
compilation LaTeX/PDF sont ignorées (et non mises en échec) lorsqu'aucune
installation TeX n'est dans le `PATH` ; tout le reste n'a besoin que de Python.
La suite vérifie aussi que le manuel de l'utilisateur et `AGENTS.md`
documentent chaque option de ligne de commande et que le nombre de
vérifications annoncé ici est à jour. Pour l'exercer sur une grande
conversation désordonnée qui vous appartient :

```bash
CLAUDE_PROJECTS=~/.claude/projects SAMPLE_SESSION=<id> python tests/test_archiver.py
```

L'échantillon est produit par `examples/make_sample.py` et délibérément
construit pour porter ce qui a cassé sur des données réelles : un bloc collé
dont les colonnes ne doivent pas être remises en forme, du grec et des
caractères de cadre, des octets NUL issus d'une sortie UTF-16 capturée octet
par octet, une ligne de 3 000 caractères, un bloc de réflexion vide, un appel
d'outil non résolu, une liste markdown qui change de type de puce en cours de
route, un tour qui cite les propres marqueurs de gabarit de l'archiveur, et une
ligne délibérément corrompue que le rapport de fidélité doit compter au lieu de
la sauter en silence.

## Prérequis

Python 3.9+ pour les formats HTML et texte — bibliothèque standard uniquement.

LaTeX et PDF exigent une installation TeX fournissant `xelatex`, `fvextra`,
`tcolorbox`, `array` et les polices DejaVu (le `scheme-full` de TeX Live les a
toutes). Les polices sont chargées **par nom de fichier depuis TeX Live**, non
depuis le système, de sorte que la sortie ne dépend pas de la base de polices
de la machine.

Les chiffres de coût viennent de la table `PRICING` en tête du script — tarifs
publics, inscrits en dur en août 2026. Quand les tarifs changent, modifiez
cette table ; les modèles qu'elle ne connaît pas sont signalés « pas de tarif
public » plutôt que facturés à tort.

## Comment il a été construit

Sous sa propre surveillance, en un sens : l'outil entier a été développé dans
Claude Code (Opus 5 et Fable 5), et chacune de ces sessions de développement
est archivable par le résultat. L'effort, reconstitué à partir des
transcriptions de sessions : **dix jours du premier prototype à la
publication** (16–26 août 2026), sur environ huit longues séances de travail —
quelque 40 Mo de transcription brute — et 15 commits. Le premier commit public
n'est arrivé qu'au neuvième jour — tout ce qui précède était du test de survie.
Deux jours de publications guidées par la relecture ont suivi (2.4 → 2.6.6,
28–31 août : trois revues complètes du projet, une passe indépendante de revue
de code, des exécutions de survie qui ont attrapé six nouveaux types
d'enregistrements que Claude Code s'était mis à écrire, et les corrections
exigées par chacun — la dernière étant un tableau qui compilait proprement tout
en perdant ses lignes), portant l'historique à 38 commits ; l'entretien qui a
suivi — garder le vérificateur de conformité *vendorisé* identique octet pour
octet au manuel de publication — le porte à 61 commits (2.7.2, une régression
que l'exécution de survie sur données réelles a attrapée après une suite tout
en vert, 2.7.3–2.7.7, cinq tours de relecture indépendante ayant chacun
trouvé de vrais défauts dans la correction du tour précédent — toujours dans
son chemin d'échec, jamais dans le chemin heureux — et 2.8.0, qui a hissé le
dépôt au standard produit (politique de sécurité, relevé des plateformes,
inventaire des tiers) et traduit le README et le manuel en quatre langues de
plus, sont les sept derniers).

La répartition du travail, reconstituée à partir de ces mêmes transcriptions et
exprimée en termes [CRediT](https://credit.niso.org/) (la taxonomie des rôles
de contributeurs qu'emploient les articles scientifiques) :

| Rôle CRediT | Fabio | Claude |
|---|---|---|
| **Conceptualisation** | La prémisse — un enregistrement autonome et d'une fidélité totale d'une session assistée par IA, propre au compte rendu scientifique — et la plupart des idées de fonctionnalités : étiquettes de citation P/R, l'interrupteur de sortie d'outils, l'index d'activité en direct, la pagination | Le modèle de rapprochement rendre/replier/compter devenu le rapport de fidélité |
| **Méthodologie** | L'ordre de priorité (fidélité du contenu d'abord, puis les sources, puis les formats) ; les exigences de publication académique qui ont façonné le fragment LaTeX | La résolution des chaînes par comparaison d'ensembles d'uuid ; le dédoublonnage de consommation par `requestId` ; la règle du tour humain mot pour mot |
| **Logiciel** | — | La totalité |
| **Validation** | A cassé chaque version sur des centaines de milliers d'enregistrements d'une archive réelle ; a trouvé les défauts de page périmée, de débordement et de mise en page ; a fixé le niveau d'exigence (*« il faut ici une grande exactitude »*) ; a commandé les passes de revue et de revue de code | La suite de 296 vérifications et l'intégration continue ; les exécutions de survie guidées par la relecture |
| **Investigation** | A dirigé l'étude des outils voisins | Analyse du code et de la documentation pour la section de comparaison |
| **Curation des données** | — | L'échantillon synthétique et la conversation-vitrine, construits pour porter exactement les cas qui avaient cassé sur données réelles |
| **Visualisation** | La mise en page conversationnelle (humain à droite, Claude à gauche), le style des encadrés, le placement des étiquettes et des horodatages | Le HTML/CSS qui la réalise |
| **Rédaction** | Relecture et édition | Première version (README, messages de commit) |
| **Ressources · Encadrement · Administration du projet · Obtention de financement** | La totalité | — |

## Licence

Licence Apache 2.0 — voir `LICENSE` et `NOTICE`. Vous pouvez l'utiliser, la
modifier et la redistribuer, y compris à des fins commerciales, à condition que
la licence et la notice voyagent avec elle ; les contributions sont acceptées
aux mêmes conditions (section 5).

### Avertissement

Ce logiciel est fourni **en l'état**, sans garantie ni condition d'aucune
sorte, expresse ou implicite, y compris, sans s'y limiter, toute garantie de
qualité marchande, d'adéquation à un usage particulier, de titre ou d'absence
de contrefaçon. En aucun cas l'auteur ne pourra être tenu responsable de
dommages de quelque nature que ce soit — directs, indirects, spéciaux,
accessoires ou consécutifs — ni d'aucune autre réclamation ou responsabilité,
qu'elle soit contractuelle, délictuelle ou autre, découlant du logiciel ou de
son utilisation, ou en relation avec eux, même si l'éventualité de tels
dommages a été signalée (Licence Apache 2.0, sections 7 et 8). Vous êtes seul
responsable de son usage licite, des transcriptions et données que vous lui
fournissez et publiez avec lui, et du respect des conditions de tout service ou
contenu tiers qu'il touche.

Ceci est un projet indépendant. Il n'est ni affilié à Anthropic, ni approuvé ni
soutenu par elle ; *Claude* et *Claude Code* sont des marques d'Anthropic, PBC,
employées ici uniquement pour nommer le logiciel dont cet outil archive les
transcriptions.
