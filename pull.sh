#!/bin/bash

echo "Pull depuis le repo GitHub"
git pull

echo "redemarrage du conteneur backend"
docker restart biblegraph_backend