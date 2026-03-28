from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import get_db
from routers.auth import get_current_user
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
import shutil
import uuid

router = APIRouter(prefix="/admin", tags=["Administration"])

# --- SCHÉMAS ---
class MailingRequest(BaseModel):
    subject: str
    message: str

# --- VIGILE ---
def get_current_admin(current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        record = session.run("MATCH (u:User {id: $uid}) RETURN u.role AS role", uid=current_user["id"]).single()
        if not record or record["role"] != "superadmin":
            raise HTTPException(status_code=403, detail="Accès refusé.")
    return current_user

# --- ROUTES STATS & USERS ---

@router.get("/stats")
def get_dashboard_stats(admin: dict = Depends(get_current_admin)):
    driver = get_db()
    with driver.session() as session:
        users_count = session.run("MATCH (u:User) RETURN count(u) AS count").single()["count"]
        graphs_count = session.run("MATCH (g:Graph) RETURN count(g) AS count").single()["count"]
        # 🚀 CORRECTION : Compte tous les noeuds attachés à un graphe
        nodes_count = session.run("MATCH (g:Graph)-[:HAS_NODE]->(n) RETURN count(n) AS count").single()["count"]
        return {"total_users": users_count, "total_graphs": graphs_count, "total_nodes": nodes_count}



@router.get("/users")
def get_all_users(admin: dict = Depends(get_current_admin)):
    driver = get_db()
    with driver.session() as session:
        query = """
        MATCH (u:User)
        OPTIONAL MATCH (u)-[:OWNS]->(g:Graph)
        RETURN 
            u.id AS id, u.email AS email, u.first_name AS first_name, u.last_name AS last_name, 
            u.role AS role, u.is_verified AS is_verified, 
            coalesce(u.is_banned, false) AS is_banned,
            toString(u.last_login) AS last_login,
            toString(u.created_at) AS created_at,
            count(g) AS total_graphs
        ORDER BY created_at DESC
        """
        result = session.run(query)
        return {"users": [dict(record) for record in result]}

# --- ACTIONS SUR LES UTILISATEURS ---
@router.put("/users/{user_id}/ban")
def toggle_ban_user(user_id: str, admin: dict = Depends(get_current_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas vous bannir vous-même.")
    driver = get_db()
    with driver.session() as session:
        # Inverse le statut de bannissement
        query = """
        MATCH (u:User {id: $uid})
        SET u.is_banned = NOT coalesce(u.is_banned, false)
        RETURN u.is_banned AS is_banned
        """
        result = session.run(query, uid=user_id).single()
        if not result:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        status = "banni" if result["is_banned"] else "débanni"
        return {"message": f"Utilisateur {status} avec succès."}

@router.delete("/users/{user_id}")
def delete_user(user_id: str, admin: dict = Depends(get_current_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas supprimer votre propre compte ici.")
    driver = get_db()
    with driver.session() as session:
        session.run("""
        MATCH (u:User {id: $uid})
        OPTIONAL MATCH (u)-[:OWNS]->(g:Graph)
        OPTIONAL MATCH (g)-[:HAS_NODE]->(n)
        DETACH DELETE n, g, u
        """, uid=user_id)
        return {"message": "Utilisateur et ses données supprimés."}


@router.post("/upload")
def upload_image(file: UploadFile = File(...), admin: dict = Depends(get_current_admin)):
    # Génère un nom unique pour éviter d'écraser des fichiers
    file_extension = file.filename.split(".")[-1]
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    file_path = f"static/uploads/{unique_filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Retourne l'URL absolue (très important pour les emails)
    return {"url": f"https://biblegraphe.softskills.ci/api/{file_path}"}


# --- CAMPAGNE MAILING ---
@router.post("/mailing")
def send_mass_email(request: MailingRequest, admin: dict = Depends(get_current_admin)):
    driver = get_db()
    with driver.session() as session:
        # Récupère tous les utilisateurs vérifiés et non bannis (sauf l'admin qui envoie)
        result = session.run("MATCH (u:User) WHERE u.is_verified = true AND coalesce(u.is_banned, false) = false AND u.id <> $uid RETURN u.email AS email", uid=admin["id"])
        emails = [record["email"] for record in result]

    if not emails:
        raise HTTPException(status_code=400, detail="Aucun utilisateur éligible trouvé.")

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", 465))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM_EMAIL", smtp_user)

    if not smtp_host:
        print(f"⚠️ [SIMULATION MAILING] Sujet: {request.subject} | Destinataires: {len(emails)}")
        return {"message": f"Simulation réussie. {len(emails)} emails virtuels envoyés."}

    success_count = 0
    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
        server.login(smtp_user, smtp_pass)

        # Envoi individuel pour éviter que les utilisateurs voient les emails des autres
        for email in emails:
            msg = MIMEMultipart()
            msg['From'] = f"BibleGraph <{from_email}>"
            msg['To'] = email
            msg['Subject'] = request.subject
            msg.attach(MIMEText(request.message, 'html', 'utf-8'))
            server.send_message(msg)
            success_count += 1

        server.quit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'envoi: {str(e)}")

    return {"message": f"Campagne envoyée avec succès à {success_count} utilisateurs."}