# MyTransilien

Intégration Home Assistant native permettant de configurer plusieurs trajets **gare de départ → gare d'arrivée** à partir des API PRIM / Île-de-France Mobilités.

## Confidentialité

Aucun trajet, nom de gare, identifiant d'arrêt, clé API ou autre donnée de configuration personnelle n'est stocké dans ce dépôt.

La clé PRIM et les trajets sont saisis uniquement dans Home Assistant et restent dans la configuration locale de l'instance.

## Installation avec HACS

1. Ouvrir **HACS → Intégrations**.
2. Menu **⋮ → Dépôts personnalisés**.
3. Ajouter ce dépôt avec le type **Intégration**.
4. Installer **MyTransilien** puis redémarrer Home Assistant une fois pour charger le composant Python.
5. Aller dans **Paramètres → Appareils et services → Ajouter une intégration → MyTransilien**.
6. Saisir la clé API PRIM, la gare de départ et la gare d'arrivée.

Pour ajouter un trajet supplémentaire, ajouter une nouvelle entrée MyTransilien. La clé PRIM déjà enregistrée localement est réutilisée automatiquement.

## Entités

Chaque trajet crée son propre appareil Home Assistant et deux capteurs :

- **Prochains trajets** : nombre de prochains itinéraires ; l'attribut `trains` contient les détails de chaque départ ;
- **Prochain départ** : horodatage du prochain départ avec heure d'arrivée, lignes, durée, correspondances et retard.

## Données

- Les trajets sont calculés via PRIM Navitia.
- Les données sont actualisées toutes les 60 secondes.
- Le temps réel est utilisé en priorité.
- En l'absence de trajet disponible dans la période courante, les horaires prévus du lendemain sont proposés selon les options configurées.
- Le retard est calculé lorsque PRIM fournit à la fois l'horaire temps réel et l'horaire de base.

## Dashboard

Le fichier `dashboard-card.yaml` fournit une carte Markdown compacte inspirée des panneaux de départ en gare.

Copier la carte puis remplacer uniquement l'`entity_id` générique par celui du capteur **Prochains trajets** à afficher.
