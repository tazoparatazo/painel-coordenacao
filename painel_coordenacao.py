# =============================================================
# PAINEL DA COORDENACAO  |  100% Asana (substitui a planilha COORDENACAO)
# Roda no Google Colab (ou Python 3.9+). Gera painel_coordenacao.html
# =============================================================

import os, re, json, time, unicodedata, datetime as dt
from collections import Counter
from zoneinfo import ZoneInfo
import requests

# ------------------ CONFIGURACAO ------------------
PROJETOS_CLIENTES = {}   # preenchido pelo segredo PAINEL_CLIENTES no GitHub
# No GitHub, a lista de clientes vem do segredo PAINEL_CLIENTES (assim os nomes nao ficam no codigo publico)
if os.environ.get("PAINEL_CLIENTES"):
    PROJETOS_CLIENTES = json.loads(os.environ["PAINEL_CLIENTES"])
CLIENTES_MOSTRAR = list(PROJETOS_CLIENTES)            # escolha quais clientes aparecem
BLOCOS = ["geral", "tarefas", "visitas", "frentes", "qualidade"]   # abas visiveis

# Regras
DIAS_RISCO = 3              # vence em ate X dias = em risco
ATRASO_ANTIGO_DIAS = 30     # atraso maior que X dias = atraso antigo (fora dos alertas)
JANELA_CONCLUIDAS = 45      # traz tarefas concluidas nos ultimos X dias (para ritmo e horas)
CONTRATO_ALERTA_DIAS = 30   # alerta de fim de contrato (usa a data de entrega do projeto no Asana)
RITMO_TOLERANCIA = 0.15     # ciclo abaixo do ritmo se o avanco estiver 15 pontos abaixo do esperado
STATUS_SEM_ATUALIZAR = 14   # status do projeto sem atualizacao ha X dias vira alerta de qualidade

# Como o time usa o Asana (descoberto no mapeamento)
SECAO_CONCLUIDO = ["CONCLUID", "FINALIZAD"]      # secoes que significam entregue
SECAO_PAUSADO = ["PAUSAD"]
TAGS_AGUARDANDO = ["AGUARDANDO CLIENTE"]
TAGS_INCENDIO = ["INCENDIO"]
CAMPO_PRIORIDADE = "Nível de prioridade?"
CAMPO_APROVACAO = "Aprovações"
CAMPOS_AREA = ["Digital", "Professional", "Branding", "Eventos", "Produção", "Comercial"]
CAMPO_TS_EST = "Timesheet estimado"
CAMPO_TS_REAL = "Timesheet real"
STATUS_JOB = "Status Job"
STATUS_ENCERRADO = ["Concluído", "Cancelado", "Perdemos"]
STATUS_PAUSADO = ["Stand By", "Férias"]
REGEX_CICLO = r"CICLO\s*(\d+).*VISITA|VISITA.*CICLO\s*(\d+)"
CAMPO_META = "Meta visitas"            # criar no Asana (numero) na tarefa do ciclo
CAMPO_REALIZADAS = "Visitas realizadas"  # criar no Asana (numero) na tarefa do ciclo ou da visitadora

DEMO = False
WHATSAPP_NUMERO = ""
ARQUIVO_SAIDA = os.environ.get("PAINEL_SAIDA", "painel_coordenacao.html")
FUSO = ZoneInfo("America/Sao_Paulo")
# --------------------------------------------------

API = "https://app.asana.com/api/1.0"
HOJE = dt.datetime.now(FUSO).date()


def pegar_token():
    if os.environ.get("ASANA_TOKEN"):
        return os.environ["ASANA_TOKEN"]
    try:
        from google.colab import userdata
        return userdata.get("ASANA_TOKEN")
    except Exception:
        from getpass import getpass
        return getpass("Token do Asana: ").strip()


def get(path, token, params=None):
    params = dict(params or {}); params.setdefault("limit", 100)
    itens = []
    while True:
        r = requests.get(API + path, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=60)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 30))); continue
        if r.status_code == 401:
            raise SystemExit("Token invalido ou expirado.")
        r.raise_for_status()
        c = r.json(); d = c.get("data", [])
        if isinstance(d, dict):
            return d
        itens += d
        if not c.get("next_page"):
            return itens
        params["offset"] = c["next_page"]["offset"]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


def cf(item, nome):
    for f in item.get("custom_fields") or []:
        if f.get("name") == nome:
            return f.get("display_value") or ""
    return ""


def cfn(item, nome):
    for f in item.get("custom_fields") or []:
        if f.get("name") == nome:
            if f.get("number_value") is not None:
                return float(f["number_value"])
            try:
                return float(str(f.get("display_value") or "").replace(",", "."))
            except ValueError:
                return None
    return None


def data_prazo(t):
    if t.get("due_on"):
        return dt.date.fromisoformat(t["due_on"])
    if t.get("due_at"):
        return dt.datetime.fromisoformat(t["due_at"].replace("Z", "+00:00")).astimezone(FUSO).date()
    return None


def limpa_nome(nome, cliente=""):
    n = re.sub(r"^\s*\d{1,2}[hH]\d{2}\s*", "", nome or "")
    n = re.sub(r"\[[^\]]*\]", "", n)
    n = re.sub(r"^\s*[\-–|:]*\s*", "", n)
    return n.strip() or (nome or "").strip()


def classificar(concluida, prazo, sj="", pausada=False):
    if concluida or sj == "Concluído":
        return "concluida", None
    if sj in STATUS_ENCERRADO:
        return "cancelada", None
    if pausada or sj in STATUS_PAUSADO:
        return "pausada", None
    if not prazo:
        return "sem_prazo", None
    d = (prazo - HOJE).days
    if ATRASO_ANTIGO_DIAS and d < -ATRASO_ANTIGO_DIAS:
        return "antiga", d
    if d < 0:
        return "atrasada", d
    if d <= DIAS_RISCO:
        return "em_risco", d
    return "no_prazo", d


CAMPOS_T = ("name,completed,completed_at,due_on,due_at,start_on,assignee.name,tags.name,num_subtasks,"
            "permalink_url,memberships.section.name,memberships.project.gid,"
            "custom_fields.name,custom_fields.display_value,custom_fields.number_value")
CAMPOS_P = ("name,permalink_url,owner.name,start_on,due_on,current_status_update.title,"
            "current_status_update.text,current_status_update.status_type,current_status_update.created_at,"
            "current_status_update.created_by.name")


def montar_item(it, cliente, projeto, secao, pai):
    """Transforma uma tarefa do Asana no registro usado pelo painel."""
    sec_n = norm(secao)
    tags = [tg["name"] for tg in it.get("tags") or []]
    tags_n = [norm(t) for t in tags]
    sj = cf(it, STATUS_JOB)
    concl = bool(it.get("completed"))
    nao_marcada = (not concl) and any(k in sec_n for k in SECAO_CONCLUIDO)
    pausada = any(k in sec_n for k in SECAO_PAUSADO) or "PAUSADO" in tags_n
    if pai is not None:
        concl = concl or pai["_concl"]
        pausada = pausada or pai["_pausada"]
        sj = sj or (pai["status_job"] if pai["status_job"] in STATUS_ENCERRADO + STATUS_PAUSADO else "")
    prazo = data_prazo(it)
    status, dias = classificar(concl or nao_marcada, prazo, sj, pausada)
    areas = [f"{c}: {cf(it, c)}" for c in CAMPOS_AREA if cf(it, c)]
    prio = cf(it, CAMPO_PRIORIDADE)
    resp = (it.get("assignee") or {}).get("name") or (pai["responsavel"] if pai is not None and pai["responsavel"] != "Sem responsavel" else "")
    return {
        "gid": it["gid"], "nome": it["name"], "nome_curto": limpa_nome(it["name"]),
        "pai": pai["nome"] if pai is not None else "", "pai_gid": pai["gid"] if pai is not None else "",
        "frente": pai["nome_curto"] if pai is not None else "", "cliente": cliente, "projeto": projeto,
        "secao": secao, "status_job": sj, "responsavel": resp or "Sem responsavel",
        "inicio": it.get("start_on"), "prazo": prazo.isoformat() if prazo else None,
        "concluida_em": (it.get("completed_at") or "")[:10] or None,
        "status": status, "dias": dias, "url": it.get("permalink_url", ""),
        "tags": tags, "aguardando_cliente": any(t in tags_n for t in map(norm, TAGS_AGUARDANDO)),
        "incendio": prio == "Incêndio" or any(t in tags_n for t in map(norm, TAGS_INCENDIO)) or sj == "INCENDIO",
        "prioridade": prio, "aprovacao": cf(it, CAMPO_APROVACAO), "areas": areas,
        "ts_est": cfn(it, CAMPO_TS_EST), "ts_real": cfn(it, CAMPO_TS_REAL),
        "meta": cfn(it, CAMPO_META), "realizadas": cfn(it, CAMPO_REALIZADAS),
        "nao_marcada": nao_marcada, "num_sub": it.get("num_subtasks") or 0,
        "_concl": concl or nao_marcada, "_pausada": pausada,
    }


def coletar_asana(token):
    desde = (HOJE - dt.timedelta(days=JANELA_CONCLUIDAS)).isoformat()
    projetos, tarefas, vistos = [], [], set()
    for cliente, gids in PROJETOS_CLIENTES.items():
        for g in gids:
            p = get(f"/projects/{g}", token, {"opt_fields": CAMPOS_P})
            print(f"  {cliente}: {p['name']}")
            su = p.get("current_status_update") or {}
            projetos.append({
                "gid": g, "cliente": cliente, "nome": p["name"], "url": p.get("permalink_url", ""),
                "dono": (p.get("owner") or {}).get("name", ""), "inicio": p.get("start_on"), "fim": p.get("due_on"),
                "status": {"tipo": su.get("status_type"), "titulo": su.get("title"), "texto": (su.get("text") or "")[:1500],
                           "data": (su.get("created_at") or "")[:10] or None, "autor": (su.get("created_by") or {}).get("name")} if su else None,
            })
            for t in get(f"/projects/{g}/tasks", token, {"opt_fields": CAMPOS_T, "completed_since": desde}):
                if not t.get("name") or t["gid"] in vistos:
                    continue
                vistos.add(t["gid"])
                secao = next(((m.get("section") or {}).get("name", "") for m in t.get("memberships", [])
                              if (m.get("project") or {}).get("gid") == g), "")
                mae = montar_item(t, cliente, p["name"], secao, None)
                tarefas.append(mae)
                if t.get("num_subtasks") and not mae["_concl"]:
                    for s in get(f"/tasks/{t['gid']}/subtasks", token, {"opt_fields": CAMPOS_T}):
                        if s.get("name") and s["gid"] not in vistos:
                            vistos.add(s["gid"])
                            tarefas.append(montar_item(s, cliente, p["name"], secao, mae))
    return projetos, tarefas


# ================== INDICADORES DERIVADOS ==================
def derivar(projetos, tarefas):
    filhos = {}
    for t in tarefas:
        if t["pai_gid"]:
            filhos.setdefault(t["pai_gid"], []).append(t)
    maes = [t for t in tarefas if not t["pai_gid"]]

    # ---------- Ciclos de visitacao ----------
    ciclos = []
    for m in maes:
        mt = re.search(REGEX_CICLO, norm(m["nome"]))
        if not mt:
            continue
        subs = filhos.get(m["gid"], [])
        etapas = []
        for s in subs:
            nome = re.sub(r"^[\s\-–]*CICLO\s*\d+\s*[\-–]*\s*", "", limpa_nome(s["nome"]), flags=re.I).strip(" -–") or s["nome_curto"]
            etapas.append({"nome": nome, "status": s["status"], "prazo": s["prazo"], "resp": s["responsavel"],
                           "url": s["url"], "aguardando": s["aguardando_cliente"]})
        feitas = sum(e["status"] in ("concluida", "cancelada") for e in etapas)
        pend = [e for e in etapas if e["status"] not in ("concluida", "cancelada")]
        pend.sort(key=lambda e: (e["prazo"] or "9999"))
        atrasadas = [e for e in pend if e["status"] in ("atrasada", "antiga")]
        meta = m["meta"] if m["meta"] is not None else (sum(s["meta"] for s in subs if s["meta"]) or None)
        real = m["realizadas"] if m["realizadas"] is not None else (sum(s["realizadas"] for s in subs if s["realizadas"]) or None)
        pct_et = feitas / len(etapas) if etapas else (1.0 if m["_concl"] else 0.0)
        pct_vis = (real / meta) if meta and real is not None else None
        ini = dt.date.fromisoformat(m["inicio"]) if m["inicio"] else None
        fim = dt.date.fromisoformat(m["prazo"]) if m["prazo"] else None
        pct_esp = min(max((HOJE - ini).days / max((fim - ini).days, 1), 0), 1) if ini and fim and fim > ini else None
        avanco = pct_vis if pct_vis is not None else pct_et
        if m["_concl"]:
            sit = "concluido"
        elif m["status"] == "pausada":
            sit = "pausado"
        elif ini and ini > HOJE and not feitas:
            sit = "nao_iniciado"
        elif fim and fim < HOJE:
            sit = "atrasado"
        elif atrasadas:
            sit = "etapa_atrasada"
        elif pct_esp is not None and avanco < pct_esp - RITMO_TOLERANCIA:
            sit = "abaixo_ritmo"
        elif not fim:
            sit = "sem_prazo"
        else:
            sit = "no_ritmo"
        mes = re.search(r"(JANEIRO|FEVEREIRO|MARCO|ABRIL|MAIO|JUNHO|JULHO|AGOSTO|SETEMBRO|OUTUBRO|NOVEMBRO|DEZEMBRO)", norm(m["nome"]))
        ciclos.append({
            "cliente": m["cliente"], "nome": m["nome"], "ciclo": mt.group(1) or mt.group(2),
            "mes": mes.group(1).title().replace("Marco", "Março") if mes else "", "resp": m["responsavel"],
            "inicio": m["inicio"], "prazo": m["prazo"], "url": m["url"], "etapas": etapas,
            "feitas": feitas, "total": len(etapas), "pct_etapas": pct_et, "pct_esp": pct_esp,
            "meta": meta, "realizadas": real, "pct_visitas": pct_vis,
            "proxima": pend[0] if pend else None, "atrasadas": len(atrasadas), "situacao": sit,
        })

    # ---------- Frentes (tarefas mae com subtarefas) ----------
    frentes = []
    for m in maes:
        subs = filhos.get(m["gid"], [])
        if not subs or m["_concl"] or re.search(REGEX_CICLO, norm(m["nome"])):
            continue
        pend = sorted([s for s in subs if s["status"] not in ("concluida", "cancelada")], key=lambda s: s["prazo"] or "9999")
        area = Counter(a.split(":")[0] for s in subs for a in s["areas"]).most_common(1)
        frentes.append({
            "cliente": m["cliente"], "nome": m["nome_curto"], "url": m["url"], "resp": m["responsavel"],
            "prazo": m["prazo"], "status": m["status"], "area": area[0][0] if area else "Outros",
            "total": len(subs), "feitas": len(subs) - len(pend), "abertas": len(pend),
            "atrasadas": sum(s["status"] in ("atrasada",) for s in pend),
            "aguardando": sum(s["aguardando_cliente"] for s in pend),
            "incendio": any(s["incendio"] for s in pend) or m["incendio"],
            "proxima": {"nome": pend[0]["nome_curto"], "prazo": pend[0]["prazo"], "resp": pend[0]["responsavel"],
                        "status": pend[0]["status"]} if pend else None,
        })

    # ---------- Clientes ----------
    clientes = []
    for k in PROJETOS_CLIENTES:
        ps = [p for p in projetos if p["cliente"] == k]
        ts = [t for t in tarefas if t["cliente"] == k]
        resp = next((p["dono"] for p in ps if p["dono"]), "")
        if not resp:
            c = Counter(t["responsavel"] for t in ts if not t["pai_gid"] and t["responsavel"] != "Sem responsavel")
            resp = c.most_common(1)[0][0] if c else ""
        fim = max((p["fim"] for p in ps if p["fim"]), default=None)
        ini = min((p["inicio"] for p in ps if p["inicio"]), default=None)
        sts = [dict(p["status"], projeto=p["nome"]) for p in ps if p["status"]]
        sts.sort(key=lambda s: s["data"] or "", reverse=True)
        clientes.append({"chave": k, "responsavel": resp, "contrato_inicio": ini, "contrato_fim": fim,
                         "status": sts[0] if sts else None, "projetos": [{"nome": p["nome"], "url": p["url"]} for p in ps]})

    # ---------- Qualidade dos dados ----------
    qualidade = []
    abertas = [t for t in tarefas if t["status"] not in ("concluida", "cancelada", "pausada")]
    for k in PROJETOS_CLIENTES:
        c = next(x for x in clientes if x["chave"] == k)
        ts = [t for t in tarefas if t["cliente"] == k]
        ab = [t for t in abertas if t["cliente"] == k]
        cs = [x for x in ciclos if x["cliente"] == k and x["situacao"] != "concluido"]
        q = {
            "cliente": k,
            "nao_marcadas": [t["gid"] for t in ts if t["nao_marcada"]],
            "sem_prazo": [t["gid"] for t in ab if not t["prazo"]],
            "sem_resp": [t["gid"] for t in ab if t["responsavel"] == "Sem responsavel"],
            "antigas": [t["gid"] for t in ab if t["status"] == "antiga"],
            "ciclos_sem_prazo": [x["nome"] for x in cs if not x["prazo"]],
            "ciclos_sem_meta": [x["nome"] for x in cs if x["meta"] is None],
            "sem_contrato": not c["contrato_fim"],
            "status_dias": (HOJE - dt.date.fromisoformat(c["status"]["data"])).days if c["status"] and c["status"]["data"] else None,
        }
        qualidade.append(q)
    return ciclos, frentes, clientes, qualidade


# ================== DADOS DE DEMONSTRACAO (formato igual ao Asana real) ==================
def dados_demo():
    import random
    random.seed(11)
    pessoas = ["Pessoa A", "Pessoa B", "Pessoa C", "Pessoa D", "Pessoa E"]
    frentes = {"SOCIAL": "Digital", "CRM": "Digital", "SITE": "Digital", "E-MAIL SEMANAL": "Digital",
               "REUNIÕES": "", "MÍDIA PAGA": "Digital", "PRODUÇÃO": "Eventos"}
    etapas_ciclo = ["Organização", "Contato nutris", "Mapeamento", "Carta P.R", "Cadastro produto",
                    "Montagem kit", "Emissão NF", "Envio", "Monitoramento", "Relatório"]
    ks = list(PROJETOS_CLIENTES)
    ciclos_cli = {ks[0]: [(1, "OUTUBRO", -30, -10), (2, "NOVEMBRO", -2, 14)]} if ks else {}
    projetos, tarefas, n = [], [], 0

    def tarefa(nome, prazo, concl=False, resp=None, tags=(), cfs=None, start=None):
        nonlocal n
        n += 1
        return {"gid": f"d{n}", "name": nome, "completed": concl, "due_on": prazo.isoformat() if prazo else None,
                "start_on": start.isoformat() if start else None,
                "completed_at": (min(prazo, HOJE).isoformat() + "T12:00:00Z") if concl and prazo else None,
                "assignee": {"name": resp} if resp else None, "tags": [{"name": t} for t in tags],
                "permalink_url": "", "custom_fields": [{"name": k, "display_value": str(v), "number_value": v if isinstance(v, (int, float)) else None} for k, v in (cfs or {}).items()]}

    for k in PROJETOS_CLIENTES:
        projetos.append({"gid": k, "cliente": k, "nome": k, "url": "", "dono": random.choice(pessoas[:2]),
                         "inicio": "2026-01-15", "fim": "2027-02-27" if random.random() < .6 else None,
                         "status": {"tipo": random.choice(["on_track", "at_risk", "off_track"]), "titulo": "Status semanal",
                                    "texto": "Resumo da semana: entregas do mês em andamento, aguardando aprovação do cliente em 2 peças.",
                                    "data": (HOJE - dt.timedelta(days=random.randint(1, 25))).isoformat(), "autor": "Pessoa A"}})
        for fr, area in random.sample(list(frentes.items()), 4):
            mae = tarefa(f"[{k} 2026] {fr}", HOJE + dt.timedelta(days=random.randint(5, 30)), resp=random.choice(pessoas))
            m = montar_item(mae, k, k, "TAREFA MÃE", None); tarefas.append(m)
            for i in range(random.randint(3, 7)):
                d = random.randint(-12, 18); concl = d < -3 and random.random() < .7 or random.random() < .25
                tg = ["AGUARDANDO CLIENTE"] if random.random() < .15 else (["INCENDIO"] if random.random() < .04 else [])
                cfs = {"Timesheet estimado": random.choice([20, 30, 60, 90]), "Timesheet real": random.choice([15, 30, 45, 60, 100])}
                if area: cfs[area] = random.choice(["Post/Feed", "Reels", "News", "Carrossel"])
                st = tarefa(f"00h30 [{k} 2026] {fr} PEÇA {i+1}", HOJE + dt.timedelta(days=d), concl, random.choice(pessoas), tg, cfs)
                tarefas.append(montar_item(st, k, k, "TAREFA MÃE", m))
        for i in range(random.randint(2, 6)):
            d = random.randint(-50, 15)
            st = tarefa(f"[{k}] AJUSTE {i+1}", HOJE + dt.timedelta(days=d) if random.random() > .2 else None,
                        random.random() < .2, random.choice(pessoas + [None]))
            tarefas.append(montar_item(st, k, k, random.choice(["NOVA TAREFA", "NOVA TAREFA", "CONCLUÍDO"]), None))
        for (c, mes, ini, fim) in ciclos_cli.get(k, []):
            cfs = {"Meta visitas": 230}
            if ini < 0: cfs["Visitas realizadas"] = 230 if fim < 0 else 140
            mae = tarefa(f"[{k} - {mes}] CICLO {c} - VISITAÇÃO", HOJE + dt.timedelta(days=fim), fim < -5,
                         "Pessoa B", cfs=cfs, start=HOJE + dt.timedelta(days=ini))
            m = montar_item(mae, k, k, "TAREFAS MÃE", None); tarefas.append(m)
            if m["_concl"]: continue
            dur = fim - ini
            for j, e in enumerate(etapas_ciclo):
                d = ini + int(dur * (j + 1) / len(etapas_ciclo))
                concl = d < -1 and random.random() < .85
                st = tarefa(f"[{k} - {mes[:3]}] - CICLO {c} - {e.upper()}", HOJE + dt.timedelta(days=d), concl, random.choice(pessoas))
                tarefas.append(montar_item(st, k, k, "TAREFAS MÃE", m))
    return projetos, tarefas


HTML = r"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Painel da Coordenação</title>
<style>
:root{--bg:#F5F6F8;--card:#fff;--txt:#1B2130;--sub:#687083;--lin:#E4E7ED;--red:#D14343;--redbg:#FCEBEB;--amb:#B97F00;--ambbg:#FFF4D6;--grn:#2D9A5A;--grnbg:#E5F4EB;--blu:#2F5FD0;--blubg:#E8EEFC;--gry:#8A90A0;--grybg:#EFF0F3}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--txt);font-size:14px}
header{background:var(--card);border-bottom:1px solid var(--lin);padding:16px 28px 0}
.top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
h1{font-size:20px;margin:0}.sub{color:var(--sub);font-size:12px}
.demo{background:var(--ambbg);color:var(--amb);padding:6px 10px;border-radius:6px;font-size:12px;font-weight:600;margin-top:8px;display:inline-block}
nav{display:flex;gap:4px;margin-top:14px;overflow-x:auto}
nav button{border:none;background:none;padding:10px 14px;font:inherit;font-weight:600;color:var(--sub);border-bottom:3px solid transparent;cursor:pointer;white-space:nowrap}
nav button.on{color:var(--txt);border-bottom-color:var(--txt)}
nav .cnt{background:var(--redbg);color:var(--red);border-radius:10px;padding:1px 7px;font-size:11px;margin-left:5px}
main{padding:18px 28px;max-width:1440px;margin:0 auto}
.filtros{background:var(--card);border:1px solid var(--lin);border-radius:10px;padding:12px 14px;margin-bottom:16px;display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end}
.filtros label,.lbl{display:flex;flex-direction:column;font-size:11px;color:var(--sub);gap:5px;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{border:1px solid var(--lin);background:#fff;border-radius:16px;padding:5px 11px;font-size:12px;cursor:pointer;font-weight:600;color:var(--sub);text-transform:none;letter-spacing:0}
.chip.on{background:var(--txt);color:#fff;border-color:var(--txt)}
select,input{padding:7px 9px;border:1px solid var(--lin);border-radius:7px;font:inherit;font-size:13px;background:#fff}
button.b{padding:7px 13px;border-radius:7px;border:1px solid var(--lin);background:#fff;font:inherit;font-size:13px;cursor:pointer}
.wa{background:#25D366!important;color:#fff;border:none!important;font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--card);border:1px solid var(--lin);border-radius:10px;padding:13px 15px;border-left:4px solid var(--gry);cursor:pointer}
.kpi .n{font-size:26px;font-weight:700}.kpi .l{color:var(--sub);font-size:12px}
.kpi.red{border-left-color:var(--red)}.kpi.red .n{color:var(--red)}.kpi.amb{border-left-color:var(--amb)}.kpi.amb .n{color:var(--amb)}.kpi.grn{border-left-color:var(--grn)}.kpi.grn .n{color:var(--grn)}.kpi.blu{border-left-color:var(--blu)}.kpi.blu .n{color:var(--blu)}
.g2{display:grid;grid-template-columns:2fr 1fr;gap:16px}
.box{background:var(--card);border:1px solid var(--lin);border-radius:10px;padding:16px;margin-bottom:16px}
.box h2{font-size:13px;margin:0 0 12px;text-transform:uppercase;letter-spacing:.04em;color:var(--sub)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.cc{border:1px solid var(--lin);border-radius:10px;padding:13px;border-top:5px solid var(--grn);cursor:pointer;background:#fff}
.cc.red{border-top-color:var(--red)}.cc.amb{border-top-color:var(--amb)}.cc:hover{box-shadow:0 3px 12px rgba(0,0,0,.07)}
.cc h3{margin:0;font-size:15px;display:flex;justify-content:space-between;gap:8px;align-items:center}
.ln{display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-top:1px dashed var(--lin);font-size:12.5px}
.ln .k{color:var(--sub);min-width:70px}.ln .v{text-align:right}
.tag{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;display:inline-block}
.t-red{background:var(--redbg);color:var(--red)}.t-amb{background:var(--ambbg);color:var(--amb)}.t-grn{background:var(--grnbg);color:var(--grn)}.t-blu{background:var(--blubg);color:var(--blu)}.t-gry{background:var(--grybg);color:var(--sub)}
.al{display:flex;gap:10px;padding:9px 0;border-bottom:1px solid var(--lin);cursor:pointer}.al:last-child{border:none}
.dot{width:9px;height:9px;border-radius:50%;margin-top:5px;flex-shrink:0}.dot.red{background:var(--red)}.dot.amb{background:var(--amb)}
.al b{font-size:12px}.al small{color:var(--sub);display:block}
.lista{max-height:600px;overflow:auto}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--lin);font-size:13px;vertical-align:top}
th{font-size:11px;color:var(--sub);text-transform:uppercase;position:sticky;top:0;background:#fff;z-index:1;cursor:pointer}
a{color:var(--blu);text-decoration:none}.vazio{color:var(--sub);padding:12px 0}
.prog{position:relative;height:8px;background:var(--grybg);border-radius:4px;min-width:110px;margin-top:5px}
.prog .f{height:100%;border-radius:4px;background:var(--grn)}.prog .f.amb{background:var(--amb)}.prog .f.red{background:var(--red)}
.prog .m{position:absolute;top:-3px;width:2px;height:14px;background:var(--txt)}
.ciclos{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:12px}
.ci{border:1px solid var(--lin);border-radius:10px;padding:14px;border-left:5px solid var(--grn)}
.ci.red{border-left-color:var(--red)}.ci.amb{border-left-color:var(--amb)}.ci.gry{border-left-color:var(--gry)}
.ci h3{margin:0;font-size:15px;display:flex;justify-content:space-between;gap:8px}
.ets{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}
.et{font-size:11px;padding:3px 7px;border-radius:5px;font-weight:600;white-space:nowrap}
.leg{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.st{border-left:4px solid var(--gry);padding:8px 12px;background:#FAFBFC;border-radius:6px;margin-bottom:10px;font-size:13px;white-space:pre-line}
.st.on_track{border-left-color:var(--grn)}.st.at_risk{border-left-color:var(--amb)}.st.off_track{border-left-color:var(--red)}
.q{cursor:pointer;font-weight:700}.q.z{color:var(--grn);cursor:default;font-weight:400}
.hide{display:none!important}
@media(max-width:1000px){.g2{grid-template-columns:1fr}.ciclos{grid-template-columns:1fr}main,header{padding-left:14px;padding-right:14px}}
</style></head><body>
<header>
 <div class="top"><div><h1>Painel da Coordenação</h1><div class="sub" id="atualizado"></div><div id="demo"></div></div>
 <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><input id="wanum" placeholder="WhatsApp (5511999998888)" style="width:210px"><button class="b wa" onclick="enviarWA()">Enviar alertas no WhatsApp</button></div></div>
 <nav id="nav"></nav>
</header>
<main>
 <div class="filtros">
  <div class="lbl">Clientes<div class="chips" id="chips"></div></div>
  <label>Prazo de<input type="date" id="fDe"></label>
  <label>Prazo até<input type="date" id="fAte"></label>
  <button class="b" onclick="limpar()">Limpar</button>
 </div>

 <section id="tab-geral">
  <div class="kpis" id="kpisGeral"></div>
  <div class="g2">
   <div class="box"><h2>Clientes</h2><div class="cards" id="cards"></div></div>
   <div class="box"><h2>Atenção agora</h2><div class="lista" id="alertas"></div></div>
  </div>
 </section>

 <section id="tab-tarefas" class="hide">
  <div class="filtros">
   <label>Situação<select id="tStatus"></select></label>
   <label>Responsável<select id="tResp"></select></label>
   <label>Frente<select id="tFrente"></select></label>
   <label>Mostrar<select id="tFlag"><option value="">Tudo</option><option value="aguardando">Aguardando cliente</option><option value="incendio">Incêndio</option><option value="interno">Sem bloqueio do cliente</option></select></label>
   <label>Busca<input id="tBusca" placeholder="nome da tarefa"></label>
   <span id="tGids"></span>
  </div>
  <div class="kpis" id="kpisTar"></div>
  <div class="box"><h2>Tarefas</h2><div class="lista"><table><thead><tr>
   <th data-k="cliente">Cliente</th><th data-k="nome">Frente › Tarefa</th><th data-k="secao">Seção</th><th data-k="responsavel">Responsável</th><th data-k="prazo">Prazo</th><th data-k="prioridade">Sinais</th><th data-k="aprovacao">Aprovação</th><th data-k="ordem">Situação</th>
  </tr></thead><tbody id="tabTar"></tbody></table><div class="sub" id="tLimite"></div></div></div>
 </section>

 <section id="tab-visitas" class="hide">
  <div class="kpis" id="kpisVis"></div>
  <div class="box"><h2>Ciclos de visitação</h2>
   <div class="leg" id="legVis"></div>
   <div class="ciclos" id="ciclos"></div></div>
 </section>

 <section id="tab-frentes" class="hide">
  <div class="filtros"><label>Área<select id="fArea"></select></label><label>Mostrar<select id="fFlag"><option value="">Todas as frentes</option><option value="alerta">Só com atraso ou aguardando cliente</option></select></label></div>
  <div id="frentes"></div>
 </section>

 <section id="tab-qualidade" class="hide">
  <div class="box"><h2>Qualidade dos dados no Asana</h2>
   <div class="sub" style="margin-bottom:12px">Para a planilha deixar de existir, o Asana precisa estar completo. Cada número abaixo é algo que o painel não consegue enxergar direito. Clique para ver as tarefas.</div>
   <div class="lista"><table><thead><tr><th>Cliente</th><th>Na seção Concluído sem marcar</th><th>Abertas sem prazo</th><th>Sem responsável</th><th>Atraso antigo</th><th>Ciclos sem prazo</th><th>Ciclos sem meta de visitas</th><th>Data de contrato</th><th>Status do projeto</th></tr></thead><tbody id="tabQ"></tbody></table></div>
  </div>
 </section>
</main>
<script>
const DATA = __DATA__;
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fd=s=>s?s.slice(8,10)+"/"+s.slice(5,7):"—";
const fdy=s=>s?fd(s)+"/"+s.slice(2,4):"—";
const pct=x=>x==null?"—":Math.round(x*100)+"%";
const dias=s=>Math.round((new Date(s+"T12:00")-new Date(DATA.hoje_iso+"T12:00"))/864e5);
const h=m=>m==null?"—":(Math.round(m/6)/10).toLocaleString("pt-BR")+"h";
const ROT={atrasada:"Atrasada",em_risco:"Em risco",no_prazo:"No prazo",sem_prazo:"Sem prazo",antiga:"Atraso antigo",pausada:"Pausada",concluida:"Concluída",cancelada:"Cancelada"};
const COR_T={antiga:"t-red",atrasada:"t-red",em_risco:"t-amb",no_prazo:"t-grn",sem_prazo:"t-gry",pausada:"t-gry",concluida:"t-gry",cancelada:"t-gry"};
const ORD={atrasada:0,em_risco:1,no_prazo:2,sem_prazo:3,antiga:4,pausada:5,concluida:6,cancelada:7};
const SIT_C={atrasado:["Prazo do ciclo vencido","t-red","red"],etapa_atrasada:["Etapa atrasada","t-red","red"],abaixo_ritmo:["Abaixo do ritmo","t-amb","amb"],sem_prazo:["Ciclo sem prazo","t-gry","gry"],no_ritmo:["No ritmo","t-grn",""],pausado:["Pausado","t-gry","gry"],nao_iniciado:["Ainda não começou","t-gry","gry"],concluido:["Concluído","t-gry","gry"]};
const COR_ET={concluida:"t-grn",cancelada:"t-gry",atrasada:"t-red",antiga:"t-red",em_risco:"t-amb",no_prazo:"t-blu",sem_prazo:"t-gry",pausada:"t-gry"};
const ST={on_track:["No trilho","t-grn"],at_risk:["Em risco","t-amb"],off_track:["Fora do trilho","t-red"],on_hold:["Pausado","t-gry"],complete:["Concluído","t-gry"]};
const ABERTA=t=>!["concluida","cancelada","pausada"].includes(t.status);
const ABAS=[["geral","Visão geral"],["tarefas","Tarefas"],["visitas","Visitação"],["frentes","Frentes por cliente"],["qualidade","Qualidade dos dados"]].filter(a=>DATA.blocos.includes(a[0]));
const BYGID=Object.fromEntries(DATA.tarefas.map(t=>[t.gid,t]));
let aba=ABAS[0][0],sel=new Set(),ordT={k:"ordem",asc:true},gidsF=null;
DATA.tarefas.forEach(t=>t.ordem=ORD[t.status]*100000+(t.dias??99999));
$("atualizado").textContent=`Dados do Asana de ${DATA.gerado_em} · "Em risco" = vence em até ${DATA.dias_risco} dias`;
if(DATA.demo)$("demo").innerHTML='<span class="demo">MODO DEMONSTRAÇÃO: dados fictícios no formato do Asana. Rode com DEMO = False para ver os dados reais.</span>';
try{$("wanum").value=localStorage.getItem("wanum")||DATA.whatsapp||""}catch(e){$("wanum").value=DATA.whatsapp||""}
try{JSON.parse(localStorage.getItem("selCli")||"[]").forEach(c=>DATA.ordem_clientes.includes(c)&&sel.add(c))}catch(e){}
const salvaSel=()=>{try{localStorage.setItem("selCli",JSON.stringify([...sel]))}catch(e){}};
const okCli=k=>sel.size===0||sel.has(k);
const de=()=>$("fDe").value,ate=()=>$("fAte").value;
const noPer=(a,b)=>{const d=de(),t=ate();a=a||b;b=b||a;if(!d&&!t)return true;if(!a)return false;return(!d||b>=d)&&(!t||a<=t)};

function F(){return{
 cli:DATA.clientes.filter(c=>okCli(c.chave)),
 tar:DATA.tarefas.filter(t=>okCli(t.cliente)&&noPer(t.prazo)),
 cic:DATA.ciclos.filter(c=>okCli(c.cliente)&&noPer(c.inicio,c.prazo)),
 fre:DATA.frentes.filter(f=>okCli(f.cliente)),
 qua:DATA.qualidade.filter(q=>okCli(q.cliente)),
}}

function horas(f){
 const d=de()||new Date(new Date(DATA.hoje_iso).getTime()-30*864e5).toISOString().slice(0,10),a=ate()||DATA.hoje_iso;
 const ts=DATA.tarefas.filter(t=>okCli(t.cliente)&&t.status==="concluida"&&t.concluida_em&&t.concluida_em>=d&&t.concluida_em<=a);
 return{est:ts.reduce((s,t)=>s+(t.ts_est||0),0),real:ts.reduce((s,t)=>s+(t.ts_real||0),0),n:ts.length,de:d,ate:a};
}

function alertas(f){
 const A=[];
 f.cli.forEach(c=>{
  if(c.contrato_fim){const d=dias(c.contrato_fim);
   if(d<0)A.push({n:"red",c:c.chave,t:`Contrato encerrado em ${fdy(c.contrato_fim)}`,s:"Data de entrega do projeto no Asana",a:"geral"});
   else if(d<=DATA.contrato_alerta_dias)A.push({n:d<=15?"red":"amb",c:c.chave,t:`Contrato termina em ${d} dias (${fdy(c.contrato_fim)})`,s:"Renovação ou encerramento",a:"geral"});}
  if(c.status&&(c.status.tipo==="off_track"||c.status.tipo==="at_risk"))A.push({n:c.status.tipo==="off_track"?"red":"amb",c:c.chave,t:`Status do projeto: ${ST[c.status.tipo][0]}`,s:`${c.status.titulo||""} · ${fdy(c.status.data)}`,a:"frentes"});
 });
 f.tar.filter(t=>t.incendio&&ABERTA(t)).forEach(t=>A.push({n:"red",c:t.cliente,t:`Incêndio: ${t.nome_curto}`,s:`${t.responsavel} · prazo ${fd(t.prazo)}`,a:"tarefas",g:[t.gid]}));
 f.cic.forEach(c=>{const q=`Ciclo ${c.ciclo}${c.mes?" ("+c.mes+")":""}`;
  if(c.situacao==="atrasado")A.push({n:"red",c:c.cliente,t:`${q}: prazo venceu em ${fd(c.prazo)}`,s:`${c.feitas}/${c.total} etapas feitas`,a:"visitas"});
  else if(c.situacao==="etapa_atrasada")A.push({n:"red",c:c.cliente,t:`${q}: ${c.atrasadas} etapa${c.atrasadas>1?"s":""} atrasada${c.atrasadas>1?"s":""}`,s:c.proxima?`Próxima: ${c.proxima.nome} (${fd(c.proxima.prazo)})`:"",a:"visitas"});
  else if(c.situacao==="abaixo_ritmo")A.push({n:"amb",c:c.cliente,t:`${q}: abaixo do ritmo`,s:`Avanço ${pct(c.pct_visitas??c.pct_etapas)}, esperado ${pct(c.pct_esp)}`,a:"visitas"});
 });
 const pc={};f.tar.forEach(t=>{const x=pc[t.cliente]=pc[t.cliente]||{ai:[],ac:[],r:[]};if(t.status==="atrasada")(t.aguardando_cliente?x.ac:x.ai).push(t.gid);if(t.status==="em_risco")x.r.push(t.gid)});
 Object.entries(pc).forEach(([c,x])=>{
  if(x.ai.length)A.push({n:"red",c,t:`${x.ai.length} tarefa${x.ai.length>1?"s":""} atrasada${x.ai.length>1?"s":""} (interno)`,s:"Sem bloqueio do cliente",a:"tarefas",g:x.ai});
  if(x.ac.length)A.push({n:"amb",c,t:`${x.ac.length} atrasada${x.ac.length>1?"s":""} aguardando cliente`,s:"Cobrar retorno",a:"tarefas",g:x.ac});
  if(x.r.length)A.push({n:"amb",c,t:`${x.r.length} vence${x.r.length>1?"m":""} em até ${DATA.dias_risco} dias`,s:"",a:"tarefas",g:x.r});
 });
 return A.sort((a,b)=>(a.n==="red"?0:1)-(b.n==="red"?0:1)||a.c.localeCompare(b.c));
}

function nav(f,A){
 const q=f.qua.reduce((s,x)=>s+x.nao_marcadas.length+x.sem_prazo.length+x.sem_resp.length,0);
 const cnt={geral:A.filter(a=>a.n==="red").length,tarefas:f.tar.filter(t=>t.status==="atrasada").length,visitas:f.cic.filter(c=>["atrasado","etapa_atrasada","abaixo_ritmo"].includes(c.situacao)).length,frentes:0,qualidade:q};
 $("nav").innerHTML=ABAS.map(([k,n])=>`<button class="${aba===k?"on":""}" onclick="irAba('${k}')">${n}${cnt[k]?`<span class="cnt">${cnt[k]}</span>`:""}</button>`).join("");
 ["geral","tarefas","visitas","frentes","qualidade"].forEach(k=>$("tab-"+k).classList.toggle("hide",k!==aba));
}
function irAba(k){aba=k;render();window.scrollTo(0,0)}
function verTarefas(c,gids,rot){sel=new Set([c]);salvaSel();gidsF={g:new Set(gids),rot};["tStatus","tResp","tFrente","tFlag","tBusca"].forEach(i=>$(i).value="");$("tStatus").value="";irAba("tarefas")}
function chips(){
 $("chips").innerHTML=`<span class="chip ${sel.size===0?"on":""}" onclick="sel.clear();salvaSel();render()">Todos</span>`+DATA.ordem_clientes.map(c=>`<span class="chip ${sel.has(c)?"on":""}" data-c="${esc(c)}">${esc(c)}</span>`).join("");
 document.querySelectorAll(".chip[data-c]").forEach(el=>el.onclick=()=>{const c=el.dataset.c;sel.has(c)?sel.delete(c):sel.add(c);salvaSel();render()});
}
function limpar(){sel.clear();salvaSel();gidsF=null;["fDe","fAte","tResp","tFrente","tFlag","tBusca","fArea","fFlag"].forEach(i=>$(i).value="");$("tStatus").value="_abertas";render()}
const kpi=(n,l,cl,fn)=>`<div class="kpi ${cl}" ${fn?`onclick="${fn}"`:""}><div class="n">${n}</div><div class="l">${l}</div></div>`;

function geral(f,A){
 const ab=f.tar.filter(ABERTA),n=fn=>ab.filter(fn).length;
 const inc=n(t=>t.incendio),ai=n(t=>t.status==="atrasada"&&!t.aguardando_cliente),ac=n(t=>t.status==="atrasada"&&t.aguardando_cliente),ri=n(t=>t.status==="em_risco");
 const cic=f.cic.filter(c=>["atrasado","etapa_atrasada","abaixo_ritmo"].includes(c.situacao)).length,H=horas(f);
 $("kpisGeral").innerHTML=kpi(inc,"Incêndios abertos",inc?"red":"grn","$('tFlag').value='incendio';irAba('tarefas')")+kpi(ai,"Atrasadas (interno)",ai?"red":"grn","$('tFlag').value='interno';$('tStatus').value='atrasada';irAba('tarefas')")+
  kpi(ac,"Atrasadas aguardando cliente",ac?"amb":"grn","$('tFlag').value='aguardando';$('tStatus').value='atrasada';irAba('tarefas')")+kpi(ri,`Vencem em ${DATA.dias_risco} dias`,ri?"amb":"grn","$('tStatus').value='em_risco';irAba('tarefas')")+
  kpi(cic,"Ciclos de visita com alerta",cic?"amb":"grn","irAba('visitas')")+kpi(h(H.real),`Horas entregues ${fd(H.de)} a ${fd(H.ate)} (estimado ${h(H.est)})`,"blu");
 $("cards").innerHTML=DATA.ordem_clientes.filter(okCli).map(k=>{
  const c=DATA.clientes.find(x=>x.chave===k)||{},ts=f.tar.filter(t=>t.cliente===k),a=ts.filter(ABERTA),al=A.filter(x=>x.c===k),cs=f.cic.filter(x=>x.cliente===k&&x.situacao!=="concluido");
  const farol=al.some(x=>x.n==="red")?"red":al.length?"amb":"",cnt=fn=>a.filter(fn).length;
  const tg=[[cnt(t=>t.incendio),"incêndio","t-red"],[cnt(t=>t.status==="atrasada"&&!t.aguardando_cliente),"atrasada","t-red"],[cnt(t=>t.status==="atrasada"&&t.aguardando_cliente),"ag. cliente","t-amb"],[cnt(t=>t.status==="em_risco"),"em risco","t-amb"]].filter(x=>x[0]).map(x=>`<span class="tag ${x[2]}">${x[0]} ${x[1]}${x[1]==="atrasada"&&x[0]>1?"s":""}</span>`).join(" ")||'<span class="tag t-grn">em dia</span>';
  let ct='<span class="sub">sem data no Asana</span>';if(c.contrato_fim){const d=dias(c.contrato_fim);ct=d<0?`<span class="tag t-red">encerrado ${fdy(c.contrato_fim)}</span>`:`até ${fdy(c.contrato_fim)} ${d<=DATA.contrato_alerta_dias?`<span class="tag ${d<=15?"t-red":"t-amb"}">${d} dias</span>`:""}`}
  const st=c.status?`<span class="tag ${ST[c.status.tipo]?.[1]||"t-gry"}">${ST[c.status.tipo]?.[0]||"—"}</span> <span class="sub">${fdy(c.status.data)}</span>`:'<span class="sub">sem status</span>';
  const ci=cs.slice(0,3).map(x=>`<div>Ciclo ${esc(x.ciclo)} · ${x.total?x.feitas+"/"+x.total+" etapas":"sem etapas"} <span class="tag ${SIT_C[x.situacao][1]}">${SIT_C[x.situacao][0]}</span></div>`).join("");
  return `<div class="cc ${farol}" onclick="sel=new Set(['${esc(k)}']);salvaSel();render()"><h3><span>${esc(k)}</span></h3>
   <div class="sub" style="margin:3px 0 6px">${esc(c.responsavel||"responsável não definido")}</div>
   <div class="ln"><span class="k">Status</span><span class="v">${st}</span></div>
   <div class="ln"><span class="k">Contrato</span><span class="v">${ct}</span></div>
   <div class="ln"><span class="k">Tarefas</span><span class="v">${tg}<br><span class="sub">${a.length} abertas</span></span></div>
   ${ci?`<div class="ln"><span class="k">Visitação</span><span class="v">${ci}</span></div>`:""}</div>`}).join("")||'<div class="vazio">Nenhum cliente selecionado.</div>';
 $("alertas").innerHTML=A.length?A.map((a,i)=>`<div class="al" data-i="${i}"><span class="dot ${a.n}"></span><div><b>${esc(a.c)}</b> · ${esc(a.t)}<small>${esc(a.s)}</small></div></div>`).join(""):'<div class="vazio">Nada pedindo atenção agora.</div>';
 document.querySelectorAll(".al[data-i]").forEach(el=>el.onclick=()=>{const a=A[+el.dataset.i];if(a.g)verTarefas(a.c,a.g,a.t);else{sel=new Set([a.c]);salvaSel();irAba(a.a)}});
}

function tarefas(f){
 const s=$("tStatus").value,r=$("tResp").value,fr=$("tFrente").value,fl=$("tFlag").value,b=$("tBusca").value.toLowerCase();
 $("tGids").innerHTML=gidsF?`<span class="tag t-blu" style="cursor:pointer" onclick="gidsF=null;render()">${esc(gidsF.rot)} ✕</span>`:"";
 const base=f.tar.filter(t=>(!gidsF||gidsF.g.has(t.gid))&&(!r||t.responsavel===r)&&(!fr||t.frente===fr)&&(!b||(t.nome+" "+t.pai).toLowerCase().includes(b))
  &&(!fl||(fl==="aguardando"&&t.aguardando_cliente)||(fl==="incendio"&&t.incendio)||(fl==="interno"&&!t.aguardando_cliente)));
 const c={};base.forEach(t=>c[t.status]=(c[t.status]||0)+1);
 $("kpisTar").innerHTML=[["atrasada","red"],["em_risco","amb"],["no_prazo","grn"],["sem_prazo",""],["antiga",""],["concluida",""]].map(([k,cl])=>kpi(c[k]||0,ROT[k],cl,`$('tStatus').value=$('tStatus').value==='${k}'?'_abertas':'${k}';render()`)).join("");
 const L=base.filter(t=>!s||(s==="_abertas"?ABERTA(t):t.status===s)).sort((a,b)=>{let x=a[ordT.k]??"",y=b[ordT.k]??"";return(x>y?1:x<y?-1:0)*(ordT.asc?1:-1)});
 $("tabTar").innerHTML=L.slice(0,600).map(t=>`<tr><td>${esc(t.cliente)}</td><td>${t.frente?`<small class="sub">${esc(t.frente)} ›</small><br>`:""}${t.url?`<a href="${t.url}" target="_blank">${esc(t.nome_curto)}</a>`:esc(t.nome_curto)}</td><td class="sub">${esc(t.secao)}</td><td>${esc(t.responsavel)}</td><td>${fd(t.prazo)}</td>
  <td>${t.incendio?'<span class="tag t-red">incêndio</span> ':""}${t.aguardando_cliente?'<span class="tag t-amb">ag. cliente</span> ':""}${t.nao_marcada?'<span class="tag t-gry">não marcada</span>':""}</td><td class="sub">${esc(t.aprovacao)}</td><td><span class="tag ${COR_T[t.status]}">${ROT[t.status]}</span></td></tr>`).join("")||`<tr><td colspan="8" class="vazio">Nenhuma tarefa com esses filtros.</td></tr>`;
 $("tLimite").textContent=L.length>600?`Mostrando 600 de ${L.length}. Use os filtros.`:"";
}

function visitas(f){
 const n=s=>f.cic.filter(c=>c.situacao===s).length;
 $("kpisVis").innerHTML=kpi(n("atrasado")+n("etapa_atrasada"),"Com atraso",n("atrasado")+n("etapa_atrasada")?"red":"grn")+kpi(n("abaixo_ritmo"),"Abaixo do ritmo",n("abaixo_ritmo")?"amb":"grn")+kpi(n("no_ritmo"),"No ritmo","grn")+kpi(n("sem_prazo"),"Sem prazo definido","")+kpi(n("concluido"),"Concluídos","");
 $("legVis").innerHTML=[["t-grn","Feita"],["t-red","Atrasada"],["t-amb","Vence em breve"],["t-blu","No prazo"],["t-gry","Sem prazo"]].map(([c,n])=>`<span class="et ${c}">${n}</span>`).join("")+'<span class="sub" style="align-self:center">O traço preto na barra mostra onde o ciclo deveria estar hoje.</span>';
 const o={atrasado:0,etapa_atrasada:1,abaixo_ritmo:2,no_ritmo:3,sem_prazo:4,nao_iniciado:5,pausado:6,concluido:7};
 $("ciclos").innerHTML=[...f.cic].sort((a,b)=>o[a.situacao]-o[b.situacao]||a.cliente.localeCompare(b.cliente)||(+a.ciclo)-(+b.ciclo)).map(c=>{
  const[s,cl,bc]=SIT_C[c.situacao],av=c.pct_visitas??c.pct_etapas,fc=bc==="red"?"red":bc==="amb"?"amb":"";
  return `<div class="ci ${bc}"><h3><span>${esc(c.cliente)} · Ciclo ${esc(c.ciclo)}${c.mes?" · "+esc(c.mes):""}</span><span class="tag ${cl}">${s}</span></h3>
  <div class="sub" style="margin-top:3px">${esc(c.resp)} · ${c.inicio?fd(c.inicio)+" a ":"até "}${fd(c.prazo)}${c.url?` · <a href="${c.url}" target="_blank">abrir no Asana</a>`:""}</div>
  <div style="margin-top:10px;font-size:13px">${c.meta?`<b>${c.realizadas??0}/${c.meta}</b> visitas${c.pct_visitas!=null?` (${pct(c.pct_visitas)})`:""}${c.total?" · ":""}`:""}${c.total?`<b>${c.feitas}/${c.total}</b> etapas`:(c.situacao==="concluido"?"Ciclo concluído":"Sem etapas cadastradas")}${c.pct_esp!=null&&c.situacao!=="concluido"?` · esperado hoje ${pct(c.pct_esp)}`:""}</div>
  <div class="prog"><div class="f ${fc}" style="width:${Math.min(av*100,100)}%"></div>${c.pct_esp!=null&&c.situacao!=="concluido"?`<div class="m" style="left:${c.pct_esp*100}%"></div>`:""}</div>
  ${c.proxima?`<div style="margin-top:8px;font-size:13px">Próxima etapa: <b>${esc(c.proxima.nome)}</b> · ${esc(c.proxima.resp)} · ${fd(c.proxima.prazo)}</div>`:""}
  <div class="ets">${c.etapas.map(e=>`<span class="et ${COR_ET[e.status]}" title="${esc(e.resp)} · ${fd(e.prazo)}${e.aguardando?" · aguardando cliente":""}">${esc(e.nome)}</span>`).join("")}</div></div>`}).join("")||'<div class="vazio">Nenhum ciclo de visitação encontrado. O painel procura tarefas com "CICLO n" e "VISITAÇÃO" no nome.</div>';
}

function frentes(f){
 const ar=$("fArea").value,fl=$("fFlag").value;
 $("frentes").innerHTML=f.cli.map(c=>{
  const fs=f.fre.filter(x=>x.cliente===c.chave&&(!ar||x.area===ar)&&(!fl||x.atrasadas||x.aguardando)).sort((a,b)=>b.atrasadas-a.atrasadas||b.aguardando-a.aguardando||(a.proxima?.prazo||"9").localeCompare(b.proxima?.prazo||"9"));
  if(!fs.length&&!c.status)return"";
  const st=c.status?`<div class="st ${c.status.tipo}"><b>${esc(c.status.titulo||"Status do projeto")}</b> <span class="sub">· ${esc(c.status.autor||"")} · ${fdy(c.status.data)}</span>${c.status.texto?"\n"+esc(c.status.texto):""}</div>`:'<div class="st"><span class="sub">Nenhum status publicado no projeto. Publicar um status semanal no Asana substitui a coluna de texto da planilha.</span></div>';
  return `<div class="box"><h2>${esc(c.chave)} · ${esc(c.responsavel||"")}</h2>${st}${fs.length?`<table><thead><tr><th>Frente</th><th>Área</th><th>Responsável</th><th>Progresso</th><th>Sinais</th><th>Próxima entrega</th></tr></thead><tbody>${fs.map(x=>`<tr>
   <td>${x.url?`<a href="${x.url}" target="_blank">${esc(x.nome)}</a>`:esc(x.nome)}</td><td class="sub">${esc(x.area)}</td><td>${esc(x.resp)}</td>
   <td>${x.feitas}/${x.total}<div class="prog"><div class="f" style="width:${x.total?x.feitas/x.total*100:0}%"></div></div></td>
   <td>${x.incendio?'<span class="tag t-red">incêndio</span> ':""}${x.atrasadas?`<span class="tag t-red">${x.atrasadas} atrasada${x.atrasadas>1?"s":""}</span> `:""}${x.aguardando?`<span class="tag t-amb">${x.aguardando} ag. cliente</span>`:""}</td>
   <td>${x.proxima?`${esc(x.proxima.nome)}<br><span class="sub">${esc(x.proxima.resp)} · ${fd(x.proxima.prazo)}</span> <span class="tag ${COR_T[x.proxima.status]}">${ROT[x.proxima.status]}</span>`:'<span class="sub">nada pendente</span>'}</td></tr>`).join("")}</tbody></table>`:'<div class="sub">Nenhuma frente com esses filtros.</div>'}</div>`}).join("")||'<div class="vazio">Nada com esses filtros.</div>';
}

function qualidade(f){
 const cel=(c,g,rot)=>g.length?`<span class="q" style="color:var(--amb)" onclick='verTarefas(${JSON.stringify(c)},${JSON.stringify(g)},${JSON.stringify(rot)})'>${g.length}</span>`:'<span class="q z">0</span>';
 const lst=l=>l.length?`<span title="${esc(l.join("\n"))}" style="color:var(--amb);font-weight:700">${l.length}</span>`:'<span class="q z">0</span>';
 $("tabQ").innerHTML=f.qua.map(q=>`<tr><td><b>${esc(q.cliente)}</b></td><td>${cel(q.cliente,q.nao_marcadas,"Na seção Concluído sem marcar")}</td><td>${cel(q.cliente,q.sem_prazo,"Abertas sem prazo")}</td><td>${cel(q.cliente,q.sem_resp,"Sem responsável")}</td><td>${cel(q.cliente,q.antigas,"Atraso antigo")}</td>
  <td>${lst(q.ciclos_sem_prazo)}</td><td>${lst(q.ciclos_sem_meta)}</td><td>${q.sem_contrato?'<span class="tag t-amb">preencher</span>':'<span class="tag t-grn">ok</span>'}</td>
  <td>${q.status_dias==null?'<span class="tag t-amb">nunca publicado</span>':q.status_dias>DATA.status_sem_atualizar?`<span class="tag t-amb">${q.status_dias} dias atrás</span>`:`<span class="tag t-grn">${q.status_dias} dias atrás</span>`}</td></tr>`).join("");
}

function opts(id,vals,todos,first){$(id).innerHTML=(first||"")+`<option value="">${todos}</option>`+vals.map(v=>`<option value="${esc(v[0])}">${esc(v[1])}</option>`).join("")}
opts("tStatus",Object.entries(ROT),"Todas",'<option value="_abertas">Abertas</option>');
opts("tResp",[...new Set(DATA.tarefas.map(t=>t.responsavel))].sort().map(x=>[x,x]),"Todos");
opts("tFrente",[...new Set(DATA.tarefas.map(t=>t.frente).filter(Boolean))].sort().map(x=>[x,x]),"Todas");
opts("fArea",[...new Set(DATA.frentes.map(x=>x.area))].sort().map(x=>[x,x]),"Todas");
["fDe","fAte","tStatus","tResp","tFrente","tFlag","tBusca","fArea","fFlag"].forEach(i=>$(i).addEventListener("input",render));
document.querySelectorAll("#tab-tarefas th").forEach(th=>th.onclick=()=>{const k=th.dataset.k;ordT={k,asc:ordT.k===k?!ordT.asc:true};render()});

function render(){const f=F(),A=alertas(f);chips();nav(f,A);
 if(aba==="geral")geral(f,A);if(aba==="tarefas")tarefas(f);if(aba==="visitas")visitas(f);if(aba==="frentes")frentes(f);if(aba==="qualidade")qualidade(f)}

function enviarWA(){
 const num=$("wanum").value.replace(/\D/g,"");try{localStorage.setItem("wanum",num)}catch(e){}
 const limpa=x=>(x||"").replace(/[\u{10000}-\u{10FFFF}☀-➿️]/gu,"").trim();
 const A=alertas(F()),cl=[...new Set(A.map(a=>a.c))];
 const l=[`*Painel da Coordenação* | ${DATA.hoje}`,`${A.filter(a=>a.n==="red").length} pontos críticos e ${A.filter(a=>a.n!=="red").length} de atenção`,""];
 cl.forEach(c=>{l.push(`*${limpa(c)}*`);A.filter(a=>a.c===c).slice(0,8).forEach(a=>l.push(`${a.n==="red"?"[!]":"[ ]"} ${limpa(a.t)}`));l.push("")});
 if(!A.length)l.push("Nada pedindo atenção hoje.");
 window.open(`https://wa.me/${num}?text=${encodeURIComponent(l.join("\n"))}`,"_blank");
}
render();
</script></body></html>
"""


def gerar():
    projetos, tarefas = dados_demo() if DEMO else coletar_asana(pegar_token())
    ciclos, frentes, clientes, qualidade = derivar(projetos, tarefas)
    dentro = lambda k: k in CLIENTES_MOSTRAR
    for t in tarefas:
        for k in ("_concl", "_pausada"):
            t.pop(k, None)
    dados = {
        "gerado_em": dt.datetime.now(FUSO).strftime("%d/%m/%Y %H:%M"), "hoje": HOJE.strftime("%d/%m/%Y"),
        "hoje_iso": HOJE.isoformat(), "dias_risco": DIAS_RISCO, "contrato_alerta_dias": CONTRATO_ALERTA_DIAS,
        "status_sem_atualizar": STATUS_SEM_ATUALIZAR, "demo": DEMO, "blocos": BLOCOS, "whatsapp": WHATSAPP_NUMERO,
        "ordem_clientes": [k for k in CLIENTES_MOSTRAR],
        "clientes": [c for c in clientes if dentro(c["chave"])],
        "tarefas": [t for t in tarefas if dentro(t["cliente"])],
        "ciclos": [c for c in ciclos if dentro(c["cliente"])],
        "frentes": [f for f in frentes if dentro(f["cliente"])],
        "qualidade": [q for q in qualidade if dentro(q["cliente"])],
    }
    html = HTML.replace("__DATA__", json.dumps(dados, ensure_ascii=False).replace("</", "<\\/"))
    os.makedirs(os.path.dirname(ARQUIVO_SAIDA) or ".", exist_ok=True)
    with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f:
        f.write(html)
    ab = [t for t in dados["tarefas"] if t["status"] not in ("concluida", "cancelada", "pausada")]
    print(f"\nPainel gerado: {ARQUIVO_SAIDA}")
    print(f"{len(dados['tarefas'])} tarefas ({len(ab)} abertas) | {sum(t['status'] == 'atrasada' for t in ab)} atrasadas | "
          f"{sum(t['incendio'] for t in ab)} incendios | {len(dados['ciclos'])} ciclos de visita | {len(dados['frentes'])} frentes")
    try:
        from google.colab import files
        files.download(ARQUIVO_SAIDA)
    except Exception:
        pass


gerar()
