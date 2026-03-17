import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase

app = FastAPI(title="BibleGraph API", description="API pour le graphe de méditation biblique")

# 🟢 AJOUT DU CORS ICI 🟢
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Autorise tous les sites (on affinera en prod)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")

driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

@app.get("/")
def read_root():
    return {"message": "Bienvenue sur l'API BibleGraph 🚀"}

@app.get("/books")
def get_books():
    """Récupère la liste de tous les livres de la Bible"""
    with driver.session() as session:
        result = session.run("MATCH (b:Book) RETURN b.name AS name, b.testament AS testament")
        books = [{"name": record["name"], "testament": record["testament"]} for record in result]
        return {"books": books}

@app.get("/chapter/{book_name}/{chapter_number}")
def get_chapter(book_name: str, chapter_number: int):
    """Récupère tous les versets d'un chapitre spécifique"""
    with driver.session() as session:
        query = """
        MATCH (c:Chapter {book: $book_name, number: $chapter_number})-[:CONTAINS]->(v:Verse)
        RETURN v.number AS number, v.text AS text
        ORDER BY v.number
        """
        result = session.run(query, book_name=book_name, chapter_number=chapter_number)
        verses = [{"verse": record["number"], "text": record["text"]} for record in result]
        
        if not verses:
            raise HTTPException(status_code=404, detail="Livre ou chapitre introuvable")
            
        return {
            "book": book_name,
            "chapter": chapter_number,
            "verses": verses
        }

@app.on_event("shutdown")
def shutdown_db_client():
    driver.close()
