# Διπλωματική Εργασία Βελτιστοποίησης Δικτύου 5G

[![Tests](https://img.shields.io/badge/tests-73%2F73%20passing-brightgreen)]() [![Defense Ready](https://img.shields.io/badge/status-defense%20ready-blue)]() [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()

Αυτό το αποθετήριο περιέχει ένα **έτοιμο για παραγωγή** σύστημα λήψης αποφάσεων handover βασισμένο σε μηχανική μάθηση για δίκτυα 5G, επικυρωμένο μέσω ολοκληρωμένης πειραματικής διαδικασίας και δοκιμών.

## 🎓 Σύνοψη Αποτελεσμάτων Διπλωματικής

**Κύρια Επιτεύγματα (επικυρωμένα σε ελεγχόμενο πείραμα):**
- **100% εξάλειψη ping-pong** (0% έναντι 37,50% σε παραδοσιακή λειτουργία A3)
- **422% βελτίωση χρόνου παραμονής σε cell** (133,71s έναντι 25,61s διάμεσος)
- **75% μείωση handover** (6 έναντι 24 handovers, μειώνοντας τον φόρτο σηματοδοσίας)
- **100% συμμόρφωση QoS** (όλα τα ML handovers βελτίωσαν καθυστέρηση, ρυθμαπόδοση και απώλεια πακέτων)
- **73/73 tests επιτυχημένα** (ολοκληρωμένη επικύρωση σε 8 φάσεις ανάπτυξης)

## 🚀 Γρήγορη Εκκίνηση

```bash
# Εγκατάσταση εξαρτήσεων
./scripts/install_system_deps.sh
./scripts/install_deps.sh

# Εκτέλεση πειράματος «Μίας Εντολής» (σύγκριση ML έναντι A3 για 10 λεπτά)
./scripts/run_thesis_experiment.sh 10 my_experiment

# Εκτέλεση tests
pytest
```

Τα αποτελέσματα παράγονται στο `thesis_results/my_experiment/` με οπτικοποιήσεις, μετρικές και ανάλυση.

## Αρχιτεκτονική Συστήματος

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   Σύστημα Βελτιστοποίησης Δικτύου 5G                    │
│                                                                         │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │   NEF Emulator      │◄──────────►│    ML Service                │    │
│  │   (FastAPI :8080)    │  Ανταλλαγή │    (Flask :5050)             │    │
│  │   - Κανόνες 3GPP A3 │  Features  │    - Πρόβλεψη LightGBM      │    │
│  │   - Μοντέλα Κινητ.  │            │    - Αποφάσεις QoS-Aware    │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
│           │                                        │                    │
│           ▼                                        ▼                    │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │  Kinisis UI (:3001) │            │  Prometheus (:9090) +        │    │
│  │  React + Leaflet     │            │  Grafana (:3000)             │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Δομή Αποθετηρίου

```
thesis/
├── 5g-network-optimization/
│   ├── services/
│   │   ├── nef-emulator/          # NEF Emulator (FastAPI) — δείτε το README του
│   │   ├── ml-service/            # ML Service (Flask) — δείτε το README του
│   │   └── kinisis_ui/            # React UI — δείτε το README του
│   ├── deployment/kubernetes/     # K8s manifests — δείτε το README του
│   ├── monitoring/                # Prometheus + Grafana — δείτε το README του
│   └── docker-compose.yml         # Ενορχήστρωση πλήρους στοίβας
├── scripts/                       # Scripts πειράματος, ανάλυσης και βοηθητικά
├── tests/                         # Ολοκληρωμένη σουίτα tests (73 tests)
├── mlops/                         # Feature store Feast, αγωγός δεδομένων
├── docs/                          # Λεπτομερής τεκμηρίωση (βλ. παρακάτω)
├── requirements.lock              # Κλειδωμένες εξαρτήσεις Python
├── requirements.txt               # Συμβολικός σύνδεσμος → requirements.lock
└── pytest.ini                     # Ρύθμιση tests
```

## Εκτέλεση του Συστήματος

Και οι δύο υπηρεσίες εκτελούνται μέσω `docker compose`. Ορίστε `ML_HANDOVER_ENABLED` για εναλλαγή λειτουργιών.

```bash
# Λειτουργία ML (συνιστάται)
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build

# Λειτουργία A3 μόνο (βάση σύγκρισης)
ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up --build

# Λειτουργία Ενός Container (ML εντός NEF)
ML_LOCAL=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

## Δοκιμές

```bash
# Γρήγορα: δημιουργία venv, εγκατάσταση εξαρτήσεων, εκτέλεση tests
./scripts/setup_tests.sh

# Ή χειροκίνητα
pip install -r requirements.txt
pytest
```

## 📚 Τεκμηρίωση

| Οδηγός | Περιγραφή |
|--------|-----------|
| **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Πλήρης αρχιτεκτονική συστήματος — επίπεδα υπηρεσιών, ροές δεδομένων, αντιστοίχιση O-RAN, αναφορά API |
| **[MANUAL.md](docs/MANUAL.md)** | Οδηγός λειτουργίας — ανάπτυξη, ρύθμιση παραμέτρων, παρακολούθηση, αντιμετώπιση προβλημάτων |
| **[THESIS.md](docs/THESIS.md)** | Τεχνική εμβάθυνση — αλγόριθμοι, μεθοδολογία, αποτελέσματα επικύρωσης, αναπαραγωγιμότητα |

Κάθε υπηρεσία διαθέτει επίσης το δικό της README με ρύθμιση ανά στοιχείο:
- [`nef-emulator/README.md`](5g-network-optimization/services/nef-emulator/README.md)
- [`ml-service/README.md`](5g-network-optimization/services/ml-service/README.md)
- [`kinisis_ui/README.md`](5g-network-optimization/services/kinisis_ui/README.md)
- [`monitoring/README.md`](5g-network-optimization/monitoring/README.md)
- [`kubernetes/README.md`](5g-network-optimization/deployment/kubernetes/README.md)
