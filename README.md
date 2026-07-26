# 🚌 MOTAS Smart Dispatch System

A modern web-based **Public Transportation Management System** developed with **Flask** and **PostgreSQL**.

> **Educational & Portfolio Project**
>
> This project was developed for educational and portfolio purposes.
> It is **not affiliated with, endorsed by, or developed by MOTAŞ**.

---

# 📖 Overview

MOTAS Smart Dispatch System is a full-stack web application that simplifies the management of urban public transportation services.

The project provides both a **public passenger portal** and a comprehensive **administration panel** for managing buses, routes, drivers, stops, announcements, users, and transportation operations.

---

# ✨ Features

## 🌐 Public Portal

- 🚌 Bus route information
- 🚏 Bus stop information
- 🤖 AI-assisted route recommendation
- 📢 Announcements
- 🔍 Route search
- 👤 User Login
- 📝 User Registration
- 🎒 Lost Property Application
- 📞 Contact Page

---

## 🔐 Administration Panel

- 📊 Dashboard
- 🚌 Bus Management
- 🚏 Bus Stop Management
- 🗺 Route Management
- 👨‍✈️ Driver Management
- 🕒 Trip Scheduling
- 📢 Announcement Management
- 👥 User Management
- 📝 Complaint & Request Management

---

# 🏗 System Architecture

```text
                Users
                   │
                   ▼
          Flask Web Application
                   │
     ┌─────────────┼─────────────┐
     │             │             │
 Templates      Static Files   Admin Panel
     │             │             │
     └─────────────┼─────────────┘
                   │
             SQLAlchemy ORM
                   │
             PostgreSQL Database
```

---

# 🛠 Technologies

| Technology | Purpose |
|------------|---------|
| Python | Backend Development |
| Flask | Web Framework |
| PostgreSQL | Database |
| SQLAlchemy | ORM |
| HTML5 | Frontend |
| CSS3 | Styling |
| JavaScript | Client-side |

---

# 📂 Project Structure

```text
MOTAS-Smart-Dispatch-System
│
├── database/
│   └── schema.sql
│
├── docs/
│   └── screenshots/
│
├── exports/
│
├── static/
│
├── templates/
│
├── app.py
├── config.py
├── requirements.txt
└── README.md
```

---

# 🗄 Database

The project uses **PostgreSQL** as the primary database.

Database schema is located in:

```text
database/schema.sql
```

---

# 🚀 Installation

## Clone Repository

```bash
git clone git@github.com:EmreBEYS/MOTAS-Smart-Dispatch-System.git
```

---

## Install Requirements

```bash
pip install -r requirements.txt
```

---

## Configure Environment

Create an **ai.env** file.

Example:

```env
SECRET_KEY=your_secret_key

DATABASE_URL=postgresql://username:password@localhost:5432/busweb

OPENAI_API_KEY=your_api_key
```

---

## Run

```bash
python app.py
```

---

# 📸 Screenshots

## 🏠 Home Page

![Home](docs/screenshots/home.png)

---

## 🤖 AI Route Recommendation

![AI Route](docs/screenshots/ai-route.png)

---

## 🚍 Transportation Services

![Transportation Services](docs/screenshots/transport-services.png)

---

## 🚌 Route List

![Routes](docs/screenshots/routes.png)

---

## 🚏 Bus Stop Details

![Bus Stop](docs/screenshots/bus-stop-detail.png)

---

## 🔐 Login

![Login](docs/screenshots/login.png)

---

## 📝 Register

![Register](docs/screenshots/register.png)

---

## 📊 Administration Dashboard

![Dashboard](docs/screenshots/dashboard.png)

---

# 📌 Roadmap

### Version 1.0

- Public transportation portal
- Administration panel
- Route management
- Bus management
- Driver management
- Bus stop management
- PostgreSQL integration

### Planned Features

- 🤖 AI-assisted dispatch recommendations
- 📍 Real-time vehicle tracking
- 📊 Passenger density analysis
- 📱 Mobile application
- 🌍 Multi-language support
- ☁ Cloud deployment
- REST API

---

# 👨‍💻 Developer

**Yunus Emre KUL**

Computer Engineering Student

GitHub:

https://github.com/EmreBEYS

---

# 📄 License

This project is licensed under the MIT License.
