from flask import Flask, jsonify, request, render_template

import db
import logic

app = Flask(__name__)
db.init_db()


def docs_by_client(all_docs, client_id):
    return [d for d in all_docs if d["client_id"] == client_id]


def complaints_by_client(all_complaints, client_id):
    return [c for c in all_complaints if c["client_id"] == client_id]


def client_public(row, all_docs, all_complaints, now):
    docs = docs_by_client(all_docs, row["id"])
    complaints = complaints_by_client(all_complaints, row["id"])
    risk = logic.compute_risk(row, docs, complaints, now)
    return {
        "id": row["id"],
        "name": row["name"],
        "business": row["business"],
        "whatsapp": row["whatsapp"],
        "mode": row["mode"],
        "das_valor": row["das_valor"],
        "das_vencimento": row["das_vencimento"],
        "honorarios_valor": row["honorarios_valor"],
        "honorarios_vencimento": row["honorarios_vencimento"],
        "risk": risk,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    sb = db.sb()
    now = db.now()

    clients_raw = sb.table("responde_clients").select("*").order("id").execute().data
    all_docs = sb.table("responde_documents").select("*").order("criado_em").execute().data
    all_complaints = sb.table("responde_complaints").select("*").execute().data

    client_by_id = {c["id"]: c for c in clients_raw}
    clients = [client_public(c, all_docs, all_complaints, now) for c in clients_raw]

    documents = []
    for d in all_docs:
        client = client_by_id[d["client_id"]]
        criado = logic.parse_datetime(d["criado_em"])
        dias_atraso = max(0, (now - criado).days)
        stage, stage_label = logic.escalation_stage(dias_atraso)
        documents.append({
            **d,
            "client_name": client["business"],
            "dias_atraso": dias_atraso,
            "stage": stage if d["status"] != "recebido" else "recebido",
            "stage_label": "Documento recebido" if d["status"] == "recebido" else stage_label,
        })

    all_messages = sb.table("responde_messages").select("*").order("created_at").execute().data

    pending = []
    for m in all_messages:
        if m["status"] != "pending":
            continue
        client = client_by_id[m["client_id"]]
        pending.append({**m, "client_name": client["name"]})

    log = []
    for m in reversed(all_messages):
        if not (m["direction"] == "out" and m["status"] == "sent"):
            continue
        client = client_by_id[m["client_id"]]
        log.append({**m, "client_name": client["name"]})
        if len(log) >= 30:
            break

    offset_res = sb.table("responde_settings").select("value").eq("key", "time_offset_days").execute()
    time_offset_days = int(offset_res.data[0]["value"]) if offset_res.data else 0

    return jsonify({
        "clients": clients,
        "documents": documents,
        "pending": pending,
        "log": log,
        "now": now.strftime("%d/%m/%Y %H:%M"),
        "time_offset_days": time_offset_days,
    })


@app.route("/api/clients/<int:client_id>/messages")
def client_messages(client_id):
    rows = (
        db.sb().table("responde_messages").select("*")
        .eq("client_id", client_id).order("created_at").execute().data
    )
    rows = [r for r in rows if r["status"] != "discarded"]
    return jsonify(rows)


@app.route("/api/clients/<int:client_id>/mode", methods=["POST"])
def set_mode(client_id):
    mode = request.json.get("mode")
    if mode not in ("assistido", "automatico"):
        return jsonify({"error": "modo inválido"}), 400
    db.sb().table("responde_clients").update({"mode": mode}).eq("id", client_id).execute()
    return jsonify({"ok": True})


@app.route("/api/clients/<int:client_id>/inbound", methods=["POST"])
def inbound(client_id):
    text = (request.json.get("text") or "").strip()
    if not text:
        return jsonify({"error": "mensagem vazia"}), 400

    sb = db.sb()
    now = db.now()
    now_str = db.iso(now)

    client_res = sb.table("responde_clients").select("*").eq("id", client_id).execute()
    if not client_res.data:
        return jsonify({"error": "cliente não encontrado"}), 404
    client = client_res.data[0]

    sb.table("responde_messages").insert({
        "client_id": client_id, "direction": "in", "text": text, "created_at": now_str,
    }).execute()
    sb.table("responde_clients").update({"last_client_message_at": now_str}).eq("id", client_id).execute()

    intent = logic.detect_intent(text)
    docs = sb.table("responde_documents").select("*").eq("client_id", client_id).execute().data
    reply = logic.build_reply(client, intent, docs, now)

    if intent is None:
        status = "pending"
        mode_used = client["mode"]
    elif client["mode"] == "automatico":
        status = "sent"
        mode_used = "automatico"
    else:
        status = "pending"
        mode_used = "assistido"

    inserted = sb.table("responde_messages").insert({
        "client_id": client_id, "direction": "out", "text": reply, "intent": intent,
        "status": status, "mode_used": mode_used, "created_at": now_str,
    }).execute().data[0]

    return jsonify({"reply_id": inserted["id"], "text": reply, "status": status, "intent": intent})


@app.route("/api/messages/<int:message_id>/approve", methods=["POST"])
def approve(message_id):
    db.sb().table("responde_messages").update({"status": "sent"}).eq("id", message_id).eq("status", "pending").execute()
    return jsonify({"ok": True})


@app.route("/api/messages/<int:message_id>/discard", methods=["POST"])
def discard(message_id):
    db.sb().table("responde_messages").update({"status": "discarded"}).eq("id", message_id).eq("status", "pending").execute()
    return jsonify({"ok": True})


@app.route("/api/documents/<int:document_id>/remind", methods=["POST"])
def remind(document_id):
    sb = db.sb()
    now = db.now()
    now_str = db.iso(now)

    doc_res = sb.table("responde_documents").select("*").eq("id", document_id).execute()
    if not doc_res.data:
        return jsonify({"error": "documento não encontrado"}), 404
    doc = doc_res.data[0]
    client = sb.table("responde_clients").select("*").eq("id", doc["client_id"]).execute().data[0]

    criado = logic.parse_datetime(doc["criado_em"])
    dias_atraso = max(0, (now - criado).days)
    text = logic.reminder_text(client, doc, dias_atraso)

    sb.table("responde_messages").insert({
        "client_id": client["id"], "direction": "out", "text": text, "intent": "cobranca",
        "status": "sent", "mode_used": "automatico", "created_at": now_str,
    }).execute()
    sb.table("responde_documents").update({"ultimo_lembrete_em": now_str}).eq("id", document_id).execute()
    return jsonify({"ok": True, "text": text})


@app.route("/api/documents/<int:document_id>/receive", methods=["POST"])
def receive(document_id):
    db.sb().table("responde_documents").update({"status": "recebido"}).eq("id", document_id).execute()
    return jsonify({"ok": True})


@app.route("/api/complaints", methods=["POST"])
def add_complaint():
    client_id = request.json.get("client_id")
    texto = (request.json.get("texto") or "Reclamação registrada pelo contador.").strip()
    now_str = db.iso(db.now())
    db.sb().table("responde_complaints").insert({
        "client_id": client_id, "texto": texto, "criado_em": now_str,
    }).execute()
    return jsonify({"ok": True})


@app.route("/api/time/advance", methods=["POST"])
def advance_time():
    days = int(request.json.get("days", 1))
    sb = db.sb()
    res = sb.table("responde_settings").select("value").eq("key", "time_offset_days").execute()
    current = int(res.data[0]["value"]) if res.data else 0
    new_value = current + days
    sb.table("responde_settings").upsert({"key": "time_offset_days", "value": str(new_value)}).execute()
    return jsonify({"ok": True, "time_offset_days": new_value})


@app.route("/api/reset", methods=["POST"])
def reset():
    db.seed()
    return jsonify({"ok": True})
