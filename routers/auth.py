from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from jose import jwt, JWTError
import random
import os
import uuid
import bcrypt
from database import get_db
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

router = APIRouter(prefix="/auth", tags=["Authentication"])

SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-biblegraph-2026")
ALGORITHM = "HS256"
# 🚀 Durée de session ajustée à 2 heures (120 minutes)
ACCESS_TOKEN_EXPIRE_MINUTES = 120

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


# --- SCHÉMAS ---
class UserCreate(BaseModel):
    email: EmailStr
    password: str


class OTPVerify(BaseModel):
    email: EmailStr
    otp: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    birth_date: Optional[str] = None
    profile_picture_url: Optional[str] = None


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str


# 🚀 NOUVEAUX SCHÉMAS POUR LE MOT DE PASSE OUBLIÉ
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str


# --- HELPERS (FONCTIONS OUTILS) ---
def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(pwd_bytes, salt)
    return hashed_password.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_byte_enc = plain_password.encode('utf-8')
    hashed_password_byte_enc = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_byte_enc, hashed_password_byte_enc)


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(status_code=401, detail="Token invalide ou expiré")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        user_id: str = payload.get("id")
        if email is None or user_id is None:
            raise credentials_exception
        return {"email": email, "id": user_id}
    except JWTError:
        raise credentials_exception


def send_otp_email(email: str, otp: str):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", 465))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM_EMAIL", smtp_user)

    if not smtp_host or not smtp_user or not smtp_pass:
        print(f"⚠️ [MODE SIMULATION] OTP pour {email} : {otp}", flush=True)
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = f"BibleGraph <{from_email}>"
        msg['To'] = email
        msg['Subject'] = "🔐 Votre code de connexion BibleGraph"

        body = f"""Bonjour,

Voici votre code de sécurité pour vous connecter à votre espace BibleGraph :

{otp}

Ce code est valide pendant 10 minutes.

À très vite sur votre espace d'étude !
L'équipe BibleGraph."""

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()

        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()

        print(f"✅ Vrai E-mail envoyé avec succès à {email} via {smtp_host}", flush=True)

    except Exception as e:
        print(f"❌ Erreur CRITIQUE lors de l'envoi SMTP : {e}", flush=True)
        print(f"⚠️ [SECOURS] OTP pour {email} : {otp}", flush=True)


# 🚀 NOUVELLE FONCTION D'ENVOI D'E-MAIL DE RÉINITIALISATION
def send_reset_password_email(email: str, otp: str):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", 465))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM_EMAIL", smtp_user)

    if not smtp_host or not smtp_user or not smtp_pass:
        print(f"⚠️ [MODE SIMULATION] Reset Password OTP pour {email} : {otp}", flush=True)
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = f"BibleGraph <{from_email}>"
        msg['To'] = email
        msg['Subject'] = "🔒 Réinitialisation de votre mot de passe BibleGraph"

        body = f"""Bonjour,

Nous avons reçu une demande de réinitialisation de mot de passe pour votre compte BibleGraph.
Voici votre code de vérification à 6 chiffres :

{otp}

Si vous n'avez pas demandé cette réinitialisation, vous pouvez ignorer cet e-mail en toute sécurité.

L'équipe BibleGraph."""

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()

        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print(f"✅ E-mail de réinitialisation envoyé avec succès à {email}", flush=True)

    except Exception as e:
        print(f"❌ Erreur lors de l'envoi SMTP (Reset) : {e}", flush=True)
        print(f"⚠️ [SECOURS] Reset OTP pour {email} : {otp}", flush=True)


# --- ROUTES ---
@router.post("/register")
def register_user(user: UserCreate):
    driver = get_db()
    with driver.session() as session:
        if session.run("MATCH (u:User {email: $email}) RETURN u", email=user.email).single():
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

        hashed_pwd = get_password_hash(user.password)
        otp = str(random.randint(100000, 999999))
        user_id = str(uuid.uuid4())

        session.run("""
        CREATE (u:User {
            id: $id, email: $email, password_hash: $pwd, otp: $otp, is_verified: false, created_at: datetime()
        })
        """, id=user_id, email=user.email, pwd=hashed_pwd, otp=otp)

    send_otp_email(user.email, otp)
    return {"message": "Utilisateur créé. Un email contenant votre code OTP a été envoyé."}


@router.post("/verify-otp")
def verify_otp(data: OTPVerify):
    driver = get_db()
    with driver.session() as session:
        record = session.run("MATCH (u:User {email: $email}) RETURN u.otp AS otp, u.is_verified AS is_verified",
                             email=data.email).single()
        if not record or record["otp"] != data.otp:
            raise HTTPException(status_code=400, detail="OTP invalide")
        session.run("MATCH (u:User {email: $email}) SET u.is_verified = true, u.otp = null", email=data.email)
        return {"message": "Compte vérifié !"}


@router.post("/login")
def login(user: UserLogin):
    driver = get_db()
    with driver.session() as session:
        record = session.run("MATCH (u:User {email: $email}) RETURN u", email=user.email).single()

        if not record or not verify_password(user.password, record["u"]["password_hash"]):
            raise HTTPException(status_code=400, detail="Email ou mot de passe incorrect")

        # 🚀 VÉRIFICATION DU BANNISSEMENT
        if record["u"].get("is_banned", False):
            raise HTTPException(status_code=403, detail="Ce compte a été suspendu par un administrateur.")

        if not record["u"]["is_verified"]:
            otp = str(random.randint(100000, 999999))
            session.run("MATCH (u:User {email: $email}) SET u.otp = $otp", email=user.email, otp=otp)
            send_otp_email(user.email, otp)
            raise HTTPException(status_code=403, detail="Compte non vérifié. Un nouveau code a été envoyé.")

        # 🚀 ENREGISTREMENT DE LA DERNIÈRE CONNEXION
        session.run("MATCH (u:User {email: $email}) SET u.last_login = datetime()", email=user.email)

        token = create_access_token(data={"sub": record["u"]["email"], "id": record["u"]["id"]})
        return {"access_token": token, "token_type": "bearer"}

# 🚀 NOUVELLES ROUTES : MOT DE PASSE OUBLIÉ
@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest):
    driver = get_db()
    with driver.session() as session:
        user = session.run("MATCH (u:User {email: $email}) RETURN u", email=request.email).single()

        # On renvoie toujours le même message pour ne pas fuiter l'existence d'un compte
        if not user:
            return {"message": "Si cet e-mail est associé à un compte, un code vous a été envoyé."}

        otp = str(random.randint(100000, 999999))
        session.run("MATCH (u:User {email: $email}) SET u.otp = $otp", email=request.email, otp=otp)

    send_reset_password_email(request.email, otp)
    return {"message": "Si cet e-mail est associé à un compte, un code vous a été envoyé."}


@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest):
    driver = get_db()
    with driver.session() as session:
        record = session.run("MATCH (u:User {email: $email}) RETURN u.otp AS otp", email=request.email).single()

        if not record or record["otp"] != request.otp:
            raise HTTPException(status_code=400, detail="Code de vérification invalide ou expiré.")

        hashed_pwd = get_password_hash(request.new_password)
        session.run("""
        MATCH (u:User {email: $email}) 
        SET u.password_hash = $pwd, u.otp = null
        """, email=request.email, pwd=hashed_pwd)

    return {"message": "Votre mot de passe a été réinitialisé avec succès. Vous pouvez vous connecter."}


# --- ROUTES PROFIL UTILISATEUR ---

@router.get("/me")
def get_my_profile(current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        record = session.run("MATCH (u:User {id: $uid}) RETURN u", uid=current_user["id"]).single()
        if not record:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")

        user_node = record["u"]
        return {
            "id": user_node.get("id"),
            "email": user_node.get("email"),
            "first_name": user_node.get("first_name", ""),
            "last_name": user_node.get("last_name", ""),
            "phone": user_node.get("phone", ""),
            "birth_date": user_node.get("birth_date", ""),
            "profile_picture_url": user_node.get("profile_picture_url", ""),
            "role": user_node.get("role", "user"),
            "created_at": user_node.get("created_at")
        }


@router.put("/me")
def update_profile(profile_data: UserProfileUpdate, current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        updates = {k: v for k, v in profile_data.dict(exclude_unset=True).items() if v is not None}

        if updates:
            query = "MATCH (u:User {id: $uid}) SET " + ", ".join([f"u.{k} = ${k}" for k in updates.keys()])
            session.run(query, uid=current_user["id"], **updates)

        return {"message": "Profil mis à jour avec succès"}


@router.put("/me/password")
def update_password(passwords: PasswordUpdate, current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        record = session.run("MATCH (u:User {id: $uid}) RETURN u", uid=current_user["id"]).single()
        if not record or not verify_password(passwords.current_password, record["u"]["password_hash"]):
            raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")

        new_hashed_pwd = get_password_hash(passwords.new_password)
        session.run("MATCH (u:User {id: $uid}) SET u.password_hash = $new_pwd",
                    uid=current_user["id"], new_pwd=new_hashed_pwd)

        return {"message": "Mot de passe modifié avec succès"}


@router.delete("/me")
def delete_my_account(current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        session.run("""
        MATCH (u:User {id: $uid})
        OPTIONAL MATCH (u)-[:OWNS]->(g:Graph)
        OPTIONAL MATCH (g)-[:HAS_NODE]->(n:Node)
        DETACH DELETE n, g, u
        """, uid=current_user["id"])

        return {"message": "Compte et données supprimés définitivement"}