#!/bin/bash

docker exec -it biblegraph_backend python -c "
from database import get_db
with get_db().session() as session:
    session.run(\"MATCH (u:User {email: 'kyoa240@gmail.com'}) DETACH DELETE u\")
print('✅ Utilisateur kyoa240@gmail.com supprimé avec succès !')
"

docker exec -it biblegraph_backend python -c "
from database import get_db
with get_db().session() as session:
    session.run(\"MATCH (u:User {email: 'schalom.yao@softskills.ci'}) DETACH DELETE u\")
print('✅ Utilisateur schalom.yao@softskills.ci supprimé avec succès !')
"