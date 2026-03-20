from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt, JWTError
import random
import os
import uuid
from database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-biblegraph-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class OTPVerify(BaseModel):
    email: EmailStr
    otp: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


def get_password_hash(password):
    return pwd_context.hash(password)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# LE VIDEUR : Vérifie le token JWT et retourne l'utilisateur
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

        print(f"📧 [EMAIL SIMULÉ] Envoyer à {user.email} -> OTP : {otp}")
        return {"message": "Utilisateur créé. Vérifiez votre email."}


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
