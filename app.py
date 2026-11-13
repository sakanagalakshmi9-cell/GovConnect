
from datetime import date
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
import sqlite3
import os

from functools import wraps
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)


# ----------------------------------
# FLASK CONFIGURATION
# ----------------------------------

app = Flask(__name__)

app.secret_key = os.environ.get("GOVCONNECT_SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "Please set the GOVCONNECT_SECRET_KEY environment variable."
    )

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "jobs.db")


# ----------------------------------
# DATABASE CONNECTION
# ----------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ----------------------------------
# DATABASE INITIALIZATION
# ----------------------------------

def init_db():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            department TEXT NOT NULL,
            qualification TEXT NOT NULL,
            last_date TEXT NOT NULL,
            link TEXT,
            status TEXT DEFAULT 'Not Applied',
            min_age INTEGER DEFAULT 18,
            max_age INTEGER DEFAULT 30,
            salary TEXT DEFAULT 'Not Specified',
            vacancies INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # Add missing columns to older databases
    existing_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(jobs)")
    }

    new_columns = {
        "min_age": "INTEGER DEFAULT 18",
        "max_age": "INTEGER DEFAULT 30",
        "salary": "TEXT DEFAULT 'Not Specified'",
        "vacancies": "INTEGER DEFAULT 0"
    }

    for column, data_type in new_columns.items():

        if column not in existing_columns:

            conn.execute(
                f"ALTER TABLE jobs ADD COLUMN {column} {data_type}"
            )

    # Applications table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            applied_date TEXT NOT NULL,
            status TEXT DEFAULT 'Applied',
            UNIQUE(user_id, job_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )
    """)

    conn.commit()
    conn.close()


# ----------------------------------
# LOGIN REQUIRED DECORATOR
# ----------------------------------

def login_required(route_function):

    @wraps(route_function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        return route_function(*args, **kwargs)

    return wrapper


# ----------------------------------
# USER REGISTRATION
# ----------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        conn = get_db()

        try:

            conn.execute("""
                INSERT INTO users (name, email, password)
                VALUES (?, ?, ?)
            """, (name, email, hashed_password))

            conn.commit()

            flash("Registration successful! Please login.")

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            flash("This email is already registered.")

        finally:
            conn.close()

    return render_template("register.html")


# ----------------------------------
# USER LOGIN
# ----------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(user["password"], password):

            session.clear()

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]

            return redirect(url_for("home"))

        flash("Invalid email or password.")

    return render_template("login.html")


# ----------------------------------
# USER LOGOUT
# ----------------------------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# ----------------------------------
# HOME PAGE
# ----------------------------------

@app.route("/")
@login_required
def home():

    conn = get_db()

    jobs = conn.execute("""
        SELECT * FROM jobs
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "index.html",
        jobs=jobs,
        checked=False,
        eligible_jobs=[]
    )


# ----------------------------------
# JOB ELIGIBILITY CHECKER
# ----------------------------------

@app.route("/check_eligibility", methods=["POST"])
@login_required
def check_eligibility():

    try:
        age = int(request.form.get("age", ""))
    except ValueError:
        flash("Please enter a valid age.")
        return redirect(url_for("home"))

    qualification = request.form.get("qualification", "").strip()

    if age < 18 or age > 100 or not qualification:
        flash("Please enter valid eligibility details.")
        return redirect(url_for("home"))

    conn = get_db()

    all_jobs = conn.execute("""
        SELECT * FROM jobs
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    eligible_jobs = []

    qualification_levels = {
        "10th pass": 1,
        "intermediate": 2,
        "any degree": 3,
        "b.tech": 3,
        "post graduation": 4
    }

    user_level = qualification_levels.get(qualification.lower())

    for job in all_jobs:

        required = job["qualification"].strip().lower()
        required_level = qualification_levels.get(required)

        age_eligible = (
            job["min_age"] <= age <= job["max_age"]
        )

        if required_level is not None and user_level is not None:
            qualification_eligible = user_level >= required_level
        else:
            qualification_eligible = qualification.lower() == required

        if age_eligible and qualification_eligible:
            eligible_jobs.append(job)

    return render_template(
        "index.html",
        jobs=all_jobs,
        eligible_jobs=eligible_jobs,
        checked=True
    )


# ----------------------------------
# APPLY / SAVE JOB
# ----------------------------------

@app.route("/apply/<int:job_id>", methods=["POST"])
@login_required
def apply_job(job_id):

    conn = get_db()

    job = conn.execute(
        "SELECT * FROM jobs WHERE id = ?",
        (job_id,)
    ).fetchone()

    if not job:

        conn.close()

        flash("Job not found.")

        return redirect(url_for("home"))

    try:

        conn.execute("""
            INSERT INTO applications
            (user_id, job_id, applied_date, status)
            VALUES (?, ?, ?, 'Saved')
        """, (
            session["user_id"],
            job_id,
            date.today().isoformat()
        ))

        conn.commit()

        flash(
            "Job saved to My Applications! "
            "Complete your application on the official website."
        )

    except sqlite3.IntegrityError:

        flash("You have already saved this job.")

    finally:
        conn.close()

    return redirect(url_for("my_applications"))


# ----------------------------------
# MY APPLICATIONS
# ----------------------------------

@app.route("/my-applications")
@login_required
def my_applications():

    conn = get_db()

    applications = conn.execute("""
        SELECT
            applications.*,
            jobs.title,
            jobs.department,
            jobs.last_date,
            jobs.link

        FROM applications

        JOIN jobs
        ON applications.job_id = jobs.id

        WHERE applications.user_id = ?

        ORDER BY applications.id DESC
    """, (session["user_id"],)).fetchall()

    conn.close()

    return render_template(
        "my_applications.html",
        applications=applications
    )


# ----------------------------------
# RUN APPLICATION
# ----------------------------------

init_db()

if __name__ == "__main__":
    app.run(debug=False)