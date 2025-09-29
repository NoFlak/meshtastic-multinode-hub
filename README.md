# Meshtastic Multi‑Node Support App

This project provides an administrative web interface for managing a small network of Meshtastic nodes. It augments the standard Meshtastic app by adding real‑time monitoring, filtering and sorting, message logging, and multi‑node control. The application is designed to run on a Raspberry Pi (or any Linux machine) and is accessible from a desktop browser, tablet or mobile device.

## Features

* **Real‑time signal monitoring** – View RSSI, SNR, battery level, power usage, GPS location and uptime for each node in your mesh. Data can be displayed as tables or simple charts and is stored locally in a SQLite database for long‑term reference.
* **Filtering and sorting** – Filter nodes by status (online/offline), role (`ROUTER` vs `ROUTER_LATE`), battery state, signal strength or geographic location. Sort by any column, such as strongest signal first or alphabetical order.
* **Simple messaging panel** – Send text messages through the mesh via a single input box. Outgoing and incoming messages are logged with timestamps and the sender/recipient names.
* **Multi‑node control** – Manage a three‑node configuration (one router and two router_late) from a single dashboard. Adjust node roles, beacon intervals, channel settings, modem presets and other parameters remotely via the Meshtastic CLI.
* **Camping/hiking/festival presets** – Switch to an off‑grid “base station” mode that reduces beacon frequency, disables GPS reporting, monitors battery/solar status and raises alerts when a node drops offline.
* **Administrative enhancements** – Display hop counts, packet loss, last‑heard timestamps and other diagnostics not exposed in the standard Meshtastic app. Trigger soft resets, firmware updates or configuration pushes for your nodes.
* **Runs on Raspberry Pi** – Install this app on a Pi acting as your base station. It exposes a responsive web interface that works on Android/iOS tablets, laptops running Kali/Windows, or any modern browser.

## Installation

1. Clone this repository or download the source files to your Raspberry Pi or server:

    ```
    git clone https://github.com/yourusername/multi-node-support-app.git
    cd multi-node-support-app
    ```

2. (Optional) Create and activate a virtual environment to isolate dependencies.

    ```
    python -m venv .venv
    # Windows
    .venv\Scripts\activate
    # Linux / macOS
    source .venv/bin/activate
    ```

3. Install the Python dependencies listed in `requirements.txt`:

    ```
    python -m pip install -r requirements.txt
    ```

4. Start the FastAPI server from the project root. Using the module form ensures Python can locate the `meshtastic_support_app` package even if `uvicorn` is not on your PATH:

    ```
    python -m uvicorn meshtastic_support_app.main:app --host 0.0.0.0 --port 8000
    ```

   The app will be available at `http://<server-ip>:8000`. You can change the port as desired. If you prefer the `uvicorn` CLI directly, run it from the project root so the package remains importable.

5. Log in with your configured credentials and explore the dashboard, messages and logs. Use the **Update Nodes** button on the dashboard to fetch current node status via the Meshtastic CLI.
## Usage

* **Dashboard** – Displays all known nodes with their latest metrics. Click **Update Nodes** to refresh. Nodes are stored in a local SQLite database.
* **Messages** – Send a message by typing in the input box and clicking **Send**. Past messages are shown below in reverse chronological order.
* **Logs** – View an audit trail of actions (e.g. messages sent, node status updates). Logs are stored in the `logs` table of the database.
* **Configuration** – At present, node control functions (changing roles, beacon intervals, etc.) are not implemented in the UI. You can extend the `run_cli_command` function in `main.py` to call additional Meshtastic CLI commands.

## License

This project is licensed under the [MIT License](LICENSE). Feel free to use, modify and distribute this software in your own projects.

## Acknowledgements

This app builds on the Meshtastic project (https://meshtastic.org/), providing an administrative front‑end for multi‑node deployments.