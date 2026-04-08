# Εξομοιωτής NEF (Προσομοιωτής RAN)

> **⚠️ Σημείωση Ορολογίας**: Παρά το όνομα «Εξομοιωτής NEF», αυτή η υπηρεσία λειτουργεί ως **Προσομοιωτής RAN** που υλοποιεί διάδοση σήματος gNB, λογική handover και μοντελοποίηση καναλιού. Το όνομα είναι ιστορικό. Δείτε [docs/ORAN_TERMINOLOGY.md](docs/ORAN_TERMINOLOGY.md) για αντιστοίχιση αρχιτεκτονικής O-RAN και διευκρίνιση ορολογίας.

Υπηρεσία προσομοίωσης RAN βασισμένη σε FastAPI με web UI, διαχείριση τοπολογίας δικτύου και προαιρετική βελτιστοποίηση handover με ML.

## Γιατί είναι σημαντική αυτή η υπηρεσία

- **Περιβάλλον Προσομοίωσης RAN** – REST API για gNBs, cells, UEs, πρότυπα κινητικότητας, με μοντέλα καναλιού συμβατά με 3GPP και λογική handover.
- **Λειτουργικό UI** – Πίνακας ελέγχου, χάρτης, εισαγωγή/εξαγωγή και ροές CRUD που εξυπηρετούνται απευθείας από το backend (`/ui`, `/static`).
- **Πειραματισμός handover** – Pipeline ML handover με δυνατότητα εναλλαγής που συνεργάζεται με τη μικρουπηρεσία ML ή τοπικό μοντέλο και επιστρέφει στον κανόνα A3 του 3GPP.
- **Παρατηρησιμότητα & αυτοματισμός** – Μετρικές Prometheus (`/metrics`), βοηθοί onboarding CAPIF, scripts σποράς επίδειξης βάσης δεδομένων, middleware χρονισμού αιτημάτων και στόχοι Make για κοινές ροές εργασίας.

---

## Αρχιτεκτονική Συστήματος

### Επιφάνειες FastAPI

- Η `app.main:app` εκθέτει εσωτερικά REST APIs κάτω από `settings.API_V1_STR` (προεπιλογή `/api/v1`). Ομάδες router βρίσκονται στο `app/api/api_v1/endpoints` και περιλαμβάνουν σύνδεση, χρήστες, απογραφή δικτύου (gNBs, Cells, UEs, Paths), έλεγχο κίνησης, πληροφορίες QoS, πρότυπα κινητικότητας και βοηθητικά ML handover.
- Μια αποκλειστική υποεφαρμογή `nef_app` είναι τοποθετημένη στο `/nef`. Περιτυλίγει τα endpoints που αντιμετωπίζουν το 3GPP (`/3gpp-monitoring-event/v1`, `/3gpp-as-session-with-qos/v1`) που χρησιμοποιούν NetApps ενσωματωμένες με CAPIF.
- Στατικοί πίνακες ελέγχου παραδίδονται με `Jinja2Templates` και `StaticFiles`. Οι σελίδες περιλαμβάνουν `/login`, `/dashboard`, `/map`, `/export`, `/import` και εναλλακτικές σφαλμάτων. Δείτε `docs/UI.md` για αναλυτική εμβάθυνση στη δομή frontend.

### Αποθήκες Δεδομένων και Background Jobs

- Η **PostgreSQL** αποθηκεύει δομημένες οντότητες (χρήστες, UEs, cells, paths). Οι sessions SQLAlchemy δημιουργούνται στο `app/db/session.py` και συνδέονται μέσω εξαρτήσεων FastAPI.
- Η **MongoDB** αποθηκεύει συνδρομές παρακολούθησης, ειδοποιήσεις και στιγμιότυπα κίνησης UE που χρησιμοποιεί το επίπεδο polling UI (`crud_mongo`).
- Το `app/initial_data.py` σπέρνει βασική κατάσταση βάσης δεδομένων και (προαιρετικά) εισάγει το NEF στο CAPIF χρησιμοποιώντας `CAPIFProviderConnector` του `evolved5g`.
- Ο βρόχος επανάληψης `backend_pre_start.py` διασφαλίζει διαθεσιμότητα Postgres πριν εκκινήσει το Uvicorn· το `start-reload.sh` εκκινεί Uvicorn με αυτόματη επαναφόρτωση (και προαιρετικό hook `prestart.sh` όταν παρέχεται).

### Pipeline ML Handover

- Ο `HandoverEngine` αξιολογεί κατάσταση UE από το `NetworkStateManager`. Όταν το `use_ml` είναι ενεργοποιημένο, αποστέλλει διανύσματα χαρακτηριστικών στο `${ML_SERVICE_URL}/api/predict` και αναμένει `{predicted_antenna, confidence}` ως επιστροφή.
- Τα κατώφλια εμπιστοσύνης (`ML_CONFIDENCE_THRESHOLD`) αποφασίζουν αν θα γίνουν αποδεκτές οι εξόδους ML ή αν θα γίνει επαναφορά στον ντετερμινιστικό `A3EventRule`. Η έλλειψη επαρκών κεραιών απενεργοποιεί επίσης αυτόματα το ML (ελάχιστος αριθμός προεπιλεγμένα τρεις).
- Βασικές μετρικές εξαγόμενες μέσω `app/monitoring/metrics.py`:
  - `nef_handover_decisions_total{outcome}` – εφαρμοσμένα vs παραλειφθέντα handovers
  - `nef_handover_fallback_total` – ML προβλέψεις απορριφθείσες λόγω χαμηλής εμπιστοσύνης
  - `nef_request_duration_seconds{method,endpoint}` – ιστόγραμμα καθυστερήσεων αιτημάτων (πληθυσμένο από το middleware που προσθέτει επίσης την επικεφαλίδα `X-Process-Time`)

---

## Τοπική Ανάπτυξη

### Προϋποθέσεις

- Docker Engine ≥ 23 και Docker Compose V2
- `make` (GNU make – εγκατάσταση μέσω `build-essential` σε Debian/Ubuntu) αν θέλετε να χρησιμοποιήσετε τους παρεχόμενους στόχους
- `jq` για το προαιρετικό script σποράς dataset (`app/db/init_simple.sh`)

### Δημιουργία του `.env`

Η στοίβα βασίζεται σε αρχείο `.env` στο `services/nef-emulator/`. Αν το `env-file-for-local.dev` είναι διαθέσιμο στο αντίγραφό σας μπορείτε να το αντιγράψετε με `make prepare-dev-env`· διαφορετικά δημιουργήστε ένα χειροκίνητα.

Ξεκινήστε με τα βασικά:

```dotenv
# Core service URLs
DOMAIN=localhost
NEF_HOST=nef.local
NGINX_HTTP=8090
NGINX_HTTPS=4443

# Backend FastAPI settings
SERVER_NAME=nef-emulator
SERVER_HOST=https://localhost
PROJECT_NAME=NEF Emulator
BACKEND_CORS_ORIGINS=["http://localhost:3000"]

# Auth bootstrap
FIRST_SUPERUSER=admin@my-email.com
FIRST_SUPERUSER_PASSWORD=pass
USERS_OPEN_REGISTRATION=false
USE_PUBLIC_KEY_VERIFICATION=false

# PostgreSQL
POSTGRES_SERVER=db
POSTGRES_DB=app
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

# MongoDB
MONGO_CLIENT=mongodb://mongo_nef:27017
MONGO_USER=root
MONGO_PASSWORD=pass
MONGO_EXPRESS_ENABLE_ADMIN=true

# CAPIF (προσαρμόστε στην ανάπτυξή σας)
CAPIF_HOST=capifcore
CAPIF_HTTP_PORT=8080
CAPIF_HTTPS_PORT=443
EXTERNAL_NET=true

# Observability
LOG_LEVEL=info
LOG_FILE=

# ML integration
ML_SERVICE_URL=http://ml-service:5050
ML_HANDOVER_ENABLED=0
ML_CONFIDENCE_THRESHOLD=0.5
ML_LOCAL=0

# Reverse proxy image tag
DOCKER_IMAGE_BACKEND=nef-emulator-backend
TAG=local
```

Πρόσθετες παράμετροι ρύθμισης αναφέρονται στην [Αναφορά Διαμόρφωσης](#αναφορά-διαμόρφωσης).

### Εκκίνηση της Στοίβας

Με το `.env` στη θέση του μπορείτε να χρησιμοποιήσετε είτε τους στόχους Make είτε απευθείας το Compose:

```powershell
# Κατασκευή των images backend και reverse proxy
make build

# Εκκίνηση προφίλ developer (FastAPI + Postgres + Mongo + reverse proxy)
make up

# Για εκτέλεση αποσυνδεμένα:
make upd

# Παρακολούθηση αρχείων καταγραφής
make logs-dev
```

Ισοδύναμες εντολές Compose (από το `services/nef-emulator/`):

```powershell
docker compose --profile dev build
docker compose --profile dev up
```

Προφίλ Compose:

- `dev` – backend (FastAPI με επαναφόρτωση), Postgres, Mongo, reverse proxy.
- `debug` – προσθέτει pgAdmin (`:5050`) και Mongo Express (`:8081`) για ζωντανή επιθεώρηση. Χρησιμοποιήστε `make debug-up` / `make debug-upd`.

### Σημεία Πρόσβασης

| Λειτουργία | URL (HTTP) | URL (HTTPS) | Σημειώσεις |
|------------|------------|-------------|------------|
| Swagger UI (εσωτερικά APIs) | `http://localhost:${NGINX_HTTP}/docs` | `https://localhost:${NGINX_HTTPS}/docs` | Διαθέσιμο στη root εφαρμογή |
| 3GPP northbound Swagger | `http://localhost:${NGINX_HTTP}/nef/docs` | `https://localhost:${NGINX_HTTPS}/nef/docs` | Τοποθετημένη υποεφαρμογή |
| Σύνδεση Web UI | `http://localhost:${NGINX_HTTP}/login` | `https://localhost:${NGINX_HTTPS}/login` | Προεπιλεγμένα διαπιστευτήρια από env |
| Μετρικές Prometheus | `http://localhost:${NGINX_HTTP}/metrics` | `https://localhost:${NGINX_HTTPS}/metrics` | Scrape με Prometheus ή curl |

Αυτόματα υπογεγραμμένα πιστοποιητικά δημιουργούνται κατά την εκκίνηση container (`nginx/self-signed-crt.sh`). Τα προγράμματα περιήγησης θα ζητήσουν εμπιστοσύνη στην πρώτη επίσκεψη.

### Σπορά Δεδομένων Επίδειξης (Προαιρετικό)

Μόλις εκτελείται η στοίβα μπορείτε να φορτώσετε ένα δείγμα σεναρίου (paths, gNB, cells, UEs) μέσω:

```powershell
make db-init
```

Το script συνδέεται χρησιμοποιώντας διαπιστευτήρια `FIRST_SUPERUSER` και εκδίδει REST POSTs. Βεβαιωθείτε ότι το `jq` είναι εγκατεστημένο τοπικά.

Επαναφορά δεδομένων:

```powershell
make db-reset    # αποκόπτει SQL πίνακες + σβήνει βάση Mongo
make db-reinit   # επαναφορά + σπορά εκ νέου
```

---

## Επιφάνεια API

| Ομάδα | Πρόθεμα | Περιγραφή |
|-------|---------|-----------|
| Αυθεντικοποίηση | `/api/v1/login` | Έκδοση token για το UI και τις NetApps |
| Χρήστες & διαχείριση | `/api/v1/users` | CRUD για χρήστες, χρησιμοποιεί εξαρτήσεις FastAPI και SQLAlchemy |
| Απογραφή δικτύου | `/api/v1/gNBs`, `/Cells`, `/UEs`, `/paths` | Διαχείριση οντοτήτων τοπολογίας που υποστηρίζουν τους UI datatables |
| Κινητικότητα & τηλεμετρία | `/api/v1/ue_movement`, `/mobility-patterns` | Έλεγχος κινητικότητας UE, λήψη τροχιών, παραγωγή διανυσμάτων χαρακτηριστικών |
| Βοηθητικά QoS | `/api/v1/qosInfo` | Εκθέτει προφίλ QoS όπως ορίζονται στο `config/qosCharacteristics.json` |
| ML handover | `/api/v1/ml/state/{ue_id}`, `/api/v1/ml/handover` | Επιθεώρηση διανυσμάτων χαρακτηριστικών, ενεργοποίηση αποφάσεων handover |
| APIs 3GPP | `/nef/3gpp-monitoring-event/v1`, `/nef/3gpp-as-session-with-qos/v1` | Εκτεθειμένα μέσω CAPIF συμβάντα παρακολούθησης, ροές QoS session με εγγραφή callback |

Λεπτομερή παραδείγματα αιτημάτων/αποκρίσεων στο `docs/test_plan/`.

### Μοντελοποίηση Κινητικότητας

Η παραγωγή τροχιών ακολουθεί τα πρότυπα κινητικότητας 3GPP TR 38.901 §7.6 και βρίσκεται στο `app/mobility_models/models.py`:

- `LinearMobilityModel` και `LShapedMobilityModel` αναπαράγουν την ευθύγραμμη κινηματική (§7.6.3.2) και δύο-τμήματος διαδρομής L-σχήματος με δειγματοληψία ευθυγραμμισμένη χρονικά.
- `RandomWaypointModel` υλοποιεί την κίνηση βάσει waypoints (§7.6.3.3), συμπεριλαμβανομένου χειρισμού παύσης και τυχαίας επιλογής ταχύτητας μεταξύ `v_min`/`v_max`.
- `ManhattanGridMobilityModel` και `UrbanGridMobilityModel` καλύπτουν τις ορθογώνιες περιπτώσεις πλέγματος οδών (§7.6.3.4) με πιθανοτική επιλογή στροφής στις διασταυρώσεις.
- `RandomDirectionalMobilityModel` υποστηρίζει συνεχείς αλλαγές κατεύθυνσης με εκθετικούς χρονιστές, συν ανάκλαση ορίων μέσω `_handle_boundary_collision`.
- `ReferencePointGroupMobilityModel` επιστρώνει μετατοπίσεις ομάδας πάνω σε οποιοδήποτε κεντρικό μοντέλο για προσομοίωση συσχετισμένων συστάδων UE (§7.6.3.5).

Όλα τα συγκεκριμένα μοντέλα κληρονομούν από το `MobilityModel`, το οποίο καταγράφει τροχιές και εκθέτει `get_position_at_time()` για παρεμβαλλόμενη αναζήτηση `(x, y, z)`. Ο κοινός βοηθός `_interpolate_position()` εκτελεί παρεμβολή με χρονική ταξινόμηση, εξασφαλίζοντας ομαλή αναπαραγωγή για το UI και τους εξαγωγείς χαρακτηριστικών.

### Παράδειγμα Ροής Handover

```powershell
# Επιθεώρηση δυναμικού διανύσματος χαρακτηριστικών για UE 202010000000001
curl -k "https://localhost:${env:NGINX_HTTPS}/api/v1/ml/state/202010000000001" -H "Authorization: Bearer $token"

# Αίτημα αξιολόγησης handover από τη μηχανή για το ίδιο UE
curl -k -X POST "https://localhost:${env:NGINX_HTTPS}/api/v1/ml/handover?ue_id=202010000000001" -H "Authorization: Bearer $token"
```

Τα payload επιστροφής περιέχουν την εφαρμοσμένη κεραία και αντικατοπτρίζονται στο `NetworkStateManager.handover_history`.

---

## Παρακολούθηση & Λειτουργίες

- Endpoint scrape Prometheus: `/metrics` (δείτε ονόματα μετρικών παραπάνω).
- Κάθε HTTP απόκριση φέρει `X-Process-Time` που εκθέτει καθυστέρηση από την πλευρά του διακομιστή.
- Τα αρχεία καταγραφής reverse proxy βρίσκονται στον τόμο `nginxdata`· τα αρχεία FastAPI τιμούν τις ρυθμίσεις `LOG_LEVEL`/`LOG_FILE`.
- Χρησιμοποιήστε `make logs-dev`, `make logs-debug` ή `docker compose logs -f backend` για ζωντανή ροή αρχείων καταγραφής.

---

## Ενσωμάτωση CAPIF

Η ροή εργασίας onboarding αυτοματοποιείται από το `app/initial_data.py`, το οποίο εκτελείται κατά την εκκίνηση container. Για επιτυχή εγγραφή στο CAPIF:

1. **Εκτέλεση CAPIF Core Function** – Ακολουθήστε <https://github.com/EVOLVED-5G/CAPIF_API_Services> και βεβαιωθείτε ότι οι βασικές υπηρεσίες είναι προσβάσιμες.
2. **Κοινό Docker network** – Ορίστε `EXTERNAL_NET=true` ώστε το Compose να επισυνάψει `services_default` (πρέπει ήδη να υπάρχει – δημιουργείται από τη στοίβα CAPIF). Για αναπτύξεις cross-host ορίστε σε `false` και δρομολογήστε την κίνηση χειροκίνητα.
3. **Καταχωρήσεις host** – Αντιστοιχίστε το `capifcore` στο `/etc/hosts` (είτε στο `127.0.0.1` ή στη διεύθυνση IP του VM CAPIF).
4. **Εκκίνηση NEF** – `make up` ή `make debug-up`. Κατά την εκκίνηση, το `capif_service_description()` επανεγγράφει το `app/core/capif_files/*.json` με τα ονόματα host και θύρες runtime, και στη συνέχεια το `capif_nef_connector()` εγγράφει και δημοσιεύει υπηρεσίες.
5. **Επικύρωση** – Μετά από επιτυχή εκτέλεση 12 αντικείμενα πιστοποιητικών πρέπει να υπάρχουν στο `backend/app/app/core/certificates/`. Τα αρχεία καταγραφής θα καταγράφουν επιτυχία/αποτυχία onboarding.

Το `USE_PUBLIC_KEY_VERIFICATION=true` αλλάζει την αυθεντικοποίηση API σε tokens εκδοθέντα από CAPIF (επικύρωση δημόσιου κλειδιού). Όταν είναι `false`, το τοπικό μυστικό JWT ασφαλίζει τα endpoints.

---

## Επισκόπηση Web UI

- **Dashboard** – CRUD σε gNBs, cells, paths, UEs χρησιμοποιώντας datatables και modal φόρμες.
- **Map** – Οπτικοποιεί κίνηση UE (βρόχος polling) και ειδοποιήσεις callback σε ροή.
- **Export / Import** – Κυκλοφορία σεναρίων ως αρχεία JSON.
- **Αυθεντικοποίηση** – Tokens αποθηκευμένα στο `localStorage` (`app_auth`), η σύνδεση εκκίνησης κινεί όλες τις σελίδες.

Ανατρέξτε στο `docs/UI.md` για λεπτομέρειες βιβλιοθηκών (CoreUI, Leaflet, DataTables, Toastr, CodeMirror) και αρχιτεκτονικές σημειώσεις.

---

## Αναφορά Διαμόρφωσης

| Μεταβλητή | Απαιτείται | Προεπιλογή / Παράδειγμα | Σκοπός |
|-----------|-----------|------------------------|--------|
| `DOMAIN` | ✅ | `localhost` | Βασικός τομέας που διαφημίζει ο reverse proxy |
| `NEF_HOST` | ✅ | `nef.local` | Όνομα host reverse proxy (χρησιμοποιείται σε TLS certs) |
| `NGINX_HTTP` / `NGINX_HTTPS` | ✅ | `8090` / `4443` | Δημοσιευμένες θύρες για HTTP/HTTPS |
| `SERVER_NAME` | ✅ | `nef-emulator` | Τίτλος FastAPI |
| `SERVER_HOST` | ✅ | `https://localhost` | Εξωτερικό URL FastAPI για δημιουργία OpenAPI |
| `BACKEND_CORS_ORIGINS` | ➖ | `[]` | Επιτρεπόμενες πηγές για CORS |
| `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD` | ✅ | `admin@my-email.com`, `pass` | Διαπιστευτήρια bootstrap διαχειριστή |
| `USERS_OPEN_REGISTRATION` | ➖ | `false` | Επιτρέπει αυτο-εγγραφή χρηστών |
| `USE_PUBLIC_KEY_VERIFICATION` | ➖ | `false` | Επιβολή επικύρωσης πιστοποιητικού CAPIF |
| `POSTGRES_SERVER`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | ✅ | `db`, `app`, `postgres`, `postgres` | Ρυθμίσεις σύνδεσης SQL |
| `MONGO_CLIENT` | ✅ | `mongodb://mongo_nef:27017` | Mongo URI για συλλογές παρακολούθησης |
| `MONGO_USER`, `MONGO_PASSWORD` | ✅ | `root`, `pass` | Διαπιστευτήρια που διαβιβάζονται στο container Mongo |
| `MONGO_EXPRESS_ENABLE_ADMIN` | ➖ | `true` | Ενεργοποιεί λειτουργία διαχειριστή στο Mongo Express όταν χρησιμοποιείται το debug profile |
| `CAPIF_HOST`, `CAPIF_HTTP_PORT`, `CAPIF_HTTPS_PORT` | ✅ (όταν χρησιμοποιείται CAPIF) | `capifcore`, `8080`, `443` | Endpoints υπηρεσίας CAPIF API |
| `EXTERNAL_NET` | ➖ | `true` | Επισύναψη στοίβας Compose στο docker network CAPIF |
| `PRODUCTION`, `DOMAIN_NAME`, `NGINX_HOST` | ➖ | – | Προσαρμογή περιγραφέων υπηρεσίας CAPIF για αναπτύξεις παραγωγής |
| `ML_SERVICE_URL` | ➖ | `http://ml-service:5050` | Βασικό URL απομακρυσμένης μικρουπηρεσίας ML |
| `ML_HANDOVER_ENABLED` | ➖ | `0` | Εξαναγκαστική ενεργοποίηση/απενεργοποίηση ML handover (παρακάμπτει αυτόματη ευρετική αριθμού κεραιών) |
| `ML_LOCAL` | ➖ | `0` | Εγκατάσταση και χρήση ενσωματωμένου πακέτου ML εντός image backend |
| `ML_CONFIDENCE_THRESHOLD` | ➖ | `0.5` | Ελάχιστη εμπιστοσύνη αποδεκτή από ML αποκρίσεις |
| `A3_HYSTERESIS_DB`, `A3_TTT_S` | ➖ | `2.0`, `0.0` | Παράμετροι για τον εναλλακτικό κανόνα A3 |
| `NOISE_FLOOR_DBM`, `RESOURCE_BLOCKS` | ➖ | `-100`, `50` | RF υπολογισμοί εντός `NetworkStateManager` |
| `LOG_LEVEL`, `LOG_FILE` | ➖ | `info`, _κενό_ | Ρύθμιση δομημένης καταγραφής |
| `DOCKER_IMAGE_BACKEND`, `TAG` | ➖ | `nef-emulator-backend`, `local` | Παρακάμψεις ονοματολογίας image για Compose |
| `INSTALL_DEV`, `INSTALL_JUPYTER` | ➖ | `true` / `false` | Build args που χρησιμοποιούνται στο `Dockerfile.backend` |

---

## Ροή Εργασίας Ανάπτυξης

### Τοπική Εγκατάσταση Εξαρτήσεων

```powershell
cd services/nef-emulator/backend/app
poetry install
```

Εκτέλεση δοκιμών:

```powershell
poetry run pytest
```

Η σουίτα δοκιμών ελέγχει φόρτωση διαμόρφωσης, αρχικοποίηση βάσης δεδομένων και API συμβόλαια UE (`tests/api/test_ue_endpoints.py`).

### Χρήσιμοι Στόχοι Make

| Στόχος | Περιγραφή |
|--------|-----------|
| `make build` | Κατασκευή images backend και nginx |
| `make up` / `make upd` | Εκκίνηση προφίλ dev (foreground / αποσυνδεμένα) |
| `make debug-up` | Εκκίνηση debug profile με pgAdmin & Mongo Express |
| `make logs-<service>` | Ζωντανή ροή αρχείων καταγραφής (backend / mongo / dev / debug) |
| `make db-init` | Σπορά demo τοπολογίας μέσω REST κλήσεων |
| `make db-reset` | Αποκοπή πινάκων Postgres & διαγραφή MongoDB |

---

## Αντιμετώπιση Προβλημάτων

- **Ελλείπουσες μεταβλητές `.env`** – Το FastAPI θα τερματίσει αν λείπουν απαιτούμενες ρυθμίσεις (π.χ., `FIRST_SUPERUSER`). Ελέγξτε διπλά σε σχέση με τον πίνακα διαμόρφωσης.
- **Αποτυχία onboarding CAPIF** – Βεβαιωθείτε ότι το `capifcore` είναι προσβάσιμο από το container backend (`docker compose exec backend ping capifcore`). Επιθεωρήστε το `backend/app/app/core/certificates/` για μερικά αντικείμενα.
- **Σφάλματα `make db-init`** – Επαληθεύστε ότι η στοίβα NEF εκτελείται ήδη και ότι το `jq` είναι εγκατεστημένο στον κεντρικό υπολογιστή. Το script αναμένει HTTPS προσβάσιμο στο `${DOMAIN}:${NGINX_HTTPS}` με το container reverse proxy υγιές.
- **Timeouts υπηρεσίας ML** – Το backend καταγράφει εξαιρέσεις από `requests.post`. Ορίστε `ML_HANDOVER_ENABLED=0` ή `ML_CONFIDENCE_THRESHOLD=1` για προσωρινή αναγκαστική λειτουργία μόνο με A3.
- **Προειδοποιήσεις αυτόματα υπογεγραμμένων πιστοποιητικών** – Εισαγάγετε `nginx/certs/*.crt` στο αποθετήριο εμπιστοσύνης σας ή χρησιμοποιήστε την θύρα HTTP για τοπική επανάληψη.

---

### Περαιτέρω Ανάγνωση

- `docs/UI.md` – Σημειώσεις σχεδίασης frontend και αλληλεπίδρασης.
- `docs/antenna_and_path_loss.md` – Τεκμηρίωση μοντελοποίησης RF.
- `tests/` – Παραδείγματα χρήσης που συνοδεύουν τα endpoints.

Καλά πειράματα με τον Εξομοιωτή NEF!
