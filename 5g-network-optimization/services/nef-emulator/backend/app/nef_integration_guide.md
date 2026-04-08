# Ενσωμάτωση Μοντέλων Κινητικότητας 3GPP με τον Εξομοιωτή NEF

## Επισκόπηση

Αυτός ο οδηγός εξηγεί πώς να χρησιμοποιήσετε τα μοντέλα κινητικότητας που συμμορφώνονται με το 3GPP με τον υπάρχοντα εξομοιωτή NEF χωρίς τροποποίηση του κώδικά του.

### Διαθέσιμα Μοντέλα Κινητικότητας
- Γραμμικές και L-σχήματος διαδρομές
- Κίνηση τυχαίων waypoints και τυχαίας κατεύθυνσης
- Μοντέλα Manhattan Grid και Urban Grid
- Κινητικότητα ομάδας σημείου αναφοράς

## Βήμα 1: Δημιουργία Σημείων Διαδρομής

Χρησιμοποιήστε τα μοντέλα κινητικότητας για να δημιουργήσετε σημεία διαδρομής σε μορφή συμβατή με το NEF:

```python
from mobility_models.nef_adapter import generate_nef_path_points, save_path_to_json

# Δημιουργία γραμμικής διαδρομής
params = {
    'ue_id': 'test_ue_1',
    'start_position': (0, 0, 0),
    'end_position': (1000, 500, 0),
    'speed': 5.0,
    'duration': 250,
    'time_step': 1.0
}

points = generate_nef_path_points('linear', **params)
json_file = save_path_to_json(points, 'my_path.json')
```

## Βήμα 2: Εισαγωγή της Διαδρομής στον Εξομοιωτή NEF

Μπορείτε να χρησιμοποιήσετε το παραγόμενο αρχείο JSON με το API του εξομοιωτή NEF:

1. Συνδεθείτε στον εξομοιωτή NEF για να αποκτήσετε access token
2. Δημιουργήστε μια νέα διαδρομή χρησιμοποιώντας το NEF API:

```bash
# Παράδειγμα χρήσης curl για τη δημιουργία διαδρομής
curl -X POST "http://localhost:8080/api/v1/paths/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d @linear_path.json
```

3. Συσχετίστε τη διαδρομή με ένα UE στον εξομοιωτή NEF
4. Ξεκινήστε την κίνηση του UE χρησιμοποιώντας το υπάρχον API

## Ενσωμάτωση σε Script Python

```python
import requests
import json

# 1. Σύνδεση για λήψη token
login_url = "http://localhost:8080/api/v1/login/access-token"
login_data = {
    "username": "your_username",
    "password": "your_password"
}
response = requests.post(login_url, data=login_data)
token = response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 2. Δημιουργία διαδρομής
with open('linear_path.json', 'r') as f:
    path_data = json.load(f)
    
path_url = "http://localhost:8080/api/v1/paths/"
path_response = requests.post(path_url, json=path_data, headers=headers)
path_id = path_response.json()["id"]
# Παράδειγμα: καταγράψτε ή εκτυπώστε το id της δημιουργηθείσας διαδρομής κατά την εκτέλεση ως script
# logger.info(f"Created path with ID: {path_id}")

# 3. Ενημέρωση UE για χρήση της διαδρομής
ue_id = "your_ue_id"  # Λάβετε αυτό από τον εξομοιωτή NEF
ue_url = f"http://localhost:8080/api/v1/UE/{ue_id}"
ue_data = {"path_id": path_id}
ue_response = requests.put(ue_url, json=ue_data, headers=headers)

# 4. Εκκίνηση κίνησης UE
start_url = "http://localhost:8080/api/v1/ue-movement/start-loop"
start_data = {"supi": "your_ue_supi"}  # Λάβετε SUPI από το UE σας
start_response = requests.post(start_url, json=start_data, headers=headers)
# Παράδειγμα: καταγράψτε ή ειδοποιήστε ότι η κίνηση του UE ξεκίνησε
# logger.info("UE movement started")
```

### Handover βάσει Κανόνων A3
Ο εξομοιωτής υποστηρίζει έναν βασικό κανόνα 3GPP Event A3. Απενεργοποιήστε τη μηχανική μάθηση ορίζοντας
`ML_HANDOVER_ENABLED=0` και ρυθμίστε τα `A3_HYSTERESIS_DB` και `A3_TTT_S` για
τον έλεγχο της υστέρεσης και του χρόνου ενεργοποίησης (time-to-trigger).

### Τοπική Λειτουργία ML

Ορίστε τη μεταβλητή περιβάλλοντος `ML_LOCAL=1` για χρήση της λογικής ML που συνοδεύει το
container του NEF αντί για επικοινωνία με το API του `ml-service`. Παρέχετε τη διαδρομή προς
το μοντέλο LightGBM με το όρισμα `ml_model_path` κατά την δημιουργία του
`HandoverEngine`.

Εγκαταστήστε το πακέτο ML κατά την κατασκευή του image:

```Dockerfile
RUN pip install -e services/ml-service
```

Κατά την εκτέλεση με ενεργοποιημένο `ML_LOCAL`, μπορείτε να παραλείψετε το container `ml-service` στο
`docker-compose.yml`:

```yaml
services:
  nef-emulator:
    environment:
      - ML_LOCAL=1
#  ml-service:
#    image: 5g-network-optimization/ml-service:latest
```
