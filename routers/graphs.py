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


# Schémas pour React Flow
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


# --- ROUTES EXISTANTES (CRÉATION ET LISTE) ---
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


# --- NOUVELLES ROUTES (SAUVEGARDE ET CHARGEMENT DU CANVAS) ---
@router.post("/{graph_id}/save")
def save_graph_data(graph_id: str, payload: GraphData, current_user: dict = Depends(get_current_user)):
    """Sauvegarde les noeuds et liens de React Flow dans Neo4j"""
    driver = get_db()
    with driver.session() as session:
        # 1. Sécurité : Vérifier que l'utilisateur possède bien ce graphe
        check = session.run("MATCH (u:User {id: $uid})-[:OWNS]->(g:Graph {id: $gid}) RETURN g", uid=current_user["id"],
                            gid=graph_id).single()
        if not check:
            raise HTTPException(status_code=403, detail="Vous n'avez pas le droit de modifier ce graphe.")

        # 2. Nettoyage : Effacer les anciens noeuds/liens de CE graphe spécifique
        session.run("""
        MATCH (g:Graph {id: $gid})-[:HAS_NODE]->(n:Node)
        DETACH DELETE n
        """, gid=graph_id)

        # 3. Insertion : Créer les nouveaux noeuds
        for node in payload.nodes:
            session.run("""
            MATCH (g:Graph {id: $gid})
            CREATE (n:Node {
                id: $n_id,
                type: $n_type,
                pos_x: $pos_x,
                pos_y: $pos_y,
                data: $data,
                style: $style
            })
            CREATE (g)-[:HAS_NODE]->(n)
            """,
                        gid=graph_id,
                        n_id=node.id,
                        n_type=node.type,
                        pos_x=node.position.get("x", 0),
                        pos_y=node.position.get("y", 0),
                        data=json.dumps(node.data),
                        style=json.dumps(node.style) if node.style else "{}"
                        )

        # 4. Insertion : Créer les liens (Edges) entre les noeuds
        for edge in payload.edges:
            session.run("""
            MATCH (source:Node {id: $source_id}), (target:Node {id: $target_id})
            CREATE (source)-[r:LINKED_TO {
                id: $e_id,
                animated: $animated,
                style: $style
            }]->(target)
            """,
                        source_id=edge.source,
                        target_id=edge.target,
                        e_id=edge.id,
                        animated=edge.animated,
                        style=json.dumps(edge.style) if edge.style else "{}"
                        )

        return {"message": "Graphe sauvegardé avec succès dans Neo4j !"}


@router.get("/{graph_id}/data")
def get_graph_data(graph_id: str, current_user: dict = Depends(get_current_user)):
    """Récupère les noeuds et liens pour les afficher dans React Flow"""
    driver = get_db()
    with driver.session() as session:
        # Sécurité
        check = session.run("MATCH (u:User {id: $uid})-[:OWNS]->(g:Graph {id: $gid}) RETURN g", uid=current_user["id"],
                            gid=graph_id).single()
        if not check:
            raise HTTPException(status_code=403, detail="Accès refusé.")

        # Récupérer les noeuds
        nodes_res = session.run("MATCH (g:Graph {id: $gid})-[:HAS_NODE]->(n:Node) RETURN n", gid=graph_id)
        nodes = []
        for record in nodes_res:
            n = record["n"]
            nodes.append({
                "id": n["id"],
                "type": n["type"],
                "position": {"x": n["pos_x"], "y": n["pos_y"]},
                "data": json.loads(n["data"]),
                "style": json.loads(n["style"])
            })

        # Récupérer les liens
        edges_res = session.run("""
        MATCH (g:Graph {id: $gid})-[:HAS_NODE]->(source:Node)-[r:LINKED_TO]->(target:Node)
        RETURN r, source.id AS source_id, target.id AS target_id
        """, gid=graph_id)

        edges = []
        for record in edges_res:
            r = record["r"]
            edges.append({
                "id": r["id"],
                "source": record["source_id"],
                "target": record["target_id"],
                "animated": r.get("animated", False),
                "style": json.loads(r["style"]) if r.get("style") else {}
            })

        return {"nodes": nodes, "edges": edges}