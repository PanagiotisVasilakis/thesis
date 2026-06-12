# Υπηρεσία ML

Μικρουπηρεσία βασισμένη σε Flask που προβλέπει στόχους handover για εξοπλισμό χρήστη (UE) και παρέχει εργαλεία εκπαίδευσης/παρακολούθησης για τον εξομοιωτή NEF. Κάθε συμπεριφορά που περιγράφεται παρακάτω προκύπτει από την τρέχουσα βάση κώδικα (`ml_service/app`).

## Βασικά Χαρακτηριστικά

- Factory εφαρμογής Flask (`ml_service.app.create_app`) με αρχικοποίηση μοντέλου στο παρασκήνιο, δομημένη καταγραφή, JWT αυθεντικοποίηση και μετρικές Prometheus.
- Πλούσιος διαχειριστής μοντέλων που υποστηρίζει LightGBM, LSTM, Ensemble και Online μοντέλα επιλέξιμα μέσω `MODEL_TYPE`.
- **Πρόληψη ping-pong** στις ML προβλέψεις για αποτροπή ταχείας ταλάντωσης handover (κρίσιμο για την επίδειξη της διπλωματικής).
- REST API προστατευμένο με JWT, με rate limiting, QoS-aware `/api/predict-with-qos`, ασύγχρονους βοηθούς πρόβλεψης/εκπαίδευσης, ενσωμάτωση NEF και εισαγωγή ανατροφοδότησης για χειρισμό drift.
- Αποκλειστικό endpoint `/metrics` προστατευμένο από αντικαταστάσιμα διαπιστευτήρια (basic, API key ή JWT) μαζί με βοηθητικά endpoints για έκδοση tokens μετρικών.
- Blueprint οπτικοποίησης για χάρτες κάλυψης και τροχιές αποθηκευμένες στο `output/`.
- Εκτεταμένη επιφάνεια ρύθμισης μέσω μεταβλητών περιβάλλοντος, όλες συναθροισμένες στο `ml_service.app.config.constants`.

## Κύκλος Ζωής Εφαρμογής

Η `create_app()` εκτελεί τα εξής βήματα:

1. Φορτώνει προεπιλογές (`NEF_API_URL`, `MODEL_PATH`, μυστικά auth, λήξη JWT, κ.λπ.) και εφαρμόζει τυχόν παρακάμψεις που διαβιβάζονται μέσω της προαιρετικής αντιστοίχισης `config`.
2. Διασφαλίζει την ύπαρξη του φακέλου μοντέλου και εκκινεί `ModelManager.initialize(..., background=True)` εκτός αν το `app.testing` είναι ενεργό. Αυτό παράγει ένα παρακολουθούμενο thread που είτε φορτώνει υπάρχον μοντέλο είτε εκπαιδεύει ένα χρησιμοποιώντας συνθετικά δεδομένα. Το placeholder στιγμιότυπο που επιστρέφεται αμέσως αντικαθίσταται μόλις ολοκληρωθεί η εκπαίδευση.
3. Καταχωρεί δύο blueprints: `/api` (βασικά REST endpoints) και `/api/visualization` (βοηθοί δημιουργίας εικόνων). Επίσης συνδέει rate limiting (`Flask-Limiter` προεπιλογή: 100 αιτήματα/λεπτό) και καθολικούς χειριστές σφαλμάτων.
4. Προσαρτά middleware Prometheus (`MetricsMiddleware`) και εκκινεί ένα background thread `MetricsCollector` για δημοσίευση μετρικών καθυστέρησης, drift και πόρων.
5. Εκθέτει αυθεντικοποιημένα endpoints `/metrics`, `/metrics/auth/token` και `/metrics/auth/stats`. Η αυθεντικοποίηση μετρικών παρακάμπτεται στις δοκιμές αλλά επιβάλλεται σε κάθε άλλη λειτουργία.
6. Προσθέτει καταγραφή αιτημάτων/αποκρίσεων με correlation IDs, καθιστώντας κάθε γραμμή αρχείου καταγραφής ανιχνεύσιμη.

Το `app.py` ρυθμίζει την καταγραφή μέσω `services/logging_config.py` και εκτελεί τον διακομιστή Flask στη θύρα `5050`, εναλλακτικά τυλίγοντάς τον σε TLS όταν υπάρχουν `SSL_CERTFILE` και `SSL_KEYFILE`.

## Οδηγός Φακέλων

- `app/api/routes.py` – σύγχρονα και ασύγχρονα REST endpoints (πρόβλεψη, εκπαίδευση, συνδεσιμότητα NEF, ανατροφοδότηση, συλλογή δεδομένων, διαχείριση μοντέλων).
- `app/api/visualization.py` – γεννήτριες PNG χαρτών κάλυψης και τροχιών υποστηριζόμενες από βοηθούς Matplotlib.
- `app/initialization/model_init.py` – `ModelManager`, εκκίνηση συνθετικής εκπαίδευσης, ανακάλυψη έκδοσης μοντέλου (`MODEL_VERSION = 1.0.0`).
- `app/monitoring/metrics.py` – προσαρμοσμένο μητρώο Prometheus, middleware, παρακολουθητής drift και background collector.
- `app/auth` – έκδοση/επαλήθευση JWT (`create_access_token`, `verify_token`) και στρατηγικές αυθεντικοποίησης μετρικών.
- `collect_training_data.py` – βοηθητικό CLI για συλλογή δειγμάτων NEF ή ανάθεση στο `/api/collect-data`.

## Τοπική Εκτέλεση

```bash
python -m venv .venv
. .venv/Scripts/activate  # ή source .venv/bin/activate σε Linux/macOS
pip install -r requirements.txt
export NEF_API_URL=http://localhost:8080
export SECRET_KEY='<set-long-random-flask-secret>'
export JWT_SECRET='<set-long-random-jwt-secret>'
export JWT_REFRESH_SECRET='<set-long-random-refresh-secret>'
export AUTH_USERNAME=ml-admin AUTH_PASSWORD='<set-strong-local-password>'
python app.py
```

Η υπηρεσία ακούει στο `http://localhost:5050` από προεπιλογή. Ορίστε `SSL_CERTFILE`/`SSL_KEYFILE` για εξυπηρέτηση HTTPS.

### Docker

```bash
docker build -t ml-service .
docker run -p 5050:5050 \
     -e AUTH_USERNAME=ml-admin -e AUTH_PASSWORD='<set-strong-local-password>' \
     -e SECRET_KEY='<set-long-random-flask-secret>' \
     -e JWT_SECRET='<set-long-random-jwt-secret>' \
     -e JWT_REFRESH_SECRET='<set-long-random-refresh-secret>' \
     -e NEF_API_URL=http://localhost:8080 \
     ml-service
```

Το `docker-compose.yml` ανωτάτου επιπέδου σε αυτό το αποθετήριο εκκινεί τον εξομοιωτή NEF, την υπηρεσία ML και τη στοίβα παρακολούθησης από άκρο σε άκρο όταν είναι ενεργό το compose profile `ml`.

## Επισκόπηση API

Όλα τα endpoints βρίσκονται κάτω από το `/api` και επιστρέφουν JSON. Rate limiting και αυθεντικοποίηση JWT εφαρμόζονται σε κάθε διαδρομή εκτός αν αναφέρεται αλλιώς.

| Endpoint | Μέθοδος | Auth; | Σκοπός |
|----------|---------|-------|--------|
| `/api/health` | GET | Όχι | Έλεγχος ζωντανότητας. |
| `/api/model-health` | GET | Όχι | Αναφέρει την ετοιμότητα μέσω `ModelManager.wait_until_ready(timeout=0)` και τα τελευταία μεταδεδομένα (έκδοση, χρονικές σφραγίδες, μετρικές). |
| `/api/login` | POST | Όχι | Εκδίδει JWT με τα δεδομένα `AUTH_USERNAME`/`AUTH_PASSWORD`. Σώμα επικυρωμένο μέσω Pydantic model `LoginRequest`. |
| `/api/predict` | POST | Ναι | Σύγχρονη πρόβλεψη. Χρησιμοποιεί `PredictionRequest`, καλεί βοηθό `predict()`, καταγράφει μετρικές & δεδομένα drift. |
| `/api/predict-with-qos` | POST | Ναι | Πρόβλεψη QoS-aware που επιστρέφει ετυμηγορία `qos_compliance` παράλληλα με την πρόταση κεραίας. |
| `/api/predict-async` | POST | Ναι | Εκτελεί `model.predict_async` αν ο υποκείμενος επιλογέας το υποστηρίζει. |
| `/api/train` | POST | Ναι | Εκπαίδευση batch. Αποδέχεται λίστα `TrainingSample` payloads (όριο 50 MB) και αποθηκεύει μέσω `ModelManager.save_active_model`. |
| `/api/train-async` | POST | Ναι | Αναμενόμενη παραλλαγή χρησιμοποιώντας `model.train_async`. |
| `/api/collect-data` | POST | Ναι | Ασύγχρονη λήψη δειγμάτων από τον εξομοιωτή NEF μέσω `NEFDataCollector.collect_training_data`. Προαιρετικά διαπιστευτήρια/διάρκεια/διάστημα. |
| `/api/nef-status` | GET | Ναι | Έλεγχος υγείας του διαμορφωμένου URL NEF μέσω `NEFClient.get_status()`, επιστρέφοντας επικεφαλίδες έκδοσης όταν είναι προσβάσιμο. |
| `/api/models` | GET | Ναι | Εμφανίζει ανακαλυφθείσες εκδόσεις `antenna_selector_v*.joblib`. |
| `/api/models/<version>` | POST/PUT | Ναι | Εναλλάσσει ενεργό μοντέλο· επικυρώνει μέσω `model_version_validator` και εγείρει δομημένα σφάλματα σε περίπτωση αρχείων που λείπουν/δικαιωμάτων. |
| `/api/feedback` | POST | Ναι | Αποδέχεται λίστα καταχωρήσεων `FeedbackSample`, τροφοδοτώντας τες στη `ModelManager.feed_feedback` για επανεκπαίδευση που ενεργοποιείται από drift. |

### Endpoints Οπτικοποίησης

- `GET /api/visualization/coverage-map` – δημιουργεί heatmap κάλυψης. Θα εκπαιδεύσει αυτόματα με συνθετικά δεδομένα αν το μοντέλο δεν είναι αρχικοποιημένο.
- `POST /api/visualization/trajectory` – καταναλώνει πίνακα στιγμιότυπων UE και εκπέμπει `trajectory.png` στον διαμορφωμένο φάκελο εξόδου.

Παράδειγμα χρήσης:

```bash
# Απόκτηση JWT token
TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# Εκτέλεση πρόβλεψης
curl -X POST http://localhost:5050/api/predict \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
                     "ue_id":"ue-42",
                     "latitude":38.0,
                     "longitude":23.7,
                     "connected_to":"antenna_1",
                     "rf_metrics": {
                          "antenna_1": {"rsrp": -78, "sinr": 15, "rsrq": -9}
                     }
                }'
```

## Μετρικές & Αυθεντικοποίηση

- Το `/metrics` επιστρέφει στατιστικά μορφής Prometheus που παράγονται από `generate_latest(metrics.REGISTRY)`.
- Τα αιτήματα πρέπει να παρέχουν διαπιστευτήρια Basic (`METRICS_AUTH_USERNAME`/`METRICS_AUTH_PASSWORD`), bearer API key (`METRICS_API_KEY`) ή έγκυρο JWT εκδοθέν με `/metrics/auth/token`.
- Το `/metrics/auth/token` εκδίδει JWT υπογεγραμμένο με `JWT_SECRET` και τιμά τη λήξη που ρυθμίζεται από `METRICS_JWT_EXPIRY_SECONDS`.
- Το `/metrics/auth/stats` εκθέτει μετρητές αποτυχημένων προσπαθειών και πληροφορίες kλειδώματος που διατηρεί ο `MetricsAuthenticator`.

## Μεταβλητές Περιβάλλοντος

### Βασικές Ρυθμίσεις

| Μεταβλητή | Προεπιλογή | Περιγραφή |
|-----------|-----------|-----------|
| `NEF_API_URL` | *(μη ορισμένη)* | Απαιτείται εκτός tests. Βασικό URL που χρησιμοποιείται από τον NEF client και τον data collector. |
| `SECRET_KEY` | *(μη ορισμένη)* | Απαιτείται εκτός tests. Flask secret key. |
| `AUTH_USERNAME` / `AUTH_PASSWORD` | *(μη ορισμένες)* | Απαιτούνται εκτός tests για `/api/login`. Αν λείπουν, η εκκίνηση αποτυγχάνει αντί να απενεργοποιήσει σιωπηλά την αυθεντικοποίηση. |
| `JWT_SECRET` / `JWT_REFRESH_SECRET` | *(μη ορισμένες)* | Απαιτούνται εκτός tests. HMAC κλειδιά για access και refresh JWTs. |
| `MODEL_PATH` | `ml_service/app/models/antenna_selector_v1.0.0.joblib` | Τοποθεσία αποθήκευσης για το ενεργό μοντέλο και μεταδεδομένα. Οι γονικοί φάκελοι δημιουργούνται αυτόματα. |
| `MODEL_TYPE` | `lightgbm` | Επιλέγει κλάση επιλογέα (`lightgbm`, `lstm`, `ensemble`, `online`). Τα μεταδεδομένα μπορούν να το παρακάμψουν. |
| `NEIGHBOR_COUNT` | `3` | Διαβιβάζεται στους κατασκευαστές επιλογέα για διαστασιολόγηση χαρακτηριστικών με επίγνωση γειτόνων. |
| `LIGHTGBM_TUNE` | `0` | Όταν `1`, εκτελεί τυχαιοποιημένη ρύθμιση LightGBM κατά την εκκίνηση. Τροποποιείται μέσω `LIGHTGBM_TUNE_N_ITER` και `LIGHTGBM_TUNE_CV`. |
| `PORT` / `HOST` | `5050` / `0.0.0.0` | Διεύθυνση δέσμευσης Gunicorn/Flask και θύρα κατά την εκκίνηση μέσω `app.py`. |
| `RATELIMIT_DEFAULT` | `100 per minute` | Προεπιλεγμένη ποσόστωση `Flask-Limiter`. |
| `RATELIMIT_PREDICT` | `60 per minute` | Ποσόστωση για `/api/predict` και `/api/predict-with-qos`. Στο root `docker-compose.yml` αυξάνεται με ασφαλές override για ελεγχόμενα live πειράματα. |
| `RATELIMIT_FEEDBACK` | `30 per minute` | Ποσόστωση για `/api/qos-feedback`. Στο root `docker-compose.yml` αυξάνεται με ασφαλές override για ελεγχόμενα live πειράματα, ώστε η εσωτερική κίνηση NEF-to-ML να μην δημιουργεί παραπλανητικά σφάλματα. |

### Επιλογές Αυθεντικοποίησης Μετρικών

| Μεταβλητή | Προεπιλογή | Σημειώσεις |
|-----------|-----------|------------|
| `METRICS_AUTH_ENABLED` | `true` | Σημαία που χρησιμοποιούν βοηθητικά scripts· η ίδια η υπηρεσία πάντα επιβάλλει αυθεντικοποίηση εκτός περιβάλλοντος δοκιμών. |
| `METRICS_AUTH_USERNAME` | `metrics` | Όνομα χρήστη basic auth. Αφήστε κενό για απενεργοποίηση basic auth. |
| `METRICS_AUTH_PASSWORD` | *(μη ορισμένο)* | Κωδικός basic auth. |
| `METRICS_API_KEY` | *(μη ορισμένο)* | Εναλλακτικό Bearer API key. |
| `METRICS_JWT_EXPIRY_SECONDS` | `3600` | TTL token για `/metrics/auth/token`. |

### Καταγραφή και HTTPS

- `LOG_LEVEL`, `LOG_FILE` επηρεάζουν το `configure_logging`.
- `SSL_CERTFILE`, `SSL_KEYFILE` ενεργοποιούν TLS όταν ορίζονται.

Ανατρέξτε στο `ml_service/app/config/constants.py` για την πλήρη λίστα, συμπεριλαμβανομένης της διαστασιολόγησης cache, παρακολούθησης drift, ορίων ασύγχρονων workers και εναλλαγών εξυγίανσης εισόδου.

## Συλλογή και Εκπαίδευση Δεδομένων

Το `collect_training_data.py` ενορχηστρώνει τη δειγματοληψία NEF και την προαιρετική εκπαίδευση.

```bash
python collect_training_data.py \
     --url http://localhost:8080 \
     --username admin --password admin \
     --duration 300 --interval 1 --train
```

- Χρησιμοποιεί `NEFDataCollector` για σύνδεση, επικύρωση κίνησης UE και συλλογή δειγμάτων JSON στο `ml_service/app/data/collected_data/`.
- Όταν παρέχεται `--ml-service-url`, το script αναθέτει στο `/api/collect-data` μιας εκτελούμενης υπηρεσίας ML, αυτόματα αυθεντικοποιούμενο μέσω `/api/login`.
- Αν υπάρχουν βοηθοί Feast (`feature_store_utils`), τα δείγματα εισάγονται πριν την εκπαίδευση.

## Δοκιμές & Ποιότητα

```bash
pytest tests
```

Τα scripts ανωτάτου επιπέδου `scripts/setup_tests.sh` και `scripts/run_tests.sh` εγκαθιστούν εξαρτήσεις, ρυθμίζουν `PYTHONPATH` και εκτελούν τη σουίτα με κάλυψη. Τα unit tests βασίζονται σε προσωρινές διαδρομές για παραγόμενα αντικείμενα, ώστε το αποθετήριο να παραμένει καθαρό μετά την εκτέλεση.

## Αντιμετώπιση Προβλημάτων

- **Το μοντέλο δεν ετοιμάζεται ποτέ**: ελέγξτε τα αρχεία καταγραφής για καταχωρήσεις παρακολούθησης thread (`model_background_init`). Μια αποτυχία επαναφέρεται στην τελευταία επιτυχή διαδρομή μοντέλου και εμφανίζεται στα μεταδεδομένα `/api/model-health`.
- **401 στο `/metrics`**: βεβαιωθείτε ότι έχει διαμορφωθεί τουλάχιστον ένα διαπιστευτήριο μετρικών. Χρησιμοποιήστε `/metrics/auth/token` για έκδοση JWT βραχείας διάρκειας.
- **Το `/api/collect-data` επιστρέφει μηδέν δείγματα**: επαληθεύστε ότι ο εξομοιωτής NEF έχει UEs σε κίνηση μέσω των endpoints `/api/v1/movement` πριν από την έναρξη συλλογής.
- **Υπέρβαση ορίου ρυθμού**: αυξήστε το `RATELIMIT_DEFAULT` ή το συγκεκριμένο όριο διαδρομής, όπως `RATELIMIT_FEEDBACK` για `/api/qos-feedback`. Η υπηρεσία πρέπει να επιστρέφει 429 και όχι να κρύβει το rate-limit ως 500.

Όλα τα παραπάνω αντικατοπτρίζουν τον τρέχοντα κώδικα· ενημερώστε αυτό το README κάθε φορά που αλλάζουν διαδρομές API, προεπιλογές ή background υπηρεσίες.
