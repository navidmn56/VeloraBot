<div align="center">

# VeloraBot

**Telegram VPN Configuration Management Bot**

Python-based Telegram bot for VPN configuration sales, user management, payments, referrals and automated configuration delivery.

<br>

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge\&logo=python\&logoColor=white)](https://www.python.org/)
[![3X-UI](https://img.shields.io/badge/3X--UI-MHSanaei-181717?style=for-the-badge\&logo=github\&logoColor=white)](https://github.com/MHSanaei/3x-ui)
[![License](https://img.shields.io/badge/Status-Active-success?style=for-the-badge)](https://github.com/navidmn56/VeloraBot)

</div>

---

<div align="center">

<img src="docs/screenshot/Screenshot.png" alt="VeloraBot" width="360">

</div>

<div align="center">

<img src="docs/screenshot/Screenshot2.png" alt="VeloraBot" width="360">

</div>

---

## Overview

VeloraBot is a Python Telegram bot designed to automate VPN configuration sales and management through the MHSanaei 3X-UI panel.

The project includes user management, payments, referrals, configuration delivery, logging and optional AI-powered support.

## Features

| Feature      | Description                           |
| ------------ | ------------------------------------- |
| Telegram Bot | User and admin management             |
| VPN Sales    | Configuration purchasing and delivery |
| 3X-UI        | Configuration and client management   |
| Payments     | Balance, orders and receipt handling  |
| Referrals    | Referral links and rewards            |
| AI Support   | Optional Google Gemini integration    |
| Logging      | Application and Telegram logging      |
| Data         | Local JSON-based runtime storage      |

## 3X-UI

VeloraBot is developed specifically for:

**MHSanaei 3X-UI**

https://github.com/MHSanaei/3x-ui

Other VPN management panels are not supported.

Compatibility with future 3X-UI releases is not guaranteed until tested.

## Requirements

* Linux server
* Python 3.10+
* Git
* Telegram Bot Token
* MHSanaei 3X-UI
* 3X-UI API access

## Installation

```bash
cd /opt
git clone https://github.com/navidmn56/VeloraBot.git
cd VeloraBot
```

Create the virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure the bot:

```bash
nano config.py
```

Run:

```bash
python main.py
```

## systemd

Create the service:

```bash
sudo nano /etc/systemd/system/velorabot.service
```

```ini
[Unit]
Description=VeloraBot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/VeloraBot
ExecStart=/opt/VeloraBot/.venv/bin/python /opt/VeloraBot/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable velorabot
sudo systemctl start velorabot
```

### Service Commands

```bash
sudo systemctl status velorabot
sudo systemctl restart velorabot
sudo systemctl stop velorabot
sudo journalctl -u velorabot -f
```

## Update

```bash
cd /opt/VeloraBot
sudo systemctl stop velorabot
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart velorabot
```

## Project Structure

```text
VeloraBot/
├── data/
│   └── .gitkeep
├── .gitignore
├── config.py
├── logger_system.py
├── main.py
├── requirements.txt
└── test.py
```

Runtime files generated inside `data/` are ignored by Git.

## Screenshots

Additional screenshots can be added to:

```text
docs/screenshots/
```

## Status

This project is actively developed and may contain bugs.

## Author

**Navid**

GitHub:
https://github.com/navidmn56/VeloraBot
