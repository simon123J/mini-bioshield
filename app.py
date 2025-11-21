import sqlite3
from datetime import datetime
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    g,
    flash,
)

app = Flask(__name__)
app.secret_key = "change_this_secret_key_later"  # needed for sessions

DB_NAME = "health.db"


# ---------- database helpers ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_NAME)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()

    # users table (simple: username + password)
    db.execute(
        """
        create table if not exists users (
            id integer primary key autoincrement,
            username text unique not null,
            password text not null,
            created_at text not null
        );
        """
    )

    # bmi logs (per user)
    db.execute(
        """
        create table if not exists bmi_logs (
            id integer primary key autoincrement,
            user_id integer not null,
            created_at text not null,
            weight real not null,
            height real not null,
            bmi real not null,
            category text not null
        );
        """
    )

    # water logs (per user)
    db.execute(
        """
        create table if not exists water_logs (
            id integer primary key autoincrement,
            user_id integer not null,
            created_at text not null,
            cups real not null
        );
        """
    )

    # sleep logs (per user)
    db.execute(
        """
        create table if not exists sleep_logs (
            id integer primary key autoincrement,
            user_id integer not null,
            created_at text not null,
            hours real not null
        );
        """
    )

    # calories logs (per user)
    db.execute(
        """
        create table if not exists calories_logs (
            id integer primary key autoincrement,
            user_id integer not null,
            created_at text not null,
            target real not null,
            actual real not null,
            difference real not null
        );
        """
    )

    db.commit()


@app.before_request
def before_request():
    init_db()


# ---------- auth helpers ----------

def logged_in():
    return "user_id" in session


def current_user():
    if not logged_in():
        return None
    db = get_db()
    user = db.execute(
        "select * from users where id = ?",
        (session["user_id"],),
    ).fetchone()
    return user


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not logged_in():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


# ---------- routes: auth ----------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("please fill out all fields")
            return render_template("register.html")

        db = get_db()
        # check if username exists
        existing = db.execute(
            "select id from users where username = ?",
            (username,),
        ).fetchone()

        if existing:
            flash("username already in use")
            return render_template("register.html")

        db.execute(
            "insert into users (username, password, created_at) values (?, ?, ?)",
            (username, password, datetime.utcnow().isoformat()),
        )
        db.commit()

        flash("account created, you can log in now")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        db = get_db()
        user = db.execute(
            "select * from users where username = ?",
            (username,),
        ).fetchone()

        if user and user["password"] == password:
            session["user_id"] = user["id"]
            flash("logged in successfully")
            return redirect(url_for("home"))
        else:
            flash("wrong username or password")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("you have been logged out")
    return redirect(url_for("login"))


# ---------- routes: main + trackers ----------

@app.route("/")
@login_required
def home():
    user = current_user()
    return render_template("home.html", user=user)


@app.route("/bmi", methods=["GET", "POST"])
@login_required
def bmi():
    db = get_db()
    bmi_value = None
    category = None
    error = None
    user_id = session["user_id"]

    if request.method == "POST":
        try:
            weight = float(request.form.get("weight", 0))
            height = float(request.form.get("height", 0))

            if weight <= 0 or height <= 0:
                error = "please enter numbers greater than zero."
            else:
                # using pounds and inches
                bmi_value = round((weight / (height ** 2)) * 703, 1)

                if bmi_value < 18.5:
                    category = "underweight"
                elif bmi_value < 25:
                    category = "normal"
                elif bmi_value < 30:
                    category = "overweight"
                else:
                    category = "obese"

                # save to database with user_id
                db.execute(
                    """
                    insert into bmi_logs (user_id, created_at, weight, height, bmi, category)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, datetime.utcnow().isoformat(), weight, height, bmi_value, category),
                )
                db.commit()

        except ValueError:
            error = "please enter valid numbers."

    # load last 20 bmi logs for this user
    entries = db.execute(
        """
        select created_at, weight, height, bmi, category
        from bmi_logs
        where user_id = ?
        order by id desc
        limit 20
        """,
        (user_id,),
    ).fetchall()

    return render_template("bmi.html", bmi=bmi_value, category=category, error=error, entries=entries)


@app.route("/water", methods=["GET", "POST"])
@login_required
def water():
    db = get_db()
    daily_cups = None
    message = None
    user_id = session["user_id"]

    if request.method == "POST":
        try:
            daily_cups = float(request.form.get("cups", 0))

            if daily_cups < 0:
                message = "water amount cannot be negative."
            elif daily_cups < 8:
                message = "you drank less than 8 cups. try to drink more."
            else:
                message = "nice! you hit your 8 cups or more for today."

            # save to database if value is valid
            if daily_cups >= 0:
                db.execute(
                    """
                    insert into water_logs (user_id, created_at, cups)
                    values (?, ?, ?)
                    """,
                    (user_id, datetime.utcnow().isoformat(), daily_cups),
                )
                db.commit()

        except ValueError:
            message = "please enter a number."

    entries = db.execute(
        """
        select created_at, cups
        from water_logs
        where user_id = ?
        order by id desc
        limit 20
        """,
        (user_id,),
    ).fetchall()

    return render_template("water.html", daily_cups=daily_cups, message=message, entries=entries)


@app.route("/sleep", methods=["GET", "POST"])
@login_required
def sleep():
    db = get_db()
    hours = None
    message = None
    user_id = session["user_id"]

    if request.method == "POST":
        try:
            hours = float(request.form.get("hours", 0))

            if hours < 0:
                message = "sleep time cannot be negative."
            elif hours < 7:
                message = "you slept less than 7 hours. try to rest more."
            elif hours <= 9:
                message = "nice, you are in the 7–9 hours range."
            else:
                message = "you slept more than 9 hours. listen to your body but watch oversleeping."

            if hours >= 0:
                db.execute(
                    """
                    insert into sleep_logs (user_id, created_at, hours)
                    values (?, ?, ?)
                    """,
                    (user_id, datetime.utcnow().isoformat(), hours),
                )
                db.commit()

        except ValueError:
            message = "please enter a number."

    entries = db.execute(
        """
        select created_at, hours
        from sleep_logs
        where user_id = ?
        order by id desc
        limit 20
        """,
        (user_id,),
    ).fetchall()

    return render_template("sleep.html", hours=hours, message=message, entries=entries)


@app.route("/calories", methods=["GET", "POST"])
@login_required
def calories():
    db = get_db()
    target = None
    actual = None
    difference = None
    message = None
    user_id = session["user_id"]

    if request.method == "POST":
        try:
            target = float(request.form.get("target", 0))
            actual = float(request.form.get("actual", 0))

            if target < 0 or actual < 0:
                message = "calories cannot be negative."
            else:
                difference = actual - target
                if difference > 0:
                    message = f"you ate about {difference:.0f} calories over your target."
                elif difference < 0:
                    message = f"you are about {abs(difference):.0f} calories under your target."
                else:
                    message = "you hit your target exactly. nice!"

                # save to database
                db.execute(
                    """
                    insert into calories_logs (user_id, created_at, target, actual, difference)
                    values (?, ?, ?, ?, ?)
                    """,
                    (user_id, datetime.utcnow().isoformat(), target, actual, difference),
                )
                db.commit()

        except ValueError:
            message = "please enter numbers."

    entries = db.execute(
        """
        select created_at, target, actual, difference
        from calories_logs
        where user_id = ?
        order by id desc
        limit 20
        """,
        (user_id,),
    ).fetchall()

    return render_template(
        "calories.html",
        target=target,
        actual=actual,
        difference=difference,
        message=message,
        entries=entries,
    )


if __name__ == "__main__":
    app.run(debug=True)


