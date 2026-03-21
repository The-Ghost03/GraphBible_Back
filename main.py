from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from database import get_db
from routers import auth, graphs, nodes
from routers import auth, graphs

app = FastAPI(title="BibleGraph SaaS API", description="API complète pour le Knowledge Graph Biblique")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusion des routes d'authentification
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

@app.on_event("shutdown")
def shutdown_db_client():
    get_db().close()
