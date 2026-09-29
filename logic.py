"""Regras de negócio do Responde: intenção da mensagem, resposta gerada a
partir dos dados reais do cliente, estágio de cobrança e score de risco."""
from datetime import datetime

DATE_FMT = "%Y-%m-%d"


def parse_date(s):
    if not s:
        return None
    return datetime.strptime(s[:10], DATE_FMT)


def parse_datetime(s):
    if not s:
        return None
    s = s.replace("Z", "").replace("T", " ")
    s = s.split("+")[0].split(".")[0]
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")


def detect_intent(text):
    t = text.lower()
    if "das" in t:
        return "das"
    if "boleto" in t or "honor" in t:
        return "boleto"
    if "nota" in t or "comprovante" in t or "recibo" in t:
        return "documento"
    return None


def build_reply(client_row, intent, documents_for_client, now):
    nome = client_row["name"]

    if intent == "das":
        venc = parse_date(client_row["das_vencimento"])
        valor = client_row["das_valor"]
        dias = (venc - now).days
        if dias < 0:
            situacao = f"venceu há {abs(dias)} dia(s)"
        elif dias == 0:
            situacao = "vence hoje"
        else:
            situacao = f"vence em {venc.strftime('%d/%m')} (faltam {dias} dia(s))"
        return (f"Oi {nome}! Seu DAS é de R$ {valor:,.2f}, e {situacao}. "
                f"Aqui está a segunda via: [link do boleto].")

    if intent == "boleto":
        venc = parse_date(client_row["honorarios_vencimento"])
        valor = client_row["honorarios_valor"]
        dias = (now - venc).days
        atraso = f", já com {dias} dia(s) de atraso" if dias > 0 else ""
        return (f"Claro! Segue a segunda via do seu boleto de honorários, "
                f"R$ {valor:,.2f}, vencimento {venc.strftime('%d/%m')}{atraso}: [link do boleto].")

    if intent == "documento":
        pendentes = [d for d in documents_for_client if d["status"] != "recebido"]
        if not pendentes:
            return f"Deixa eu ver aqui... está tudo certo, {nome}! Não há nenhum documento pendente no momento."
        doc = pendentes[0]
        return (f"Deixa eu ver aqui... ainda não recebemos: {doc['referencia']}, {nome}. "
                f"Pode mandar foto ou PDF por aqui mesmo quando puder!")

    return (f"Oi {nome}! Não consegui identificar automaticamente sua pergunta — "
            f"já registrei aqui e o contador vai te responder pessoalmente.")


def escalation_stage(dias_atraso):
    if dias_atraso >= 7:
        return "escalonado", "Escalonado — o contador foi avisado pra intervir"
    if dias_atraso >= 3:
        return "segundo_lembrete", "Segundo lembrete, tom mais direto"
    if dias_atraso >= 1:
        return "lembrete_leve", "Lembrete leve automático"
    return "novo", "Pendência recém-registrada"


def reminder_text(client_row, document_row, dias_atraso):
    nome = client_row["name"]
    ref = document_row["referencia"]
    stage, _ = escalation_stage(dias_atraso)
    if stage == "escalonado":
        return (f"{nome}, já são {dias_atraso} dias sem recebermos {ref.lower()}. "
                f"Vamos precisar resolver isso ainda essa semana — o contador vai te ligar.")
    if stage == "segundo_lembrete":
        return f"{nome}, passando de novo: ainda precisamos de {ref.lower()}. Consegue mandar hoje?"
    return f"Oi {nome}! Só um lembrete: estamos aguardando {ref.lower()}. Quando puder, nos manda por aqui."


def compute_risk(client_row, documents_for_client, complaints_for_client, now):
    last_msg = parse_datetime(client_row["last_client_message_at"])
    silence_days = max(0, (now - last_msg).days) if last_msg else 0

    overdue_docs = 0
    for d in documents_for_client:
        if d["status"] == "recebido":
            continue
        criado = parse_datetime(d["criado_em"])
        dias = (now - criado).days
        if dias >= 3:
            overdue_docs += 1

    complaints_count = len(complaints_for_client)

    score = silence_days * 1 + overdue_docs * 4 + complaints_count * 6

    if score >= 15:
        level = "alto"
    elif score >= 5:
        level = "medio"
    else:
        level = "baixo"

    signals = []
    if silence_days >= 2:
        signals.append(f"Silêncio há {silence_days} dia(s) sem responder mensagens")
    if overdue_docs:
        signals.append(f"{overdue_docs} documento(s) pendente(s) há 3+ dias")
    if complaints_count:
        signals.append(f"{complaints_count} reclamação(ões) registrada(s)")
    if not signals:
        signals.append("Nenhum sinal de alerta nos últimos registros")

    if level == "alto":
        action = "Sugestão: ligar essa semana — esse é o padrão que costuma anteceder um pedido de rescisão."
    elif level == "medio":
        action = "Sugestão: uma ligação rápida essa semana, antes que o padrão se repita."
    else:
        action = "Nenhuma ação necessária — só manter o relacionamento normal."

    return dict(score=score, level=level, signals=signals, action=action,
                silence_days=silence_days, overdue_docs=overdue_docs, complaints_count=complaints_count)
