"""Modo demonstração: dados fictícios que nascem na subida e zeram todo dia.

`python servidor.py --demo` (ou a variável de ambiente `GESTOR_DEMO=1`, que é como o Render liga)
sobe o app numa pasta temporária com a Equipe e as tarefas abaixo, e um relógio recria tudo a cada
24 h. É o que está publicado em https://gestor-demandas.onrender.com.

Tudo aqui é inventado: as empresas são as cinco do `clientes.SEMENTE` (101–105), a Equipe é Ana
Souza, Bruno Martins e Carla Dias, e Daniel Rocha é o contato de um dos clientes. Os prazos são
relativos a hoje, para a demonstração sempre ter uma atrasada, uma para hoje, uma para amanhã e uma
para a semana que vem, seja quando for aberta.
"""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from . import calendario

EQUIPE = ["Ana Souza", "Bruno Martins", "Carla Dias"]
ANA, BRUNO, CARLA = EQUIPE
ZERA_A_CADA = 24 * 60 * 60          # segundos entre um zeramento e outro
LIMITE_CORPO = 64 * 1024            # bytes por pedido (413 acima disso)
LIMITE_TAREFAS = 500                # tarefas ao todo (429 quando passar)
LIMITE_TEXTO = 2000                 # caracteres de título, descrição, comentário…
LIMITE_MENSAGEM = 20000             # caracteres de uma conversa colada
LIMITE_PESSOAS = 50                 # espaços pessoais (um por nome digitado)

FAIXA = "Demonstração pública: os dados são fictícios e zeram todo dia. Qualquer um que abrir vê o que você escrever."


def limpar_pasta(pasta: Path) -> None:
    """Apaga o que houver na pasta de dados da demonstração e a deixa vazia, pronta para nascer de novo."""
    pasta = Path(pasta)
    if pasta.exists():
        shutil.rmtree(pasta, ignore_errors=True)
    pasta.mkdir(parents=True, exist_ok=True)


def cortar_textos(corpo, limite: int = LIMITE_TEXTO, limite_mensagem: int = LIMITE_MENSAGEM):
    """Corta, no lugar, as strings do corpo de um pedido: `texto` (a conversa colada) no limite maior,
    o resto (título, descrição, comentário, nome…) no menor. Devolve o próprio corpo."""
    if isinstance(corpo, dict):
        for chave, valor in corpo.items():
            if isinstance(valor, str):
                teto = limite_mensagem if chave == "texto" else limite
                if len(valor) > teto:
                    corpo[chave] = valor[:teto]
            else:
                cortar_textos(valor, limite, limite_mensagem)
    elif isinstance(corpo, list):
        for i, valor in enumerate(corpo):
            if isinstance(valor, str):
                if len(valor) > limite:
                    corpo[i] = valor[:limite]
            else:
                cortar_textos(valor, limite, limite_mensagem)
    return corpo


def contar_tarefas(esc) -> int:
    """Tarefas de todos os departamentos e de todos os espaços pessoais já abertos."""
    total = sum(len(d.area.tarefas) for d in esc.departamentos if d.acessivel)
    total += sum(len(a.tarefas) for a in list(esc._areas_pessoais.values()))
    return total


def semear(esc) -> dict:
    """Preenche a área padrão do escritório com a demonstração. Devolve contagens, para o log."""
    a = esc.area_padrao()
    hoje = dt.date.today()

    def dia(n: int) -> str:
        return (hoje + dt.timedelta(days=n)).isoformat()

    def momento(dias_atras: int, hora: str = "09:15") -> str:
        return f"{(hoje - dt.timedelta(days=dias_atras)).isoformat()}T{hora}:00"

    a.editar_equipe(EQUIPE)
    por_nome = {l["nome"]: l["id"] for l in a.listas}
    caixa = por_nome.get("Caixa de entrada", a.listas[0]["id"])
    clientes = por_nome.get("Demandas de clientes", a.listas[0]["id"])
    internas = por_nome.get("Pendências internas", a.listas[0]["id"])

    def criar(lista: str, texto: str, pessoa: str, criada_ha: int = 0, hora: str = "09:15", **ajustes) -> dict:
        t = a.criar_tarefa(lista, texto, pessoa, ajustes, pessoas=a.pessoas())
        if criada_ha:
            t["criada"] = momento(criada_ha, hora)
            a._gravar_tarefa(t, snapshot=False, subir=False)
        return t

    # ---- Demandas de clientes
    atrasada = criar(clientes, "101 pediu a carta de faturamento dos últimos 12 meses", ANA, criada_ha=5,
                     titulo="Carta de faturamento (12 meses)", cliente="101", tipo="carta_faturamento",
                     prazo=dia(-2), prioridade="alta", responsaveis=[ANA], origem="email",
                     descricao="O banco pediu a carta para renovar o limite. Período: últimos 12 meses, assinada pelo contador.")
    hoje_t = criar(clientes, "padaria pediu a cnd federal e a certidão estadual, urgente", BRUNO, criada_ha=1, hora="14:02",
                   titulo="CND federal e estadual", cliente="104", tipo="cnd", prazo=dia(0), prioridade="urgente",
                   responsaveis=[BRUNO], origem="whatsapp",
                   checklist=[{"texto": "CND federal", "feito": True}, {"texto": "CND estadual", "feito": False},
                              {"texto": "Enviar ao cliente", "feito": False}],
                   descricao="Precisa das duas certidões para uma licitação. Entrega até o fim do dia.")
    criar(clientes, "balancete de setembro da 102", CARLA, criada_ha=2,
          titulo="Balancete de setembro", cliente="102", tipo="balancete", prazo=dia(1), prioridade="normal",
          responsaveis=[CARLA], campos={"competencia": "09/2026"})
    nota = criar(clientes, "emitir a nota fiscal de serviço da 105", ANA, criada_ha=1, hora="16:30",
                 titulo="Emitir nota fiscal de serviço", cliente="105", tipo="nota_fiscal", prazo=dia(7),
                 prioridade="normal", responsaveis=[ANA], origem="email",
                 descricao="Tomador: Comércio Modelo. Valor: R$ 2.350,00. Descrição: consultoria de outubro.")
    aguardando = criar(clientes, "retificar a DCTFWeb de agosto da 103", BRUNO, criada_ha=8,
                       titulo="Retificar a DCTFWeb de agosto", cliente="103", tipo="dctfweb", prazo=dia(3),
                       prioridade="alta", responsaveis=[BRUNO], status_tipo="aguardando", origem="telefone",
                       descricao="Falta o extrato do eSocial do mês para fechar a retificadora. Pedido ao cliente em "
                                 + (hoje - dt.timedelta(days=6)).strftime("%d/%m") + ".")
    aguardando["aguardando_desde"] = dia(-6)
    a._gravar_tarefa(aguardando, snapshot=False, subir=False)
    criar(clientes, "enviar a alíquota do Simples da 101 todo dia 20", ANA, criada_ha=20,
          titulo="Enviar a alíquota do Simples", cliente="101", tipo="aliquota_simples",
          prazo=calendario.proxima_mensal(20, "antes", hoje).isoformat(), prioridade="normal",
          responsaveis=[ANA], recorrencia="mensal:20:antes",
          descricao="Toda competência: pegar a alíquota efetiva no PGDAS-D e mandar por e-mail. Repete todo mês.")
    criar(clientes, "parcelamento dos débitos da 102", CARLA, criada_ha=3,
          titulo="Simular o parcelamento dos débitos", cliente="102", tipo="parcelamento", prazo=dia(10),
          prioridade="baixa", responsaveis=[CARLA])
    feita = criar(clientes, "segunda via da guia do DAS de setembro da 104", BRUNO, criada_ha=2,
                  titulo="2ª via da guia do DAS de setembro", cliente="104", tipo="segunda_via_guia", prazo=dia(-1),
                  prioridade="normal", responsaveis=[BRUNO], campos={"competencia": "09/2026"})
    a.concluir(feita["id"], BRUNO)
    feita["concluida_em"] = feita["atualizada"] = momento(1, "16:40")
    for item in feita.get("checklist", []):
        item["feito"] = True
    a._gravar_tarefa(feita, snapshot=False, subir=False)

    # ---- Pendências internas
    criar(internas, "atualizar o cadastro de clientes no sistema", CARLA, criada_ha=1,
          titulo="Atualizar o cadastro de clientes no sistema", tipo="cadastro", prazo=dia(2), prioridade="normal",
          responsaveis=[CARLA],
          checklist=[{"texto": "Conferir e-mails e telefones", "feito": True},
                     {"texto": "Marcar quem mudou de regime em 2026", "feito": False},
                     {"texto": "Avisar a equipe do que mudou", "feito": False}])
    criar(internas, "reunião de fechamento do mês com a equipe", ANA, criada_ha=4,
          titulo="Reunião de fechamento do mês", tipo="reuniao", prazo=dia(4), prioridade="normal",
          responsaveis=[ANA, BRUNO, CARLA],
          descricao="Sala de reunião, 15h. Pauta: pendências por cliente, o que atrasou e por quê.")
    criar(internas, "renovar o certificado digital do escritório", BRUNO, criada_ha=6,
          titulo="Renovar o certificado digital do escritório", tipo="certificado_digital", prazo=dia(14),
          prioridade="baixa", responsaveis=[BRUNO])

    # ---- Caixa de entrada (o que chegou e ninguém triou ainda)
    criar(caixa, "Padaria Central mandou perguntando sobre o pró-labore", ANA, hora="08:40",
          titulo="Dúvida sobre o pró-labore de outubro", cliente="104", tipo="pro_labore", prazo=dia(1),
          prioridade="normal", responsaveis=[], origem="whatsapp",
          descricao="[" + hoje.strftime("%d/%m/%Y") + ", 08:31] Daniel Rocha: Bom dia! O pró-labore de outubro vai "
                    "mudar com o novo sócio? Preciso saber até amanhã para fechar a folha.")
    criar(caixa, "clínica horizonte pediu o XML das notas de setembro", ANA, hora="08:55",
          titulo="XML das notas de setembro", cliente="105", tipo="arquivos_xml", prazo=dia(2), prioridade="normal",
          responsaveis=[], origem="email", campos={"competencia": "09/2026"})

    # ---- comentários, um anexo (link) e um modelo de lista
    a.comentar(hoje_t["id"], f"@{BRUNO.split()[0]} a CND federal já saiu; a estadual está em processamento no portal.", ANA)
    a.comentar(aguardando["id"], "Liguei para o Daniel Rocha (contato do cliente): ele manda o extrato do eSocial até quinta.", BRUNO)
    a.anexar(nota["id"], "link", "Portal da NFS-e (exemplo)", "https://example.com/portal-nfse", "", ANA)
    a.salvar_modelo(internas, "Rotina de fechamento do mês")

    return {"equipe": len(a.equipe), "tarefas": len(a.tarefas), "listas": len(a.listas), "modelos": len(a.modelos),
            "comentarios": sum(len(t.get("comentarios", [])) for t in a.tarefas.values()),
            "anexos": sum(len(t.get("anexos", [])) for t in a.tarefas.values()),
            "atrasada": atrasada["chave"], "concluida": feita["chave"]}
