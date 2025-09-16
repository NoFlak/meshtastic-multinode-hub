# Meshtastic Multi‑Node Support App (early work in progress 9/16/2025)

This project provides a web-based administrative interface for managing a small network of Meshtastic nodes. It extends the standard Meshtastic app with real‑time monitoring, advanced filtering and sorting, message logging, and centralized multi‑node control. Designed to run on a Raspberry Pi (or any Linux machine), the app is accessible via desktop browser, tablet, or mobile device.

## Features

- **Real‑Time Signal Monitoring**  
  Track RSSI, SNR, battery level, power usage, GPS location, and uptime for each node. Data is displayed in tables or simple charts and stored locally in a SQLite database for long-term reference.

- **Filtering & Sorting**  
  Filter nodes by status (online/offline), role (`ROUTER` vs `ROUTER_LATE`), battery state, signal strength, or geographic location. Sort by any column—e.g., strongest signal first or alphabetical order.

- **Simple Messaging Panel**  
  Send text messages through the mesh using a single input box. All messages are timestamped and logged with sender/recipient details.

- **Multi‑Node Control**  
  Built to manage configurations with three or more nodes (e.g., one `ROUTER` and two `ROUTER_LATE`, each covering a 120° field). Remotely adjust node roles, beacon intervals, channel settings, modem presets, and more via the Meshtastic CLI.

- **Off‑Grid Presets for Camping, Hiking & Festivals**  
  Activate a “base station” mode that reduces beacon frequency, disables GPS reporting, monitors battery/solar status, and raises alerts when nodes go offline.

- **Administrative Enhancements**  
  View hop counts, packet loss, last-heard timestamps, and other diagnostics not available in the standard Meshtastic app. Trigger soft resets, firmware updates, or configuration pushes.

- **Optimized for Raspberry Pi**  
  Install on a Pi to act as your base station. The responsive web interface works seamlessly across Android/iOS tablets, Kali/Windows laptops, or any modern browser.

## Installation

1. **Clone the repository**  
   Download the source files to your Raspberry Pi or Linux server:

   ```bash
   git clone https://github.com/yourusername/multi-node-support-app.git
   cd multi-node-support-app/meshtastic_support_app
   ```

2. **Install dependencies**  
   This app uses [FastAPI](https://fastapi.tiangolo.com/), [uvicorn](https://www.uvicorn.org/), and [Jinja2](https://palletsprojects.com/p/jinja/):

   ```bash
   pip install fastapi uvicorn jinja2
   ```

   Alternatively, use the included `requirements.txt` for explicit dependency management.

3. **Configure authentication**  
   Edit `config.json` to set your admin username and hashed password. The default is `admin` with an empty password—be sure to update this before deploying.

4. **Start the server**  
   Launch the app using uvicorn:

   ```bash
   uvicorn meshtastic_support_app.main:app --host 0.0.0.0 --port 8000
   ```

   Access the app at `http://<server-ip>:8000`. You can change the port if needed.

5. **Log in and explore**  
   Use your credentials to access the dashboard, messaging panel, and logs. Click **Update Nodes** to fetch the latest status via the Meshtastic CLI.

## Usage Overview

- **Dashboard**  
  Displays all known nodes with current metrics. Click **Update Nodes** to refresh. Node data is stored in a local SQLite database.

- **Messages**  
  Type your message and click **Send**. Messages are logged and displayed in reverse chronological order.

- **Logs**  
  View a history of actions (e.g., sent messages, node updates). Logs are stored in the `logs` table.

- **Configuration**  
  UI-based node control is not yet implemented. To extend functionality, modify the `run_cli_command` function in `main.py` to support additional Meshtastic CLI commands.

## License

This project is licensed under the [MIT License](LICENSE). You're free to use, modify, and distribute it in your own projects.

## Acknowledgements

Built on the [Meshtastic project](https://meshtastic.org/), this app provides a streamlined administrative front‑end for multi‑node deployments.
```

Let me know if you'd like to add a diagram, screenshot section, or GitHub badges for build status, license, or versioning.
