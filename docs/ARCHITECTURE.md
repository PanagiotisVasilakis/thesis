# Αρχιτεκτονική Συστήματος

**Έκδοση:** 2.1 | **Τελευταία Ενημέρωση:** Μάρτιος 2026 | **Συγγραφέας:** Υλοποίηση Διπλωματικής

---

## Πίνακας Περιεχομένων

1. [Εκτελεστική Σύνοψη](#εκτελεστική-σύνοψη)
2. [Αρχιτεκτονική Υψηλού Επιπέδου](#αρχιτεκτονική-υψηλού-επιπέδου)
3. [Αντιστοίχιση Αρχιτεκτονικής O-RAN](#αντιστοίχιση-αρχιτεκτονικής-o-ran)
4. [Λεπτομέρειες Επιπέδου Υπηρεσιών](#λεπτομέρειες-επιπέδου-υπηρεσιών)
   - [NEF Emulator (Προσομοιωτής RAN)](#1-nef-emulator-προσομοιωτής-ran)
   - [ML Service](#2-ml-service)
   - [Kinisis UI](#3-kinisis-ui)
5. [Βασικά Υποσυστήματα](#βασικά-υποσυστήματα)
   - [Μοντέλο Καναλιού](#υποσύστημα-μοντέλου-καναλιού)
   - [Μηχανή Handover](#υποσύστημα-μηχανής-handover)
   - [Μετρικές & Ανίχνευση RLF](#υποσύστημα-μετρικών--ανίχνευσης-rlf)
   - [Γραμμή Πρόβλεψης ML](#γραμμή-πρόβλεψης-ml)
6. [Επίπεδο Δεδομένων](#επίπεδο-δεδομένων)
7. [Scripts & Πλαίσιο Ανάλυσης](#scripts--πλαίσιο-ανάλυσης)
8. [Γραμμή MLOps](#γραμμή-mlops)
9. [Υποδομή Δοκιμών](#υποδομή-δοκιμών)
10. [Αρχιτεκτονική Ανάπτυξης](#αρχιτεκτονική-ανάπτυξης)
11. [Ροές Δεδομένων](#ροές-δεδομένων)
12. [Αναφορά Ρυθμίσεων](#αναφορά-ρυθμίσεων)
13. [Αναφορά API](#αναφορά-api)

---

## Εκτελεστική Σύνοψη

Το σύστημα αυτό υλοποιεί ένα **πλαίσιο βελτιστοποίησης handover υποβοηθούμενο από ML** για δίκτυα 5G, σχεδιασμένο για τη σύγκριση μεθόδων μηχανικής μάθησης έναντι του πρότυπου **κανόνα handover βασισμένου στο γεγονός A3 κατά 3GPP**. Η αρχιτεκτονική ακολουθεί τις αρχές του O-RAN Alliance με κατάλληλες απλοποιήσεις για ερευνητικούς σκοπούς.

### Βασικές Δυνατότητες

| Δυνατότητα | Υλοποίηση |
|------------|-----------|
| **Απόφαση Handover** | ML (LightGBM) έναντι baseline 3GPP A3 |
| **Μοντελοποίηση Καναλιού** | AR1 shadowing, Rayleigh fading, 3GPP path loss |
| **Πρόληψη Ping-Pong** | Προστασία 3 επιπέδων (χρόνος παραμονής, χαρακτηριστικά ML, μεροληψία QoS) |
| **Ερμηνευσιμότητα** | Ερμηνευσιμότητα μοντέλου βασισμένη σε SHAP |
| **Οπτικοποίηση Πραγματικού Χρόνου** | Μετάδοση μετρικών μέσω WebSocket |
| **Στατιστική Ανάλυση** | Ζευγαρωτές δοκιμές, bootstrap CI, διόρθωση Bonferroni |

### Επικυρωμένα Αποτελέσματα

|      Μετρική       | Λειτουργία ML |  Baseline A3  |       Βελτίωση        |
|--------------------|---------------|---------------|----------------------|
| Ρυθμός Ping-Pong   |      0%       |    40-60%     | **100% εξάλειψη**    |
| Αριθμός Handovers  |   Μειωμένος   |   Baseline    | **~75% μείωση**      |
| Μέσος Χρ. Παραμονής|    5.22s      |    ~1.0s      | **422% αύξηση**      |
| Απώλεια Κάλυψης    | Διατηρήθηκε   |   Baseline    |    Ισοδύναμη         |

---

## Αρχιτεκτονική Υψηλού Επιπέδου


```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                    PRESENTATION LAYER                                    │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                              Kinisis UI (React 18 + Vite)                          │  │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐             │  │
│  │  │  MapPage  │ │ Dashboard │ │ Scenarios │ │  Metrics  │ │  Config   │             │  │
│  │  │ (Leaflet) │ │  (Charts) │ │  (Select) │ │  (Live)   │ │  (Forms)  │             │  │
│  │  └───────────┘ └───────────┘ └───────────┘ └───────────┘ └───────────┘             │  │
│  │  ┌──────────────────────────────────────────────────────────────────────────────┐  │  │
│  │  │  SignalPanel | RealTimeMetrics | RetryModal | AntennaMarkers | UETrajectory  │  │  │
│  │  └──────────────────────────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────────────────┘  │
│                                          │ HTTP/REST + WebSocket                         │
└──────────────────────────────────────────┼───────────────────────────────────────────────┘
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                       API LAYER                                          │
│  ┌────────────────────────────────────┐    ┌────────────────────────────────────────┐    │
│  │    NEF Emulator / RAN Simulator    │    │           ML Service                   │    │
│  │         (FastAPI - Port 8080)      │    │       (Flask - Port 5050)              │    │
│  │  ┌──────────────────────────────┐  │    │  ┌──────────────────────────────────┐  │    │
│  │  │ REST Endpoints:              │  │    │  │ REST Endpoints:                  │  │    │
│  │  │  • /api/v1/ue/*              │  │◄──►│  │  • POST /predict                 │  │    │
│  │  │  • /api/v1/cells/*           │  │    │  │  • POST /predict/batch           │  │    │
│  │  │  • /api/v1/handover/*        │  │    │  │  • GET  /health                  │  │    │
│  │  │  • /api/v1/scenarios/*       │  │    │  │  • GET  /metrics                 │  │    │
│  │  │  • /api/v1/experiments/*     │  │    │  │  • POST /feedback                │  │    │
│  │  │  • WS /ws/metrics            │  │    │  │  • GET  /model/info              │  │    │
│  │  └──────────────────────────────┘  │    │  └──────────────────────────────────┘  │    │
│  └────────────────────────────────────┘    └────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                   BUSINESS LOGIC LAYER                                   │
│                                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              HANDOVER ENGINE (engine.py)                            │ │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐                   │ │
│  │  │    ML Mode       │  │    A3 Mode       │  │   Hybrid Mode    │                   │ │
│  │  │  (LightGBM)      │  │  (3GPP TS 38.331)│  │  (ML + fallback) │                   │ │
│  │  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘                   │ │
│  │           └─────────────────────┴─────────────────────┘                             │ │
│  │                                     │                                               │ │
│  │  ┌──────────────────────────────────┴──────────────────────────────────┐            │ │
│  │  │   Per-UE TTT Timers  │  Ping-Pong Prevention  │  QoS-Aware Boost    │            │ │
│  │  └─────────────────────────────────────────────────────────────────────┘            │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                          │
│  ┌────────────────────────────┐  ┌────────────────────────────┐                          │
│  │      A3EventRule           │  │    NetworkStateManager     │                          │
│  │  ┌──────────────────────┐  │  │  ┌──────────────────────┐  │                          │
│  │  │ • Hysteresis (2dB)   │  │  │  │ • UE State Tracking  │  │                          │
│  │  │ • TTT Support        │  │  │  │ • Feature Extraction │  │                          │
│  │  │ • RSRP/RSRQ events   │  │  │  │ • Signal Calculation │  │                          │
│  │  │ • 3GPP Compliance    │  │  │  │ • Cell Management    │  │                          │
│  │  └──────────────────────┘  │  │  └──────────────────────┘  │                          │
│  └────────────────────────────┘  └────────────────────────────┘                          │
│                                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                            CHANNEL MODEL (rf_models/)                               │ │
│  │  ┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────────┐  │ │
│  │  │    Path Loss Models   │ │  AR1 Shadowing Model  │ │  Rayleigh Fading Model    │  │ │
│  │  │  • ABG (3GPP 38.901)  │ │  • σ_SF = 4-8 dB      │ │  • Doppler-aware          │  │ │
│  │  │  • CI (Close-In)      │ │  • d_corr = 37m       │ │  • Coherence time         │  │ │
│  │  │  • UMa/UMi variants   │ │  • Spatial correlation│ │  • Division-by-0 safe     │  │ │
│  │  └───────────────────────┘ └───────────────────────┘ └───────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                          METRICS & RLF DETECTION (metrics/)                         │ │
│  │  ┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────────┐  │ │
│  │  │    RLF Detector       │ │ Throughput Calculator │ │  Interruption Tracker     │  │ │
│  │  │  • T310 timer (1s)    │ │  • Shannon capacity   │ │  • Queue-based tracking   │  │ │
│  │  │  • >= comparison      │ │  • RLF zone degrade   │ │  • Overlap handling       │  │ │
│  │  │  • HO exception       │ │  • Piecewise model    │ │  • 50ms interruption      │  │ │
│  │  └───────────────────────┘ └───────────────────────┘ └───────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                       ML/AI LAYER                                       │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                           LightGBM Handover Model                                  │ │
│  │  ┌───────────────────────────────────────────────────────────────────────────────┐ │ │
│  │  │  INPUT FEATURES (12):                                                         │ │ │
│  │  │  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐               │ │ │
│  │  │  │ Signal Features  │ │ Distance Features│ │ Mobility Features│               │ │ │
│  │  │  │ • rsrp_serving   │ │ • dist_serving   │ │ • velocity       │               │ │ │
│  │  │  │ • rsrp_neighbor  │ │ • dist_neighbor  │ │ • heading        │               │ │ │
│  │  │  │ • rsrp_diff      │ │ • dist_diff      │ │ • time_since_ho  │               │ │ │
│  │  │  │ • sinr_serving   │ └──────────────────┘ │ • ho_count_1min  │               │ │ │
│  │  │  │ • sinr_neighbor  │                      └──────────────────┘               │ │ │
│  │  │  │ • sinr_diff      │                                                         │ │ │
│  │  │  └──────────────────┘                                                         │ │ │
│  │  └───────────────────────────────────────────────────────────────────────────────┘ │ │
│  │  ┌───────────────────────────────────────────────────────────────────────────────┐ │ │
│  │  │  OUTPUT: handover_probability (0.0 - 1.0)                                     │ │ │
│  │  │  THRESHOLD: ML_CONFIDENCE_THRESHOLD (default: 0.5, QoS-adjusted: 0.6)         │ │ │
│  │  │  CALIBRATION: Isotonic regression for improved probability estimates          │ │ │
│  │  └───────────────────────────────────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                         │
│  ┌────────────────────────────────┐  ┌────────────────────────────────────────────────┐ │
│  │    SHAP Interpretability       │  │         Ping-Pong Prevention Stack             │ │
│  │  ┌──────────────────────────┐  │  │  ┌──────────────────────────────────────────┐  │ │
│  │  │ Modes:                   │  │  │  │ Layer 1: MIN_DWELL_TIME_S = 3.0s         │  │ │
│  │  │ • OFF (batch)            │  │  │  │ Layer 2: ho_count_last_minute feature    │  │ │
│  │  │ • SAMPLED (10%)          │  │  │  │ Layer 3: QoS-aware confidence boost      │  │ │
│  │  │ • ALWAYS (demo)          │  │  │  └──────────────────────────────────────────┘  │ │
│  │  │ TreeExplainer + safety   │  │  └────────────────────────────────────────────────┘ │
│  │  └──────────────────────────┘  │                                                     │
│  └────────────────────────────────┘                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       DATA LAYER                                           │
│  ┌─────────────────────┐ ┌───────────────────────┐ ┌──────────────────────────────────┐    │
│  │    PostgreSQL       │ │      MongoDB          │ │       Feast Feature Store        │    │
│  │    (Port 5432)      │ │    (Port 27017)       │ │                                  │    │
│  │  ┌───────────────┐  │ │  ┌─────────────────┐  │ │  ┌────────────────────────────┐  │    │
│  │  │ • UE Records  │  │ │  │ • Time Series   │  │ │  │ feature_repo/              │  │    │
│  │  │ • Cell Config │  │ │  │ • ML Predictions│  │ │  │  • ue_features.py          │  │    │
│  │  │ • Handover Log│  │ │  │ • Raw Signals   │  │ │  │  • cell_features.py        │  │    │
│  │  │ • Experiments │  │ │  │ • SHAP Values   │  │ │  │ Offline: Parquet files     │  │    │
│  │  │ • Scenarios   │  │ │  │ • Metrics Hist  │  │ │  │ Online: Redis/SQLite       │  │    │
│  │  └───────────────┘  │ │  └─────────────────┘  │ │  └────────────────────────────┘  │    │
│  └─────────────────────┘ └───────────────────────┘ └──────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                  INFRASTRUCTURE LAYER                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              Docker Compose Stack                                    │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │ │
│  │  │nef-emu   │ │ml-service│ │kinisis-ui│ │ postgres │ │ mongodb  │ │  redis   │    │ │
│  │  │  :8080   │ │  :5050   │ │  :3001   │ │  :5432   │ │  :27017  │ │  :6379   │    │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘    │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              Monitoring Stack                                        │ │
│  │  ┌────────────────────────────┐  ┌────────────────────────────────────────────────┐ │ │
│  │  │ Prometheus (Port 9090)     │  │ Grafana (Port 3000)                            │ │ │
│  │  │ • Service metrics          │  │ • Pre-built dashboards                         │ │ │
│  │  │ • Handover counters        │  │ • Real-time visualization                      │ │ │
│  │  │ • Latency histograms       │  │ • Alert management                             │ │ │
│  │  └────────────────────────────┘  └────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                            Kubernetes (Optional)                                     │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               │ │
│  │  │ Deployments  │ │  Services    │ │ ConfigMaps   │ │   Ingress    │               │ │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘               │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```


---

## Αντιστοίχιση Αρχιτεκτονικής O-RAN

Η υλοποίηση αντιστοιχίζεται στην αρχιτεκτονική αναφοράς του O-RAN Alliance:

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                              O-RAN Reference Mapping                                      │
│                                                                                           │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                          Service Management & Orchestration                      │   │
│   │                               (SMO - Non-RT RIC)                                 │   │
│   │   ┌────────────────────────────────────────────────────────────────────────┐    │   │
│   │   │  Kinisis UI ──────────────► Dashboard / Orchestration Interface        │    │   │
│   │   │  MLOps Pipeline ──────────► Model Training & Lifecycle Management      │    │   │
│   │   │  Feast Feature Store ─────► R1 Interface (ML Model Support)            │    │   │
│   │   └────────────────────────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                          │ A1 Interface (Policy)                         │
│                                          ▼                                               │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                            Near-RT RIC (10ms - 1s)                               │   │
│   │   ┌────────────────────────────────────────────────────────────────────────┐    │   │
│   │   │  ML Service ──────────────► Handover Optimization xApp                 │    │   │
│   │   │  SHAP Explainer ──────────► Model Interpretability Function            │    │   │
│   │   │  QoS Bias Module ─────────► QoS-Aware Decision Modification            │    │   │
│   │   └────────────────────────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                          │ E2 Interface (simplified as REST/JSON)       │
│                                          ▼                                               │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                              E2 Node (RAN Simulation)                            │   │
│   │   ┌────────────────────────────────────────────────────────────────────────┐    │   │
│   │   │  NEF Emulator ────────────► gNB-DU/CU Simulation                       │    │   │
│   │   │  Channel Model ───────────► Radio Channel Simulation                   │    │   │
│   │   │  A3 Rule Engine ──────────► 3GPP Baseline Handover                     │    │   │
│   │   │  Handover Engine ─────────► Decision Execution                         │    │   │
│   │   └────────────────────────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                           │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```


### Απλοποιήσεις Πρωτοκόλλων

| Πραγματικό O-RAN | Αυτή η Υλοποίηση | Αιτιολόγηση |
|-------------------|-------------------|-------------|
| ASN.1 + SCTP + E2AP | JSON + HTTP REST | Ερευνητική εστίαση σε αλγορίθμους, όχι πρωτόκολλα |
| E2SM-KPM/RC schemas | Προσαρμοσμένα JSON schemas | Ευελιξία για γρήγορο πειραματισμό |
| Σύνθετη συνδρομή | Request-response / WebSocket | Απλούστερη υλοποίηση και αποσφαλμάτωση |
| Τυπικά Service Models | Προσαρμοσμένες μετρικές & έλεγχοι | Απαιτήσεις ειδικές για τη διπλωματική |

### Διατηρημένες Αρχιτεκτονικές Αρχές

- ✅ **Διαχωρισμός ευθυνών**: Προσομοιωτής RAN ↔ Ευφυής ελεγκτής
- ✅ **Σαφή όρια διεπαφών**: Καλά ορισμένα συμβόλαια API
- ✅ **Καθυστέρηση Near-RT**: Βρόχος αποφάσεων <1 δευτερόλεπτο
- ✅ **Αναφορά μετρικών**: Ανάλογη με E2 Indication
- ✅ **Ενέργειες ελέγχου**: Ανάλογες με E2 Control

---

## Λεπτομέρειες Επιπέδου Υπηρεσιών

### 1. NEF Emulator (Προσομοιωτής RAN)

**Τοποθεσία:** `5g-network-optimization/services/nef-emulator/`
**Τεχνολογία:** FastAPI (Python 3.10+)
**Θύρα:** 8080

#### Δομή Καταλόγου


```
nef-emulator/
├── backend/app/app/
│   ├── api/                    # REST API routes
│   │   ├── v1/
│   │   │   ├── endpoints/      # API endpoint handlers
│   │   │   │   ├── ue.py       # UE management
│   │   │   │   ├── cells.py    # Cell management
│   │   │   │   ├── handover.py # Handover operations
│   │   │   │   ├── scenarios.py# Scenario management
│   │   │   │   └── experiments.py # Experiment control
│   │   │   └── api.py          # API router aggregation
│   │   └── deps.py             # Dependency injection
│   ├── handover/               # Handover decision logic
│   │   ├── engine.py           # Main HandoverEngine class
│   │   ├── a3_rule.py          # 3GPP A3 event implementation
│   │   └── runtime.py          # Simulation runtime
│   ├── metrics/                # Metrics and RLF detection
│   │   ├── rlf_detector.py     # RLF detection (Fixes #4,5,6,26,27)
│   │   └── __init__.py
│   ├── network/                # Network state management
│   │   └── state_manager.py    # NetworkStateManager
│   ├── mobility_models/        # UE movement patterns
│   ├── simulation/             # Simulation orchestration
│   └── core/                   # Core utilities
├── rf_models/                  # Channel models (Fixes #3,24,25)
│   ├── channel_model.py        # AR1 shadowing + Rayleigh fading
│   └── path_loss.py            # 3GPP path loss models
├── docs/
│   ├── ORAN_TERMINOLOGY.md     # O-RAN mapping (Fix #9,10)
│   └── antenna_and_path_loss.md
└── tests/
```


#### Βασικές Κλάσεις

| Κλάση | Αρχείο | Αρμοδιότητα |
|-------|--------|-------------|
| `HandoverEngine` | `handover/engine.py` | Ενορχήστρωση αποφάσεων ML/A3, διαχείριση χρονοδιακοπτών TTT |
| `A3EventRule` | `handover/a3_rule.py` | Συμμόρφωση με 3GPP TS 38.331 γεγονός A3 |
| `NetworkStateManager` | `network/state_manager.py` | Κατάσταση UE, εξαγωγή χαρακτηριστικών |
| `ChannelModel` | `rf_models/channel_model.py` | AR1 shadowing, Rayleigh fading |
| `RLFDetector` | `metrics/rlf_detector.py` | Ανίχνευση αποτυχίας ραδιοζεύξης (Radio Link Failure) |
| `ThroughputCalculator` | `metrics/rlf_detector.py` | Αντιστοίχιση SINR σε ρυθμαπόδοση |
| `HandoverInterruptionTracker` | `metrics/rlf_detector.py` | Παρακολούθηση διακοπών βασισμένη σε ουρά |

#### Λειτουργίες Handover

```python
class HandoverEngine:
    # Τρεις λειτουργικές καταστάσεις
    handover_mode: Literal["ml", "a3", "hybrid"]
    
    # ML mode: Αποκλειστικά αποφάσεις βασισμένες σε ML
    # A3 mode: Αποκλειστικά κανόνας 3GPP A3
    # Hybrid mode: ML με εφεδρικό A3 (συνιστάται)
```

---

### 2. ML Service

**Τοποθεσία:** `5g-network-optimization/services/ml-service/`
**Τεχνολογία:** Flask (Python 3.10+)
**Θύρα:** 5050

#### Δομή Καταλόγου


```
ml-service/ml_service/app/
├── api/                        # API routes
│   └── routes.py               # Flask routes
├── models/                     # ML models
│   ├── lightgbm_selector.py    # Primary LightGBM model
│   ├── antenna_selector.py     # Base selector interface
│   ├── interpretability.py     # SHAP utilities (Fixes #14,15,28)
│   ├── ping_pong_prevention.py # Anti-ping-pong logic
│   ├── qos_bias.py             # QoS-aware threshold adjustment
│   ├── onnx_selector.py        # ONNX runtime support
│   ├── ensemble_selector.py    # Ensemble methods
│   └── hyperparameter_tuning.py# Hyperparameter optimization
├── data/                       # Data processing
│   └── feature_extractor.py    # Feature engineering
├── config/                     # Configuration
│   ├── feature_specs.py        # Feature definitions
│   └── constants.py            # Model constants
├── optimization/               # Performance optimization
│   ├── warmup.py               # Model warm-up utilities
│   └── fast_scaler.py          # Optimized scaling
├── auth/                       # Authentication
├── qos/                        # QoS management
└── monitoring/                 # Metrics export
```


#### Αρχιτεκτονική Μοντέλου


```
┌────────────────────────────────────────────────────────────────────┐
│                    LightGBM Handover Classifier                     │
├────────────────────────────────────────────────────────────────────┤
│  Hyperparameters:                                                   │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ • n_estimators: 100 (env: N_ESTIMATORS)                    │    │
│  │ • max_depth: 10                                            │    │
│  │ • num_leaves: 31                                           │    │
│  │ • learning_rate: 0.1                                       │    │
│  │ • feature_fraction: 1.0                                    │    │
│  │ • random_state: 42 (reproducibility)                       │    │
│  └────────────────────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────────────────────┤
│  Confidence Calibration:                                            │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ • Method: Isotonic regression (or Platt scaling)           │    │
│  │ • Purpose: Improve probability estimate reliability        │    │
│  │ • Config: CALIBRATE_CONFIDENCE=true, CALIBRATION_METHOD    │    │
│  └────────────────────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────────────────────┤
│  Input Features (12):                                               │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────┐   │
│  │ Signal (6)      │ │ Distance (3)    │ │ Mobility (3)        │   │
│  │ rsrp_serving    │ │ dist_serving    │ │ velocity            │   │
│  │ rsrp_neighbor   │ │ dist_neighbor   │ │ heading             │   │
│  │ rsrp_diff       │ │ dist_diff       │ │ time_since_last_ho  │   │
│  │ sinr_serving    │ └─────────────────┘ │ ho_count_last_min   │   │
│  │ sinr_neighbor   │                     └─────────────────────┘   │
│  │ sinr_diff       │                                               │
│  └─────────────────┘                                               │
├────────────────────────────────────────────────────────────────────┤
│  Output:                                                            │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ • handover_probability: float [0.0, 1.0]                   │    │
│  │ • recommended_action: "handover" | "stay"                  │    │
│  │ • confidence: float (calibrated probability)               │    │
│  │ • shap_values: Optional[Dict] (if SHAP enabled)            │    │
│  └────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
```


#### Ρύθμιση SHAP (Διορθώσεις #14, #15, #28)

```python
class SHAPMode(Enum):
    OFF = "off"           # Απενεργοποιημένο (ταχύτερο, για μαζικά πειράματα)
    SAMPLED = "sampled"   # Υπολογισμός για X% των αποφάσεων (προεπιλογή 10%)
    ALWAYS = "always"     # Υπολογισμός για κάθε απόφαση (UI/demo)

@dataclass
class SHAPConfig:
    mode: SHAPMode = SHAPMode.OFF
    sample_rate: float = 0.1
    validate_additivity: bool = False
    additivity_tolerance: float = 0.01
```

---

### 3. Kinisis UI

**Τοποθεσία:** `5g-network-optimization/services/kinisis_ui/`
**Τεχνολογία:** React 18 + Vite + Leaflet
**Θύρα:** 3001

#### Δομή Καταλόγου


```
kinisis_ui/
├── src/
│   ├── pages/
│   │   ├── MapPage.jsx         # Interactive map with UE/cell markers
│   │   ├── Dashboard.jsx       # Overview metrics and charts
│   │   ├── Scenarios.jsx       # Scenario selection and config
│   │   ├── Metrics.jsx         # Detailed metrics view
│   │   └── Config.jsx          # System configuration
│   ├── components/
│   │   ├── SignalPanel.jsx     # UE signal quality table
│   │   ├── RealTimeMetrics.jsx # WebSocket metrics display
│   │   ├── RetryModal.jsx      # ML service retry UI
│   │   ├── AntennaMarkers.jsx  # Cell visualization
│   │   ├── UEMarker.jsx        # UE position markers
│   │   └── UETrajectory.jsx    # Movement path visualization
│   ├── services/
│   │   ├── api.js              # REST API client
│   │   └── websocket.js        # WebSocket connection
│   └── hooks/
│       └── useWebSocket.js     # WebSocket React hook
├── public/
└── vite.config.js
```


---

## Βασικά Υποσυστήματα

### Υποσύστημα Μοντέλου Καναλιού

**Τοποθεσία:** `nef-emulator/rf_models/channel_model.py`

Υλοποιεί τις Διορθώσεις #3, #24, #25 της διπλωματικής:


```
┌───────────────────────────────────────────────────────────────────────────────┐
│                            Channel Model Pipeline                              │
│                                                                                │
│   UE Position ──► Path Loss ──► Shadowing ──► Fading ──► Total Loss ──► RSRP │
│       │              │             │            │                             │
│       │              ▼             ▼            ▼                             │
│       │         ┌─────────┐  ┌─────────┐  ┌─────────┐                        │
│       │         │3GPP ABG │  │  AR1    │  │Rayleigh │                        │
│       │         │ PL(d,f) │  │  σ=4dB  │  │ Doppler │                        │
│       │         │ α,β,γ   │  │ d_c=37m │  │ aware   │                        │
│       │         └─────────┘  └─────────┘  └─────────┘                        │
│       │                                                                       │
│  ┌────┴────────────────────────────────────────────────────────────────────┐ │
│  │ Fix #3: RSRP = TX_power - path_loss - shadowing - fading_loss           │ │
│  │         (All components properly signed)                                 │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │ Fix #24: Doppler Division-by-Zero Protection                             │ │
│  │ if velocity < 0.1 m/s:                                                   │ │
│  │     coherence_time = 10.0s  # Stationary UE                              │ │
│  │ else:                                                                    │ │
│  │     f_d = (velocity * f_c) / c  # Doppler frequency                      │ │
│  │     coherence_time = 0.423 / f_d                                         │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │ Fix #25: Shadowing Initial Seeding                                       │ │
│  │ if first_call:                                                           │ │
│  │     shadowing = N(0, σ_SF)  # Draw from target distribution              │ │
│  │ else:                                                                    │ │
│  │     ρ = exp(-distance_moved / d_corr)  # AR1 correlation                 │ │
│  │     shadowing = ρ * prev_shadowing + √(1-ρ²) * N(0, σ_SF)               │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────┘
```


### Υποσύστημα Μηχανής Handover

**Τοποθεσία:** `nef-emulator/backend/app/app/handover/engine.py`


```
┌───────────────────────────────────────────────────────────────────────────────┐
│                          Handover Decision Flow                                │
│                                                                                │
│   evaluate_handover(ue_id) ─────────────────────────────────────────────────► │
│          │                                                                     │
│          ▼                                                                     │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                     Check Ping-Pong Prevention                        │   │
│   │  ┌─────────────────────────────────────────────────────────────────┐ │   │
│   │  │ Layer 1: if time_since_last_ho < MIN_DWELL_TIME_S (3.0s):       │ │   │
│   │  │              return STAY (too soon for another handover)        │ │   │
│   │  └─────────────────────────────────────────────────────────────────┘ │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│          │                                                                     │
│          ▼                                                                     │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │              Mode Selection: ML / A3 / Hybrid                         │   │
│   │                                                                       │   │
│   │   ML Mode:        A3 Mode:           Hybrid Mode:                     │   │
│   │   ┌─────┐         ┌─────┐            ┌──────────────────────┐         │   │
│   │   │ ML  │         │ A3  │            │ Try ML → Fallback A3 │         │   │
│   │   │ API │         │Rule │            │ if ML unavailable    │         │   │
│   │   └──┬──┘         └──┬──┘            └──────────┬───────────┘         │   │
│   │      │               │                          │                     │   │
│   └──────┴───────────────┴──────────────────────────┴─────────────────────┘   │
│          │                                                                     │
│          ▼                                                                     │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                   Per-UE TTT Timer Management                         │   │
│   │  _ttt_timers: Dict[ue_id, Dict[target_cell, start_time]]             │   │
│   │                                                                       │   │
│   │  if A3_satisfied and target not in timers:                           │   │
│   │      start_timer(ue_id, target_cell)                                 │   │
│   │  if timer_expired(TTT_S):                                            │   │
│   │      execute_handover()                                              │   │
│   │  if A3_not_satisfied:                                                │   │
│   │      clear_timer(ue_id, target_cell)                                 │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│          │                                                                     │
│          ▼                                                                     │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │               QoS-Aware Threshold Adjustment (Layer 3)                │   │
│   │  if current_cell_qos_good:                                           │   │
│   │      effective_threshold = ML_CONFIDENCE_THRESHOLD * 1.2             │   │
│   │      # Harder to trigger handover from good cell                     │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│          │                                                                     │
│          ▼                                                                     │
│   HANDOVER / STAY Decision ◄─────────────────────────────────────────────────│
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```


### Υποσύστημα Μετρικών & Ανίχνευσης RLF

**Τοποθεσία:** `nef-emulator/backend/app/app/metrics/rlf_detector.py`

Υλοποιεί τις Διορθώσεις #4, #5, #6, #26, #27 της διπλωματικής:


```
┌───────────────────────────────────────────────────────────────────────────────┐
│                           RLF Detection Pipeline                               │
│                                                                                │
│   SINR Input ────────────────────────────────────────────────────────────────►│
│        │                                                                       │
│        ▼                                                                       │
│   ┌─────────────────────────────────────────────────────────────────────────┐ │
│   │ Fix #26: Handover Interruption Exception                                │ │
│   │ if ue.in_handover_interruption:                                         │ │
│   │     clear_rlf_timer(ue_id)  # Don't count normal HO as RLF              │ │
│   │     return False                                                         │ │
│   └─────────────────────────────────────────────────────────────────────────┘ │
│        │                                                                       │
│        ▼                                                                       │
│   ┌─────────────────────────────────────────────────────────────────────────┐ │
│   │ Fix #4: Timer Precision (>= comparison)                                 │ │
│   │ if SINR < -6.0 dB:                                                      │ │
│   │     if timer not started:                                               │ │
│   │         start_timer(current_time)                                       │ │
│   │     elif (current_time - timer_start) >= 1.0s:  # Fix: >= not >         │ │
│   │         declare_rlf()                                                   │ │
│   │ else:                                                                   │ │
│   │     clear_timer()  # Signal recovered                                   │ │
│   └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────────┐
│                     Throughput Calculation (Fix #5)                            │
│                                                                                │
│   SINR ──────────────────────────────────────────────────────────────────────►│
│     │                                                                          │
│     ├─── SINR < -10 dB ────► Throughput = 0 (No connection)                   │
│     │                                                                          │
│     ├─── -10 ≤ SINR < -6 ──► Throughput = BW × 0.5 bits/Hz (RLF zone)        │
│     │                        (Graceful degradation, not cliff)                │
│     │                                                                          │
│     └─── SINR ≥ -6 dB ─────► Shannon capacity: BW × log2(1 + SINR_linear)    │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────────┐
│               Handover Interruption Tracking (Fixes #6, #27)                   │
│                                                                                │
│   ┌─────────────────────────────────────────────────────────────────────────┐ │
│   │ Fix #27: Queue-based tracking (not single timestamp)                    │ │
│   │                                                                          │ │
│   │ interruptions: Deque[HandoverInterruption]                              │ │
│   │                                                                          │ │
│   │ When handover executes:                                                 │ │
│   │     interruptions.append(HandoverInterruption(                          │ │
│   │         start_time=current_time,                                        │ │
│   │         end_time=current_time + 50ms                                    │ │
│   │     ))                                                                  │ │
│   │                                                                          │ │
│   │ Fix #6: Check if ANY interruption covers current time                   │ │
│   │ is_interrupted = any(                                                   │ │
│   │     intr.start <= current_time < intr.end                              │ │
│   │     for intr in interruptions                                          │ │
│   │ )                                                                       │ │
│   └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```


### Γραμμή Πρόβλεψης ML


```
┌───────────────────────────────────────────────────────────────────────────────┐
│                         ML Service Prediction Pipeline                         │
│                                                                                │
│   HTTP POST /predict ────────────────────────────────────────────────────────►│
│        │                                                                       │
│        ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                     Feature Extraction                                │   │
│   │  Raw UE State ──► Feature Transformer ──► 12-Feature Vector          │   │
│   │                                                                       │   │
│   │  Signal:    [rsrp_s, rsrp_n, Δrsrp, sinr_s, sinr_n, Δsinr]          │   │
│   │  Distance:  [dist_s, dist_n, Δdist]                                  │   │
│   │  Mobility:  [velocity, heading, time_since_ho, ho_count_1min]        │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│        │                                                                       │
│        ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                     Feature Scaling                                   │   │
│   │  StandardScaler (fitted during training)                             │   │
│   │  X_scaled = (X - μ) / σ                                              │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│        │                                                                       │
│        ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                     LightGBM Prediction                               │   │
│   │  probability = model.predict_proba(X_scaled)[0, 1]                   │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│        │                                                                       │
│        ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                 Confidence Calibration (Optional)                     │   │
│   │  if calibrated_model:                                                │   │
│   │      calibrated_prob = calibrated_model.predict_proba(X_scaled)[0,1] │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│        │                                                                       │
│        ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │              SHAP Explanation (if mode != OFF)                        │   │
│   │  Fix #14: Robust extraction handles format variants                  │   │
│   │  Fix #15: Mode-based computation (OFF/SAMPLED/ALWAYS)                │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│        │                                                                       │
│        ▼                                                                       │
│   Response: {probability, recommendation, confidence, shap_values?} ◄────────│
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```


---

## Επίπεδο Δεδομένων

### Επισκόπηση Σχήματος Βάσεων Δεδομένων


```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PostgreSQL                                      │
│                                                                              │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────────┐ │
│  │      ue_table      │  │    cell_table      │  │   handover_log         │ │
│  ├────────────────────┤  ├────────────────────┤  ├────────────────────────┤ │
│  │ ue_id (PK)         │  │ cell_id (PK)       │  │ id (PK)                │ │
│  │ position_x         │  │ position_x         │  │ ue_id (FK)             │ │
│  │ position_y         │  │ position_y         │  │ source_cell (FK)       │ │
│  │ position_z         │  │ tx_power_dbm       │  │ target_cell (FK)       │ │
│  │ velocity           │  │ frequency_ghz      │  │ timestamp              │ │
│  │ heading            │  │ cell_radius_m      │  │ trigger_reason         │ │
│  │ serving_cell (FK)  │  │ antenna_height_m   │  │ rsrp_before            │ │
│  │ created_at         │  │ created_at         │  │ rsrp_after             │ │
│  │ updated_at         │  └────────────────────┘  │ ml_confidence          │ │
│  └────────────────────┘                          │ was_ping_pong          │ │
│                                                  └────────────────────────┘ │
│  ┌────────────────────┐  ┌────────────────────┐                             │
│  │  experiment_table  │  │   scenario_table   │                             │
│  ├────────────────────┤  ├────────────────────┤                             │
│  │ id (PK)            │  │ id (PK)            │                             │
│  │ name               │  │ name               │                             │
│  │ scenario_id (FK)   │  │ description        │                             │
│  │ algorithm          │  │ duration_s         │                             │
│  │ seed               │  │ ue_count           │                             │
│  │ started_at         │  │ cell_count         │                             │
│  │ completed_at       │  │ config_json        │                             │
│  │ results_json       │  └────────────────────┘                             │
│  └────────────────────┘                                                      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                               MongoDB                                        │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ Collection: metrics_timeseries                                         │ │
│  │ {                                                                      │ │
│  │   "timestamp": ISODate,                                                │ │
│  │   "ue_id": string,                                                     │ │
│  │   "cell_id": string,                                                   │ │
│  │   "rsrp": float,                                                       │ │
│  │   "rsrq": float,                                                       │ │
│  │   "sinr": float,                                                       │ │
│  │   "throughput_mbps": float                                             │ │
│  │ }                                                                      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ Collection: ml_predictions                                             │ │
│  │ {                                                                      │ │
│  │   "timestamp": ISODate,                                                │ │
│  │   "ue_id": string,                                                     │ │
│  │   "features": {...},                                                   │ │
│  │   "probability": float,                                                │ │
│  │   "decision": string,                                                  │ │
│  │   "shap_values": {...}  // Optional                                    │ │
│  │ }                                                                      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```


### Feast Feature Store

**Τοποθεσία:** `mlops/feast_repo/`

```
feast_repo/
├── feature_store.yaml          # Ρύθμιση Feast
├── feature_repo.py             # Ορισμοί χαρακτηριστικών
├── constants.py                # Σταθερές χαρακτηριστικών
└── data/
    └── *.parquet               # Offline δεδομένα χαρακτηριστικών
```

---

## Scripts & Πλαίσιο Ανάλυσης

**Τοποθεσία:** `scripts/`


```
scripts/
├── core/
│   └── reproducibility.py      # Fix #1: Seed propagation
├── validation/
│   ├── distance_units.py       # Fix #2: Unit validation
│   └── a3_baseline_criteria.py # Fix #7: A3 acceptance criteria
├── analysis/
│   ├── statistical_analysis.py # Fixes #16,17,18,19
│   └── sample_collector.py     # Fix #8: Sample collection
├── experiments/
│   └── experimental_config.py  # Fixes #11,12,13
├── visualization/
│   ├── publication_plots.py    # Fix #20: Publication standards
│   └── shap_validation.py      # Fixes #14,28,29
├── benchmarking/
│   └── performance_benchmark.py# Fix #22: Performance protocol
├── scenarios/
│   ├── highway_handover.py
│   └── smart_city_downtown.py
├── data_generation/
│   └── synthetic_generator.py
└── run_enhanced_experiment.py  # Main experiment runner
```


### Στατιστική Ανάλυση (Διορθώσεις #16-19)

```python
# Διόρθωση #16: Ζευγαρωτό t-test (όχι ανεξάρτητο)
from scipy.stats import ttest_rel, wilcoxon

# Διόρθωση #17: Cohen's d_z για ζευγαρωτά δεδομένα
def calculate_cohens_d_z(differences):
    return np.mean(differences) / np.std(differences, ddof=1)

# Διόρθωση #18: Διόρθωση Bonferroni
def apply_bonferroni(p_value, n_comparisons):
    return min(p_value * n_comparisons, 1.0)

# Διόρθωση #19: Bootstrap CI (διατηρεί τη ζεύξη)
def bootstrap_ci(a3_values, ml_values, n_iterations=10000):
    # Επαναδειγματοληψία ΖΕΥΓΑΡΙΩΝ, όχι ανεξάρτητα
    ...
```

### Πειραματική Διαμόρφωση (Διορθώσεις #11-13)

```python
# Διόρθωση #11: Πειραματικό πλαίσιο βασισμένο σε επίπεδα
# Tier 1: 40 εκτελέσεις (2 σενάρια × 2 αλγόριθμοι × 10 seeds)
# Tier 2: Εκτεταμένη ανάλυση ευαισθησίας
# Tier 3: Πλήρεις 270 συνδυασμοί (μελλοντική εργασία)

# Διόρθωση #12: Στρατηγική επιλογής seed
class SeedStrategy(Enum):
    SEQUENTIAL = "sequential"  # 1, 2, 3, ...
    PRIMES = "primes"          # 2, 3, 5, 7, 11, ...
    HASH_BASED = "hash"        # Ντετερμινιστικό από metadata

# Διόρθωση #13: Ρεαλιστική εκτίμηση χρόνου εκτέλεσης
# Ανά εκτέλεση: 8-10 λεπτά κατά μέσο όρο
# Tier 1 (40 εκτελέσεις): 6-8 ώρες
```

---

## Γραμμή MLOps

**Τοποθεσία:** `mlops/`

```
mlops/
├── data_pipeline/
│   └── nef_collector.py        # Συλλογή δεδομένων εκπαίδευσης από NEF
├── feast_repo/
│   ├── feature_store.yaml      # Ρύθμιση Feast
│   └── feature_repo.py         # Ορισμοί χαρακτηριστικών
└── feature_store/
    └── feature_repo/           # Αποθετήριο χαρακτηριστικών
```

### Γραμμή Δεδομένων Εκπαίδευσης


```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Training Data Pipeline                               │
│                                                                              │
│  NEF Simulator ──► Data Collector ──► Feature Engineering ──► Feast Store  │
│       │                 │                    │                    │         │
│       ▼                 ▼                    ▼                    ▼         │
│  ┌─────────┐      ┌──────────┐        ┌───────────┐       ┌───────────┐    │
│  │Raw UE   │      │ MongoDB  │        │ Transform │       │ Parquet   │    │
│  │States   │      │ Storage  │        │ Pipeline  │       │ Files     │    │
│  └─────────┘      └──────────┘        └───────────┘       └───────────┘    │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Feature Engineering:                                                  │  │
│  │  • Compute RSRP/SINR differences                                     │  │
│  │  • Calculate distances to cells                                      │  │
│  │  • Derive velocity from position history                             │  │
│  │  • Count recent handovers (ping-pong indicator)                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```


---

## Υποδομή Δοκιμών

**Τοποθεσία:** `tests/`


tests/
├── conftest.py                 # Pytest configuration (portable paths)
├── core/
│   └── test_reproducibility.py # Fix #1 tests
├── validation/
│   └── test_distance_units.py  # Fix #2 tests
├── metrics/
│   └── test_rlf_detector.py    # Fixes #4,5,6,26,27 tests
├── rf_model_tests/
│   └── test_channel_model.py   # Fixes #3,24,25 tests
├── analysis/
│   ├── test_sample_collector.py     # Fix #8 tests
│   └── test_statistical_analysis.py # Fixes #16-19 tests
├── integration/
│   ├── test_handover_coverage_loss.py
│   ├── test_multi_antenna_scenarios.py
│   └── test_thesis_claims.py   # Validate thesis claims
└── ml_system/
    └── test_shap_validation.py # Fixes #14,28,29 tests
```


### Κατηγορίες Δοκιμών

| Κατηγορία | Σκοπός | Βασικές Δοκιμές |
|-----------|--------|-----------------|
| **Μοναδιαίες Δοκιμές (Unit)** | Απομόνωση συνιστωσών | Μοντέλο καναλιού, ανιχνευτής RLF |
| **Δοκιμές Ολοκλήρωσης (Integration)** | Αλληλεπίδραση υπηρεσιών | Ροή handover, συμβόλαια API |
| **Δοκιμές Επικύρωσης (Validation)** | Επαλήθευση διορθώσεων διπλωματικής | Κάλυψη και των 29 διορθώσεων |
| **Δοκιμές Συστήματος ML** | Συμπεριφορά μοντέλου | SHAP, προβλέψεις, βαθμονόμηση |
| **Δοκιμές Ισχυρισμών Διπλωματικής** | Επικύρωση αποτελεσμάτων | Εξάλειψη ping-pong, βελτιώσεις |

---

## Αρχιτεκτονική Ανάπτυξης

### Docker Compose (Ανάπτυξη/Δοκιμές)


```yaml
# docker-compose.yml structure
services:
  nef-emulator:
    build: ./services/nef-emulator
    ports: ["8080:8080"]
    depends_on: [postgres, mongodb]
    
  ml-service:
    build: ./services/ml-service
    ports: ["5050:5050"]
    environment:
      - ML_CONFIDENCE_THRESHOLD=0.5
      - SHAP_MODE=off
    
  kinisis-ui:
    build: ./services/kinisis_ui
    ports: ["3001:3001"]
    depends_on: [nef-emulator]
    
  postgres:
    image: postgres:14-alpine
    ports: ["5432:5432"]
    
  mongodb:
    image: mongo:6
    ports: ["27017:27017"]
    
  prometheus:
    image: prom/prometheus
    ports: ["9090:9090"]
    
  grafana:
    image: grafana/grafana
    ports: ["3000:3000"]
```


### Kubernetes (Παραγωγή)

**Τοποθεσία:** `deployment/kubernetes/`

```
kubernetes/
├── deployments/
│   ├── nef-emulator.yaml
│   ├── ml-service.yaml
│   └── kinisis-ui.yaml
├── services/
│   ├── nef-emulator-svc.yaml
│   ├── ml-service-svc.yaml
│   └── kinisis-ui-svc.yaml
├── configmaps/
│   └── app-config.yaml
└── ingress/
    └── ingress.yaml
```

---

## Ροές Δεδομένων

### Ροή Μετρικών Πραγματικού Χρόνου


```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Real-Time Metrics WebSocket Flow                      │
│                                                                              │
│  Kinisis UI ◄───── WebSocket ─────► NEF Emulator ◄───► Simulation Loop     │
│      │                │                   │                  │              │
│      │                │                   │                  │              │
│      ▼                ▼                   ▼                  ▼              │
│  ┌─────────┐    ┌──────────┐       ┌───────────┐      ┌───────────┐        │
│  │ Render  │    │  Parse   │       │  Collect  │      │  Channel  │        │
│  │ Charts  │    │  JSON    │       │  Metrics  │      │  Update   │        │
│  │ & Map   │    │ Messages │       │  100ms    │      │  100ms    │        │
│  └─────────┘    └──────────┘       └───────────┘      └───────────┘        │
│                                                                              │
│  Message Format:                                                             │
│  {                                                                          │
│    "type": "metrics",                                                       │
│    "timestamp": "2026-01-21T12:00:00Z",                                     │
│    "ues": [                                                                 │
│      {"ue_id": "ue001", "rsrp": -85.2, "sinr": 12.5, "cell": "cell_1"},   │
│      ...                                                                    │
│    ],                                                                       │
│    "handovers_total": 15,                                                   │
│    "pingpong_count": 0                                                      │
│  }                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```


### Ροή Αποφάσεων Handover


```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Handover Decision Sequence                           │
│                                                                              │
│  ┌───────────┐  1. evaluate   ┌───────────────┐  2. features  ┌──────────┐ │
│  │Simulation │ ─────────────► │ Handover      │ ────────────► │   ML     │ │
│  │   Loop    │                │   Engine      │               │ Service  │ │
│  └───────────┘                └───────────────┘               └──────────┘ │
│                                      │                              │       │
│                                      │ 3. A3 check                  │       │
│                                      ▼                              │       │
│                               ┌───────────────┐                     │       │
│                               │  A3EventRule  │                     │       │
│                               │  (baseline)   │                     │       │
│                               └───────────────┘                     │       │
│                                      │                              │       │
│                                      ▼                              │       │
│                               ┌───────────────┐  4. probability    │       │
│                               │   Decision    │ ◄─────────────────┘       │
│                               │    Merger     │                           │
│                               └───────────────┘                           │
│                                      │                                    │
│                                      │ 5. execute if approved             │
│                                      ▼                                    │
│                               ┌───────────────┐                           │
│                               │   Execute     │                           │
│                               │   Handover    │                           │
│                               └───────────────┘                           │
│                                      │                                    │
│                                      │ 6. record metrics                  │
│                                      ▼                                    │
│                               ┌───────────────┐                           │
│                               │   Metrics     │                           │
│                               │   Database    │                           │
│                               └───────────────┘                           │
└─────────────────────────────────────────────────────────────────────────────┘
```


---

## Αναφορά Ρυθμίσεων

### Μεταβλητές Περιβάλλοντος

| Μεταβλητή | Προεπιλογή | Περιγραφή |
|-----------|------------|-----------|
| **NEF Emulator** | | |
| `A3_HYSTERESIS_DB` | 2.0 | Περιθώριο υστέρησης A3 σε dB |
| `A3_TTT_S` | 0.0 | Χρόνος μέχρι ενεργοποίηση (0 = ανά UE) |
| `MIN_DWELL_TIME_S` | 3.0 | Ελάχιστος χρόνος παραμονής σε κελί |
| `ML_HANDOVER_ENABLED` | true | Ενεργοποίηση λειτουργίας ML |
| `ML_SERVICE_URL` | http://ml-service:5050 | Τελικό σημείο ML service |
| `ML_CONFIDENCE_THRESHOLD` | 0.5 | Κατώφλι απόφασης |
| **ML Service** | | |
| `N_ESTIMATORS` | 100 | Αριθμός δέντρων LightGBM |
| `CALIBRATE_CONFIDENCE` | true | Ενεργοποίηση βαθμονόμησης |
| `SHAP_ENABLED` | false | Ενεργοποίηση SHAP |
| `SHAP_MODE` | off | off/sampled/always |
| `SHAP_SAMPLE_RATE` | 0.1 | Ρυθμός δειγματοληψίας |
| **Αναπαραγωγιμότητα** | | |
| `EXPERIMENT_SEED` | 42 | Τυχαίος σπόρος |

### Αρχεία Ρυθμίσεων

| Αρχείο | Σκοπός |
|--------|--------|
| `docker-compose.yml` | Ενορχήστρωση υπηρεσιών |
| `requirements.lock` | Κλειδωμένες εξαρτήσεις Python (Διόρθωση #21) |
| `feature_store.yaml` | Ρύθμιση Feast |
| `prometheus.yml` | Συλλογή μετρικών |
| `grafana/dashboards/*.json` | Προ-κατασκευασμένα dashboards |

---

## Αναφορά API

### API του NEF Emulator

| Τελικό Σημείο | Μέθοδος | Περιγραφή |
|---------------|---------|-----------|
| `/api/v1/ue/` | GET | Λίστα όλων των UEs |
| `/api/v1/ue/{ue_id}` | GET | Λεπτομέρειες UE |
| `/api/v1/ue/{ue_id}/state` | GET | Κατάσταση σήματος UE |
| `/api/v1/cells/` | GET | Λίστα όλων των κελιών |
| `/api/v1/cells/{cell_id}` | GET | Λεπτομέρειες κελιού |
| `/api/v1/handover/trigger` | POST | Ενεργοποίηση handover |
| `/api/v1/handover/evaluate` | POST | Αξιολόγηση απόφασης |
| `/api/v1/scenarios/` | GET | Λίστα σεναρίων |
| `/api/v1/scenarios/{id}/start` | POST | Έναρξη σεναρίου |
| `/api/v1/experiments/start` | POST | Έναρξη πειράματος |
| `/api/v1/experiments/stop` | POST | Τερματισμός πειράματος |
| `/ws/metrics` | WS | Μετρικές πραγματικού χρόνου |

### API του ML Service

| Τελικό Σημείο | Μέθοδος | Περιγραφή |
|---------------|---------|-----------|
| `/predict` | POST | Λήψη πρόβλεψης handover |
| `/predict/batch` | POST | Μαζικές προβλέψεις |
| `/health` | GET | Έλεγχος υγείας |
| `/metrics` | GET | Μετρικές μοντέλου |
| `/model/info` | GET | Πληροφορίες μοντέλου |
| `/feedback` | POST | Υποβολή ανατροφοδότησης |

---

*Αυτό το έγγραφο παρέχει την πλήρη τεχνική αρχιτεκτονική της υλοποίησης της διπλωματικής για Βελτιστοποίηση Δικτύων 5G. Για διευκρίνιση ορολογίας O-RAN, ανατρέξτε στο [ORAN_TERMINOLOGY.md](../5g-network-optimization/services/nef-emulator/docs/ORAN_TERMINOLOGY.md). Για λειτουργίες και ανάπτυξη, ανατρέξτε στο [MANUAL.md](./MANUAL.md). Για μεθοδολογία διπλωματικής και αναπαραγωγιμότητα, ανατρέξτε στο [THESIS.md](./THESIS.md).*
