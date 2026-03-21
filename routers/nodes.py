from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/nodes", tags=["Graph Nodes"])


@router.get("/fetch-passage/{book_name}/{chapter_number}/{v_start}/{v_end}")
def fetch_specific_passage(book_name: str, chapter_number: int, v_start: int, v_end: int,
                           current_user: dict = Depends(get_current_user)):
    if v_end < v_start:
        raise HTTPException(status_code=400, detail="Le verset de fin doit être après le verset de début.")

    driver = get_db()
    with driver.session() as session:
        query = """
        MATCH (c:Chapter {book: $book_name, number: $chapter_number})-[:CONTAINS]->(v:Verse)
        WHERE v.number >= $v_start AND v.number <= $v_end
        RETURN v.number AS number, v.text AS text
        ORDER BY v.number
        """
        result = session.run(query, book_name=book_name, chapter_number=chapter_number, v_start=v_start, v_end=v_end)
        verses = [{"verse": record["number"], "text": record["text"]} for record in result]

        if not verses:
            raise HTTPException(status_code=404, detail="Passage introuvable dans la base de données.")

        formatted_text = ""
        if v_start == v_end:
            formatted_text = verses[0]["text"]
        else:
            for v in verses:
                formatted_text += f"{v['verse']}. {v['text']}\n"

        reference = f"{book_name} {chapter_number}:{v_start}"
        if v_start != v_end:
            reference += f"-{v_end}"

        return {"reference": reference, "text": formatted_text.strip()}