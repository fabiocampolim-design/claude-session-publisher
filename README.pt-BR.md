# claude-session-publisher
<!-- source-digest: 03d8d27d2947e2b1 -->

[![Tests](https://github.com/fabiocampolim-design/claude-session-publisher/actions/workflows/tests.yml/badge.svg)](https://github.com/fabiocampolim-design/claude-session-publisher/actions/workflows/tests.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Dependencies: stdlib only](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen)](transcript_archiver.py)
[![Platform: Windows | Linux | macOS](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)](#requisitos)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

[English](README.md) · **Português (Brasil)** · [Español](README.es.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

*Tradução do README em inglês, que é a referência; comandos, nomes de arquivos, opções e blocos de código ficam como no original.*

Transforme uma sessão do Claude Code em um único documento autocontido — HTML,
texto puro, Markdown, LaTeX ou PDF — com um relatório de fidelidade que prova
que nada foi descartado silenciosamente.

> **Comentários são muito bem-vindos.** Esta ferramenta é nova e transcrições
> são selvagens — se alguma sessão sua for renderizada de forma estranha, se um
> número do relatório de fidelidade não fechar, ou se faltar um formato de que
> você precisa, por favor
> [abra uma issue](https://github.com/fabiocampolim-design/claude-session-publisher/issues).

**Por que isto existe.** A pesquisa assistida por IA precisa do mesmo padrão de
registro que qualquer outro método: quando um resultado foi obtido em conversa
com um modelo, a transparência e a reprodutibilidade da ciência dependem de
poder citar e auditar essa conversa — literal, completa e em uma forma que um
artigo possa referenciar. É para isso que serve esta ferramenta. *Mas*
construí-la também nos ensinou que os próprios registros são frágeis: em agosto
de 2026 uma reinstalação do Claude Desktop — recomendada pelo suporte após uma
falha na atualização de plano — apagou minhas sessões de agente local, e a
exportação de dados da conta acabou não incluindo essas sessões. Projetos
inteiros, perdidos para sempre. Portanto a ferramenta interessa a um público
maior que o científico: qualquer pessoa cujas conversas importem deveria manter
sua própria cópia. O lema: **arquive cedo, arquive sempre** — um arquivo só
existe se você o fizer enquanto os arquivos de origem ainda existirem.

O Claude Code grava cada sessão em um arquivo JSON Lines sob
`~/.claude/projects/`. Esse arquivo é completo, porém ilegível: registros
intercalados, cargas úteis de ferramentas, contabilidade interna do *harness*.
Este script analisa cada tipo de registro e o converte em um modelo tipado,
decide por classe se deve **renderizar**, **agrupar** ou **contar** cada um, e
imprime um relatório de fidelidade que reconcilia os três números com a
contagem de registros da origem — de modo que a diferença entre *"não está na
transcrição"* e *"não está na origem"* fique sempre visível na página.

Arquivo único, apenas biblioteca padrão, sem etapa de instalação.

```bash
python transcript_archiver.py <session-id>
python transcript_archiver.py <session-id> --format html,text,markdown,latex,pdf
python transcript_archiver.py --index          # reconstrói a página de índice
```

Referência completa: [`docs/USER_MANUAL.pt-BR.md`](docs/USER_MANUAL.pt-BR.md)
(também em [HTML](docs/USER_MANUAL.pt-BR.html) e
[PDF](docs/USER_MANUAL.pt-BR.pdf)) lista todas as opções, saídas, recursos e
limitações conhecidas. Vai conduzi-la com um agente de IA? Entregue o
[`AGENTS.md`](AGENTS.md) a ele. As mudanças estão em
[`CHANGELOG.md`](CHANGELOG.md); como contribuir está em
[`CONTRIBUTING.md`](CONTRIBUTING.md) e as decisões de projeto — incluindo a
nota de ameaças — em [`docs/DESIGN.md`](docs/DESIGN.md). Política de segurança:
[`SECURITY.md`](SECURITY.md). Do que depende e o que reproduz:
[`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md). Onde foi de fato executada:
[`docs/platforms.md`](docs/platforms.md).

## Recursos

- **Cinco formatos a partir de uma única análise** — HTML, texto puro,
  Markdown, LaTeX e PDF são todos renderizados a partir do mesmo modelo tipado
  da transcrição, de modo que um turno não pode aparecer em um formato e sumir
  em outro. `--fragment` emite um corpo LaTeX pronto para `\input` em um
  manuscrito, transliterado para compilar tanto com pdflatex quanto com
  XeLaTeX.
- **Transcrições de subagentes fazem parte do registro** — a conversa de um
  agente em segundo plano (`<session-id>/subagents/agent-*.jsonl`) é
  renderizada como apêndice com link em todos os formatos, seu uso é somado à
  tabela de custos, e cada arquivo é listado no relatório de fidelidade.
  `--subagents off` suprime o conteúdo, mas nunca a divulgação.
- **Três origens** — sessões do Claude Code, sessões *cowork* do Claude Desktop
  (modo de agente local) via `--cowork-root`, e conversas do claude.ai via
  `--import-claude-ai conversations.json` (em Settings → Privacy → Export
  data), todas pelo mesmo pipeline e com o mesmo relatório de fidelidade.
- **Um relatório de fidelidade em cada página** — cada registro de origem é
  renderizado, agrupado em um turno anterior, ou contado como deliberadamente
  não renderizado, e os três números são reconciliados com a contagem de
  registros da origem. Linhas corrompidas também são contadas. Se algo escapar
  do analisador, a página diz isso em vez de esconder.
- **Turnos humanos são literais** — texto digitado e colagens nunca passam por
  um renderizador de markdown, de modo que um *traceback* colado ou um
  *benchmark* em colunas permanece byte a byte intacto em todos os formatos.
- **Etiquetas de referência citáveis** — cada prompt é P1, P2, … e cada
  resposta R1, R2, …, sequenciais e únicos dentro do documento (turnos de
  subagentes recebem o prefixo A1., A2., …), de modo que um artigo possa dizer
  "no prompt P32" ou "na resposta A2.R4". As etiquetas aparecem ao lado do
  rótulo do interlocutor em todos os formatos e são âncoras no HTML (`#P32`
  leva direto ao prompt).
- **Resolução de cadeia de sessões** — uma conversa retomada ou espelhada é
  gravada em um novo arquivo que repete os registros anteriores; o arquivador
  encontra o arquivo mais completo comparando conjuntos de uuids de registro,
  segue continuações genuínas e se recusa a seguir bifurcações.
- **Contabilidade de uso e custo** — tokens por modelo, deduplicados por
  `requestId` (somar os registros ingenuamente superestima a saída em ~2,3× em
  sessões com muitas ferramentas), com leituras de cache, escritas de cache de
  5 minutos vs 1 hora, e uma estimativa de custo a preço de tabela — **ao lado
  do custo informado pelo próprio Claude Code** a partir do medidor
  `cost-state` (Claude Code ≥ 2.1.9x), somado ao longo das execuções da sessão
  e reunido entre os arquivos de uma sessão retomada, e marcado como *parcial*
  quando a sessão começou antes de sua primeira execução medida.
- **O harness fica visível** — saída de hooks, arquivos injetados,
  carregamentos de *skills*, resumos de compactação e registros de sistema são
  renderizados em uma faixa recolhida, com a evidência de classificação de cada
  um, em vez de sumirem ou se passarem por coisas que você digitou.
- **Honesto sobre o pensamento** — o Claude Code solicita o pensamento com
  `display: "omitted"`, então o arquivo mostra *que* o Claude pensou em um dado
  ponto e diz claramente que o texto nunca chega à transcrição.
- **HTML autocontido** — layout em estilo de conversa, temas claro e escuro com
  um alternador que o navegador memoriza, uma caixa de busca que oculta os
  turnos que não correspondem, sumário filtrável, alternadores por faixa,
  navegação por teclado, nenhum recurso externo. `--paginate N` divide uma
  sessão muito grande em páginas de N turnos, com o sumário lateral e os links
  de subagentes apontando entre as páginas.
- **Um índice vivo com busca em todos os arquivos** — `--index` constrói uma
  página ordenável de todas as sessões em disco, com uma coluna de atividade
  cujas idades envelhecem no navegador sem regeneração, e uma caixa de busca
  sobre **todos os prompts de todos os arquivos** (embutidos no momento da
  indexação, com link direto para a âncora `#P` do prompt em sua página);
  `--index --watch 300` continua regenerando em laço e a página se recarrega
  sozinha, dando um painel de ritmo lento de quais conversas estão ativas
  agora.
- **Mais quatro idiomas para a moldura da página** — `--lang pt-BR|es|de|fr`
  (ou `CLAUDE_ARCHIVE_LANG`) coloca as palavras do próprio arquivador —
  rótulos, títulos, notas, o relatório de fidelidade, o índice — em português
  do Brasil, espanhol, alemão ou francês, em todos os formatos. A conversa
  nunca é traduzida: prompts, respostas, entrada/saída de ferramentas e texto
  de sistema são os mesmos bytes em qualquer idioma, e a suíte de testes prova
  isso fragmento por fragmento.
- **Saída de ferramentas sob seu controle** — `--tool-output on|off`
  independente do formato, e saídas longas elididas no meio (`--full` para
  manter tudo), com cada elisão contada na página.
- **Sobrevive a transcrições reais** — bytes NUL de capturas de console em
  UTF-16, códigos ANSI, emoji, linhas de 65.000 caracteres, chamadas de
  ferramenta não resolvidas e linhas não analisáveis são todos tratados,
  contados e relatados.
- **Toda execução fica registrada** — `--verbose`/`--quiet` para o console, e
  um log de auditoria por invocação em `<archive-dir>/logs/` (linha de comando
  exata, versões, todas as mensagens, desfecho), com `--log-dir` para mudá-lo
  de lugar.
- **O que compila é verificado, não apenas o código de saída 0** — o caminho
  LaTeX divide turnos grandes demais e fatia tabelas longas ou largas para que
  nada saia da página, e a suíte compila uma sessão cheia de tabelas e conta as
  páginas para provar que as linhas chegaram. Um código de saída limpo não é
  evidência de que o conteúdo sobreviveu ao tipógrafo.
- Apenas biblioteca padrão, um arquivo, 528 verificações na suíte de testes,
  pyflakes e CI em Linux/Windows/macOS.

## Como isto se compara

O [simonw/claude-code-transcripts](https://github.com/simonw/claude-code-transcripts)
é a ferramenta mais conhecida nesta área: instalável via pip, com seletor
interativo de sessões, HTML paginado e adaptado a celular, linhas do tempo de
commits do git e publicação em um Gist do GitHub com um comando. Outros
exportadores ([claude-session-exporter](https://github.com/rubicon/claude-session-exporter)
e vários semelhantes) miram Markdown para cofres de notas. O foco desta
ferramenta é outro: **fidelidade de arquivo e impressão** — o relatório de
fidelidade reconciliado, turnos humanos literais, contabilidade de uso e custo,
resolução de cadeias, e saída LaTeX/PDF adequada ao apêndice de um artigo. Se
você quer um link web rápido para compartilhar, use a ferramenta do Simon; se
quer um registro completo e auditável ou um documento, use esta.

## Roteiro

Lacunas que vale fechar:

- **Suporte de primeira classe a Linux e macOS.** A CI roda a suíte em Linux e
  macOS. O Linux teve sua primeira execução real em 31/08/2026 (WSL2 Ubuntu,
  Python 3.14): HTML, texto, Markdown e LaTeX de uma sessão real, `--index`
  sobre 88 sessões, e o caminho de falha sem `xelatex` se comportaram como no
  Windows. Ainda não verificados em campo: compilação de PDF e caminhos de
  fontes TeX no Linux, sessões *cowork* produzidas no Linux, e tudo no macOS.
  Relatos de usuários de Linux/Mac são especialmente bem-vindos.
- **Escala.** Cada execução relê todas as transcrições sob as raízes para
  resolver cadeias, e o índice compara conjuntos de uuid par a par — tudo bem
  para centenas de sessões, lento para milhares. Uma varredura em cache é o
  próximo passo óbvio.
- **A busca cobre prompts, não respostas, entre arquivos.** O índice busca
  todos os prompts humanos de todos os arquivos; as respostas do Claude são
  buscáveis dentro de uma página. Indexar as respostas também significa um
  arquivo de índice muito maior e fica adiado até que alguém precise.

(Renderização de subagentes, o formato Markdown, descoberta de sessões
*cowork*, o importador do claude.ai, paginação, busca por página e busca de
prompts entre arquivos, antes listados aqui, já foram entregues. Todos os
recursos e todas as limitações conhecidas estão reunidos em um só lugar no
[manual do usuário](docs/USER_MANUAL.pt-BR.md).) Duas ressalvas sobre as
origens: o layout do diretório *cowork* segue a estrutura documentada do Claude
Desktop, mas foi testado com dados sintéticos, e o importador do claude.ai —
agora validado contra uma exportação real de agosto de 2026 (relatório de
fidelidade reconciliado exatamente, UTF-8 acentuado intacto) — mira o esquema
de exportação de meados de 2026; aquela exportação não continha conversas
dentro de projetos, então relatos de exportações que sejam analisadas de outra
forma, especialmente conversas de projeto, continuam bem-vindos.

## Onde os arquivos vão parar

A entrada é descoberta sob `--projects-root` (padrão `~/.claude/projects`) e,
quando o diretório existe, `--cowork-root` (detectado automaticamente por
plataforma). A saída vai para `--archive-dir` (padrão `~/claude-archives`, ou a
variável de ambiente `CLAUDE_ARCHIVE_DIR`): cada sessão vira
`<session-id>_<title-slug>.<ext>` ali, um arquivo por formato (importações do
claude.ai usam o prefixo do uuid da conversa), `--index` grava `index.html` no
mesmo diretório, e cada execução deixa um log de auditoria em `logs/`. Para
posicionar um único arquivo com exatidão, `--out caminho/para/relatorio` nomeia
o radical — cada formato acrescenta sua própria extensão.

## Escopo

O arquivador lê os arquivos de transcrição que o Claude Code grava no seu
disco, de modo que o que ele pode arquivar é decidido por onde vive a
transcrição de uma sessão:

| Superfície do Claude | Arquivável? |
|---|---|
| Claude Code CLI | **Sim** — é seu formato nativo. |
| Aplicativo desktop do Claude Code | **Sim** — as sessões rodam localmente e gravam os mesmos arquivos. |
| Claude Code web/celular, espelhado para a sua máquina | **Sim** — o lado local grava uma transcrição, e os registros da ponte têm sua cadeia resolvida, de modo que as partes saem como uma única conversa. |
| *Cowork* do Claude Desktop (modo de agente local) | **Sim** — mesmo formato sob um diretório-base diferente, incorporado à descoberta via `--cowork-root` (detectado automaticamente). |
| Conversas do claude.ai, chat do Claude Desktop, aplicativo de celular | **Via exportação** — solicite a exportação dos seus dados (Settings → Privacy → Export data) e rode `--import-claude-ai conversations.json`. A exportação não traz uso de tokens nem nomes de modelos, e a página diz isso. |
| Sessões em nuvem do Claude Code (nunca espelhadas) | Não — nada é gravado no seu disco. |

Dois fatos duramente conquistados ao validar contra uma conta real (agosto de
2026): a exportação de dados do claude.ai contém **apenas conversas avulsas** —
conversas dentro de Projetos do claude.ai e sessões *cowork* do Claude Desktop
não estão nela — e o armazenamento local do *cowork* **não** sobrevive a uma
reinstalação do aplicativo — veja *Por que isto existe*, no topo.

## Experimente

Uma conversa-vitrine totalmente inventada acompanha o `examples/` — uma caça a
modos de energia zero em uma nanofita de grafeno, construída para exercitar
tudo: etiquetas de referência em dois modelos, uma chamada de ferramenta que
falha e sua repetição, uma tabela colada literalmente, uma imagem colada, grego
e desenho de caixas, um subagente em segundo plano (etiquetado `A1.*`), uma
compactação de contexto, uma chamada de ferramenta não resolvida e uma linha
deliberadamente corrompida que o relatório de fidelidade conta.

```bash
python transcript_archiver.py 0000c0de-cafe-4000-8000-00000000f00d \
    --projects-root examples --archive-dir demo --format html,markdown,pdf
```

![Uma página do PDF da vitrine](docs/showcase-pdf.png)

## Formatos

| | |
|---|---|
| `html` | Página em estilo de conversa: seus turnos à direita, os do Claude à esquerda, entrada/saída de ferramentas recolhível, sumário filtrável, temas claro e escuro. Autocontida — sem recursos externos. |
| `text` | UTF-8 puro. Turnos humanos e saída de ferramentas são reproduzidos byte a byte e nunca são requebrados. |
| `markdown` | Para cofres de notas (Obsidian etc.). A prosa do Claude é markdown e passa direto; turnos humanos e entrada/saída de ferramentas ficam em blocos literais, com cercas dimensionadas para superar qualquer sequência de crases interna. |
| `latex` | Um documento XeLaTeX autônomo, ou — com `--fragment` — um corpo que você pode `\input` no seu próprio artigo. |
| `pdf` | O LaTeX compilado com `xelatex` (duas passagens, por causa do sumário). |

Todos os cinco são renderizados a partir da mesma transcrição analisada, de
modo que um turno não pode aparecer em um formato e sumir em outro, e cada um
declara no próprio cabeçalho o que seu meio não consegue carregar.

### Idioma

`--lang pt-BR|es|de|fr` traduz apenas o que o próprio arquivador escreve; a
conversa permanece literal e o log de auditoria permanece em inglês. Detalhes
no [manual](docs/USER_MANUAL.pt-BR.md#idioma).

### Saída de ferramentas

`--tool-output on|off` é independente de `--format`. Os argumentos das
ferramentas são formatados com clareza em todos os casos, mas entrada e saída
completas transformam uma sessão grande em um documento de várias centenas de
páginas, então:

```bash
# um PDF legível: chamadas de ferramenta listadas por nome, cargas omitidas
python transcript_archiver.py <id> --format pdf --tool-output off

# o registro completo
python transcript_archiver.py <id> --format html --tool-output on
```

Uma sessão de 1.655 registros tem 92 páginas com a saída de ferramentas
desligada e 260 com ela ligada.

### Fragmentos para um artigo

`--fragment` emite o corpo sem preâmbulo e translitera cada caractere para que
compile tanto com **pdflatex** quanto com XeLaTeX — grego vira matemática,
setas e desenho de caixas viram ASCII. O preâmbulo do seu documento
hospedeiro precisa de:

```latex
\usepackage{fvextra} \usepackage{xcolor} \usepackage{enumitem}
\usepackage{booktabs} \usepackage{array} \usepackage[most]{tcolorbox}
```

Os ambientes de turno são definidos com `\@ifundefined`, então você pode
reestilizar cada turno a partir do seu próprio preâmbulo sem editar o arquivo
gerado.

## O que ele acerta

Todos estes foram defeitos reais encontrados ao rodá-lo sobre centenas de
milhares de registros, e cada um está agora coberto por um teste:

- **O uso é deduplicado por `requestId`.** Uma resposta da API é gravada como
  vários registros que repetem cada um o mesmo uso cumulativo; somá-los
  superestima os tokens de saída em cerca de 2,3× em uma sessão com muitas
  ferramentas.
- **Humano vs. injetado é lido de `promptSource`/`origin.kind`**, não adivinhado
  a partir do texto, de modo que prompts injetados pelo *harness* não sejam
  renderizados como coisas que você digitou.
- **Cadeias de sessão são resolvidas.** Uma conversa retomada ou espelhada é
  gravada em um *novo* arquivo que repete os registros anteriores, então
  arquivar o id que você por acaso nomeou pode capturar metade de uma conversa.
  Compare conjuntos de uuid, não nomes de arquivo nem contagens de registros —
  o arquivo menor pode conter mais conversa.
- **Turnos humanos nunca passam pelo renderizador de markdown.** Eles são texto
  digitado e colagens; interpretá-los achata um *traceback* colado em prosa.
- **Blocos de pensamento estão sempre vazios.** O Claude Code os solicita com
  `display: "omitted"`, então um arquivo pode mostrar *que* o Claude pensou em
  um dado ponto, nunca o que ele pensou. A página diz isso em vez de sugerir o
  contrário.

## Testes

```bash
python tests/test_archiver.py
```

528 verificações, executadas contra as sessões sintéticas em `examples/` —
autocontidas, sem necessidade de transcrição real. As verificações de
compilação LaTeX/PDF são puladas (não falham) quando não há instalação TeX no
`PATH`; todo o resto precisa apenas de Python. A suíte também verifica que o
manual do usuário e o `AGENTS.md` documentam todas as opções de linha de
comando e que a contagem de verificações declarada aqui está atual. Para
exercitá-la sobre uma conversa grande e bagunçada sua:

```bash
CLAUDE_PROJECTS=~/.claude/projects SAMPLE_SESSION=<id> python tests/test_archiver.py
```

A amostra é gerada por `examples/make_sample.py` e é deliberadamente construída
para carregar as coisas que quebraram com dados reais: um bloco colado cujas
colunas não podem ser requebradas, grego e desenho de caixas, bytes NUL de
saída UTF-16 capturada byte a byte, uma linha de 3.000 caracteres, um bloco de
pensamento vazio, uma chamada de ferramenta não resolvida, uma lista markdown
que troca de tipo de marcador no meio, um turno que cita os próprios marcadores
de template do arquivador, e uma linha deliberadamente corrompida que o
relatório de fidelidade deve contar em vez de pular em silêncio.

## Requisitos

Python 3.9+ para os formatos HTML e texto — apenas biblioteca padrão.

LaTeX e PDF precisam de uma instalação TeX que forneça `xelatex`, `fvextra`,
`tcolorbox`, `array` e as fontes DejaVu (o `scheme-full` do TeX Live tem todas
elas). As fontes são carregadas **por nome de arquivo, a partir do TeX Live**,
e não do sistema, de modo que a saída não depende do banco de fontes da
máquina.

Os valores de custo vêm da tabela `PRICING` no topo do script — tarifas
públicas de tabela, fixadas no código em agosto de 2026. Quando as tarifas
mudarem, edite essa tabela; modelos que ela não conhece são reportados como
"sem preço de tabela" em vez de precificados errado.

## Como foi construído

Com ele próprio observando, de certa forma: a ferramenta inteira foi
desenvolvida no Claude Code (Opus 5 e Fable 5), e cada uma dessas sessões de
desenvolvimento é arquivável pelo resultado. O esforço, reconstruído a partir
das transcrições das sessões: **dez dias do primeiro protótipo ao lançamento**
(16–26 de agosto de 2026), ao longo de cerca de oito sessões longas de trabalho
— uns 40 MB de transcrição bruta — e 15 commits. O primeiro commit público só
apareceu no nono dia — tudo antes disso foi teste de sobrevivência. Seguiram-se
mais dois dias de lançamentos guiados por revisão (2.4 → 2.6.6, 28–31 de
agosto: três revisões completas do projeto, uma passagem independente de
revisão de código, execuções de sobrevivência que pegaram seis novos tipos de
registro que o Claude Code havia começado a escrever, e as correções que cada
uma delas exigiu — a última delas uma tabela que compilava sem erro enquanto
perdia suas linhas), levando o histórico a 38 commits; a manutenção que se
seguiu — manter o verificador de conformidade *vendorizado* byte a byte
idêntico ao manual de publicação — leva a 58 commits (2.7.2, uma regressão que
a execução de sobrevivência com dados reais pegou depois de uma suíte toda
verde, 2.7.3–2.7.7, cinco rodadas de revisão independente, cada uma
encontrando defeitos reais na correção da rodada anterior — sempre no caminho
de falha, nunca no caminho feliz — e 2.8.0, que trouxe o repositório ao padrão
de produto (política de segurança, registro de plataformas, inventário de
terceiros) e traduziu o README e o manual para mais quatro idiomas, são os
últimos sete).

A divisão do trabalho, reconstruída a partir dessas mesmas transcrições e
expressa em termos [CRediT](https://credit.niso.org/) (a taxonomia de papéis
de contribuidores usada em artigos científicos):

| Papel CRediT | Fabio | Claude |
|---|---|---|
| **Conceituação** | A premissa — um registro autocontido e de fidelidade total de uma sessão assistida por IA, apto a relato científico — e a maioria das ideias de recursos: etiquetas de citação P/R, a chave de saída de ferramentas, o índice de atividade ao vivo, a paginação | O modelo de reconciliação renderizar/agrupar/contar que virou o relatório de fidelidade |
| **Metodologia** | A ordem de prioridade (fidelidade de conteúdo primeiro, depois origens, depois formatos); os requisitos de publicação acadêmica que moldaram o fragmento LaTeX | Resolução de cadeia por comparação de conjuntos de uuid; deduplicação de uso por `requestId`; a regra do turno humano literal |
| **Software** | — | Tudo |
| **Validação** | Quebrou cada build contra centenas de milhares de registros de um arquivo real; pegou os defeitos de página obsoleta, transbordamento e layout; definiu o padrão (*"isto precisa de alta acurácia"*); encomendou as passagens de revisão e de revisão de código | A suíte de 296 verificações e a CI; as execuções de sobrevivência guiadas por revisão |
| **Investigação** | Dirigiu o levantamento de ferramentas vizinhas | Análise de código e documentação para a seção de comparação |
| **Curadoria de dados** | — | A amostra sintética e a conversa-vitrine, construídas para carregar exatamente os casos que haviam quebrado com dados reais |
| **Visualização** | O layout de conversa (humano à direita, Claude à esquerda), o estilo das caixas, a posição de etiquetas e horários | O HTML/CSS que o realiza |
| **Redação** | Revisão e edição | Rascunho original (README, mensagens de commit) |
| **Recursos · Supervisão · Administração do projeto · Captação de recursos** | Tudo | — |

## Licença

Licença Apache 2.0 — veja `LICENSE` e `NOTICE`. Você pode usar, modificar e
redistribuir, inclusive comercialmente, desde que a licença e o aviso viajem
junto; contribuições são aceitas sob os mesmos termos (seção 5).

### Isenção de responsabilidade

Este software é fornecido **no estado em que se encontra**, sem garantias ou
condições de qualquer natureza, expressas ou implícitas, incluindo, entre
outras, qualquer garantia de comercialização, adequação a uma finalidade
específica, titularidade ou não violação. Em nenhuma hipótese o autor será
responsável por quaisquer danos de qualquer natureza — diretos, indiretos,
especiais, incidentais ou consequenciais — nem por qualquer outra reivindicação
ou responsabilidade, seja em contrato, ato ilícito ou de outra forma,
decorrente de, ou em conexão com, o software ou seu uso, mesmo que avisado da
possibilidade de tais danos (Licença Apache 2.0, seções 7 e 8). Somente você é
responsável por usá-lo licitamente, pelas transcrições e dados que lhe fornecer
e publicar com ele, e por cumprir os termos de qualquer serviço ou conteúdo de
terceiros que ele toque.

Este é um projeto independente. Não é afiliado, endossado ou apoiado pela
Anthropic; *Claude* e *Claude Code* são marcas da Anthropic, PBC, usadas aqui
apenas para nomear o software cujas transcrições esta ferramenta arquiva.
