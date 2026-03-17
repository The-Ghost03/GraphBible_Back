import json
import os
from neo4j import GraphDatabase

# Connexion à Neo4j
URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")

driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

def create_constraints():
    """Créer des index pour que l'importation et les recherches soient ultra-rapides"""
    with driver.session() as session:
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (b:Book) REQUIRE b.name IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Chapter) REQUIRE (c.book, c.number) IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (v:Verse) REQUIRE (v.book, v.chapter, v.number) IS UNIQUE")

def seed_database():
    """Lire le JSON et envoyer les données à Neo4j"""
    print("Chargement du fichier JSON...")
    with open("bible-fr.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    with driver.session() as session:
        for testament in data.get("Testaments", []):
            testament_name = testament.get("Text")
            
            for book in testament.get("Books", []):
                book_name = book.get("Text")
                print(f"-> Importation de : {book_name}...")
                
                # 1. Créer le Livre
                session.run("""
                    MERGE (b:Book {name: $book_name})
                    SET b.testament = $testament_name
                """, book_name=book_name, testament_name=testament_name)
                
                for chapter_idx, chapter in enumerate(book.get("Chapters", [])):
                    chapter_num = chapter_idx + 1
                    
                    # 2. Créer le Chapitre et le lier au Livre
                    session.run("""
                        MATCH (b:Book {name: $book_name})
                        MERGE (c:Chapter {book: $book_name, number: $chapter_num})
                        MERGE (b)-[:CONTAINS]->(c)
                    """, book_name=book_name, chapter_num=chapter_num)
                    
                    # Préparer les versets pour une insertion en lot (Batch) pour plus de rapidité
                    verses_batch = []
                    for verse in chapter.get("Verses", []):
                        # Le premier verset de ce JSON n'a parfois pas de champ 'ID', on force 1
                        verse_num = verse.get("ID", 1) 
                        verse_text = verse.get("Text", "")
                        verses_batch.append({
                            "number": verse_num,
                            "text": verse_text
                        })
                        
                    # 3. Créer les Versets et les lier au Chapitre
                    session.run("""
                        MATCH (c:Chapter {book: $book_name, number: $chapter_num})
                        UNWIND $verses AS v_data
                        MERGE (v:Verse {book: $book_name, chapter: $chapter_num, number: v_data.number})
                        SET v.text = v_data.text
                        MERGE (c)-[:CONTAINS]->(v)
                    """, book_name=book_name, chapter_num=chapter_num, verses=verses_batch)

if __name__ == "__main__":
    print("🚀 Initialisation de la base de données...")
    create_constraints()
    print("📖 Début de l'importation de la Bible (cela peut prendre quelques minutes)...")
    seed_database()
    print("✅ Importation terminée avec succès !")
    driver.close()
