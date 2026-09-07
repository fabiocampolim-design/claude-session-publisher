---
title: "claude-session-publisher — Manual do Usuário"
subtitle: "transcript_archiver.py v2.8.0"
source-digest: "cb33ce2647306476"
---

# claude-session-publisher — Manual do Usuário

[English](USER_MANUAL.md) · **Português (Brasil)** · [Español](USER_MANUAL.es.md) · [Deutsch](USER_MANUAL.de.md) · [Français](USER_MANUAL.fr.md)

*Tradução do manual em inglês, que é a referência; comandos, nomes de arquivos, opções e blocos de código ficam como no original.*

O `transcript_archiver.py` transforma uma conversa do Claude em um documento
autocontido — HTML, texto puro, Markdown, LaTeX ou PDF — com um relatório de
fidelidade que reconcilia cada registro de origem com o que a página mostra.
Este manual é a referência completa: todas as opções, todas as saídas, todos os
recursos e todas as limitações conhecidas. O README é a página do produto; o
`AGENTS.md` traz a mesma informação escrita para um agente de IA que conduza a
ferramenta.

Arquivo único, Python 3.9+, apenas biblioteca padrão. Sem etapa de instalação:

```bash
python transcript_archiver.py --version
python transcript_archiver.py --help
```

## 1. Início rápido

```bash
# arquiva uma sessão do Claude Code em HTML (o formato padrão)
python transcript_archiver.py <session-id>

# todos os formatos de uma vez
python transcript_archiver.py <session-id> --format html,text,markdown,latex,pdf

# reconstrói a página de índice de tudo que está em disco
python transcript_archiver.py --index

# experimente na conversa-vitrine que acompanha o projeto
python transcript_archiver.py 0000c0de-cafe-4000-8000-00000000f00d \
    --projects-root examples --archive-dir demo --format html,markdown,pdf
```

O id da sessão é o nome do arquivo `.jsonl` em
`~/.claude/projects/<project>/`. O `--index` lista todas as sessões que ele
encontra, com id e título, então rode-o primeiro se você não souber o id.

## 2. Origens

| Origem | Como | Observações |
|---|---|---|
| Claude Code CLI / aplicativo desktop | padrão; sessões sob `--projects-root` (`~/.claude/projects`) | formato nativo |
| Claude Code web/celular espelhado para a sua máquina | igual | os registros da ponte têm a cadeia resolvida em uma única conversa |
| *Cowork* do Claude Desktop (modo de agente local) | `--cowork-root` (detectado automaticamente por plataforma) | mesmo esquema de registros, diretório-base diferente; o `audit.jsonl` é ignorado. Testado apenas com dados sintéticos |
| Conversas do claude.ai, chat do Claude Desktop, aplicativo de celular | `--import-claude-ai conversations.json` | em Settings → Privacy → Export data. Apenas conversas avulsas; sem conversas de Projeto, sem dados de uso ou de modelo (a página diz isso) |
| Sessões em nuvem do Claude Code nunca espelhadas | não arquivável | nada é gravado no seu disco |

Detecção automática do *cowork*:
`%APPDATA%\Claude\local-agent-mode-sessions` no Windows,
`~/Library/Application Support/Claude/local-agent-mode-sessions` no macOS,
`~/.config/Claude/local-agent-mode-sessions` nos demais. Passe
`--cowork-root ""` para desativar.

## 3. Referência de linha de comando

Toda entrada e toda saída são alcançáveis pela linha de comando; nada está
fixo no código. O `--help` imprime cada opção com seu padrão.

### Posicional

| | |
|---|---|
| `session_id` | UUID da transcrição (o nome do arquivo `.jsonl`). Opcional com `--index` ou `--import-claude-ai`. |

### Descoberta e localização

| Opção | Padrão | Significado |
|---|---|---|
| `--projects-root DIR` | `~/.claude/projects` | onde o Claude Code grava as sessões |
| `--cowork-root DIR` | automático por plataforma | sessões *cowork* do Claude Desktop, incorporadas à descoberta quando o diretório existe; `""` desativa |
| `--archive-dir DIR` | `$CLAUDE_ARCHIVE_DIR` ou `~/claude-archives` | onde vão os arquivos, o `index.html` e o `logs/` |
| `--out PATH` | — | **radical** do caminho de saída para um único arquivo; cada formato acrescenta sua própria extensão (`--out report.pdf --format html` grava `report.html`). Sobrepõe a nomeação de `--archive-dir` |
| `--title TEXT` | o `ai-title` da própria sessão | título da página; também define o *slug* do nome do arquivo. Rearquivar com outro título grava um arquivo novo |
| `--summary-file FILE` | texto de exemplo | fragmento HTML (blocos `h3`/`ul`) renderizado como o resumo escrito à mão da sessão |

### Conteúdo

| Opção | Padrão | Significado |
|---|---|---|
| `--format LIST` | `html` | separado por vírgulas: `html`, `text`, `markdown` (ou `md`), `latex`, `pdf` |
| `--tool-output on\|off` | `on` | inclui entrada e saída das ferramentas. Independente de `--format`. `off` reduz cada chamada a uma linha rotulada — geralmente o que se quer para LaTeX/PDF |
| `--max-tool-output N` | `16384` | elide o meio de qualquer saída de ferramenta maior que N caracteres; cada elisão é contada na página. `0` = nunca |
| `--full` | desligado | nunca elide (o mesmo que `--max-tool-output 0`) |
| `--subagents on\|off` | `on` | renderiza transcrições de subagentes como seções de apêndice. Com `off` elas continuam listadas no relatório de fidelidade e seu uso continua contando |
| `--no-follow-chain` | desligado | arquiva exatamente o id dado, mesmo que exista uma continuação mais completa |
| `--fragment` | desligado | com `--format latex`: apenas o corpo, sem preâmbulo, transliterado para compilar tanto com pdflatex quanto com XeLaTeX. Não pode ser combinado com `pdf` |
| `--paginate N` | `0` | divide o HTML em páginas de N turnos; a página 1 mantém as seções de resumo, uso e fidelidade; a barra lateral liga as páginas |
| `--lang CODE` | `$CLAUDE_ARCHIVE_LANG` ou `en` | `en`, `pt-BR`, `es`, `de`, `fr`: o idioma das palavras do próprio arquivador em todos os formatos e no índice. A conversa nunca é traduzida (veja §4, *Idioma*) |

### Índice

| Opção | Significado |
|---|---|
| `--index` | reconstrói o `index.html` em `--archive-dir` e sai |
| `--watch SECONDS` | com `--index`: regenera a cada SECONDS (mínimo 30) até Ctrl+C, e marca a página para se recarregar; ao parar, o índice é gravado mais uma vez para não se recarregar mais |

### Importação do claude.ai

| Opção | Significado |
|---|---|
| `--import-claude-ai FILE` | importa conversas de um `conversations.json` do claude.ai |
| `--conversation TEXT` | apenas conversas cujo nome ou uuid contenha TEXT (sem distinguir maiúsculas) |
| `--list-conversations` | lista as conversas da exportação e sai |

### Controle de saída e registro

| Opção | Significado |
|---|---|
| `--verbose` | detalhe por etapa (arquivos analisados, passagens de compilação, caminho do log de auditoria) |
| `--quiet` | não imprime nada além de avisos; o log de auditoria continua registrando tudo |
| `--log-dir DIR` | onde vai o log de auditoria de cada execução (padrão `<archive-dir>/logs/`) |
| `--version` | imprime a versão do arquivador e sai |
| `--help` | referência de opções |

Combinações inválidas são recusadas antes de qualquer gravação: `--watch` sem
`--index`; `--conversation`/`--list-conversations` sem `--import-claude-ai`;
`--fragment` sem `latex` ou junto com `pdf`; `--verbose` com `--quiet`; um
valor desconhecido de `--format`.

## 4. O que é produzido

### Arquivos

Em `--archive-dir` (ou no radical de `--out`), um arquivo por formato:
`<session-id>_<title-slug>.html|.txt|.md|.tex|.pdf`. Um corpo LaTeX de
`--fragment` é `<stem>_fragment.tex`. O HTML paginado acrescenta
`<stem>_p2.html`, `<stem>_p3.html`, …. Importações do claude.ai são nomeadas
`<uuid-prefix>_<slug>`. O `--index` grava `index.html`. Toda execução grava
`logs/<timestamp>_<label>.log`.

Quando uma sessão é uma conversa retomada ou espelhada, o arquivo recebe o nome
da transcrição efetivamente arquivada (o arquivo mais completo da cadeia), e a
página registra qual id foi solicitado.

### A página

Todos os formatos trazem, nesta ordem: o **resumo da sessão** (escrito à mão
via `--summary-file`, ou um texto de exemplo), **uso e custo**, o **relatório
de fidelidade**, depois a **transcrição**, depois as **transcrições de
subagentes** como apêndices.

Tipos de turno e como cada formato os mostra:

| Turno | HTML | texto / Markdown | LaTeX / PDF |
|---|---|---|---|
| Prompt humano (P*n*) | balão alinhado à direita, literal, monoespaçado quando em colunas, URLs com link | literal, nunca requebrado (Markdown: em bloco) | caixa literal |
| Resposta do Claude (R*n*) | markdown renderizado | prosa requebrada (Markdown: markdown ativo) | markdown → LaTeX |
| Pensamento | recolhido; vazio na prática (veja §7) | rotulado | caixa rotulada |
| Chamada de ferramenta | entrada/saída recolhida, estados de erro e pendente, capturas de tela | entrada/saída completa ou uma linha (`--tool-output`) | entrada/saída completa ou caixa só com título |
| Imagem colada | embutida | anunciada como omitida | anunciada como omitida |
| Harness / sistema / evento | faixa recolhida com a evidência de classificação | blocos rotulados | caixas rotuladas |
| Transcrição de subagente | apêndice recolhível, com link a partir da chamada que o criou | seção de apêndice | seção de apêndice |

### Idioma

`--lang pt-BR|es|de|fr` (ou a variável de ambiente `CLAUDE_ARCHIVE_LANG`; a
opção vence; padrão `en`) define o idioma de tudo que o próprio arquivador
escreve: a moldura da página e seus controles, os rótulos dos turnos, as
informações da sessão, as notas de uso e custo, o relatório de fidelidade, o
apêndice de subagentes, as notas de formato das saídas em texto/Markdown/LaTeX,
e a página de índice. O `<html lang>` e o campo `lang` dos metadados embutidos
registram a escolha; o LaTeX autônomo carrega o polyglossia quando ele está
instalado, mantém o **inglês como idioma padrão** — a prosa da conversa é
hifenizada e espaçada como inglês, de modo que uma página em francês nunca
insere espaços antes do `!` do Claude — e envolve apenas as palavras do próprio
arquivador no idioma do documento. Um `--fragment` compõe essas palavras com
macros de acento (`\'{e}`, `\"{a}`, `\ss{}`) para que o pdflatex as imprima
intactas, e nunca as conta na nota de descarte do fragmento.

A conversa nunca é traduzida. Prompts, respostas, pensamento, nomes de
ferramentas, entrada e saída de ferramentas, texto de sistema e do *harness*,
nomes de modelos, títulos, caminhos, datas (ISO) e números são os mesmos bytes
em todos os idiomas — a suíte renderiza o modelo de teste nos cinco e verifica
que cada fragmento de conversa da página em inglês está presente, literal, nas
demais. Selos de evento e rótulos de anexos são traduzidos onde são
renderizados; os nomes de tipos de registro nas tabelas de fidelidade
(`human turn`, `tool_use`, …) são vocabulário do analisador e permanecem em
inglês, assim como o carimbo `archiver v…` que o índice relê. O log de
auditoria, o console (`--verbose`) e o `--help` permanecem em inglês seja qual
for o idioma. Um código desconhecido — na opção ou na variável — é recusado
antes de qualquer gravação.

### Etiquetas de referência

Cada prompt humano é `P1, P2, …` e cada resposta `R1, R2, …`, sequenciais
dentro do documento; turnos de subagentes recebem o prefixo `A1.`, `A2.`
(assim, `A2.R4`). No HTML as etiquetas são âncoras: `page.html#P32` leva direto
ao prompt.

### Relatório de fidelidade

Cada registro de origem é **renderizado** (produziu um ou mais turnos),
**agrupado** (um resultado de ferramenta absorvido pela sua chamada) ou
**contado** (metadados sem conteúdo de transcrição — e linhas corrompidas). Os
três números são reconciliados com a contagem de registros da origem na página;
se não fecharem, a página diz isso em vez de esconder. O relatório também lista
os registros por tipo, os blocos de conteúdo, o que foi renderizado e o que foi
contado, a evidência humano-vs-injetado por registro, os arquivos de
subagentes, e as ressalvas (blocos de pensamento vazios, chamadas de ferramenta
não resolvidas, horário do instantâneo versus o último registro da origem).

### Uso e custo

Tokens por modelo deduplicados por `requestId` — uma resposta da API é gravada
como vários registros que repetem o mesmo uso, e somá-los superestima a saída
em ~2,3× em sessões com muitas ferramentas. Leituras de cache e escritas de
cache de 5 minutos e de 1 hora são separadas, e um custo é estimado a **preços
públicos de tabela** a partir da tabela `PRICING` no topo do script (leituras
de cache a 0,1× da entrada, escritas a 1,25× / 2×). Não é o que uma assinatura
cobra. Modelos que a tabela não conhece são reportados como "sem preço de
tabela". O uso dos subagentes é incorporado.

**Custo informado.** O Claude Code ≥ 2.1.9x também grava seu próprio medidor no
arquivo da sessão (registros `cost-state`: custo corrente, custo por modelo,
linhas adicionadas e removidas por ferramentas). Quando presente, a página
mostra esse valor como uma coluna de *custo informado* ao lado da estimativa de
tabela, uma linha nas informações da sessão, e `reported_cost_usd`,
`reported_cost_runs`, `reported_cost_partial`, `lines_added`, `lines_removed`
nos metadados embutidos; os formatos texto, Markdown e LaTeX trazem a mesma
frase. O medidor é **por processo**: cada `claude --resume` inicia um contador
novo, e execuções feitas antes de o registro existir não gravaram nenhum — então
o valor é a soma do último instantâneo de cada execução (reunido de todos os
arquivos da cadeia de uma sessão retomada) e é marcado como **parcial** quando
a sessão começou mais de um minuto antes de sua primeira execução medida. Nesse
caso a página diz qual gasto não está coberto e o índice segue mostrando a
estimativa de tabela; caso contrário o índice mostra "$X informado". Uma
execução que o Claude Code não conseguiu precificar por completo é anotada ("o
total informado é um piso"). Na prática o medidor ficou ~30 % abaixo da
estimativa de tabela em uma sessão de uma única execução.

### Os controles da página HTML

Barra lateral: **busca** (oculta turnos cujo texto não corresponde), **filtro**
(restringe a lista do sumário; tecla `/`), alternadores de faixa (pensamento,
ferramentas, *harness*, eventos, subagentes), expandir/recolher tudo,
**alternador de tema** (claro ou escuro, memorizado por navegador; segue o
sistema até você escolher), fatos da sessão, sumário. Teclas: `j`/`k` saltam
entre turnos humanos.

Uma **recusa de salvaguarda com troca de modelo** (o Claude Code grava um
registro `system/model_refusal_fallback` quando uma mensagem é recusada e a
sessão continua em outro modelo) é renderizada como evento em todos os
formatos: o selo *Model fallback after a safeguard refusal*, o detalhe
`<original> -> <fallback> (category: …), N message(s) retracted`, e um corpo
declarando quantas das mensagens retiradas estão ausentes do arquivo de origem.
As informações da sessão em HTML acrescentam uma linha *Harness retractions*. O
resumo que o Claude Code imprime quando você volta (`away_summary`) é o evento
*Away summary*.

### O índice

O `--index` varre todas as sessões em disco e marca cada uma como
**arquivada**, **desatualizada** (a origem tem registros mais novos que o
arquivo), **coberta** (retomada em outra transcrição que está arquivada),
**legada v1**, ou **não arquivada**; lista arquivos cuja origem não está em
disco (importações do claude.ai, transcrições apagadas); e mostra uma coluna de
atividade cujas idades envelhecem no navegador. Os cabeçalhos ordenam ao
clique. O `--watch` mantém a regeneração: cada página que ele grava carrega um
`<meta http-equiv="refresh">` para que um navegador aberto acompanhe. Quando a
observação para — Ctrl+C, um console fechado, um `taskkill` no PID — o índice é
gravado mais uma vez sem essa marca, de modo que uma página deixada aberta não
recarregue mais um índice congelado a cada N segundos. Se essa última gravação
não puder ser feita (arquivo bloqueado, disco cheio) a execução avisa e nomeia o
que continua em disco; rode `--index` de novo para substituí-lo. Um primeiro
`--index` em um diretório que ainda não existe cria o diretório.

**Busca em todos os arquivos.** A página de índice traz uma caixa de busca
sobre todos os prompts humanos de todos os arquivos — incluindo todas as
páginas de um arquivo paginado e os prompts de subagentes (`A1.P1`) — lidos de
volta do próprio HTML dos arquivos no momento da indexação, de modo que
arquivos escritos por versões anteriores e importações do claude.ai fiquem
igualmente cobertos. Ao digitar dois ou mais caracteres, ela lista os prompts
correspondentes (sessão, etiqueta, título, trecho destacado; os 200 primeiros),
cada um com link direto para a âncora do prompt em sua página, e restringe a
tabela de sessões às que corresponderam. Os prompts são limitados a 400
caracteres no índice; as respostas do Claude são buscáveis dentro de cada
página, não entre arquivos (veja as limitações).

## 5. LaTeX e PDF

Requisitos: uma instalação TeX que forneça `xelatex`, `fvextra`, `tcolorbox`,
`booktabs`, `array`, `enumitem`, `xcolor`, `hyperref` e as fontes DejaVu (o
`scheme-full` do TeX Live tem todas). As fontes são carregadas **por nome de
arquivo, a partir do TeX Live**, e não do sistema, de modo que a saída não
depende do banco de fontes da máquina.

- `pdf` = o LaTeX autônomo compilado pelo `xelatex` duas vezes (por causa do
  sumário); `.aux/.log/.out/.toc` são removidos em caso de sucesso e o `.tex` é
  mantido apenas se `latex` também tiver sido pedido. Em caso de falha, as
  últimas 30 linhas do log são impressas e o `.tex` permanece para inspeção.
- `--fragment` emite um corpo para `\input` no seu próprio documento. Ele é
  neutro quanto ao motor: o grego vira matemática (`Γ` → `$\Gamma$`),
  sub/sobrescritos viram matemática, setas e desenho de caixas viram ASCII,
  acentos são reduzidos à letra base. Seu preâmbulo precisa de
  `\usepackage{fvextra} \usepackage{xcolor} \usepackage{enumitem}
  \usepackage{booktabs} \usepackage{array} \usepackage[most]{tcolorbox}`.
  Os ambientes de turno são definidos com `\@ifundefined`, então você pode
  reestilizá-los a partir do seu preâmbulo.
- Emoji e outros glifos que nenhuma fonte TeX consegue compor, e bytes de
  controle C0/C1 (NULs de capturas de console em UTF-16, *backspaces*), são
  removidos e **contados no documento**. Linhas com mais de 500 caracteres são
  quebradas à força para que o TeX possa compô-las; a contagem é declarada.
- Um turno com mais de 1.500 linhas compostas (uma colagem enorme ou saída de
  ferramenta) é dividido em caixas consecutivas intituladas *(part k/n)*: uma
  única caixa quebrável contendo tudo esgota a memória do TeX. O documento
  declara quantos turnos foram divididos; nada é omitido.
- **Tabelas markdown são cortadas em pedaços de no máximo 30 linhas
  compostas**, cada uma um `tabular` próprio que repete o cabeçalho e é marcado
  *(table continued)*, porque um único `tabular` não pode quebrar entre
  páginas. Uma tabela cuja largura natural exceda a linha recebe colunas `p`
  com quebra equalizada em vez de colunas naturais, de modo que nenhuma célula
  saia do papel. Ambos eram perdas silenciosas antes da 2.6.4.
- Validado por uma passagem completa sobre um arquivo real de 64 sessões
  (6.245 páginas, 69 minutos, `--tool-output off`, 64/64 compiladas, agosto de
  2026), e por uma verificação de compilar-e-contar na suíte: uma resposta que
  é uma tabela de 300 linhas tem de ocupar as páginas que suas linhas exigem,
  não apenas sair com código 0.
- Custo da entrada/saída completa de ferramentas, medido: uma sessão de 636
  registros → 643 páginas em cerca de quatro minutos; uma sessão de 1.655
  registros tem 92 páginas com `--tool-output off` e 260 com ele ligado.

## 6. Registro e auditoria

Console: linhas de progresso por padrão; `--quiet` as silencia; `--verbose`
acrescenta detalhe por etapa. Avisos vão sempre para o stderr. Toda invocação
grava `<archive-dir>/logs/<YYYYMMDD-HHMMSS>_<label>.log` (ou sob `--log-dir`)
contendo as versões do arquivador e do Python, a linha de comando exata, o
diretório de trabalho, os horários de início e fim, todas as mensagens de
console, e o desfecho (`ok`, `failed: …`, `crashed: …`, `interrupted`). O
registro nunca aborta uma execução.

## 7. Limitações conhecidas

Estas são as bordas honestas. Cada uma é declarada na página em que se aplica.

- **O texto do pensamento nunca está na transcrição.** O Claude Code solicita o
  pensamento com `display: "omitted"`; todo bloco de pensamento em disco está
  vazio. O arquivo mostra *que* o Claude pensou em um ponto, nunca o que ele
  pensou.
- **O custo de tabela é uma estimativa**, não uma fatura; a tabela `PRICING`
  está fixa no código (tarifas de agosto de 2026) e precisa ser editada quando
  as tarifas mudarem. O **custo informado** é o número do próprio Claude Code,
  mas é por processo: sessões retomadas ao longo de várias execuções, ou
  iniciadas antes do Claude Code 2.1.9x, são cobertas apenas em parte e dizem
  isso (`partial`).
- **Uma sessão ao vivo fica com uma chamada de ferramenta a menos**: arquivar de
  dentro da sessão deixa a chamada do próprio arquivador não resolvida; a
  página diz isso.
- **A exportação do claude.ai contém apenas conversas avulsas** — sem conversas
  de Projeto, sem sessões *cowork*, sem uso nem nomes de modelos. Ela mira o
  esquema de exportação de meados de 2026.
- **A descoberta do *cowork* segue o layout documentado**, mas foi testada
  apenas com dados sintéticos; o armazenamento local do *cowork* não sobrevive
  a uma reinstalação do aplicativo.
- **Sessões em nuvem nunca espelhadas para a sua máquina não podem ser
  arquivadas.**
- **Texto e Markdown não conseguem carregar imagens**; elas são anunciadas como
  omitidas. LaTeX/PDF idem; o HTML as contém.
- **A renderização de markdown cobre a prosa do próprio Claude** (títulos,
  listas incl. aninhadas, tabelas, blocos de código de qualquer tamanho,
  citações, código/negrito/itálico/tachado/links em linha), não CommonMark
  arbitrário: sem HTML embutido, sem links de referência, sem notas de rodapé;
  células de tabela são divididas em cada `|`. Em LaTeX e PDF uma tabela é
  fatiada e, quando larga, quebrada (§5): todas as células sobrevivem, mas uma
  tabela muito larga é equalizada por coluna em vez de diagramada a gosto.
- **A classificação humano-vs-injetado** é autoritativa em registros que
  carregam `promptSource` / `origin.kind`; registros mais antigos recorrem a
  marcadores de texto, e a evidência usada é listada por registro no relatório
  de fidelidade.
- **Os horários são locais** à máquina que arquiva (passe o mouse para ver UTC
  no HTML).
- **Rearquivar com um `--title` diferente grava um arquivo novo** ao lado do
  antigo, em vez de sobrescrevê-lo.
- **Escala**: cada execução relê todos os arquivos `.jsonl` sob as raízes para
  resolver cadeias; o índice compara conjuntos de uuid par a par. Tudo bem para
  centenas de sessões; lento para milhares.
- **Plataformas**: desenvolvido e validado no Windows; a suíte e uma
  verificação estática com pyflakes rodam em Linux, Windows e macOS na CI. O
  Linux teve uma execução real (31/08/2026, WSL2 Ubuntu, Python 3.14: todos os
  formatos não-PDF de uma sessão real, `--index`, e a falha ruidosa sem
  `xelatex`). Não verificados em campo: PDF e caminhos de fontes TeX no Linux,
  sessões *cowork* produzidas no Linux, e o macOS por completo. No WSL, ler as
  transcrições através de `/mnt/c` tornou a varredura cerca de quatro vezes
  mais lenta que nativamente (18 s contra 4 s para 281 transcrições) — mantenha
  as raízes do lado Linux.
- **O envelhecimento do índice ao vivo é unidirecional**: uma sessão pode ficar
  silenciosa na tela, mas não pode voltar a ficar ativa sem regeneração
  (`--watch`).
- **A busca entre arquivos cobre prompts, não respostas** (e os primeiros 400
  caracteres de cada prompt). As respostas são buscáveis dentro de uma página.
  Indexar as respostas multiplicaria o tamanho do arquivo de índice e está
  adiado.

## 8. Testes

```bash
python tests/test_archiver.py
```

528 verificações contra as sessões sintéticas em `examples/` (sem necessidade
de transcrição real). As verificações de compilação LaTeX/PDF são puladas, não
falham, quando não há TeX no `PATH`. Para exercitá-lo em uma conversa sua:

```bash
CLAUDE_PROJECTS=~/.claude/projects SAMPLE_SESSION=<id> python tests/test_archiver.py
```

A suíte também verifica que este manual e o `AGENTS.md` documentam todas as
opções de linha de comando e que a contagem de verificações declarada no README
está atual.

## 9. Como construir este manual

```bash
python docs/build_manual.py
```

Renderiza o `USER_MANUAL.md` — e cada tradução — para `.html` e `.pdf` com o
pandoc (e o xelatex para o PDF) quando disponíveis, caso contrário com o
renderizador de Markdown do próprio arquivador para o HTML e uma nota de que o
PDF foi pulado. Os arquivos construídos são versionados para que os leitores
não precisem de ferramenta alguma.

O inglês é o texto de referência. Cada tradução registra o *digest* do texto em
inglês do qual foi feita, e a suíte falha quando o inglês mudou e a tradução
não; `python docs/build_manual.py --stamp` grava esses *digests*, depois que a
tradução foi atualizada — nunca em vez disso.
