import os
from datetime import datetime, timedelta

from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

_client = None


def sb():
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def now():
    res = sb().table("responde_settings").select("value").eq("key", "time_offset_days").execute()
    offset = int(res.data[0]["value"]) if res.data else 0
    return datetime.now() + timedelta(days=offset)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def init_db(reset=False):
    res = sb().table("responde_clients").select("id").execute()
    if reset or not res.data:
        seed()


def seed():
    client = sb()
    for table in ("responde_complaints", "responde_documents", "responde_messages", "responde_clients"):
        client.table(table).delete().gte("id", 0).execute()
    client.table("responde_settings").upsert({"key": "time_offset_days", "value": "0"}).execute()

    t = datetime.now()

    clients = [
        dict(
            name="Ana", business="Loja da Ana Doces", whatsapp="+55 11 9xxxx-0001",
            mode="assistido",
            das_valor=187.40, das_vencimento=(t + timedelta(days=5)).strftime("%Y-%m-%d"),
            honorarios_valor=350.00, honorarios_vencimento=(t + timedelta(days=-10)).strftime("%Y-%m-%d"),
            last_client_message_at=iso(t - timedelta(hours=2)),
        ),
        dict(
            name="Roberto Bittencourt", business="Transportes Bittencourt", whatsapp="+55 11 9xxxx-0002",
            mode="assistido",
            das_valor=612.90, das_vencimento=(t + timedelta(days=12)).strftime("%Y-%m-%d"),
            honorarios_valor=480.00, honorarios_vencimento=(t + timedelta(days=-3)).strftime("%Y-%m-%d"),
            last_client_message_at=iso(t - timedelta(days=4)),
        ),
        dict(
            name="Marli Alvorada", business="Construtora Alvorada", whatsapp="+55 11 9xxxx-0003",
            mode="automatico",
            das_valor=1450.00, das_vencimento=(t + timedelta(days=20)).strftime("%Y-%m-%d"),
            honorarios_valor=900.00, honorarios_vencimento=(t + timedelta(days=-1)).strftime("%Y-%m-%d"),
            last_client_message_at=iso(t - timedelta(days=12)),
        ),
        dict(
            name="João Padaria", business="Padaria Central", whatsapp="+55 11 9xxxx-0004",
            mode="automatico",
            das_valor=95.20, das_vencimento=(t + timedelta(days=18)).strftime("%Y-%m-%d"),
            honorarios_valor=250.00, honorarios_vencimento=(t + timedelta(days=15)).strftime("%Y-%m-%d"),
            last_client_message_at=iso(t - timedelta(hours=6)),
        ),
    ]

    inserted = client.table("responde_clients").insert(clients).execute().data
    client_ids = {c["name"]: c["id"] for c in inserted}

    documents = [
        dict(client="Ana", tipo="nota_fiscal", referencia="Nota fiscal de agosto", dias_atras=3),
        dict(client="Roberto Bittencourt", tipo="comprovante", referencia="Comprovante de pagamento", dias_atras=7),
        dict(client="Marli Alvorada", tipo="comprovante", referencia="Comprovante de honorários", dias_atras=9),
    ]
    doc_rows = []
    for d in documents:
        criado = t - timedelta(days=d["dias_atras"])
        doc_rows.append(dict(
            client_id=client_ids[d["client"]], tipo=d["tipo"], referencia=d["referencia"],
            status="escalonado" if d["dias_atras"] >= 7 else "pendente", criado_em=iso(criado),
        ))
    client.table("responde_documents").insert(doc_rows).execute()

    client.table("responde_complaints").insert(dict(
        client_id=client_ids["Marli Alvorada"],
        texto="Reclamou do prazo de resposta sobre o boleto atrasado.",
        criado_em=iso(t - timedelta(days=6)),
    )).execute()
