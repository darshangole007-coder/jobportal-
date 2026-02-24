import os
import sqlite3
from datetime import datetime
from flask import (Flask, render_template, request, redirect, url_for, flash, session, g, jsonify)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "jobportal.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = "change_this_secret_for_prod"

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


app.teardown_appcontext(close_db)


def init_db():
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            email TEXT,
            message TEXT,
            applied_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_type TEXT NOT NULL,  
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    db.commit()


with app.app_context():
    init_db()


def create_notification(user_type, message):
    db = get_db()
    db.execute(
        "INSERT INTO notifications (user_type, message, is_read, created_at) VALUES (?, ?, 0, ?)",
        (user_type, message, datetime.utcnow().isoformat())
    )
    db.commit()


def unread_counts():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM notifications WHERE user_type='hr' AND is_read=0")
    hr_unread = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM notifications WHERE user_type='employee' AND is_read=0")
    emp_unread = cur.fetchone()[0]
    return {"hr_unread": hr_unread, "emp_unread": emp_unread}


@app.route("/login_hr", methods=["GET", "POST"])
def login_hr():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        # demo credentials
        if username == "hr" and password == "hr123":
            session["hr_logged_in"] = True
            flash("Logged in as HR", "success")
            return redirect(url_for("hr_dashboard"))
        flash("Invalid HR credentials", "danger")
    return render_template("login_hr.html", unread=unread_counts())


@app.route("/hr_dashboard")
def hr_dashboard():
    if not session.get("hr_logged_in"):
        return redirect(url_for("login_hr"))
    db = get_db()
    jobs = db.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
    stats = {
        "jobs_count": len(jobs),
        "applications_count": db.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    }
    return render_template("hr_dashboard.html", jobs=jobs, stats=stats, unread=unread_counts())


@app.route("/hr_add_job", methods=["GET", "POST"])
def hr_add_job():
    if not session.get("hr_logged_in"):
        return redirect(url_for("login_hr"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title or not description:
            flash("All fields are required", "warning")
            return render_template("hr_add_job.html", unread=unread_counts())
        db = get_db()
        db.execute(
            "INSERT INTO jobs (title, description, created_at) VALUES (?, ?, ?)",
            (title, description, datetime.utcnow().isoformat())
        )
        db.commit()
        # notify employees
        create_notification("employee", f"New job posted: {title}")
        flash("Job posted and employees notified", "success")
        return redirect(url_for("hr_dashboard"))
    return render_template("hr_add_job.html", unread=unread_counts())


@app.route("/hr_notifications")
def hr_notifications():
    if not session.get("hr_logged_in"):
        return redirect(url_for("login_hr"))
    db = get_db()
    notes = db.execute("SELECT * FROM notifications WHERE user_type='hr' ORDER BY id DESC").fetchall()
    return render_template("hr_notifications.html", notifications=notes, unread=unread_counts())


@app.route("/hr_applications")
def hr_applications():
    if not session.get("hr_logged_in"):
        return redirect(url_for("login_hr"))
    db = get_db()
    apps = db.execute(
        "SELECT a.*, j.title as job_title FROM applications a JOIN jobs j ON a.job_id = j.id ORDER BY a.id DESC"
    ).fetchall()
    return render_template("hr_applications.html", applications=apps, unread=unread_counts())


@app.route("/hr_logout")
def hr_logout():
    session.pop("hr_logged_in", None)
    flash("Logged out (HR)", "info")
    return redirect(url_for("login_hr"))


@app.route("/", methods=["GET", "POST"])
@app.route("/login_employee", methods=["GET", "POST"])
def login_employee():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Enter your name", "warning")
            return render_template("login_employee.html", unread=unread_counts())
        session["employee_name"] = name
        flash(f"Welcome {name}", "success")
        return redirect(url_for("employee_home"))
    return render_template("login_employee.html", unread=unread_counts())


@app.route("/employee_home")
def employee_home():
    if "employee_name" not in session:
        return redirect(url_for("login_employee"))
    db = get_db()
    jobs = db.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
    return render_template("employee_home.html", jobs=jobs, name=session["employee_name"], unread=unread_counts())


@app.route("/add_skills", methods=["GET", "POST"])
def add_skills():
    if "employee_name" not in session:
        return redirect(url_for("login_employee"))
    if request.method == "POST":
        # simple demo: do not store skills permanently in this simplified app
        flash("Skills saved (demo)", "success")
        return redirect(url_for("employee_home"))
    return render_template("add_skills.html", unread=unread_counts())


@app.route("/apply/<int:job_id>", methods=["GET", "POST"])
def apply(job_id):
    if "employee_name" not in session:
        return redirect(url_for("login_employee"))
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        flash("Job not found", "danger")
        return redirect(url_for("employee_home"))
    if request.method == "POST":
        name = session["employee_name"]
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()
        db.execute(
            "INSERT INTO applications (job_id, name, email, message, applied_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, name, email, message, datetime.utcnow().isoformat())
        )
        db.commit()
        create_notification("hr", f"{name} applied for '{job['title']}'")
        flash("Application submitted. HR notified.", "success")
        return redirect(url_for("confirmation"))
    return render_template("apply.html", job=job, unread=unread_counts())


@app.route("/employee_notifications")
def employee_notifications():
    if "employee_name" not in session:
        return redirect(url_for("login_employee"))
    db = get_db()
    notes = db.execute("SELECT * FROM notifications WHERE user_type='employee' ORDER BY id DESC").fetchall()
    return render_template("employee_notifications.html", notifications=notes, unread=unread_counts())


@app.route("/employee_logout")
def employee_logout():
    session.pop("employee_name", None)
    flash("Logged out (Employee)", "info")
    return redirect(url_for("login_employee"))


@app.route("/api/hr_unread_notifications")
def api_hr_unread_notifications():
    db = get_db()
    notes = db.execute("SELECT * FROM notifications WHERE user_type='hr' AND is_read=0 ORDER BY id DESC").fetchall()
    # return list of dicts
    result = [dict(n) for n in notes]
    return jsonify(result)


@app.route("/api/employee_unread_notifications")
def api_employee_unread_notifications():
    db = get_db()
    notes = db.execute("SELECT * FROM notifications WHERE user_type='employee' AND is_read=0 ORDER BY id DESC").fetchall()
    result = [dict(n) for n in notes]
    return jsonify(result)


@app.route("/api/notifications/mark_read/<int:notif_id>", methods=["POST"])
def api_mark_read(notif_id):
    db = get_db()
    db.execute("UPDATE notifications SET is_read=1 WHERE id = ?", (notif_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/confirmation")
def confirmation():
    return render_template("confirmation.html", unread=unread_counts())


if __name__ == "__main__":
    app.run(debug=True, port=3000)
