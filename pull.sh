#!/bin/bash

echo "Pull depuis le repo GitHub"
git pull

echo "redemarrage du conteneur backend"
docker compose up -d --build