from decimal import Decimal, ROUND_HALF_UP

from models import (
    db,
    FilamentPreset,
    MarginPreset,
    QuoteLine,
    QuoteLineFilament,
    QuoteExtra
)


def dec(value):
    return Decimal(str(value or 0))


def money(value):
    return dec(value).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )


def calculate_quote_payload(payload):
    preset_id = int(payload.get("preset_id") or 0)

    preset = db.session.get(
        MarginPreset,
        preset_id
    )

    if not preset or not preset.active:
        raise ValueError(
            "El preset seleccionado no es válido."
        )

    lines_result = []

    subtotal_material = Decimal("0")
    subtotal_print = Decimal("0")
    subtotal_post = Decimal("0")

    for raw_line in payload.get("lines", []):

        article_name = (
            raw_line.get("article_name") or ""
        ).strip()

        quantity = int(
            raw_line.get("quantity") or 0
        )

        print_hours = dec(
            raw_line.get("print_hours_each")
        )

        post_hours = dec(
            raw_line.get("post_hours_each")
        )

        if not article_name:
            raise ValueError(
                "Cada artículo debe tener un nombre."
            )

        if quantity < 1:
            raise ValueError(
                "La cantidad debe ser al menos 1."
            )

        line_material = Decimal("0")

        filaments_result = []

        for raw_filament in raw_line.get(
            "filaments",
            []
        ):
            filament_id = int(
                raw_filament.get("filament_id") or 0
            )

            grams_each = dec(
                raw_filament.get("grams_each")
            )

            if grams_each <= 0:
                continue

            filament = db.session.get(
                FilamentPreset,
                filament_id
            )

            if not filament:
                continue

            base_cost = (
                filament.price_per_g
                * grams_each
                * quantity
            )

            markup_multiplier = (
                Decimal("1")
                + dec(
                    preset.filament_markup_pct
                ) / Decimal("100")
            )

            material_price = money(
                base_cost
                * markup_multiplier
            )

            line_material += material_price

            filaments_result.append({
                "filament_id": filament.id,
                "filament_name": filament.name,
                "material": filament.material,
                "color": filament.color,
                "price_per_g_snapshot":
                    filament.price_per_g,
                "grams_each": grams_each,
                "cost_with_markup":
                    material_price
            })

        line_print = money(
            print_hours
            * quantity
            * dec(preset.print_hour_rate)
        )

        line_post = money(
            post_hours
            * quantity
            * dec(
                preset.postprocess_hour_rate
            )
        )

        line_material = money(
            line_material
        )

        line_total = money(
            line_material
            + line_print
            + line_post
        )

        subtotal_material += line_material
        subtotal_print += line_print
        subtotal_post += line_post

        lines_result.append({
            "article_name": article_name,
            "quantity": quantity,
            "print_hours_each":
                print_hours,
            "post_hours_each":
                post_hours,
            "line_material_cost":
                line_material,
            "line_print_cost":
                line_print,
            "line_post_cost":
                line_post,
            "line_total":
                line_total,
            "filaments":
                filaments_result
        })

    if not lines_result:
        raise ValueError(
            "La cotización necesita al menos un artículo."
        )

    extras_result = []

    subtotal_extras = Decimal("0")

    for raw_extra in payload.get(
        "extras",
        []
    ):
        description = (
            raw_extra.get("description") or ""
        ).strip()

        quantity = int(
            raw_extra.get("quantity") or 0
        )

        unit_cost = dec(
            raw_extra.get("unit_cost")
        )

        if not description:
            continue

        if quantity < 1:
            continue

        extra_multiplier = (
            Decimal("1")
            + dec(
                preset.extra_markup_pct
            ) / Decimal("100")
        )

        line_total = money(
            unit_cost
            * quantity
            * extra_multiplier
        )

        subtotal_extras += line_total

        extras_result.append({
            "description":
                description,
            "quantity":
                quantity,
            "unit_cost":
                unit_cost,
            "markup_pct":
                dec(
                    preset.extra_markup_pct
                ),
            "line_total":
                line_total
        })

    total = money(
        subtotal_material
        + subtotal_print
        + subtotal_post
        + subtotal_extras
    )

    return {
        "preset": preset,

        "lines":
            lines_result,

        "extras":
            extras_result,

        "subtotal_material":
            money(subtotal_material),

        "subtotal_print":
            money(subtotal_print),

        "subtotal_post":
            money(subtotal_post),

        "subtotal_extras":
            money(subtotal_extras),

        "total":
            total
    }


def save_quote_from_payload(
    quote,
    payload
):
    calculated = calculate_quote_payload(
        payload
    )

    preset = calculated["preset"]

    quote.customer_name = (
        payload.get("customer_name") or ""
    ).strip() or None

    quote.notes = (
        payload.get("notes") or ""
    ).strip() or None

    quote.preset_name = preset.name

    quote.filament_markup_pct = (
        preset.filament_markup_pct
    )

    quote.print_hour_rate = (
        preset.print_hour_rate
    )

    quote.postprocess_hour_rate = (
        preset.postprocess_hour_rate
    )

    quote.extra_markup_pct = (
        preset.extra_markup_pct
    )

    quote.subtotal_material = (
        calculated["subtotal_material"]
    )

    quote.subtotal_print = (
        calculated["subtotal_print"]
    )

    quote.subtotal_post = (
        calculated["subtotal_post"]
    )

    quote.subtotal_extras = (
        calculated["subtotal_extras"]
    )

    quote.total = calculated["total"]

    quote.lines.clear()
    quote.extras.clear()

    db.session.flush()

    for line_data in calculated["lines"]:

        line = QuoteLine(
            article_name=
                line_data["article_name"],

            quantity=
                line_data["quantity"],

            print_hours_each=
                line_data[
                    "print_hours_each"
                ],

            post_hours_each=
                line_data[
                    "post_hours_each"
                ],

            line_material_cost=
                line_data[
                    "line_material_cost"
                ],

            line_print_cost=
                line_data[
                    "line_print_cost"
                ],

            line_post_cost=
                line_data[
                    "line_post_cost"
                ],

            line_total=
                line_data["line_total"]
        )

        quote.lines.append(line)

        for filament in line_data[
            "filaments"
        ]:
            line.filaments.append(
                QuoteLineFilament(
                    **filament
                )
            )

    for extra in calculated["extras"]:
        quote.extras.append(
            QuoteExtra(
                **extra
            )
        )