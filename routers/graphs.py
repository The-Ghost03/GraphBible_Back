from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import get_db
from routers.auth import get_current_user
import uuid

router = APIRouter(prefix="/graphs", tags=["Graphs"])


class GraphCreate(BaseModel):
    title: str
    description: str = ""
    is_public: bool = False


@router.post("/")
def create_graph(graph: GraphCreate, current_user: dict = Depends(get_current_user)):
    driver = get_db()
    graph_id = str(uuid.uuid4())

    with driver.session() as session:
        query = """
        MATCH (u:User {id: $user_id})
        CREATE (g:Graph {
            id: $graph_id,
            title: $title,
            description: $description,
            is_public: $is_public,
            created_at: datetime(),
            updated_at: datetime()
        })
        CREATE (u)-[:OWNS]->(g)
        RETURN g.id AS id
        """
        session.run(query, user_id=current_user["id"], graph_id=graph_id, title=graph.title,
                    description=graph.description, is_public=graph.is_public)

        return {"message": "Graphe créé avec succès", "graph_id": graph_id}


@router.get("/")
def get_my_graphs(current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        query = """
        MATCH (u:User {id: $user_id})-[:OWNS]->(g:Graph)
        RETURN g.id AS id, g.title AS title, g.description AS description, g.created_at AS created_at
        ORDER BY g.created_at DESC
        """
        result = session.run(query, user_id=current_user["id"])
        graphs = [{"id": record["id"], "title": record["title"], "description": record["description"]} for record in
                  result]

        return {"graphs": graphs}