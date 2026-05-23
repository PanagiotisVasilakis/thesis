# Εγχειρίδιο Λειτουργίας

Αυτός ο οδηγός παρέχει αναλυτικές οδηγίες για την εγκατάσταση, ρύθμιση, ανάπτυξη και λειτουργία του συστήματος βελτιστοποίησης δικτύων 5G.

## 📋 Πίνακας Περιεχομένων
1. [Προαπαιτούμενα & Εγκατάσταση](#προαπαιτούμενα--εγκατάσταση)
2. [Ρύθμιση Παραμέτρων](#ρύθμιση-παραμέτρων)
3. [Επιλογές Ανάπτυξης](#επιλογές-ανάπτυξης)
4. [Παραγωγή Δεδομένων](#παραγωγή-δεδομένων)
5. [Εκπαίδευση Μοντέλου](#εκπαίδευση-μοντέλου)
6. [Παρακολούθηση & Μετρικές](#παρακολούθηση--μετρικές)
7. [Αντιμετώπιση Προβλημάτων](#αντιμετώπιση-προβλημάτων)

---

## Προαπαιτούμενα & Εγκατάσταση

### Απαιτήσεις Συστήματος
- **Λειτουργικό Σύστημα**: Linux, macOS ή Windows (WSL2)
- **Docker**: v23.0+
- **Python**: 3.10+
- **Πόροι**: 8GB RAM, 10GB αποθηκευτικός χώρος

### Εγκατάσταση
```bash
cd ~/thesis

# 1. Εγκατάσταση βιβλιοθηκών συστήματος (libcairo κ.λπ.)
./scripts/install_system_deps.sh

# 2. Εγκατάσταση εξαρτήσεων Python
./scripts/install_deps.sh

# 3. Ρύθμιση Python path
export PYTHONPATH="${PWD}:${PWD}/5g-network-optimization/services:${PYTHONPATH}"
```

---

## Ρύθμιση Παραμέτρων

Ο έλεγχος της συμπεριφοράς του συστήματος γίνεται μέσω μεταβλητών περιβάλλοντος στο αρχείο `.env` ή μέσω Docker Compose.

### Βασικές Ρυθμίσεις
| Μεταβλητή | Προεπιλογή | Περιγραφή |
|-----------|------------|-----------|
| `ML_HANDOVER_ENABLED` | `unset` | `1`=ML, `0`=A3. Χωρίς τιμή=Αυτόματο (χρήση ML εάν ≥3 κεραίες). |
| `ML_CONFIDENCE_THRESHOLD` | `0.5` | Ελάχιστη βεβαιότητα πρόβλεψης για επιλογή κεραίας. |
| `MODEL_TYPE` | `lightgbm` | Επιλογές: `lightgbm`, `lstm`, `ensemble`. |

### Πρόληψη Φαινομένου Ping-Pong
| Μεταβλητή | Προεπιλογή | Περιγραφή |
|-----------|------------|-----------|
| `MIN_HANDOVER_INTERVAL_S` | `2.0` | Ελάχιστα δευτερόλεπτα μεταξύ διαδοχικών handovers. |
| `MAX_HANDOVERS_PER_MINUTE` | `3` | Μέγιστος ρυθμός handovers ανά λεπτό. |
| `PINGPONG_WINDOW_S` | `10.0` | Χρονικό παράθυρο για ανίχνευση επιστροφής σε προηγούμενο κελί. |

### Ρυθμίσεις QoS
| Μεταβλητή | Προεπιλογή | Περιγραφή |
|-----------|------------|-----------|
| `QOS_URLLC_MIN_CONFIDENCE` | `0.85` | Απαιτούμενη βεβαιότητα για URLLC slices. |
| `QOS_EMBB_MIN_CONFIDENCE` | `0.70` | Απαιτούμενη βεβαιότητα για eMBB slices. |

---

## Επιλογές Ανάπτυξης

### 1. Docker Compose (Τοπική Ανάπτυξη)

**Λειτουργία ML (Συνιστάται)**
```bash
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```
- **Σημεία Πρόσβασης**:
    - NEF Emulator: `http://localhost:8080`
    - ML Service: `http://localhost:5050`
    - Prometheus: `http://localhost:9090`
    - Grafana: `http://localhost:3000` (use `GF_SECURITY_ADMIN_PASSWORD` from the local environment)

**Λειτουργία A3 (Baseline)**
```bash
ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

### 2. Kubernetes (Παραγωγή)
Ανατρέξτε στο [`5g-network-optimization/deployment/kubernetes/README.md`](../5g-network-optimization/deployment/kubernetes/README.md) για τα manifests και τα helm charts.

---

## Παραγωγή Δεδομένων

Δημιουργία συνθετικών συνόλων δεδομένων QoS σύμφωνα με τις προδιαγραφές 3GPP, για χρήση στην εκπαίδευση.

```bash
# Ισορροπημένο σύνολο δεδομένων (eMBB, URLLC, mMTC)
python scripts/data_generation/synthetic_generator.py \
  --records 10000 \
  --profile balanced \
  --output output/qos_dataset.csv \
  --seed 42

# Προφίλ βαρύτητας σε URLLC
python scripts/data_generation/synthetic_generator.py \
  --records 5000 \
  --profile urllc-heavy \
  --output output/urllc_data.json
```

---

## Εκπαίδευση Μοντέλου

### Αυτόματη Εκπαίδευση
Η υπηρεσία ML εκπαιδεύει αυτόματα το μοντέλο κατά την εκκίνηση, εφόσον δεν υπάρχει προηγούμενο μοντέλο ή εάν ανιχνευθεί data drift (`AUTO_RETRAIN=true`).

### Χειροκίνητη Εκπαίδευση μέσω API
```bash
# 1. Λήψη Token αυθεντικοποίησης
TOKEN=$(curl -s -X POST http://localhost:5050/api/login -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# 2. Ενεργοποίηση εκπαίδευσης
curl -X POST http://localhost:5050/api/train \
  -H "Authorization: Bearer $TOKEN" \
  -d @output/training_data.json
```

---

## Παρακολούθηση & Μετρικές

### Βασικές Μετρικές Prometheus
- `ml_prediction_requests_total`: Συνολικός αριθμός προβλέψεων που εξυπηρετήθηκαν.
- `ml_prediction_latency_seconds`: Κατανομή καθυστέρησης (στόχος <30ms).
- `ml_pingpong_suppressions_total`: Αριθμός αποτρεπόμενων ping-pong handovers.
- `nef_handover_decisions_total`: Handovers που εκτελέστηκαν σε σύγκριση με αυτά που παρακάμφθηκαν.

### Dashboards Grafana
Πρόσβαση στο `http://localhost:3000` για προβολή των προ-ρυθμισμένων dashboards:
1. **Επισκόπηση ML Service**: Καθυστέρηση, βασικά χαρακτηριστικά, drift.
2. **Κατάσταση Δικτύου**: Θέσεις UE σε πραγματικό χρόνο, φορτίο κεραιών.
3. **Συγκριτική Ανάλυση**: Μετρικές απόδοσης ML έναντι A3.

---

## Αντιμετώπιση Προβλημάτων

### Script Επαλήθευσης
Εκτέλεση του ενσωματωμένου ελέγχου συστήματος:
```bash
bash scripts/verify_system_ready.sh --ml
```

### Συχνά Προβλήματα
1. **Η υπηρεσία δεν εκκινεί**: Ελέγξτε τα logs με `docker compose logs ml-service`.
2. **Σφάλμα εξουσιοδότησης**: Βεβαιωθείτε ότι η μεταβλητή `AUTH_USERNAME` αντιστοιχεί στο αρχείο `.env`.
3. **Δεν πραγματοποιούνται handovers**: Επαληθεύστε ότι τα UEs κινούνται (`/api/v1/ue_movement/start`).

---

## Έλεγχος Εκδόσεων & Κυκλοφορία

### Αρχείο Έκδοσης
Ο ριζικός κατάλογος του αποθετηρίου περιέχει ένα αρχείο `VERSION` με την τρέχουσα σημασιολογική έκδοση (π.χ. `1.0.0`). Αυτό το αρχείο αποτελεί τη μοναδική πηγή αλήθειας για τον αριθμό έκδοσης.

### Git Tagging για Ορόσημα Διπλωματικής

Χρήση annotated tags για τη σήμανση σημαντικών σταδίων της διπλωματικής:

```bash
# Ανάγνωση τρέχουσας έκδοσης
VERSION=$(cat VERSION)

# Tag για υποβολή διπλωματικής
git tag -a "v${VERSION}-thesis-final" -m "Thesis final submission - ML-based handover optimization"

# Tag για έκδοση υποστήριξης (σε περίπτωση ενημερώσεων)
git tag -a "v${VERSION}-defense" -m "Thesis defense demonstration version"

# Αποστολή tags στο απομακρυσμένο αποθετήριο
git push origin --tags
```

### Σύμβαση Ονοματοδοσίας Tags
- **Μορφή**: `v{VERSION}-{milestone}`
- **Παραδείγματα**:
  - `v1.0.0-thesis-final` — Υποβληθείσα έκδοση διπλωματικής
  - `v1.0.0-defense` — Έκδοση παρουσίασης/υποστήριξης
  - `v1.0.1-camera-ready` — Τελική έκδοση μετά την αξιολόγηση

### Αναπαραγωγιμότητα
Για αναπαραγωγή οποιασδήποτε σημειωμένης έκδοσης:
```bash
git checkout v1.0.0-thesis-final
docker compose up -d
```

---

**Λίστα Ελέγχου End-to-End Demo**: Ανατρέξτε στο [`docs/THESIS.md`](THESIS.md) για την παρουσίαση υποστήριξης.

**Πλήρης Αναφορά Αρχιτεκτονικής**: Ανατρέξτε στο [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) για λεπτομέρειες υπηρεσιών, ροές δεδομένων και αναφορά API.
