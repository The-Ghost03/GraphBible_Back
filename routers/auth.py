from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
import random
import os
from database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Configuration de la sécurité
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-biblegraph-2026") # À changer en prod
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 7 jours

# Schémas de données (Pydantic)
class UserCreate(BaseModel):
    email: EmailStr
    password: str

class OTPVerify(BaseModel):
    email: EmailStr
    otp: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

# Fonctions utilitaires
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def generate_otp():
    return str(random.randint(100000, 999999))

# Routes API
@router.post("/register")
def register_user(user: UserCreate):
    driver = get_db()
    with driver.session() as session:
        # Vérifier si l'utilisateur existe déjà
        result = session.run("MATCH (u:User {email: $email}) RETURN u", email=user.email)
        if result.single():
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

        hashed_pwd = get_password_hash(user.password)
        otp = generate_otp()
        
        # Créer l'utilisateur dans Neo4j
        query = """
        CREATE (u:User {
            id: randomUUID(),
            email: $email, 
            password_hash: $password_hash, 
            otp: $otp,
            is_verified: false, 
            created_at: datetime()
        }) RETURN u.email
        """
        session.run(query, email=user.email, password_hash=hashed_pwd, otp=otp)
        
        # TODO: Intégrer un vrai service SMTP plus tard
        print(f"📧 [SIMULATION EMAIL] Envoyer à {user.email} -> Code OTP : {otp}")
        
        return {"message": "Utilisateur créé. Veuillez vérifier votre email pour le code OTP."}

@router.post("/verify-otp")
def verify_otp(data: OTPVerify):
    driver = get_db()
    with driver.session() as session:
        result = session.run("MATCH (u:User {email: $email}) RETURN u.otp AS otp, u.is_verified AS is_verified", email=data.email)
        record = result.single()
        
        if not record:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        if record["is_verified"]:
            return {"message": "Compte déjà vérifié"}
        if record["otp"] != data.otp:
            raise HTTPException(status_code=400, detail="Code OTP invalide")
            
        # Valider l'utilisateur et supprimer l'OTP
        session.run("MATCH (u:User {email: $email}) SET u.is_verified = true, u.otp = null", email=data.email)
        return {"message": "Compte vérifié avec succès ! Vous pouvez vous connecter."}

@router.post("/login")
def login(user: UserLogin):
    driver = get_db()
    with driver.session() as session:
        result = session.run("MATCH (u:User {email: $email}) RETURN u", email=user.email)
        record = result.single()
        
        if not record:
            raise HTTPException(status_code=400, detail="Email ou mot de passe incorrect")
            
        user_node = record["u"]
        if not user_node["is_verified"]:
            raise HTTPException(status_code=403, detail="Veuillez d'abord vérifier votre compte avec le code OTP")
            
        if not verify_password(user.password, user_node["password_hash"]):
            raise HTTPException(status_code=400, detail="Email ou mot de passe incorrect")
            
        # Générer le token JWT
        access_token = create_access_token(data={"sub": user_node["email"], "id": user_node["id"]})
        return {"access_token": access_token, "token_type": "bearer"}
