from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from models import AppSetting


DEFAULT_TIMEZONE = "America/Panama"


def get_timezone_name():
    """
    Obtiene la zona horaria configurada en la base de datos.
    """

    setting = AppSetting.query.filter_by(
        key="timezone"
    ).first()

    if setting and setting.value:
        return setting.value

    return DEFAULT_TIMEZONE


def get_timezone():
    """
    Devuelve un objeto ZoneInfo válido.
    """

    timezone_name = get_timezone_name()

    try:
        return ZoneInfo(timezone_name)

    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def to_local_datetime(value):
    """
    Convierte un datetime almacenado en UTC
    a la zona horaria seleccionada por el administrador.

    Las fechas antiguas de la aplicación son naive UTC,
    por lo que se les asigna UTC antes de convertirlas.
    """

    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        get_timezone()
    )


def format_local_datetime(
    value,
    format_string="%d/%m/%Y %H:%M"
):
    """
    Convierte y formatea una fecha.
    """

    converted = to_local_datetime(
        value
    )

    if converted is None:
        return "—"

    return converted.strftime(
        format_string
    )