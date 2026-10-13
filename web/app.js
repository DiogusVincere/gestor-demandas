/* Gestor de Demandas — a página. Fala com o servidor em /api e desenha as visões. */
"use strict";

const E = {
  dados: null, pessoa: "", lista: "", visaoFixa: "", visao: "lista", filtro: "", agrupar: "status",
  mostrarFeitas: false, selecionada: "", mes: null, ajustes: {}, previa: null, cal: {}, recolhidos: {},
  ordenar: null, arrastando: "", visaoSalva: "", colunasOcultas: ["prioridade", "feito"],
  selecao: new Set(), fichasAbertas: false, abaPainel: "detalhes", notificacoes: [], naoLidas: 0,
};
const PRIO_ROTULO = { urgente: "Urgente", alta: "Alta", normal: "Normal", baixa: "Baixa" };
const PRIO_COR = { urgente: "#A33C2E", alta: "#EF9F27", normal: "#378ADD", baixa: "#B4B2A9" };
const DIAS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const DIAS_CHAVE = ["dom", "seg", "ter", "qua", "qui", "sex", "sab"];
const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
  "outubro", "novembro", "dezembro"];
const TIPO_CAMPO_ROTULO = { texto: "Texto", numero: "Número", dinheiro: "R$", data: "Data", selecao: "Seleção", simnao: "Sim/não", pessoa: "Pessoa" };
const EVENTO_ROTULO = { status: "status vira", criada: "é criada", prazo_passou: "o prazo passa", checklist_completo: "checklist completa", prioridade: "prioridade vira", liberada: "é liberada (o que ela dependia foi concluído)" };
const ACAO_ROTULO = { status: "mudar status para", prioridade: "mudar prioridade para", responsavel: "atribuir a", lembrar: "lembrar em (dias)", mover_lista: "mover para a lista", prazo_mais: "adiar o prazo (dias)" };
const COLUNAS_BASE = [["status", "Status"], ["cliente", "Cliente"], ["prazo", "Prazo"], ["prioridade", "Prioridade"], ["responsavel", "Responsável"], ["feito", "Feito"]];

/* ---------------------------------------------------------------- utilidades */
const $ = (s, raiz = document) => raiz.querySelector(s);
const $$ = (s, raiz = document) => Array.from(raiz.querySelectorAll(s));
function el(tag, attrs = {}, filhos = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v === true ? "" : v);
  }
  for (const f of [].concat(filhos)) if (f !== null && f !== undefined) n.append(f.nodeType ? f : document.createTextNode(String(f)));
  return n;
}
async function api(metodo, caminho, corpo) {
  const r = await fetch(caminho, {
    method: metodo,
    headers: { "Content-Type": "application/json", "X-Pessoa": encodeURIComponent(E.pessoa) },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  let json = {};
  try { json = await r.json(); } catch (e) { json = {}; }
  if (r.status === 401 && json.login_ligado) { E.loginLigado = true; pedirLogin(); throw new Error("faça login"); }
  if (!r.ok) { aviso(json.erro || `erro ${r.status}`); throw new Error(json.erro || r.status); }
  return json;
}
let avisoTimer = null;
/* aviso("texto") — ou aviso("Concluída", { rotulo: "Desfazer", acao: async () => … }) para dar 8 s de arrependimento */
function aviso(texto, desfazer) {
  const a = $("#aviso"); a.textContent = texto; a.classList.remove("oculto");
  // pode ser uma ação ou várias ([{rotulo, acao}, …] — "Cobrar em 2 dias úteis" e "Desfazer" no mesmo aviso)
  const acoes = (Array.isArray(desfazer) ? desfazer : [desfazer]).filter(x => x && x.acao);
  for (const d of acoes) a.append(el("button", { class: "desfazer", text: d.rotulo || "Desfazer", onclick: async () => { a.classList.add("oculto"); try { await d.acao(); } catch (e) { } } }));
  clearTimeout(avisoTimer); avisoTimer = setTimeout(() => a.classList.add("oculto"), acoes.length ? 8000 : 2800);
}
function hojeISO() { return isoDe(new Date()); }
function dataDe(iso) { const [a, m, d] = iso.split("-").map(Number); return new Date(a, m - 1, d); }
function isoDe(d) { return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, "0"), String(d.getDate()).padStart(2, "0")].join("-"); }
function diasAte(iso) { if (!iso) return null; return Math.round((dataDe(iso) - dataDe(hojeISO())) / 86400000); }
function fmtPrazo(iso) {
  const n = diasAte(iso);
  if (n === null) return "";
  const d = dataDe(iso), dm = `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
  if (n === 0) return "hoje"; if (n === 1) return "amanhã"; if (n < 0) return `${-n}d atrás`;
  if (n <= 6) return `${DIAS[d.getDay()]} ${dm}`; return dm;
}
function fmtDataCurta(iso) { return iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : ""; }
function classePrazo(t) { const n = diasAte(t.prazo); if (n === null || feita(t)) return ""; if (n < 0) return "atrasado"; if (n === 0) return "hoje"; return ""; }
function iniciais(nome) { return (nome || "").split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join("") || "?"; }
function listaDe(id) { return E.dados.listas.find(l => l.id === id); }
function espacoDe(id) { return E.dados.espacos.find(e => e.id === id); }
function statusDe(t) { const l = listaDe(t.lista); return (l && l.status.find(s => s.id === t.status)) || { id: t.status, nome: t.status, cor: "#B4B2A9", tipo: "aberto" }; }
function feita(t) { return statusDe(t).tipo === "feito"; }
function tarefa(id) { return E.dados.tarefas.find(t => t.id === id); }
function filhasDe(id) { return E.dados.tarefas.filter(t => t.pai === id).sort((a, b) => a.ordem - b.ordem); }
function bloqueiosDe(t) { return (t.ligacoes || []).filter(l => l.tipo === "depende").map(l => tarefa(l.alvo)).filter(x => x && !feita(x)); }
function nomeCliente(t) { if (!t.cliente) return ""; const partes = (t.cliente_nome || "").split(/\s+/).filter(p => p.length > 2 && !/^(LTDA|EIRELI|EIRE|ME|EPP|SA|S\/A|DE|DA|DO|DOS|DAS|E|SOCIEDADE|INDIVIDUAL|COMERCIO|SERVICOS)$/i.test(p)); return `${t.cliente} ${partes.slice(0, 2).join(" ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase())}`; }
function progresso(t) { if (!t.checklist || !t.checklist.length) return ""; const f = t.checklist.filter(i => i.feito).length; return `${f}/${t.checklist.length}`; }
function bateFiltro(t) {
  if (!E.filtro) return true;
  const alvo = `${t.chave || ""} ${t.titulo} ${t.cliente} ${t.cliente_nome} ${donos(t).join(" ")} ${t.descricao || ""} ${Object.values(t.campos || {}).join(" ")}`.toLowerCase();
  return E.filtro.toLowerCase().split(/\s+/).every(p => alvo.includes(p));
}
function prioTag(t) { return el("span", { class: `prio prio-${t.prioridade}`, text: PRIO_ROTULO[t.prioridade] || t.prioridade }); }
/* uma tarefa pode ser de várias pessoas (`responsaveis`); `responsavel` é a primeira */
function donos(t) { return (t.responsaveis && t.responsaveis.length) ? t.responsaveis : (t.responsavel ? [t.responsavel] : []); }
function minha(t) { const d = donos(t); return d.includes(E.pessoa) || (!d.length && t.criada_por === E.pessoa); }
function pessoaTag(t) {
  const d = donos(t); if (!d.length) return el("span");
  const caixa = el("span", { class: "pessoas", title: d.join(", ") });
  d.slice(0, 3).forEach(n => caixa.append(el("span", { class: "pessoa", text: iniciais(n) })));
  if (d.length > 3) caixa.append(el("span", { class: "mais", text: `+${d.length - 3}` }));
  return caixa;
}
function chaveTag(t) { return el("span", { class: "chave", text: t.chave || "" }); }
function fmtCampo(c, v) {
  if (v === undefined || v === null || v === "") return "";
  if (c.tipo === "dinheiro") return "R$ " + Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (c.tipo === "data") return fmtDataCurta(String(v));
  if (c.tipo === "simnao") return v ? "sim" : "não";
  return String(v);
}
function pessoasConhecidas(extra) { return [...new Set([E.pessoa, ...E.dados.pessoas, extra].filter(Boolean))]; }

/* ---------------------------------------------------------------- menu de contexto e diálogo */
let menuAbertoEm = 0;
function menu(x, y, itens) {
  // o clique que abre o menu ainda vai subir até o document; sem esta marca ele fecharia na hora
  menuAbertoEm = Date.now();
  const m = $("#menu"); m.innerHTML = ""; m.classList.remove("oculto");
  for (const it of itens) {
    if (it === "sep") { m.append(el("hr")); continue; }
    m.append(el("div", { class: it.perigo ? "perigo" : "", text: it.rotulo, onclick: () => { fecharMenu(); it.acao(); } }));
  }
  m.style.left = Math.min(x, window.innerWidth - 240) + "px";
  m.style.top = Math.min(y, window.innerHeight - 36 * itens.length - 20) + "px";
}
function fecharMenu() { $("#menu").classList.add("oculto"); }
function dialogo(titulo, corpo, botoes) {
  const caixa = $("#dialogo-caixa"); caixa.innerHTML = "";
  caixa.append(el("div", { class: "dialogo-topo" }, [el("h2", { text: titulo }), el("button", { class: "mini", text: "×", onclick: fecharDialogo })]));
  caixa.append(corpo);
  const rod = el("div", { class: "dialogo-rodape" });
  rod.append(el("div", {}, botoes.esquerda || []));
  rod.append(el("div", { class: "direita" }, botoes.direita || []));
  caixa.append(rod);
  $("#dialogo").classList.remove("oculto");
}
function fecharDialogo() { $("#dialogo").classList.add("oculto"); }
document.addEventListener("click", e => { if (!e.target.closest("#menu") && Date.now() - menuAbertoEm > 150) fecharMenu(); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    fecharMenu(); $("#notif-pop").classList.add("oculto"); $("#filtros-pop").classList.add("oculto");
    if (!$("#busca").classList.contains("oculto")) $("#busca").classList.add("oculto");
    else if (!$("#dialogo").classList.contains("oculto")) fecharDialogo();
    else if (E.selecao.size) { E.selecao.clear(); renderVisao(); renderLoteBarra(); }
    else if (!$("#painel").classList.contains("fechado")) fecharPainel();
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); abrirBusca(); }
});
document.addEventListener("click", e => {
  // clique fora fecha as caixinhas de notificações e filtros
  if (!e.target.closest("#notif-pop, #bt-notif")) $("#notif-pop").classList.add("oculto");
  if (!e.target.closest("#filtros-pop, #bt-filtros")) $("#filtros-pop").classList.add("oculto");
});

/* ---------------------------------------------------------------- carga */
async function carregar(primeira = false) {
  E.dados = await api("GET", "/api/tudo");
  if (primeira) {
    const guardada = localStorage.getItem("demandas.lista");
    E.lista = listaDe(guardada) ? guardada : (E.dados.listas[0] ? E.dados.listas[0].id : "");
    E.visao = localStorage.getItem("demandas.visao") || "lista";
    const hoje = new Date(); E.mes = { ano: hoje.getFullYear(), mes: hoje.getMonth() + 1 };
  }
  if (E.lista && !listaDe(E.lista)) E.lista = E.dados.listas[0] ? E.dados.listas[0].id : "";
  if (primeira) {
    // a bolha abre o app já numa tarefa: /?tarefa=<id>
    const pedida = new URLSearchParams(location.search).get("tarefa");
    const t = pedida && tarefa(pedida);
    if (t) { E.lista = t.lista; E.visaoFixa = ""; E.selecionada = t.id; $("#painel").classList.remove("fechado"); history.replaceState(null, "", "/"); }
  }
  for (const id of [...E.selecao]) if (!tarefa(id)) E.selecao.delete(id);
  renderLateral(); renderCabecalho(); renderLembretes(); await renderVisao(); renderLoteBarra();
  if (E.selecionada) { if (tarefa(E.selecionada)) renderPainel(); else fecharPainel(); }
  if (primeira) { carregarAvisos(true); carregarNotificacoes(); }
  const eq = (E.dados.equipe || {})[departamentoDaLista(E.lista) || ""] || [];
  $("#equipe-lateral").textContent = eq.length ? eq.join(", ") : "ninguém cadastrado — clique em ⋯";
}
let codigoDoServidor = "";
/* a faixa "Demonstração pública…" — só quando /api/versao diz demo: true (o servidor público do Render) */
function faixaDemo(v) {
  const f = $("#faixa-demo");
  if (!f || !v || !v.demo) return;
  const quando = v.demo_zera_em ? `Zera ${fmtDataCurta(v.demo_zera_em)} às ${v.demo_zera_em.slice(11, 16)}.` : "";
  if (f.dataset.pronta) {
    // já desenhada: só atualiza a hora do próximo zeramento (muda depois que os dados zeram); se a pessoa escondeu, fica escondida
    const q = f.querySelector(".quando"); if (q && q.textContent !== quando) q.textContent = quando;
    return;
  }
  f.dataset.pronta = "1"; f.innerHTML = "";
  f.append(el("span", { text: v.demo_faixa || "Demonstração pública: os dados são fictícios e zeram todo dia. Qualquer um que abrir vê o que você escrever." }));
  f.append(el("span", { class: "quando", text: quando }));
  f.append(el("button", { class: "mini", text: "×", title: "esconder por agora", onclick: () => f.classList.add("oculto") }));
  f.classList.remove("oculto");
}
setInterval(async () => {
  if (!E.dados) return;
  try {
    const v = await api("GET", "/api/versao");
    // o servidor foi trocado por uma versão nova: a página recarrega para pegar o código novo
    if (codigoDoServidor && v.codigo && v.codigo !== codigoDoServidor) { location.reload(); return; }
    codigoDoServidor = v.codigo || codigoDoServidor;
    faixaDemo(v);
    if (v.versao !== E.dados.versao) await carregar();
  } catch (e) { }
}, 5000);

/* ---------------------------------------------------------------- lateral */
function caixaDeEntradaDe(dep) {
  const tri = (E.dados.triagem || {})[dep] || {};
  return listaDe(tri.caixa_entrada) || E.dados.listas.find(l => l.departamento === dep && /caixa de entrada/i.test(l.nome)) || null;
}
function renderLateral() {
  $("#quem").textContent = E.pessoa + (E.loginLigado && E.usuario ? ` · ${E.usuario.papel}` : "");
  $("#bt-trocar-nome").classList.toggle("oculto", !!E.loginLigado);
  const caixaAtual = caixaDeEntradaDe(departamentoDaLista(E.lista) || (departamentosAcessiveis()[0] || {}).nome);
  $$("#nav-fixa .nav-item, #nav-acompanhar .nav-item").forEach(n => n.classList.toggle("ativo", !!n.dataset.visaoFixa && n.dataset.visaoFixa === E.visaoFixa));
  $("#nav-caixa").classList.toggle("ativo", !E.visaoFixa && !!caixaAtual && E.lista === caixaAtual.id);
  const abertasCaixa = E.dados.tarefas.filter(t => !t.pai && !feita(t) && E.dados.listas.some(l => l.id === t.lista && /caixa de entrada/i.test(l.nome))).length;
  $("#caixa-conta").textContent = abertasCaixa || "";
  const caixa = $("#espacos"); caixa.innerHTML = "";
  const deps = E.dados.departamentos || [];
  const varios = deps.filter(d => d.acessivel).length > 1 || deps.some(d => !d.acessivel);
  let depAtual = null;
  for (const e of E.dados.espacos) {
    if ((varios || e.departamento === "Meu espaço" || depAtual === "Meu espaço") && e.departamento !== depAtual) {
      depAtual = e.departamento;
      const d = deps.find(x => x.nome === depAtual) || {};
      // "Meu espaço" é só seu — ganha o próprio cabeçalho, mesmo com um departamento só
      const meu = depAtual === "Meu espaço";
      caixa.append(el("div", { class: "dep-cab", title: meu ? "Só você vê o que está aqui" : "" }, [
        el("span", { class: "espaco-cor", style: `background:${meu ? "#5E706E" : (d.cor || "#9DB8D4")}` }),
        el("span", { text: meu ? "Meu espaço · só você" : depAtual })]));
    }
    const listas = E.dados.listas.filter(l => l.espaco === e.id);
    const bloco = el("div", { class: "espaco" + (E.recolhidos[e.id] ? " recolhido" : "") });
    const cab = el("div", { class: "espaco-cab", onclick: () => { E.recolhidos[e.id] = !E.recolhidos[e.id]; renderLateral(); } }, [
      el("span", { class: "espaco-cor", style: `background:${e.cor}` }),
      el("span", { class: "nome", text: e.nome }), el("span", { class: "chave", text: e.prefixo || "" }),
      el("span", { class: "seta", text: E.recolhidos[e.id] ? "▸" : "▾" }),
    ]);
    cab.addEventListener("contextmenu", ev => { ev.preventDefault(); menuEspaco(ev, e); });
    bloco.append(cab);
    const ul = el("div", { class: "listas" });
    for (const l of listas) {
      const abertas = E.dados.tarefas.filter(t => t.lista === l.id && !feita(t) && !t.pai).length;
      const item = el("div", { class: "lista-item" + (l.id === E.lista && !E.visaoFixa ? " ativo" : ""), onclick: () => escolherLista(l.id) }, [
        el("span", { text: l.nome }), el("span", { class: "conta", text: abertas || "" })]);
      item.addEventListener("contextmenu", ev => { ev.preventDefault(); menuLista(ev, l); });
      ul.append(item);
    }
    ul.append(el("div", { class: "lista-nova", text: "+ lista", onclick: ev => menuNovaLista(ev, e.id) }));
    bloco.append(ul); caixa.append(bloco);
  }
  const ml = $("#modelos-lateral"); ml.innerHTML = "";
  for (const m of E.dados.modelos || []) {
    ml.append(el("div", { class: "modelo-item", onclick: () => dialogoNovaListaDeModelo(m.id), title: "Criar lista a partir deste modelo" }, [
      el("span", { text: m.nome }), el("span", { class: "apagado", text: `  ${(m.tarefas || []).length} tarefa(s)` })]));
  }
  if (!(E.dados.modelos || []).length) ml.append(el("div", { class: "modelo-item apagado", text: "nenhum ainda — ⚙ na lista → Salvar como modelo" }));
  for (const d of deps.filter(x => !x.acessivel)) caixa.append(el("div", { class: "dep-cab sem-acesso", title: d.erro || "", text: `${d.nome} — sem acesso` }));
  const tris = E.dados.triagem || {};
  const nRegras = Object.values(tris).reduce((n, t) => n + ((t && t.regras) || []).length, 0);
  $("#triagem-lateral").textContent = `${nRegras} regra(s)` + (Object.values(tris).some(t => t && listaDe(t.caixa_entrada)) ? " · sobra vai para a Caixa de entrada" : " · sem Caixa de entrada");
  $("#titulo-departamentos").classList.toggle("oculto", !E.dados.admin);
  const dl = $("#departamentos-lateral"); dl.innerHTML = "";
  if (E.dados.admin) dl.append(el("div", { class: "modelo-item apagado", text: `${deps.length} departamento(s): ${deps.filter(d => d.acessivel).length} acessível(is)`, onclick: dialogoDepartamentos }));
}
function departamentoDaLista(lid) { const l = listaDe(lid); return l ? l.departamento : ""; }
function departamentosAcessiveis() { return (E.dados.departamentos || []).filter(d => d.acessivel); }
function dialogoDepartamentos() {
  const deps = (E.dados.departamentos || []).map(d => ({ nome: d.nome, pasta: d.pasta, cor: d.cor || "", acessivel: d.acessivel, erro: d.erro }));
  const corpo = el("div");
  corpo.append(el("p", { class: "dica", text: "Cada departamento tem a sua pasta de dados (relativa à pasta do app ou um caminho completo). Quem enxerga o quê é a permissão da pasta (TI): membro lê só a do seu departamento; gestor lê todas. Esta tela só diz onde fica cada pasta." }));
  const tab = el("table", { class: "dialogo-tabela" });
  tab.append(el("thead", {}, el("tr", {}, ["Departamento", "Pasta de dados", "Cor", "Acesso", ""].map(x => el("th", { text: x })))));
  const tb = el("tbody"); tab.append(tb);
  const desenhar = () => {
    tb.innerHTML = "";
    deps.forEach((d, i) => tb.append(el("tr", {}, [
      el("td", {}, el("input", { type: "text", value: d.nome, oninput: e => d.nome = e.target.value })),
      el("td", {}, el("input", { type: "text", value: d.pasta, placeholder: "dados/contabil (relativa à pasta do app) ou um caminho completo", oninput: e => d.pasta = e.target.value })),
      el("td", {}, el("input", { type: "color", value: d.cor || "#9DB8D4", oninput: e => d.cor = e.target.value })),
      el("td", { class: "apagado", text: d.acessivel ? "ok" : (d.erro || "novo") }),
      el("td", {}, el("button", { class: "mini perigo", text: "×", onclick: () => { deps.splice(i, 1); desenhar(); } })),
    ])));
  };
  desenhar(); corpo.append(tab);
  dialogo("Departamentos (admin)", corpo, {
    esquerda: [el("button", { text: "+ Departamento", onclick: () => { deps.push({ nome: "", pasta: "", cor: "#9DB8D4" }); desenhar(); } })],
    direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Salvar", onclick: async () => {
      try { await api("PATCH", "/api/departamentos", { departamentos: deps.filter(d => d.nome.trim() && d.pasta.trim()) }); fecharDialogo(); await carregar(); aviso("Departamentos salvos. A permissão de cada pasta é com a TI."); } catch (e) { }
    } })],
  });
}
$("#bt-triagem").onclick = () => dialogoTriagem();
function dialogoTriagem(departamento) {
  const deps = departamentosAcessiveis();
  const dep = departamento || departamentoDaLista(E.lista) || (deps[0] ? deps[0].nome : "");
  const tri = (E.dados.triagem || {})[dep] || { caixa_entrada: "", regras: [] };
  const regras = (tri.regras || []).map(r => ({ id: r.id, se: { ...r.se }, entao: { ...r.entao } }));
  const corpo = el("div");
  corpo.append(el("p", { class: "dica", text: "Quando uma demanda chega sem você estar numa lista (colada, de Minhas tarefas, da Caixa de entrada do e-mail), estas regras dizem para onde ela vai e de quem é. O que não bate em regra nenhuma cai na Caixa de entrada." }));
  if (deps.length > 1) corpo.append(el("div", { class: "linha-form" }, [el("label", { text: "Departamento" }), el("select", { onchange: e => { fecharDialogo(); dialogoTriagem(e.target.value); } }, deps.map(d => el("option", { value: d.nome, text: d.nome, selected: d.nome === dep })))]));
  const listasDep = E.dados.listas.filter(l => l.departamento === dep);
  const selCaixa = el("select", {}, [el("option", { value: "", text: "— nenhuma (fica na lista aberta)" }), ...listasDep.map(l => el("option", { value: l.id, text: `${(espacoDe(l.espaco) || {}).nome || ""} / ${l.nome}`, selected: l.id === tri.caixa_entrada }))]);
  corpo.append(el("div", { class: "linha-form" }, [el("label", { text: "Caixa de entrada" }), selCaixa]));
  const caixaR = el("div"); corpo.append(caixaR);
  const desenhar = () => {
    caixaR.innerHTML = "";
    regras.forEach((r, i) => {
      const linha = el("div", { class: "regra-triagem" });
      linha.append(el("span", { class: "rot", text: "se" }));
      linha.append(el("select", { onchange: e => r.se.tipo = e.target.value }, [el("option", { value: "", text: "qualquer tipo", selected: !r.se.tipo }), ...Object.entries(E.dados.tipos).sort((a, b) => a[1].localeCompare(b[1])).map(([k, n]) => el("option", { value: k, text: n, selected: k === r.se.tipo }))]));
      linha.append(el("input", { type: "text", value: r.se.cliente || "", placeholder: "cliente (código)", oninput: e => r.se.cliente = e.target.value }));
      linha.append(el("input", { type: "text", value: r.se.palavra || "", placeholder: "palavra no título", oninput: e => r.se.palavra = e.target.value }));
      linha.append(el("span", { class: "rot", text: "então" }));
      linha.append(el("select", { onchange: e => r.entao.lista = e.target.value }, [el("option", { value: "", text: "mesma lista", selected: !r.entao.lista }), ...listasDep.map(l => el("option", { value: l.id, text: l.nome, selected: l.id === r.entao.lista }))]));
      linha.append(el("select", { onchange: e => r.entao.responsavel = e.target.value }, [el("option", { value: "", text: "responsável: —", selected: !r.entao.responsavel }), ...pessoasConhecidas(r.entao.responsavel).map(n => el("option", { value: n, text: n, selected: n === r.entao.responsavel }))]));
      linha.append(el("select", { onchange: e => r.entao.prioridade = e.target.value }, [el("option", { value: "", text: "prioridade: —", selected: !r.entao.prioridade }), ...Object.keys(PRIO_ROTULO).map(p => el("option", { value: p, text: PRIO_ROTULO[p], selected: p === r.entao.prioridade }))]));
      linha.append(el("button", { class: "mini perigo", text: "×", onclick: () => { regras.splice(i, 1); desenhar(); } }));
      caixaR.append(linha);
    });
    if (!regras.length) caixaR.append(el("div", { class: "sem-nada", text: "Nenhuma regra. Tudo o que chega sem lista vai para a Caixa de entrada." }));
  };
  desenhar();
  dialogo("Triagem — o que vai para onde", corpo, {
    esquerda: [el("button", { text: "+ Regra", onclick: () => { regras.push({ se: {}, entao: {} }); desenhar(); } })],
    direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Salvar", onclick: async () => {
      await api("PATCH", "/api/triagem", { departamento: dep, caixa_entrada: selCaixa.value, regras }); fecharDialogo(); carregar(); aviso("Triagem salva.");
    } })],
  });
}
function escolherLista(id) { E.lista = id; E.visaoFixa = ""; E.visaoSalva = ""; E.filtro = ""; $("#filtro").value = ""; localStorage.setItem("demandas.lista", id); renderLateral(); renderCabecalho(); renderVisao(); }
function menuNovaLista(ev, espacoId) {
  const itens = [{ rotulo: "Lista vazia", acao: () => novaLista(espacoId) }];
  for (const m of E.dados.modelos || []) itens.push({ rotulo: `A partir do modelo "${m.nome}"`, acao: () => dialogoNovaListaDeModelo(m.id, espacoId) });
  menu(ev.clientX, ev.clientY, itens);
}
async function novaLista(espacoId) { const nome = prompt("Nome da lista:"); if (!nome) return; const l = await api("POST", "/api/listas", { espaco: espacoId, nome }); await carregar(); escolherLista(l.id); }
function menuEspaco(ev, e) {
  menu(ev.clientX, ev.clientY, [
    { rotulo: "Renomear espaço", acao: async () => { const n = prompt("Nome:", e.nome); if (n) { await api("PATCH", `/api/espacos/${e.id}`, { nome: n }); carregar(); } } },
    { rotulo: `Prefixo dos IDs (${e.prefixo})…`, acao: async () => { const p = prompt(`Prefixo (até 6 letras). As tarefas deste espaço mudam de ${e.prefixo}-12 para o novo:`, e.prefixo); if (p && p.toUpperCase() !== e.prefixo) { await api("PATCH", `/api/espacos/${e.id}`, { prefixo: p }); carregar(); } } },
    { rotulo: "Trocar cor", acao: async () => { const cores = ["#2F5D8A", "#7F77DD", "#D85A30", "#D4537E", "#378ADD", "#639922", "#BA7517"]; const i = (cores.indexOf(e.cor) + 1) % cores.length; await api("PATCH", `/api/espacos/${e.id}`, { cor: cores[i] }); carregar(); } },
    { rotulo: "+ Lista neste espaço", acao: () => novaLista(e.id) },
    "sep",
    { rotulo: "Apagar espaço", perigo: true, acao: async () => { if (confirm(`Apagar o espaço "${e.nome}"? Só dá se estiver sem listas.`)) { await api("DELETE", `/api/espacos/${e.id}`); carregar(); } } },
  ]);
}
function menuLista(ev, l) {
  const outros = E.dados.espacos.filter(e => e.id !== l.espaco);
  menu(ev.clientX, ev.clientY, [
    { rotulo: "Renomear lista", acao: async () => { const n = prompt("Nome:", l.nome); if (n) { await api("PATCH", `/api/listas/${l.id}`, { nome: n }); carregar(); } } },
    { rotulo: "Campos personalizados…", acao: () => dialogoCampos(l) },
    { rotulo: "Automações…", acao: () => dialogoAutomacoes(l) },
    { rotulo: "Salvar como modelo…", acao: () => salvarComoModelo(l) },
    ...outros.map(e => ({ rotulo: `Mover para ${e.nome}`, acao: async () => { await api("PATCH", `/api/listas/${l.id}`, { espaco: e.id }); carregar(); } })),
    "sep",
    { rotulo: "Apagar lista (tarefas vão para a lixeira)", perigo: true, acao: async () => { if (confirm(`Apagar a lista "${l.nome}" e mandar as tarefas dela para a lixeira?`)) { await api("DELETE", `/api/listas/${l.id}`); E.lista = ""; carregar(true); } } },
  ]);
}
async function novoEspaco(departamento) {
  const nome = prompt("Nome do espaço:"); if (!nome) return;
  const prefixo = prompt("Prefixo dos IDs (até 6 letras, ex.: EQP, FIS, CON):", nome.replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase()) || "";
  await api("POST", "/api/espacos", { nome, prefixo, departamento }); carregar();
}
$("#bt-novo-espaco").onclick = ev => {
  const deps = departamentosAcessiveis();
  if (deps.length > 1) menu(ev.clientX, ev.clientY, deps.map(d => ({ rotulo: `No ${d.nome}`, acao: () => novoEspaco(d.nome) })));
  else novoEspaco(deps[0] ? deps[0].nome : "");
};
$$("#nav-fixa .nav-item[data-visao-fixa], #nav-acompanhar .nav-item").forEach(n => n.onclick = () => { E.visaoFixa = n.dataset.visaoFixa; E.selecao.clear(); renderLateral(); renderCabecalho(); renderVisao(); renderLoteBarra(); });
$("#bt-trocar-nome").onclick = () => pedirNome(true);
$("#bt-modelos").onclick = () => dialogoModelos();

/* ---------------------------------------------------------------- cabeçalho */
function renderCabecalho() {
  const l = listaDe(E.lista);
  const sel = $("#agrupar"); sel.innerHTML = "";
  for (const [v, r] of [["status", "status"], ["prioridade", "prioridade"], ["cliente", "cliente"], ["prazo", "prazo"], ["responsavel", "responsável"]]) sel.append(el("option", { value: v, text: "Agrupar: " + r, selected: E.agrupar === v }));
  for (const c of (l ? l.campos : []).filter(c => c.tipo === "selecao" || c.tipo === "simnao" || c.tipo === "pessoa")) sel.append(el("option", { value: "campo:" + c.id, text: "Agrupar: " + c.nome, selected: E.agrupar === "campo:" + c.id }));
  if (![...sel.options].some(o => o.selected)) { E.agrupar = "status"; sel.value = "status"; }
  if (E.visaoFixa) {
    $("#cab-espaco").textContent = "";
    $("#cab-nome").textContent = ({ minhas: `Minhas tarefas — ${E.pessoa}`, hoje: "Hoje", atrasadas: "Atrasadas", concluidas: "Concluídas", historico: "Histórico — o que aconteceu" })[E.visaoFixa] || "";
    $("#visoes").style.visibility = "hidden"; $("#visoes-salvas").innerHTML = ""; $("#bt-salvar-visao").style.display = "none";
    $("#agrupar").style.display = "none"; $("#bt-colunas").style.display = "none"; $("#bt-config-lista").style.display = "none";
  } else {
    const e = l ? espacoDe(l.espaco) : null;
    $("#cab-espaco").textContent = e ? e.nome + " /" : "";
    $("#cab-nome").textContent = l ? l.nome : "Crie uma lista no menu da esquerda";
    $("#visoes").style.visibility = "visible"; $("#bt-salvar-visao").style.display = l ? "" : "none"; $("#bt-config-lista").style.display = l ? "" : "none";
    $("#agrupar").style.display = E.visao === "lista" ? "" : "none"; $("#bt-colunas").style.display = E.visao === "lista" ? "" : "none";
    const vs = $("#visoes-salvas"); vs.innerHTML = "";
    for (const v of (l ? l.visoes : [])) {
      const b = el("button", { class: v.id === E.visaoSalva ? "ativo" : "", text: v.nome, onclick: () => aplicarVisaoSalva(v) });
      b.addEventListener("contextmenu", ev => { ev.preventDefault(); menuVisaoSalva(ev, l, v); });
      vs.append(b);
    }
  }
  $$("#visoes button").forEach(b => b.classList.toggle("ativo", b.dataset.visao === E.visao && !E.visaoSalva));
  $("#mostrar-feitas").checked = E.mostrarFeitas;
}
$$("#visoes button").forEach(b => b.onclick = () => { E.visao = b.dataset.visao; E.visaoSalva = ""; localStorage.setItem("demandas.visao", E.visao); renderCabecalho(); renderVisao(); });
$("#cab-nome").onclick = async () => { const l = listaDe(E.lista); if (!l || E.visaoFixa) return; const n = prompt("Nome da lista:", l.nome); if (n) { await api("PATCH", `/api/listas/${l.id}`, { nome: n }); carregar(); } };
$("#filtro").oninput = e => { E.filtro = e.target.value.trim(); renderVisao(); };
$("#agrupar").onchange = e => { E.agrupar = e.target.value; renderVisao(); };
$("#mostrar-feitas").onchange = e => { E.mostrarFeitas = e.target.checked; renderVisao(); };
$("#bt-config-lista").onclick = ev => { const l = listaDe(E.lista); if (!l) return; menu(ev.clientX, ev.clientY, [
  { rotulo: "Campos personalizados…", acao: () => dialogoCampos(l) },
  { rotulo: "Automações…", acao: () => dialogoAutomacoes(l) },
  { rotulo: "Colunas do quadro (status)…", acao: () => aviso("No Quadro, use o ⋯ de cada coluna e o botão + Nova coluna.") },
  "sep",
  { rotulo: "Salvar esta lista como modelo…", acao: () => salvarComoModelo(l) },
  { rotulo: "Renomear lista", acao: () => $("#cab-nome").click() },
]); };
$("#bt-colunas").onclick = ev => {
  const l = listaDe(E.lista); if (!l) return;
  const todas = [...COLUNAS_BASE, ...l.campos.map(c => ["campo:" + c.id, c.nome])];
  menu(ev.clientX, ev.clientY, todas.map(([id, nome]) => ({ rotulo: (E.colunasOcultas.includes(id) ? "☐ " : "☑ ") + nome, acao: () => { E.colunasOcultas = E.colunasOcultas.includes(id) ? E.colunasOcultas.filter(x => x !== id) : [...E.colunasOcultas, id]; renderVisao(); } })));
};

/* ---- visões salvas */
function visaoAtual() { return { tipo: E.visao, agrupar: E.agrupar, filtro: E.filtro, ordenar: E.ordenar, mostrar_feitas: E.mostrarFeitas, colunas_ocultas: E.colunasOcultas }; }
function aplicarVisaoSalva(v) {
  E.visaoSalva = v.id; E.visao = v.tipo; E.agrupar = v.agrupar || "status"; E.filtro = v.filtro || ""; $("#filtro").value = E.filtro;
  E.ordenar = v.ordenar || null; E.mostrarFeitas = !!v.mostrar_feitas; E.colunasOcultas = v.colunas_ocultas || [];
  renderCabecalho(); renderVisao();
}
$("#bt-salvar-visao").onclick = async () => {
  const l = listaDe(E.lista); if (!l) return;
  const nome = prompt("Nome da visão (ex.: Atrasadas, Por responsável, Só Simples):"); if (!nome) return;
  const visoes = [...l.visoes, { nome, ...visaoAtual() }];
  const nova = await api("PATCH", `/api/listas/${l.id}`, { visoes });
  E.visaoSalva = nova.visoes[nova.visoes.length - 1].id; await carregar(); aviso(`Visão "${nome}" salva.`);
};
function menuVisaoSalva(ev, l, v) {
  menu(ev.clientX, ev.clientY, [
    { rotulo: "Atualizar com o que está na tela", acao: async () => { await api("PATCH", `/api/listas/${l.id}`, { visoes: l.visoes.map(x => x.id === v.id ? { ...x, ...visaoAtual() } : x) }); carregar(); aviso("Visão atualizada."); } },
    { rotulo: "Renomear", acao: async () => { const n = prompt("Nome:", v.nome); if (n) { await api("PATCH", `/api/listas/${l.id}`, { visoes: l.visoes.map(x => x.id === v.id ? { ...x, nome: n } : x) }); carregar(); } } },
    "sep",
    { rotulo: "Apagar visão", perigo: true, acao: async () => { await api("PATCH", `/api/listas/${l.id}`, { visoes: l.visoes.filter(x => x.id !== v.id) }); if (E.visaoSalva === v.id) E.visaoSalva = ""; carregar(); } },
  ]);
}

/* ---------------------------------------------------------------- lembretes */
function renderLembretes() {
  const caixa = $("#lembretes"); caixa.innerHTML = "";
  const ids = E.dados.lembretes || [];
  if (!ids.length) { caixa.classList.add("oculto"); return; }
  caixa.classList.remove("oculto");
  caixa.append(el("span", { text: "Lembretes:" }));
  for (const id of ids) {
    const t = tarefa(id); if (!t) continue;
    caixa.append(el("span", { class: "item", onclick: () => abrirPainel(t.id) }, [
      `${t.chave || ""} ${t.titulo}`, el("button", { class: "mini", text: "✓", title: "ok, visto", onclick: async ev => { ev.stopPropagation(); await api("PATCH", `/api/tarefas/${t.id}`, { lembrete: null }); carregar(); } })]));
  }
}

/* ---------------------------------------------------------------- a caixa única */
let timerPrevia = null;
$("#rapido").addEventListener("input", () => { clearTimeout(timerPrevia); timerPrevia = setTimeout(previa, 250); });
$("#rapido").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); gravarRapido(); } if (e.key === "Escape") { limparRapido(); } });
$("#bt-rapido").onclick = gravarRapido;
async function previa() {
  const texto = $("#rapido").value.trim();
  if (!texto) { E.previa = null; E.ajustes = E.ajustes.pai ? { pai: E.ajustes.pai } : {}; $("#fichas").innerHTML = ""; return; }
  try { E.previa = await api("POST", "/api/entender", { texto, lista: E.lista || undefined }); } catch (e) { return; }
  renderFichas();
}
function renderFichas() {
  const p = E.previa, aj = E.ajustes, caixa = $("#fichas"); caixa.innerHTML = "";
  if (!p) return;
  const ficha = (texto, classe, acao) => { const f = el("span", { class: "ficha " + classe, text: texto, onclick: ev => acao(ev) }); caixa.append(f); return f; };
  const cli = "cliente" in aj ? aj.cliente : (p.cliente ? p.cliente.codigo : "");
  const nomeCli = "cliente" in aj ? (aj.cliente_nome || aj.cliente) : (p.cliente ? `${p.cliente.codigo} ${p.cliente.nome.split(" ").slice(0, 2).join(" ")}` : "");
  if (cli) ficha(nomeCli + (p.candidatos.length && !("cliente" in aj) ? "  ?" : ""), p.candidatos.length && !("cliente" in aj) ? "duvida" : "boa", ev => menuCliente(ev));
  else if (!p.e_informacao && !("pessoal" in aj ? aj.pessoal : p.pessoal)) ficha("sem cliente — escolher", "falta", ev => menuCliente(ev));
  const tipo = "tipo" in aj ? aj.tipo : p.tipo;
  ficha(tipo ? (E.dados.tipos[tipo] || tipo) : "tipo: outro", "", ev => menu(ev.clientX, ev.clientY, [
    ...Object.entries(E.dados.tipos).sort((a, b) => a[1].localeCompare(b[1])).map(([k, n]) => ({ rotulo: n, acao: () => { aj.tipo = k; renderFichas(); } })),
    "sep", { rotulo: "Outro (sem tipo)", acao: () => { aj.tipo = ""; renderFichas(); } }]));
  const prazo = "prazo" in aj ? aj.prazo : p.prazo;
  ficha(prazo ? `vence ${fmtPrazo(prazo)}` : "sem prazo", prazo ? "" : "neutra", ev => menuPrazo(ev, v => { aj.prazo = v; renderFichas(); }));
  const prio = aj.prioridade || p.prioridade;
  ficha(`● ${PRIO_ROTULO[prio]}`, `prio-${prio}`, ev => menu(ev.clientX, ev.clientY, Object.keys(PRIO_ROTULO).map(k => ({ rotulo: PRIO_ROTULO[k], acao: () => { aj.prioridade = k; renderFichas(); } }))));
  const resps = "responsaveis" in aj ? aj.responsaveis : ((p.pessoas && p.pessoas.length) ? p.pessoas : (p.pessoa ? [p.pessoa] : (E.pessoa ? [E.pessoa] : [])));
  ficha(`para ${resps.length ? resps.join(", ") : "ninguém"}`, "neutra", ev => menu(ev.clientX, ev.clientY, [
    ...pessoasConhecidas().map(n => ({ rotulo: (resps.includes(n) ? "✓ " : "") + n, acao: () => { aj.responsaveis = resps.includes(n) ? resps.filter(x => x !== n) : [...resps, n]; renderFichas(); } })),
    "sep", { rotulo: "Sem responsável", acao: () => { aj.responsaveis = []; renderFichas(); } }]));
  const rec = "recorrencia" in aj ? aj.recorrencia : p.recorrencia;
  const menuRepetir = ev => menu(ev.clientX, ev.clientY, [
    { rotulo: "Não repete", acao: () => { aj.recorrencia = ""; renderFichas(); } },
    { rotulo: "Todo mês, dia…", acao: () => { const d = prompt("Dia do mês:", prazo ? String(Number(prazo.slice(8, 10))) : "1"); if (d) { aj.recorrencia = `mensal:${Number(d) || 1}:depois`; renderFichas(); } } },
    { rotulo: "Toda semana (mesmo dia do prazo)", acao: () => { const d = prazo ? DIAS_CHAVE[dataDe(prazo).getDay()] : "seg"; aj.recorrencia = `semanal:${d}`; renderFichas(); } },
    { rotulo: "A cada 15 dias", acao: () => { aj.recorrencia = "dias:15"; renderFichas(); } },
    { rotulo: "A cada N dias…", acao: () => { const n = prompt("A cada quantos dias?", "30"); if (n) { aj.recorrencia = `dias:${Number(n) || 30}`; renderFichas(); } } },
    { rotulo: "Todo ano", acao: () => { aj.recorrencia = "dias:365"; renderFichas(); } }]);
  if (rec) ficha(`repete: ${descreverRecorrencia(rec)}`, "", menuRepetir);
  else ficha("não repete", "neutra", menuRepetir);
  const avisar = "avisar" in aj ? aj.avisar : !!p.avisar;
  ficha(avisar ? ("🔔 avisar" + (p.hora ? " às " + p.hora : " no dia")) : "sem aviso", avisar ? "boa" : "neutra", () => { aj.avisar = !avisar; renderFichas(); });
  // coisa sua (vai para o seu espaço Pessoal, que só você vê) — o app adivinha; o clique corrige e ele aprende
  const pessoal = "pessoal" in aj ? aj.pessoal : !!p.pessoal;
  ficha(pessoal ? "pessoal (só você vê)" : "do departamento", pessoal ? "boa" : "neutra", () => { aj.pessoal = !pessoal; renderFichas(); }, p.pessoal_motivo || "Clique para trocar entre pessoal e do departamento");
  if (p.rodizio) ficha("rodízio: cada vez é de um da equipe", "", () => aviso("A ordem do rodízio você ajusta no painel da tarefa, em Repetir."));
  if (aj.pai && tarefa(aj.pai)) ficha(`subtarefa de: ${tarefa(aj.pai).titulo.slice(0, 30)}  ×`, "duvida", () => { delete aj.pai; $("#rapido").placeholder = "Escreva e aperte Enter: 101 carta de faturamento até sexta pra ana"; renderFichas(); });
  if (p.e_informacao && !aj.demanda) ficha("é informação, não demanda — clique se for demanda", "neutra", () => { aj.demanda = true; renderFichas(); });
  if (p.checklist && p.checklist.length) ficha(`checklist: ${p.checklist.length} passos`, "neutra", () => { });
  const ex = p.extraidos || {};
  const partesEx = [];
  if (ex.competencia) partesEx.push(`competência ${ex.competencia}`);
  if (ex.documento) partesEx.push(`doc. ${ex.documento}`);
  if (ex.valor !== undefined) partesEx.push("R$ " + Number(ex.valor).toLocaleString("pt-BR", { minimumFractionDigits: 2 }));
  if (partesEx.length) ficha(partesEx.join(" · "), "extra", () => aviso("Vão para os campos da lista com o mesmo nome (competencia, valor, documento) e ficam no painel."));
  if (p.outras && p.outras.length) ficha(`+${p.outras.length} tarefa(s): ${p.outras.map(o => o.titulo).join(" · ").slice(0, 60)}`, "mais", ev => menu(ev.clientX, ev.clientY,
    [...p.outras.map(o => ({ rotulo: `${o.titulo}${o.tipo_nome ? " · " + o.tipo_nome : ""}${o.prazo ? " · " + fmtPrazo(o.prazo) : ""}`, acao: () => { } })), "sep",
     { rotulo: "Essa linha é UMA demanda só", acao: () => { aj.uma = true; renderFichas(); } }]));
  if (p.duplicatas && p.duplicatas.length && !aj.ignorar_dup) {
    const d = p.duplicatas[0];
    ficha(`já existe: ${d.chave} “${d.titulo.slice(0, 28)}” — clique`, "dup", ev => menu(ev.clientX, ev.clientY, [
      { rotulo: `Abrir ${d.chave}`, acao: () => abrirPainel(d.id) },
      { rotulo: `Anexar este texto à ${d.chave} em vez de criar outra`, acao: async () => { const t = tarefa(d.id); await api("PATCH", `/api/tarefas/${d.id}`, { descricao: ((t.descricao || "") + `\n${fmtDataCurta(hojeISO())}: ${$("#rapido").value.trim()}`).trim() }); limparRapido(); await carregar(); abrirPainel(d.id); aviso(`Anexado em ${d.chave}.`); } },
      { rotulo: "É outra demanda — criar mesmo assim", acao: () => { aj.ignorar_dup = true; renderFichas(); } }]));
  }
  // modo compacto — o que o app tem certeza vira uma linha cinza; chip colorido só quando há dúvida
  const duvidas = $$(".ficha.falta, .ficha.duvida, .ficha.dup", caixa);
  if (!E.fichasAbertas && !duvidas.length) {
    const textos = $$(".ficha", caixa).map(f => f.textContent.trim()).filter(x => x && !/^(sem aviso|não repete|sem prazo|tipo: outro)$/.test(x));
    caixa.innerHTML = "";
    const linha = el("div", { class: "resumo-linha" });
    textos.forEach((x, i) => { if (i) linha.append(el("span", { text: "·" })); linha.append(el("span", { class: "ok", text: x })); });
    linha.append(el("span", { class: "editar", text: "ajustar", title: "Trocar cliente, tipo, prazo, pessoa…", onclick: () => { E.fichasAbertas = true; renderFichas(); } }));
    caixa.append(linha);
  }
  caixa.append(el("span", { class: "apagado", text: "  " + (p.motivo_prioridade || "") }));
}
function descreverRecorrencia(r) {
  if (!r) return "nunca";
  const [tipo, valor, regra] = r.split(":");
  if (tipo === "mensal") return `todo mês, dia ${valor}` + (regra === "depois" ? " (adia se não for útil)" : regra === "exato" ? " (no dia exato)" : " (antecipa se não for útil)");
  if (tipo === "semanal") return `toda ${({ seg: "segunda", ter: "terça", qua: "quarta", qui: "quinta", sex: "sexta", sab: "sábado", dom: "domingo" })[valor] || valor}`;
  if (tipo === "uteis") return `${valor} dia(s) útil(eis) depois`;
  if (tipo === "dias") return valor === "1" ? "todo dia" : valor === "7" ? "toda semana" : valor === "15" ? "a cada 15 dias" : valor === "365" ? "todo ano" : `a cada ${valor} dias`;
  if (tipo === "obrig") return `segue ${valor}` + (regra && regra !== "0" ? ` (+${regra} útil)` : "");
  return r;
}

/* ---------------------------------------------------------------- equipe e avisos */
/* ---- "lembrar a cada" é digitado, não escolhido: "20 min", "1:30h", "2 horas", "de 2 em 2 horas" */
function lerIntervalo(texto) {
  const t = (texto || "").toLowerCase().replace(/\s+/g, " ").trim();
  if (!t) return null;
  const m = t.match(/(?:a cada |de \d+ em )?(\d+)(?:[:h,.](\d{1,2}))?\s*(min|minutos?|m|h|hr|hrs|horas?)?\b/);
  if (!m) return null;
  const inteiro = Number(m[1]), fracao = m[2], unidade = m[3] || "";
  let min;
  if (unidade.startsWith("h") || (fracao && !unidade)) min = inteiro * 60 + (fracao ? (fracao.length === 2 ? Number(fracao) : Number(fracao) * 6) : 0);
  else min = inteiro;
  return (min >= 5 && min <= 12 * 60) ? min : null;
}
function descreverIntervalo(min) {
  if (!min) return "";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60), r = min % 60;
  return r ? `${h}h${String(r).padStart(2, "0")}` : `${h} h`;
}
function campoIntervalo(atual, definir) {
  const inp = el("input", { type: "text", value: descreverIntervalo(atual), placeholder: "ex.: 20 min, 1:30h, 2 horas (vazio = uma vez)", style: "width:230px",
    title: "No dia do lembrete o balão repete nessa cadência, das 07h às 20h. De 5 min a 12 h." });
  inp.addEventListener("change", () => {
    const v = inp.value.trim();
    if (!v) { definir(null); return; }
    const min = lerIntervalo(v);
    if (min === null) { aviso("não entendi o intervalo — escreva como '20 min', '1:30h' ou '2 horas' (de 5 min a 12 h)"); inp.value = descreverIntervalo(atual); return; }
    inp.value = descreverIntervalo(min); definir(min);
  });
  inp.addEventListener("keydown", ev => { if (ev.key === "Enter") { ev.preventDefault(); inp.blur(); } });
  return inp;
}

/* ---- vários responsáveis por tarefa (chips com + e ×), só gente da Equipe */
function equipeDe(listaId) {
  const dep = departamentoDaLista(listaId || E.lista) || (departamentosAcessiveis()[0] || {}).nome || "";
  const eq = ((E.dados.equipe || {})[dep] || []);
  return eq.length ? eq : pessoasConhecidas();
}
function controleResponsaveis(nomes, onChange, compacto) {
  const caixa = el("span", { class: "resp-chips" + (compacto ? " compacto" : "") });
  const atual = nomes.slice();
  for (const n of atual) caixa.append(el("span", { class: "chip", title: n }, [
    el("span", { text: compacto ? iniciais(n) : n }),
    el("button", { text: "×", title: `Tirar ${n}`, onclick: ev => { ev.stopPropagation(); onChange(atual.filter(x => x !== n)); } })]));
  caixa.append(el("button", { class: "add", text: atual.length ? "+" : "+ pessoa", title: "Atribuir a mais alguém da Equipe", onclick: ev => {
    ev.stopPropagation();
    const opcoes = equipeDe(E.lista).filter(n => !atual.includes(n));
    if (!opcoes.length) { aviso("todo mundo da Equipe já está nesta tarefa (Equipe ⋯ para cadastrar mais gente)"); return; }
    menu(ev.clientX, ev.clientY, [...opcoes.map(n => ({ rotulo: n, acao: () => onChange([...atual, n]) })), ...(atual.length ? ["sep", { rotulo: "Ninguém", acao: () => onChange([]) }] : [])]);
  } }));
  return caixa;
}

/* ---- criar a demanda à mão, com todos os campos */
function dialogoNovaDemanda(predefinidos = {}) {
  const listas = E.dados.listas.slice();
  if (!listas.length) { aviso("crie uma lista primeiro"); return; }
  const f = { titulo: "", lista: predefinidos.lista || E.lista || listas[0].id, cliente: "", cliente_nome: "", tipo: "", prazo: "", prioridade: "normal",
    responsaveis: E.pessoa ? [E.pessoa] : [], status: "", recorrencia: "", recDia: "", lembrete: "", lembrete_cada: "", etiquetas: "", descricao: "",
    checklist: "", campos: {}, pai: predefinidos.pai || "", depende: "", avisar: false, ...predefinidos };
  const corpo = el("div", { class: "form-grid" });
  const linha = (rotulo, controle) => { corpo.append(el("label", { text: rotulo }), controle); return controle; };
  const titulo = linha("Título", el("input", { type: "text", placeholder: "O que precisa ser feito", oninput: ev => f.titulo = ev.target.value }));
  const dinamicos = el("div", { style: "display:contents" });
  const montarPorLista = () => {
    dinamicos.innerHTML = "";
    const l = listaDe(f.lista);
    if (!l) return;
    if (!l.status.some(s => s.id === f.status)) f.status = l.status[0].id;
    dinamicos.append(el("label", { text: "Status" }), el("select", { onchange: ev => f.status = ev.target.value }, l.status.map(s => el("option", { value: s.id, text: s.nome, selected: s.id === f.status }))));
    for (const c of l.campos || []) {
      dinamicos.append(el("label", { text: c.nome }), controleCampo({ campos: f.campos }, c, v => { f.campos[c.id] = v; }));
    }
    const irmas = E.dados.tarefas.filter(t => t.lista === l.id && !feita(t));
    dinamicos.append(el("label", { text: "Subtarefa de" }), el("select", { onchange: ev => f.pai = ev.target.value },
      [el("option", { value: "", text: "— (tarefa principal)", selected: !f.pai }), ...irmas.map(t => el("option", { value: t.id, text: `${t.chave} ${t.titulo.slice(0, 50)}`, selected: t.id === f.pai }))]));
    dinamicos.append(el("label", { text: "Depende de" }), el("select", { onchange: ev => f.depende = ev.target.value },
      [el("option", { value: "", text: "— (pode começar já)", selected: !f.depende }), ...irmas.map(t => el("option", { value: t.id, text: `${t.chave} ${t.titulo.slice(0, 50)}`, selected: t.id === f.depende }))]));
  };
  linha("Lista", el("select", { onchange: ev => { f.lista = ev.target.value; montarPorLista(); } }, listas.map(x => el("option", { value: x.id, text: `${(espacoDe(x.espaco) || {}).nome || ""} / ${x.nome}`, selected: x.id === f.lista }))));
  // cliente com busca
  const cli = el("div", { style: "position:relative" });
  const cliInput = el("input", { type: "text", placeholder: "código ou nome do cliente", autocomplete: "off" });
  const sug = el("div", { class: "sugestoes oculto" });
  let timer = null;
  cliInput.addEventListener("input", () => { clearTimeout(timer); f.cliente = ""; timer = setTimeout(async () => {
    const q = cliInput.value.trim(); if (!q) { sug.classList.add("oculto"); return; }
    let r; try { r = await api("GET", `/api/clientes?q=${encodeURIComponent(q)}`); } catch (e) { return; }
    sug.innerHTML = ""; (r || []).slice(0, 8).forEach(c => sug.append(el("div", { text: `${c.codigo} — ${c.nome}`, onmousedown: () => { f.cliente = c.codigo; f.cliente_nome = c.nome; cliInput.value = `${c.codigo} ${c.nome}`; sug.classList.add("oculto"); } })));
    sug.classList.toggle("oculto", !(r || []).length);
  }, 250); });
  cliInput.addEventListener("blur", () => setTimeout(() => sug.classList.add("oculto"), 150));
  cli.append(cliInput, sug); linha("Cliente", cli);
  linha("Tipo", el("select", { onchange: ev => f.tipo = ev.target.value }, [el("option", { value: "", text: "outro" }), ...Object.entries(E.dados.tipos).sort((a, b) => a[1].localeCompare(b[1])).map(([k, n]) => el("option", { value: k, text: n, selected: k === f.tipo }))]));
  linha("Prazo", el("div", { class: "linha" }, [el("input", { type: "date", class: "curto", onchange: ev => f.prazo = ev.target.value }),
    el("select", { onchange: ev => f.prioridade = ev.target.value }, Object.keys(PRIO_ROTULO).map(k => el("option", { value: k, text: "prioridade " + PRIO_ROTULO[k], selected: k === f.prioridade })))]));
  const respCaixa = el("div");
  const montarResp = () => { respCaixa.innerHTML = ""; respCaixa.append(controleResponsaveis(f.responsaveis, nomes => { f.responsaveis = nomes; montarResp(); }, false)); };
  montarResp(); linha("Responsáveis", respCaixa);
  corpo.append(dinamicos); montarPorLista();
  const recDia = el("input", { type: "number", min: 1, max: 31, class: "curto", placeholder: "dia", oninput: ev => f.recDia = ev.target.value, style: "display:none" });
  const selRec = el("select", { onchange: ev => { f.recorrencia = ev.target.value; recDia.style.display = ev.target.value === "mensal" ? "" : "none"; } },
    [["", "não repete"], ["mensal", "todo mês, no dia…"], ["semanal", "toda semana (dia do prazo)"], ["dias:15", "a cada 15 dias"], ["dias:30", "a cada 30 dias"], ["dias:365", "todo ano"]].map(([v, r]) => el("option", { value: v, text: r })));
  linha("Repetir", el("div", { class: "linha" }, [selRec, recDia]));
  linha("Lembrar em", el("div", { class: "linha" }, [el("input", { type: "date", class: "curto", onchange: ev => f.lembrete = ev.target.value }),
    el("span", { class: "apagado", style: "flex:0 0 auto", text: "às" }), el("input", { type: "time", class: "curto", onchange: ev => f.lembrete_hora = ev.target.value }),
    el("span", { class: "apagado", style: "flex:0 0 auto", text: "a cada" }), campoIntervalo(null, min => f.lembrete_cada = min)]));
  linha("Pessoal", el("div", { class: "marcar" }, [el("label", {}, [el("input", { type: "checkbox", onchange: ev => f.pessoal = ev.target.checked }), "é coisa pessoal — vai para o espaço Pessoal de quem for fazer (só a pessoa vê)"])]));
  linha("Etiquetas", el("input", { type: "text", placeholder: "banco, licitação (separe por vírgula)", oninput: ev => f.etiquetas = ev.target.value }));
  linha("Checklist", el("textarea", { rows: 4, placeholder: "um item por linha", oninput: ev => f.checklist = ev.target.value }));
  linha("Descrição", el("textarea", { rows: 4, placeholder: "contexto, o que o cliente disse, links…", oninput: ev => f.descricao = ev.target.value }));
  const gravar = async () => {
    if (!f.titulo.trim()) { aviso("dê um título à demanda"); titulo.focus(); return; }
    // só vai o que foi preenchido: o que ficar em branco o entendedor decide pelo título
    const ajustes = { titulo: f.titulo.trim(), prioridade: f.prioridade, responsaveis: f.responsaveis, status: f.status, campos: f.campos,
      etiquetas: f.etiquetas.split(",").map(x => x.trim()).filter(Boolean), ligacoes: f.depende ? [{ tipo: "depende", alvo: f.depende }] : [], varias: false };
    if (f.cliente) ajustes.cliente = f.cliente;
    if (f.tipo) ajustes.tipo = f.tipo;
    if (f.prazo) ajustes.prazo = f.prazo;
    if (f.descricao.trim()) ajustes.descricao = f.descricao.trim();
    if (f.lembrete) ajustes.lembrete = f.lembrete;
    if (f.lembrete_cada) ajustes.lembrete_cada = Number(f.lembrete_cada);
    if (f.lembrete_hora) { ajustes.lembrete_hora = f.lembrete_hora; if (!f.lembrete) ajustes.lembrete = f.prazo || hojeISO(); }
    if (f.pessoal) ajustes.pessoal = true;
    const itens = f.checklist.split("\n").map(x => x.trim()).filter(Boolean);
    if (itens.length) ajustes.checklist = itens;
    if (f.recorrencia) ajustes.recorrencia = f.recorrencia === "mensal" ? `mensal:${Number(f.recDia) || 1}:depois` : (f.recorrencia === "semanal" ? `semanal:${f.prazo ? DIAS_CHAVE[dataDe(f.prazo).getDay()] : "seg"}` : f.recorrencia);
    if (f.pai) ajustes.pai = f.pai;
    try {
      const t = await api("POST", "/api/tarefas", { lista: f.lista, texto: f.titulo.trim(), ajustes });
      fecharDialogo(); await carregar();
      aviso(`${t.chave} criada em "${(listaDe(t.lista) || {}).nome || ""}"`);
      if (t.lista !== E.lista && !E.visaoFixa) escolherLista(t.lista);
      abrirPainel(t.id);
    } catch (e) { }
  };
  dialogo("Nova demanda", corpo, { esquerda: [el("span", { class: "apagado", text: "Só o título é obrigatório. O que você não preencher, o app decide pelo título (cliente, tipo, prazo padrão)." })],
    direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Criar demanda", onclick: gravar })] });
  setTimeout(() => titulo.focus(), 50);
}
$("#bt-nova-demanda").onclick = () => dialogoNovaDemanda();

/* ---- concluir num clique (com desfazer), menu de status, notificações, busca, lote, lixeira, configurações */
async function concluirTarefa(t) {
  const l = listaDe(t.lista); if (!l) return;
  const antes = t.status;
  const alvo = feita(t) ? (l.status.find(s => s.tipo === "aberto") || l.status[0]) : l.status.find(s => s.tipo === "feito");
  if (!alvo) { aviso("esta lista não tem um status de concluído"); return; }
  await api("PATCH", `/api/tarefas/${t.id}`, { status: alvo.id }); await carregar();
  aviso(feita(tarefa(t.id) || t) ? `${t.chave || ""} concluída` : `${t.chave || ""} reaberta`, { rotulo: "Desfazer", acao: async () => { await api("PATCH", `/api/tarefas/${t.id}`, { status: antes }); carregar(); } });
}
function menuStatus(ev, t) {
  const l = listaDe(t.lista); if (!l) return;
  menu(ev.clientX, ev.clientY, l.status.map(s => ({ rotulo: (s.id === t.status ? "✓ " : "") + s.nome, acao: () => mudarStatus(t, s) })));
}
/* muda o status com "Desfazer"; se a tarefa foi para "Aguardando cliente", oferece o lembrete de cobrar */
async function mudarStatus(t, s) {
  if (!s || s.id === t.status) return;
  const antes = t.status;
  await api("PATCH", `/api/tarefas/${t.id}`, { status: s.id }); await carregar();
  const desfazer = { rotulo: "Desfazer", acao: async () => { await api("PATCH", `/api/tarefas/${t.id}`, { status: antes }); carregar(); } };
  if (s.tipo === "aguardando") aviso(`${t.chave || ""} → ${s.nome} · lembrar de cobrar o cliente?`, [{ rotulo: "Em 2 dias úteis", acao: () => lembrarDeCobrar(t, { dias_uteis: 2 }) }, desfazer]);
  else aviso(`${t.chave || ""} → ${s.nome}`, desfazer);
}
async function lembrarDeCobrar(t, quando) {
  const r = await api("POST", `/api/tarefas/${t.id}/adiar`, { ...quando, motivo: "cobrar o cliente" }); await carregar();
  aviso(`${t.chave || ""}: lembrete de cobrar o cliente ${fmtPrazo(r.lembrete)}${r.lembrete_hora ? " às " + r.lembrete_hora : ""}`);
}
function menuCobrar(ev, t) {
  const hoje = new Date(); const mais = n => { const d = new Date(hoje); d.setDate(d.getDate() + n); return isoDe(d); };
  const sexta = mais(((5 - hoje.getDay() + 7) % 7) || 7);
  menu(ev.clientX, ev.clientY, [{ rotulo: "Amanhã", acao: () => lembrarDeCobrar(t, { dias_uteis: 1 }) }, { rotulo: "Em 2 dias úteis", acao: () => lembrarDeCobrar(t, { dias_uteis: 2 }) },
    { rotulo: `Sexta (${fmtPrazo(sexta)})`, acao: () => lembrarDeCobrar(t, { data: sexta }) }, { rotulo: "Em uma semana", acao: () => lembrarDeCobrar(t, { dias_uteis: 5 }) }]);
}

/* notificações pessoais: sino com contador; clique abre a tarefa e marca como lida */
async function carregarNotificacoes() {
  let r; try { r = await api("GET", "/api/notificacoes"); } catch (e) { return; }
  const novas = (r.notificacoes || []).filter(n => !n.lida && !E.notificacoes.some(x => x.id === n.id));
  E.notificacoes = r.notificacoes || []; E.naoLidas = r.nao_lidas || 0;
  const b = $("#notif-badge"); b.textContent = E.naoLidas > 99 ? "99+" : String(E.naoLidas); b.classList.toggle("oculto", !E.naoLidas);
  if (E.notificacoesCarregadas) for (const n of novas.slice(0, 3)) aviso(n.texto);
  E.notificacoesCarregadas = true;
  if (!$("#notif-pop").classList.contains("oculto")) renderNotificacoes();
}
setInterval(carregarNotificacoes, 30000);
function renderNotificacoes() {
  const pop = $("#notif-pop"); pop.innerHTML = "";
  pop.append(el("div", { class: "notif-cab" }, [el("span", { text: E.naoLidas ? `${E.naoLidas} não lida(s)` : "tudo lido" }),
    el("button", { class: "mini", text: "marcar todas como lidas", onclick: async () => { await api("POST", "/api/notificacoes/lidas", { ids: "todas" }); await carregarNotificacoes(); renderNotificacoes(); } })]));
  if (!E.notificacoes.length) pop.append(el("div", { class: "apagado", style: "padding:12px", text: "Nada ainda. Aqui chegam atribuições, comentários, menções, mudanças de status e prazo nas suas tarefas." }));
  const ROT = { atribuida: "atribuída a você", comentario: "comentário", mencao: "você foi mencionado", status: "status", prazo: "prazo", atrasou: "atrasou" };
  for (const n of E.notificacoes.slice(0, 60)) {
    pop.append(el("div", { class: "notif-item" + (n.lida ? "" : " nova"), onclick: async () => {
      if (!n.lida) { await api("POST", "/api/notificacoes/lidas", { ids: [n.id] }); carregarNotificacoes(); }
      pop.classList.add("oculto");
      if (tarefa(n.tarefa)) abrirPainel(n.tarefa); else aviso("essa tarefa não está mais aqui");
    } }, [el("span", { class: "ponto" }), el("div", {}, [el("div", { text: n.texto }), el("div", { class: "quando", text: `${ROT[n.tipo] || n.tipo} · ${fmtDataCurta(n.quando)} ${(n.quando || "").slice(11, 16)}${n.departamento && departamentosAcessiveis().length > 1 ? " · " + n.departamento : ""}` })])]));
  }
}
$("#bt-notif").onclick = ev => { ev.stopPropagation(); const pop = $("#notif-pop"); const abrir = pop.classList.contains("oculto"); $("#filtros-pop").classList.add("oculto"); pop.classList.toggle("oculto", !abrir); if (abrir) renderNotificacoes(); };
$("#bt-filtros").onclick = ev => { ev.stopPropagation(); $("#notif-pop").classList.add("oculto"); const pop = $("#filtros-pop"); pop.classList.toggle("oculto"); if (!pop.classList.contains("oculto")) $("#filtro").focus(); };

/* busca global (Ctrl+K): tarefas por ID, título, cliente; listas; setas e Enter */
function abrirBusca() {
  const caixa = $("#busca"), inp = $("#busca-input"), lista = $("#busca-lista");
  caixa.classList.remove("oculto"); inp.value = ""; lista.innerHTML = ""; inp.focus();
  let itens = [], ativo = 0;
  const desenhar = () => {
    lista.innerHTML = "";
    itens.forEach((it, i) => lista.append(el("div", { class: "busca-item" + (i === ativo ? " ativo" : ""), onclick: it.acao, onmouseenter: () => { ativo = i; desenhar(); } },
      [el("span", { class: "chave", text: it.chave }), el("span", { text: it.texto }), el("span", { class: "apagado", text: it.extra })])));
  };
  const procurar = () => {
    const q = inp.value.trim().toLowerCase(); itens = []; ativo = 0;
    if (!q) { desenhar(); return; }
    const partes = q.split(/\s+/);
    const bate = s => partes.every(p => s.includes(p));
    for (const l of E.dados.listas) if (bate(`${l.nome} ${(espacoDe(l.espaco) || {}).nome || ""}`.toLowerCase())) itens.push({ chave: "lista", texto: `${(espacoDe(l.espaco) || {}).nome || ""} / ${l.nome}`, extra: l.departamento || "", acao: () => { caixa.classList.add("oculto"); escolherLista(l.id); } });
    for (const t of E.dados.tarefas) {
      const alvo = `${t.chave} ${t.titulo} ${t.cliente} ${t.cliente_nome} ${donos(t).join(" ")} ${t.descricao || ""}`.toLowerCase();
      if (bate(alvo)) itens.push({ chave: t.chave || "", texto: t.titulo, extra: `${nomeCliente(t)}${feita(t) ? " · concluída" : ""}`, acao: () => { caixa.classList.add("oculto"); if (!E.visaoFixa && t.lista !== E.lista) escolherLista(t.lista); abrirPainel(t.id); } });
      if (itens.length >= 30) break;
    }
    desenhar();
  };
  inp.oninput = procurar;
  inp.onkeydown = ev => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); ativo = Math.min(ativo + 1, itens.length - 1); desenhar(); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); ativo = Math.max(ativo - 1, 0); desenhar(); }
    else if (ev.key === "Enter" && itens[ativo]) { ev.preventDefault(); itens[ativo].acao(); }
  };
  caixa.onclick = ev => { if (ev.target === caixa) caixa.classList.add("oculto"); };
}
$("#bt-busca").onclick = abrirBusca;

/* ações em lote: marque as linhas (a caixinha aparece ao passar o mouse) e a barra surge embaixo */
function renderLoteBarra() {
  const barra = $("#lote-barra"); barra.innerHTML = "";
  $$(".tabela").forEach(tb => tb.classList.toggle("selecionando", E.selecao.size > 0));
  if (!E.selecao.size) { barra.classList.add("oculto"); return; }
  barra.classList.remove("oculto");
  const ids = [...E.selecao];
  const primeira = tarefa(ids[0]); const l = primeira ? listaDe(primeira.lista) : null;
  const lote = async (campos, rotulo) => {
    const antes = ids.map(id => { const t = tarefa(id); return t ? { id, campos: Object.fromEntries(Object.keys(campos).map(k => [k, t[k]])) } : null; }).filter(Boolean);
    await api("PATCH", "/api/tarefas/lote", { ids, campos }); E.selecao.clear(); await carregar();
    aviso(`${ids.length} tarefa(s): ${rotulo}`, { rotulo: "Desfazer", acao: async () => { for (const a of antes) { try { await api("PATCH", `/api/tarefas/${a.id}`, a.campos); } catch (e) { } } carregar(); } });
  };
  barra.append(el("span", { text: `${ids.length} selecionada(s)` }));
  if (l) barra.append(el("button", { text: "Status ▾", onclick: ev => menu(ev.clientX, ev.clientY, l.status.map(s => ({ rotulo: s.nome, acao: () => lote({ status: s.id }, s.nome) }))) }));
  barra.append(el("button", { text: "Responsável ▾", onclick: ev => menu(ev.clientX, ev.clientY, [...equipeDe(E.lista).map(n => ({ rotulo: n, acao: () => lote({ responsaveis: [n] }, "para " + n) })), "sep", { rotulo: "Ninguém", acao: () => lote({ responsaveis: [] }, "sem responsável") }]) }));
  barra.append(el("button", { text: "Prioridade ▾", onclick: ev => menu(ev.clientX, ev.clientY, Object.keys(PRIO_ROTULO).map(p => ({ rotulo: PRIO_ROTULO[p], acao: () => lote({ prioridade: p }, PRIO_ROTULO[p]) }))) }));
  barra.append(el("button", { text: "Prazo ▾", onclick: ev => menuPrazo(ev, v => lote({ prazo: v }, v ? "prazo " + fmtPrazo(v) : "sem prazo")) }));
  if (l) barra.append(el("button", { text: "Mover para ▾", onclick: ev => menu(ev.clientX, ev.clientY, E.dados.listas.filter(x => x.departamento === l.departamento && x.id !== l.id).map(x => ({ rotulo: x.nome, acao: () => lote({ lista: x.id }, "→ " + x.nome) }))) }));
  barra.append(el("button", { class: "perigo", text: "Apagar", onclick: async () => {
    const apagadas = ids.map(id => tarefa(id)).filter(Boolean);
    for (const t of apagadas) { try { await api("DELETE", `/api/tarefas/${t.id}`); } catch (e) { } }
    E.selecao.clear(); await carregar();
    aviso(`${apagadas.length} tarefa(s) na lixeira`, { rotulo: "Desfazer", acao: async () => { for (const t of apagadas) { try { await api("POST", `/api/lixeira/${t.id}/restaurar`); } catch (e) { } } carregar(); } });
  } }));
  barra.append(el("button", { text: "×", title: "Limpar seleção (Esc)", onclick: () => { E.selecao.clear(); renderVisao(); renderLoteBarra(); } }));
}

/* lixeira: o que foi apagado, com restaurar */
async function dialogoLixeira() {
  let r; try { r = await api("GET", "/api/lixeira"); } catch (e) { return; }
  const corpo = el("div");
  corpo.append(el("p", { class: "dica", text: "O que foi apagado fica aqui, com a chave e a lista de onde saiu. Restaurar põe de volta na mesma lista (ou na primeira, se a lista não existe mais)." }));
  const itens = r.lixeira || [];
  if (!itens.length) corpo.append(el("div", { class: "sem-nada", text: "Lixeira vazia." }));
  const tab = el("table", { class: "dialogo-tabela" });
  tab.append(el("thead", {}, el("tr", {}, ["ID", "Tarefa", "Cliente", "Lista", "Apagada em", ""].map(x => el("th", { text: x })))));
  const tb = el("tbody");
  for (const x of itens) tb.append(el("tr", {}, [el("td", {}, el("span", { class: "chave", text: x.chave || "" })), el("td", { text: x.titulo }), el("td", { text: x.cliente || "" }), el("td", { text: x.lista || "" }),
    el("td", { class: "apagado", text: `${fmtDataCurta(x.apagada_em)} ${(x.apagada_em || "").slice(11, 16)}` }),
    el("td", {}, el("button", { class: "mini", text: "Restaurar", onclick: async () => { await api("POST", `/api/lixeira/${x.id}/restaurar`); fecharDialogo(); await carregar(); aviso(`${x.chave || ""} restaurada`); } }))]));
  tab.append(tb); corpo.append(tab);
  dialogo("Lixeira", corpo, { direita: [el("button", { text: "Fechar", onclick: fecharDialogo })] });
}

/* clientes: o cadastro (clientes.json) que a linha reconhece — código, nome e apelidos */
async function dialogoClientes() {
  let r; try { r = await api("GET", "/api/clientes"); } catch (e) { return; }
  const clientes = (r.clientes || []).map(c => ({ codigo: c.codigo, nome: c.nome, apelidos: (c.apelidos || []).join(", ") }));
  const corpo = el("div");
  corpo.append(el("p", { class: "dica", text: `Códigos e nomes que a linha reconhece ("101 balancete", "padaria pediu a CND"). Apelidos são outros jeitos de chamar o cliente, separados por vírgula. O arquivo é ${r.arquivo || "clientes.json"}; e-mails e telefones de remetentes vão no contatos.json ao lado dele.` }));
  const tab = el("table", { class: "dialogo-tabela" });
  tab.append(el("thead", {}, el("tr", {}, ["Código", "Nome", "Apelidos", ""].map(x => el("th", { text: x })))));
  const tb = el("tbody"); tab.append(tb);
  const desenhar = () => {
    tb.innerHTML = "";
    clientes.forEach((c, i) => tb.append(el("tr", {}, [
      el("td", {}, el("input", { type: "text", value: c.codigo, placeholder: "101", style: "width:80px", oninput: ev => c.codigo = ev.target.value })),
      el("td", {}, el("input", { type: "text", value: c.nome, placeholder: "razão social ou nome fantasia", oninput: ev => c.nome = ev.target.value })),
      el("td", {}, el("input", { type: "text", value: c.apelidos, placeholder: "apelido1, apelido2", oninput: ev => c.apelidos = ev.target.value })),
      el("td", {}, el("button", { class: "mini perigo", text: "×", onclick: () => { clientes.splice(i, 1); desenhar(); } })),
    ])));
    if (!clientes.length) tb.append(el("tr", {}, el("td", { colspan: 4, class: "sem-nada", text: "Nenhum cliente. Sem cadastro, a linha só reconhece cliente pelo que você ensinar nas fichas." })));
  };
  desenhar(); corpo.append(tab);
  dialogo("Clientes", corpo, {
    esquerda: [el("button", { text: "+ Cliente", onclick: () => { clientes.push({ codigo: "", nome: "", apelidos: "" }); desenhar(); setTimeout(() => { const ult = tb.querySelector("tr:last-child input"); if (ult) ult.focus(); }, 30); } })],
    direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Salvar", onclick: async () => {
      const lista = clientes.map(c => ({ codigo: c.codigo.trim(), nome: c.nome.trim(), apelidos: c.apelidos.split(",").map(x => x.trim()).filter(Boolean) }));
      try { await api("PUT", "/api/clientes", { clientes: lista }); fecharDialogo(); await carregar(); aviso("Clientes salvos."); } catch (e) { }
    } })],
  });
}

/* ⚙ no rodapé: tudo que é configuração, fora do caminho de quem só registra demanda */
$("#bt-config").onclick = ev => {
  const itens = [
    { rotulo: "Clientes (códigos, nomes e apelidos)", acao: dialogoClientes },
    { rotulo: "Equipe (quem recebe tarefa)", acao: () => $("#bt-equipe").click() },
    { rotulo: "Triagem (o que vai para onde)", acao: () => $("#bt-triagem").click() },
    { rotulo: "Modelos de lista", acao: () => $("#bt-modelos").click() },
    { rotulo: "Avisos e balões", acao: () => $("#bt-avisos").click() },
    { rotulo: "Lixeira", acao: dialogoLixeira },
  ];
  if (E.dados && E.dados.admin) itens.push("sep", { rotulo: "Departamentos (admin)", acao: dialogoDepartamentos });
  if (E.loginLigado) {
    if (E.dados && E.dados.admin) itens.push({ rotulo: "Usuários e senhas (admin)", acao: dialogoUsuarios });
    itens.push("sep", { rotulo: "Trocar a minha senha", acao: dialogoSenha }, { rotulo: `Sair (${E.pessoa})`, acao: sair });
  } else itens.push("sep", { rotulo: "Trocar o meu nome", acao: () => $("#bt-trocar-nome").click() });
  menu(ev.clientX - 200, ev.clientY - 36 * (itens.length + 1), itens);
};
$("#nav-caixa").onclick = () => {
  const c = caixaDeEntradaDe(departamentoDaLista(E.lista) || (departamentosAcessiveis()[0] || {}).nome);
  if (c) escolherLista(c.id); else aviso("este departamento ainda não tem Caixa de entrada (⚙ → Triagem)");
};
$("#titulo-acompanhar").onclick = () => {
  const nav = $("#nav-acompanhar"); nav.classList.toggle("oculto");
  $("#titulo-acompanhar .seta").textContent = nav.classList.contains("oculto") ? "▸" : "▾";
  localStorage.setItem("demandas.acompanhar", nav.classList.contains("oculto") ? "0" : "1");
};
if (localStorage.getItem("demandas.acompanhar") === "1") { $("#nav-acompanhar").classList.remove("oculto"); $("#titulo-acompanhar .seta").textContent = "▾"; }

/* ---- modelo A: login, usuários (admin) e senha própria */
function pedirLogin() {
  const m = $("#modal"); const caixa = $(".modal-caixa", m); caixa.innerHTML = "";
  caixa.append(el("h2", { text: "Entrar" }), el("p", { class: "apagado", text: "Login e senha do Gestor de Demandas. Quem não tem, pede ao administrador." }));
  const login = el("input", { type: "text", placeholder: "login", autocomplete: "username" });
  const senha = el("input", { type: "password", placeholder: "senha", autocomplete: "current-password" });
  const erro = el("p", { class: "apagado", style: "color:var(--vermelho);min-height:18px" });
  const entrar = async () => {
    erro.textContent = "";
    let r; try { r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ login: login.value.trim(), senha: senha.value }) }); } catch (e) { erro.textContent = "sem resposta do servidor"; return; }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { erro.textContent = j.erro || "não entrou"; senha.focus(); return; }
    E.loginLigado = true; E.usuario = j.usuario; E.pessoa = j.usuario.nome; localStorage.setItem("demandas.pessoa", E.pessoa);
    m.classList.add("oculto");
    if (E.dados) carregar(); else iniciar();
  };
  caixa.append(login, senha, erro, el("div", { class: "modal-botoes" }, [el("button", { class: "primario", text: "Entrar", onclick: entrar })]));
  senha.onkeydown = ev => { if (ev.key === "Enter") entrar(); };
  login.onkeydown = ev => { if (ev.key === "Enter") senha.focus(); };
  m.classList.remove("oculto"); login.focus();
}
async function sair() {
  try { await fetch("/api/sair", { method: "POST" }); } catch (e) { }
  E.usuario = null; location.reload();
}
function dialogoSenha() {
  const corpo = el("div", { class: "form-grid" });
  const atual = el("input", { type: "password", autocomplete: "current-password" }), nova = el("input", { type: "password", autocomplete: "new-password" }), de_novo = el("input", { type: "password", autocomplete: "new-password" });
  corpo.append(el("label", { text: "Senha atual" }), atual, el("label", { text: "Nova senha" }), nova, el("label", { text: "Repita" }), de_novo);
  dialogo("Trocar a minha senha", corpo, { direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Trocar", onclick: async () => {
    if (nova.value !== de_novo.value) { aviso("as duas senhas novas não batem"); return; }
    try { await api("POST", "/api/senha", { atual: atual.value, nova: nova.value }); fecharDialogo(); aviso("senha trocada"); } catch (e) { }
  } })] });
  setTimeout(() => atual.focus(), 50);
}
async function dialogoUsuarios() {
  let r; try { r = await api("GET", "/api/usuarios"); } catch (e) { return; }
  const usuarios = (r.usuarios || []).map(u => ({ ...u, senha: "" }));
  const deps = r.departamentos || [];
  const corpo = el("div");
  corpo.append(el("p", { class: "dica", text: "Membro vê os departamentos dele; gestor vê os dele e os que gere; admin vê tudo e cadastra. A senha só precisa ser preenchida para criar ou trocar (em branco mantém)." }));
  const tab = el("table", { class: "dialogo-tabela" });
  tab.append(el("thead", {}, el("tr", {}, ["Login", "Nome", "Papel", "Departamentos", "Gere (gestor)", "Senha", ""].map(x => el("th", { text: x })))));
  const tb = el("tbody"); tab.append(tb);
  const marcar = (u, chave) => el("div", { class: "marcar" }, deps.map(d => el("label", {}, [el("input", { type: "checkbox", checked: (u[chave] || []).includes(d), onchange: ev => { u[chave] = ev.target.checked ? [...(u[chave] || []), d] : (u[chave] || []).filter(x => x !== d); } }), d])));
  const desenhar = () => {
    tb.innerHTML = "";
    usuarios.forEach((u, i) => tb.append(el("tr", {}, [
      el("td", {}, el("input", { type: "text", value: u.login, placeholder: "login", oninput: ev => u.login = ev.target.value })),
      el("td", {}, el("input", { type: "text", value: u.nome, placeholder: "como está na Equipe", oninput: ev => u.nome = ev.target.value })),
      el("td", {}, el("select", { onchange: ev => u.papel = ev.target.value }, ["membro", "gestor", "admin"].map(p => el("option", { value: p, text: p, selected: p === u.papel })))),
      el("td", {}, marcar(u, "departamentos")), el("td", {}, marcar(u, "gere")),
      el("td", {}, el("input", { type: "password", placeholder: u.tem_senha ? "(mantém)" : "defina", autocomplete: "new-password", oninput: ev => u.senha = ev.target.value })),
      el("td", {}, el("button", { class: "mini perigo", text: "×", onclick: () => { usuarios.splice(i, 1); desenhar(); } })),
    ])));
  };
  desenhar(); corpo.append(tab);
  dialogo("Usuários (admin)", corpo, {
    esquerda: [el("button", { text: "+ Usuário", onclick: () => { usuarios.push({ login: "", nome: "", papel: "membro", departamentos: [], gere: [], senha: "" }); desenhar(); } })],
    direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Salvar", onclick: async () => {
      try { await api("PATCH", "/api/usuarios", { usuarios: usuarios.filter(u => u.login.trim()) }); fecharDialogo(); aviso("usuários salvos"); } catch (e) { }
    } })],
  });
}

function dialogoEquipe() {
  const deps = departamentosAcessiveis();
  const dep = departamentoDaLista(E.lista) || (deps[0] ? deps[0].nome : "");
  const nomes = ((E.dados.equipe || {})[dep] || []).slice();
  const corpo = el("div");
  corpo.append(el("p", { class: "dica", text: `Quem trabalha no ${dep || "departamento"}. É esta lista que a linha reconhece em "pra Ana", "atribuir à Carla", "@bruno", "Carla vai fazer". Um nome por linha.` }));
  const ta = el("textarea", { rows: 8, style: "width:100%" }); ta.value = nomes.join("\n"); corpo.append(ta);
  dialogo(`Equipe — ${dep}`, corpo, {
    direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Salvar", onclick: async () => {
      await api("PATCH", "/api/equipe", { departamento: dep, equipe: ta.value.split("\n").map(x => x.trim()).filter(Boolean) }); fecharDialogo(); carregar(); aviso("Equipe salva.");
    } })],
  });
}
$("#bt-equipe").onclick = dialogoEquipe;
let avisosDesde = "";
async function carregarAvisos(primeira = false) {
  let r; try { r = await api("GET", `/api/avisos?desde=${encodeURIComponent(avisosDesde)}`); } catch (e) { return; }
  const res = r.resumo || {};
  const faixa = $("#resumo-dia"); faixa.innerHTML = "";
  const partes = [];
  if ((res.atrasadas || []).length) partes.push([`${res.atrasadas.length} atrasada(s)`, res.atrasadas]);
  if ((res.hoje || []).length) partes.push([`${res.hoje.length} para hoje`, res.hoje]);
  if ((res.amanha || []).length) partes.push([`${res.amanha.length} para amanhã` + ((res.urgentes_amanha || []).length ? ` (${res.urgentes_amanha.length} urgente)` : ""), res.amanha]);
  if ((res.aguardando || []).length) partes.push([`${res.aguardando.length} aguardando há 5+ dias`, res.aguardando]);
  if (partes.length) {
    faixa.classList.remove("oculto");
    faixa.append(el("span", { text: `Seu dia, ${E.pessoa}:` }));
    for (const [rotulo, itens] of partes) faixa.append(el("span", { class: "item", text: rotulo, title: itens.map(t => `${t.chave} ${t.titulo}`).join("\n"), onclick: () => { E.visaoFixa = "minhas"; renderLateral(); renderCabecalho(); renderVisao(); } }));
    faixa.append(el("button", { class: "mini", text: "×", title: "esconder por agora", onclick: () => faixa.classList.add("oculto") }));
  } else faixa.classList.add("oculto");
  const novos = r.pendentes || [];
  for (const a of novos) {
    if (avisosDesde && a.quando > avisosDesde) {
      aviso(`${a.titulo}: ${a.texto}`);
      if ("Notification" in window && Notification.permission === "granted") { try { const n = new Notification(a.titulo, { body: a.texto }); n.onclick = () => { if (a.tarefa) abrirPainel(a.tarefa); window.focus(); }; } catch (e) { } }
    }
  }
  if (novos.length) avisosDesde = novos[novos.length - 1].quando; else if (!avisosDesde) avisosDesde = new Date().toISOString().slice(0, 19);
  if (primeira && "Notification" in window && Notification.permission === "default") { try { Notification.requestPermission(); } catch (e) { } }
  $("#avisos-lateral").textContent = (r.config && r.config.ligado) ? `resumo ${(r.config.horarios_resumo || []).join(" e ")} · amanhã às ${r.config.hora_amanha || "—"}` : "desligados";
}
setInterval(carregarAvisos, 30000);
function dialogoAvisos() {
  api("GET", "/api/avisos").then(r => {
    const c = r.config || {};
    const corpo = el("div");
    corpo.append(el("p", { class: "dica", text: "O servidor desta máquina avisa pelo balão do Windows mesmo com a página fechada — para quem usou a página por último aqui. A página mostra os mesmos avisos." }));
    const ligado = el("input", { type: "checkbox", checked: c.ligado !== false });
    const balao = el("input", { type: "checkbox", checked: c.balao !== false });
    const horarios = el("input", { type: "text", value: (c.horarios_resumo || []).join(", "), placeholder: "08:30, 13:30" });
    const amanha = el("input", { type: "text", value: c.hora_amanha || "", placeholder: "16:30" });
    corpo.append(el("div", { class: "linha-form" }, [
      el("label", { text: "Avisos ligados" }), ligado, el("label", { text: "Balão do Windows" }), balao,
      el("label", { text: "Resumo do dia às" }), horarios, el("label", { text: "Alerta de amanhã às" }), amanha,
      el("label", { text: "Quem recebe aqui" }), el("span", { text: c.pessoa || E.pessoa })]));
    dialogo("Avisos", corpo, {
      esquerda: [el("button", { text: "Testar o balão", onclick: () => api("POST", "/api/avisos/testar", {}).then(x => aviso(x.ok ? "Balão enviado — olhe o canto da tela." : "Não consegui mostrar o balão nesta máquina.")) })],
      direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Salvar", onclick: async () => {
        await api("PATCH", "/api/avisos/config", { ligado: ligado.checked, balao: balao.checked, horarios_resumo: horarios.value.split(/[,\s]+/).filter(Boolean), hora_amanha: amanha.value.trim() });
        fecharDialogo(); carregarAvisos(); aviso("Avisos salvos.");
      } })],
    });
  });
}
$("#bt-avisos").onclick = dialogoAvisos;
function menuCliente(ev) {
  const p = E.previa, aj = E.ajustes;
  const itens = [];
  const vistos = new Set();
  for (const c of [p.cliente, ...(p.candidatos || [])].filter(Boolean)) {
    if (vistos.has(c.codigo)) continue; vistos.add(c.codigo);
    itens.push({ rotulo: `${c.codigo} — ${c.nome.slice(0, 44)}`, acao: () => { aj.cliente = c.codigo; aj.cliente_nome = `${c.codigo} ${c.nome.split(" ").slice(0, 2).join(" ")}`; renderFichas(); } });
  }
  if (itens.length) itens.push("sep");
  itens.push({ rotulo: "Procurar pelo código ou nome…", acao: () => procurarCliente(c => { aj.cliente = c.codigo; aj.cliente_nome = `${c.codigo} ${c.nome.split(" ").slice(0, 2).join(" ")}`; renderFichas(); }) });
  itens.push({ rotulo: "Sem cliente", acao: () => { aj.cliente = ""; aj.cliente_nome = ""; renderFichas(); } });
  menu(ev.clientX, ev.clientY, itens);
}
async function procurarCliente(aoEscolher) {
  const q = prompt("Código ou parte do nome:"); if (!q) return;
  const achados = await api("GET", `/api/clientes?q=${encodeURIComponent(q)}`);
  if (!achados.length) { aviso("não achei cliente com isso"); return; }
  if (achados.length === 1) { aoEscolher(achados[0]); return; }
  menu(window.innerWidth / 2 - 100, 120, achados.map(c => ({ rotulo: `${c.codigo} — ${c.nome.slice(0, 44)}`, acao: () => aoEscolher(c) })));
}
function menuPrazo(ev, definir) {
  const hoje = dataDe(hojeISO());
  const mais = n => { const d = new Date(hoje); d.setDate(d.getDate() + n); return isoDe(d); };
  const sexta = mais((5 - hoje.getDay() + 7) % 7);
  menu(ev.clientX, ev.clientY, [
    { rotulo: "Hoje", acao: () => definir(hojeISO()) }, { rotulo: "Amanhã", acao: () => definir(mais(1)) },
    { rotulo: `Sexta (${fmtPrazo(sexta)})`, acao: () => definir(sexta) }, { rotulo: "Em uma semana", acao: () => definir(mais(7)) },
    { rotulo: "Outra data…", acao: () => { const t = prompt("Data (dd/mm ou dd/mm/aaaa):"); const d = lerData(t); if (d) definir(d); else if (t) aviso("não entendi a data"); } },
    "sep", { rotulo: "Sem prazo", acao: () => definir(null) }]);
}
function lerData(t) {
  if (!t) return null; const m = t.trim().match(/^(\d{1,2})[\/.-](\d{1,2})(?:[\/.-](\d{2,4}))?$/); if (!m) return null;
  let ano = m[3] ? Number(m[3]) : new Date().getFullYear(); if (ano < 100) ano += 2000;
  const d = new Date(ano, Number(m[2]) - 1, Number(m[1])); if (isNaN(d)) return null;
  if (!m[3] && d < dataDe(hojeISO())) d.setFullYear(ano + 1);
  return isoDe(d);
}
async function gravarRapido() {
  const texto = $("#rapido").value.trim(); if (!texto) return;
  const lista = E.lista || (E.dados.listas[0] && E.dados.listas[0].id);
  if (!lista) { aviso("crie uma lista primeiro"); return; }
  if (!E.previa) { try { E.previa = await api("POST", "/api/entender", { texto, lista }); } catch (e) { } }
  const p = E.previa, aj = { ...E.ajustes };
  // o que o app adivinhou e você não mexeu vai junto (pessoal, hora do lembrete)
  if (p && p.pessoal && !("pessoal" in aj)) aj.pessoal = true;
  if (p && p.hora && !("lembrete_hora" in aj)) aj.lembrete_hora = p.hora;
  if (p && p.e_informacao && !aj.demanda && (p.cliente || aj.cliente)) {
    const cod = aj.cliente || p.cliente.codigo;
    const esperando = E.dados.tarefas.find(t => t.cliente === cod && statusDe(t).tipo === "aguardando");
    if (esperando && confirm(`"${esperando.titulo}" estava aguardando desde ${fmtDataCurta(esperando.aguardando_desde)}.\n\nEssa informação destrava ela? (volta para "em andamento" e o texto vai para a descrição)`)) {
      const l = listaDe(esperando.lista); const aberto = l.status.find(s => s.tipo === "aberto" && s.id !== l.status[0].id) || l.status[0];
      await api("PATCH", `/api/tarefas/${esperando.id}`, { status: aberto.id, descricao: ((esperando.descricao || "") + `\n${fmtDataCurta(hojeISO())}: ${texto}`).trim() });
      limparRapido(); await carregar(); abrirPainel(esperando.id); aviso("Destravada."); return;
    }
  }
  if (p && p.duplicatas && p.duplicatas.length && !aj.ignorar_dup) {
    const d = p.duplicatas[0];
    if (!confirm(`${d.chave} “${d.titulo}” já está aberta para este cliente.\n\nCriar outra mesmo assim?\n(Cancelar = não criar; clique na ficha amarela para anexar o texto à ${d.chave})`)) return;
  }
  if (aj.uma) { aj.varias = false; }
  if (E.visaoFixa || !E.lista) aj.triar = true;  // fora de uma lista, as regras de triagem decidem
  limparRapido();
  try {
    const t = await api("POST", "/api/tarefas", { lista, texto: aj.uma ? texto.replace(/\n/g, " ") : texto, ajustes: aj });
    await carregar();
    const n = (t.criadas || []).length;
    aviso(n > 1 ? `${n} tarefas criadas: ${t.criadas.map(c => c.chave).join(", ")}` : `${t.chave} adicionada: ${t.titulo}`);
  } catch (e) {
    $("#rapido").value = texto; E.ajustes = aj; previa();
  }
}
function limparRapido() { $("#rapido").value = ""; $("#rapido-area").value = ""; E.previa = null; E.ajustes = {}; E.colada = null; E.fichasAbertas = false; $("#fichas").innerHTML = ""; $("#rapido").placeholder = "Escreva e aperte Enter: 101 carta de faturamento até sexta pra ana"; }

/* ---- colar a mensagem inteira */
function modoColar(ligar) {
  const r = $(".rapido"); r.classList.toggle("colando", ligar);
  $("#rapido-area").classList.toggle("oculto", !ligar);
  if (ligar) { $("#rapido-area").focus(); } else { $("#rapido").focus(); }
  if (!ligar) { E.colada = null; $("#fichas").innerHTML = ""; }
}
$("#bt-colar").onclick = () => modoColar(!$(".rapido").classList.contains("colando"));
$("#rapido").addEventListener("paste", ev => {
  const texto = (ev.clipboardData || window.clipboardData).getData("text") || "";
  if (texto.includes("\n") || texto.length > 160) {
    ev.preventDefault(); modoColar(true); $("#rapido-area").value = texto; previaColar();
  }
});
let timerColar = null;
$("#rapido-area").addEventListener("input", () => { clearTimeout(timerColar); timerColar = setTimeout(previaColar, 350); });
$("#rapido-area").addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); gravarColado(); } if (e.key === "Escape") { modoColar(false); } });
const STATUS_TIPO_ROTULO = { aberto: "A fazer", aguardando: "Aguardando cliente", feito: "Concluída" };
async function previaColar() {
  const texto = $("#rapido-area").value.trim();
  const caixa = $("#fichas"); caixa.innerHTML = "";
  if (!texto) { E.colada = null; return; }
  // lados corrigidos e Juntar/Separar sobrevivem à nova leitura; o resto o servidor decide de novo
  const antes = E.colada && E.colada.ajustes ? E.colada.ajustes : {};
  const corpo = { texto, lista: E.lista || undefined, lados: antes.lados || {} };
  if (typeof antes.juntar === "boolean") corpo.juntar = antes.juntar;
  let resp;
  try { resp = await api("POST", "/api/colar", corpo); } catch (e) { return; }
  if ($("#rapido-area").value.trim() !== texto) return;     // a pessoa continuou digitando
  resp.ajustes = { ...antes };
  resp.incluir = resp.pedidos.map(() => true);
  resp.pedidos.forEach(p => { p.checklist = (p.checklist || []).map(x => typeof x === "string" ? { texto: x, feito: false } : { ...x }); });
  E.colada = resp;
  renderColada();
}
function renderColada() {
  const c = E.colada, caixa = $("#fichas"); caixa.innerHTML = "";
  if (!c) return;
  const painel = el("div", { class: "colar-painel" });
  const releitura = () => previaColar();

  /* --- de onde veio e de quem é */
  const cab = el("div", { class: "colar-cab" });
  cab.append(el("span", { class: "apagado", text: ({ whatsapp: "WhatsApp", email: "E-mail", conversa: "Conversa", chat: "Chat de atendimento", texto: "Mensagem" })[c.formato] + (c.remetente ? " de " + c.remetente : "") + (c.quando ? " · " + c.quando : "") }));
  const cli = c.ajustes.cliente ? { codigo: c.ajustes.cliente, nome: c.ajustes.cliente_nome || "" } : c.cliente;
  const fichaCli = el("span", { class: "ficha " + (cli ? (c.candidatos && c.candidatos.length && !c.ajustes.cliente ? "duvida" : "boa") : "falta"),
    title: c.cliente_motivo || "",
    text: cli ? `${cli.codigo} ${(cli.nome || "").split(" ").slice(0, 2).join(" ")}` + (c.cliente_motivo && !c.ajustes.cliente ? ` (${c.cliente_motivo})` : "") : "cliente? — clique para escolher",
    onclick: ev => menu(ev.clientX, ev.clientY, [
      ...[c.cliente, ...(c.candidatos || [])].filter(Boolean).map(x => ({ rotulo: `${x.codigo} — ${x.nome.slice(0, 44)}`, acao: () => { c.ajustes.cliente = x.codigo; c.ajustes.cliente_nome = x.nome; renderColada(); } })),
      "sep", { rotulo: "Procurar pelo código ou nome…", acao: () => procurarCliente(x => { c.ajustes.cliente = x.codigo; c.ajustes.cliente_nome = x.nome; renderColada(); }) },
      { rotulo: "Sem cliente", acao: () => { c.ajustes.cliente = ""; c.ajustes.cliente_nome = ""; renderColada(); } }]) });
  cab.append(fichaCli);
  if (c.email) cab.append(el("span", { class: "apagado", text: c.email }));
  painel.append(cab);

  /* --- quem falou: cada nome é uma ficha que troca de lado */
  const turnos = c.turnos || [];
  if (turnos.length && !c.so_minha) {
    const falas = el("div", { class: "colar-falas" });
    falas.append(el("span", { class: "apagado", text: "Quem falou:" }));
    const vistos = new Set();
    turnos.forEach((t, i) => {
      const chave = t.nome ? t.nome : `#${i}`;
      if (t.nome && vistos.has(t.nome)) return;
      vistos.add(t.nome);
      const n = turnos.filter(x => (x.nome || `#${turnos.indexOf(x)}`) === chave).length;
      const rot = (t.nome || `fala ${i + 1}`) + " · " + (t.lado === "equipe" ? "equipe" : t.lado === "cliente" ? "cliente" : "?") + (n > 1 ? ` (${n})` : "");
      falas.append(el("span", { class: "ficha " + (t.lado === "equipe" ? "lado-equipe" : "lado-cliente"), text: rot,
        title: (t.lado_motivo ? `decidido ${t.lado_motivo}` : "") + "\n" + (t.texto || "").slice(0, 160),
        onclick: ev => menu(ev.clientX, ev.clientY, [
          { rotulo: "É o cliente", acao: () => { c.ajustes.lados = { ...(c.ajustes.lados || {}), [chave]: "cliente" }; releitura(); } },
          { rotulo: "É da equipe (você ou um colega)", acao: () => { c.ajustes.lados = { ...(c.ajustes.lados || {}), [chave]: "equipe" }; releitura(); } }]) }));
    });
    painel.append(falas);
  } else if (c.so_minha) {
    painel.append(el("div", { class: "apagado", style: "margin:4px 0 2px", text: "Só você falou: cada linha virou uma demanda, como na caixa de cima." }));
  }

  /* --- o que a conversa decidiu para todas */
  const geral = el("div", { class: "colar-geral" });
  const st = c.ajustes.status_tipo || c.status_tipo || "aberto";
  geral.append(el("span", { class: "ficha " + (st === "aguardando" ? "duvida" : st === "feito" ? "boa" : "neutra"),
    text: `status: ${STATUS_TIPO_ROTULO[st]}` + (c.status_motivo && !c.ajustes.status_tipo ? ` — ${c.status_motivo}` : ""),
    title: "Clique para trocar",
    onclick: ev => menu(ev.clientX, ev.clientY, Object.entries(STATUS_TIPO_ROTULO).map(([k, v]) => ({ rotulo: v, acao: () => { c.ajustes.status_tipo = k; c.pedidos.forEach(p => p.status_tipo = k); renderColada(); } }))) }));
  if (c.prazo_motivo && !c.so_minha) geral.append(el("span", { class: "apagado", text: `prazo: ${c.prazo_motivo}` }));
  if (c.pessoa_motivo) geral.append(el("span", { class: "apagado", text: `para ${c.pessoa}: ${c.pessoa_motivo}` }));
  if (c.prioridade_motivo) geral.append(el("span", { class: "apagado", text: `prioridade: ${c.prioridade_motivo}` }));
  if (c.recorrencia) geral.append(el("span", { class: "ficha", text: `repete: ${descreverRecorrencia(c.recorrencia)}` }));
  if (c.avisar) geral.append(el("span", { class: "ficha boa", text: "🔔 avisar no dia" }));
  const n = c.pedidos.length;
  if (c.pode_juntar) geral.append(el("button", { class: "mini destaque", text: `Juntar em 1 tarefa (${n} itens)`, onclick: () => { c.ajustes.juntar = true; releitura(); } }));
  if (c.pode_separar) geral.append(el("button", { class: "mini destaque", text: "Separar em uma tarefa por item", onclick: () => { c.ajustes.juntar = false; releitura(); } }));
  if (typeof c.ajustes.juntar === "boolean") geral.append(el("button", { class: "mini", text: "voltar ao automático", onclick: () => { delete c.ajustes.juntar; releitura(); } }));
  painel.append(geral);

  /* --- as tarefas, cada uma com o seu checklist editável */
  c.pedidos.forEach((p, i) => {
    const item = el("div", { class: "pedido-item" });
    const chk = el("input", { type: "checkbox", checked: c.incluir[i], title: "Desmarque o que não for tarefa", onchange: ev => { c.incluir[i] = ev.target.checked; item.classList.toggle("fora", !ev.target.checked); } });
    const corpo = el("div", { class: "corpo" });
    const titulo = el("div", { class: "titulo", contenteditable: "true", spellcheck: "false", text: p.titulo, title: "Clique para corrigir o título" });
    titulo.addEventListener("blur", () => { p.titulo = titulo.textContent.trim(); });
    titulo.addEventListener("keydown", ev => { if (ev.key === "Enter") { ev.preventDefault(); titulo.blur(); } });
    corpo.append(titulo);
    const fichas = el("div", { class: "fichas" });
    const f = (t, cls, acao, title) => fichas.append(el("span", { class: "ficha " + cls, text: t, title: title || "", onclick: acao ? (ev => acao(ev)) : null }));
    f(p.tipo_nome || "tipo: outro", "", ev => menu(ev.clientX, ev.clientY, [
      ...Object.entries(E.dados.tipos).sort((a, b) => a[1].localeCompare(b[1])).map(([k, nome]) => ({ rotulo: nome, acao: () => { p.tipo = k; p.tipo_nome = nome; renderColada(); } })),
      "sep", { rotulo: "Outro (sem tipo)", acao: () => { p.tipo = ""; p.tipo_nome = ""; renderColada(); } }]));
    f(p.prazo ? `vence ${fmtPrazo(p.prazo)}` : "sem prazo", p.prazo ? "" : "neutra", ev => menuPrazo(ev, v => { p.prazo = v; p.prazo_motivo = "você escolheu"; renderColada(); }), p.prazo_motivo || "");
    f(`● ${PRIO_ROTULO[p.prioridade] || "Normal"}`, `prio-${p.prioridade || "normal"}`, ev => menu(ev.clientX, ev.clientY, Object.keys(PRIO_ROTULO).map(k => ({ rotulo: PRIO_ROTULO[k], acao: () => { p.prioridade = k; p.prioridade_escolhida = k; renderColada(); } }))), p.motivo_prioridade || "");
    const resp = "pessoa" in p && p.pessoa !== undefined ? p.pessoa : "";
    f(`para ${resp || E.pessoa || "você"}`, "neutra", ev => menu(ev.clientX, ev.clientY, [
      ...pessoasConhecidas().map(nome => ({ rotulo: nome, acao: () => { p.pessoa = nome; p.pessoa_motivo = "você escolheu"; renderColada(); } })),
      "sep", { rotulo: "Sem responsável", acao: () => { p.pessoa = ""; renderColada(); } }]), p.pessoa_motivo || "");
    if (p.duplicatas && p.duplicatas.length) f(`já existe ${p.duplicatas[0].chave}`, "dup", null, p.duplicatas[0].titulo);
    corpo.append(fichas);
    // checklist: o que a conversa destrinchou; cada item diz de onde veio
    const lista = el("ul", { class: "colar-checklist" });
    p.checklist.forEach((it, j) => {
      const li = el("li", { class: it.feito ? "feito" : "", title: it.motivo || (it.origem === "catalogo" ? "roteiro padrão do tipo" : "") });
      li.append(el("input", { type: "checkbox", checked: !!it.feito, onchange: ev => { it.feito = ev.target.checked; li.classList.toggle("feito", it.feito); } }));
      const tx = el("span", { class: "texto " + (it.origem || ""), contenteditable: "true", spellcheck: "false", text: it.texto });
      tx.addEventListener("blur", () => { it.texto = tx.textContent.trim(); if (!it.texto) { p.checklist.splice(j, 1); renderColada(); } });
      tx.addEventListener("keydown", ev => { if (ev.key === "Enter") { ev.preventDefault(); tx.blur(); } });
      li.append(tx);
      if (it.origem && it.origem !== "catalogo") li.append(el("span", { class: "origem", text: ({ cliente: "do cliente", equipe: "seu", pergunta: "pergunta", anexo: "anexo" })[it.origem] || it.origem }));
      li.append(el("button", { class: "mini", text: "×", title: "Tirar este item", onclick: () => { p.checklist.splice(j, 1); renderColada(); } }));
      lista.append(li);
    });
    const novo = el("input", { type: "text", class: "novo-item", placeholder: "+ item do checklist (Enter)" });
    novo.addEventListener("keydown", ev => { if (ev.key === "Enter" && novo.value.trim()) { ev.preventDefault(); p.checklist.push({ texto: novo.value.trim(), feito: false, origem: "equipe" }); renderColada(); } });
    lista.append(el("li", { class: "novo" }, [novo]));
    corpo.append(lista);
    item.append(chk, corpo); painel.append(item);
  });
  if (!c.pedidos.length) painel.append(el("div", { class: "apagado", text: "Não achei pedido nenhum nessa conversa. Escreva o pedido numa linha abaixo do texto colado, ou corrija quem é o cliente nas fichas acima." }));
  painel.append(el("div", { style: "display:flex;gap:8px;justify-content:flex-end;margin-top:8px;align-items:center" }, [
    el("span", { class: "apagado", text: "A conversa inteira vai para a descrição da tarefa." }),
    el("button", { text: "Cancelar", onclick: () => modoColar(false) }),
    el("button", { class: "primario", text: `Criar ${c.incluir.filter(Boolean).length} tarefa(s)`, onclick: gravarColado })]));
  caixa.append(painel);
}
async function gravarColado() {
  const c = E.colada; if (!c) return;
  const texto = $("#rapido-area").value.trim();
  const lista = E.lista || (E.dados.listas[0] && E.dados.listas[0].id);
  const pedidos = c.pedidos.filter((p, i) => c.incluir[i]).map(p => ({
    titulo: p.titulo, texto: p.texto, checklist: p.checklist.map(x => ({ texto: x.texto, feito: !!x.feito })),
    status_tipo: c.ajustes.status_tipo || p.status_tipo || "aberto", prazo: p.prazo || null, responsavel: p.pessoa || "",
    prioridade: p.prioridade_conversa || "", prioridade_escolhida: p.prioridade_escolhida || "", tipo: p.tipo || "",
    recorrencia: p.recorrencia || "", avisar: !!p.avisar, extraidos: p.extraidos || {},
    cliente: c.so_minha && p.cliente ? p.cliente.codigo : "" }));
  if (!pedidos.length) { aviso("marque pelo menos um pedido"); return; }
  const ajustes = { pedidos, triar: true, lados: c.ajustes.lados || {} };
  if (typeof c.ajustes.juntar === "boolean") ajustes.juntar = c.ajustes.juntar;
  if ("cliente" in c.ajustes) ajustes.cliente = c.ajustes.cliente;
  try {
    const t = await api("POST", "/api/tarefas", { lista, texto, modo: "colar", ajustes });
    modoColar(false); limparRapido(); await carregar();
    const l = listaDe(t.lista);
    aviso(`${t.criadas.length} tarefa(s) criada(s) em "${l ? l.nome : ""}": ${t.criadas.map(x => x.chave).join(", ")}`);
    if (l && l.id !== E.lista && !E.visaoFixa) escolherLista(l.id);
  } catch (e) { }
}

/* ---------------------------------------------------------------- visões */
async function renderVisao() {
  const v = $("#visao"); v.innerHTML = "";
  if (!E.dados) return;
  if (E.visaoFixa) return renderMinhas(v);
  if (!E.lista) { v.append(el("div", { class: "sem-nada", text: "Crie uma lista no menu da esquerda para começar." })); return; }
  if (E.visao === "quadro") return renderQuadro(v);
  if (E.visao === "calendario") return renderCalendario(v);
  return renderLista(v);
}
function tarefasDaLista() { return E.dados.tarefas.filter(t => t.lista === E.lista && bateFiltro(t)); }

/* ---- quadro */
function renderQuadro(v) {
  const l = listaDe(E.lista); const quadro = el("div", { class: "quadro" });
  const todas = tarefasDaLista();
  for (const s of l.status) {
    const col = el("div", { class: "coluna", "data-status": s.id });
    const itens = todas.filter(t => t.status === s.id && !t.pai).sort((a, b) => a.ordem - b.ordem);
    const cab = el("div", { class: "coluna-cab" }, [
      el("span", { class: "bolinha", style: `background:${s.cor}` }), el("span", { text: s.nome }),
      el("span", { class: "conta", text: itens.length }),
      el("button", { class: "mini", text: "⋯", onclick: ev => { ev.stopPropagation(); menuStatus(ev, l, s); } })]);
    col.append(cab);
    const corpo = el("div", { class: "coluna-corpo" });
    for (const t of itens) corpo.append(cartao(t, l));
    col.append(corpo);
    ligarSoltar(col, corpo, { status: s.id });
    quadro.append(col);
  }
  quadro.append(el("div", { class: "coluna-nova" }, el("button", { text: "+ Nova coluna", onclick: () => novoStatus(l) })));
  v.append(quadro);
}
function cartao(t, l) {
  const c = el("div", { class: "cartao", draggable: true, "data-id": t.id, onclick: () => abrirPainel(t.id) });
  c.append(el("div", { class: "titulo" + (feita(t) ? " feita" : "") }, [chaveTag(t), t.titulo]));
  const l2 = el("div", { class: "linha2" }, [prioTag(t)]);
  if (t.cliente) l2.append(el("span", { class: "cliente-tag", text: nomeCliente(t) }));
  if (t.tipo && E.dados.tipos[t.tipo] && E.dados.tipos[t.tipo].toLowerCase() !== t.titulo.toLowerCase()) l2.append(el("span", { class: "sub", text: E.dados.tipos[t.tipo] }));
  c.append(l2);
  for (const campo of (l.campos || []).filter(x => x.no_cartao)) {
    const valor = fmtCampo(campo, (t.campos || {})[campo.id]);
    if (valor) c.append(el("div", { class: "campo-cartao" }, [campo.nome + ": ", el("b", { text: valor })]));
  }
  const filhas = filhasDe(t.id); const partes = [];
  if (t.prazo) partes.push(el("span", { class: "prazo " + classePrazo(t), text: fmtPrazo(t.prazo) }));
  if (progresso(t)) partes.push(el("span", { class: "progresso", text: "☑ " + progresso(t) }));
  if (filhas.length) partes.push(el("span", { class: "sub", text: `${filhas.filter(f => feita(f)).length}/${filhas.length} subtarefas` }));
  if (statusDe(t).tipo === "aguardando" && t.aguardando_desde) partes.push(el("span", { class: "sub", text: `há ${-diasAte(t.aguardando_desde)}d` }));
  const bloq = bloqueiosDe(t);
  if (bloq.length) partes.push(el("span", { class: "bloqueada", text: `🔒 depende de ${bloq[0].chave || bloq[0].titulo.slice(0, 18)}` }));
  else if (t.liberada_em && !feita(t)) partes.push(el("span", { class: "liberada", text: "pode começar" }));
  if (t.recorrencia) partes.push(el("span", { class: "sub", text: "↻" , title: descreverRecorrencia(t.recorrencia) }));
  c.append(el("div", { class: "linha3" }, [el("div", { style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap" }, partes), pessoaTag(t)]));
  c.addEventListener("dragstart", ev => { E.arrastando = t.id; c.classList.add("arrastando"); ev.dataTransfer.setData("text/plain", t.id); ev.dataTransfer.effectAllowed = "move"; });
  c.addEventListener("dragend", () => { c.classList.remove("arrastando"); E.arrastando = ""; $$(".antes,.depois").forEach(x => x.classList.remove("antes", "depois")); });
  c.addEventListener("contextmenu", ev => { ev.preventDefault(); menuTarefa(ev, t); });
  return c;
}
function ligarSoltar(zona, corpo, destino) {
  let alvo = null, pos = "";
  zona.addEventListener("dragover", ev => {
    if (!E.arrastando) return; ev.preventDefault(); ev.dataTransfer.dropEffect = "move"; zona.classList.add("sobre");
    $$(".antes,.depois", corpo).forEach(x => x.classList.remove("antes", "depois"));
    const cartoes = $$("[data-id]", corpo).filter(c => c.dataset.id && c.dataset.id !== E.arrastando);
    alvo = null; pos = "";
    for (const c of cartoes) { const r = c.getBoundingClientRect(); if (ev.clientY < r.top + r.height / 2) { alvo = c; pos = "antes"; break; } alvo = c; pos = "depois"; }
    if (alvo) alvo.classList.add(pos);
  });
  zona.addEventListener("dragleave", ev => { if (!zona.contains(ev.relatedTarget)) zona.classList.remove("sobre"); });
  zona.addEventListener("drop", async ev => {
    ev.preventDefault(); zona.classList.remove("sobre");
    const id = E.arrastando || ev.dataTransfer.getData("text/plain"); if (!id) return;
    const corpoReq = {};
    if (destino.status) corpoReq.status = destino.status;
    if (alvo) corpoReq[pos === "antes" ? "antes_de" : "depois_de"] = alvo.dataset.id;
    if (destino.patch) { await api("PATCH", `/api/tarefas/${id}`, destino.patch); }
    if (destino.status !== undefined || alvo) await api("POST", `/api/tarefas/${id}/mover`, corpoReq);
    await carregar();
  });
}
function menuStatus(ev, l, s) {
  const i = l.status.findIndex(x => x.id === s.id);
  const salvar = async (novos) => { await api("PATCH", `/api/listas/${l.id}`, { status: novos }); carregar(); };
  menu(ev.clientX, ev.clientY, [
    { rotulo: "Renomear coluna", acao: () => { const n = prompt("Nome:", s.nome); if (n) { salvar(l.status.map(x => x.id === s.id ? { ...x, nome: n } : x)); } } },
    { rotulo: "Trocar cor", acao: () => { const cores = ["#B4B2A9", "#378ADD", "#EF9F27", "#639922", "#7F77DD", "#D85A30", "#D4537E", "#2F5D8A"]; const k = (cores.indexOf(s.cor) + 1) % cores.length; salvar(l.status.map(x => x.id === s.id ? { ...x, cor: cores[k] } : x)); } },
    { rotulo: `Tipo: ${s.tipo} → trocar`, acao: () => { const ordem = ["aberto", "aguardando", "feito"]; const k = (ordem.indexOf(s.tipo) + 1) % 3; salvar(l.status.map(x => x.id === s.id ? { ...x, tipo: ordem[k] } : x)); } },
    { rotulo: "Mover para a esquerda", acao: () => { if (i > 0) { const n = l.status.slice(); [n[i - 1], n[i]] = [n[i], n[i - 1]]; salvar(n); } } },
    { rotulo: "Mover para a direita", acao: () => { if (i < l.status.length - 1) { const n = l.status.slice(); [n[i + 1], n[i]] = [n[i], n[i + 1]]; salvar(n); } } },
    "sep",
    { rotulo: "Apagar coluna (tarefas vão para a primeira)", perigo: true, acao: () => { if (l.status.length > 1 && confirm(`Apagar a coluna "${s.nome}"?`)) salvar(l.status.filter(x => x.id !== s.id)); } },
  ]);
}
async function novoStatus(l) {
  const nome = prompt("Nome da coluna:"); if (!nome) return;
  const novos = l.status.slice(); const feito = novos.findIndex(s => s.tipo === "feito");
  const nova = { nome, cor: "#7F77DD", tipo: "aberto" };
  if (feito >= 0) novos.splice(feito, 0, nova); else novos.push(nova);
  await api("PATCH", `/api/listas/${l.id}`, { status: novos }); carregar();
}

/* ---- lista */
function gruposDe(tarefas, l) {
  const g = [];
  const chave = E.agrupar;
  if (chave === "status") for (const s of l.status) g.push({ chave: s.id, rotulo: s.nome, cor: s.cor, tipo: s.tipo, itens: tarefas.filter(t => t.status === s.id), mover: { status: s.id } });
  else if (chave === "prioridade") for (const p of Object.keys(PRIO_ROTULO)) g.push({ chave: p, rotulo: PRIO_ROTULO[p], cor: PRIO_COR[p], itens: tarefas.filter(t => t.prioridade === p), patch: { prioridade: p } });
  else if (chave === "prazo") {
    const f = (fn, rotulo, chave2) => g.push({ chave: chave2, rotulo, cor: "#2F5D8A", itens: tarefas.filter(fn) });
    f(t => diasAte(t.prazo) !== null && diasAte(t.prazo) < 0 && !feita(t), "Atrasadas", "atrasadas"); f(t => diasAte(t.prazo) === 0, "Hoje", "hoje");
    f(t => diasAte(t.prazo) > 0 && diasAte(t.prazo) <= 6, "Esta semana", "semana"); f(t => diasAte(t.prazo) > 6, "Depois", "depois");
    f(t => t.prazo === null || (diasAte(t.prazo) < 0 && feita(t)), "Sem prazo", "sem");
  } else if (chave === "cliente") {
    const nomes = [...new Set(tarefas.map(t => t.cliente ? nomeCliente(t) : ""))].sort((a, b) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
    for (const n of nomes) g.push({ chave: n || "sem", rotulo: n || "Sem cliente", cor: "#2F5D8A", itens: tarefas.filter(t => (t.cliente ? nomeCliente(t) : "") === n) });
  } else if (chave === "responsavel") {
    // uma tarefa de duas pessoas aparece nos dois grupos; arrastar para um grupo troca para essa pessoa
    const nomes = [...new Set(tarefas.flatMap(t => donos(t).length ? donos(t) : [""]))].sort((a, b) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
    for (const n of nomes) g.push({ chave: n || "sem", rotulo: n || "Sem responsável", cor: "#9DB8D4", itens: tarefas.filter(t => n ? donos(t).includes(n) : !donos(t).length), patch: { responsaveis: n ? [n] : [] } });
  } else if (chave.startsWith("campo:")) {
    const campo = (l.campos || []).find(c => c.id === chave.slice(6));
    if (campo) {
      const valorDe = t => { const v = (t.campos || {})[campo.id]; return campo.tipo === "simnao" ? (v ? "sim" : "não") : (v === undefined || v === "" ? "" : String(v)); };
      const valores = campo.tipo === "selecao" ? [...campo.opcoes, ""] : campo.tipo === "simnao" ? ["sim", "não"] : [...new Set(tarefas.map(valorDe))].sort();
      for (const val of [...new Set(valores)]) {
        const itens = tarefas.filter(t => valorDe(t) === val);
        if (!itens.length && val === "") continue;
        g.push({ chave: val || "sem", rotulo: val || `Sem ${campo.nome}`, cor: "#7F77DD", itens, patch: campo.tipo === "selecao" ? { campos: { [campo.id]: val } } : campo.tipo === "simnao" ? { campos: { [campo.id]: val === "sim" } } : undefined });
      }
    }
  }
  return g;
}
function ordenarItens(itens) {
  const o = E.ordenar;
  if (!o) return itens.sort((a, b) => a.ordem - b.ordem);
  const val = t => o.campo.startsWith("campo:") ? String((t.campos || {})[o.campo.slice(6)] ?? "") : ({ titulo: t.titulo.toLowerCase(), chave: Number((t.chave || "-0").split("-")[1]), cliente: nomeCliente(t), prazo: t.prazo || "9999", prioridade: Object.keys(PRIO_ROTULO).indexOf(t.prioridade), responsavel: t.responsavel || "~", status: statusDe(t).nome })[o.campo];
  return itens.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * (o.asc ? 1 : -1));
}
function renderLista(v) {
  const l = listaDe(E.lista);
  const todas = tarefasDaLista().filter(t => !t.pai);
  const grupos = gruposDe(todas, l);
  if (!todas.length) { v.append(el("div", { class: "sem-nada", text: E.filtro ? "Nada bate com o filtro." : "Lista vazia. Escreva a primeira tarefa na caixa de cima." })); return; }
  const visivel = id => !E.colunasOcultas.includes(id);
  for (const g of grupos) {
    if (!g.itens.length && E.agrupar !== "status") continue;
    const recolhido = E.recolhidos["g:" + E.lista + g.chave] ?? (g.tipo === "feito" && !E.mostrarFeitas);
    const bloco = el("div", { class: "grupo" + (recolhido ? " recolhido" : "") });
    const cab = el("div", { class: "grupo-cab", onclick: () => { E.recolhidos["g:" + E.lista + g.chave] = !recolhido; renderVisao(); } }, [
      el("span", { class: "bolinha", style: `background:${g.cor}` }), el("span", { text: g.rotulo }), el("span", { class: "conta", text: g.itens.length }), el("span", { class: "seta", text: recolhido ? "▸" : "▾" })]);
    bloco.append(cab);
    const tab = el("table", { class: "tabela" });
    const th = (campo, rotulo, w) => el("th", { style: w ? `width:${w}` : "", text: rotulo + (E.ordenar && E.ordenar.campo === campo ? (E.ordenar.asc ? " ↑" : " ↓") : ""), onclick: () => { E.ordenar = E.ordenar && E.ordenar.campo === campo ? (E.ordenar.asc ? { campo, asc: false } : null) : { campo, asc: true }; renderVisao(); } });
    const cabecalhos = [el("th", { style: "width:22px" }), th("chave", "ID", "72px"), th("titulo", "Tarefa")];
    if (visivel("status")) cabecalhos.push(th("status", "Status", "150px"));
    if (visivel("cliente")) cabecalhos.push(th("cliente", "Cliente", "180px"));
    if (visivel("prazo")) cabecalhos.push(th("prazo", "Prazo", "130px"));
    if (visivel("prioridade")) cabecalhos.push(th("prioridade", "Prioridade", "110px"));
    if (visivel("responsavel")) cabecalhos.push(th("responsavel", "Responsável", "130px"));
    for (const c of l.campos || []) if (visivel("campo:" + c.id)) cabecalhos.push(th("campo:" + c.id, c.nome, c.tipo === "simnao" ? "70px" : "140px"));
    if (visivel("feito")) cabecalhos.push(el("th", { text: "Feito", style: "width:60px" }));
    tab.append(el("thead", {}, el("tr", {}, cabecalhos)));
    const tb = el("tbody");
    for (const t of ordenarItens(g.itens.slice())) { tb.append(linhaTabela(t, l, false, visivel)); for (const f of filhasDe(t.id)) if (bateFiltro(f)) tb.append(linhaTabela(f, l, true, visivel)); }
    tab.append(tb); bloco.append(tab);
    ligarSoltar(bloco, tb, { status: g.mover ? g.mover.status : undefined, patch: g.patch });
    v.append(bloco);
  }
}
function controleCampo(t, c, aoMudar) {
  const v = (t.campos || {})[c.id];
  if (c.tipo === "selecao") return el("select", { onchange: ev => aoMudar(ev.target.value) }, [el("option", { value: "", text: "—", selected: !v }), ...c.opcoes.map(o => el("option", { value: o, text: o, selected: o === v }))]);
  if (c.tipo === "simnao") return el("input", { type: "checkbox", checked: !!v, onchange: ev => aoMudar(ev.target.checked) });
  if (c.tipo === "pessoa") return el("select", { onchange: ev => aoMudar(ev.target.value) }, [el("option", { value: "", text: "—", selected: !v }), ...pessoasConhecidas(v).map(n => el("option", { value: n, text: n, selected: n === v }))]);
  if (c.tipo === "data") return el("input", { type: "date", value: v || "", onchange: ev => aoMudar(ev.target.value || "") });
  if (c.tipo === "numero" || c.tipo === "dinheiro") return el("input", { type: "number", step: c.tipo === "dinheiro" ? "0.01" : "any", value: v ?? "", onchange: ev => aoMudar(ev.target.value === "" ? "" : Number(ev.target.value)) });
  return el("input", { type: "text", value: v || "", onchange: ev => aoMudar(ev.target.value) });
}
function linhaTabela(t, l, sub, visivel = () => true) {
  const tr = el("tr", { class: "linha" + (sub ? " sub" : "") + (E.selecao.has(t.id) ? " marcada" : ""), draggable: !sub, "data-id": sub ? "" : t.id });
  const st = statusDe(t);
  const patch = async campos => { await api("PATCH", `/api/tarefas/${t.id}`, campos); carregar(); };
  // status como chip colorido com menu (não mais um seletor por linha)
  const chipStatus = el("span", { class: "status-chip", text: st.nome, style: `background:${st.cor}22;color:${st.cor}`, title: "Trocar o status", onclick: ev => menuStatus(ev, t) });
  const pontoPrio = el("span", { class: "prio-ponto", style: `background:${PRIO_COR[t.prioridade] || "#B4B2A9"}`, title: `Prioridade ${PRIO_ROTULO[t.prioridade] || ""} — clique para trocar`,
    onclick: ev => menu(ev.clientX, ev.clientY, Object.keys(PRIO_ROTULO).map(p => ({ rotulo: (p === t.prioridade ? "✓ " : "") + PRIO_ROTULO[p], acao: () => patch({ prioridade: p }) }))) });
  const chipPrazo = el("span", { class: "prazo-chip " + (t.prazo ? classePrazo(t) : "vazio"), text: t.prazo ? fmtPrazo(t.prazo) : "—", title: t.prazo ? `Prazo ${fmtDataCurta(t.prazo)}/${t.prazo.slice(0, 4)} — clique para mudar` : "Dar um prazo",
    onclick: ev => menuPrazo(ev, v => patch({ prazo: v })) });
  const selResp = controleResponsaveis(donos(t), nomes => patch({ responsaveis: nomes }), true);
  const bloq = bloqueiosDe(t);
  const prog = progresso(t);
  const marcar = el("td", { class: "marcar" }, el("input", { type: "checkbox", checked: E.selecao.has(t.id), title: "Selecionar para ação em lote", onclick: ev => ev.stopPropagation(),
    onchange: ev => { if (ev.target.checked) E.selecao.add(t.id); else E.selecao.delete(t.id); tr.classList.toggle("marcada", ev.target.checked); renderLoteBarra(); } }));
  const bolinha = el("span", { class: "concluir" + (feita(t) ? " feita" : ""), title: feita(t) ? "Reabrir" : "Concluir", onclick: ev => { ev.stopPropagation(); concluirTarefa(t); } });
  const celTitulo = el("td", {}, [bolinha, pontoPrio, el("span", { class: "t-titulo" + (feita(t) ? " feita" : ""), text: (sub ? "↳ " : "") + t.titulo, onclick: () => abrirPainel(t.id) }),
    t.tipo && E.dados.tipos[t.tipo] && E.dados.tipos[t.tipo].toLowerCase() !== t.titulo.toLowerCase() ? el("span", { class: "apagado", text: "  " + E.dados.tipos[t.tipo] }) : null,
    prog ? el("span", { class: "t-progresso", text: prog, title: "checklist" }) : null,
    (t.comentarios || []).length ? el("span", { class: "t-progresso", text: `💬${t.comentarios.length}`, title: "comentários" }) : null,
    (t.anexos || []).length ? el("span", { class: "t-progresso", text: `📎${t.anexos.length}`, title: "anexos" }) : null,
    bloq.length ? el("span", { class: "bloqueada", text: `  🔒 ${bloq[0].chave || ""}` }) : (t.liberada_em && !feita(t) ? el("span", { class: "liberada", text: " pode começar" }) : null),
    t.recorrencia ? el("span", { class: "apagado", text: " ↻", title: descreverRecorrencia(t.recorrencia) }) : null]);
  tr.append(marcar, el("td", {}, chaveTag(t)), celTitulo);
  if (visivel("status")) tr.append(el("td", {}, chipStatus));
  if (visivel("cliente")) tr.append(el("td", {}, t.cliente ? el("span", { class: "cliente-tag", text: nomeCliente(t) }) : ""));
  if (visivel("prazo")) tr.append(el("td", {}, chipPrazo));
  if (visivel("prioridade")) tr.append(el("td", {}, el("span", { class: "apagado", text: PRIO_ROTULO[t.prioridade] || "" })));
  if (visivel("responsavel")) tr.append(el("td", {}, selResp));
  for (const c of l.campos || []) if (visivel("campo:" + c.id)) tr.append(el("td", {}, controleCampo(t, c, valor => patch({ campos: { [c.id]: valor } }))));
  if (visivel("feito")) tr.append(el("td", { class: "progresso", text: progresso(t) }));
  if (!sub) {
    tr.addEventListener("dragstart", ev => { E.arrastando = t.id; ev.dataTransfer.setData("text/plain", t.id); });
    tr.addEventListener("dragend", () => { E.arrastando = ""; $$(".antes,.depois").forEach(x => x.classList.remove("antes", "depois")); });
  }
  tr.addEventListener("contextmenu", ev => { ev.preventDefault(); menuTarefa(ev, t); });
  return tr;
}

/* ---- calendário */
async function renderCalendario(v) {
  const { ano, mes } = E.mes;
  try { E.cal = await api("GET", `/api/calendario?ano=${ano}&mes=${mes}`); } catch (e) { E.cal = { feriados: {}, obrigacoes: [] }; }
  const topo = el("div", { class: "cal-topo" }, [
    el("button", { text: "‹", onclick: () => { E.mes = mes === 1 ? { ano: ano - 1, mes: 12 } : { ano, mes: mes - 1 }; renderVisao(); } }),
    el("h2", { text: `${MESES[mes - 1]} ${ano}` }),
    el("button", { text: "›", onclick: () => { E.mes = mes === 12 ? { ano: ano + 1, mes: 1 } : { ano, mes: mes + 1 }; renderVisao(); } }),
    el("button", { text: "Hoje", onclick: () => { const h = new Date(); E.mes = { ano: h.getFullYear(), mes: h.getMonth() + 1 }; renderVisao(); } }),
    el("span", { class: "apagado", text: "Arraste a tarefa para outro dia para mudar o prazo." })]);
  v.append(topo);
  const grade = el("div", { class: "cal" });
  for (const d of ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]) grade.append(el("div", { class: "cal-dia-nome", text: d }));
  const primeiro = new Date(ano, mes - 1, 1); const inicio = new Date(primeiro); inicio.setDate(1 - ((primeiro.getDay() + 6) % 7));
  const tarefas = tarefasDaLista().filter(t => t.prazo && (E.mostrarFeitas || !feita(t)));
  for (let i = 0; i < 42; i++) {
    const dia = new Date(inicio); dia.setDate(inicio.getDate() + i); const iso = isoDe(dia);
    const fora = dia.getMonth() !== mes - 1;
    if (i >= 35 && fora && dia.getDay() === 1) break;
    const cel = el("div", { class: "cal-dia" + (fora ? " fora" : "") + (iso === hojeISO() ? " hoje" : "") });
    const num = el("div", { class: "num" }, [el("span", { text: dia.getDate() })]);
    if (E.cal.feriados && E.cal.feriados[iso]) num.append(el("span", { class: "feriado", text: E.cal.feriados[iso] }));
    cel.append(num);
    for (const o of (E.cal.obrigacoes || []).filter(o => o.data === iso)) cel.append(el("div", { class: "cal-obrig", text: o.nome, title: "obrigação do calendário" }));
    for (const t of tarefas.filter(t => t.prazo === iso).sort((a, b) => a.ordem - b.ordem)) {
      const it = el("div", { class: `cal-item prio-${t.prioridade}` + (feita(t) ? " feita" : ""), draggable: true, "data-id": t.id, text: `${t.chave || ""} ${t.cliente ? t.cliente + " · " : ""}${t.titulo}`, title: t.titulo, onclick: () => abrirPainel(t.id) });
      it.addEventListener("dragstart", ev => { E.arrastando = t.id; ev.dataTransfer.setData("text/plain", t.id); });
      it.addEventListener("dragend", () => { E.arrastando = ""; });
      cel.append(it);
    }
    cel.addEventListener("dragover", ev => { if (E.arrastando) { ev.preventDefault(); cel.classList.add("sobre"); } });
    cel.addEventListener("dragleave", () => cel.classList.remove("sobre"));
    cel.addEventListener("drop", async ev => { ev.preventDefault(); cel.classList.remove("sobre"); const id = E.arrastando; if (!id) return; await api("PATCH", `/api/tarefas/${id}`, { prazo: iso }); carregar(); });
    grade.append(cel);
  }
  v.append(grade);
}

/* ---- minhas tarefas / hoje */
/* ---- Atrasadas, Concluídas e Histórico (o que vai sendo guardado) */
function filtroPessoa(v, chave, onChange) {
  const sel = el("select", { onchange: ev => { E[chave] = ev.target.value; onChange(); } },
    [el("option", { value: "", text: "todo mundo", selected: !E[chave] }), ...pessoasConhecidas().map(n => el("option", { value: n, text: n, selected: E[chave] === n }))]);
  return sel;
}
function renderAtrasadas(v) {
  const filtros = el("div", { class: "hist-filtros" }, [el("span", { class: "apagado", text: "Responsável:" }), filtroPessoa(v, "pessoaAtrasadas", renderVisao)]);
  v.append(filtros);
  const itens = E.dados.tarefas.filter(t => bateFiltro(t) && !feita(t) && t.prazo && diasAte(t.prazo) < 0 && statusDe(t).tipo !== "aguardando"
    && (!E.pessoaAtrasadas || donos(t).includes(E.pessoaAtrasadas))).sort((a, b) => (a.prazo || "").localeCompare(b.prazo || ""));
  if (!itens.length) { v.append(el("div", { class: "sem-nada", text: "Nada atrasado." })); return; }
  const porPessoa = {};
  for (const t of itens) for (const n of (donos(t).length ? donos(t) : ["(sem responsável)"])) porPessoa[n] = (porPessoa[n] || 0) + 1;
  filtros.append(el("span", { class: "apagado", text: Object.entries(porPessoa).map(([n, q]) => `${n}: ${q}`).join(" · ") }));
  const bloco = el("div", { class: "grupo" }); const tab = el("table", { class: "tabela" }); const tb = el("tbody");
  for (const t of itens) {
    const l = listaDe(t.lista); const tr = linhaTabela(t, l, false, id => !id.startsWith("campo:"));
    const dias = -diasAte(t.prazo);
    tr.insertBefore(el("td", { class: "apagado", style: "width:200px" }, [el("span", { class: "atraso-dias", text: `${dias} dia(s) atrasada` }), el("span", { text: ` · ${l ? l.nome : ""}` + (t.atrasou_em ? ` · desde ${fmtPrazo(t.atrasou_em)}` : "") })]), tr.children[3]);
    tb.append(tr);
  }
  tab.append(tb); bloco.append(tab); v.append(bloco);
}
function renderConcluidas(v) {
  const filtros = el("div", { class: "hist-filtros" }, [el("span", { class: "apagado", text: "Responsável:" }), filtroPessoa(v, "pessoaConcluidas", renderVisao)]);
  v.append(filtros);
  const itens = E.dados.tarefas.filter(t => bateFiltro(t) && feita(t) && (!E.pessoaConcluidas || donos(t).includes(E.pessoaConcluidas)))
    .sort((a, b) => (b.concluida_em || "").localeCompare(a.concluida_em || ""));
  if (!itens.length) { v.append(el("div", { class: "sem-nada", text: "Nenhuma concluída ainda." })); return; }
  const meses = {};
  for (const t of itens) { const m = (t.concluida_em || "").slice(0, 7) || "sem data"; (meses[m] = meses[m] || []).push(t); }
  for (const [m, lista] of Object.entries(meses)) {
    const noPrazo = lista.filter(t => !t.prazo || (t.concluida_em || "").slice(0, 10) <= t.prazo).length;
    const rot = m === "sem data" ? m : `${m.slice(5, 7)}/${m.slice(0, 4)}`;
    v.append(el("div", { class: "secao-titulo", text: `${rot} — ${lista.length} concluída(s), ${noPrazo} no prazo` }));
    const bloco = el("div", { class: "grupo" }); const tab = el("table", { class: "tabela" }); const tb = el("tbody");
    for (const t of lista) {
      const l = listaDe(t.lista); const tr = linhaTabela(t, l, false, id => !id.startsWith("campo:"));
      const atrasada = t.prazo && (t.concluida_em || "").slice(0, 10) > t.prazo;
      tr.insertBefore(el("td", { class: "apagado", style: "width:220px", text: `concluída ${fmtPrazo((t.concluida_em || "").slice(0, 10))}` + (atrasada ? ` (prazo era ${fmtPrazo(t.prazo)})` : "") + ` · ${l ? l.nome : ""}` }), tr.children[3]);
      tb.append(tr);
    }
    tab.append(tb); bloco.append(tab); v.append(bloco);
  }
}
const HIST_ROTULO = { criada: "criada", status: "status", concluida: "concluída", reaberta: "reaberta", prazo: "prazo", responsaveis: "responsáveis", lista: "lista", prioridade: "prioridade", cliente: "cliente", tipo: "tipo", titulo: "título", atrasou: "atrasou", apagada: "apagada", comentario: "comentário", lembrete: "lembrete" };
async function renderHistorico(v) {
  const filtros = el("div", { class: "hist-filtros" }, [el("span", { class: "apagado", text: "Pessoa:" }), filtroPessoa(v, "pessoaHistorico", renderVisao),
    el("span", { class: "apagado", text: "Desde:" }), el("input", { type: "date", value: E.desdeHistorico || "", onchange: ev => { E.desdeHistorico = ev.target.value; renderVisao(); } })]);
  v.append(filtros);
  let r; try { r = await api("GET", `/api/eventos?pessoa=${encodeURIComponent(E.pessoaHistorico || "")}&desde=${encodeURIComponent(E.desdeHistorico || "")}&limite=400`); } catch (e) { return; }
  const evs = r.eventos || [];
  if (!evs.length) { v.append(el("div", { class: "sem-nada", text: "Nada registrado ainda. Cada criação, mudança de status, prazo, responsável e atraso vai aparecer aqui." })); return; }
  const lista = el("div", { class: "hist-lista" });
  const fmt = x => Array.isArray(x) ? x.join(", ") : (x === null || x === undefined || x === "" ? "—" : String(x));
  for (const ev of evs) {
    let texto;
    if (ev.tipo === "criada") texto = "criada" + (ev.para && ev.para.length ? ` para ${fmt(ev.para)}` : "") + (ev.texto ? ` (${ev.texto})` : "");
    else if (["concluida", "reaberta", "apagada"].includes(ev.tipo)) texto = HIST_ROTULO[ev.tipo] + (ev.texto ? ` — ${ev.texto}` : "");
    else if (ev.tipo === "lembrete") texto = `lembrete para ${fmt(ev.para)}` + (ev.texto ? ` — ${ev.texto}` : "");
    else if (ev.tipo === "atrasou") texto = `atrasou (prazo era ${fmt(ev.de)})`;
    else if (ev.tipo === "comentario") texto = ev.texto;
    else texto = `${HIST_ROTULO[ev.tipo] || ev.tipo}: ${fmt(ev.de)} → ${fmt(ev.para)}`;
    const varios = departamentosAcessiveis().length > 1;
    lista.append(el("div", { class: "hist-item " + ev.tipo }, [
      el("span", { class: "quando", text: `${fmtDataCurta(ev.quando)} ${(ev.quando || "").slice(11, 16)}` }),
      el("span", { class: "chave", text: ev.chave || "", onclick: () => { if (E.dados.tarefas.some(t => t.id === ev.tarefa)) abrirPainel(ev.tarefa); } }),
      el("span", { class: "texto", text: `${(ev.titulo || "").slice(0, 60)} · ${texto}` + (ev.pessoa ? ` · ${ev.pessoa}` : "") + (varios && ev.departamento ? ` · ${ev.departamento}` : "") })]));
  }
  v.append(lista);
}
function renderMinhas(v) {
  if (E.visaoFixa === "atrasadas") return renderAtrasadas(v);
  if (E.visaoFixa === "concluidas") return renderConcluidas(v);
  if (E.visaoFixa === "historico") return renderHistorico(v);
  const minhas = E.visaoFixa === "minhas";
  const base = E.dados.tarefas.filter(t => bateFiltro(t) && (minhas ? minha(t) : true));
  const abertas = base.filter(t => !feita(t));
  const secoes = [
    ["Atrasadas", abertas.filter(t => diasAte(t.prazo) !== null && diasAte(t.prazo) < 0 && statusDe(t).tipo !== "aguardando")],
    ["Hoje", abertas.filter(t => diasAte(t.prazo) === 0 && statusDe(t).tipo !== "aguardando")],
    ["Esta semana", abertas.filter(t => diasAte(t.prazo) > 0 && diasAte(t.prazo) <= 6 && statusDe(t).tipo !== "aguardando")],
    ["Aguardando resposta", abertas.filter(t => statusDe(t).tipo === "aguardando").sort((a, b) => (a.aguardando_desde || "") < (b.aguardando_desde || "") ? -1 : 1)],
  ];
  if (minhas) secoes.push(["Depois", abertas.filter(t => diasAte(t.prazo) > 6 && statusDe(t).tipo !== "aguardando")], ["Sem prazo", abertas.filter(t => !t.prazo && statusDe(t).tipo !== "aguardando")]);
  secoes.push(["Concluídas hoje", base.filter(t => feita(t) && (t.concluida_em || "").slice(0, 10) === hojeISO())]);
  let algo = false;
  for (const [rotulo, itens] of secoes) {
    if (!itens.length) continue; algo = true;
    v.append(el("div", { class: "secao-titulo", text: `${rotulo} (${itens.length})` }));
    const bloco = el("div", { class: "grupo" }); const tab = el("table", { class: "tabela" }); const tb = el("tbody");
    for (const t of itens.sort((a, b) => (a.prazo || "9999").localeCompare(b.prazo || "9999"))) {
      const l = listaDe(t.lista); const tr = linhaTabela(t, l, false, id => !id.startsWith("campo:"));
      const varios = departamentosAcessiveis().length > 1;
      tr.insertBefore(el("td", { class: "apagado", style: "width:160px", text: (l ? l.nome : "") + (varios && t.departamento ? ` · ${t.departamento}` : "") }), tr.children[3]);
      tb.append(tr);
    }
    tab.append(tb); bloco.append(tab); v.append(bloco);
  }
  if (!algo) v.append(el("div", { class: "sem-nada", text: minhas ? "Nada seu em aberto. Bom sinal." : "Nada para hoje." }));
}

/* ---------------------------------------------------------------- menu da tarefa */
function menuTarefa(ev, t) {
  const l = listaDe(t.lista);
  menu(ev.clientX, ev.clientY, [
    { rotulo: `Abrir ${t.chave || ""}`, acao: () => abrirPainel(t.id) },
    { rotulo: feita(t) ? "Reabrir" : "Concluir ✓", acao: () => concluirTarefa(t) },
    { rotulo: "Comentar…", acao: () => { E.abaPainel = "comentarios"; abrirPainel(t.id); } },
    ...l.status.filter(s => s.id !== t.status).map(s => ({ rotulo: `→ ${s.nome}`, acao: () => mudarStatus(t, s) })),
    { rotulo: "Lembrar de cobrar o cliente ▸", acao: () => menuCobrar(ev, t) },
    "sep",
    { rotulo: "Nova subtarefa", acao: () => { E.ajustes.pai = t.id; $("#rapido").focus(); $("#rapido").placeholder = `Subtarefa de "${t.titulo.slice(0, 30)}" — escreva e Enter`; renderFichas(); } },
    { rotulo: "Copiar o ID", acao: () => { navigator.clipboard && navigator.clipboard.writeText(t.chave || ""); aviso(`${t.chave} copiado`); } },
    { rotulo: "Apagar (lixeira)", perigo: true, acao: () => apagarTarefa(t) },
  ]);
}
async function apagarTarefa(t) {
  // sem "tem certeza?": apaga, e o aviso dá 8 segundos para desfazer (a lixeira guarda)
  const filhas = filhasDe(t.id);
  let junto = false;
  if (filhas.length) junto = confirm(`"${t.titulo}" tem ${filhas.length} subtarefa(s).\n\nOK = apaga as subtarefas junto.\nCancelar = só a mãe sai e as subtarefas sobem um nível.`);
  await api("DELETE", `/api/tarefas/${t.id}?com_filhas=${junto ? 1 : 0}`);
  if (E.selecionada === t.id) fecharPainel();
  await carregar();
  aviso(`${t.chave || ""} foi para a lixeira`, { rotulo: "Desfazer", acao: async () => {
    await api("POST", `/api/lixeira/${t.id}/restaurar`);
    for (const f of (junto ? filhas : [])) { try { await api("POST", `/api/lixeira/${f.id}/restaurar`); } catch (e) { } }
    await carregar(); aviso(`${t.chave || ""} de volta`);
  } });
}

/* ---------------------------------------------------------------- painel */
function abrirPainel(id) { E.selecionada = id; $("#painel").classList.remove("fechado"); renderPainel(); }
function fecharPainel() { E.selecionada = ""; $("#painel").classList.add("fechado"); }
$("#bt-fechar-painel").onclick = fecharPainel;
$("#bt-apagar").onclick = () => { const t = tarefa(E.selecionada); if (t) apagarTarefa(t); };
function renderPainel() {
  const t = tarefa(E.selecionada); if (!t) return;
  const l = listaDe(t.lista); const corpo = $("#painel-corpo"); corpo.innerHTML = "";
  const e = l ? espacoDe(l.espaco) : null;
  $("#painel-chave").textContent = t.chave || "";
  $("#painel-caminho").textContent = `${e ? e.nome + " / " : ""}${l ? l.nome : ""}${t.pai && tarefa(t.pai) ? " / " + (tarefa(t.pai).chave || tarefa(t.pai).titulo) : ""}`;
  const patch = async campos => { await api("PATCH", `/api/tarefas/${t.id}`, campos); await carregar(); };

  const h2 = el("h2", { contenteditable: "true", text: t.titulo });
  h2.addEventListener("blur", () => { const n = h2.textContent.trim(); if (n && n !== t.titulo) patch({ titulo: n }); });
  h2.addEventListener("keydown", ev => { if (ev.key === "Enter") { ev.preventDefault(); h2.blur(); } });
  corpo.append(h2);

  // o painel em abas — Detalhes, Checklist, Comentários, Atividade (antes era uma rolagem só)
  const abas = el("div", { class: "painel-abas" });
  const paginas = { detalhes: el("div"), checklist: el("div"), comentarios: el("div"), atividade: el("div") };
  const rotulos = { detalhes: "Detalhes", checklist: `Checklist${progresso(t) ? " " + progresso(t) : ""}`, comentarios: `Comentários${(t.comentarios || []).length ? " " + t.comentarios.length : ""}`, atividade: "Atividade" };
  for (const [k, r] of Object.entries(rotulos)) abas.append(el("button", { class: k === E.abaPainel ? "ativo" : "", text: r, onclick: () => { E.abaPainel = k; renderPainel(); } }));
  corpo.append(abas);
  for (const [k, pag] of Object.entries(paginas)) { pag.classList.toggle("oculto", k !== E.abaPainel); corpo.append(pag); }
  const emAba = (nome, elemento) => paginas[nome].append(elemento);

  const campos = el("div", { class: "campos" });
  const campo = (rotulo, controle) => { campos.append(el("label", { text: rotulo }), controle); };
  campo("Status", el("select", { onchange: ev => mudarStatus(t, l.status.find(s => s.id === ev.target.value)) }, l.status.map(s => el("option", { value: s.id, text: s.nome, selected: s.id === t.status }))));
  campo("Prioridade", el("select", { onchange: ev => patch({ prioridade: ev.target.value }) }, Object.keys(PRIO_ROTULO).map(p => el("option", { value: p, text: PRIO_ROTULO[p], selected: p === t.prioridade }))));
  campo("Prazo", el("input", { type: "date", value: t.prazo || "", onchange: ev => patch({ prazo: ev.target.value || null }) }));
  const cli = el("div", { class: "sugestoes" });
  const cliInput = el("input", { type: "text", value: t.cliente ? `${t.cliente} — ${t.cliente_nome}` : "", placeholder: "código ou nome" });
  const sug = el("div", { class: "sugestoes-lista oculto" });
  let timerCli = null;
  cliInput.addEventListener("input", () => {
    clearTimeout(timerCli);
    timerCli = setTimeout(async () => {
      const q = cliInput.value.trim(); if (!q) { sug.classList.add("oculto"); if (t.cliente) patch({ cliente: "" }); return; }
      const achados = await api("GET", `/api/clientes?q=${encodeURIComponent(q)}`); sug.innerHTML = "";
      for (const c of achados) sug.append(el("div", { text: `${c.codigo} — ${c.nome}`, onmousedown: () => { patch({ cliente: c.codigo }); sug.classList.add("oculto"); } }));
      sug.classList.toggle("oculto", !achados.length);
    }, 250);
  });
  cliInput.addEventListener("blur", () => setTimeout(() => sug.classList.add("oculto"), 150));
  cli.append(cliInput, sug); campo("Cliente", cli);
  campo("Tipo", el("select", { onchange: ev => patch({ tipo: ev.target.value }) }, [el("option", { value: "", text: "outro", selected: !t.tipo }), ...Object.entries(E.dados.tipos).sort((a, b) => a[1].localeCompare(b[1])).map(([k, n]) => el("option", { value: k, text: n, selected: k === t.tipo }))]));
  campo("Responsáveis", controleResponsaveis(donos(t), nomes => patch({ responsaveis: nomes }), false));
  campo("Lista", el("select", { onchange: ev => patch({ lista: ev.target.value }) }, E.dados.listas.map(x => el("option", { value: x.id, text: `${(espacoDe(x.espaco) || {}).nome || ""} / ${x.nome}`, selected: x.id === t.lista }))));
  // repetir
  const [recTipo, recValor, recRegra] = (t.recorrencia || "").split(":");
  const selRec = el("select", {}, [["", "nunca"], ["mensal", "todo mês, no dia…"], ["semanal", "toda semana, na…"], ["dias", "a cada N dias"], ["uteis", "N dias úteis depois de concluir"]].map(([v, r]) => el("option", { value: v, text: r, selected: v === (recTipo || "") })));
  const recDetalhe = el("span", { style: "display:flex;gap:6px;align-items:center;flex-wrap:wrap" });
  const montarRec = () => {
    recDetalhe.innerHTML = "";
    const tipo = selRec.value;
    if (!tipo) { if (t.recorrencia) patch({ recorrencia: "" }); return; }
    if (tipo === "semanal") {
      const s = el("select", { onchange: ev => patch({ recorrencia: `semanal:${ev.target.value}` }) }, ["seg", "ter", "qua", "qui", "sex", "sab", "dom"].map(d => el("option", { value: d, text: d, selected: d === recValor })));
      recDetalhe.append(s); if (recTipo !== "semanal") patch({ recorrencia: `semanal:${s.value}` });
    } else if (tipo === "mensal") {
      const n = el("input", { type: "number", min: "1", max: "31", value: recValor || "1", style: "width:64px" });
      const r = el("select", {}, [["depois", "se não for útil, adia"], ["antes", "se não for útil, antecipa"], ["exato", "no dia exato"]].map(([v, rot]) => el("option", { value: v, text: rot, selected: v === (recRegra || "depois") })));
      const salvar = () => patch({ recorrencia: `mensal:${n.value || 1}:${r.value}` });
      n.onchange = salvar; r.onchange = salvar;
      recDetalhe.append(el("span", { class: "apagado", text: "dia" }), n, r);
      if (recTipo !== "mensal") salvar();
    } else {
      const n = el("input", { type: "number", min: "1", max: "365", value: recValor || "7", style: "width:70px", onchange: ev => patch({ recorrencia: `${tipo}:${ev.target.value}` }) });
      recDetalhe.append(n); if (recTipo !== tipo) patch({ recorrencia: `${tipo}:${n.value}` });
    }
  };
  selRec.onchange = montarRec; montarRec();
  campo("Repetir", el("div", { style: "display:flex;gap:6px;align-items:center;flex-wrap:wrap" }, [selRec, recDetalhe]));
  campo("Lembrar em", el("span", { style: "display:flex;gap:6px;align-items:center;flex-wrap:wrap" }, [
    el("input", { type: "date", value: t.lembrete || "", onchange: ev => patch({ lembrete: ev.target.value || null }) }),
    el("span", { class: "apagado", text: "às" }),
    el("input", { type: "time", value: t.lembrete_hora || "", title: "Hora do balão (vazio = no começo do dia)", onchange: ev => patch({ lembrete_hora: ev.target.value || "", lembrete: t.lembrete || (ev.target.value ? (t.prazo || hojeISO()) : null) }) }),
    el("span", { class: "apagado", text: "e nesse dia, a cada" }),
    campoIntervalo(t.lembrete_cada, min => patch({ lembrete_cada: min })),
    // o motivo vai no balão ("Lembrete: cobrar o cliente — EQP-12"); o botão marca o lembrete em dias úteis
    el("input", { type: "text", class: "curto", value: t.lembrete_motivo || "", placeholder: "motivo (ex.: cobrar o cliente)", title: "Aparece no balão do lembrete", onchange: ev => patch({ lembrete_motivo: ev.target.value.trim() }) }),
    el("button", { class: "mini", text: "cobrar o cliente ▾", title: "Lembrete de perguntar se o cliente respondeu", onclick: ev => menuCobrar(ev, t) })]));
  // rodízio — quando a tarefa repete, cada vez é de um da lista, nesta ordem
  const rodCaixa = el("div");
  const montarRod = () => {
    rodCaixa.innerHTML = "";
    const ordem = t.rodizio || [];
    if (!t.recorrencia) { rodCaixa.append(el("span", { class: "apagado", text: "só para tarefa que repete (Repetir acima)" })); return; }
    rodCaixa.append(controleResponsaveis(ordem, nomes => patch({ rodizio: nomes }), false));
    if (ordem.length) rodCaixa.append(el("div", { class: "apagado", style: "margin-top:4px", text: `ordem: ${ordem.join(" → ")} → ${ordem[0]} · a próxima vez vai para quem vem depois de ${(t.responsaveis || [])[0] || "—"}` }));
    else rodCaixa.append(el("div", { class: "apagado", style: "margin-top:4px", text: "sem rodízio: repete sempre com os mesmos responsáveis" }));
  };
  montarRod(); campo("Rodízio", rodCaixa);
  emAba("detalhes", campos);

  const bl = (titulo, aba = "detalhes") => { const b = el("div", { class: "bloco" }); b.append(el("h3", { text: titulo })); paginas[aba].append(b); return b; };

  if ((l.campos || []).length) {
    const bCampos = bl("Campos da lista");
    const grade = el("div", { class: "campos" });
    for (const c of l.campos) { grade.append(el("label", { text: c.nome }), controleCampo(t, c, valor => patch({ campos: { [c.id]: valor } }))); }
    bCampos.append(grade);
  }

  const bDesc = bl("Descrição");
  const ta = el("textarea", { id: "descricao", placeholder: "Anotações, o que o cliente disse, o que falta…" }); ta.value = t.descricao || "";
  ta.addEventListener("blur", () => { if (ta.value.trim() !== (t.descricao || "").trim()) patch({ descricao: ta.value.trim() }); });
  bDesc.append(ta);

  const bCheck = bl(`Checklist ${progresso(t) ? "· " + progresso(t) : ""}`, "checklist");
  (t.checklist || []).forEach((it, i) => {
    bCheck.append(el("div", { class: "item-check" }, [
      el("input", { type: "checkbox", checked: it.feito, onchange: ev => patch({ checklist: t.checklist.map((x, j) => j === i ? { ...x, feito: ev.target.checked } : x) }) }),
      el("span", { class: it.feito ? "feito" : "", text: it.texto }),
      el("button", { class: "mini", text: "×", onclick: () => patch({ checklist: t.checklist.filter((_, j) => j !== i) }) })]));
  });
  const novoItem = el("input", { type: "text", placeholder: "novo passo e Enter" });
  novoItem.addEventListener("keydown", ev => { if (ev.key === "Enter" && novoItem.value.trim()) patch({ checklist: [...(t.checklist || []), { texto: novoItem.value.trim(), feito: false }] }); });
  bCheck.append(el("div", { class: "linha-add" }, [novoItem]));

  const bSub = bl("Subtarefas", "checklist");
  for (const f of filhasDe(t.id)) {
    const s = statusDe(f);
    bSub.append(el("div", { class: "subtarefa", onclick: () => abrirPainel(f.id) }, [el("span", { class: "st", style: `background:${s.cor}` }), chaveTag(f), el("span", { text: f.titulo, style: feita(f) ? "text-decoration:line-through;color:var(--apagado)" : "" }), f.prazo ? el("span", { class: "prazo " + classePrazo(f), text: fmtPrazo(f.prazo) }) : null]));
  }
  const novaSub = el("input", { type: "text", placeholder: "nova subtarefa e Enter (entende a linha também)" });
  novaSub.addEventListener("keydown", async ev => { if (ev.key === "Enter" && novaSub.value.trim()) { await api("POST", "/api/tarefas", { lista: t.lista, texto: novaSub.value.trim(), ajustes: { pai: t.id } }); carregar(); } });
  bSub.append(el("div", { class: "linha-add" }, [novaSub]));

  const bLig = bl("Ligações (seguidas e relacionadas)");
  for (const lg of (t.ligacoes || [])) {
    const alvo = tarefa(lg.alvo); if (!alvo) continue;
    const bloqueia = lg.tipo === "depende" && !feita(alvo);
    bLig.append(el("div", { class: "ligacao" + (bloqueia ? " bloqueia" : "") }, [
      el("span", { class: "tipo", text: lg.tipo === "depende" ? "começa depois de" : "relacionada a" }),
      el("span", { class: "alvo", text: `${alvo.chave || ""} ${alvo.titulo}`, onclick: () => abrirPainel(alvo.id) }),
      el("button", { class: "mini", text: "×", onclick: () => patch({ ligacoes: t.ligacoes.filter(x => x.alvo !== lg.alvo) }) })]));
  }
  const selTipo = el("select", {}, [el("option", { value: "depende", text: "começa depois de" }), el("option", { value: "relacionada", text: "relacionada a" })]);
  const busca = el("input", { type: "text", placeholder: "ID ou título da outra tarefa" });
  const sugL = el("div", { class: "sugestoes-lista oculto" });
  busca.addEventListener("input", () => {
    const q = busca.value.trim().toLowerCase(); sugL.innerHTML = "";
    const achadas = q ? E.dados.tarefas.filter(x => x.id !== t.id && (`${x.chave} ${x.titulo}`).toLowerCase().includes(q)).slice(0, 8) : [];
    for (const x of achadas) sugL.append(el("div", { text: `${x.chave || ""} ${x.titulo}${x.cliente ? " · " + x.cliente : ""}`, onmousedown: () => patch({ ligacoes: [...(t.ligacoes || []), { tipo: selTipo.value, alvo: x.id }] }) }));
    sugL.classList.toggle("oculto", !achadas.length);
  });
  busca.addEventListener("blur", () => setTimeout(() => sugL.classList.add("oculto"), 150));
  bLig.append(el("div", { class: "linha-add" }, [selTipo, el("div", { class: "sugestoes", style: "flex:1" }, [busca, sugL])]));

  // anexos (link ou arquivo) nos Detalhes
  const bAnexos = bl(`Anexos${(t.anexos || []).length ? " · " + t.anexos.length : ""}`);
  for (const a of (t.anexos || [])) {
    const link = a.tipo === "link" ? el("a", { href: /^https?:/i.test(a.url) ? a.url : "#", target: "_blank", text: a.nome || a.url, title: a.url,
      onclick: ev => { if (!/^https?:/i.test(a.url)) { ev.preventDefault(); navigator.clipboard && navigator.clipboard.writeText(a.url); aviso("caminho copiado — cole no Explorador de Arquivos"); } } })
      : el("a", { href: `/api/anexos/${t.id}/${a.id}`, target: "_blank", text: a.nome, title: `${(a.tamanho / 1024).toFixed(0)} KB` });
    bAnexos.append(el("div", { class: "anexo" }, [el("span", { text: a.tipo === "link" ? "🔗" : "📎" }), link,
      el("span", { class: "apagado", text: `${a.pessoa || ""} ${fmtDataCurta(a.quando)}` }),
      el("button", { class: "mini", text: "×", title: "Tirar", onclick: async () => { await api("DELETE", `/api/tarefas/${t.id}/anexos/${a.id}`); carregar(); } })]));
  }
  const linkNome = el("input", { type: "text", placeholder: "nome (opcional)", style: "flex:1" });
  const linkUrl = el("input", { type: "text", placeholder: "https://… ou caminho de rede", style: "flex:2" });
  const addLink = async () => { if (!linkUrl.value.trim()) { aviso("cole o endereço ou o caminho"); return; } await api("POST", `/api/tarefas/${t.id}/anexos`, { tipo: "link", nome: linkNome.value.trim(), url: linkUrl.value.trim() }); carregar(); };
  linkUrl.addEventListener("keydown", ev => { if (ev.key === "Enter") addLink(); });
  const arquivo = el("input", { type: "file", style: "display:none", onchange: async ev => {
    const f = ev.target.files[0]; if (!f) return;
    if (f.size > 20 * 1024 * 1024) { aviso("arquivo maior que 20 MB — guarde na pasta do cliente e anexe o caminho"); return; }
    const b64 = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });
    await api("POST", `/api/tarefas/${t.id}/anexos`, { tipo: "arquivo", nome: f.name, dados: b64 }); carregar();
  } });
  bAnexos.append(el("div", { class: "linha-add" }, [linkNome, linkUrl, el("button", { class: "mini", text: "+ link", onclick: addLink }), el("button", { class: "mini", text: "+ arquivo", onclick: () => arquivo.click() }), arquivo]));
  bAnexos.append(el("div", { class: "apagado", text: "Dica: um caminho de pasta vira link que copia ao clicar — cole no Explorador de Arquivos." }));

  // comentários com @nome
  const pC = paginas.comentarios;
  const comentarios = (t.comentarios || []);
  if (!comentarios.length) pC.append(el("div", { class: "apagado", style: "padding:8px 0", text: "Nenhum comentário. Use @nome para avisar alguém da Equipe." }));
  for (const c of comentarios) {
    const texto = el("div", { class: "texto" });
    (c.texto || "").split(/(@[\wÀ-ÿ]+)/).forEach(parte => texto.append(/^@/.test(parte) ? el("span", { class: "mencao", text: parte }) : document.createTextNode(parte)));
    pC.append(el("div", { class: "comentario" }, [
      c.pessoa === E.pessoa ? el("button", { class: "mini", text: "×", title: "Apagar", onclick: async () => { await api("DELETE", `/api/tarefas/${t.id}/comentarios/${c.id}`); carregar(); } }) : null,
      el("span", { class: "quem", text: c.pessoa || "alguém" }), el("span", { class: "quando", text: `${fmtDataCurta(c.quando)} ${(c.quando || "").slice(11, 16)}` }), texto]));
  }
  const caixaCom = el("div", { class: "comentar" });
  const taCom = el("textarea", { placeholder: "Escreva um comentário… @nome avisa a pessoa. Ctrl+Enter envia." });
  const enviar = async () => { const v = taCom.value.trim(); if (!v) return; await api("POST", `/api/tarefas/${t.id}/comentarios`, { texto: v }); taCom.value = ""; E.abaPainel = "comentarios"; carregar(); };
  taCom.addEventListener("keydown", ev => { if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") { ev.preventDefault(); enviar(); } });
  caixaCom.append(taCom, el("div", { style: "display:flex;justify-content:space-between;align-items:center;margin-top:6px" }, [
    el("span", { class: "apagado", text: "Equipe: " + equipeDe(t.lista).map(n => "@" + n.split(" ")[0].toLowerCase()).join(" ") }),
    el("button", { class: "primario", text: "Comentar", onclick: enviar })]));
  pC.append(caixaCom);

  const meta = el("div", { class: "meta" });
  meta.append(el("div", { text: `Prioridade ${PRIO_ROTULO[t.prioridade]}: ${t.motivo_prioridade || "—"}` }));
  meta.append(el("div", { text: `Criada ${fmtDataCurta(t.criada)} ${(t.criada || "").slice(11, 16)}${t.criada_por ? " por " + t.criada_por : ""}${t.origem ? " · veio por " + t.origem : ""}` }));
  if (statusDe(t).tipo === "aguardando" && t.aguardando_desde) meta.append(el("div", { text: `Aguardando há ${-diasAte(t.aguardando_desde)} dia(s)` }));
  if (t.concluida_em) meta.append(el("div", { text: `Concluída ${fmtDataCurta(t.concluida_em)}` }));
  if (t.texto_original && t.texto_original !== t.titulo) meta.append(el("div", { text: `Você escreveu: “${t.texto_original.split("\n")[0].slice(0, 160)}”` }));
  const ex = t.extraidos || {};
  if (ex.competencia || ex.documento || ex.valor !== undefined) meta.append(el("div", { text: "Da linha: " + [ex.competencia && `competência ${ex.competencia}`, ex.documento && `documento ${ex.documento}`, ex.valor !== undefined && "R$ " + Number(ex.valor).toLocaleString("pt-BR", { minimumFractionDigits: 2 })].filter(Boolean).join(" · ") }));
  if (t.triada_por) meta.append(el("div", { text: t.triada_por === "caixa" ? "Caiu na Caixa de entrada (nenhuma regra bateu)." : t.triada_por === "aprendido" ? "Lista escolhida pelo que você fez da última vez com este cliente e tipo." : "Lista e responsável vieram de uma regra de triagem." }));
  emAba("detalhes", meta);

  const bAt = bl("Atividade", "atividade");
  const lista = el("div", { class: "atividade", text: "carregando…" }); bAt.append(lista);
  api("GET", `/api/tarefas/${t.id}/historico`).then(itens => {
    lista.innerHTML = "";
    for (const it of itens.slice().reverse()) lista.append(el("div", {}, [`${fmtDataCurta(it.quando)} ${(it.quando || "").slice(11, 16)} — `, el("span", { text: it.texto })]));
    if (!itens.length) lista.textContent = "sem histórico ainda";
  }).catch(() => { lista.textContent = ""; });
}

/* ---------------------------------------------------------------- diálogos: campos, automações, modelos */
function dialogoCampos(l) {
  const campos = (l.campos || []).map(c => ({ ...c }));
  const corpo = el("div");
  corpo.append(el("p", { class: "dica", text: "Cada lista tem as suas colunas. Seleção: escreva as opções separadas por vírgula. \"No cartão\" mostra o valor no Quadro." }));
  const tab = el("table", { class: "dialogo-tabela" });
  tab.append(el("thead", {}, el("tr", {}, [el("th", { text: "Nome" }), el("th", { text: "Tipo" }), el("th", { text: "Opções (seleção)" }), el("th", { text: "No cartão" }), el("th")])));
  const tb = el("tbody"); tab.append(tb);
  const desenhar = () => {
    tb.innerHTML = "";
    campos.forEach((c, i) => {
      tb.append(el("tr", {}, [
        el("td", {}, el("input", { type: "text", value: c.nome, placeholder: "ex.: Regime", oninput: ev => c.nome = ev.target.value })),
        el("td", {}, el("select", { onchange: ev => { c.tipo = ev.target.value; desenhar(); } }, Object.entries(TIPO_CAMPO_ROTULO).map(([v, r]) => el("option", { value: v, text: r, selected: v === c.tipo })))),
        el("td", {}, c.tipo === "selecao" ? el("input", { type: "text", value: (c.opcoes || []).join(", "), placeholder: "Simples, Presumido, Real", oninput: ev => c.opcoes = ev.target.value.split(",").map(x => x.trim()).filter(Boolean) }) : el("span", { class: "apagado", text: "—" })),
        el("td", {}, el("input", { type: "checkbox", checked: !!c.no_cartao, onchange: ev => c.no_cartao = ev.target.checked })),
        el("td", {}, el("button", { class: "mini perigo", text: "×", onclick: () => { campos.splice(i, 1); desenhar(); } })),
      ]));
    });
  };
  desenhar(); corpo.append(tab);
  dialogo(`Campos de "${l.nome}"`, corpo, {
    esquerda: [el("button", { text: "+ Campo", onclick: () => { campos.push({ nome: "", tipo: "texto", opcoes: [] }); desenhar(); } })],
    direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Salvar", onclick: async () => {
      const validos = campos.filter(c => c.nome.trim());
      await api("PATCH", `/api/listas/${l.id}`, { campos: validos }); fecharDialogo(); carregar(); aviso("Campos salvos.");
    } })],
  });
}
function dialogoAutomacoes(l) {
  const regras = (l.automacoes || []).map(a => ({ ...a, entao: a.entao.map(x => ({ ...x })) }));
  const corpo = el("div");
  corpo.append(el("p", { class: "dica", text: "Quando acontece X nesta lista, o app faz Y sozinho. Uma regra pode ter mais de um \"então\"." }));
  const caixa = el("div"); corpo.append(caixa);
  const valorQuando = (r) => {
    const ev = r.quando.evento;
    if (ev === "status") return el("select", { onchange: e => r.quando.valor = e.target.value }, [el("option", { value: "", text: "qualquer", selected: !r.quando.valor }), ...l.status.map(s => el("option", { value: s.id, text: s.nome, selected: s.id === r.quando.valor }))]);
    if (ev === "prioridade") return el("select", { onchange: e => r.quando.valor = e.target.value }, [el("option", { value: "", text: "qualquer", selected: !r.quando.valor }), ...Object.keys(PRIO_ROTULO).map(p => el("option", { value: p, text: PRIO_ROTULO[p], selected: p === r.quando.valor }))]);
    return el("span", { class: "apagado", text: "" });
  };
  const valorEntao = (x) => {
    if (x.acao === "status") return el("select", { onchange: e => x.valor = e.target.value }, l.status.map(s => el("option", { value: s.id, text: s.nome, selected: s.id === x.valor })));
    if (x.acao === "prioridade") return el("select", { onchange: e => x.valor = e.target.value }, Object.keys(PRIO_ROTULO).map(p => el("option", { value: p, text: PRIO_ROTULO[p], selected: p === x.valor })));
    if (x.acao === "responsavel") return el("select", { onchange: e => x.valor = e.target.value }, [el("option", { value: "", text: "ninguém", selected: !x.valor }), ...pessoasConhecidas(x.valor).map(n => el("option", { value: n, text: n, selected: n === x.valor }))]);
    if (x.acao === "mover_lista") return el("select", { onchange: e => x.valor = e.target.value }, E.dados.listas.filter(z => z.id !== l.id).map(z => el("option", { value: z.id, text: z.nome, selected: z.id === x.valor })));
    return el("input", { type: "number", value: x.valor || (x.acao === "lembrar" ? 3 : 7), oninput: e => x.valor = e.target.value });
  };
  const desenhar = () => {
    caixa.innerHTML = "";
    regras.forEach((r, i) => {
      const linha = el("div", { class: "regra" });
      linha.append(el("span", { class: "quando", text: "quando" }));
      linha.append(el("select", { onchange: e => { r.quando.evento = e.target.value; r.quando.valor = ""; desenhar(); } }, Object.entries(EVENTO_ROTULO).map(([v, rot]) => el("option", { value: v, text: rot, selected: v === r.quando.evento }))));
      linha.append(valorQuando(r));
      linha.append(el("span", { class: "entao", text: "então" }));
      const x = r.entao[0];
      linha.append(el("select", { onchange: e => { x.acao = e.target.value; x.valor = ""; desenhar(); } }, Object.entries(ACAO_ROTULO).map(([v, rot]) => el("option", { value: v, text: rot, selected: v === x.acao }))));
      linha.append(valorEntao(x));
      linha.append(el("button", { class: "mini perigo", text: "×", onclick: () => { regras.splice(i, 1); desenhar(); } }));
      caixa.append(linha);
      r.entao.slice(1).forEach((y, j) => {
        const extra = el("div", { class: "regra" });
        extra.append(el("span"), el("span"), el("span"), el("span", { class: "entao", text: "e" }));
        extra.append(el("select", { onchange: e => { y.acao = e.target.value; y.valor = ""; desenhar(); } }, Object.entries(ACAO_ROTULO).map(([v, rot]) => el("option", { value: v, text: rot, selected: v === y.acao }))));
        extra.append(valorEntao(y));
        extra.append(el("button", { class: "mini perigo", text: "×", onclick: () => { r.entao.splice(j + 1, 1); desenhar(); } }));
        caixa.append(extra);
      });
      caixa.append(el("div", { style: "padding:2px 0 8px 70px" }, el("button", { class: "mini", text: "+ e também…", onclick: () => { r.entao.push({ acao: "lembrar", valor: "3" }); desenhar(); } })));
    });
    if (!regras.length) caixa.append(el("div", { class: "sem-nada", text: "Nenhuma regra ainda." }));
  };
  desenhar();
  dialogo(`Automações de "${l.nome}"`, corpo, {
    esquerda: [el("button", { text: "+ Regra", onclick: () => { regras.push({ quando: { evento: "status", valor: l.status.find(s => s.tipo === "aguardando") ? l.status.find(s => s.tipo === "aguardando").id : "" }, entao: [{ acao: "lembrar", valor: "3" }], ligada: true }); desenhar(); } }),
      el("button", { text: "Exemplos", onclick: () => { regras.push(
        { quando: { evento: "prazo_passou", valor: "" }, entao: [{ acao: "prioridade", valor: "urgente" }], ligada: true },
        { quando: { evento: "checklist_completo", valor: "" }, entao: [{ acao: "status", valor: (l.status.find(s => s.tipo === "feito") || {}).id || "" }], ligada: true },
        { quando: { evento: "liberada", valor: "" }, entao: [{ acao: "lembrar", valor: "0" }], ligada: true }); desenhar(); } })],
    direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Salvar", onclick: async () => {
      try { await api("PATCH", `/api/listas/${l.id}`, { automacoes: regras }); fecharDialogo(); carregar(); aviso("Automações salvas."); } catch (e) { }
    } })],
  });
}
async function salvarComoModelo(l) {
  const nome = prompt("Nome do modelo:", l.nome); if (!nome) return;
  const m = await api("POST", "/api/modelos", { lista: l.id, nome });
  await carregar(); aviso(`Modelo "${m.nome}" salvo com ${m.tarefas.length} tarefa(s).`); dialogoModelos(m.id);
}
function dialogoModelos(abrirId) {
  const modelos = E.dados.modelos || [];
  const corpo = el("div");
  if (!modelos.length) { corpo.append(el("p", { class: "dica", text: "Nenhum modelo ainda. Numa lista, ⚙ → Salvar como modelo." })); dialogo("Modelos de lista", corpo, { direita: [el("button", { text: "Fechar", onclick: fecharDialogo })] }); return; }
  const sel = el("select", {}, modelos.map(m => el("option", { value: m.id, text: m.nome, selected: m.id === abrirId })));
  corpo.append(el("div", { class: "linha-form" }, [el("label", { text: "Modelo" }), sel]));
  const area = el("div"); corpo.append(area);
  const desenhar = () => {
    const m = modelos.find(x => x.id === sel.value); area.innerHTML = "";
    area.append(el("p", { class: "dica", text: "Marque \"por cliente\" para a tarefa nascer uma vez por cliente escolhido; \"segue a anterior\" liga a tarefa à de cima (começa depois dela). O prazo pode vir de uma obrigação do calendário, de um dia do mês ou de N dias úteis depois de criar." }));
    const tab = el("table", { class: "dialogo-tabela" });
    tab.append(el("thead", {}, el("tr", {}, ["Tarefa", "Por cliente", "Segue a anterior", "Prazo", "", "Responsável", ""].map(x => el("th", { text: x })))));
    const tb = el("tbody"); tab.append(tb);
    m.tarefas.forEach((t, i) => {
      const regra = t.prazo || {};
      const tipoPrazo = regra.obrigacao ? "obrigacao" : regra.dia ? "dia" : regra.uteis_apos !== undefined ? "uteis" : "";
      const valorPrazo = el("span");
      const montar = () => {
        valorPrazo.innerHTML = "";
        const tp = selPrazo.value;
        if (tp === "obrigacao") valorPrazo.append(el("select", { onchange: e => t.prazo = { obrigacao: e.target.value } }, E.dados.obrigacoes.map(o => el("option", { value: o, text: o, selected: o === regra.obrigacao }))));
        else if (tp === "dia") valorPrazo.append(el("input", { type: "number", min: 1, max: 31, value: regra.dia || 10, onchange: e => t.prazo = { dia: Number(e.target.value) } }));
        else if (tp === "uteis") valorPrazo.append(el("input", { type: "number", min: 0, max: 60, value: regra.uteis_apos ?? 2, onchange: e => t.prazo = { uteis_apos: Number(e.target.value) } }));
        else t.prazo = null;
        if (tp === "obrigacao" && !t.prazo?.obrigacao) t.prazo = { obrigacao: E.dados.obrigacoes[0] };
        if (tp === "dia" && !t.prazo?.dia) t.prazo = { dia: regra.dia || 10 };
        if (tp === "uteis" && t.prazo?.uteis_apos === undefined) t.prazo = { uteis_apos: regra.uteis_apos ?? 2 };
      };
      const selPrazo = el("select", { onchange: montar }, [["", "sem prazo"], ["obrigacao", "obrigação do mês"], ["dia", "dia do mês"], ["uteis", "dias úteis depois"]].map(([v, r]) => el("option", { value: v, text: r, selected: v === tipoPrazo })));
      montar();
      tb.append(el("tr", {}, [
        el("td", {}, el("input", { type: "text", value: t.titulo, oninput: e => t.titulo = e.target.value })),
        el("td", {}, el("input", { type: "checkbox", checked: !!t.por_cliente, onchange: e => t.por_cliente = e.target.checked })),
        el("td", {}, el("input", { type: "checkbox", checked: !!t.depende_da_anterior, onchange: e => t.depende_da_anterior = e.target.checked })),
        el("td", {}, selPrazo), el("td", {}, valorPrazo),
        el("td", {}, el("input", { type: "text", value: t.responsavel || "", placeholder: "quem cria", oninput: e => t.responsavel = e.target.value })),
        el("td", {}, el("button", { class: "mini perigo", text: "×", onclick: () => { m.tarefas.splice(i, 1); desenhar(); } })),
      ]));
    });
    area.append(tab);
    area.append(el("div", { style: "margin-top:8px" }, el("button", { text: "+ Tarefa no modelo", onclick: () => { m.tarefas.push({ titulo: "", prioridade: "normal", checklist: [], campos: {}, por_cliente: false, depende_da_anterior: false }); desenhar(); } })));
  };
  sel.onchange = desenhar; desenhar();
  dialogo("Modelos de lista", corpo, {
    esquerda: [el("button", { class: "perigo", text: "Apagar modelo", onclick: async () => { const m = modelos.find(x => x.id === sel.value); if (confirm(`Apagar o modelo "${m.nome}"?`)) { await api("DELETE", `/api/modelos/${m.id}`); fecharDialogo(); carregar(); } } }),
      el("button", { text: "Renomear", onclick: async () => { const m = modelos.find(x => x.id === sel.value); const n = prompt("Nome:", m.nome); if (n) { await api("PATCH", `/api/modelos/${m.id}`, { nome: n }); carregar(); } } })],
    direita: [el("button", { text: "Fechar", onclick: fecharDialogo }),
      el("button", { text: "Salvar alterações", onclick: async () => { const m = modelos.find(x => x.id === sel.value); await api("PATCH", `/api/modelos/${m.id}`, { tarefas: m.tarefas.filter(t => t.titulo.trim()) }); carregar(); aviso("Modelo salvo."); } }),
      el("button", { class: "primario", text: "Criar lista com este modelo…", onclick: () => { const id = sel.value; fecharDialogo(); dialogoNovaListaDeModelo(id); } })],
  });
}
function dialogoNovaListaDeModelo(modeloId, espacoId) {
  const m = (E.dados.modelos || []).find(x => x.id === modeloId); if (!m) return;
  const hoje = new Date();
  const comp = `${String(hoje.getMonth() + 1).padStart(2, "0")}-${hoje.getFullYear()}`;
  const temPorCliente = m.tarefas.some(t => t.por_cliente);
  const selEsp = el("select", {}, E.dados.espacos.filter(e => !m.departamento || e.departamento === m.departamento).map(e => el("option", { value: e.id, text: e.nome, selected: e.id === (espacoId || (listaDe(E.lista) || {}).espaco) })));
  const nome = el("input", { type: "text", value: m.nome.replace(/\{mes\}/g, comp) + (/\d{2}[-\/]\d{4}/.test(m.nome) ? "" : " " + comp) });
  const compInput = el("input", { type: "text", value: comp, placeholder: "MM-AAAA" });
  const clientes = el("textarea", { rows: 3, placeholder: "códigos separados por vírgula ou espaço — ex.: 101, 102, 103" });
  const corpo = el("div");
  corpo.append(el("div", { class: "linha-form" }, [el("label", { text: "Espaço" }), selEsp, el("label", { text: "Nome da lista" }), nome, el("label", { text: "Competência" }), compInput]));
  if (temPorCliente) {
    corpo.append(el("div", { class: "linha-form" }, [el("label", { text: "Clientes" }), clientes]));
    corpo.append(el("p", { class: "dica", text: `${m.tarefas.filter(t => t.por_cliente).length} tarefa(s) do modelo nascem uma vez por cliente. Deixe em branco para pular essas.` }));
  }
  corpo.append(el("p", { class: "dica", text: `${m.tarefas.length} tarefa(s) no modelo. Prazos vêm do calendário da competência.` }));
  dialogo(`Nova lista a partir de "${m.nome}"`, corpo, {
    direita: [el("button", { text: "Cancelar", onclick: fecharDialogo }), el("button", { class: "primario", text: "Criar lista", onclick: async () => {
      const codigos = clientes.value.split(/[\s,;]+/).map(x => x.trim()).filter(Boolean);
      const l = await api("POST", "/api/listas/de-modelo", { modelo: m.id, espaco: selEsp.value, nome: nome.value.trim(), competencia: compInput.value.trim(), clientes: codigos });
      fecharDialogo(); await carregar(); escolherLista(l.id); aviso(`Lista "${l.nome}" criada.`);
    } })],
  });
}

/* ---------------------------------------------------------------- identidade */
function pedirNome(trocar = false) {
  const m = $("#modal"); const inp = $("#modal-nome");
  inp.value = trocar ? E.pessoa : ""; m.classList.remove("oculto"); setTimeout(() => inp.focus(), 50);
  const ok = () => { const n = inp.value.trim(); if (!n) { inp.focus(); return; } E.pessoa = n; localStorage.setItem("demandas.pessoa", n); m.classList.add("oculto"); if (E.dados) { carregar(); } else iniciar(); };
  $("#modal-ok").onclick = ok; inp.onkeydown = ev => { if (ev.key === "Enter") ok(); };
}
async function iniciar() {
  try { await carregar(true); } catch (e) { aviso("Não consegui falar com o servidor local. Abra pelo .bat de novo."); }
}
E.pessoa = localStorage.getItem("demandas.pessoa") || "";
/* com login ligado (modelo A), quem você é vem do servidor; sem login, do nome guardado no navegador */
(async () => {
  let eu = null;
  try { const r = await fetch("/api/eu"); eu = await r.json(); } catch (e) { }
  try { const r = await fetch("/api/versao"); const v = await r.json(); codigoDoServidor = v.codigo || ""; faixaDemo(v); } catch (e) { }
  E.loginLigado = !!(eu && eu.login_ligado);
  if (E.loginLigado) {
    if (eu.usuario) { E.usuario = eu.usuario; E.pessoa = eu.usuario.nome; localStorage.setItem("demandas.pessoa", E.pessoa); iniciar(); }
    else pedirLogin();
  } else if (E.pessoa) iniciar(); else pedirNome();
})();
