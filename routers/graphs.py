from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from database import get_db
from routers.auth import get_current_user
import uuid
import json

router = APIRouter(prefix="/graphs", tags=["Graphs"])


# --- SCHÉMAS DE DONNÉES ---
class GraphCreate(BaseModel):
    title: str
    description: str = ""
    is_public: bool = False


class GraphUpdate(BaseModel):
    title: str
    description: str = ""
    is_public: bool = False


class RFNode(BaseModel):
    id: str
    type: Optional[str] = "default"
    position: Dict[str, float]
    data: Dict[str, Any]
    style: Optional[Dict[str, Any]] = None


class RFEdge(BaseModel):
    id: str
    source: str
    target: str
    animated: Optional[bool] = False
    style: Optional[Dict[str, Any]] = None


class GraphData(BaseModel):
    nodes: List[RFNode]
    edges: List[RFEdge]


# --- ROUTES EXISTANTES ---
@router.post("/")
def create_graph(graph: GraphCreate, current_user: dict = Depends(get_current_user)):
    driver = get_db()
    graph_id = str(uuid.uuid4())
    with driver.session() as session:
        query = """
        MATCH (u:User {id: $user_id})
        CREATE (g:Graph {id: $graph_id, title: $title, description: $description, is_public: $is_public, created_at: datetime(), updated_at: datetime()})
        CREATE (u)-[:OWNS]->(g)
        RETURN g.id AS id
        """
        session.run(query, user_id=current_user["id"], graph_id=graph_id, title=graph.title,
                    description=graph.description, is_public=graph.is_public)
        return {"message": "Graphe créé", "graph_id": graph_id}


@router.get("/")
def get_my_graphs(current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        query = "MATCH (u:User {id: $user_id})-[:OWNS]->(g:Graph) RETURN g.id AS id, g.title AS title, g.description AS description, g.created_at AS created_at ORDER BY g.created_at DESC"
        result = session.run(query, user_id=current_user["id"])
        return {
            "graphs": [{"id": record["id"], "title": record["title"], "description": record["description"]} for record
                       in result]}


@router.post("/{graph_id}/save")
def save_graph_data(graph_id: str, payload: GraphData, current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        check = session.run("MATCH (u:User {id: $uid})-[:OWNS]->(g:Graph {id: $gid}) RETURN g", uid=current_user["id"],
                            gid=graph_id).single()
        if not check: raise HTTPException(status_code=403, detail="Accès refusé.")

        session.run("MATCH (g:Graph {id: $gid})-[:HAS_NODE]->(n:Node) DETACH DELETE n", gid=graph_id)

        for node in payload.nodes:
            session.run("""
            MATCH (g:Graph {id: $gid})
            CREATE (n:Node {id: $n_id, type: $n_type, pos_x: $pos_x, pos_y: $pos_y, data: $data, style: $style})
            CREATE (g)-[:HAS_NODE]->(n)
            """, gid=graph_id, n_id=node.id, n_type=node.type, pos_x=node.position.get("x", 0),
                        pos_y=node.position.get("y", 0), data=json.dumps(node.data),
                        style=json.dumps(node.style) if node.style else "{}")

        for edge in payload.edges:
            session.run("""
            MATCH (source:Node {id: $source_id}), (target:Node {id: $target_id})
            CREATE (source)-[r:LINKED_TO {id: $e_id, animated: $animated, style: $style}]->(target)
            """, source_id=edge.source, target_id=edge.target, e_id=edge.id, animated=edge.animated,
                        style=json.dumps(edge.style) if edge.style else "{}")

        return {"message": "Sauvegardé"}


# --- NOUVELLE ROUTE : MODIFIER LE TITRE ---
@router.put("/{graph_id}/metadata")
def update_graph_metadata(graph_id: str, payload: GraphUpdate, current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        check = session.run("MATCH (u:User {id: $uid})-[:OWNS]->(g:Graph {id: $gid}) RETURN g", uid=current_user["id"],
                            gid=graph_id).single()
        if not check: raise HTTPException(status_code=403, detail="Accès refusé.")

        session.run("""
        MATCH (g:Graph {id: $gid})
        SET g.title = $title, g.description = $description, g.is_public = $is_public, g.updated_at = datetime()
        """, gid=graph_id, title=payload.title, description=payload.description, is_public=payload.is_public)

        return {"message": "Informations mises à jour"}


# --- ROUTE MISE À JOUR : CHARGEMENT ---
@router.get("/{graph_id}/data")
def get_graph_data(graph_id: str, current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        # On récupère le titre et la description !
        graph_record = session.run(
            "MATCH (u:User {id: $uid})-[:OWNS]->(g:Graph {id: $gid}) RETURN g.title AS title, g.description AS description",
            uid=current_user["id"], gid=graph_id).single()
        if not graph_record: raise HTTPException(status_code=403, detail="Accès refusé.")

        graph_info = {"title": graph_record["title"], "description": graph_record["description"]}

        nodes_res = session.run("MATCH (g:Graph {id: $gid})-[:HAS_NODE]->(n:Node) RETURN n", gid=graph_id)
        nodes = [{"id": record["n"]["id"], "type": record["n"]["type"],
                  "position": {"x": record["n"]["pos_x"], "y": record["n"]["pos_y"]},
                  "data": json.loads(record["n"]["data"]), "style": json.loads(record["n"]["style"])} for record in
                 nodes_res]

        edges_res = session.run(
            "MATCH (g:Graph {id: $gid})-[:HAS_NODE]->(source:Node)-[r:LINKED_TO]->(target:Node) RETURN r, source.id AS source_id, target.id AS target_id",
            gid=graph_id)
        edges = [{"id": record["r"]["id"], "source": record["source_id"], "target": record["target_id"],
                  "animated": record["r"].get("animated", False),
                  "style": json.loads(record["r"]["style"]) if record["r"].get("style") else {}} for record in
                 edges_res]

        return {"graph": graph_info, "nodes": nodes, "edges": edges}  # On renvoie graph_info