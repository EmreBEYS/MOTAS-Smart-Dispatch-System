# 🚌 MOTAS Smart Dispatch System

A modern web-based public transportation management system developed as an educational and portfolio project.

> **Disclaimer**
>
> This project is an independent software project developed for educational and portfolio purposes.
> It is **not affiliated with, endorsed by, or developed by MOTAŞ**.

---

# 📖 Overview

MOTAS Smart Dispatch System is a web application designed to simplify the management of a city's public transportation network.

The project includes both a **public information portal** and a comprehensive **administration panel** for managing transportation operations.

---

# ✨ Features

## 🌐 Public Panel

- 🚌 Bus information
- 🚏 Bus stop information
- 🗺 Route information
- 📢 Announcements
- 📞 Contact page
- 🎒 Lost property application
- 👤 User Login
- 📝 User Registration

---

## 🔐 Administration Panel

- 📊 Dashboard
- 🚌 Bus Management
- 👨‍✈️ Driver Management
- 🚏 Bus Stop Management
- 🗺 Route Management
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

| Technology | Usage |
|------------|------|
| Python | Backend |
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
├── database
│   └── schema.sql
│
├── exports
│
├── static
│   ├── css
│   ├── image
│   └── js
│
├── templates
│   ├── admin
│   ├── pages
│   └── partials
│
├── app.py
├── config.py
├── requirements.txt
└── README.md
```

---

# 🗄 Database

The application uses **PostgreSQL**.

Database schema:

```
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

## Environment Variables

Create an `ai.env` file.

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

Screenshots will be added in future updates.

---

# 📌 Future Improvements

- 🤖 AI-assisted dispatch recommendations
- 📱 Mobile application
- 📡 Real-time vehicle tracking
- 📊 Passenger density analytics
- 📈 Statistical dashboard
- ☁ Cloud deployment
- 🔐 Advanced authentication
- 🌍 Multi-language support

---

# 👨‍💻 Developer

**Yunus Emre KUL**

Computer Engineering Student

GitHub

https://github.com/EmreBEYS

---

# ⭐ Project Status

Current Version

```
v1.0.0
```

Status

```
✅ Stable
```

---

# 📄 License

This project is released under the MIT License.
