#!/bin/bash

# Utilise le 1er argument comme message, ou "commit automatique" par défaut
MESSAGE=${1:-"commit automatique"}

echo "📦 Ajout des fichiers..."
git add .

echo "📝 Création du commit : $MESSAGE"
git commit -m "$MESSAGE"

echo "🚀 Envoi vers GitHub..."
git push

echo "✅ Terminé !"
