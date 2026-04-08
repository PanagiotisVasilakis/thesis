# Στοίβα Παρακολούθησης

Αυτός ο φάκελος περιέχει τις ρυθμίσεις για το Prometheus και το Grafana που χρησιμοποιούνται κατά την ανάπτυξη. Όταν εκκινείται το `docker-compose` από τον ριζικό φάκελο του έργου, αυτές οι υπηρεσίες συλλέγουν μετρικές από τον εξομοιωτή NEF και την υπηρεσία ML.

Η υπηρεσία ML εκθέτει μετρικές στη διεύθυνση `http://localhost:5050/metrics` κατά την τοπική εκτέλεση.

## Prometheus

Το Prometheus συλλέγει το endpoint `/metrics` που εκθέτει κάθε υπηρεσία. Οι στόχοι συλλογής ορίζονται στο `prometheus/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "ml_service"
    metrics_path: /metrics
    static_configs:
      - targets: ["ml-service:5050"]
  - job_name: "nef_emulator"
    metrics_path: /metrics
    static_configs:
      - targets: ["nef-emulator:8080"]
```

Η ρύθμιση περιλαμβάνει επίσης ένα job για το ίδιο το Prometheus. Προσαρμόστε τους στόχους αν αλλάξουν τα ονόματα υπηρεσιών ή οι θύρες.

Ο εξομοιωτής NEF εκθέτει μετρητές όπως `nef_handover_decisions_total` και το
histogram `nef_request_duration_seconds` σε αυτό το endpoint. Η υπηρεσία ML
παρέχει επιπλέον gauges για drift και λειτουργικές μετρικές:

- `ml_data_drift_score` – μέση μεταβολή στις κατανομές χαρακτηριστικών.
- `ml_prediction_error_rate` – κλάσμα αιτημάτων πρόβλεψης που απέτυχαν.
- `ml_cpu_usage_percent` – χρήση CPU της υπηρεσίας.
- `ml_memory_usage_bytes` – κατανάλωση μνήμης (resident memory).

Εκκινήστε το Prometheus με Docker Compose ή εκτελέστε το container χειροκίνητα και προσαρτήστε αυτόν τον φάκελο στο `/etc/prometheus`.

## Grafana

Το Grafana διαβάζει δεδομένα από το Prometheus και παρέχει dashboards. Το δείγμα dashboard στο `grafana/dashboards/ml_service.json` οπτικοποιεί την καθυστέρηση αιτημάτων, τους αριθμούς προβλέψεων, τα στατιστικά εκπαίδευσης και τα νέα gauges drift/χρήσης από την υπηρεσία ML. Όταν το Grafana εκκινείται μέσω Docker Compose, φορτώνει αυτόματα τα dashboards από το `grafana/dashboards`.

Η παροχή dashboards ρυθμίζεται στο `grafana/provisioning/dashboards.yml`, το οποίο οδηγεί το Grafana να φορτώνει οποιαδήποτε JSON dashboards από αυτόν τον φάκελο κατά την εκκίνηση.

Συνδεθείτε με τα προεπιλεγμένα διαπιστευτήρια διαχειριστή (`admin` / `admin`) και προσθέστε την πηγή δεδομένων Prometheus στο `http://prometheus:9090` αν δεν είναι προρυθμισμένη. Στη συνέχεια μπορείτε να εισάγετε ή να προσαρμόσετε dashboards για την παρακολούθηση επιπλέον μετρικών.
