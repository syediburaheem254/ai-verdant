# AI Verdant — AI Farming Monitoring System

A full stack for the AI Farming project: a sensor box (ESP32 + 5 sensors)
reports live field conditions, which are mirrored to Google Sheets and
served through **AI Verdant**, a neon-styled multi-page dashboard that
scores conditions, explains them in plain English, charts fluctuations
over time, and generates a prioritized care strategy.

```
ai-verdant/
├── backend/              Flask API — ingest, scoring, recommendations, Sheets sync
├── frontend/             AI Verdant web app (Dashboard, Sensors, Trends, Strategy, Settings)
├── hardware/             ESP32 Arduino sketch for the sensor box
├── google_apps_script/   Optional in-Sheet automation
└── docs/                 (space for your own notes/diagrams)
```

## 1. How data flows

```
[ Sensor Box: DHT22, HC-SR04, pH probe, PIR, soil moisture ]
                        │  WiFi, every 10 min
                        ▼
              POST /api/ingest  (Flask backend)
                 │                     │
                 ▼                     ▼
         SQLite (ai_verdant.db)   Google Sheet ("Readings" tab)
                 │
                 ▼
      Scoring + recommendation engine (analysis.py)
                 │
                 ▼
     AI Verdant frontend (Dashboard / Sensors / Trends / Strategy)
                 ▲
                 │ scan
         QR code sticker on the box → /portal/<device_id>
```

## 2. Backend setup

```bash
cd backend
python -m venv venv && source venv/bin/activate      # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env                                  # then edit values
python app.py
```

The API runs at `http://localhost:5000` by default. Key endpoints:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ingest` | Device pushes one reading (needs `X-Device-Key` header) |
| GET | `/api/devices` | List registered sensor boxes |
| GET | `/api/devices/<id>/latest` | Latest reading + scores + explanations |
| GET | `/api/devices/<id>/history?hours=24` | Time series for charts |
| GET | `/api/devices/<id>/recommendations` | Ranked recommendations |
| GET | `/api/devices/<id>/strategy` | Elaborate optimal-strategy plan |
| GET | `/portal/<id>` | QR-code landing page |

### Google Sheets bridge
1. Create a Google Cloud project → enable **Sheets API** + **Drive API**.
2. Create a **Service Account**, download its JSON key as `backend/service_account.json`.
3. Open `google_sheets_template/AI_Verdant_Sensor_Log.xlsx` in Google Sheets: Drive → New → File
   upload → open it → File → Save as Google Sheets. Rename the file to match `GOOGLE_SHEET_NAME` in
   `.env` (default `AI Farming - Sensor Log`), or copy its ID into `GOOGLE_SHEET_ID`.
   This template already has the exact tabs and columns the backend expects, so you don't
   need to build the sheet by hand:
   - **Readings** — the log the backend appends to (must keep this exact column order).
   - **Devices** — one row per sensor box; set each device's `Crop Type` here.
   - **Optimal Conditions** — ideal ranges per crop (Tomato, Lettuce, Rice, Wheat, Chili, plus a
     Default row matching `backend/config.py`). Edit or add crops here.
   - **Live Status** — live formulas that pull the most recent `Readings` row, look up that
     device's crop, and compare it against `Optimal Conditions` — the in-sheet equivalent of the
     app's Dashboard, with conditional-formatting highlights (green/amber/pink).
   Delete the example rows in Readings/Devices once your real device starts reporting.
4. Share the Sheet with the service account's email (found in the JSON as `client_email`), **Editor** access.
5. Restart the backend — every ingested reading now appears as a new row in the "Readings" tab automatically.
6. (Optional) Paste `google_apps_script/Code.gs` into Extensions → Apps Script in that Sheet for
   conditional-formatting highlights and a one-click daily-summary email.

> Note: the **Live Status** tab's formulas point at whatever row is currently last in Readings —
> they update automatically as the backend appends new rows, no re-copying needed.

### QR code sticker
```bash
cd backend
python qr_generator.py device-001
```
This creates `device-001-qr.png` encoding `PUBLIC_BASE_URL/portal/device-001`. Print it and stick it
on the sensor box. Scanning it opens a page showing the latest reading with a button into the full app.

## 3. Frontend setup

The frontend is plain HTML/CSS/JS — no build step required.

```bash
cd frontend
python -m http.server 8080
# open http://localhost:8080
```

On first load, go to **Settings** and confirm the backend API URL (defaults to
`http://localhost:5000`). Pick your device from the sidebar dropdown — the app remembers it.

Pages:
- **Dashboard** — overall condition score, live metric cards, top explanations & recommendations.
- **Sensor Details** — every sensor's raw value, ideal range, and individual health score in one table.
- **Trends & History** — line charts of temperature, humidity, soil moisture, and pH with plain-English
  descriptions of each trend, selectable over 6h/24h/3d/7d.
- **Optimal Strategy** — the consolidated, timed action plan (next 2 hours / today / this week) plus
  the full ranked recommendation list.
- **Settings** — backend URL, registered devices, and a summary of how data flows end to end.

## 3b. Installing it as an app (PWA)

The frontend now ships with `manifest.json`, `sw.js`, and app icons, so once it's served over
**HTTPS** (GitHub Pages and Netlify both do this automatically), visitors can install it:

- **Android/Chrome:** menu → "Install app" / "Add to Home screen".
- **iPhone/Safari:** Share button → "Add to Home Screen".

It then opens full-screen with its own icon, no browser bar, and the app shell (HTML/CSS/JS)
is cached for instant loading — though live sensor data still needs an internet connection to
reach your backend. This does not work over plain `http://`, only `https://` or `localhost`.

## 4. Hardware setup

Open `hardware/field_node.ino` in the Arduino IDE with ESP32 board support installed.
Install libraries: **DHT sensor library** (Adafruit) and **ArduinoJson**. Fill in your WiFi
credentials, `SERVER_URL` (your backend's public address), and `DEVICE_API_KEY` (must match
the backend's `.env`). Wire the sensors per the pin comments at the top of the file, then flash it.

## 5. Customizing for your crop

Edit `IDEAL_RANGES` in `backend/config.py` to match your crop's ideal temperature, humidity,
soil moisture, and pH windows — every score, explanation, and recommendation is derived from
these ranges.

## 6. Security notes

- `DEVICE_API_KEY` gate the ingest endpoint — keep it secret and don't commit `.env` or
  `service_account.json` to version control (both are already good candidates for `.gitignore`).
- For production, put the Flask app behind HTTPS (e.g. via a reverse proxy or a host like
  Render/Fly.io) since sensor data and your Sheet credentials are on the line.
