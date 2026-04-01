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

Elle décide ensuite **quand faire tourner la pompe**, en priorisant la fenêtre solaire du midi et en rattrapant les retards en fin de journée.

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

---

### Niveau 2 — Calcul du besoin journalier

#### 2a. Objectif minimal — `H_min`

```
H_min = clamp(T_eau_moy_3h / 2 ; 2 h ; 16 h)
```

C'est la règle de base de la filtration piscine : **diviser la température de l'eau par 2**.
- Eau à 20 °C → 10 h de filtration minimum
- Eau à 28 °C → 14 h
- Jamais moins de 2 h (même en hiver), jamais plus de 16 h via ce seul paramètre

C'est le **plancher absolu**. Le système ne descendra jamais en dessous.

---

#### 2b. Objectif dynamique — `H_dyn`

```
H_dyn = clamp(
    T_eau / 2
    + 0.20 × max(UV − 3, 0)
    + 0.04 × max(Vent − 15, 0)
    + 0.12 × max(T_air − 26, 0)
; 2 h ; 18 h)
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

Le résultat est plafonné à **18 h** pour éviter le fonctionnement permanent.

---

#### 2c. Objectif final — `H_target`

```
H_target = max(H_target_précédent, H_min, H_dyn)
```

`H_target` prend le **maximum des trois valeurs**. Il ne peut **jamais diminuer** au cours d'une journée.

Pourquoi ? Si une canicule arrive à 14h alors que l'objectif du matin était de 10 h, le système rehausse l'objectif à 14 h — mais ne reviendra pas en arrière si le temps se couvre ensuite.
C'est une protection contre la sous-filtration accidentelle.

La remise à zéro s'effectue chaque jour à l'heure configurée (par défaut 00:00).

---

### Niveau 3 — Décision ON/OFF

Toutes les 10 minutes, le système vérifie si la pompe doit tourner. Trois conditions indépendantes peuvent déclencher la mise en marche :

#### Fenêtre solaire prioritaire

```
Fenêtre = [zénith_solaire − 4 h  ;  zénith_solaire + 4 h]
```

Le zénith solaire est calculé dynamiquement à partir de la position géographique de Home Assistant.
Pour une position en France métropolitaine en été, cela correspond environ à **10h00 – 18h00**.

Si la pompe a encore du temps à faire (`H_remaining > 0`) et que l'on est dans cette fenêtre → elle tourne.
C'est le cas nominal. La filtration se fait naturellement autour du moment où le soleil est le plus intense.

#### Rattrapage critique

```
H_remaining > temps_restant_dans_la_fenêtre
```

Si le temps restant à filtrer est supérieur au temps qu'il reste dans la fenêtre solaire, la pompe tourne **même si elle était prévue s'arrêter** — pour éviter de sortir de la fenêtre avec un retard irrécupérable.

> Exemple : 3 h restantes, 2 h avant la fin de la fenêtre → la pompe tourne sans s'arrêter.

#### Rattrapage fin de journée

```
heure > fin_de_fenêtre  ET  H_done < H_target
```

Après la fenêtre solaire, si l'objectif n'est pas atteint, la pompe continue de tourner hors fenêtre jusqu'à combler le retard, dans la limite de la plage horaire autorisée (06h00–23h00 par défaut).

---

### Niveau 4 — Garde-fous

Ces règles s'appliquent **par-dessus** la décision logique, comme des verrous matériels :

| Garde-fou | Valeur | Raison |
|-----------|--------|--------|
| Durée minimum ON | 30 min | Protège la pompe contre les démarrages trop fréquents |
| Durée minimum OFF | 15 min | Laisse le moteur refroidir entre deux cycles |
| Plafond journalier | 18 h | Évite la surconsommation en cas de bug capteur |
| Plage horaire | 06h–23h | Évite de faire tourner la pompe la nuit (bruit, tarif) |
| Anti-régression | — | `H_target` ne peut que croître dans la journée |

---

### Cycle complet — résumé visuel

```
[Capteurs bruts]
      │
      ▼  lissage (moyenne glissante 1h / 3h)
[Moyennes]
      │
      ├──▶  H_min = T_eau / 2  (plancher)
      │
      ├──▶  H_dyn = H_min + ajustements UV + vent + chaleur
      │
      └──▶  H_target = max(H_target_veille, H_min, H_dyn)  ← figé à la hausse

[H_target vs H_done]  →  H_remaining = H_target − H_done
      │
      ▼
[Décision ON/OFF]
      ├── Fenêtre solaire active ?  →  ON
      ├── Retard critique ?         →  ON
      ├── Fin de journée en retard? →  ON
      └── Aucune condition          →  OFF
      │
      ▼
[Garde-fous]  →  anti-cycle, plage horaire, plafond
      │
      ▼
[Commande switch pompe]
```

---

### Mode hivernage

Activé manuellement via `switch.pool_winter_mode`. Remplace entièrement la logique normale.

**Si gel détecté** (T_air ≤ 0 °C **ou** T_eau ≤ 5 °C) :
La pompe tourne 1 h toutes les 4 h (durée et intervalle configurables).
L'objectif est de maintenir l'eau en mouvement pour éviter le gel des tuyaux.

**Si hiver sans gel** :
La pompe tourne 2 h par jour, réparties librement.
Suffit à éviter la stagnation et le développement bactérien.

La détection de gel se fait sur la température **actuelle** (non lissée) pour réagir rapidement.

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
| `sensor.pool_filtration_target_hours` | Objectif journalier calculé (h) |
| `sensor.pool_filtration_done_hours` | Temps déjà filtré aujourd'hui (h) |
| `sensor.pool_filtration_remaining_hours` | Temps restant à filtrer (h) |
| `sensor.pool_filtration_status` | ON / OFF logique |

### Capteurs de transparence

| Entité | Description |
|--------|-------------|
| `sensor.pool_decision_reason` | Pourquoi la pompe tourne (ou non) |
| `sensor.pool_system_state` | État global : normal / catching_up / winter / idle / degraded |
| `sensor.pool_delay_status` | À l'heure / En retard |
| `sensor.pool_time_remaining_window` | Temps restant dans la fenêtre solaire (h) |

### Capteurs calculés

| Entité | Description |
|--------|-------------|
| `sensor.pool_dynamic_target` | H_dyn du cycle en cours |
| `sensor.pool_minimum_target` | H_min du cycle en cours |
| `sensor.pool_water_temp_avg_3h` | Moyenne glissante température eau (3 h) |
| `sensor.pool_air_temp_avg_3h` | Moyenne glissante température air (3 h) |
| `sensor.pool_uv_avg_1h` | Moyenne glissante UV (1 h) |
| `sensor.pool_wind_avg_1h` | Moyenne glissante vent (1 h) |

### Switch

| Entité | Description |
|--------|-------------|
| `switch.pool_winter_mode` | Activer le mode hivernage |

---

## Mode hivernage

Activé via `switch.pool_winter_mode`.

| Condition | Comportement |
|-----------|--------------|
| T_air ≤ 0 °C **ou** T_eau ≤ 5 °C | 1 h toutes les 4 h (configurable) |
| Hiver sans gel | 2 h / jour |

---

## Garde-fous intégrés

- **Anti-court-cycle** : 30 min minimum ON, 15 min minimum OFF
- **Plages horaires** : 06h00 – 23h00 par défaut (configurable)
- **Plafond journalier** : 18 h maximum
- **Anti-régression** : l'objectif ne diminue jamais en cours de journée
- **Capteur indisponible** : valeurs de repli, état `degraded` visible

---

## Exemple concret

> Eau à 24 °C, UV 6, vent 25 km/h, air 29 °C — journée ensoleillée d'été

```
H_min  = 24 / 2 = 12 h
H_dyn  = 12 + 0.20×(6−3) + 0.04×(25−15) + 0.12×(29−26)
       = 12 + 0.60 + 0.40 + 0.36 = 13.36 h
H_target = 13.36 h
```

La pompe tourne ~13h36, réparties autour du midi solaire, avec rattrapage automatique si elle a été arrêtée manuellement.

---

## Options configurables

Accessibles via **Paramètres → Intégrations → Pool Filtration → Configurer** :

| Option | Défaut |
|--------|--------|
| Heure de remise à zéro | 00:00 |
| Heure de début autorisée | 06:00 |
| Heure de fin autorisée | 23:00 |
| Intervalle cycle hivernage | 4 h |
| Durée cycle hivernage | 60 min |
