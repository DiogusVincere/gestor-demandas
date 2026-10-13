# Gestor de Demandas

Gestor de tarefas para equipes de serviços — escritórios de contabilidade, advocacia, consultorias —
que **entende pedidos escritos em português**. Você escreve `101 pediu o balancete de agosto até sexta`
e a tarefa nasce com cliente, tipo, prazo, prioridade e checklist. Cola uma conversa de WhatsApp ou um
e-mail e ele separa quem falou, destrincha o que foi pedido e usa o que você combinou.

- **Servidor HTTP em Python** (biblioteca padrão + `rapidfuzz`), **página em JavaScript puro** (sem build,
  sem framework) e uma **bolha flutuante** opcional que fica no canto da tela.
- **Sem banco externo e sem internet**: os dados são arquivos JSON numa pasta — ou um SQLite, no servidor
  central. Roda numa máquina só, numa pasta compartilhada da rede ou num servidor com login.
- **Só regras, sem IA**: cada decisão do entendedor guarda o motivo, e a tela mostra para você corrigir
  num clique. O que você corrige vira aprendizado (apelido do cliente, prioridade, lista, responsável).

<!-- adicionar: print da tela principal (Lista) com a caixa de cima e as fichas -->

## Demonstração

**https://gestor-demandas.onrender.com** — publicado pelo `render.yaml` deste repositório (Render, plano
gratuito). Os dados são fictícios e **zeram todo dia** (e sempre que o serviço acorda): Equipe Ana Souza,
Bruno Martins e Carla Dias, os cinco clientes de exemplo e uma dúzia de tarefas com prazos relativos a
hoje — uma atrasada, uma para hoje, uma para amanhã, uma *Aguardando cliente*, uma recorrente, uma
concluída ontem, comentários, um anexo (link) e um modelo de lista. O plano gratuito hiberna sem uso, por
isso **o primeiro acesso pode levar uns 30 s**. Qualquer pessoa que abrir vê o que você escrever.

O que a demonstração desliga, em relação ao app completo: avisos pelo Windows e backup em disco (não há
máquina sua ali), anexo de **arquivo** (só link), usuários e departamentos (um departamento só, sem
login), e a bolha (que é um programa do Windows). Limites contra abuso: 64 KB por pedido, 500 tarefas ao
todo, títulos e descrições cortados em 2.000 caracteres (a conversa colada em 20.000), 50 espaços
pessoais. A faixa amarela no topo da página lembra tudo isso.

Para rodar o mesmo modo na sua máquina:

```
python servidor.py --demo            # pasta temporária, zera a cada 24 h, abre em http://127.0.0.1:8731
```

(`--demo` equivale à variável de ambiente `GESTOR_DEMO=1`; `--dados <pasta>` escolhe a pasta, que é
**apagada e recriada** na subida e a cada zeramento.)

## Para quem é

Para a equipe que recebe pedidos por todos os canais (WhatsApp, e-mail, telefone, balcão) e precisa
transformar isso em tarefas com dono e prazo sem perder tempo preenchendo formulário. O vocabulário que
vem pronto é o de um escritório contábil (CND, DAS, balancete, nota fiscal, DCTFWeb…), mas tudo está em
JSON editável — `catalogo.json`, `obrigacoes.json`, `clientes.json` — e serve a qualquer equipe que
trabalhe por cliente.

## A caixa de cima

Escreva e aperte **Enter**. O que o app entendeu aparece embaixo, em fichas clicáveis; errou, clique e
troque. **Enter nunca falha**: o que faltar fica em branco e a tarefa nasce mesmo assim. Exemplos reais,
rodados com o cadastro de exemplo que vem com o app (Equipe cadastrada: Ana Souza, Bruno Martins, Carla Dias):

| Você escreve | O app entende |
|---|---|
| `101 pediu o balancete de agosto até sexta` | cliente **101 Empresa Exemplo Ltda** (pelo código), tipo **Balancete / relatório contábil**, vence **sexta**, título *Balancete de agosto*, checklist com os 3 passos do tipo |
| `pra ana: conferir o DAS da 102 todo mês após o fechamento` | responsável **Ana Souza** (primeiro nome basta, desde que esteja na Equipe), cliente **102**, **repete todo mês** (`mensal:1:antes` — como fala em DAS, antecipa quando o dia cai em fim de semana ou feriado) |
| `me avisar a cada 30 min de ligar pro 103` | cliente **103**, tipo **Reunião / ligação**, prazo padrão do tipo (próximo dia útil), **lembrete** nesse dia **repetido a cada 30 min** (balão do Windows das 07h às 20h) |
| `padaria pediu a cnd federal e a certidão estadual, urgente` | cliente **104 Padaria Central** pelo **apelido**, tipo **Certidão negativa (CND)**, prioridade **urgente** (o motivo fica escrito: "“urgente” no texto; vence em 1 dia") |
| `todo dia 20 pagar o DAS da 105 e me lembrar` | cliente **105**, recorrência **todo dia 20** (pagamento: antecipa), próximo prazo já calculado, lembrete ligado |
| `clinica horizonte mandou o contrato assinado` | cliente **105 Clínica Horizonte** pelo **nome**, e **é informação, não demanda**: se o 105 tinha algo *Aguardando cliente*, a tela pergunta se isso destrava |

Outros jeitos de falar que ele entende:

- **Datas**: hoje, amanhã, depois de amanhã, sexta, sexta que vem, dia 15, 15/10, 20/10/2026, em 2 dias,
  em 3 dias úteis, fim do mês, semana que vem. Dias úteis pulam feriado nacional, móvel e o que estiver em
  `feriados.json`. Pelo calendário de obrigações: `pós fechamento do simples`, `antes do DAS`, `até o
  vencimento do ISS`.
- **Repetição**: `todo dia 1`, `todia 8` (erro de digitação tolerado), `toda sexta`, `a cada 15 dias`,
  `quinzenal`, `trimestral`, `todo ano`, `é recorrente`, `demanda fixa`. Com "todo mês pós fechamento do
  simples", a repetição segue a obrigação, não um dia fixo.
- **Pessoas**: `pra ana`, `atribuir à Carla`, `@bruno`, `Carla vai fazer`, `pra ana e bruno` (vários
  responsáveis). Só quem está na **Equipe** recebe tarefa.
- **Números que viram campos**: `competência 09/2026`, `mês 5`, `NF 1234`, `R$ 1.500,00` saem do título e
  vão para os campos personalizados da lista com o mesmo nome (`competencia`, `documento`, `valor`).
- **Várias numa linha**: `101, 102, 103: enviar o das` vira três tarefas, uma por cliente; `101 pediu carta
  de faturamento e cnd federal` vira duas (relacionadas).
- **Coisa sua**: `eu: ir ao RH amanhã às 10h` vai para o seu espaço pessoal (só você vê), com lembrete às
  10:00. Sem o `eu:`, palavras como "minha vez", "lavar", "médico" fazem o app adivinhar — e ele aprende
  quando você corrige.
- **Pedir aviso**: `me avisar`, `lembrar`, `alerta` → balão no dia do prazo (e "a cada 30 min", "a cada
  1:30h" repete nesse dia). Intervalos e quantidades são sempre digitados do seu jeito, não escolhidos
  numa lista fechada.
- **Já existe?** Se o cliente tem uma tarefa aberta parecida (mesmo tipo ou título parecido, nos últimos
  60 dias), aparece "já existe EQP-12": abrir, anexar o texto nela ou criar mesmo assim.

`Ctrl+K` abre a busca por ID, título, cliente ou lista; `Esc` limpa.

## Colar uma conversa inteira

Cole no mesmo campo (ou clique em 📋) um WhatsApp exportado, um e-mail com respostas encadeadas, uma
transcrição `Cliente: … / Eu: …` ou um texto solto. O app lê como **conversa**:

```
[13/10/2026, 09:12] Daniel Rocha: Bom dia! Preciso da CND federal e da CND estadual até sexta, por favor.
[13/10/2026, 09:13] Daniel Rocha: Segue o contrato social em anexo.
[13/10/2026, 09:15] Ana Souza: Bom dia, Daniel! Vou providenciar as certidões da 102. Me manda também o cartão CNPJ atualizado?
[13/10/2026, 09:16] Daniel Rocha: Mando ainda hoje.
[13/10/2026, 09:17] Daniel Rocha: Já foi pago o DAS de setembro?
```

Com você logada como Ana, sai **uma tarefa**, *CND federal e CND estadual*, cliente **102** (do "da 102"
na sua fala), tipo CND, vence **sexta**, status **Aguardando cliente** ("você pediu: “Me manda também o
cartão CNPJ atualizado?” — o cliente disse que manda"), e o checklist:

```
[ ] CND federal                                  (do cliente)
[ ] CND estadual                                 (do cliente)
[ ] Conferir contrato (enviado pelo cliente)     (anexo)
[ ] Responder: Já foi pago o DAS de setembro?    (pergunta)
[ ] Receber do cliente: cartão CNPJ atualizado   (seu)
[ ] Enviar ao cliente                            (roteiro do tipo)
```

Como ele decide:

1. **Quem falou.** Daniel é "nome desconhecido" e escreve como cliente ("preciso", "segue em anexo", "por
   favor"); Ana é você. Seu nome, a Equipe, "Você/Eu" e e-mails do domínio da equipe (`config.json`)
   são o lado da equipe; contatos do `contatos.json` são o cliente. Na prévia cada nome é uma ficha
   "cliente / equipe" — clique para corrigir, e ele lembra na próxima.
2. **O que foi pedido.** Das falas do cliente saem as tarefas e o checklist: enumerações ("balancete, a
   DRE e o razão de setembro" → três itens com 09/2026), períodos ("de julho a setembro" → um por mês),
   itens numerados do mesmo tipo viram um checklist, de tipos diferentes viram tarefas, perguntas viram
   "Responder: …", anexos viram "Conferir … (enviado pelo cliente)". Dados de nota prontos ("Tomador: …
   CNPJ: … Valor: R$ …") viram "Emitir N notas fiscais" com um item por nota e o valor somado.
3. **O que você registrou manda.** Das suas falas saem o prazo que você prometeu ("vou mandar até
   sexta"), o que você pediu ao cliente ("me manda o contrato" → "Receber do cliente: contrato"), o
   responsável, a prioridade, a recorrência e o "me avisar".
4. **Status sugerido** pela ordem das falas: você pediu e o cliente só prometeu → Aguardando cliente;
   ele mandou → A fazer com o item já marcado; você fechou com "enviado" → Concluída.

Cliente pelo remetente: e-mail ou telefone do `contatos.json`, domínio do e-mail parecido com o nome da
empresa, nome já ensinado, ou "do 102" numa fala sua. Uma palavra solta na fala do cliente nunca vira
cliente por parecença. Botões **Juntar em 1 tarefa** / **Separar em uma por item**; títulos e itens do
checklist editáveis na prévia; **Ctrl+Enter** cria tudo com a conversa inteira na descrição. Se só você
falou, cada linha é a caixa de cima.

## As visões

- **Lista**: tabela agrupada por status (ou prioridade, cliente, prazo, responsável, ou um campo de
  seleção da lista). Status, prazo, prioridade e responsáveis mudam na própria linha; ○ conclui num
  clique (com "Desfazer" por 8 s); arraste para outro grupo; caixinha para ações em lote.
- **Quadro**: colunas por status, arrastar entre colunas e para reordenar. Cada lista tem os seus status
  (tipos *aberto*, *aguardando* e *feito*).
- **Calendário**: tarefas no dia do prazo (arrastar muda), feriados e as obrigações do mês.
- **Minhas tarefas**: atrasadas, hoje, esta semana, aguardando resposta (há quantos dias), depois, sem
  prazo, concluídas hoje. Mais **Atrasadas**, **Concluídas** (por mês, no prazo × atrasada) e **Histórico**
  (quem fez o quê, quando) em "Acompanhar".
- **Painel da tarefa** em abas: Detalhes (cliente, tipo, prazo, repetir, lembrar em, campos da lista,
  descrição, anexos, ligações *começa depois de* / *relacionada*), Checklist e subtarefas, Comentários
  com `@nome`, Atividade.
- **Visões salvas** por lista, **campos personalizados** (texto, número, R$, data, seleção, sim/não,
  pessoa), **automações** "quando X então Y" (status vira, prazo passou, checklist completa, tarefa
  liberada, criada → mudar status/prioridade/responsável, lembrar, mover de lista, adiar), **modelos de
  lista** (status + campos + tarefas-esqueleto, com prazo por obrigação do mês, dia do mês ou dias úteis,
  e "uma por cliente"), **triagem** (regras *se tipo/cliente/palavra → lista/responsável/prioridade*; o
  que não bate cai na Caixa de entrada), **notificações** pessoais, **lixeira** com restaurar.

<!-- adicionar: prints do Quadro, do Calendário e do painel da tarefa -->

## A bolha

`Abrir Bolha.bat` abre uma barrinha sempre por cima, no canto da tela (arraste para onde quiser; ela
lembra o lugar). Clique, ou **Ctrl+Shift+D de qualquer programa**, e a caixa abre:

- a mesma linha inteligente, com o entendimento resumido numa linha ("101 Empresa Exemplo · carta de
  faturamento · vence sex 17/10 · para Ana"), cada parte clicável; Ctrl+V com uma conversa dá a prévia;
- o seu dia: **Meus** (só você vê), **Atrasadas**, **Hoje** e **Lembretes**, por prioridade; tocar numa
  tarefa mostra checklist, descrição e os **status da lista como botões**; ao cair em *Aguardando cliente*
  ela pergunta "lembrar de cobrar? amanhã · 2 dias úteis · sexta";
- avisos e lembretes aparecem num **balão acima da barrinha**, com "+10 min · +1 h · amanhã";
- recolhe sozinha (15 s depois de você ir para outro programa, 90 s parada), nunca com texto digitado.
  "⤢ tudo" abre o app completo numa janela própria; ⚙ tem "abrir com o Windows" e "esconder".

Precisa de `pip install -r requirements-bolha.txt` (pywebview) e do WebView2 (vem com o Edge). Sem
pywebview, abre a página da bolha no navegador. Limite do WebView2: a janela não fica transparente nem redonda — por isso é uma barrinha.

<!-- adicionar: print da bolha recolhida e aberta -->

## Avisos pelo Windows

O servidor fica ligado o dia inteiro, então **avisa mesmo com a página fechada**, pelo balão do
Windows (`toast.ps1`, sem instalar nada), para quem usou a página nessa máquina por último:

- **resumo do dia** nos horários que você escolher (padrão 08:30 e 13:30) e logo que o servidor sobe;
- **alerta de amanhã** (padrão 16:30), urgentes na frente;
- **lembretes** ("lembrar em", "me avisar", com hora e com intervalo) e **urgente para hoje** na hora.

Na página, a faixa "Seu dia" resume o mesmo, e o navegador pode mostrar a notificação dele também.
⚙ → Avisos configura horários e tem "Testar o balão".

## Departamentos e permissões (modelo B)

Vários departamentos, **um não vê as demandas do outro**. Sem servidor central, quem decide é a
**permissão da pasta**: `departamentos.json` (copie de `departamentos.exemplo.json`) lista os
departamentos e as pastas de dados — relativas à pasta do app (`dados/fiscal`) ou um caminho completo,
inclusive de rede. Ao abrir, o app carrega só as pastas que o sistema deixa ler; o resto aparece como
"sem acesso". Cada departamento tem os seus espaços (com os seus prefixos de ID), listas, modelos, regras
de triagem, Caixa de entrada, Equipe e aprendizado. **Admin** = quem consegue escrever o
`departamentos.json`; para ele aparece "Departamentos" no ⚙. Cada pessoa tem ainda um **espaço pessoal**
("Meu espaço · só você"), com Lembretes e Rotinas, que ninguém mais vê — e dá para deixar um lembrete no
espaço pessoal de outra pessoa ("Ana, tira o lixo hoje").

Várias máquinas podem abrir a mesma pasta: cada uma sobe o seu servidor, e as outras percebem a mudança em
até 5 segundos (`versao.txt`). Duas pessoas editando a **mesma** tarefa no mesmo segundo: a última gravação
vence.

## Servidor central com login (modelo A)

Numa máquina sempre ligada, `Abrir Gestor (servidor central).bat` sobe o servidor com `--host 0.0.0.0` e
todos abrem `http://NOME-DA-MAQUINA:8731`. Copie `usuarios.exemplo.json` para `usuarios.json` ao lado do
`departamentos.json` e o **login** liga: toda rota passa a exigir sessão (cookie, 30 dias), o nome da
pessoa é o do cadastro, e os papéis decidem o que cada um vê — **membro** vê os departamentos dele,
**gestor** vê os dele e os que gere, **admin** vê tudo e cadastra usuários, departamentos e clientes.
Senha escrita em claro no arquivo vira hash PBKDF2 na primeira leitura. É intranet sem HTTPS: serve para
dizer quem é quem, não contra quem já está dentro da rede com má intenção.

## Armazéns: JSON ou SQLite, e backup

Por padrão tudo é JSON na pasta de dados: `espacos.json`, `listas.json`, `modelos.json`, `equipe.json`,
`triagem.json`, `aprendizado.json`, `notificacoes.json`, uma tarefa por arquivo em `tarefas/`, 20 snapshots
por tarefa em `historico/`, `lixeira/`, `anexos/` (arquivos até 20 MB), `eventos.jsonl` (append-only: é de
onde saem Atividade, Histórico, Concluídas e Atrasadas) e `versao.txt`. Escrita atômica; várias máquinas
podem gravar na mesma pasta.

O **SQLite** (`demandas.db`, WAL, JSON em colunas TEXT, anexos em BLOB) é para o **servidor central**: um
processo só, banco no disco local. Em pasta de rede com vários servidores o SQLite corrompe — por isso não é
o padrão. Liga com `"armazem": "sqlite"` no departamento; na primeira abertura o que havia em JSON é
importado (os JSON ficam como cópia). A `Area` não sabe qual armazém está por baixo (`nucleo/armazem.py`).

**Backup**: às 18h cada departamento grava `backup/AAAA-MM-DD.json` (30 últimos) com tudo; `POST /api/backup`
faz na hora. Vale para JSON e SQLite.

## O que a equipe edita

| Arquivo | Onde | O que é |
|---|---|---|
| `clientes.json` | pasta de dados (`dados/`) | códigos, nomes e apelidos — nasce com cinco clientes de exemplo; edite pela tela (⚙ → Clientes), à mão ou por `PUT /api/clientes` |
| `contatos.json` | pasta de dados, opcional | `[{"email": …, "codigo": …}, {"telefone": …}, {"cnpj": …}]`: liga remetente a cliente na conversa colada |
| `catalogo.json` | pasta do app | os tipos de demanda: palavras que caem em cada tipo, prazo padrão em dias úteis, prioridade e checklist pronto — **é o que mais vale ajustar** |
| `obrigacoes.json` | pasta do app, opcional | as obrigações do mês (dia e regra de dia útil); modelo em `obrigacoes.exemplo.json` |
| `feriados.json` | pasta do app, opcional | feriados além dos nacionais e móveis, `{"2026-09-30": "Aniversário do município"}`; modelo em `feriados.exemplo.json` |
| `config.json` | pasta do app, opcional | `dominio_equipe` (padrão `empresa.exemplo`); a variável de ambiente `DOMINIO_EQUIPE` vale mais |
| `departamentos.json` | pasta do app, opcional | departamentos e pastas (modelo B); modelo em `departamentos.exemplo.json` |
| `usuarios.json` | ao lado do `departamentos.json`, opcional | liga o login (modelo A); modelo em `usuarios.exemplo.json` |

Os arquivos de dados e de configuração local estão no `.gitignore`; só os `*.exemplo.json` são versionados.

## Como rodar

```
pip install -r requirements.txt        # rapidfuzz (a bolha pede também requirements-bolha.txt)
python servidor.py                     # sobe em http://127.0.0.1:8731 e abre o navegador
```

Funciona no Windows, Linux e macOS (Python 3.12 ou mais novo); o que é só do Windows — balão de aviso,
bolha, os `.bat` — fica de fora nos outros sistemas sem quebrar nada.

Ou dê dois cliques em `Abrir Gestor de Demandas.bat` (Windows). Na primeira abertura ele cria `dados/` com
o espaço **Equipe** (IDs `EQP-1`, `EQP-2`…), as listas **Caixa de entrada**, **Demandas de clientes** e
**Pendências internas**, a Equipe vazia e o `clientes.json` de exemplo — e pergunta o seu nome. Cadastre
a Equipe em ⚙ → Equipe (é o que "pra ana" reconhece).

Opções do `servidor.py`:

| Opção | Para quê |
|---|---|
| `--porta 8731` | a porta (a bolha procura o servidor na 8731); a variável de ambiente `PORT` vale quando existe |
| `--host 127.0.0.1` | só esta máquina (padrão); `0.0.0.0` = servidor central (e o padrão do `--demo`) |
| `--dados <pasta>` | pasta de dados quando não há `departamentos.json` (padrão `dados/`) |
| `--demo` | demonstração: dados fictícios numa pasta temporária, zerados a cada 24 h, sem avisos nem anexos de arquivo, com limites de uso (= `GESTOR_DEMO=1`) |
| `--clientes <arquivo>` | outro `clientes.json` (padrão `<dados>/clientes.json`) |
| `--departamentos <json>` | outro `departamentos.json`; `-` ignora o do app |
| `--usuarios <json>` | outro `usuarios.json`; `-` desliga o login mesmo que exista |
| `--local <pasta>` | onde fica a configuração desta máquina (`avisos.json`); padrão `%LOCALAPPDATA%\GestorDemandas` (`~/.config/GestorDemandas` fora do Windows) |
| `--sem-navegador` | não abre o navegador |
| `--sem-avisos` | não dispara balões do Windows (testes) |

Se a porta já está em uso por este mesmo app, ele só abre a página; se for uma versão mais antiga do
código, pede para ela sair e sobe no lugar (a página recarrega sozinha). Erros do servidor vão para
`erros.log`.

## A API, em resumo

Tudo em JSON sob `/api`. O nome de quem está usando vai no cabeçalho `X-Pessoa` (codificado com
`encodeURIComponent`); com login ligado vale o cookie da sessão.

- `GET /api/tudo` — espaços, listas, tarefas, modelos, triagem, equipe, departamentos; `GET /api/versao`
  (versão dos dados, versão do código e `demo: true` quando é a demonstração).
- `POST /api/entender {texto}` — a prévia da linha; `POST /api/colar {texto, lados?, juntar?}` — a prévia
  da conversa.
- `POST /api/tarefas {lista, texto, ajustes}` (`modo: "colar"` com `ajustes.pedidos` para a conversa);
  `GET|PATCH|DELETE /api/tarefas/<id>`; `/mover`, `/concluir`, `/adiar`, `/historico`, `/comentarios`,
  `/anexos`; `PATCH /api/tarefas/lote`.
- `/api/espacos`, `/api/listas`, `/api/listas/de-modelo`, `/api/modelos`, `/api/equipe`, `/api/triagem`,
  `/api/clientes` (`?q=` busca; sem `q` devolve o cadastro; `PUT` substitui), `/api/calendario?ano&mes`,
  `/api/eventos`, `/api/notificacoes`, `/api/lixeira`, `/api/avisos`, `/api/backup`, `/api/departamentos`.
- Modelo A: `POST /api/login`, `POST /api/sair`, `GET /api/eu`, `/api/usuarios` (admin), `POST /api/senha`.

## Estrutura de pastas

```
servidor.py                      o servidor HTTP e as rotas da API (e o modo --demo)
bolha.pyw                        a bolha flutuante (pywebview + WebView2)
toast.ps1                        o balão do Windows
render.yaml                      o Blueprint da demonstração pública no Render
requirements.txt                 rapidfuzz; requirements-bolha.txt acrescenta o pywebview
catalogo.json                    tipos de demanda (editável)
*.exemplo.json                   modelos de departamentos, usuários, config, feriados, obrigações
Abrir Gestor de Demandas.bat     abre o servidor local e a página
Abrir Bolha.bat                  abre a bolha
Abrir Gestor (servidor central).bat
nucleo/
  clientes.py      cadastro de clientes (clientes.json, contatos.json), apelidos, parecença de nomes
  entender.py      a linha única → cliente, tipo, prazo, pessoas, recorrência, aviso, hora, pessoal
  conversa.py      a conversa colada → turnos, lados, pedidos, checklist, status, prazo combinado
  mensagem.py      formato (WhatsApp / e-mail / texto) e remetente de uma mensagem
  catalogo.py      leitura do catálogo e busca do tipo no texto
  calendario.py    dias úteis, feriados nacionais e móveis, obrigações do mês
  importancia.py   a prioridade sugerida, com o motivo
  dados.py         a Area de um departamento: espaços, listas, tarefas, triagem, automações, eventos…
  armazem.py       ArmazemJSON e ArmazemSQLite
  escritorio.py    vários departamentos + o espaço pessoal de cada um
  usuarios.py      login, senhas e papéis (modelo A)
  avisos.py        o relógio dos balões e o backup diário
  config.py        domínio de e-mail da equipe
  demo.py          a semente e os limites do modo demonstração
web/
  index.html, app.js, estilo.css   a página
  bolha.html, bolha.js             a bolha
dados/                           nasce na primeira abertura (ignorado pelo git)
```

## Licença

MIT — veja `LICENSE`.
