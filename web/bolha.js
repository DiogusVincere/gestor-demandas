/* A bolha: registrar a demanda e ver o dia sem abrir o app. Mesma API do servidor local, numa janela
   pequena sempre por cima (bolha.pyw). Fora do pywebview (navegador comum) funciona como página normal
   — serve para testar. Edição de verdade é no app completo ("⤢ tudo"); aqui é registrar, consultar,
   mudar o estado e pedir "me lembra depois". */
"use strict";
const $ = s => document.querySelector(s);
const el = (tag, attrs = {}, filhos = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v);
  }
  for (const f of [].concat(filhos)) if (f !== null && f !== undefined) n.append(f.nodeType ? f : document.createTextNode(String(f)));
  return n;
};
const B = { pessoa: localStorage.getItem("demandas.pessoa") || "", previa: null, ajustes: {}, colada: null, aberta: false, desde: "", listaPadrao: "",
            resumo: null, aberto: "", balaoTimer: null, equipe: null, fichasAbertas: false, recolherTimer: null, ociosoTimer: null };
const ABERTURAS_COM_DICA = 5;            // a linha de dicas aparece nas primeiras aberturas e depois some
const RECOLHER_SEM_FOCO_MS = 15000;      // clicou em outro programa: a caixa recolhe sozinha em 15 s (se não há texto digitado)
const RECOLHER_OCIOSA_MS = 90000;        // aberta e parada: recolhe em 90 s
const nativo = () => !!(window.pywebview && window.pywebview.api);
// o pywebview injeta `window.pywebview` depois que a página carrega: só decide "é navegador" se ele não aparecer
window.addEventListener("pywebviewready", () => document.body.classList.remove("navegador"));
setTimeout(() => { if (!nativo()) document.body.classList.add("navegador"); }, 1200);
const py = async (metodo, ...args) => { if (!nativo()) return null; try { return await window.pywebview.api[metodo](...args); } catch (e) { return null; } };

async function api(metodo, caminho, corpo) {
  const r = await fetch(caminho, { method: metodo, headers: { "Content-Type": "application/json", "X-Pessoa": encodeURIComponent(B.pessoa) }, body: corpo === undefined ? undefined : JSON.stringify(corpo) });
  let json = {}; try { json = await r.json(); } catch (e) { }
  if (r.status === 401 && json.login_ligado) {
    // modelo A: o login é feito no app completo; a janela da bolha usa o mesmo perfil e herda a sessão
    aviso("faça login no app completo (⤢ tudo) — depois a bolha funciona sozinha");
    if (!B.aberta) abrir();
    throw new Error("faça login");
  }
  if (!r.ok) { aviso(json.erro || `erro ${r.status}`); throw new Error(json.erro || r.status); }
  return json;
}
let avisoTimer = null;
function aviso(texto) { const a = $("#aviso"); a.textContent = texto; a.classList.remove("oculto"); clearTimeout(avisoTimer); avisoTimer = setTimeout(() => a.classList.add("oculto"), 2600); }
function isoDe(d) { return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, "0"), String(d.getDate()).padStart(2, "0")].join("-"); }
function hojeISO() { return isoDe(new Date()); }
function diasAte(iso) { if (!iso) return null; const [a, m, d] = iso.split("-").map(Number); const hoje = new Date(); hoje.setHours(0, 0, 0, 0); return Math.round((new Date(a, m - 1, d) - hoje) / 86400000); }
function fmtPrazo(iso) {
  const n = diasAte(iso); if (n === null) return "";
  const [a, m, d] = iso.split("-").map(Number); const dt = new Date(a, m - 1, d); const dm = `${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}`;
  return n === 0 ? "hoje" : n === 1 ? "amanhã" : n < 0 ? `${-n}d atrás` : n <= 6 ? ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"][dt.getDay()] + " " + dm : dm;
}
/* "EMPRESA EXEMPLO LTDA" → "Empresa Exemplo" (como no app) */
function nomeCurto(nome) {
  const partes = (nome || "").split(/\s+/).filter(p => p.length > 2 && !/^(LTDA|EIRELI|EIRE|ME|EPP|SA|S\/A|DE|DA|DO|DOS|DAS|E|SOCIEDADE|INDIVIDUAL|COMERCIO|SERVICOS)$/i.test(p));
  return partes.slice(0, 2).join(" ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}
const PRIO = { urgente: "Urgente", alta: "Alta", normal: "Normal", baixa: "Baixa" };
const PRIO_COR = { urgente: "#A33C2E", alta: "#EF9F27", normal: "#378ADD", baixa: "#B4B2A9" };
const PRIO_ORDEM = { urgente: 0, alta: 1, normal: 2, baixa: 3 };
const temTexto = () => !!($("#linha").value.trim() || $("#colado").value.trim());

/* ---- abrir / recolher: a janela nativa muda de tamanho; no navegador só troca o que aparece */
async function abrir() {
  B.aberta = true; document.body.classList.add("aberta"); document.body.classList.remove("com-balao");
  $("#bolha").classList.add("oculto"); $("#balao").classList.add("oculto"); $("#caixa").classList.remove("oculto");
  await py("abrir");
  if (!B.pessoa) { $("#nome").classList.remove("oculto"); $("#nome-input").focus(); } else $("#linha").focus();
  // as dicas só nas primeiras aberturas
  let n = 0; try { n = Number(localStorage.getItem("demandas.bolha.aberturas") || 0) + 1; localStorage.setItem("demandas.bolha.aberturas", String(n)); } catch (e) { }
  $("#dica").classList.toggle("oculto", n > ABERTURAS_COM_DICA);
  armarOciosa();
  atualizarResumo();
}
async function recolher() {
  B.aberta = false; document.body.classList.remove("aberta"); $("#caixa").classList.add("oculto"); $("#balao").classList.add("oculto"); $("#bolha").classList.remove("oculto"); modoColar(false); limpar();
  $("#pergunta").classList.add("oculto"); B.aberto = ""; fecharMenu();
  clearTimeout(B.recolherTimer); clearTimeout(B.ociosoTimer);
  await py("recolher");
}
function abrirDaTecla() { abrir(); }     // chamada pelo bolha.pyw quando o atalho global é apertado
window.abrirDaTecla = abrirDaTecla;
$("#bt-recolher").onclick = recolher;
$("#bt-tudo").onclick = () => abrirTudo("");
async function abrirTudo(tarefaId) {
  if (nativo()) { await py("abrir_tudo", tarefaId || ""); }
  else window.open("/" + (tarefaId ? `?tarefa=${encodeURIComponent(tarefaId)}` : ""), "_blank");
}
$("#nome-ok").onclick = () => { const n = $("#nome-input").value.trim(); if (!n) return; B.pessoa = n; localStorage.setItem("demandas.pessoa", n); $("#nome").classList.add("oculto"); $("#linha").focus(); atualizarResumo(); };
$("#nome-input").addEventListener("keydown", e => { if (e.key === "Enter") $("#nome-ok").click(); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { if (!$("#menu").classList.contains("oculto")) fecharMenu(); else if ($("#entrada-colar").classList.contains("oculto")) recolher(); else modoColar(false); }
});

/* ---- recolhe sozinha. Clicou em outro programa → 15 s; aberta e parada → 90 s. Nunca com texto digitado. */
function armarOciosa() {
  clearTimeout(B.ociosoTimer);
  if (!B.aberta) return;
  B.ociosoTimer = setTimeout(() => { if (B.aberta && !temTexto() && $("#menu").classList.contains("oculto")) recolher(); else armarOciosa(); }, RECOLHER_OCIOSA_MS);
}
for (const ev of ["mousemove", "keydown", "mousedown", "wheel"]) document.addEventListener(ev, () => { if (B.aberta) armarOciosa(); }, { passive: true });
window.addEventListener("blur", () => {
  if (!B.aberta) return;
  clearTimeout(B.recolherTimer);
  B.recolherTimer = setTimeout(() => { if (B.aberta && !document.hasFocus() && !temTexto()) recolher(); }, RECOLHER_SEM_FOCO_MS);
});
window.addEventListener("focus", () => clearTimeout(B.recolherTimer));

/* ---- arrastar para onde quiser: a barrinha (recolhida) e o cabeçalho (aberta) movem a janela.
   Feito à mão, com mousedown/mousemove → api.mover(dx, dy); menos de 5 px é clique. */
function arrastavel(elemento, aoClicar) {
  let inicio = null, moveu = false, acumX = 0, acumY = 0, agendado = false;
  elemento.addEventListener("mousedown", ev => {
    if (ev.button !== 0 || ev.target.closest("button")) return;
    inicio = { x: ev.screenX, y: ev.screenY }; moveu = false; acumX = acumY = 0; ev.preventDefault();
  });
  window.addEventListener("mousemove", ev => {
    if (!inicio) return;
    const dx = ev.screenX - inicio.x, dy = ev.screenY - inicio.y;
    if (!moveu && Math.abs(dx) + Math.abs(dy) < 5) return;
    moveu = true; inicio = { x: ev.screenX, y: ev.screenY }; acumX += dx; acumY += dy;
    if (!agendado) { agendado = true; requestAnimationFrame(async () => { const mx = acumX, my = acumY; acumX = acumY = 0; agendado = false; if (nativo()) await py("mover", mx, my); }); }
  });
  window.addEventListener("mouseup", async () => {
    if (!inicio) return;
    const foiClique = !moveu; inicio = null;
    if (foiClique) { if (aoClicar) aoClicar(); }
    else await py("guardar_posicao");
  });
}
arrastavel($("#bolha"), abrir);
arrastavel($("#cab"), null);

/* ---- a linha única, com o entendimento resumido (mesmo entendedor do app) */
function limpar() { $("#linha").value = ""; $("#colado").value = ""; $("#fichas").innerHTML = ""; $("#pedidos").innerHTML = ""; B.previa = null; B.ajustes = {}; B.colada = null; B.fichasAbertas = false; $("#bt-meu").classList.remove("ativo"); }
let timerPrevia = null;
$("#linha").addEventListener("input", () => { clearTimeout(timerPrevia); timerPrevia = setTimeout(previa, 300); });
$("#linha").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); criar(); } });
$("#linha").addEventListener("paste", ev => {
  const texto = (ev.clipboardData || window.clipboardData).getData("text") || "";
  if (texto.includes("\n") || texto.length > 160) { ev.preventDefault(); modoColar(true); $("#colado").value = texto; previaColar(); }
});
$("#bt-criar").onclick = criar;
async function previa() {
  const texto = $("#linha").value.trim(); const caixa = $("#fichas"); caixa.innerHTML = "";
  if (!texto) { B.previa = null; return; }
  try { B.previa = await api("POST", "/api/entender", { texto, lista: B.listaPadrao || undefined }); } catch (e) { return; }
  if ($("#linha").value.trim() !== texto) return;
  renderFichas();
}
function menu(x, y, itens) {
  const m = $("#menu"); m.innerHTML = ""; m.classList.remove("oculto");
  for (const it of itens) m.append(it === "sep" ? el("hr") : el("div", { text: it.rotulo, onclick: () => { fecharMenu(); it.acao(); } }));
  m.style.left = Math.max(4, Math.min(x, window.innerWidth - 230)) + "px"; m.style.top = Math.max(4, Math.min(y, window.innerHeight - 30 * itens.length - 10)) + "px";
  setTimeout(() => document.addEventListener("click", fecharMenu, { once: true }), 50);
}
function fecharMenu() { $("#menu").classList.add("oculto"); }
async function equipe() {
  if (B.equipe) return B.equipe;
  try { B.equipe = (await api("GET", "/api/equipe")).equipe || []; } catch (e) { B.equipe = []; }
  return B.equipe;
}
/* o que o app entendeu: numa linha ("101 Empresa Exemplo · carta de faturamento · vence sex 10/10 · para Ana"), cada parte
   clicável para trocar; as fichas coloridas só quando há dúvida (cliente?, já existe, pessoal) ou em "ajustar" */
function renderFichas() {
  const p = B.previa, aj = B.ajustes, caixa = $("#fichas"); caixa.innerHTML = ""; if (!p) return;
  const cli = "cliente" in aj ? aj.cliente : (p.cliente ? p.cliente.codigo : "");
  const nomeCli = "cliente" in aj ? (aj.cliente_nome || aj.cliente || "sem cliente") : (p.cliente ? `${p.cliente.codigo} ${nomeCurto(p.cliente.nome)}` : "");
  const prazo = "prazo" in aj ? aj.prazo : p.prazo;
  const prio = aj.prioridade || p.prioridade;
  const resps = "responsaveis" in aj ? aj.responsaveis : ((p.pessoas && p.pessoas.length) ? p.pessoas : (p.pessoa ? [p.pessoa] : (B.pessoa ? [B.pessoa] : [])));
  const pessoal = "pessoal" in aj ? aj.pessoal : !!p.pessoal;
  $("#bt-meu").classList.toggle("ativo", pessoal);
  const duvidaCliente = !!(p.candidatos && p.candidatos.length && !("cliente" in aj));
  const faltaCliente = !cli && !("cliente" in aj) && !p.e_informacao && !pessoal;
  const menuPrio = ev => menu(ev.clientX, ev.clientY, Object.keys(PRIO).map(k => ({ rotulo: PRIO[k], acao: () => { aj.prioridade = k; renderFichas(); } })));
  const menuResp = async ev => {
    const eq = await equipe();
    menu(ev.clientX, ev.clientY, [...eq.map(n => ({ rotulo: (resps.includes(n) ? "✓ " : "") + n, acao: () => { aj.responsaveis = resps.includes(n) ? resps.filter(x => x !== n) : [...resps, n]; renderFichas(); } })), "sep", { rotulo: "Ninguém", acao: () => { aj.responsaveis = []; renderFichas(); } }]);
  };
  const ficha = (t, cls, acao) => caixa.append(el("span", { class: "ficha " + cls, text: t, onclick: ev => { ev.stopPropagation(); acao && acao(ev); } }));
  if (!B.fichasAbertas) {
    const linha = el("div", { class: "resumo-linha" });
    const parte = (t, acao, title) => { linha.append(el("span", { class: "parte", text: t, title: title || "clique para trocar", onclick: ev => { ev.stopPropagation(); acao(ev); } })); linha.append(el("span", { class: "sep", text: "·" })); };
    if (cli) parte(nomeCli, menuCliente);
    parte(p.tipo_nome || "tipo: outro", () => { B.fichasAbertas = true; renderFichas(); });
    parte(prazo ? `vence ${fmtPrazo(prazo)}` : "sem prazo", ev => menuPrazo(ev, v => { aj.prazo = v; renderFichas(); }));
    if (prio && prio !== "normal") parte(PRIO[prio] || prio, menuPrio);
    parte(`para ${resps.length ? resps.join(", ") : "ninguém"}`, menuResp);
    if (p.hora) parte(`🔔 às ${p.hora}`, () => { B.fichasAbertas = true; renderFichas(); });
    if (p.recorrencia) parte("repete", () => { B.fichasAbertas = true; renderFichas(); });
    if (linha.lastChild && linha.lastChild.className === "sep") linha.lastChild.remove();
    linha.append(el("span", { class: "ajustar", text: "ajustar", onclick: ev => { ev.stopPropagation(); B.fichasAbertas = true; renderFichas(); } }));
    caixa.append(linha);
  } else {
    if (cli || "cliente" in aj) ficha(nomeCli, duvidaCliente ? "duvida" : "boa", menuCliente);
    ficha(p.tipo_nome || "tipo: outro", "");
    ficha(prazo ? `vence ${fmtPrazo(prazo)}` : "sem prazo", "", ev => menuPrazo(ev, v => { aj.prazo = v; renderFichas(); }));
    ficha(`● ${PRIO[prio] || prio}`, "", menuPrio);
    ficha(`para ${resps.length ? resps.join(", ") : "ninguém"}`, "", menuResp);
    if (p.recorrencia) ficha("repete", "");
    if (p.avisar) ficha("🔔 avisar", "boa");
    if (p.hora) ficha(`🔔 às ${p.hora}`, "boa");
    if (p.rodizio) ficha("rodízio", "");
  }
  // as dúvidas aparecem sempre, resumido ou não
  if (duvidaCliente) ficha(`cliente: ${nomeCli}? — ver outros`, "duvida", menuCliente);
  if (faltaCliente) ficha("cliente? — clique", "falta", menuCliente);
  if (p.outras && p.outras.length) ficha(`+${p.outras.length} tarefa(s)`, "");
  if (p.duplicatas && p.duplicatas.length && !aj.ignorar_dup) ficha(`já existe ${p.duplicatas[0].chave}`, "dup", () => { aj.ignorar_dup = true; renderFichas(); aviso("vai criar mesmo assim"); });
  if (pessoal) ficha("pessoal · só você vê", "boa", () => { aj.pessoal = false; renderFichas(); });
}
function menuCliente(ev) {
  const p = B.previa, aj = B.ajustes;
  const escolher = c => { aj.cliente = c.codigo; aj.cliente_nome = `${c.codigo} ${nomeCurto(c.nome)}`; renderFichas(); };
  menu(ev.clientX, ev.clientY, [
    ...[p.cliente, ...(p.candidatos || [])].filter(Boolean).map(c => ({ rotulo: `${c.codigo} — ${c.nome.slice(0, 40)}`, acao: () => escolher(c) })),
    "sep", { rotulo: "Procurar…", acao: () => { const q = prompt("Código ou nome do cliente:"); if (q) api("GET", `/api/clientes?q=${encodeURIComponent(q)}`).then(r => { if (r[0]) escolher(r[0]); else aviso("não achei"); }); } },
    { rotulo: "Sem cliente", acao: () => { aj.cliente = ""; aj.cliente_nome = ""; renderFichas(); } }]);
}
function menuPrazo(ev, definir) {
  const hoje = new Date();
  const mais = n => { const d = new Date(hoje); d.setDate(d.getDate() + n); return isoDe(d); };
  const sexta = mais((5 - hoje.getDay() + 7) % 7);
  menu(ev.clientX, ev.clientY, [{ rotulo: "Hoje", acao: () => definir(isoDe(hoje)) }, { rotulo: "Amanhã", acao: () => definir(mais(1)) }, { rotulo: `Sexta (${fmtPrazo(sexta)})`, acao: () => definir(sexta) }, { rotulo: "Em uma semana", acao: () => definir(mais(7)) }, "sep", { rotulo: "Sem prazo", acao: () => definir(null) }]);
}
async function listaPadrao() {
  if (B.listaPadrao) return B.listaPadrao;
  try { const tudo = await api("GET", "/api/tudo"); B.listaPadrao = (tudo.listas[0] || {}).id || ""; } catch (e) { }
  return B.listaPadrao;
}
$("#bt-meu").onclick = () => { B.ajustes.pessoal = !("pessoal" in B.ajustes ? B.ajustes.pessoal : !!(B.previa && B.previa.pessoal)); renderFichas(); $("#linha").focus(); };
async function criar() {
  const texto = $("#linha").value.trim(); if (!texto) return;
  const ajustes = { ...B.ajustes, triar: true };
  // o que o app adivinhou e você não mexeu vai junto (pessoal, hora)
  if (B.previa && B.previa.pessoal && !("pessoal" in ajustes)) ajustes.pessoal = true;
  if (B.previa && B.previa.hora && !("lembrete_hora" in ajustes)) ajustes.lembrete_hora = B.previa.hora;
  const lista = await listaPadrao(); if (!lista) return;
  $("#linha").value = ""; $("#fichas").innerHTML = ""; B.previa = null; B.ajustes = {}; B.fichasAbertas = false;
  try {
    const t = await api("POST", "/api/tarefas", { lista, texto, ajustes });
    aviso(`${t.criadas.map(x => x.chave).join(", ")} criada(s)`); atualizarResumo();
  } catch (e) { $("#linha").value = texto; }
}

/* ---- colar uma conversa inteira: a mesma prévia do app, resumida */
function modoColar(ligar) {
  $("#entrada-linha").classList.toggle("oculto", ligar); $("#entrada-colar").classList.toggle("oculto", !ligar);
  $("#pedidos").classList.toggle("oculto", !ligar); $("#acoes-colar").classList.toggle("oculto", !ligar); $("#hoje").classList.toggle("oculto", ligar);
  $("#dica-texto").textContent = ligar ? "Ctrl+Enter cria · Esc volta" : "Enter cria · Ctrl+V com conversa cola · Esc recolhe · Ctrl+Shift+D abre de qualquer programa";
  if (ligar) { $("#colado").focus(); }
  else { $("#fichas").innerHTML = ""; $("#pedidos").innerHTML = ""; B.colada = null; }
}
$("#bt-colar").onclick = () => modoColar($("#entrada-colar").classList.contains("oculto"));
$("#bt-cancelar-colar").onclick = () => modoColar(false);
let timerColar = null;
$("#colado").addEventListener("input", () => { clearTimeout(timerColar); timerColar = setTimeout(previaColar, 400); });
$("#colado").addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); criarColado(); } });
$("#bt-criar-colar").onclick = criarColado;
async function previaColar() {
  const texto = $("#colado").value.trim(); const ped = $("#pedidos"); ped.innerHTML = ""; $("#fichas").innerHTML = "";
  if (!texto) { B.colada = null; return; }
  try { B.colada = await api("POST", "/api/colar", { texto }); } catch (e) { return; }
  const c = B.colada; c.incluir = c.pedidos.map(() => true); c.ajustes = {};
  const f = $("#fichas");
  f.append(el("span", { class: "ficha " + (c.cliente ? "boa" : "falta"), text: c.cliente ? `${c.cliente.codigo} ${nomeCurto(c.cliente.nome)}` : "cliente? — clique",
    onclick: ev => { ev.stopPropagation(); menu(ev.clientX, ev.clientY, [...[c.cliente, ...(c.candidatos || [])].filter(Boolean).map(x => ({ rotulo: `${x.codigo} — ${x.nome.slice(0, 40)}`, acao: () => { c.ajustes.cliente = x.codigo; aviso("cliente: " + x.codigo); } })),
      "sep", { rotulo: "Procurar…", acao: () => { const q = prompt("Código ou nome:"); if (q) api("GET", `/api/clientes?q=${encodeURIComponent(q)}`).then(r => { if (r[0]) { c.ajustes.cliente = r[0].codigo; aviso("cliente: " + r[0].codigo); } }); } }]); } }));
  f.append(el("span", { class: "ficha " + (c.status_tipo === "aguardando" ? "duvida" : ""), text: ({ aberto: "a fazer", aguardando: "aguardando cliente", feito: "concluída" })[c.status_tipo] || c.status_tipo, title: c.status_motivo || "" }));
  if (c.turnos && c.turnos.length) f.append(el("span", { class: "ficha", text: `${c.turnos.filter(t => t.lado === "cliente").length} do cliente · ${c.turnos.filter(t => t.lado === "equipe").length} sua(s)` }));
  c.pedidos.forEach((p, i) => {
    const chk = el("input", { type: "checkbox", checked: true, onchange: ev => c.incluir[i] = ev.target.checked });
    ped.append(el("div", { class: "pedido" }, [chk, el("div", {}, [el("div", { class: "t", text: p.titulo }), el("div", { class: "sub", text: [p.tipo_nome, p.prazo ? "vence " + fmtPrazo(p.prazo) : "", p.pessoa ? "para " + p.pessoa : "", (p.checklist || []).length ? `${p.checklist.length} itens no checklist` : ""].filter(Boolean).join(" · ") })])]));
  });
}
async function criarColado() {
  const c = B.colada; if (!c) return;
  const texto = $("#colado").value.trim();
  const lista = await listaPadrao(); if (!lista) return;
  const pedidos = c.pedidos.filter((p, i) => c.incluir[i]).map(p => ({ titulo: p.titulo, texto: p.texto, checklist: (p.checklist || []).map(x => ({ texto: x.texto, feito: !!x.feito })), status_tipo: p.status_tipo || "aberto", prazo: p.prazo || null, responsavel: p.pessoa || "", prioridade: p.prioridade_conversa || "", tipo: p.tipo || "", extraidos: p.extraidos || {} }));
  if (!pedidos.length) { aviso("marque pelo menos um pedido"); return; }
  const ajustes = { pedidos, triar: true }; if (c.ajustes.cliente) ajustes.cliente = c.ajustes.cliente;
  try {
    const t = await api("POST", "/api/tarefas", { lista, texto, modo: "colar", ajustes });
    aviso(`${t.criadas.map(x => x.chave).join(", ")} criada(s)`); modoColar(false); limpar(); atualizarResumo();
  } catch (e) { }
}

/* ---- o dia: atrasadas, de hoje e lembretes, por prioridade; tocar abre os detalhes */
function renderHoje() {
  const caixa = $("#hoje"); caixa.innerHTML = "";
  const r = B.resumo; if (!r) return;
  const ordenar = lista => lista.slice().sort((a, b) => (PRIO_ORDEM[a.prioridade] ?? 2) - (PRIO_ORDEM[b.prioridade] ?? 2) || (a.prazo || "9999").localeCompare(b.prazo || "9999") || (a.lembrete_hora || "").localeCompare(b.lembrete_hora || ""));
  // o que é seu (espaço pessoal) vem primeiro, com tique para riscar ali mesmo; o resto é do departamento.
  // "Amanhã" saiu (cabe no app); entrou "Lembretes" — o que tem lembrete para hoje e não está nas outras seções
  const vistos = new Set();
  const semRepetir = lista => (lista || []).filter(t => !vistos.has(t.id) && vistos.add(t.id));
  const todas = [...(r.atrasadas || []), ...(r.hoje || []), ...(r.lembretes || [])];
  const meus = ordenar(semRepetir(todas.filter(t => t.pessoal)));
  const dep = x => semRepetir((x || []).filter(t => !t.pessoal));
  const secoes = [["Meus (só você vê)", meus, true], ["Atrasadas", ordenar(dep(r.atrasadas)), false], ["Hoje", ordenar(dep(r.hoje)), false], ["Lembretes", ordenar(dep(r.lembretes)), false]];
  let algo = false;
  for (const [rot, itens, pessoal] of secoes) {
    if (!itens.length) continue; algo = true;
    caixa.append(el("div", { class: "secao" }, [el("span", { text: rot }), el("span", { text: String(itens.length) })]));
    for (const t of itens) {
      const primeira = pessoal
        ? el("span", { class: "tique", title: "Feito! (risca aqui mesmo)", onclick: async ev => { ev.stopPropagation(); try { await api("POST", `/api/tarefas/${t.id}/concluir`, {}); aviso(`${t.titulo.slice(0, 40)} ✓`); atualizarResumo(); } catch (e) { } } })
        : el("span", { class: "prio", style: `background:${PRIO_COR[t.prioridade] || "#B4B2A9"}`, title: PRIO[t.prioridade] || "" });
      const quando = rot === "Lembretes" ? [t.lembrete_hora ? `às ${t.lembrete_hora}` : "lembrete", t.prazo ? `· vence ${fmtPrazo(t.prazo)}` : ""].filter(Boolean).join(" ")
        : [fmtPrazo(t.prazo), t.lembrete_hora ? `às ${t.lembrete_hora}` : ""].filter(Boolean).join(" ");
      const motivo = t.lembrete_motivo ? `🔔 ${t.lembrete_motivo}` : "";
      const sub = pessoal ? [motivo, t.rodizio && t.rodizio.length ? "rodízio: sua vez" : "", (t.responsaveis || []).length > 1 ? t.responsaveis.join(", ") : ""].filter(Boolean).join(" · ")
        : [motivo, t.cliente ? `${t.cliente} ${nomeCurto(t.cliente_nome)}`.trim() : "", (t.responsaveis || []).join(", "), t.rodizio && t.rodizio.length ? "rodízio: sua vez" : ""].filter(Boolean).join(" · ");
      const linha = el("div", { class: "tarefa" + (pessoal ? " pessoal" : ""), onclick: () => abrirDetalhe(t) }, [
        primeira,
        el("div", {}, [el("div", { class: "tit", text: `${pessoal ? "" : (t.chave || "") + " "}${t.titulo}` }), sub ? el("div", { class: "sub", text: sub }) : null]),
        el("span", { class: "prazo " + (diasAte(t.prazo) < 0 ? "atrasado" : diasAte(t.prazo) === 0 ? "hoje" : ""), text: quando })]);
      caixa.append(linha);
      if (B.aberto === t.id) caixa.append(el("div", { class: "detalhe", id: "det-" + t.id, text: "…" }));
    }
  }
  if (!algo) caixa.append(el("div", { class: "vazio", text: "Nada atrasado nem para hoje. Escreva acima para registrar uma demanda." }));
  if (B.aberto) carregarDetalhe(B.aberto);
}
function abrirDetalhe(t) { B.aberto = B.aberto === t.id ? "" : t.id; renderHoje(); }
async function carregarDetalhe(id) {
  const caixa = $("#det-" + id); if (!caixa) return;
  let t; try { t = await api("GET", `/api/tarefas/${id}`); } catch (e) { caixa.textContent = "não consegui abrir"; return; }
  caixa.innerHTML = "";
  const feitos = (t.checklist || []).filter(c => c.feito).length;
  caixa.append(el("div", { class: "linha" }, [
    el("span", {}, [el("b", { text: PRIO[t.prioridade] || "" })]),
    t.prazo ? el("span", {}, ["prazo ", el("b", { text: fmtPrazo(t.prazo) })]) : null,
    t.lembrete ? el("span", {}, ["lembrete ", el("b", { text: fmtPrazo(t.lembrete) + (t.lembrete_hora ? " às " + t.lembrete_hora : "") + (t.lembrete_motivo ? " — " + t.lembrete_motivo : "") })]) : null,
    t.rodizio && t.rodizio.length ? el("span", {}, ["rodízio ", el("b", { text: t.rodizio.join(" → ") })]) : null,
    t.cliente ? el("span", {}, ["cliente ", el("b", { text: `${t.cliente} ${nomeCurto(t.cliente_nome)}` })]) : null,
    (t.responsaveis || []).length ? el("span", {}, ["para ", el("b", { text: t.responsaveis.join(", ") })]) : null,
    el("span", {}, ["lista ", el("b", { text: t.lista_nome || "" })])]));
  if ((t.checklist || []).length) {
    caixa.append(el("div", { class: "linha" }, [el("span", {}, [el("b", { text: `Checklist ${feitos}/${t.checklist.length}` })])]));
    for (const c of t.checklist) caixa.append(el("div", { class: "check" + (c.feito ? " feito" : "") }, [el("span", { class: "cx" }), el("span", { text: c.texto })]));
  }
  if (t.descricao) caixa.append(el("div", { class: "desc", text: t.descricao.slice(0, 400) }));
  if ((t.comentarios || []).length) caixa.append(el("div", { class: "linha" }, [el("span", { text: `💬 ${t.comentarios.length} comentário(s) — o último: “${t.comentarios[t.comentarios.length - 1].texto.slice(0, 80)}”` })]));
  // os estados da lista como botões (Fazendo / Aguardando cliente / Concluída…) e o lembrete de cobrar
  if ((t.status_lista || []).length) {
    const estados = el("div", { class: "estados" });
    for (const s of t.status_lista) {
      const atual = s.id === t.status;
      estados.append(el("button", { class: (atual ? "atual " : "") + (s.tipo || ""), text: (atual ? "✓ " : "") + s.nome, disabled: atual, title: atual ? "estado atual" : `mudar para ${s.nome}`,
        onclick: ev => { ev.stopPropagation(); mudarEstado(t, s); } }));
    }
    caixa.append(estados);
  }
  caixa.append(el("div", { class: "acoes-d" }, [
    el("button", { text: "🔔 cobrar o cliente ▾", title: "Lembrete de perguntar se o cliente respondeu", onclick: ev => { ev.stopPropagation(); menuCobrar(ev, t); } }),
    el("button", { class: "primario", text: "⤢ abrir no app", onclick: ev => { ev.stopPropagation(); abrirTudo(t.id); } }),
    el("button", { text: "fechar", onclick: ev => { ev.stopPropagation(); B.aberto = ""; renderHoje(); } })]));
}
async function mudarEstado(t, s) {
  try { await api("PATCH", `/api/tarefas/${t.id}`, { status: s.id }); } catch (e) { return; }
  aviso(`${t.chave || t.titulo.slice(0, 30)} → ${s.nome}`);
  if (s.tipo === "feito") B.aberto = "";
  if (s.tipo === "aguardando") perguntarCobrar(t);
  atualizarResumo();
}
/* depois de "Aguardando cliente": lembrar de cobrar? */
function perguntarCobrar(t) {
  const p = $("#pergunta"); p.innerHTML = ""; p.classList.remove("oculto");
  const escolher = async quando => { p.classList.add("oculto"); await lembrarDeCobrar(t, quando); };
  p.append(el("b", { text: `${t.chave || ""} aguardando o cliente.` }), el("span", { text: "Lembrar de cobrar?" }),
    el("button", { text: "amanhã", onclick: () => escolher({ dias_uteis: 1 }) }),
    el("button", { text: "em 2 dias úteis", onclick: () => escolher({ dias_uteis: 2 }) }),
    el("button", { text: "sexta", onclick: () => escolher({ data: proximaSexta() }) }),
    el("span", { class: "x", text: "×", title: "não precisa", onclick: () => p.classList.add("oculto") }));
}
function proximaSexta() { const hoje = new Date(); const d = new Date(hoje); d.setDate(d.getDate() + (((5 - hoje.getDay() + 7) % 7) || 7)); return isoDe(d); }
async function lembrarDeCobrar(t, quando) {
  try {
    const r = await api("POST", `/api/tarefas/${t.id}/adiar`, { ...quando, motivo: "cobrar o cliente" });
    aviso(`cobrar o cliente ${fmtPrazo(r.lembrete)}${r.lembrete_hora ? " às " + r.lembrete_hora : ""} — ${t.chave || ""}`);
    atualizarResumo();
  } catch (e) { }
}
function menuCobrar(ev, t) {
  const sexta = proximaSexta();
  menu(ev.clientX, ev.clientY, [{ rotulo: "Amanhã", acao: () => lembrarDeCobrar(t, { dias_uteis: 1 }) }, { rotulo: "Em 2 dias úteis", acao: () => lembrarDeCobrar(t, { dias_uteis: 2 }) },
    { rotulo: `Sexta (${fmtPrazo(sexta)})`, acao: () => lembrarDeCobrar(t, { data: sexta }) }, { rotulo: "Em uma semana", acao: () => lembrarDeCobrar(t, { dias_uteis: 5 }) }]);
}

/* ---- o número na bolha, a lista do dia e os avisos que aparecem acima da barrinha */
function mostrarBalao(a) {
  const b = $("#balao"); b.innerHTML = "";
  const TIPO = { resumo: "seu dia", amanha: "amanhã", lembrete: "lembrete", urgente: "urgente hoje" };
  const abrirAviso = () => { esconderBalao(); if (a.tarefa) B.aberto = a.tarefa; abrir(); };
  b.append(el("span", { class: "tipo", text: TIPO[a.tipo] || a.tipo }), el("span", { class: "texto", text: `${a.titulo}: ${a.texto}`.slice(0, 200), onclick: abrirAviso }),
    el("span", { class: "fechar", text: "×", onclick: ev => { ev.stopPropagation(); esconderBalao(); } }));
  // lembrete e urgente de uma tarefa trazem "me lembra depois"
  const comAcoes = !!a.tarefa && (a.tipo === "lembrete" || a.tipo === "urgente");
  if (comAcoes) {
    const adiar = async corpo => { try { const r = await api("POST", `/api/tarefas/${a.tarefa}/adiar`, corpo); aviso(`de novo ${fmtPrazo(r.lembrete)}${r.lembrete_hora ? " às " + r.lembrete_hora : ""}`); } catch (e) { } esconderBalao(); };
    b.append(el("div", { class: "balao-acoes" }, [
      el("button", { text: "+10 min", onclick: () => adiar({ minutos: 10 }) }),
      el("button", { text: "+1 h", onclick: () => adiar({ minutos: 60 }) }),
      el("button", { text: "amanhã", onclick: () => adiar({ dias_uteis: 1 }) }),
      el("button", { class: "primario", text: "abrir", onclick: abrirAviso })]));
  }
  b.classList.remove("oculto"); document.body.classList.add("com-balao");
  // a janela cresce para cima e para a esquerda, com a barrinha parada onde estava
  py("redimensionar", 340, 60 + 12 + Math.max(60, Math.min(150, 40 + Math.ceil(a.texto.length / 42) * 17)) + (comAcoes ? 36 : 0));
  clearTimeout(B.balaoTimer); B.balaoTimer = setTimeout(esconderBalao, comAcoes ? 25000 : 15000);
}
function esconderBalao() {
  $("#balao").classList.add("oculto"); document.body.classList.remove("com-balao");
  if (!B.aberta) py("recolher");
}
async function atualizarResumo() {
  let r; try { r = await api("GET", `/api/avisos?desde=${encodeURIComponent(B.desde)}`); } catch (e) { $("#badge").textContent = ""; return; }
  const res = r.resumo || {}; B.resumo = res;
  const hoje = (res.hoje || []).length, atras = (res.atrasadas || []).length, lemb = (res.lembretes || []).filter(t => !(res.hoje || []).some(x => x.id === t.id) && !(res.atrasadas || []).some(x => x.id === t.id)).length;
  $("#badge").textContent = (hoje + atras + lemb) ? String(hoje + atras + lemb) : "";
  $("#bolha").classList.toggle("alerta", atras > 0 || (res.hoje || []).some(t => t.prioridade === "urgente"));
  // a barrinha diz o que importa ("2 hoje · 1 atrasada"), não o atalho
  const partes = [atras ? `${atras} atrasada${atras > 1 ? "s" : ""}` : "", hoje ? `${hoje} hoje` : "", lemb ? `${lemb} lembrete${lemb > 1 ? "s" : ""}` : ""].filter(Boolean);
  $("#sub").textContent = partes.join(" · ") || "nada para hoje";
  $("#resumo").textContent = [...partes, (res.amanha || []).length ? `${res.amanha.length} amanhã` : ""].filter(Boolean).join(" · ") || "nada para hoje";
  if (B.aberta) renderHoje();
  const novos = (r.pendentes || []).filter(a => B.desde && a.quando > B.desde);
  if (novos.length && !B.aberta) mostrarBalao(novos[novos.length - 1]);
  if ((r.pendentes || []).length) B.desde = r.pendentes[r.pendentes.length - 1].quando; else if (!B.desde) B.desde = new Date().toISOString().slice(0, 19);
}
atualizarResumo(); setInterval(atualizarResumo, 30000);

/* ---- ⚙: abrir com o Windows, esconder, trocar o nome (era a linha de links do rodapé) */
$("#bt-config").onclick = async ev => {
  ev.stopPropagation();
  const ja = nativo() ? await py("inicio_instalado") : null;
  const itens = [];
  if (nativo()) itens.push({ rotulo: ja ? "✓ abre com o Windows (desfazer)" : "abrir com o Windows", acao: async () => {
    const ok = ja ? await py("desinstalar_inicio") : await py("instalar_inicio");
    aviso(ok ? (ja ? "não abre mais com o Windows" : "a bolha vai abrir junto com o Windows") : "não consegui — veja o bolha.log");
  } });
  itens.push({ rotulo: "esconder a bolha (Ctrl+Shift+D traz de volta)", acao: async () => { if (nativo()) await py("esconder"); else aviso("na janela nativa a bolha some; Ctrl+Shift+D traz de volta"); } });
  itens.push({ rotulo: "abrir o app completo", acao: () => abrirTudo("") });
  itens.push("sep", { rotulo: `trocar meu nome (${B.pessoa || "sem nome"})`, acao: () => { $("#nome").classList.remove("oculto"); $("#nome-input").value = B.pessoa; $("#nome-input").focus(); } });
  menu(ev.clientX - 180, ev.clientY + 14, itens);
};
