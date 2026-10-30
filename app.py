import os
import uuid
import csv
import io
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, 
    flash, session, jsonify, Response
)
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db, init_db, log_audit

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Ensure database tables exist on startup
init_db()

# ----------------- Decorators -----------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Please log in to access the administrator panel.', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ----------------- Student / Public Routes -----------------
@app.route('/')
def index():
    conn = get_db()
    # Fetch active elections
    active_elections = conn.execute(
        "SELECT * FROM elections WHERE status = 'active' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template('index.html', active_elections=active_elections)

@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    conn = get_db()
    active_elections = conn.execute(
        "SELECT * FROM elections WHERE status = 'active' ORDER BY created_at DESC"
    ).fetchall()

    if request.method == 'POST':
        election_id = request.form.get('election_id')
        student_id = request.form.get('student_id', '').strip()
        access_code = request.form.get('access_code', '').strip()

        if not election_id or not student_id:
            flash('Please select an active election and enter your Student ID.', 'error')
            conn.close()
            return render_template('student_login.html', active_elections=active_elections)

        # Check if election is active
        election = conn.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
        if not election or election['status'] != 'active':
            flash('The selected election is not active or open for voting.', 'error')
            conn.close()
            return render_template('student_login.html', active_elections=active_elections)

        # Check student in database
        student = conn.execute("SELECT * FROM students WHERE student_id = ?", (student_id,)).fetchone()
        if not student:
            flash(f'Student ID "{student_id}" was not found in the voter registry. Please register first.', 'error')
            conn.close()
            return render_template('student_login.html', active_elections=active_elections)

        # Check access code if required
        if student['access_code'] and student['access_code'] != access_code:
            flash('Invalid Access PIN for this Student ID.', 'error')
            conn.close()
            return render_template('student_login.html', active_elections=active_elections)

        # Check if already voted
        has_voted = conn.execute(
            "SELECT id FROM election_voters WHERE election_id = ? AND student_id = ?",
            (election_id, student_id)
        ).fetchone()

        if has_voted:
            flash(f'Student {student_id} has already cast a ballot in "{election["title"]}". Duplicate voting is not permitted.', 'warning')
            conn.close()
            return render_template('student_login.html', active_elections=active_elections)

        conn.close()

        # Save to session and redirect to ballot
        session['student_id'] = student_id
        session['student_name'] = student['full_name']
        session['current_election_id'] = election_id
        flash(f'Identity verified! Welcome, {student["full_name"]}.', 'success')
        return redirect(url_for('ballot', election_id=election_id))

    conn.close()
    return render_template('student_login.html', active_elections=active_elections)

@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        full_name = request.form.get('full_name', '').strip()
        access_code = request.form.get('access_code', '').strip()

        if not student_id or not full_name:
            flash('Student ID and Full Name are required.', 'error')
            return render_template('student_register.html')

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO students (student_id, full_name, access_code) VALUES (?, ?, ?)",
                (student_id, full_name, access_code if access_code else None)
            )
            conn.commit()
            log_audit('STUDENT_REGISTER', f"New student registered: {student_id} ({full_name})")
            flash(f'Registration successful for {full_name} ({student_id})! You can now log in to vote.', 'success')
            conn.close()
            return redirect(url_for('student_login'))
        except Exception as e:
            conn.close()
            flash(f'Student ID "{student_id}" is already registered. Please log in directly.', 'warning')
            return redirect(url_for('student_login'))

    return render_template('student_register.html')

# Backwards compatibility endpoints
@app.route('/voter/login', methods=['POST'])
def voter_login():
    return student_login()

@app.route('/voter/register', methods=['POST'])
def voter_register():
    return student_register()

@app.route('/student/logout')
def student_logout():
    session.pop('student_id', None)
    session.pop('student_name', None)
    session.pop('current_election_id', None)
    flash('Student session ended.', 'info')
    return redirect(url_for('index'))

@app.route('/vote/<int:election_id>')
def ballot(election_id):
    if not session.get('student_id') or str(session.get('current_election_id')) != str(election_id):
        flash('Please verify your student credentials before accessing the ballot.', 'warning')
        return redirect(url_for('index'))

    conn = get_db()
    election = conn.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election or election['status'] != 'active':
        flash('This election is not currently open for voting.', 'error')
        conn.close()
        return redirect(url_for('index'))

    # Check if already voted
    already_voted = conn.execute(
        "SELECT id FROM election_voters WHERE election_id = ? AND student_id = ?",
        (election_id, session['student_id'])
    ).fetchone()
    if already_voted:
        flash('You have already voted in this election.', 'warning')
        conn.close()
        return redirect(url_for('index'))

    # Get positions and candidates
    positions = conn.execute(
        "SELECT * FROM positions WHERE election_id = ? ORDER BY display_order ASC, id ASC",
        (election_id,)
    ).fetchall()

    positions_list = []
    for pos in positions:
        cands = conn.execute(
            "SELECT * FROM candidates WHERE position_id = ? ORDER BY id ASC",
            (pos['id'],)
        ).fetchall()
        pos_dict = dict(pos)
        pos_dict['candidates'] = [dict(c) for c in cands]
        positions_list.append(pos_dict)

    conn.close()
    return render_template('vote.html', election=election, positions=positions_list)

@app.route('/vote/<int:election_id>/submit', methods=['POST'])
def submit_vote(election_id):
    student_id = session.get('student_id')
    if not student_id or str(session.get('current_election_id')) != str(election_id):
        flash('Session expired or unauthorized vote attempt.', 'error')
        return redirect(url_for('index'))

    conn = get_db()
    election = conn.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election or election['status'] != 'active':
        flash('This election is no longer active.', 'error')
        conn.close()
        return redirect(url_for('index'))

    # Double check duplicate vote
    has_voted = conn.execute(
        "SELECT id FROM election_voters WHERE election_id = ? AND student_id = ?",
        (election_id, student_id)
    ).fetchone()

    if has_voted:
        flash('You have already submitted a vote for this election.', 'error')
        conn.close()
        return redirect(url_for('index'))

    # Get positions
    positions = conn.execute("SELECT id FROM positions WHERE election_id = ?", (election_id,)).fetchall()
    
    # Generate cryptographic receipt code for student verification
    receipt_code = f"VOTE-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:4].upper()}"

    try:
        cur = conn.cursor()
        # Record voter participation
        cur.execute(
            "INSERT INTO election_voters (election_id, student_id) VALUES (?, ?)",
            (election_id, student_id)
        )

        # Record secret votes decoupled from student ID
        for pos in positions:
            cand_id = request.form.get(f"position_{pos['id']}")
            if cand_id:
                cur.execute(
                    "INSERT INTO votes (election_id, position_id, candidate_id, receipt_code) VALUES (?, ?, ?, ?)",
                    (election_id, pos['id'], cand_id, receipt_code)
                )

        conn.commit()
        log_audit('VOTE_CAST', f"Ballot cast in '{election['title']}' with Receipt: {receipt_code}")
    except Exception as e:
        conn.rollback()
        conn.close()
        flash('An error occurred while submitting your vote. Please try again.', 'error')
        return redirect(url_for('index'))

    conn.close()

    # Clear student voting session
    student_name = session.pop('student_name', 'Student')
    session.pop('student_id', None)
    session.pop('current_election_id', None)

    return render_template(
        'vote_success.html',
        receipt_code=receipt_code,
        student_id=student_id,
        election_title=election['title'],
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

# ----------------- Admin Routes -----------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = get_db()
        admin = conn.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
        conn.close()

        if admin and check_password_hash(admin['password_hash'], password):
            session['admin_logged_in'] = True
            session['admin_username'] = admin['username']
            log_audit('ADMIN_LOGIN', f"Admin '{username}' logged in.")
            flash('Successfully signed in to Admin Dashboard.', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials. Please try again.', 'error')

    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    username = session.get('admin_username', 'admin')
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    log_audit('ADMIN_LOGOUT', f"Admin '{username}' logged out.")
    flash('Logged out successfully.', 'info')
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    conn = get_db()
    elections = conn.execute("SELECT * FROM elections ORDER BY created_at DESC").fetchall()
    
    selected_id = request.args.get('election_id')
    current_election = None
    if selected_id:
        current_election = conn.execute("SELECT * FROM elections WHERE id = ?", (selected_id,)).fetchone()
    
    if not current_election and elections:
        current_election = elections[0]

    stats = {
        'total_students': 0,
        'total_voted': 0,
        'turnout_percent': 0
    }
    election_results = []

    # Get total registered students
    total_students = conn.execute("SELECT COUNT(*) as count FROM students").fetchone()['count']
    stats['total_students'] = total_students

    if current_election:
        voted_count = conn.execute(
            "SELECT COUNT(DISTINCT student_id) as count FROM election_voters WHERE election_id = ?",
            (current_election['id'],)
        ).fetchone()['count']
        stats['total_voted'] = voted_count
        stats['turnout_percent'] = round((voted_count / total_students * 100), 1) if total_students > 0 else 0

        # Build position tallies
        positions = conn.execute(
            "SELECT * FROM positions WHERE election_id = ? ORDER BY display_order ASC, id ASC",
            (current_election['id'],)
        ).fetchall()

        for pos in positions:
            total_pos_votes = conn.execute(
                "SELECT COUNT(*) as count FROM votes WHERE position_id = ?",
                (pos['id'],)
            ).fetchone()['count']

            candidates = conn.execute(
                "SELECT * FROM candidates WHERE position_id = ? ORDER BY id ASC",
                (pos['id'],)
            ).fetchall()

            cand_data = []
            max_votes = 0
            for c in candidates:
                cand_votes = conn.execute(
                    "SELECT COUNT(*) as count FROM votes WHERE candidate_id = ?",
                    (c['id'],)
                ).fetchone()['count']
                if cand_votes > max_votes:
                    max_votes = cand_votes
                
                percentage = round((cand_votes / total_pos_votes * 100), 1) if total_pos_votes > 0 else 0
                c_dict = dict(c)
                c_dict['votes'] = cand_votes
                c_dict['percentage'] = percentage
                cand_data.append(c_dict)

            pos_dict = dict(pos)
            pos_dict['total_position_votes'] = total_pos_votes
            pos_dict['candidates'] = cand_data
            pos_dict['max_votes'] = max_votes
            election_results.append(pos_dict)

    # Recent audit logs
    audit_logs = conn.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 15").fetchall()
    conn.close()

    return render_template(
        'admin_dashboard.html',
        elections=elections,
        current_election=current_election,
        stats=stats,
        election_results=election_results,
        audit_logs=audit_logs
    )

@app.route('/api/admin/stats/<int:election_id>')
@admin_required
def api_admin_stats(election_id):
    conn = get_db()
    total_students = conn.execute("SELECT COUNT(*) as count FROM students").fetchone()['count']
    voted_count = conn.execute(
        "SELECT COUNT(DISTINCT student_id) as count FROM election_voters WHERE election_id = ?",
        (election_id,)
    ).fetchone()['count']
    
    turnout = round((voted_count / total_students * 100), 1) if total_students > 0 else 0

    positions = conn.execute(
        "SELECT * FROM positions WHERE election_id = ? ORDER BY display_order ASC, id ASC",
        (election_id,)
    ).fetchall()

    pos_list = []
    for pos in positions:
        total_pos_votes = conn.execute(
            "SELECT COUNT(*) as count FROM votes WHERE position_id = ?",
            (pos['id'],)
        ).fetchone()['count']

        candidates = conn.execute(
            "SELECT * FROM candidates WHERE position_id = ? ORDER BY id ASC",
            (pos['id'],)
        ).fetchall()

        cand_list = []
        max_votes = 0
        for c in candidates:
            v_count = conn.execute(
                "SELECT COUNT(*) as count FROM votes WHERE candidate_id = ?",
                (c['id'],)
            ).fetchone()['count']
            if v_count > max_votes:
                max_votes = v_count
            pct = round((v_count / total_pos_votes * 100), 1) if total_pos_votes > 0 else 0
            cand_list.append({
                'id': c['id'],
                'name': c['name'],
                'votes': v_count,
                'percentage': pct
            })

        pos_list.append({
            'id': pos['id'],
            'title': pos['title'],
            'total_position_votes': total_pos_votes,
            'max_votes': max_votes,
            'candidates': cand_list
        })

    logs = conn.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 15").fetchall()
    conn.close()

    return jsonify({
        'status': 'ok',
        'stats': {
            'total_students': total_students,
            'total_voted': voted_count,
            'turnout_percent': turnout
        },
        'positions': pos_list,
        'logs': [dict(log) for log in logs]
    })

# ----------------- Elections & Candidates Management -----------------
@app.route('/admin/elections')
@admin_required
def admin_elections():
    conn = get_db()
    elections = conn.execute("SELECT * FROM elections ORDER BY created_at DESC").fetchall()

    elections_list = []
    for el in elections:
        el_dict = dict(el)
        positions = conn.execute(
            "SELECT * FROM positions WHERE election_id = ? ORDER BY display_order ASC, id ASC",
            (el['id'],)
        ).fetchall()

        pos_list = []
        for pos in positions:
            p_dict = dict(pos)
            cands = conn.execute("SELECT * FROM candidates WHERE position_id = ?", (pos['id'],)).fetchall()
            p_dict['candidates'] = [dict(c) for c in cands]
            pos_list.append(p_dict)

        el_dict['positions'] = pos_list
        elections_list.append(el_dict)

    conn.close()
    return render_template('admin_elections.html', elections=elections_list)

@app.route('/admin/elections/create', methods=['POST'])
@admin_required
def create_election():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    status = request.form.get('status', 'active')

    if not title:
        flash('Election title is required.', 'error')
        return redirect(url_for('admin_elections'))

    conn = get_db()
    conn.execute(
        "INSERT INTO elections (title, description, status) VALUES (?, ?, ?)",
        (title, description, status)
    )
    conn.commit()
    conn.close()
    log_audit('ELECTION_CREATE', f"Created election '{title}' (Status: {status})")
    flash(f'Election "{title}" created successfully.', 'success')
    return redirect(url_for('admin_elections'))

@app.route('/admin/elections/<int:election_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_election_status(election_id):
    new_status = request.form.get('status')
    if new_status in ['draft', 'active', 'paused', 'closed']:
        conn = get_db()
        conn.execute("UPDATE elections SET status = ? WHERE id = ?", (new_status, election_id))
        conn.commit()
        conn.close()
        log_audit('ELECTION_STATUS', f"Election #{election_id} status changed to '{new_status}'")
        flash(f'Election status updated to {new_status}.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/admin/elections/<int:election_id>/delete', methods=['POST'])
@admin_required
def delete_election(election_id):
    conn = get_db()
    election = conn.execute("SELECT title FROM elections WHERE id = ?", (election_id,)).fetchone()
    if election:
        title = election['title']
        conn.execute("DELETE FROM elections WHERE id = ?", (election_id,))
        conn.commit()
        log_audit('ELECTION_DELETE', f"Deleted election '{title}' and all associated records.")
        flash(f'Election "{title}" deleted.', 'info')
    conn.close()
    return redirect(url_for('admin_elections'))

@app.route('/admin/positions/add', methods=['POST'])
@admin_required
def add_position():
    election_id = request.form.get('election_id')
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()

    if not election_id or not title:
        flash('Position title is required.', 'error')
        return redirect(url_for('admin_elections'))

    conn = get_db()
    conn.execute(
        "INSERT INTO positions (election_id, title, description) VALUES (?, ?, ?)",
        (election_id, title, description)
    )
    conn.commit()
    conn.close()
    log_audit('POSITION_ADD', f"Added position '{title}' to election #{election_id}")
    flash(f'Position "{title}" added successfully.', 'success')
    return redirect(url_for('admin_elections'))

@app.route('/admin/positions/<int:position_id>/delete', methods=['POST'])
@admin_required
def delete_position(position_id):
    conn = get_db()
    conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
    conn.commit()
    conn.close()
    log_audit('POSITION_DELETE', f"Deleted position #{position_id}")
    flash('Position deleted.', 'info')
    return redirect(url_for('admin_elections'))

@app.route('/admin/candidates/add', methods=['POST'])
@admin_required
def add_candidate():
    position_id = request.form.get('position_id')
    name = request.form.get('name', '').strip()
    manifesto = request.form.get('manifesto', '').strip()
    photo_url = request.form.get('photo_url', '').strip()

    if not position_id or not name:
        flash('Candidate name is required.', 'error')
        return redirect(url_for('admin_elections'))

    conn = get_db()
    conn.execute(
        "INSERT INTO candidates (position_id, name, manifesto, photo_url) VALUES (?, ?, ?, ?)",
        (position_id, name, manifesto, photo_url if photo_url else None)
    )
    conn.commit()
    conn.close()
    log_audit('CANDIDATE_ADD', f"Added candidate '{name}' to position #{position_id}")
    flash(f'Candidate "{name}" added.', 'success')
    return redirect(url_for('admin_elections'))

@app.route('/admin/candidates/<int:candidate_id>/delete', methods=['POST'])
@admin_required
def delete_candidate(candidate_id):
    conn = get_db()
    conn.execute("DELETE FROM candidates WHERE id = ?", (candidate_id,))
    conn.commit()
    conn.close()
    log_audit('CANDIDATE_DELETE', f"Deleted candidate #{candidate_id}")
    flash('Candidate removed.', 'info')
    return redirect(url_for('admin_elections'))

# ----------------- Student Voter Registry Management -----------------
@app.route('/admin/students')
@admin_required
def admin_students():
    conn = get_db()
    students = conn.execute("SELECT * FROM students ORDER BY registered_at DESC").fetchall()
    
    students_list = []
    for s in students:
        s_dict = dict(s)
        # Check how many elections voted in
        voted_count = conn.execute(
            "SELECT COUNT(*) as count FROM election_voters WHERE student_id = ?",
            (s['student_id'],)
        ).fetchone()['count']
        s_dict['voted_count'] = voted_count
        students_list.append(s_dict)

    conn.close()
    return render_template('admin_students.html', students=students_list)

@app.route('/admin/students/add', methods=['POST'])
@admin_required
def add_student():
    student_id = request.form.get('student_id', '').strip()
    full_name = request.form.get('full_name', '').strip()
    access_code = request.form.get('access_code', '').strip()

    if not student_id or not full_name:
        flash('Student ID and Full Name are required.', 'error')
        return redirect(url_for('admin_students'))

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO students (student_id, full_name, access_code) VALUES (?, ?, ?)",
            (student_id, full_name, access_code if access_code else None)
        )
        conn.commit()
        log_audit('STUDENT_ADD', f"Admin added student: {student_id} ({full_name})")
        flash(f'Student "{full_name}" ({student_id}) added to database.', 'success')
    except Exception as e:
        flash(f'Student ID "{student_id}" is already registered.', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin_students'))

@app.route('/admin/students/bulk', methods=['POST'])
@admin_required
def bulk_add_students():
    bulk_data = request.form.get('bulk_data', '').strip()
    if not bulk_data:
        flash('No data provided.', 'error')
        return redirect(url_for('admin_students'))

    lines = bulk_data.split('\n')
    imported_count = 0
    conn = get_db()

    for line in lines:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 2:
            s_id = parts[0]
            s_name = parts[1]
            s_pin = parts[2] if len(parts) > 2 else None
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO students (student_id, full_name, access_code) VALUES (?, ?, ?)",
                    (s_id, s_name, s_pin)
                )
                imported_count += 1
            except:
                pass

    conn.commit()
    conn.close()
    log_audit('BULK_IMPORT', f"Imported {imported_count} student voter records.")
    flash(f'Successfully imported {imported_count} student records.', 'success')
    return redirect(url_for('admin_students'))

@app.route('/admin/students/<student_id>/delete', methods=['POST'])
@admin_required
def delete_student(student_id):
    conn = get_db()
    conn.execute("DELETE FROM students WHERE student_id = ?", (student_id,))
    conn.execute("DELETE FROM election_voters WHERE student_id = ?", (student_id,))
    conn.commit()
    conn.close()
    log_audit('STUDENT_DELETE', f"Admin removed student {student_id}")
    flash(f'Student {student_id} removed.', 'info')
    return redirect(url_for('admin_students'))

@app.route('/admin/elections/<int:election_id>/export-csv')
@admin_required
def export_results(election_id):
    conn = get_db()
    election = conn.execute("SELECT * FROM elections WHERE id = ?", (election_id,)).fetchone()
    if not election:
        conn.close()
        flash('Election not found.', 'error')
        return redirect(url_for('admin_dashboard'))

    positions = conn.execute("SELECT * FROM positions WHERE election_id = ?", (election_id,)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Election Title", election['title']])
    writer.writerow(["Generated At", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow([])
    writer.writerow(["Position", "Candidate Name", "Vote Count", "Vote Percentage"])

    for pos in positions:
        total_pos_votes = conn.execute("SELECT COUNT(*) as c FROM votes WHERE position_id = ?", (pos['id'],)).fetchone()['c']
        candidates = conn.execute("SELECT * FROM candidates WHERE position_id = ?", (pos['id'],)).fetchall()
        for c in candidates:
            cand_votes = conn.execute("SELECT COUNT(*) as c FROM votes WHERE candidate_id = ?", (c['id'],)).fetchone()['c']
            pct = round((cand_votes / total_pos_votes * 100), 2) if total_pos_votes > 0 else 0
            writer.writerow([pos['title'], c['name'], cand_votes, f"{pct}%"])

    conn.close()
    csv_data = output.getvalue()
    filename = f"election_{election_id}_results.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )

if __name__ == '__main__':
    print("=" * 60)
    print(" Student Voting System Server Starting")
    print(" Server Running at: http://127.0.0.1:5000")
    print(" Admin Login:       http://127.0.0.1:5000/admin/login")
    print(" Admin User: admin  | Password: admin123")
    print("=" * 60)
    app.run(host='127.0.0.1', port=5000, debug=True)
