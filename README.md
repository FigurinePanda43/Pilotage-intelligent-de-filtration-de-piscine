# Pilotage intelligent de filtration de piscine

Intégration Home Assistant distribuée via HACS.

Pilotage **entièrement autonome** d'une pompe de filtration de piscine, sans aucune automatisation à créer.

---

## Le problème

Les programmateurs horaires classiques ne s'adaptent pas aux conditions réelles.
Une journée à 35 °C avec fort UV n'a pas les mêmes besoins qu'une journée nuageuse à 18 °C.
Résultat : soit sous-filtration (eau verte), soit surconsommation électrique inutile.

---

## La solution

Cette intégration calcule en continu le besoin réel de filtration en fonction de :

- **La température de l'eau** → besoin de base
- **L'indice UV** → activité solaire, prolifération algale
- **La vitesse du vent** → dispersion de contaminants
- **La température extérieure** → charge thermique sur l'eau

Elle décide ensuite **quand faire tourner la pompe**, en centrant la filtration sur le midi solaire et en rattrapant les retards en fin de journée.

---

## Fonctionnement de l'algorithme

Le système fonctionne en **trois niveaux imbriqués** : calcul du besoin, décision ON/OFF, garde-fous.
Il tourne toutes les 10 minutes en arrière-plan, sans intervention humaine.

---

### Niveau 1 — Lissage des données brutes (moyennes glissantes)

Avant tout calcul, les capteurs sont lissés pour éviter les réactions à des pics ponctuels (nuage passager, rafale courte, relevé aberrant).

| Signal | Fenêtre de lissage | Pourquoi |
|--------|--------------------|----------|
| Température eau | 3 heures | Inertie thermique forte — l'eau chauffe lentement |
| Température air | 3 heures | Évite de réagir à un pic de chaleur de 20 minutes |
| Indice UV | 1 heure | Signal plus volatile, fenêtre plus courte |
| Vitesse du vent | 1 heure | Idem |

> Exemple : si l'UV passe à 9 pendant 5 minutes puis redescend à 3, la moyenne 1 h ne bougera presque pas.
> Le système ne sursautera pas.

**Persistance des historiques** : les historiques sont sauvegardés dans le stockage HA toutes les 10 minutes. Après un redémarrage, les moyennes sont restaurées immédiatement à partir des vraies données historiques, sans passer par les valeurs de repli.

---

### Niveau 2 — Calcul du besoin journalier

#### 2a. Objectif minimal — `H_min`

```
H_min = clamp(T_eau_moy_3h / 2 ; 2 h ; plafond)
```

C'est la règle de base de la filtration piscine : **diviser la température de l'eau par 2**.
- Eau à 20 °C → 10 h de filtration minimum
- Eau à 28 °C → 14 h
- Jamais moins de 2 h (même en hiver), jamais plus que le plafond configuré

C'est le **plancher absolu**. Le système ne descendra jamais en dessous.

---

#### 2b. Objectif dynamique — `H_dyn`

```
H_dyn = clamp(
    T_eau / 2
    + 0.20 × max(UV − 3, 0)
    + 0.04 × max(Vent − 15, 0)
    + 0.12 × max(T_air − 26, 0)
; 2 h ; plafond)
```

`H_dyn` **ajuste le besoin vers le haut** selon trois facteurs aggravants :

**Facteur UV** — `0.20 × max(UV − 3, 0)`

L'UV favorise la dégradation du chlore et la prolifération algale.
En dessous de 3 (temps couvert), aucun ajout.
Au-delà de 3, chaque unité d'UV supplémentaire ajoute 12 minutes de filtration.
- UV = 3 → +0 h
- UV = 6 → +0.60 h (36 min)
- UV = 10 → +1.40 h (84 min)

**Facteur vent** — `0.04 × max(Vent − 15, 0)`

Le vent apporte feuilles, pollen, poussières dans l'eau.
En dessous de 15 km/h, aucun ajout.
- Vent = 30 km/h → +0.60 h (36 min)
- Vent = 50 km/h → +1.40 h (84 min)

**Facteur chaleur air** — `0.12 × max(T_air − 26, 0)`

Au-delà de 26 °C, la chaleur accélère la consommation du chlore et la charge biologique.
- T_air = 30 °C → +0.48 h (29 min)
- T_air = 35 °C → +1.08 h (65 min)

Le résultat est plafonné au **plafond journalier configurable** (18 h par défaut) pour éviter le fonctionnement permanent.

---

#### 2c. Facteur de correction — `F_correction`

Un multiplicateur optionnel (0.5–2.0, défaut 1.0) permet d'adapter l'objectif à l'installation réelle :

```
H_min_adj = min(H_min × F_correction ; plafond)
H_dyn_adj = min(H_dyn × F_correction ; plafond)
```

| Facteur | Effet | Cas d'usage |
|---------|-------|-------------|
| 0.5 | −50 % | Installation surdimensionnée, eau toujours claire |
| 1.0 | Neutre | **Défaut** |
| 1.5 | +50 % | Filtre vieillissant ou sous-dimensionné |
| 2.0 | +100 % | Piscine fortement sous-filtrée |

---

#### 2d. Objectif final — `H_target`

```
H_target = max(H_target_précédent, H_min_adj, H_dyn_adj)
```

`H_target` prend le **maximum des trois valeurs**. Il ne peut **jamais diminuer** au cours d'une journée.

Pourquoi ? Si une canicule arrive à 14h alors que l'objectif du matin était de 10 h, le système rehausse l'objectif à 14 h — mais ne reviendra pas en arrière si le temps se couvre ensuite.
C'est une protection contre la sous-filtration accidentelle.

La remise à zéro s'effectue chaque jour à l'heure configurée (par défaut 00:00).
Un **bouton de réinitialisation** (`button.pool_filtration_reset_daily_counters`) permet de remettre l'objectif à zéro manuellement sans attendre minuit — utile si l'objectif a été gonflé par erreur.

---

### Niveau 3 — Décision ON/OFF (bloc centré sur le midi solaire)

Le cœur du planificateur est un **bloc de filtration de durée `H_target`, centré sur le midi solaire** :

```
run_start = midi_solaire − H_target / 2
run_end   = midi_solaire + H_target / 2
```

Le midi solaire est calculé dynamiquement à partir des coordonnées GPS de Home Assistant. En France métropolitaine en été, il se situe autour de **13h30–14h00**.

#### Exemples (midi solaire à 13h37)

| H_target | Démarrage | Arrêt |
|----------|-----------|-------|
| 8 h | 09:37 | 17:37 (= fenêtre solaire exacte) |
| 10 h | 08:37 | 18:37 |
| 12 h | 07:37 | 19:37 |
| 14 h | 06:37 | 20:37 |
| 16 h | 05:37 | 21:37 |

Si `H_target` dépasse la durée de la fenêtre solaire (8 h par défaut), le bloc s'étend **symétriquement** avant le lever et après le coucher du soleil — jamais de démarrage unilatéral à 5 h du matin.

Si `H_target` augmente en cours de journée (ratchet), `run_end` se décale automatiquement vers le soir.

#### Rattrapage fin de journée

Si la pompe n'a pas pu effectuer les heures prévues dans le bloc (coupure, heure autorisée dépassée, redémarrage), elle continue de tourner **après `run_end`** jusqu'à atteindre l'objectif, dans la limite de la plage horaire autorisée.

#### Statut du planning

```
H_remaining > temps_restant_dans_le_bloc + 30 min  →  "En retard"
H_remaining ≤ temps_restant_dans_le_bloc + 30 min  →  "À l'heure"
```

Une tolérance de 30 minutes évite les basculements intempestifs pour un écart mineur.

---

### Niveau 4 — Garde-fous

Ces règles s'appliquent **par-dessus** la décision logique, comme des verrous matériels :

| Garde-fou | Valeur par défaut | Raison |
|-----------|-------------------|--------|
| Durée minimum ON | 30 min | Protège la pompe contre les démarrages trop fréquents |
| Durée minimum OFF | 15 min | Laisse le moteur refroidir entre deux cycles |
| Plafond journalier | 18 h (**configurable** 6–24 h) | Évite la surconsommation en cas de bug capteur |
| Plage horaire | 06h–23h | Évite de faire tourner la pompe la nuit (bruit, tarif) |
| Anti-régression | — | `H_target` ne peut que croître dans la journée |
| Capteur indisponible | valeur de repli + historique persisté | Fonctionnement dégradé sans interruption |

---

### Cycle complet — résumé visuel

```
[Capteurs bruts]
      │
      ▼  lissage (moyenne glissante 1h / 3h) — historiques persistés entre redémarrages
[Moyennes]
      │
      ├──▶  H_min = T_eau / 2  (plancher)
      │
      ├──▶  H_dyn = H_min + ajustements UV + vent + chaleur
      │
      ├──▶  H_min_adj = min(H_min × F_correction ; plafond)
      ├──▶  H_dyn_adj = min(H_dyn × F_correction ; plafond)
      │
      └──▶  H_target = max(H_target_veille, H_min_adj, H_dyn_adj)  ← figé à la hausse

[Bloc centré sur le midi solaire]
      run_start = midi_solaire − H_target/2
      run_end   = midi_solaire + H_target/2
      │
      ▼
[Décision ON/OFF]
      ├── Dans le bloc (run_start → run_end) ?     →  ON
      ├── Dans la fenêtre solaire (±4 h) ?         →  raison : "Fenêtre solaire"
      ├── Hors fenêtre mais dans le bloc ?          →  raison : "Rattrapage – retard"
      ├── Passé run_end, objectif non atteint ?     →  ON (rattrapage fin de journée)
      └── Aucune condition                          →  OFF
      │
      ▼
[Garde-fous]  →  anti-cycle, plage horaire, plafond
      │
      ▼
[Commande switch pompe]
      │
      ▼
[Notifications]  →  critique / intermédiaire / détaillé (optionnel)
```

---

### Mode hivernage

Activé manuellement via `switch.pool_winter_mode`. Remplace entièrement la logique normale.

**Si gel détecté** (T_air ≤ 0 °C **et** T_eau ≤ 5 °C) :
La pompe tourne 1 h toutes les 4 h (durée et intervalle configurables).
L'objectif est de maintenir l'eau en mouvement pour éviter le gel des tuyaux.

**Si hiver sans gel** :
La pompe reste **complètement éteinte**.
En hivernage, aucun besoin de filtration hors période de gel.

La détection de gel se fait sur la température **actuelle** (non lissée) pour réagir immédiatement. Les deux conditions sont **cumulatives** : le gel doit être présent aussi bien dans l'air que dans l'eau.

### Mode éco

Activé manuellement via `switch.pool_filtration_eco_mode`. Fonctionne par-dessus la logique normale : le besoin journalier (`H_target`) reste inchangé, seule la **répartition temporelle** change.

**Principe** : une partie de la filtration est déplacée vers les heures creuses.

```
H_day_min = max(60 % × H_target ; 3 h)   ← obligatoirement réalisé en fenêtre solaire
H_shiftable = H_target − H_day_min        ← peut être déplacé en heures creuses
```

En fenêtre solaire, la pompe assure d'abord `H_day_min` (priorité absolue). Le temps restant (`H_shiftable`) est décalé vers les heures creuses configurées.

**Suspension automatique** si l'une des conditions suivantes est vraie :
- Retard critique dans le bloc de filtration en cours
- T_eau > 28 °C
- UV moyen > 6
- Minimum diurne progressif non atteint en fenêtre solaire

Dans ces cas, le système revient automatiquement au comportement normal jusqu'à ce que les conditions redeviennent favorables.

---

## Notifications

Le système peut envoyer des notifications push sur un ou plusieurs appareils en cas d'événement.

### Configuration

Dans **Paramètres → Intégrations → Pool Filtration → Configurer** :

| Option | Description |
|--------|-------------|
| **Niveau de notification** | `Désactivé` / `Critique` / `Intermédiaire` / `Détaillé` |
| **Appareils de notification** | Noms de services séparés par des virgules — ex. : `notify.mobile_app_iphone,notify.mobile_app_tablette` |

> **Format du champ appareils** : indiquer le nom complet du service HA au format `domaine.service`. Si seul le nom du service est saisi (ex. `mobile_app_iphone`), le domaine `notify` est assumé. `notify.notify` envoie sur tous les appareils mobiles enregistrés par défaut.

### Niveaux (cumulatifs)

| Niveau | Événements déclencheurs |
|--------|------------------------|
| 🚨 **Critique** | La pompe n'a pas pu démarrer ou s'arrêter (exception HA lors de l'appel de service) |
| ⚠️ **Intermédiaire** | Critique + capteur indisponible depuis > 30 min + capteur rétabli + arrêt inattendu de la pompe |
| ✅ **Détaillé** | Intermédiaire + pompe démarrée (heure + temp. eau + objectif) + pompe arrêtée (heure + temp. eau + filtration effectuée) |

### Délai de grâce pour les capteurs

Une indisponibilité de capteur de **moins de 30 minutes** (ex. bref redémarrage HA) ne déclenche aucune notification. La notification "capteur rétabli" n'est envoyée que si la notification "capteur indisponible" avait été émise au préalable.

---

## Dashboards Lovelace

Deux exemples de dashboards prêts à l'emploi sont disponibles dans le dossier [`dashboards/`](dashboards/).

> **IDs d'entités** : les IDs générés par HA dépendent de la langue et de la version. Si une entité n'est pas trouvée, allez dans **Paramètres → Appareils et services → Entités**, filtrez par "Pool Filtration" et copiez l'ID réel.

---

### Dashboard minimaliste (`dashboards/minimaliste.yaml`)

Vue rapide sur une seule page. Idéal pour un téléphone ou un panneau compact.

| Carte | Contenu |
|-------|---------|
| État global | Système, pompe, planning |
| Jauge | Progression de la filtration journalière |
| Objectifs | H_target / effectuée / restante |
| Conditions | Température eau, air, vent |
| Modes | Manuel, hivernage, éco, forte fréquentation + bouton reset |

**Utilisation :**
1. Dashboard → ⋮ → *Modifier* → *Ajouter une vue*
2. Passer en mode YAML, coller le contenu de `dashboards/minimaliste.yaml`

---

### Dashboard complet (`dashboards/complet.yaml`)

Six vues thématiques pour un suivi détaillé.

| Vue | Contenu |
|-----|---------|
| Tableau de bord | Statut, jauge, objectifs, modes, historique filtration |
| Environnement | Jauges températures, UV, vent, graphiques 24 h |
| Mode éco | Statut, tarif HC/HP, heures déplaçables, historique |
| Forte fréquentation | Statut boost, fenêtre nocturne, temps restant |
| Hivernage | Températures de référence gel, historique 7 jours |
| Diagnostics | Tous les capteurs, raison de décision, état système |

**Utilisation :**
1. Dashboard → ⋮ → *Modifier* → *Ajouter une vue*
2. Répéter pour chaque vue en copiant la section correspondante du YAML

---

## Installation

1. Ajouter ce dépôt dans HACS → *Intégrations personnalisées*
2. Installer **Pool Filtration**
3. Redémarrer Home Assistant
4. **Paramètres → Intégrations → Ajouter → Pool Filtration**
5. Sélectionner les 5 entités (voir ci-dessous)
6. ✅ Terminé — le système pilote la pompe automatiquement

---

## Entités requises

| Rôle | Type |
|------|------|
| Interrupteur pompe | `switch` |
| Température eau | `sensor` (device_class: temperature) |
| Température extérieure | `sensor` (device_class: temperature) |
| Indice UV | `sensor` |
| Vitesse du vent | `sensor` |
| Rafales *(optionnel)* | `sensor` |

---

## Entités créées automatiquement

### Capteurs principaux

| Entité | Description |
|--------|-------------|
| `sensor.pool_filtration_objectif_filtration` | Objectif journalier calculé (h) |
| `sensor.pool_filtration_filtration_effectuee` | Temps déjà filtré aujourd'hui (h) |
| `sensor.pool_filtration_filtration_restante` | Temps restant à filtrer (h) |
| `sensor.pool_filtration_etat_filtration` | ON / OFF logique |

### Capteurs de transparence

| Entité | Description |
|--------|-------------|
| `sensor.pool_filtration_raison_de_la_decision` | Pourquoi la pompe tourne (ou non) |
| `sensor.pool_filtration_etat_du_systeme` | État global : normal / catching_up / winter / eco / busy / idle / degraded |
| `sensor.pool_filtration_statut_du_planning` | À l'heure / En retard (tolérance 30 min) |
| `sensor.pool_filtration_temps_restant_fenetre_solaire` | Temps restant dans le bloc de filtration du jour (h) |

### Capteurs calculés

| Entité | Description |
|--------|-------------|
| `sensor.pool_filtration_objectif_dynamique` | H_dyn du cycle en cours |
| `sensor.pool_filtration_objectif_minimal` | H_min du cycle en cours |
| `sensor.pool_filtration_facteur_de_correction_objectif` | Facteur F_correction actif |
| `sensor.pool_filtration_temp_eau_moy_3_h` | Moyenne glissante température eau (3 h) |
| `sensor.pool_filtration_temp_air_moy_3_h` | Moyenne glissante température air (3 h) |
| `sensor.pool_filtration_uv_moy_1_h` | Moyenne glissante UV (1 h) |
| `sensor.pool_filtration_vent_moy_1_h` | Moyenne glissante vent (1 h) |

### Capteurs éco

| Entité | Description |
|--------|-------------|
| `sensor.pool_filtration_eco_heures_depla_ables` | H_shiftable : heures déplaçables en HC (h) |
| `sensor.pool_filtration_eco_heures_depla_ables_restantes` | Heures déplaçables restantes à faire en HC (h) |
| `sensor.pool_filtration_statut_mode_eco` | Mode éco actif ou suspendu |
| `sensor.pool_filtration_tarif_actuel` | Tarif actuel : HC (heures creuses) ou HP (heures pleines) |

### Capteurs mode forte fréquentation

| Entité | Description |
|--------|-------------|
| `sensor.pool_filtration_statut_mode_forte_frequentation` | Statut : `active` / `standby` |
| `sensor.pool_filtration_duree_boost_nocturne` | Durée configurée (h) |
| `sensor.pool_filtration_fenetre_boost_nocturne` | Fenêtre calculée, ex : `00:45 – 02:45` |
| `sensor.pool_filtration_temps_restant_boost` | Temps restant dans la fenêtre boost (h) |

### Switchs

| Entité | Description |
|--------|-------------|
| `switch.pool_filtration_mode_hivernage` | Activer le mode hivernage |
| `switch.pool_filtration_mode_eco` | Activer le mode éco |
| `switch.pool_filtration_mode_forte_frequentation` | Activer le mode forte fréquentation |

### Bouton

| Entité | Description |
|--------|-------------|
| `button.pool_filtration_reinitialiser_les_compteurs_journaliers` | Remet `H_target` à zéro manuellement |

---

## Mode manuel

Activé via `switch.pool_filtration_mode_manuel`.

Ce mode donne le contrôle total de la pompe à l'utilisateur : tant qu'il est actif, l'intégration **n'envoie plus aucune commande** marche/arrêt à la pompe — elle se contente d'observer son état réel et de continuer à calculer les objectifs et le temps de filtration effectué pour affichage.

C'est la priorité **la plus haute** : elle prend le pas sur le mode hivernage, le boost forte fréquentation, le mode éco et la logique normale. Pratique pour une intervention ponctuelle (nettoyage, contre-lavage du filtre, test du matériel) sans avoir à désactiver l'intégration.

Pensez à désactiver le mode manuel pour que la filtration automatique reprenne.

---

## Mode hivernage

Activé via `switch.pool_filtration_mode_hivernage`.

| Condition | Comportement |
|-----------|--------------|
| T_air ≤ 0 °C **et** T_eau ≤ 5 °C | Cycles anti-gel : 1 h toutes les 4 h (configurable) |
| Hiver sans gel | Pompe **éteinte** (veille hivernage) |

---

## Mode forte fréquentation (boost nocturne)

Activé via `switch.pool_filtration_mode_forte_frequentation`.

Ce mode ajoute un cycle de filtration nocturne **en plus** de la logique normale. Il est conçu pour les périodes de forte utilisation de la piscine (week-ends, vacances, fêtes).

### Principe

La nuit est définie entre le coucher et le lever du soleil. Le boost est centré sur le **milieu de la nuit** (solar midnight) :

```
night_start  = coucher du soleil (jour J)
night_end    = lever du soleil   (jour J+1)
night_mid    = (night_start + night_end) / 2

boost_start  = night_mid − D/2
boost_end    = night_mid + D/2
```

Exemple avec un coucher à 21h30, un lever à 06h00 et un boost de 2 h :
- Solar midnight : 01h45
- Fenêtre boost : **00h45 – 02h45**

La fenêtre est automatiquement tronquée pour ne jamais déborder en dehors de la nuit.

### Paramétrage

| Option | Défaut | Plage |
|--------|--------|-------|
| Durée du boost nocturne | 2 h | 0,5 h – 6 h |

Réglable dans **Paramètres → Intégrations → Pool Filtration → Configurer**.

### Priorité

| Priorité | Mode |
|----------|------|
| 1 | Mode manuel (contrôle utilisateur) |
| 2 | Mode hivernage (sécurité) |
| 3 | Boost nocturne forte fréquentation |
| 4 | Mode éco / logique normale |

Le boost est **suspendu automatiquement** si les capteurs critiques sont indisponibles (mode dégradé).

### Non-interférence

Le boost nocturne est une **surcouche additive** : il ne modifie pas `H_target`, `H_min`, `H_dyn`, le mode éco ni la logique de rattrapage. La pompe tourne plus longtemps, mais les calculs normaux restent inchangés.

---

## Mode éco

Activé via `switch.pool_filtration_mode_eco`.

Configurer les heures creuses dans **Paramètres → Intégrations → Pool Filtration → Configurer** :

| Option | Description |
|--------|-------------|
| Plages heures creuses | Une ou plusieurs plages au format `HH:MM-HH:MM` séparées par des virgules |
| Binary sensor HC | `binary_sensor` externe — prend la priorité sur les plages configurées |

**Format des plages heures creuses** — exemples :

| Valeur | Signification |
|--------|---------------|
| `22:00-06:00` | Nuit (traversée de minuit automatiquement gérée) |
| `22:00-06:00,12:00-14:00` | Nuit + pause de midi |
| `01:00-07:00,14:00-17:00,22:30-06:30` | Trois plages dont deux traversant minuit |

> Les plages peuvent se chevaucher. Une traversée de minuit est détectée automatiquement quand l'heure de fin est antérieure à l'heure de début.

Le mode éco est automatiquement suspendu (comportement normal) si :
- T_eau > 28 °C
- UV moyen > 6
- Retard critique dans le bloc de filtration en cours
- Minimum diurne progressif non atteint en fenêtre solaire

---

## Garde-fous intégrés

- **Anti-court-cycle** : 30 min minimum ON, 15 min minimum OFF
- **Plages horaires** : 06h00 – 23h00 par défaut (configurable)
- **Plafond journalier** : 18 h par défaut, configurable de 6 à 24 h
- **Anti-régression** : l'objectif ne diminue jamais en cours de journée
- **Capteur indisponible** : historiques persistés entre redémarrages ; valeur de repli + état `degraded` visible si l'historique expire ; notification après 30 min d'indisponibilité continue

---

## Exemple concret

> Eau à 24 °C, UV 6, vent 25 km/h, air 29 °C — journée ensoleillée d'été

```
H_min  = 24 / 2 = 12 h
H_dyn  = 12 + 0.20×(6−3) + 0.04×(25−15) + 0.12×(29−26)
       = 12 + 0.60 + 0.40 + 0.36 = 13.36 h
H_target = 13.36 h

Bloc de filtration (midi solaire = 13h37) :
  run_start = 13:37 − 6h41 = 06:56
  run_end   = 13:37 + 6h41 = 20:18
```

La pompe tourne de ~07h00 à ~20h20, centrée sur l'heure la plus chaude de la journée.

---

## Options configurables

Accessibles via **Paramètres → Intégrations → Pool Filtration → Configurer** :

| Option | Défaut | Description |
|--------|--------|-------------|
| Heure de remise à zéro | 00:00 | Reset quotidien des compteurs |
| Heure de début autorisée | 06h | Aucune commande de pompe avant cette heure |
| Heure de fin autorisée | 23h | Aucune commande de pompe après cette heure |
| **Plafond journalier** | **18 h** | **Maximum de filtration par jour (6–24 h)** |
| **Facteur de correction** | **1.0** | **Multiplicateur sur H_min et H_dyn (0.5–2.0)** |
| Intervalle cycle hivernage | 4 h | Temps entre deux cycles anti-gel |
| Durée cycle hivernage | 60 min | Durée de chaque cycle anti-gel |
| Durée boost nocturne | 2 h | Durée du boost forte fréquentation (0,5–6 h) |
| **Niveau de notification** | **Désactivé** | **Critique / Intermédiaire / Détaillé** |
| **Appareils de notification** | — | **Services séparés par virgules — ex. `notify.mobile_app_iphone`** |
| Plages heures creuses | — | Une ou plusieurs plages HC (option A) — voir format ci-dessus |
| Binary sensor HC | — | Entité `binary_sensor` indiquant les HC (option B, prioritaire) |
| Interrupteur pompe | — | Remplace l'entité sélectionnée lors de l'installation |
| Capteur température eau | — | Remplace l'entité sélectionnée lors de l'installation |
| Capteur température extérieure | — | Remplace l'entité sélectionnée lors de l'installation |
| Capteur UV | — | Remplace l'entité sélectionnée lors de l'installation |
| Capteur vitesse du vent | — | Remplace l'entité sélectionnée lors de l'installation |
| Capteur rafales | — | Remplace l'entité sélectionnée lors de l'installation |
