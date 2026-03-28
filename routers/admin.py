from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from database import get_db
from routers.auth import get_current_user
from datetime import datetime, timedelta, date
from collections import defaultdict
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import shutil
import uuid

router = APIRouter(prefix="/admin", tags=["Administration"])


# --- SCHÉMAS DE DONNÉES ---
class MailingRequest(BaseModel):
    subject: str
    message: str


# Nouveau schéma pour agréger les données de graphique
class DateDataPoint(BaseModel):
    date: str  # format YYYY-MM-DD
    registrations: int = 0
    logins: int = 0
    graphs_created: int = 0
    nodes_created: int = 0


# Schéma pour les Top Users
class TopUser(BaseModel):
    name: str
    email: str
    score: int  # Total de noeuds générés


# Schéma complet de l'analytics
class AnalyticsData(BaseModel):
    # KPIs Flash
    active_users_daily: int  # DAU (Last 24h)
    stickiness: float  # % DAU / MAU
    retention_rate_w1: float  # % inscrit il y a 7j et revenu
    avg_nodes_per_graph: float

    # Données temporelles pour graphiques
    registration_trend: list[DateDataPoint]  # Inscriptions cumulées
    activity_trend: list[DateDataPoint]  # Logins journaliers
    creation_trend: list[DateDataPoint]  # Graphes/Noeuds journaliers

    # Top Lists
    top_power_users: list[TopUser]  # Plus de noeuds
    top_churn_risks: list[TopUser]  # Actifs et inactifs (login < 30j, nodes > 20)


# --- VIGILE ---
def get_current_admin(current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        record = session.run("MATCH (u:User {id: $uid}) RETURN u.role AS role", uid=current_user["id"]).single()
        if not record or record["role"] != "superadmin":
            raise HTTPException(status_code=403, detail="Accès refusé.")
    return current_user


# --- ROUTE ANALYTICS AVANCÉE ---
@router.get("/analytics", response_model=AnalyticsData)
def get_advanced_analytics(admin: dict = Depends(get_current_admin)):
    driver = get_db()
    now = datetime.utcnow()
    one_day_ago = now - timedelta(days=1)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    # Helper pour grouper les données par date (sur 30 jours)
    date_aggregation = defaultdict(lambda: {"regs": 0, "logins": 0, "graphs": 0, "nodes": 0})

    with driver.session() as session:
        # 🚀 1. KPIs COMPORTEMENTAUX

        # DAU (Daily Active Users)
        query_dau = "MATCH (u:User) WHERE u.last_login > datetime($time) RETURN count(u) AS count"
        dau = session.run(query_dau, time=one_day_ago.isoformat()).single()["count"]

        # MAU (Monthly Active Users)
        query_mau = "MATCH (u:User) WHERE u.last_login > datetime($time) RETURN count(u) AS count"
        mau = session.run(query_mau, time=thirty_days_ago.isoformat()).single()["count"]

        stickiness = round((dau / mau * 100), 1) if mau > 0 else 0.0

        # Rétention Semaine 1 (Inscrit entre J-8 et J-7 et revenu < 7 jours)
        query_retention = """
        MATCH (u:User)
        WHERE u.created_at >= datetime($t8) AND u.created_at < datetime($t7)
        WITH count(u) AS total_cohort
        MATCH (u:User)
        WHERE u.created_at >= datetime($t8) AND u.created_at < datetime($t7) AND u.last_login > datetime($t7)
        RETURN total_cohort, count(u) AS returned_cohort
        """
        retention_res = session.run(query_retention, t8=(now - timedelta(days=8)).isoformat(),
                                    t7=seven_days_ago.isoformat()).single()
        retention_w1 = round((retention_res["returned_cohort"] / retention_res["total_cohort"] * 100), 1) if \
        retention_res["total_cohort"] > 0 else 0.0

        # Engagement (Noeuds moyen par graphe)
        query_engagement = """
        MATCH (g:Graph)
        OPTIONAL MATCH (g)-[:HAS_NODE]->(n)
        WITH g, count(n) AS node_count
        WHERE node_count > 0
        RETURN avg(node_count) AS avg_nodes
        """
        avg_nodes = round(session.run(query_engagement).single()["avg_nodes"] or 0.0, 1)

        # 🚀 2. DONNÉES TEMPORELLES POUR GRAPHIQUES (30 DERNIERS JOURS)

        # Registrations Journalières
        query_regs = "MATCH (u:User) WHERE u.created_at > datetime($time) RETURN date(u.created_at) AS date, count(u) AS count"
        res_regs = session.run(query_regs, time=thirty_days_ago.isoformat())
        for rec in res_regs: date_aggregation[str(rec["date"])]["regs"] += rec["count"]

        # Logins Journaliers
        query_logins = "MATCH (u:User) WHERE u.last_login > datetime($time) RETURN date(u.last_login) AS date, count(u) AS count"
        res_logins = session.run(query_logins, time=thirty_days_ago.isoformat())
        for rec in res_logins: date_aggregation[str(rec["date"])]["logins"] += rec["count"]

        # Création Graphes/Noeuds Journaliers
        query_creation = """
        MATCH (u:User)-[:OWNS]->(g:Graph)
        WHERE g.created_at > datetime($time)
        OPTIONAL MATCH (g)-[:HAS_NODE]->(n)
        WHERE n.created_at > datetime($time)
        RETURN date(g.created_at) AS date, count(DISTINCT g) AS graphs, count(n) AS nodes
        """
        res_creation = session.run(query_creation, time=thirty_days_ago.isoformat())
        for rec in res_creation:
            date_aggregation[str(rec["date"])]["graphs"] += rec["graphs"]
            date_aggregation[str(rec["date"])]["nodes"] += rec["nodes"]

        # Formater les tendances pour le frontend
        registration_trend = []
        cumulative_registrations = 0

        # On remplit les 30 derniers jours (Y compris les jours vides)
        for i in range(30):
            day = (thirty_days_ago + timedelta(days=i)).strftime("%Y-%m-%d")
            cumulative_registrations += date_aggregation[day]["regs"]

            registration_trend.append(DateDataPoint(date=day, registrations=cumulative_registrations))
            date_aggregation[day]["date"] = day  # On s'assure que la date est dedans pour les autres trends

        # 🚀 3. TOP LISTS (Les "Cachés" de Neo4j)

        # Power Users (Les plus actifs par noeuds)
        query_power = """
        MATCH (u:User)-[:OWNS]->(g:Graph)-[:HAS_NODE]->(n)
        RETURN 
            coalesce(u.first_name, 'Utilisateur') + ' ' + coalesce(u.last_name, '(Inconnu)') AS name,
            u.email AS email,
            count(n) AS score
        ORDER BY score DESC LIMIT 5
        """
        top_power_users = [TopUser(**dict(rec)) for rec in session.run(query_power)]

        # Churn Risk (Inactifs depuis 30j mais ont déjà créé +20 noeuds)
        query_churn = """
        MATCH (u:User)-[:OWNS]->(g:Graph)-[:HAS_NODE]->(n)
        WHERE u.last_login <= datetime($thirty) OR u.last_login IS NULL
        WITH u, count(n) AS nodes
        WHERE nodes > 20
        RETURN 
            coalesce(u.first_name, 'Utilisateur') + ' ' + coalesce(u.last_name, '(Inconnu)') AS name,
            u.email AS email,
            nodes AS score
        ORDER BY u.last_login ASC LIMIT 5
        """
        top_churn_risks = [TopUser(**dict(rec)) for rec in session.run(query_churn, thirty=thirty_days_ago.isoformat())]

        return AnalyticsData(
            active_users_daily=dau, stickiness=stickiness, retention_rate_w1=retention_w1,
            avg_nodes_per_graph=avg_nodes,
            registration_trend=registration_trend,
            activity_trend=[DateDataPoint(date=day, logins=data["logins"]) for day, data in date_aggregation.items() if
                            "date" in data],
            creation_trend=[DateDataPoint(date=day, graphs_created=data["graphs"], nodes_created=data["nodes"]) for
                            day, data in date_aggregation.items() if "date" in data],
            top_power_users=top_power_users,
            top_churn_risks=top_churn_risks
        )
# ... le reste du fichier (Upload, Mailing, Users...) reste identique