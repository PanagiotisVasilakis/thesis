# Αυτοματοποιημένος Αγωγός MLOps

Ο φάκελος αυτός περιέχει τα βοηθητικά εργαλεία που συλλέγουν δεδομένα QoS από τον εξομοιωτή NEF, ορίζουν το feature store Feast και ενορχηστρώνουν την εκπαίδευση μοντέλων για την υπηρεσία ML. Η ροή εργασίας υποστηρίζει τόσο πλήρως συνθετικά σύνολα δεδομένων όσο και ζωντανές καταγραφές που ρέουν από τη στοίβα NEF.

## Ροή Εκπαίδευσης

1. **Συλλογή απαιτήσεων QoS** – Το `mlops/data_pipeline/nef_collector.py` προσφέρει σύγχρονους βοηθούς (`NEFQoSCollector`) που κανονικοποιούν τα payloads QoS που επιστρέφονται από το NEF API. Το module επιβάλλει μετατροπή τύπων, υποχρεωτικά κατώφλια και περιγραφικά σφάλματα, ώστε κανένα ελαττωματικό payload να μην φθάσει ποτέ στο μοντέλο.
2. **Δημιουργία συνθετικών ιχνών** – Το `scripts/data_generation/synthetic_generator.py` (τεκμηριωμένο στο `docs/qos/synthetic_qos_dataset.md`) μπορεί να παράγει σύνολα δεδομένων αιτημάτων σε μορφή CSV/JSON που συμμορφώνονται με τα QoS envelopes που χρησιμοποιεί ο επιλογέας LightGBM.
3. **Φόρτωση στο Feast** – Το αποθετήριο Feast στο `mlops/feature_store/feature_repo/` ορίζει οντότητες, feature views και το σχήμα που χρησιμοποιείται από τα offline και online stores. Το `feature_repo/schema.py` διατηρεί την κανονική λίστα στηλών, συμπεριλαμβανομένων των μετρικών QoS που ελέγχονται από τα tests στο `tests/mlops/test_qos_feature_ranges.py`.
4. **Εκπαίδευση μέσω της υπηρεσίας ML** – Το `collect_training_data.py` (υπό `services/ml-service/`) μπορεί να επικοινωνήσει με τον εξομοιωτή NEF ή να επαναχρησιμοποιήσει συνθετικά δεδομένα και στη συνέχεια να ενεργοποιήσει τα endpoints `/api/train`/`/api/train-async` στην υπηρεσία ML. Οι εκτελέσεις εκπαίδευσης εκπέμπουν μετρικές Prometheus όπως `ml_model_training_duration_seconds`, που συλλέγονται από τη στοίβα παρακολούθησης.
5. **Regression tests** – Η εκτέλεση `pytest -k qos` ασκεί τον collector, την επικύρωση σχήματος και τη λογική βαθμολόγησης μοντέλου. Τα εξειδικευμένα QoS tests στο `services/ml-service/ml_service/tests/` διασφαλίζουν ότι το confidence gating και η εξαγωγή χαρακτηριστικών παραμένουν συγχρονισμένα με το `features.yaml`.

## Εξυπηρέτηση & Ανάπτυξη

- **Κατασκευή container** – Η εντολή `docker compose -f 5g-network-optimization/docker-compose.yml up --build` κατασκευάζει και εκτελεί τοπικά τον εξομοιωτή NEF, την υπηρεσία ML, το Prometheus και το Grafana. Τα ίδια images υποστηρίζουν τα Kubernetes manifests στο `5g-network-optimization/deployment/kubernetes/`.
- **Ρύθμιση παραμέτρων** – Οι ρυθμίσεις χρόνου εκτέλεσης για QoS (handovers, circuit breakers, rate limits) περιγράφονται στο `docs/architecture/qos.md`. Χρησιμοποιήστε μεταβλητές περιβάλλοντος όπως `ML_HANDOVER_ENABLED`, `ML_CONFIDENCE_THRESHOLD` και `ASYNC_MODEL_WORKERS` για τον συντονισμό της συμπεριφοράς ανά ανάπτυξη.
- **Παρατηρησιμότητα** – Και οι δύο υπηρεσίες εκθέτουν endpoints `/metrics`. Τα dashboards Grafana στο `5g-network-optimization/monitoring/grafana/` οπτικοποιούν την καθυστέρηση πρόβλεψης, τα στατιστικά εκπαίδευσης και τους μετρητές συμμόρφωσης/fallback QoS.

## Βασικές Πτυχές Δομής Αποθετηρίου

- `data_pipeline/nef_collector.py` – Επικυρώνει και δομεί τις απαιτήσεις QoS που λαμβάνονται από το NEF API.
- `feature_store/feature_repo/` – Ρύθμιση Feast (οντότητες, feature view, βοηθητικές συναρτήσεις σχήματος).
- `feast_repo/` – Παράδειγμα αποθετηρίου Feast για τοπική υλοποίηση και πειραματισμό.
- `tests/mlops/test_qos_feature_ranges.py` – Regression tests που διασφαλίζουν ότι το σχήμα Feast και οι επικυρωτές QoS αποδέχονται έγκυρα δεδομένα και απορρίπτουν παραβάσεις.

Αυτά τα στοιχεία μαζί παρέχουν μια επαναλήψιμη διαδρομή από την εισαγωγή δεδομένων QoS έως την εκπαίδευση μοντέλου και την ανάπτυξη υπό Docker Compose ή Kubernetes. Κάθε φορά που επεκτείνετε τον αγωγό, ενημερώστε τους σχετικούς βοηθούς σχήματος και τα tests, ώστε οι διαδρομές εκπαίδευσης και εξυπηρέτησης να παραμένουν ευθυγραμμισμένες.
