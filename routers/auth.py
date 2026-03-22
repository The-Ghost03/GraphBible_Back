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

router = APIRouter(prefix="/auth", tags=["Authentication"])

SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-biblegraph-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

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

        print(f"⏳ Tentative de connexion SMTP à {smtp_host} sur le port {smtp_port}...", flush=True)

        # 🚀 LA CORRECTION EST ICI : 465 = SSL, les autres = TLS
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

    # 🚀 C'EST ICI QU'ON APPELLE ENFIN LA FONCTION !
    send_otp_email(user.email, otp)

    # 🚀 ET IL NE FAUT PAS OUBLIER DE RÉPONDRE AU FRONTEND
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
        if not record["u"]["is_verified"]:
            raise HTTPException(status_code=403, detail="Vérifiez votre compte d'abord")

        token = create_access_token(data={"sub": record["u"]["email"], "id": record["u"]["id"]})
        return {"access_token": token, "token_type": "bearer"}