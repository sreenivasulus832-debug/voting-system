# Student Electronic Voting System

A secure, modern, full-stack student voting web application with zero hardcoded election names or voter data, featuring an administrative real-time voting monitor and persistent SQLite database storage.

---

## 🌟 Key Features

1. **No Hardcoded Election or Student Data**
   - The system starts with an empty canvas. All election titles, candidate positions, candidate names, manifestos, and student records are configured dynamically through the Admin Portal.
   - Self-registration is also supported for students on the voter portal.

2. **Secret Ballot & Voter Integrity**
   - **One Student, One Vote**: Checks against the `election_voters` table prevent students from voting multiple times in the same election.
   - **Anonymized Ballots**: Votes in the `votes` table are decoupled from student IDs to preserve total voting privacy.
   - **Cryptographic Audit Receipt**: After voting, students receive a verifiable ballot hash (e.g. `VOTE-A1B2C3D4-E5F6`) and can print their digital receipt.

3. **Live Admin Monitoring & Real-time Tally Dashboard**
   - **Telemetry Cards**: Live registered student counts, total votes cast, turnout percentage, and election status.
   - **Dynamic Bar Visualizations**: Real-time percentage bars and vote tallies per position/candidate.
   - **Auto-Syncing**: Uses live polling (every 4 seconds) to update counts and leading candidate crown badges automatically.
   - **Audit Trail Feed**: Real-time log of administrative actions, voter logins, and votes cast.
   - **One-Click Controls**: Start, Pause, or Conclude elections on the fly.
   - **CSV Export**: Download complete election outcome reports.

4. **Database-Driven Architecture**
   - Driven by **SQLite3** (`voting.db`) with foreign key constraints, cascading deletes, and indexed tables:
     - `admins`: Administrator login credentials (hashed passwords via `werkzeug.security`).
     - `elections`: Configurable election records.
     - `positions`: Roles or offices up for election (e.g. President, Secretary).
     - `candidates`: Contenders with bio/manifesto and optional photo.
     - `students`: Registered student roll with optional security PINs.
     - `election_voters`: Duplicate-voting prevention records.
     - `votes`: Anonymous secret ballots with receipt tokens.
     - `audit_logs`: Detailed time-stamped system event history.

---

## 🚀 Getting Started

### 1. Requirements
- Python 3.7+ installed.
- Flask (already installed).

### 2. Run the Application
Open a terminal in the project directory and run:
```bash
python app.py
```

Open your browser and navigate to:
- **Student Login Page**: [http://127.0.0.1:5000/student/login](http://127.0.0.1:5000/student/login)
- **Student Registration Page**: [http://127.0.0.1:5000/student/register](http://127.0.0.1:5000/student/register)
- **Home / Portal Gateway**: [http://127.0.0.1:5000](http://127.0.0.1:5000)
- **Admin Portal**: [http://127.0.0.1:5000/admin/login](http://127.0.0.1:5000/admin/login)

### 3. Default Admin Credentials
- **Username:** `admin`
- **Password:** `admin123`

---

## 📋 Typical Workflow

1. **Log in to the Admin Portal** with `admin / admin123`.
2. Go to **"Elections & Candidates"** -> Click **"Create New Election"** (e.g. specify any title, guidelines, and set status to Active).
3. Click **"Add Position"** (e.g. "President", "Treasurer", "Sports Representative").
4. Under each position, click **"Add Candidate"** (e.g. name, manifesto, photo URL).
5. Go to **"Student Voters"** -> Add students individually or use **"Bulk Import"** (`ID, Full Name, PIN`).
6. Students visit [http://127.0.0.1:5000](http://127.0.0.1:5000), enter their Student ID, vote for their preferred candidates, and receive a secure receipt token.
7. Switch to **"Live Monitor"** on the Admin dashboard to observe real-time vote tallies, turnout %, and audit logs.
