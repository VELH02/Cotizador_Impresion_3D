import io
import os

from flask import current_app

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm

from reportlab.lib.styles import (
    getSampleStyleSheet
)

from reportlab.lib.utils import (
    ImageReader
)

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image
)

from quote_logic import money

from time_utils import (
    format_local_datetime
)


def create_quote_pdf(
    quote,
    company_name,
    company_phone,
    company_email,
    currency
):

    buffer = io.BytesIO()


    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=
            18 * mm,
        rightMargin=
            18 * mm,
        topMargin=
            15 * mm,
        bottomMargin=
            15 * mm
    )


    styles = (
        getSampleStyleSheet()
    )


    content = []


    # ========================================================
    # LOGO O NOMBRE DE EMPRESA
    # ========================================================

    logo_path = os.path.join(
        current_app.static_folder,
        "logo.png"
    )


    logo_loaded = False


    if os.path.exists(
        logo_path
    ):

        try:

            image_reader = (
                ImageReader(
                    logo_path
                )
            )


            original_width, original_height = (
                image_reader.getSize()
            )


            max_width = (
                55 * mm
            )

            max_height = (
                22 * mm
            )


            scale = min(
                max_width
                /
                original_width,
                max_height
                /
                original_height
            )


            logo = Image(
                logo_path,
                width=
                    original_width
                    * scale,
                height=
                    original_height
                    * scale
            )


            content.append(
                logo
            )


            logo_loaded = True


        except Exception:

            logo_loaded = False


    if not logo_loaded:

        content.append(
            Paragraph(
                f"<b>{company_name}</b>",
                styles["Title"]
            )
        )


    content.append(
        Spacer(
            1,
            4 * mm
        )
    )


    # ========================================================
    # CONTACTO
    # ========================================================

    contact_information = []


    if company_phone:

        contact_information.append(
            company_phone
        )


    if company_email:

        contact_information.append(
            company_email
        )


    if contact_information:

        content.append(
            Paragraph(
                " | ".join(
                    contact_information
                ),
                styles[
                    "Normal"
                ]
            )
        )


        content.append(
            Spacer(
                1,
                3 * mm
            )
        )


    # ========================================================
    # INFORMACIÓN
    # ========================================================

    content.append(
        Paragraph(
            (
                "<b>Cotización "
                f"{quote.quote_number}"
                "</b>"
            ),
            styles[
                "Heading2"
            ]
        )
    )


    content.append(
        Spacer(
            1,
            2 * mm
        )
    )


    content.append(
        Paragraph(
            (
                "Fecha: "
                +
                format_local_datetime(
                    quote.created_at,
                    "%d/%m/%Y"
                )
            ),
            styles[
                "Normal"
            ]
        )
    )


    if quote.created_by:

        content.append(
            Paragraph(
                (
                    "Vendedor: "
                    f"{quote.created_by.username}"
                ),
                styles[
                    "Normal"
                ]
            )
        )


    if quote.customer_name:

        content.append(
            Paragraph(
                (
                    "Cliente: "
                    f"{quote.customer_name}"
                ),
                styles[
                    "Normal"
                ]
            )
        )


    content.append(
        Spacer(
            1,
            6 * mm
        )
    )


    # ========================================================
    # TABLA COMERCIAL
    # ========================================================

    data = [
        [
            "Artículo",
            "Cantidad",
            "Precio unitario",
            "Total"
        ]
    ]


    for line in quote.lines:

        quantity = (
            line.quantity
            if line.quantity
            else 1
        )


        unit_price = money(
            line.line_total
            /
            quantity
        )


        data.append(
            [
                line.article_name,

                str(
                    quantity
                ),

                (
                    f"{currency}"
                    f"{unit_price:.2f}"
                ),

                (
                    f"{currency}"
                    f"{money(line.line_total):.2f}"
                )
            ]
        )


    for extra in quote.extras:

        quantity = (
            extra.quantity
            if extra.quantity
            else 1
        )


        unit_price = money(
            extra.line_total
            /
            quantity
        )


        data.append(
            [
                extra.description,

                str(
                    quantity
                ),

                (
                    f"{currency}"
                    f"{unit_price:.2f}"
                ),

                (
                    f"{currency}"
                    f"{money(extra.line_total):.2f}"
                )
            ]
        )


    table = Table(
        data,
        colWidths=[
            90 * mm,
            25 * mm,
            32 * mm,
            32 * mm
        ],
        repeatRows=1
    )


    table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor(
                        "#20252b"
                    )
                ),

                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white
                ),

                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold"
                ),

                (
                    "ALIGN",
                    (1, 1),
                    (-1, -1),
                    "RIGHT"
                ),

                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE"
                ),

                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor(
                        "#cccccc"
                    )
                ),

                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    9
                ),

                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8
                ),

                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8
                )
            ]
        )
    )


    content.append(
        table
    )


    content.append(
        Spacer(
            1,
            7 * mm
        )
    )


    # ========================================================
    # TOTAL
    # ========================================================

    total_table = Table(
        [
            [
                "TOTAL",

                (
                    f"{currency}"
                    f"{money(quote.total):.2f}"
                )
            ]
        ],
        colWidths=[
            45 * mm,
            40 * mm
        ],
        hAlign="RIGHT"
    )


    total_table.setStyle(
        TableStyle(
            [
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, -1),
                    "Helvetica-Bold"
                ),

                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    13
                ),

                (
                    "ALIGN",
                    (1, 0),
                    (1, 0),
                    "RIGHT"
                ),

                (
                    "LINEABOVE",
                    (0, 0),
                    (-1, 0),
                    1.2,
                    colors.black
                ),

                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8
                )
            ]
        )
    )


    content.append(
        total_table
    )


    if quote.notes:

        content.append(
            Spacer(
                1,
                8 * mm
            )
        )


        content.append(
            Paragraph(
                "<b>Notas</b>",
                styles[
                    "Heading3"
                ]
            )
        )


        content.append(
            Paragraph(
                quote.notes.replace(
                    "\n",
                    "<br/>"
                ),
                styles[
                    "Normal"
                ]
            )
        )


    document.build(
        content
    )


    buffer.seek(0)


    return buffer