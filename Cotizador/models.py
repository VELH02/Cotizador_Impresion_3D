from datetime import datetime
from decimal import Decimal

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)


db = SQLAlchemy()


# ============================================================
# USUARIOS
# ============================================================

class User(
    db.Model,
    UserMixin
):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    is_admin = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )


    def set_password(
        self,
        password
    ):

        self.password_hash = (
            generate_password_hash(
                password
            )
        )


    def check_password(
        self,
        password
    ):

        return check_password_hash(
            self.password_hash,
            password
        )


    @property
    def is_active(self):

        return self.active


# ============================================================
# CONFIGURACIÓN
# ============================================================

class AppSetting(
    db.Model
):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    key = db.Column(
        db.String(100),
        unique=True,
        nullable=False,
        index=True
    )

    value = db.Column(
        db.Text,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )


# ============================================================
# FILAMENTOS
# ============================================================

class FilamentPreset(
    db.Model
):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(120),
        nullable=False
    )

    material = db.Column(
        db.String(50),
        nullable=False
    )

    color = db.Column(
        db.String(50),
        nullable=False
    )

    spool_price = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    spool_weight_g = db.Column(
        db.Numeric(10, 2),
        nullable=False,
        default=1000
    )

    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


    @property
    def price_per_g(
        self
    ):

        if not self.spool_weight_g:
            return Decimal("0")

        return (
            Decimal(
                str(
                    self.spool_price
                )
            )
            /
            Decimal(
                str(
                    self.spool_weight_g
                )
            )
        )


# ============================================================
# PRESETS DE PRECIO
# ============================================================

class MarginPreset(
    db.Model
):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(120),
        unique=True,
        nullable=False
    )

    filament_markup_pct = db.Column(
        db.Numeric(8, 2),
        default=30,
        nullable=False
    )

    print_hour_rate = db.Column(
        db.Numeric(10, 2),
        default=5,
        nullable=False
    )

    postprocess_hour_rate = db.Column(
        db.Numeric(10, 2),
        default=5,
        nullable=False
    )

    extra_markup_pct = db.Column(
        db.Numeric(8, 2),
        default=0,
        nullable=False
    )

    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


# ============================================================
# COTIZACIONES
# ============================================================

class Quote(
    db.Model
):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    quote_number = db.Column(
        db.String(30),
        unique=True,
        nullable=False,
        index=True
    )

    customer_name = db.Column(
        db.String(160)
    )

    preset_name = db.Column(
        db.String(120),
        nullable=False
    )

    filament_markup_pct = db.Column(
        db.Numeric(8, 2),
        nullable=False
    )

    print_hour_rate = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    postprocess_hour_rate = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    extra_markup_pct = db.Column(
        db.Numeric(8, 2),
        nullable=False
    )

    notes = db.Column(
        db.Text
    )

    subtotal_material = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    subtotal_print = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    subtotal_post = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    subtotal_extras = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    total = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    created_by = db.relationship(
        "User",
        foreign_keys=[
            created_by_id
        ]
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    lines = db.relationship(
        "QuoteLine",
        cascade="all, delete-orphan",
        backref="quote"
    )

    extras = db.relationship(
        "QuoteExtra",
        cascade="all, delete-orphan",
        backref="quote"
    )


class QuoteLine(
    db.Model
):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    quote_id = db.Column(
        db.Integer,
        db.ForeignKey("quote.id"),
        nullable=False
    )

    article_name = db.Column(
        db.String(180),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        default=1,
        nullable=False
    )

    print_hours_each = db.Column(
        db.Numeric(10, 2),
        default=0
    )

    post_hours_each = db.Column(
        db.Numeric(10, 2),
        default=0
    )

    line_material_cost = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    line_print_cost = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    line_post_cost = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    line_total = db.Column(
        db.Numeric(12, 2),
        default=0
    )

    filaments = db.relationship(
        "QuoteLineFilament",
        cascade="all, delete-orphan",
        backref="line"
    )


class QuoteLineFilament(
    db.Model
):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    quote_line_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "quote_line.id"
        ),
        nullable=False
    )

    filament_id = db.Column(
        db.Integer
    )

    filament_name = db.Column(
        db.String(120),
        nullable=False
    )

    material = db.Column(
        db.String(50),
        nullable=False
    )

    color = db.Column(
        db.String(50),
        nullable=False
    )

    price_per_g_snapshot = db.Column(
        db.Numeric(12, 6),
        nullable=False
    )

    grams_each = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    cost_with_markup = db.Column(
        db.Numeric(12, 2),
        nullable=False
    )


class QuoteExtra(
    db.Model
):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    quote_id = db.Column(
        db.Integer,
        db.ForeignKey("quote.id"),
        nullable=False
    )

    description = db.Column(
        db.String(180),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        default=1
    )

    unit_cost = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    markup_pct = db.Column(
        db.Numeric(8, 2),
        default=0
    )

    line_total = db.Column(
        db.Numeric(12, 2),
        nullable=False
    )


# ============================================================
# AUDITORÍA
# ============================================================

class AuditLog(
    db.Model
):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer
    )

    username = db.Column(
        db.String(80),
        nullable=False
    )

    action = db.Column(
        db.String(40),
        nullable=False
    )

    entity = db.Column(
        db.String(40),
        nullable=False
    )

    entity_ref = db.Column(
        db.String(120)
    )

    details = db.Column(
        db.Text
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )