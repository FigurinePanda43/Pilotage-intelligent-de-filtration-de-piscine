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

## Formules

```
H_min  = clamp(T_eau / 2 ; 2 h ; 16 h)

H_dyn  = clamp(
    T_eau / 2
    + 0.20 × max(UV − 3, 0)
    + 0.04 × max(Vent − 15 km/h, 0)
    + 0.12 × max(T_air − 26 °C, 0)
; 2 h ; 18 h)

H_target = max(H_target_précédent, H_min, H_dyn)   ← ne diminue jamais
```

La **fenêtre prioritaire** est centrée sur le zénith solaire local (±4 h).

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
