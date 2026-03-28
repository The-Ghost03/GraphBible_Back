from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/admin", tags=["Administration"])

# 🚀 LE VIGILE BACKEND : Vérifie que le token appartient bien à un SuperAdmin
def get_current_admin(current_user: dict = Depends(get_current_user)):
    driver = get_db()
    with driver.session() as session:
        record = session.run("MATCH (u:User {id: $uid}) RETURN u.role AS role", uid=current_user["id"]).single()
        if not record or record["role"] != "superadmin":
            raise HTTPException(status_code=403, detail="Accès refusé. Réservé aux administrateurs.")
    return current_user

# 🚀 1. ROUTE DES STATS GLOBALES
@router.get("/stats")
def get_dashboard_stats(admin: dict = Depends(get_current_admin)):
    driver = get_db()
    with driver.session() as session:
        users_count = session.run("MATCH (u:User) RETURN count(u) AS count").single()["count"]
        graphs_count = session.run("MATCH (g:Graph) RETURN count(g) AS count").single()["count"]
        # On compte tous les noeuds créés (Notes + Passages)
        nodes_count = session.run("MATCH (n) WHERE n:Note OR n:Passage RETURN count(n) AS count").single()["count"]

        return {
            "total_users": users_count,
            "total_graphs": graphs_count,
            "total_nodes": nodes_count
        }

# 🚀 2. ROUTE POUR LA LISTE DES UTILISATEURS
@router.get("/users")
def get_all_users(admin: dict = Depends(get_current_admin)):
    driver = get_db()
    with driver.session() as session:
        query = """
        MATCH (u:User)
        OPTIONAL MATCH (u)-[:OWNS]->(g:Graph)
        RETURN 
            u.id AS id, 
            u.email AS email, 
            u.first_name AS first_name, 
            u.last_name AS last_name, 
            u.role AS role, 
            u.is_verified AS is_verified,
            toString(u.created_at) AS created_at,
            count(g) AS total_graphs
        ORDER BY created_at DESC
        """
        result = session.run(query)
        users = [dict(record) for record in result]
        return {"users": users}