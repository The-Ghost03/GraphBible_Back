from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uuid

# 🚀 CORRECTION ICI : On retire 'close_db' qui n'existe pas
from database import get_db
# 🚀 CORRECTION ICI : J'ai retiré le doublon d'importation
from routers import auth, graphs, nodes
from routers.auth import get_password_hash

app = FastAPI(title="BibleGraph SaaS API", description="API complète pour le Knowledge Graph Biblique")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusion des routes
app.include_router(auth.router)
app.include_router(graphs.router)
app.include_router(nodes.router)

@app.get("/")
def read_root():
    return {"message": "BibleGraph API est en ligne 🚀"}

@app.get("/books")
def get_books():
    driver = get_db()
    with driver.session() as session:
        result = session.run("MATCH (b:Book) RETURN b.name AS name, b.testament AS testament")
        return {"books": [{"name": record["name"], "testament": record["testament"]} for record in result]}

@app.get("/chapter/{book_name}/{chapter_number}")
def get_chapter(book_name: str, chapter_number: int):
    driver = get_db()
    with driver.session() as session:
        query = """
        MATCH (c:Chapter {book: $book_name, number: $chapter_number})-[:CONTAINS]->(v:Verse)
        RETURN v.number AS number, v.text AS text
        ORDER BY v.number
        """
        result = session.run(query, book_name=book_name, chapter_number=chapter_number)
        verses = [{"verse": record["number"], "text": record["text"]} for record in result]
        if not verses:
            raise HTTPException(status_code=404, detail="Introuvable")
        return {"book": book_name, "chapter": chapter_number, "verses": verses}


@app.on_event("startup")
def startup_db_client():
    driver = get_db()
    try:
        driver.verify_connectivity()
        print("✅ Connecté à Neo4j avec succès !")

        # --- CRÉATION DU SUPER ADMIN AUTOMATIQUE ---
        with driver.session() as session:
            admin_email = "admin@admin.com"
            admin_check = session.run("MATCH (u:User {email: $email}) RETURN u", email=admin_email).single()

            if not admin_check:
                hashed_pwd = get_password_hash("password")
                admin_id = str(uuid.uuid4())
                session.run("""
                CREATE (u:User {
                    id: $id, email: $email, password_hash: $pwd, 
                    is_verified: true, role: 'superadmin', 
                    first_name: 'Super', last_name: 'Admin',
                    created_at: datetime()
                })
                """, id=admin_id, email=admin_email, pwd=hashed_pwd)
                print("👑 Compte Super Admin généré (admin@admin.com / password)")

    except Exception as e:
        print(f"❌ Erreur de connexion à Neo4j : {e}")