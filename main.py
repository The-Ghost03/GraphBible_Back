from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import uuid, os
from fastapi.staticfiles import StaticFiles

from routers import auth, graphs, nodes, admin
from database import get_db
from routers.auth import get_password_hash
from limiter import limiter

app = FastAPI(title="BibleGraph SaaS API", description="API complète pour le Knowledge Graph Biblique")

# ── Rate limiter ──────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://biblegraphe.softskills.ci",
        "http://biblegraphe.softskills.ci",
        "http://161.97.105.109:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files ──────────────────────────────────────────────────────────────
os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(graphs.router)
app.include_router(nodes.router)
app.include_router(admin.router)


# ── Routes racine ─────────────────────────────────────────────────────────────
@app.get("/")
def read_root():
    return {"message": "BibleGraph API est en ligne 🚀"}


@app.get("/health")
def health_check():
    """Health check pour le monitoring et le CI/CD."""
    try:
        driver = get_db()
        driver.verify_connectivity()
        return {"status": "ok", "db": "connected"}
    except Exception:
        return {"status": "ok", "db": "unreachable"}


@app.get("/books")
def get_books():
    driver = get_db()
    with driver.session() as session:
        result = session.run("MATCH (b:Book) RETURN b.name AS name, b.testament AS testament")
        return {"books": [{"name": r["name"], "testament": r["testament"]} for r in result]}


@app.get("/books/{book_name}/metadata")
def get_book_metadata(book_name: str):
    driver = get_db()
    with driver.session() as session:
        result = session.run("""
            MATCH (c:Chapter {book: $book_name})-[:CONTAINS]->(v:Verse)
            RETURN c.number AS chapter, max(toInteger(v.number)) AS max_verses
            ORDER BY toInteger(c.number)
        """, book_name=book_name)
        return {"metadata": [{"chapter": r["chapter"], "max_verses": r["max_verses"]} for r in result]}


@app.get("/chapter/{book_name}/{chapter_number}")
def get_chapter(book_name: str, chapter_number: int):
    driver = get_db()
    with driver.session() as session:
        result = session.run("""
            MATCH (c:Chapter {book: $book_name, number: $chapter_number})-[:CONTAINS]->(v:Verse)
            RETURN v.number AS number, v.text AS text ORDER BY v.number
        """, book_name=book_name, chapter_number=chapter_number)
        verses = [{"verse": r["number"], "text": r["text"]} for r in result]
        if not verses:
            raise HTTPException(status_code=404, detail="Introuvable")
        return {"book": book_name, "chapter": chapter_number, "verses": verses}


@app.on_event("startup")
def startup_db_client():
    driver = get_db()
    try:
        driver.verify_connectivity()
        print("✅ Connecté à Neo4j avec succès !")
        admin_email = os.getenv("ADMIN_EMAIL")
        admin_password = os.getenv("ADMIN_PASSWORD")
        if not admin_email or not admin_password:
            print("⚠️  ADMIN_EMAIL / ADMIN_PASSWORD non définis — compte superadmin non créé.")
        else:
            with driver.session() as session:
                if not session.run("MATCH (u:User {email: $email}) RETURN u", email=admin_email).single():
                    hashed_pwd = get_password_hash(admin_password)
                    admin_id = str(uuid.uuid4())
                    session.run("""
                        CREATE (u:User {
                            id: $id, email: $email, password_hash: $pwd,
                            is_verified: true, role: 'superadmin',
                            first_name: 'Super', last_name: 'Admin',
                            created_at: datetime()
                        })
                    """, id=admin_id, email=admin_email, pwd=hashed_pwd)
                    print(f"👑 Compte Super Admin généré ({admin_email})")
    except Exception as e:
        print(f"❌ Erreur de connexion à Neo4j : {e}")
