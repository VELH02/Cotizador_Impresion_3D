import json
import os
import platform
import sqlite3
import subprocess
import tempfile

from datetime import (
    datetime,
    timezone
)

from decimal import Decimal
from functools import wraps

from dotenv import load_dotenv

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for
)

from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user
)

from flask_wtf.csrf import (
    CSRFProtect
)

from sqlalchemy import (
    func,
    or_
)

from zoneinfo import (
    ZoneInfo,
    ZoneInfoNotFoundError
)

from models import (
    db,
    User,
    AppSetting,
    FilamentPreset,
    MarginPreset,
    Quote,
    AuditLog
)

from quote_logic import (
    dec,
    money,
    save_quote_from_payload
)

from pdf_utils import (
    create_quote_pdf
)

from time_utils import (
    DEFAULT_TIMEZONE,
    get_timezone_name,
    get_timezone,
    format_local_datetime
)


# ============================================================
# CONFIGURACIÓN
# ============================================================

load_dotenv()


app = Flask(
    __name__,
    instance_relative_config=True
)


os.makedirs(
    app.instance_path,
    exist_ok=True
)


app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "CAMBIAR-ESTA-CLAVE"
)


DATABASE_PATH = os.path.join(
    app.instance_path,
    "quotes.db"
)


database_uri_path = (
    DATABASE_PATH.replace(
        "\\",
        "/"
    )
)


app.config[
    "SQLALCHEMY_DATABASE_URI"
] = (
    f"sqlite:///{database_uri_path}"
)


app.config[
    "SQLALCHEMY_TRACK_MODIFICATIONS"
] = False


app.config["COMPANY_NAME"] = os.getenv(
    "COMPANY_NAME",
    "Cotizador 3D"
)


app.config["COMPANY_PHONE"] = os.getenv(
    "COMPANY_PHONE",
    ""
)


app.config["COMPANY_EMAIL"] = os.getenv(
    "COMPANY_EMAIL",
    ""
)


app.config["CURRENCY"] = os.getenv(
    "CURRENCY",
    "B/."
)


db.init_app(
    app
)


csrf = CSRFProtect(
    app
)


# ============================================================
# LOGIN
# ============================================================

login_manager = LoginManager(
    app
)


login_manager.login_view = (
    "login"
)


login_manager.login_message = (
    "Debes iniciar sesión."
)


@login_manager.user_loader
def load_user(
    user_id
):

    return db.session.get(
        User,
        int(user_id)
    )


# ============================================================
# UTILIDADES GENERALES
# ============================================================

def admin_required(
    function
):

    @wraps(
        function
    )
    @login_required
    def wrapper(
        *args,
        **kwargs
    ):

        if not current_user.is_admin:
            abort(403)

        return function(
            *args,
            **kwargs
        )

    return wrapper


def audit(
    action,
    entity,
    entity_ref=None,
    details=None
):

    if current_user.is_authenticated:

        username = (
            current_user.username
        )

        user_id = (
            current_user.id
        )

    else:

        username = "system"
        user_id = None


    log = AuditLog(

        user_id=user_id,

        username=username,

        action=action,

        entity=entity,

        entity_ref=entity_ref,

        details=details
    )


    db.session.add(
        log
    )


def set_setting(
    key,
    value
):

    setting = (
        AppSetting.query
        .filter_by(
            key=key
        )
        .first()
    )


    if setting:

        setting.value = (
            value
        )

    else:

        setting = AppSetting(
            key=key,
            value=value
        )

        db.session.add(
            setting
        )


def next_quote_number():

    year = datetime.now().year

    prefix = (
        f"COT-{year}-"
    )


    last_quote = (

        Quote.query

        .filter(
            Quote.quote_number.like(
                f"{prefix}%"
            )
        )

        .order_by(
            Quote.id.desc()
        )

        .first()
    )


    number = 1


    if last_quote:

        try:

            number = (
                int(
                    last_quote
                    .quote_number
                    .split("-")[-1]
                )
                + 1
            )

        except ValueError:

            number = (
                Quote.query.count()
                + 1
            )


    return (
        f"{prefix}"
        f"{number:04d}"
    )


def can_modify_quote(
    quote
):

    return (
        current_user.is_admin
        or
        quote.created_by_id
        ==
        current_user.id
    )


def quote_to_payload(
    quote
):

    preset = (

        MarginPreset.query

        .filter_by(
            name=quote.preset_name,
            active=True
        )

        .first()
    )


    if not preset:

        preset = (

            MarginPreset.query

            .filter_by(
                active=True
            )

            .first()
        )


    return {

        "customer_name":
            quote.customer_name or "",

        "notes":
            quote.notes or "",

        "preset_id":
            preset.id
            if preset
            else None,

        "lines": [

            {

                "article_name":
                    line.article_name,

                "quantity":
                    line.quantity,

                "print_hours_each":
                    float(
                        line.print_hours_each
                    ),

                "post_hours_each":
                    float(
                        line.post_hours_each
                    ),

                "filaments": [

                    {

                        "filament_id":
                            filament.filament_id,

                        "grams_each":
                            float(
                                filament.grams_each
                            )

                    }

                    for filament
                    in line.filaments
                ]

            }

            for line
            in quote.lines
        ],

        "extras": [

            {

                "description":
                    extra.description,

                "quantity":
                    extra.quantity,

                "unit_cost":
                    float(
                        extra.unit_cost
                    )

            }

            for extra
            in quote.extras
        ]
    }


def get_filaments_json():

    filaments = (

        FilamentPreset.query

        .filter_by(
            active=True
        )

        .order_by(
            FilamentPreset.material,
            FilamentPreset.color
        )

        .all()
    )


    return [

        {

            "id":
                filament.id,

            "label":
                f"{filament.name} — "
                f"{filament.material} "
                f"{filament.color}"

        }

        for filament
        in filaments
    ]


def get_restart_command():

    raw = os.getenv(
        "RESTART_COMMAND_JSON",
        ""
    ).strip()


    if not raw:
        return None


    try:

        command = json.loads(
            raw
        )

    except json.JSONDecodeError:

        return None


    if not isinstance(
        command,
        list
    ):
        return None


    if not command:
        return None


    if not all(
        isinstance(item, str)
        and item
        for item
        in command
    ):
        return None


    return command


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/")
@login_required
def dashboard():

    quotes_query = (

        Quote.query

        .order_by(
            Quote.updated_at.desc()
        )
    )


    if not current_user.is_admin:

        quotes_query = (

            quotes_query.filter_by(
                created_by_id=
                    current_user.id
            )
        )


    recent = (

        quotes_query

        .limit(8)

        .all()
    )


    total_value = sum(

        (
            dec(
                quote.total
            )

            for quote
            in quotes_query.all()
        ),

        Decimal("0")
    )


    stats = {

        "quotes":
            quotes_query.count(),

        "filaments":
            FilamentPreset.query
            .filter_by(active=True)
            .count(),

        "presets":
            MarginPreset.query
            .filter_by(active=True)
            .count(),

        "total":
            total_value
    }


    return render_template(

        "dashboard.html",

        recent=recent,

        stats=stats
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=[
        "GET",
        "POST"
    ]
)
def login():

    if current_user.is_authenticated:

        return redirect(
            url_for(
                "dashboard"
            )
        )


    if request.method == "POST":

        username = (

            request.form

            .get(
                "username",
                ""
            )

            .strip()
        )


        password = (

            request.form

            .get(
                "password",
                ""
            )
        )


        user = (

            User.query

            .filter(
                func.lower(
                    User.username
                )
                ==
                username.lower()
            )

            .first()
        )


        if (
            user
            and
            user.active
            and
            user.check_password(
                password
            )
        ):

            login_user(
                user
            )


            audit(
                "LOGIN",
                "user",
                user.username
            )


            db.session.commit()


            return redirect(
                url_for(
                    "dashboard"
                )
            )


        flash(
            "Usuario o contraseña incorrectos.",
            "danger"
        )


    return render_template(
        "login.html"
    )


@app.route(
    "/logout",
    methods=["POST"]
)
@login_required
def logout():

    audit(
        "LOGOUT",
        "user",
        current_user.username
    )


    db.session.commit()


    logout_user()


    return redirect(
        url_for(
            "login"
        )
    )


# ============================================================
# USUARIOS
# ============================================================

@app.route(
    "/users"
)
@admin_required
def users():

    all_users = (

        User.query

        .order_by(
            User.username
        )

        .all()
    )


    return render_template(
        "users.html",
        users=all_users
    )


@app.route(
    "/users/save",
    methods=["POST"]
)
@admin_required
def user_save():

    user_id = (
        request.form.get(
            "id"
        )
    )


    username = (

        request.form

        .get(
            "username",
            ""
        )

        .strip()
    )


    password = (

        request.form

        .get(
            "password",
            ""
        )
    )


    is_admin = (
        request.form.get(
            "is_admin"
        )
        == "on"
    )


    active = (
        request.form.get(
            "active"
        )
        == "on"
    )


    if user_id:

        user = db.session.get(
            User,
            int(user_id)
        )


        if not user:
            abort(404)


        if user.username == "VELH":

            username = "VELH"
            is_admin = True
            active = True


        if len(username) < 3:

            flash(
                "El usuario debe tener al menos 3 caracteres.",
                "danger"
            )

            return redirect(
                url_for(
                    "users"
                )
            )


        existing = (

            User.query

            .filter(
                func.lower(
                    User.username
                )
                ==
                username.lower()
            )

            .filter(
                User.id
                !=
                user.id
            )

            .first()
        )


        if existing:

            flash(
                "Ya existe otro usuario con ese nombre.",
                "danger"
            )

            return redirect(
                url_for(
                    "users"
                )
            )


        old_username = (
            user.username
        )


        user.username = (
            username
        )

        user.is_admin = (
            is_admin
        )

        user.active = (
            active
        )


        if password:

            if len(password) < 8:

                flash(
                    "La contraseña debe tener al menos 8 caracteres.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "users"
                    )
                )


            user.set_password(
                password
            )


        audit(
            "UPDATE",
            "user",
            user.username,
            f"Usuario anterior: {old_username}"
        )


        db.session.commit()


        flash(
            "Usuario actualizado correctamente.",
            "success"
        )


        return redirect(
            url_for(
                "users"
            )
        )


    if len(username) < 3:

        flash(
            "El usuario debe tener al menos 3 caracteres.",
            "danger"
        )

        return redirect(
            url_for(
                "users"
            )
        )


    if len(password) < 8:

        flash(
            "La contraseña debe tener al menos 8 caracteres.",
            "danger"
        )

        return redirect(
            url_for(
                "users"
            )
        )


    existing = (

        User.query

        .filter(
            func.lower(
                User.username
            )
            ==
            username.lower()
        )

        .first()
    )


    if existing:

        flash(
            "Ese usuario ya existe.",
            "danger"
        )

        return redirect(
            url_for(
                "users"
            )
        )


    user = User(

        username=username,

        is_admin=is_admin,

        active=active
    )


    user.set_password(
        password
    )


    db.session.add(
        user
    )


    audit(
        "CREATE",
        "user",
        username
    )


    db.session.commit()


    flash(
        "Usuario creado correctamente.",
        "success"
    )


    return redirect(
        url_for(
            "users"
        )
    )


# ============================================================
# FILAMENTOS
# ============================================================

@app.route(
    "/filaments"
)
@login_required
def filaments():

    items = (

        FilamentPreset.query

        .order_by(
            FilamentPreset.material,
            FilamentPreset.color
        )

        .all()
    )


    return render_template(
        "filaments.html",
        filaments=items
    )


@app.route(
    "/filaments/save",
    methods=["POST"]
)
@admin_required
def filament_save():

    filament_id = (
        request.form.get(
            "id"
        )
    )


    if filament_id:

        filament = db.session.get(
            FilamentPreset,
            int(filament_id)
        )

        if not filament:
            abort(404)

        action = "UPDATE"

    else:

        filament = FilamentPreset()
        action = "CREATE"


    filament.name = (
        request.form.get(
            "name",
            ""
        ).strip()
    )


    filament.material = (
        request.form.get(
            "material",
            ""
        ).strip().upper()
    )


    filament.color = (
        request.form.get(
            "color",
            ""
        ).strip()
    )


    filament.spool_price = money(
        request.form.get(
            "spool_price"
        )
    )


    filament.spool_weight_g = dec(
        request.form.get(
            "spool_weight_g"
        )
    )


    filament.active = (
        request.form.get(
            "active"
        )
        == "on"
    )


    if (
        not filament.name
        or
        not filament.material
        or
        not filament.color
    ):

        flash(
            "Completa los datos del filamento.",
            "danger"
        )

        return redirect(
            url_for(
                "filaments"
            )
        )


    if (
        filament.spool_price < 0
        or
        filament.spool_weight_g <= 0
    ):

        flash(
            "Revisa precio y peso del rollo.",
            "danger"
        )

        return redirect(
            url_for(
                "filaments"
            )
        )


    db.session.add(
        filament
    )


    db.session.flush()


    audit(
        action,
        "filament",
        str(filament.id),
        filament.name
    )


    db.session.commit()


    flash(
        "Filamento guardado correctamente.",
        "success"
    )


    return redirect(
        url_for(
            "filaments"
        )
    )


@app.route(
    "/filaments/<int:filament_id>/delete",
    methods=["POST"]
)
@admin_required
def filament_delete(
    filament_id
):

    filament = db.session.get(
        FilamentPreset,
        filament_id
    )


    if not filament:
        abort(404)


    audit(
        "DELETE",
        "filament",
        str(filament.id),
        filament.name
    )


    db.session.delete(
        filament
    )


    db.session.commit()


    flash(
        "Filamento eliminado.",
        "success"
    )


    return redirect(
        url_for(
            "filaments"
        )
    )


# ============================================================
# MÁRGENES
# ============================================================

@app.route(
    "/margins"
)
@login_required
def margins():

    presets = (

        MarginPreset.query

        .order_by(
            MarginPreset.name
        )

        .all()
    )


    return render_template(
        "margins.html",
        presets=presets
    )


@app.route(
    "/margins/save",
    methods=["POST"]
)
@admin_required
def margin_save():

    preset_id = (
        request.form.get(
            "id"
        )
    )


    if preset_id:

        preset = db.session.get(
            MarginPreset,
            int(preset_id)
        )

        if not preset:
            abort(404)

        action = "UPDATE"

    else:

        preset = MarginPreset()
        action = "CREATE"


    preset.name = (
        request.form.get(
            "name",
            ""
        ).strip()
    )


    preset.filament_markup_pct = dec(
        request.form.get(
            "filament_markup_pct"
        )
    )


    preset.print_hour_rate = money(
        request.form.get(
            "print_hour_rate"
        )
    )


    preset.postprocess_hour_rate = money(
        request.form.get(
            "postprocess_hour_rate"
        )
    )


    preset.extra_markup_pct = dec(
        request.form.get(
            "extra_markup_pct"
        )
    )


    preset.active = (
        request.form.get(
            "active"
        )
        == "on"
    )


    if not preset.name:

        flash(
            "El preset debe tener un nombre.",
            "danger"
        )

        return redirect(
            url_for(
                "margins"
            )
        )


    duplicate = (

        MarginPreset.query

        .filter(
            func.lower(
                MarginPreset.name
            )
            ==
            preset.name.lower()
        )

        .filter(
            MarginPreset.id
            !=
            (
                preset.id
                if preset.id
                else 0
            )
        )

        .first()
    )


    if duplicate:

        flash(
            "Ya existe otro preset con ese nombre.",
            "danger"
        )

        return redirect(
            url_for(
                "margins"
            )
        )


    db.session.add(
        preset
    )


    db.session.flush()


    audit(
        action,
        "margin_preset",
        str(preset.id),
        preset.name
    )


    db.session.commit()


    flash(
        "Preset guardado correctamente.",
        "success"
    )


    return redirect(
        url_for(
            "margins"
        )
    )


@app.route(
    "/margins/<int:preset_id>/delete",
    methods=["POST"]
)
@admin_required
def margin_delete(
    preset_id
):

    preset = db.session.get(
        MarginPreset,
        preset_id
    )


    if not preset:
        abort(404)


    if (
        MarginPreset.query.count()
        <= 1
    ):

        flash(
            "Debe existir al menos un preset.",
            "warning"
        )

        return redirect(
            url_for(
                "margins"
            )
        )


    audit(
        "DELETE",
        "margin_preset",
        str(preset.id),
        preset.name
    )


    db.session.delete(
        preset
    )


    db.session.commit()


    flash(
        "Preset eliminado.",
        "success"
    )


    return redirect(
        url_for(
            "margins"
        )
    )


# ============================================================
# COTIZACIONES
# ============================================================

@app.route(
    "/quotes"
)
@login_required
def quotes():

    query = (
        Quote.query
        .order_by(
            Quote.updated_at.desc()
        )
    )


    if not current_user.is_admin:

        query = query.filter_by(
            created_by_id=
                current_user.id
        )


    term = (
        request.args
        .get(
            "q",
            ""
        )
        .strip()
    )


    if term:

        search = (
            f"%{term}%"
        )


        query = query.filter(
            or_(
                Quote.quote_number.like(
                    search
                ),
                Quote.customer_name.like(
                    search
                )
            )
        )


    return render_template(
        "quotes.html",
        quotes=query.all(),
        term=term
    )


@app.route(
    "/quotes/new",
    methods=[
        "GET",
        "POST"
    ]
)
@login_required
def quote_new():

    if request.method == "POST":

        try:

            payload = json.loads(
                request.form.get(
                    "quote_payload",
                    "{}"
                )
            )


            quote = Quote(
                quote_number=
                    next_quote_number(),

                created_by_id=
                    current_user.id,

                preset_name="",

                filament_markup_pct=0,

                print_hour_rate=0,

                postprocess_hour_rate=0,

                extra_markup_pct=0
            )


            db.session.add(
                quote
            )


            save_quote_from_payload(
                quote,
                payload
            )


            db.session.flush()


            audit(
                "CREATE",
                "quote",
                quote.quote_number
            )


            db.session.commit()


            flash(
                "Cotización creada correctamente.",
                "success"
            )


            return redirect(
                url_for(
                    "quote_view",
                    quote_id=
                        quote.id
                )
            )


        except Exception as error:

            db.session.rollback()

            flash(
                str(error),
                "danger"
            )


    first_preset = (
        MarginPreset.query
        .filter_by(
            active=True
        )
        .first()
    )


    initial = {

        "customer_name": "",

        "notes": "",

        "preset_id":
            first_preset.id
            if first_preset
            else None,

        "lines": [
            {
                "article_name": "",
                "quantity": 1,
                "print_hours_each": 0,
                "post_hours_each": 0,
                "filaments": []
            }
        ],

        "extras": []
    }


    presets = (
        MarginPreset.query
        .filter_by(
            active=True
        )
        .order_by(
            MarginPreset.name
        )
        .all()
    )


    return render_template(
        "quote_form.html",
        title=
            "Nueva cotización",
        initial=
            initial,
        filaments_json=
            get_filaments_json(),
        presets=
            presets
    )


@app.route(
    "/quotes/<int:quote_id>"
)
@login_required
def quote_view(
    quote_id
):

    quote = db.session.get(
        Quote,
        quote_id
    )


    if not quote:
        abort(404)


    if (
        not current_user.is_admin
        and
        quote.created_by_id
        !=
        current_user.id
    ):

        abort(403)


    return render_template(
        "quote_view.html",
        q=quote
    )


@app.route(
    "/quotes/<int:quote_id>/edit",
    methods=[
        "GET",
        "POST"
    ]
)
@login_required
def quote_edit(
    quote_id
):

    quote = db.session.get(
        Quote,
        quote_id
    )


    if not quote:
        abort(404)


    if not can_modify_quote(
        quote
    ):

        abort(403)


    if request.method == "POST":

        try:

            payload = json.loads(
                request.form.get(
                    "quote_payload",
                    "{}"
                )
            )


            save_quote_from_payload(
                quote,
                payload
            )


            audit(
                "UPDATE",
                "quote",
                quote.quote_number
            )


            db.session.commit()


            flash(
                "Cotización actualizada.",
                "success"
            )


            return redirect(
                url_for(
                    "quote_view",
                    quote_id=
                        quote.id
                )
            )


        except Exception as error:

            db.session.rollback()

            flash(
                str(error),
                "danger"
            )


    presets = (
        MarginPreset.query
        .filter_by(
            active=True
        )
        .order_by(
            MarginPreset.name
        )
        .all()
    )


    return render_template(
        "quote_form.html",
        title=
            f"Editar "
            f"{quote.quote_number}",
        initial=
            quote_to_payload(
                quote
            ),
        filaments_json=
            get_filaments_json(),
        presets=
            presets
    )


@app.route(
    "/quotes/<int:quote_id>/duplicate",
    methods=["POST"]
)
@login_required
def quote_duplicate(
    quote_id
):

    source = db.session.get(
        Quote,
        quote_id
    )


    if not source:
        abort(404)


    if (
        not current_user.is_admin
        and
        source.created_by_id
        !=
        current_user.id
    ):

        abort(403)


    payload = quote_to_payload(
        source
    )


    quote = Quote(
        quote_number=
            next_quote_number(),

        created_by_id=
            current_user.id,

        preset_name="",

        filament_markup_pct=0,

        print_hour_rate=0,

        postprocess_hour_rate=0,

        extra_markup_pct=0
    )


    db.session.add(
        quote
    )


    save_quote_from_payload(
        quote,
        payload
    )


    db.session.flush()


    audit(
        "DUPLICATE",
        "quote",
        quote.quote_number,
        f"Original: {source.quote_number}"
    )


    db.session.commit()


    flash(
        "Cotización duplicada.",
        "success"
    )


    return redirect(
        url_for(
            "quote_edit",
            quote_id=
                quote.id
        )
    )


@app.route(
    "/quotes/<int:quote_id>/delete",
    methods=["POST"]
)
@login_required
def quote_delete(
    quote_id
):

    quote = db.session.get(
        Quote,
        quote_id
    )


    if not quote:
        abort(404)


    if not can_modify_quote(
        quote
    ):

        abort(403)


    quote_number = (
        quote.quote_number
    )


    audit(
        "DELETE",
        "quote",
        quote_number
    )


    db.session.delete(
        quote
    )


    db.session.commit()


    flash(
        "Cotización eliminada.",
        "success"
    )


    return redirect(
        url_for(
            "quotes"
        )
    )


@app.route(
    "/quotes/<int:quote_id>/pdf"
)
@login_required
def quote_pdf(
    quote_id
):

    quote = db.session.get(
        Quote,
        quote_id
    )


    if not quote:
        abort(404)


    if (
        not current_user.is_admin
        and
        quote.created_by_id
        !=
        current_user.id
    ):

        abort(403)


    buffer = create_quote_pdf(

        quote,

        app.config[
            "COMPANY_NAME"
        ],

        app.config[
            "COMPANY_PHONE"
        ],

        app.config[
            "COMPANY_EMAIL"
        ],

        app.config[
            "CURRENCY"
        ]
    )


    return send_file(
        buffer,
        mimetype=
            "application/pdf",
        as_attachment=True,
        download_name=
            f"{quote.quote_number}.pdf"
    )


# ============================================================
# AUDITORÍA
# ============================================================

@app.route(
    "/audit"
)
@admin_required
def audit_log():

    logs = (
        AuditLog.query
        .order_by(
            AuditLog.created_at.desc()
        )
        .limit(500)
        .all()
    )


    return render_template(
        "audit.html",
        logs=logs
    )


# ============================================================
# SISTEMA
# ============================================================

@app.route(
    "/system"
)
@admin_required
def system_page():

    timezone_name = (
        get_timezone_name()
    )


    current_time = (
        datetime.now(
            timezone.utc
        )
        .astimezone(
            get_timezone()
        )
    )


    timezone_options = [

        (
            "Panamá",
            "America/Panama"
        ),

        (
            "Colombia",
            "America/Bogota"
        ),

        (
            "Costa Rica",
            "America/Costa_Rica"
        ),

        (
            "México",
            "America/Mexico_City"
        ),

        (
            "Nueva York",
            "America/New_York"
        ),

        (
            "España",
            "Europe/Madrid"
        ),

        (
            "Argentina",
            "America/Argentina/Buenos_Aires"
        ),

        (
            "Chile",
            "America/Santiago"
        ),

        (
            "UTC",
            "UTC"
        )
    ]


    database_size = 0


    if os.path.exists(
        DATABASE_PATH
    ):

        database_size = (
            os.path.getsize(
                DATABASE_PATH
            )
        )


    return render_template(

        "system.html",

        timezone_name=
            timezone_name,

        current_time=
            current_time,

        timezone_options=
            timezone_options,

        database_size=
            database_size,

        python_version=
            platform.python_version(),

        operating_system=
            platform.platform(),

        restart_enabled=
            get_restart_command()
            is not None
    )


@app.route(
    "/system/timezone",
    methods=["POST"]
)
@admin_required
def system_timezone():

    selected_timezone = (
        request.form
        .get(
            "timezone",
            ""
        )
        .strip()
    )


    custom_timezone = (
        request.form
        .get(
            "custom_timezone",
            ""
        )
        .strip()
    )


    timezone_name = (
        custom_timezone
        or
        selected_timezone
    )


    if not timezone_name:

        flash(
            "Debes seleccionar una zona horaria.",
            "danger"
        )

        return redirect(
            url_for(
                "system_page"
            )
        )


    try:

        ZoneInfo(
            timezone_name
        )

    except ZoneInfoNotFoundError:

        flash(
            "El código de zona horaria no es válido.",
            "danger"
        )

        return redirect(
            url_for(
                "system_page"
            )
        )


    previous_timezone = (
        get_timezone_name()
    )


    set_setting(
        "timezone",
        timezone_name
    )


    audit(
        "UPDATE",
        "system_setting",
        "timezone",
        (
            f"{previous_timezone} "
            f"-> "
            f"{timezone_name}"
        )
    )


    db.session.commit()


    flash(
        "Zona horaria actualizada correctamente.",
        "success"
    )


    return redirect(
        url_for(
            "system_page"
        )
    )


@app.route(
    "/system/database/export",
    methods=["POST"]
)
@admin_required
def system_database_export():

    audit(
        "EXPORT",
        "database",
        "quotes.db",
        "Copia de seguridad descargada"
    )


    db.session.commit()


    file_descriptor, backup_path = (
        tempfile.mkstemp(
            suffix=".db"
        )
    )


    os.close(
        file_descriptor
    )


    source_connection = None
    backup_connection = None


    try:

        source_connection = (
            sqlite3.connect(
                DATABASE_PATH
            )
        )


        backup_connection = (
            sqlite3.connect(
                backup_path
            )
        )


        source_connection.backup(
            backup_connection
        )


    finally:

        if backup_connection:
            backup_connection.close()

        if source_connection:
            source_connection.close()


    timestamp = (
        datetime.now(
            timezone.utc
        )
        .astimezone(
            get_timezone()
        )
        .strftime(
            "%Y-%m-%d_%H-%M-%S"
        )
    )


    response = send_file(
        backup_path,
        as_attachment=True,
        mimetype=
            "application/vnd.sqlite3",
        download_name=
            (
                "cotizador3d_backup_"
                f"{timestamp}.db"
            )
    )


    @response.call_on_close
    def remove_backup():

        try:

            os.remove(
                backup_path
            )

        except OSError:

            pass


    return response


@app.route(
    "/system/restart",
    methods=["POST"]
)
@admin_required
def system_restart():

    command = (
        get_restart_command()
    )


    if command is None:

        flash(
            "El reinicio del servicio no está configurado.",
            "warning"
        )

        return redirect(
            url_for(
                "system_page"
            )
        )


    audit(
        "RESTART",
        "application",
        "Cotizador 3D",
        "Reinicio solicitado por administrador"
    )


    db.session.commit()


    try:

        subprocess.Popen(
            command,
            shell=False,
            stdin=
                subprocess.DEVNULL,
            stdout=
                subprocess.DEVNULL,
            stderr=
                subprocess.DEVNULL
        )


        flash(
            "Se envió la solicitud de reinicio del servicio.",
            "success"
        )


    except Exception as error:

        flash(
            f"No se pudo solicitar el reinicio: {error}",
            "danger"
        )


    return redirect(
        url_for(
            "system_page"
        )
    )


# ============================================================
# FILTROS
# ============================================================

@app.template_filter(
    "money"
)
def money_filter(
    value
):

    return (
        f"{money(value):.2f}"
    )


@app.template_filter(
    "localdatetime"
)
def localdatetime_filter(
    value
):

    return format_local_datetime(
        value,
        "%d/%m/%Y %H:%M"
    )


@app.template_filter(
    "localdate"
)
def localdate_filter(
    value
):

    return format_local_datetime(
        value,
        "%d/%m/%Y"
    )


@app.template_filter(
    "localsimpletime"
)
def localsimpletime_filter(
    value
):

    return format_local_datetime(
        value,
        "%H:%M"
    )


@app.template_filter(
    "filesize"
)
def filesize_filter(
    value
):

    size = float(
        value or 0
    )


    units = [
        "B",
        "KB",
        "MB",
        "GB"
    ]


    for unit in units:

        if size < 1024:

            return (
                f"{size:.1f} {unit}"
            )

        size /= 1024


    return (
        f"{size:.1f} TB"
    )


@app.context_processor
def inject_globals():

    return {

        "currency":
            app.config[
                "CURRENCY"
            ],

        "company_name":
            app.config[
                "COMPANY_NAME"
            ],

        "app_timezone":
            get_timezone_name()
    }


# ============================================================
# ERRORES
# ============================================================

@app.errorhandler(403)
def forbidden(
    error
):

    return render_template(
        "error.html",
        code=403,
        message=
            "No tienes permiso para realizar esta acción."
    ), 403


@app.errorhandler(404)
def not_found(
    error
):

    return render_template(
        "error.html",
        code=404,
        message=
            "No se encontró el recurso solicitado."
    ), 404


# ============================================================
# INICIALIZACIÓN
# ============================================================

def initialize_database():

    with app.app_context():

        db.create_all()


        admin = (
            User.query
            .filter_by(
                username="VELH"
            )
            .first()
        )


        if not admin:

            password = os.getenv(
                "INITIAL_ADMIN_PASSWORD",
                "VELH12345!"
            )


            admin = User(
                username="VELH",
                is_admin=True,
                active=True
            )


            admin.set_password(
                password
            )


            db.session.add(
                admin
            )


        if (
            MarginPreset.query.count()
            == 0
        ):

            regular = MarginPreset(
                name=
                    "Cliente regular",
                filament_markup_pct=
                    30,
                print_hour_rate=
                    5,
                postprocess_hour_rate=
                    5,
                extra_markup_pct=
                    0,
                active=True
            )


            db.session.add(
                regular
            )


        timezone_setting = (
            AppSetting.query
            .filter_by(
                key="timezone"
            )
            .first()
        )


        if not timezone_setting:

            db.session.add(
                AppSetting(
                    key="timezone",
                    value=
                        DEFAULT_TIMEZONE
                )
            )


        db.session.commit()


initialize_database()


if __name__ == "__main__":

    app.run(
        debug=True,
        host="0.0.0.0",
        port=8000
    )