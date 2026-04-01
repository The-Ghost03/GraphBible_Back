from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from database import get_db
from routers.auth import get_current_user
from datetime import datetime, timedelta
from collections import defaultdict
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import shutil
import uuid
from typing import Optional

router = APIRouter(prefix="/admin", tags=["Administration"])


# --- SCHÉMAS DE DONNÉES ---
class MailingRequest(BaseModel):
    subject: str
    message: str


class DateDataPoint(BaseModel):
    date: str
    registrations: int = 0
    logins: int = 0
    graphs_created: int = 0
    nodes_created: int = 0


class TopUser(BaseModel):
    name: str
    email: str
    score: int


class AnalyticsData(BaseModel):
    total_nodes: int  # 🚀 NOUVEAU : On réintègre le total absolu
    active_users_daily: int
    stickiness: float
    retention_rate_w1: float
    avg_nodes_per_graph: float
    registration_trend: list[DateDataPoint]
    activity_trend: list[DateDataPoint]
    creation_trend: list[DateDataPoint]
    top_power_users: list[TopUser]
    top_churn_risks: list[TopUser]


# --- VIGILE ---
def get_current_admin(current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        record = session.run("MATCH (u:User {id: $uid}) RETURN u.role AS role", uid=current_user["id"]).single()
        if not record or record["role"] != "superadmin":
            raise HTTPException(status_code=403, detail="Accès refusé.")
    return current_user


# --- ROUTES ANALYTICS ---
@router.get("/analytics", response_model=AnalyticsData)
def get_advanced_analytics(admin: dict = Depends(get_current_admin)):
    driver = get_db()
    now = datetime.utcnow()
    one_day_ago = now - timedelta(days=1)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    date_aggregation = defaultdict(lambda: {"regs": 0, "logins": 0, "graphs": 0, "nodes": 0})

    with driver.session() as session:
        # 🚀 NOUVEAU : Compte de tous les noeuds de la base
        total_nodes = session.run("MATCH (g:Graph)-[:HAS_NODE]->(n) RETURN count(n) AS count").single()["count"]

        # DAU & MAU
        dau = session.run("MATCH (u:User) WHERE u.last_login > datetime($time) RETURN count(u) AS count",
                          time=one_day_ago.isoformat()).single()["count"]
        mau = session.run("MATCH (u:User) WHERE u.last_login > datetime($time) RETURN count(u) AS count",
                          time=thirty_days_ago.isoformat()).single()["count"]
        stickiness = round((dau / mau * 100), 1) if mau > 0 else 0.0

        # Rétention S1
        query_retention = """
        MATCH (u:User)
        WHERE u.created_at >= datetime($t8) AND u.created_at < datetime($t7)
        WITH count(u) AS total_cohort
        OPTIONAL MATCH (u:User)
        WHERE u.created_at >= datetime($t8) AND u.created_at < datetime($t7) AND u.last_login > datetime($t7)
        RETURN total_cohort, count(u) AS returned_cohort
        """
        retention_res = session.run(query_retention, t8=(now - timedelta(days=8)).isoformat(),
                                    t7=seven_days_ago.isoformat()).single()

        retention_w1 = 0.0
        if retention_res and retention_res["total_cohort"] > 0:
            retention_w1 = round((retention_res["returned_cohort"] / retention_res["total_cohort"] * 100), 1)

        # Engagement
        avg_nodes = round(session.run(
            "MATCH (g:Graph) OPTIONAL MATCH (g)-[:HAS_NODE]->(n) WITH g, count(n) AS node_count WHERE node_count > 0 RETURN avg(node_count) AS avg_nodes").single()[
                              "avg_nodes"] or 0.0, 1)

        # Tendances
        for rec in session.run(
                "MATCH (u:User) WHERE u.created_at > datetime($time) RETURN date(u.created_at) AS date, count(u) AS count",
                time=thirty_days_ago.isoformat()):
            date_aggregation[str(rec["date"])]["regs"] += rec["count"]
        for rec in session.run(
                "MATCH (u:User) WHERE u.last_login > datetime($time) RETURN date(u.last_login) AS date, count(u) AS count",
                time=thirty_days_ago.isoformat()):
            date_aggregation[str(rec["date"])]["logins"] += rec["count"]
        for rec in session.run(
                "MATCH (u:User)-[:OWNS]->(g:Graph) WHERE g.created_at > datetime($time) OPTIONAL MATCH (g)-[:HAS_NODE]->(n) WHERE n.created_at > datetime($time) RETURN date(g.created_at) AS date, count(DISTINCT g) AS graphs, count(n) AS nodes",
                time=thirty_days_ago.isoformat()):
            date_aggregation[str(rec["date"])]["graphs"] += rec["graphs"]
            date_aggregation[str(rec["date"])]["nodes"] += rec["nodes"]

        registration_trend = []
        cumulative_registrations = 0
        for i in range(30):
            day = (thirty_days_ago + timedelta(days=i)).strftime("%Y-%m-%d")
            cumulative_registrations += date_aggregation[day]["regs"]
            registration_trend.append(DateDataPoint(date=day, registrations=cumulative_registrations))
            date_aggregation[day]["date"] = day

        # Top Lists
        top_power_users = [TopUser(**dict(rec)) for rec in session.run(
            "MATCH (u:User)-[:OWNS]->(g:Graph)-[:HAS_NODE]->(n) RETURN coalesce(u.first_name, 'Utilisateur') + ' ' + coalesce(u.last_name, '') AS name, u.email AS email, count(n) AS score ORDER BY score DESC LIMIT 5")]
        top_churn_risks = [TopUser(**dict(rec)) for rec in session.run(
            "MATCH (u:User)-[:OWNS]->(g:Graph)-[:HAS_NODE]->(n) WHERE u.last_login <= datetime($thirty) OR u.last_login IS NULL WITH u, count(n) AS nodes WHERE nodes > 20 RETURN coalesce(u.first_name, 'Utilisateur') + ' ' + coalesce(u.last_name, '') AS name, u.email AS email, nodes AS score ORDER BY u.last_login ASC LIMIT 5",
            thirty=thirty_days_ago.isoformat())]

        return AnalyticsData(
            total_nodes=total_nodes,  # 🚀 NOUVEAU
            active_users_daily=dau, stickiness=stickiness, retention_rate_w1=retention_w1,
            avg_nodes_per_graph=avg_nodes,
            registration_trend=registration_trend,
            activity_trend=[DateDataPoint(date=day, logins=data["logins"]) for day, data in date_aggregation.items() if
                            "date" in data],
            creation_trend=[DateDataPoint(date=day, graphs_created=data["graphs"], nodes_created=data["nodes"]) for
                            day, data in date_aggregation.items() if "date" in data],
            top_power_users=top_power_users, top_churn_risks=top_churn_risks
        )


# --- ROUTES USERS ---

@router.get("/users")
def get_all_users(
        skip: int = 0,
        limit: int = 10,
        search: Optional[str] = None,
        admin: dict = Depends(get_current_admin)
):
    driver = get_db()
    with driver.session() as session:
        # 1. Requête de base pour récupérer les utilisateurs
        match_clause = "MATCH (u:User)"
        where_clause = ""
        params = {"skip": skip, "limit": limit}

        # Si une recherche est demandée, on filtre sur l'email, le nom ou le prénom
        if search:
            where_clause = " WHERE toLower(u.email) CONTAINS toLower($search) OR toLower(u.first_name) CONTAINS toLower($search) OR toLower(u.last_name) CONTAINS toLower($search)"
            params["search"] = search

        # 2. On compte le total d'utilisateurs (pour la pagination)
        count_query = f"{match_clause}{where_clause} RETURN count(u) as total"
        total_users = session.run(count_query, **params).single()["total"]

        # 3. On récupère les utilisateurs avec pagination
        query = f"""
        {match_clause}{where_clause}
        OPTIONAL MATCH (u)-[:OWNS]->(g:Graph)
        RETURN 
            u.id AS id, u.email AS email, u.first_name AS first_name, u.last_name AS last_name, 
            u.role AS role, u.is_verified AS is_verified, coalesce(u.is_banned, false) AS is_banned,
            toString(u.last_login) AS last_login, toString(u.created_at) AS created_at,
            count(g) AS total_graphs
        ORDER BY created_at DESC
        SKIP $skip LIMIT $limit
        """

        result = session.run(query, **params)
        users = [dict(record) for record in result]

        # On renvoie les utilisateurs ET le total pour que le front sache combien de pages il y a
        return {
            "users": users,
            "total": total_users,
            "skip": skip,
            "limit": limit
        }

@router.put("/users/{user_id}/ban")
def toggle_ban_user(user_id: str, admin: dict = Depends(get_current_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas vous bannir vous-même.")
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            "MATCH (u:User {id: $uid}) SET u.is_banned = NOT coalesce(u.is_banned, false) RETURN u.is_banned AS is_banned",
            uid=user_id).single()
        if not result:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        return {"message": f"Utilisateur {'banni' if result['is_banned'] else 'débanni'} avec succès."}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, admin: dict = Depends(get_current_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas vous supprimer.")
    driver = get_db()
    with driver.session() as session:
        session.run(
            "MATCH (u:User {id: $uid}) OPTIONAL MATCH (u)-[:OWNS]->(g:Graph) OPTIONAL MATCH (g)-[:HAS_NODE]->(n) DETACH DELETE n, g, u",
            uid=user_id)
        return {"message": "Utilisateur supprimé."}


# --- ROUTE MAILING ---
@router.post("/mailing")
def send_mass_email(request: MailingRequest, admin: dict = Depends(get_current_admin)):
    driver = get_db()
    with driver.session() as session:
        emails = [record["email"] for record in session.run(
            "MATCH (u:User) WHERE u.is_verified = true AND coalesce(u.is_banned, false) = false AND u.id <> $uid RETURN u.email AS email",
            uid=admin["id"])]

    if not emails:
        raise HTTPException(status_code=400, detail="Aucun utilisateur éligible.")

    smtp_host, smtp_port, smtp_user, smtp_pass, from_email = os.getenv("SMTP_HOST"), int(
        os.getenv("SMTP_PORT", 465)), os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"), os.getenv("SMTP_FROM_EMAIL",
                                                                                                    os.getenv(
                                                                                                        "SMTP_USER"))

    if not smtp_host:
        return {"message": f"Simulation réussie. {len(emails)} emails envoyés."}

    try:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port) if smtp_port == 465 else smtplib.SMTP(smtp_host, smtp_port)
        if smtp_port != 465: server.starttls()
        server.login(smtp_user, smtp_pass)
        for email in emails:
            msg = MIMEMultipart()
            msg['From'], msg['To'], msg['Subject'] = f"BibleGraph <{from_email}>", email, request.subject
            msg.attach(MIMEText(request.message, 'html', 'utf-8'))
            server.send_message(msg)
        server.quit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": f"Campagne envoyée à {len(emails)} utilisateurs."}


# --- ROUTE UPLOAD ---
@router.post("/upload")
def upload_image(file: UploadFile = File(...), admin: dict = Depends(get_current_admin)):
    file_extension = file.filename.split(".")[-1]
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    file_path = f"static/uploads/{unique_filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"url": f"https://biblegraphe.softskills.ci/api/{file_path}"}