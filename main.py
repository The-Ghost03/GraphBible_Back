import os
from fastapi import FastAPI, HTTPException
from neo4j import GraphDatabase

app = FastAPI(title="BibleGraph API", description="API pour le graphe de méditation biblique")

URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")

driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

@app.get("/")
def read_root():
    return {"message": "Bienvenue sur l'API BibleGraph 🚀"}

@app.get("/test-db")
def test_db_connection():
    try:
        with driver.session() as session:
            result = session.run("RETURN 'Connexion à Neo4j réussie !' AS message")
            record = result.single()
            return {"status": "success", "neo4j_message": record["message"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de connexion à Neo4j : {str(e)}")

@app.on_event("shutdown")
def shutdown_db_client():
    driver.close()
