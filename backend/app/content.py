"""Todos los textos que el bot le envía al ciudadano.

Escenario de la demo: el mismo de la web del equipo (terremoto del 10 de agosto).
Límites de WhatsApp: cuerpo de mensaje interactivo <= 1024 caracteres, título de botón <= 20,
título de fila de lista <= 24, descripción de fila <= 72.
"""

WEB_URL = "https://geo-aid-coral.vercel.app"
EMERGENCY_LINE = "123"


def welcome(name: str | None) -> str:
    saludo = f"Hola {name}" if name else "Hola"
    return (
        f"{saludo}, te damos la bienvenida a *GeoAid*.\n\n"
        "Si tu *vivienda* o tu *negocio* resultó afectado por el terremoto del 10 de agosto, por aquí puedes "
        "reportar los daños para que el equipo priorice la visita técnica y las ayudas. Te tomará unos 5 minutos."
    )


def welcome_back(name: str | None) -> str:
    return f"Hola{' ' + name if name else ''}, ¿en qué te podemos ayudar?"


# Texto presentable para la demo. Antes de operar con una entidad real debe validarlo un abogado.
TERMS = (
    "*Autorización de tratamiento de datos (Ley 1581 de 2012)*\n\n"
    "Para registrar tu reporte necesitamos tu nombre, número de cédula, ubicación, fotos del inmueble "
    "y datos de tu hogar o de tu negocio. Los usaremos únicamente para evaluar los daños y priorizar ayudas. "
    "Las fotos de los daños las revisa un servicio de inteligencia artificial (Claude, de Anthropic) "
    "solo para clasificar el daño de forma preliminar. "
    "Las preguntas sobre pertenencia étnica y la foto de tu rostro son *opcionales*. "
    "Puedes consultar, corregir o pedir que se eliminen tus datos en cualquier momento.\n\n"
    "_GeoAid es un prototipo universitario presentado en Expoandes: los datos se usan solo para esta "
    "demostración y se eliminan al terminar el evento._\n\n"
    "¿Autorizas el tratamiento de tus datos?"
)
TERMS_ACCEPTED = "Gracias."

# --- Tipo de reporte ---------------------------------------------------------------------

REPORT_TYPE_HOME = "VIVIENDA"
REPORT_TYPE_BUSINESS = "NEGOCIO"
ASK_REPORT_TYPE = (
    "¿Qué quieres reportar?\n\n"
    "• *Mi vivienda:* la casa o apartamento donde vive tu hogar.\n"
    "• *Mi negocio:* tienda, local, bodega, taller u otra empresa.\n\n"
    "_Si tienes los dos, al terminar puedes reportar el otro._"
)
START_HOME = "Empecemos con la ubicación de la vivienda afectada."
START_BUSINESS = "Empecemos con la ubicación del negocio afectado."


def place(business: bool) -> str:
    """'la vivienda' o 'el negocio', para los textos compartidos por los dos tipos de reporte."""
    return "el negocio" if business else "la vivienda"
TERMS_REJECTED = (
    "Entendido. Sin tu autorización no podemos registrar el reporte. "
    "Si cambias de opinión, escríbenos de nuevo cuando quieras.\n\n"
    f"Si hay riesgo para la vida, llama a la línea de emergencias *{EMERGENCY_LINE}*."
)

def ask_at_property(business: bool = False) -> str:
    where = "en el negocio o local afectado" if business else "en la vivienda afectada"
    return f"¿Estás *en este momento* {where}?"


def ask_location(at_property: bool, business: bool = False) -> str:
    if at_property:
        intro = (
            "Comparte tu ubicación actual con el botón de abajo, así sabremos exactamente "
            f"dónde está {place(business)}."
        )
    else:
        intro = (
            f"Comparte tu ubicación actual con el botón de abajo. Sabemos que no estás en {place(business)}; "
            "en el siguiente paso te pediremos su dirección."
        )
    return intro + "\n\nSi no puedes compartirla, escribe *omitir*."
LOCATION_SKIPPED = "Está bien, continuamos sin la ubicación GPS."
LOCATION_INVALID = (
    "Usa el botón *Enviar ubicación* y elige tu ubicación *actual* "
    "(la ubicación en tiempo real no nos llega). O escribe *omitir*."
)

SKIP_HINT = "\n\n_Si prefieres no responder, escribe *saltar*._"
SKIP_ROW_TITLE = "Saltar pregunta"
SKIP_ROW_DESCRIPTION = "Prefiero no responder"
SKIPPED = "Listo, pasamos a la siguiente pregunta."

ZONE_URBAN = "URBANA"
ZONE_RURAL = "RURAL"
def ask_zone(business: bool = False) -> str:
    return (
        f"¿{place(business).capitalize()} está en *zona urbana* o *rural*?\n\n"
        "• *Urbana:* ciudad o casco urbano de un pueblo.\n"
        "• *Rural:* vereda, corregimiento o finca."
    )


def ask_address(business: bool = False) -> str:
    what = "del negocio" if business else "de la vivienda afectada"
    return f"Escribe la *dirección {what}* y el barrio.\nEjemplo: Calle 10 # 5-23, barrio El Centro" + SKIP_HINT


ASK_ADDRESS_RURAL = (
    "Escribe el nombre de la *vereda o corregimiento* y, si aplica, de la *finca*. "
    "Puedes agregar una referencia para llegar.\n"
    "Ejemplo: Finca La Esperanza, vereda El Retiro, a 2 km de la escuela" + SKIP_HINT
)

def ask_municipality(business: bool = False) -> str:
    return f"¿En qué *municipio* está {place(business)}? Elige de la lista o escríbelo."


ASK_MUNICIPALITY_MORE = "Más municipios. Si no está el tuyo, elige *Otro municipio* y escríbelo."


def ask_municipality_rural(business: bool = False) -> str:
    near = "al negocio" if business else "a la vivienda"
    return (
        f"¿Cuál es el *pueblo o municipio más cercano* {near}? Escribe también el departamento.\n"
        "Ejemplo: Timbío, Cauca"
    )

MUNICIPALITY_BUTTON = "Ver municipios"
MUNICIPALITY_SECTION = "Municipios"
MUNICIPALITY_OTHER_ID = "OTRO"
MUNICIPALITY_MORE_ID = "MAS"
MUNICIPALITY_PAGE_SIZE = 9  # WhatsApp admite 10 filas por lista: 9 municipios + "Ver más"
# (id, título <= 24, departamento), en orden alfabético
MUNICIPALITY_OPTIONS = (
    ("ARMENIA", "Armenia", "Quindío"),
    ("BOGOTA", "Bogotá", "Distrito Capital"),
    ("BUENAVENTURA", "Buenaventura", "Valle del Cauca"),
    ("CALI", "Cali", "Valle del Cauca"),
    ("IPIALES", "Ipiales", "Nariño"),
    ("MANIZALES", "Manizales", "Caldas"),
    ("MEDELLIN", "Medellín", "Antioquia"),
    ("NEIVA", "Neiva", "Huila"),
    ("PASTO", "Pasto", "Nariño"),
    ("PEREIRA", "Pereira", "Risaralda"),
    ("PITALITO", "Pitalito", "Huila"),
    ("POPAYAN", "Popayán", "Cauca"),
    ("SANTANDER_QUILICHAO", "Santander de Quilichao", "Cauca"),
)
ASK_MUNICIPALITY_TEXT = "Escribe el *municipio y departamento*."

ASK_HOUSEHOLD = "¿Cuántas personas viven en esa vivienda?"
HOUSEHOLD_BUTTON = "Elegir"
HOUSEHOLD_SECTION = "Personas"
HOUSEHOLD_MORE_ID = "6+"
HOUSEHOLD_OPTIONS = (
    ("1", "1 persona"),
    ("2", "2 personas"),
    ("3", "3 personas"),
    ("4", "4 personas"),
    ("5", "5 personas"),
    (HOUSEHOLD_MORE_ID, "6 o más"),
)
ASK_HOUSEHOLD_NUMBER = "Escribe el número exacto de personas." + SKIP_HINT
INVALID_HOUSEHOLD = "Por favor responde con un número entre 1 y 30."

# --- Situación de emergencia -------------------------------------------------------------
# Listas: (id, título <= 24 caracteres, descripción <= 72 o "")

ASK_HABITABILITY = "¿Pueden seguir viviendo en la vivienda afectada?"
HABITABILITY_SECTION = "Situación"
HABITABILITY_OPTIONS = (
    ("HABITABLE", "Sí, sin riesgo", "Seguimos viviendo allí con normalidad"),
    ("HABITABLE_RIESGO", "Sí, con daños o miedo", "Seguimos allí, pero hay riesgo"),
    ("NO_ALBERGUE", "No: en un albergue", "Estamos en un albergue o refugio"),
    ("NO_FAMILIARES", "No: con familiares", "Donde familiares, amigos o vecinos"),
    ("NO_INTEMPERIE", "No: a la intemperie", "En la calle, en carpa o sin techo"),
    ("OTRO", "Otra situación", ""),
)
DISPLACED_PREFIX = "NO_"  # ids que significan que el hogar no puede habitar la vivienda

ASK_INJURED = "¿Hay personas *heridas* o que necesiten atención médica?"
INJURED_WARNING = (
    f"Si alguien está herido o en peligro, *llama ya a la línea de emergencias {EMERGENCY_LINE}*.\n"
    "Marcamos tu reporte como prioritario."
)

ASK_SERVICES = "¿Tienen *agua y luz* en este momento?"
SERVICES_SECTION = "Servicios"
SERVICES_OPTIONS = (
    ("AGUA_LUZ", "Agua y luz", ""),
    ("SOLO_AGUA", "Solo agua", ""),
    ("SOLO_LUZ", "Solo luz", ""),
    ("NINGUNO", "Ni agua ni luz", ""),
)

ASK_URGENT_NEED = "¿Qué es lo que *más necesita* tu hogar en este momento?"
URGENT_NEED_SECTION = "Necesidad urgente"
URGENT_NEED_OPTIONS = (
    ("ALBERGUE", "Albergue", "Un lugar seguro donde dormir"),
    ("ALIMENTOS", "Alimentos", ""),
    ("AGUA", "Agua potable", ""),
    ("MEDICAMENTOS", "Medicamentos", ""),
    ("ASEO", "Kits de aseo", "Higiene personal y pañales"),
    ("ROPA", "Ropa o cobijas", ""),
    ("NINGUNA", "Ninguna por ahora", ""),
)

# --- Hogar -------------------------------------------------------------------------------

ASK_ESTRATO = "¿De qué *estrato* es la vivienda? Aparece en el recibo de la luz o del agua."
ESTRATO_SECTION = "Estrato"
ESTRATO_OPTIONS = (
    ("1", "Estrato 1", ""),
    ("2", "Estrato 2", ""),
    ("3", "Estrato 3", ""),
    ("4", "Estrato 4", ""),
    ("5", "Estrato 5", ""),
    ("6", "Estrato 6", ""),
    ("RURAL", "Rural / sin estrato", "Vereda o zona rural"),
    ("NO_SABE", "No sé", ""),
)

ASK_VULNERABLE = (
    "¿En el hogar hay alguna de estas personas?\n"
    "• Niñas, niños o adolescentes\n"
    "• Adultos mayores (60 años o más)\n"
    "• Personas con discapacidad\n"
    "• Mujeres embarazadas o lactantes\n"
    "• Víctimas del conflicto armado\n"
    "• Personas migrantes\n"
    "• Mujer cabeza de hogar\n"
    "• Personas con enfermedad crónica"
)
ASK_VULNERABLE_DETAIL = (
    "¿Cuáles? Responde con los números separados por coma (ejemplo: *1,3*):\n"
    "1. Niñas, niños o adolescentes\n"
    "2. Adultos mayores\n"
    "3. Personas con discapacidad\n"
    "4. Mujeres embarazadas o lactantes\n"
    "5. Víctimas del conflicto armado\n"
    "6. Personas migrantes\n"
    "7. Mujer cabeza de hogar\n"
    "8. Personas con enfermedad crónica" + SKIP_HINT
)

ASK_ETHNICITY = (
    "¿Tú o tu hogar se reconocen como parte de alguno de estos grupos étnicos? "
    "_Es opcional: puedes elegir \"Prefiero no responder\"._"
)
ETHNICITY_SECTION = "Pertenencia étnica"
ETHNICITY_OPTIONS = (
    ("INDIGENA", "Indígena", ""),
    ("AFRO", "Negro o afro", "Afrocolombiano, raizal o palenquero"),
    ("RROM", "Rrom (gitano)", ""),
    ("NINGUNA", "Ninguno", ""),
    ("NO_RESPONDE", "Prefiero no responder", ""),
)

LIST_BUTTON = "Elegir"

ASK_TENURE = "¿Cuál es tu relación con la vivienda?"
TENURE_BUTTON = "Elegir opción"
TENURE_SECTION = "Tenencia"
# (id, título <= 24 caracteres, descripción <= 72)
TENURE_OPTIONS = (
    ("PROPIETARIO", "Propietario(a)", "Tengo escritura o título"),
    ("ARRENDATARIO", "Arrendatario(a)", "Pago arriendo"),
    ("POSEEDOR", "Poseedor(a)", "Vivo allí sin escritura"),
    ("FAMILIAR", "Vivienda familiar", "Prestada por un familiar o conocido"),
    ("OTRO", "Otro", "Otra situación"),
)

# --- Negocio (pyme) ----------------------------------------------------------------------

ASK_BIZ_NAME = (
    "¿Cómo se llama el *negocio*? Si no tiene un nombre oficial, escribe cómo lo conocen.\n"
    "Ejemplo: Tienda Doña Rosa"
)
INVALID_BIZ_NAME = "El nombre del negocio es necesario para el reporte. Escríbelo, aunque sea como lo conocen."

ASK_BIZ_PREMISES = "¿Qué tipo de *local* es el que se afectó?"
BIZ_PREMISES_SECTION = "Tipo de local"
BIZ_PREMISES_OPTIONS = (
    ("PUNTO_VENTA", "Punto de venta", "Tienda, local o almacén abierto al público"),
    ("BODEGA", "Bodega", "Almacenamiento de mercancía o materiales"),
    ("PUNTO_VENTA_BODEGA", "Punto de venta y bodega", "Atiende al público y almacena"),
    ("TALLER_PLANTA", "Taller o planta", "Producción, fabricación o reparación"),
    ("OFICINA", "Oficina", ""),
    ("PUESTO_MOVIL", "Puesto móvil o en calle", "Carro, toldo o puesto en una plaza"),
    ("OTRO", "Otro", ""),
)

ASK_BIZ_IN_HOME = (
    "¿El negocio funciona *dentro de tu vivienda*? Por ejemplo, una tienda en el primer piso de la casa."
)

ASK_BIZ_OPERATING = "¿El negocio puede *seguir funcionando*?"
BIZ_OPERATING_SECTION = "Funcionamiento"
BIZ_CLOSED_PREFIX = "CERRADO_"
BIZ_OPERATING_OPTIONS = (
    ("NORMAL", "Sí, con normalidad", ""),
    ("PARCIAL", "Sí, parcialmente", "Con menos horario, ventas o personal"),
    ("CERRADO_TEMPORAL", "Cerrado temporalmente", "Mientras se repara o se evalúa"),
    ("CERRADO_DEFINITIVO", "Cerrado definitivamente", "No podrá volver a abrir"),
)

ASK_BIZ_SECTOR = "¿A qué *sector económico* pertenece el negocio?"
BIZ_SECTOR_SECTION = "Sector"
BIZ_SECTOR_OPTIONS = (
    ("COMERCIO", "Comercio", "Tienda, almacén, ferretería, droguería"),
    ("ALIMENTOS", "Restaurante o alimentos", "Restaurante, cafetería, panadería"),
    ("INDUSTRIA", "Industria o construcción", "Fábrica, taller, confección, carpintería, obra"),
    ("AGROPECUARIO", "Agropecuario", "Cultivos, ganadería, avicultura, pesca"),
    ("TURISMO", "Turismo u hotelería", "Hotel, hostal, agencia de viajes"),
    ("SERVICIOS", "Servicios profesionales", "Consultoría, contabilidad, tecnología"),
    ("BELLEZA_SALUD", "Belleza o salud", "Peluquería, spa, consultorio"),
    ("TRANSPORTE", "Transporte", "Carga, pasajeros o mensajería"),
    ("OTRO", "Otro", ""),
)

ASK_BIZ_AGE = "¿Hace cuánto *funciona* el negocio?"
BIZ_AGE_SECTION = "Antigüedad"
BIZ_AGE_OPTIONS = (
    ("MENOS_1", "Menos de 1 año", ""),
    ("1_3", "Entre 1 y 3 años", ""),
    ("3_5", "Entre 3 y 5 años", ""),
    ("5_10", "Entre 5 y 10 años", ""),
    ("MAS_10", "Más de 10 años", ""),
)

ASK_BIZ_EMPLOYEES = "¿Cuántas personas *trabajan* en el negocio, contándote a ti?"
BIZ_EMPLOYEES_SECTION = "Personas"
BIZ_EMPLOYEES_OPTIONS = (
    ("1", "Solo yo", "Sin empleados"),
    ("2_5", "De 2 a 5 personas", ""),
    ("6_10", "De 6 a 10 personas", ""),
    ("11_50", "De 11 a 50 personas", ""),
    ("51_200", "De 51 a 200 personas", ""),
    ("MAS_200", "Más de 200 personas", ""),
)
# Tamaño por número de trabajadores (criterio de la Ley 905 de 2004; el Decreto 957 de 2019 usa ingresos).
BIZ_SIZE_BY_EMPLOYEES = {
    "1": "MICRO",
    "2_5": "MICRO",
    "6_10": "MICRO",
    "11_50": "PEQUENA",
    "51_200": "MEDIANA",
    "MAS_200": "GRANDE",
}

ASK_BIZ_JOBS_AT_RISK = (
    "¿Cuántas personas del negocio *no pueden trabajar* ahora por el terremoto? "
    "Escribe el número (cuéntate a ti si aplica)."
)
INVALID_JOBS = "Escribe solo un número, por ejemplo *3*, o toca *Ninguna*."

ASK_BIZ_REGISTRY = (
    "¿El negocio tiene *Registro Mercantil* en la Cámara de Comercio, y está *renovado* este año?"
)
BIZ_REGISTRY_SECTION = "Cámara de Comercio"
BIZ_REGISTERED = {"RENOVADO", "SIN_RENOVAR"}
BIZ_INFORMAL = "NO"
BIZ_REGISTRY_OPTIONS = (
    ("RENOVADO", "Sí, al día", "Matrícula mercantil renovada este año"),
    ("SIN_RENOVAR", "Sí, sin renovar", "Registrado, pero falta renovar"),
    (BIZ_INFORMAL, "No está registrado", "Negocio informal"),
    ("NO_SABE", "No sé", ""),
)
BIZ_INFORMAL_NOTE = (
    "No te preocupes: tu reporte se registra igual. Saber cuántos negocios no están registrados "
    "ayuda a diseñar apoyos para ellos."
)

ASK_BIZ_NIT = (
    "Escribe el *NIT* del negocio (con o sin dígito de verificación) o el número de *matrícula mercantil*."
    + SKIP_HINT
)
INVALID_NIT = "El NIT o la matrícula deben tener entre 5 y 15 dígitos. Ejemplo: 900123456-7"

ASK_BIZ_TENURE = "El *local* del negocio es:"
BIZ_TENURE_SECTION = "Local"
BIZ_TENURE_OPTIONS = (
    ("PROPIO", "Propio", ""),
    ("ARRENDADO", "Arrendado", "Pago arriendo por el local"),
    ("PRESTADO", "Prestado o familiar", ""),
    ("OTRO", "Otro", ""),
)

ASK_BIZ_SALES = (
    "Antes del terremoto, ¿cuánto *vendía al mes* el negocio, aproximadamente? "
    "_Es un dato reservado: no se publica y solo sirve para dimensionar los apoyos._"
)
BIZ_SALES_SECTION = "Ventas mensuales"
BIZ_SALES_OPTIONS = (
    ("MENOS_1M", "Menos de $1 millón", ""),
    ("1_5M", "$1 a $5 millones", ""),
    ("5_20M", "$5 a $20 millones", ""),
    ("20_100M", "$20 a $100 millones", ""),
    ("MAS_100M", "Más de $100 millones", ""),
    ("NO_RESPONDE", "Prefiero no responder", ""),
)

# Selección múltiple (WhatsApp no tiene casillas): se responde con los números separados por coma.
BIZ_LEADERSHIP_OPTIONS = (
    ("MUJER", "Una mujer"),
    ("JOVEN", "Una persona joven (18 a 28 años)"),
    ("VICTIMA_CONFLICTO", "Una víctima del conflicto armado"),
    ("DISCAPACIDAD", "Una persona con discapacidad"),
    ("ETNICA", "Una persona indígena, afro o Rrom"),
    ("MIGRANTE", "Una persona migrante"),
)
BIZ_LOSS_OPTIONS = (
    ("MERCANCIA", "Mercancía o inventario"),
    ("MATERIA_PRIMA", "Materia prima o insumos"),
    ("MAQUINARIA", "Maquinaria o herramientas"),
    ("EQUIPOS_TECNOLOGICOS", "Equipos tecnológicos (computador, datáfono, celulares)"),
    ("MOBILIARIO", "Mobiliario, vitrinas o neveras"),
    ("VEHICULOS", "Vehículos"),
    ("DOCUMENTOS", "Documentos, facturas o registros"),
)
NONE_SELECTED = "NINGUNO"


def _numbered(options: tuple[tuple[str, str], ...]) -> str:
    return "\n".join(f"{n}. {label}" for n, (_, label) in enumerate(options, start=1))


ASK_BIZ_LEADERSHIP = (
    "¿El negocio es de propiedad o está *liderado* por alguna de estas personas? "
    "Responde con los números separados por coma (ejemplo: *1,3*):\n" + _numbered(BIZ_LEADERSHIP_OPTIONS)
)
ASK_BIZ_LOSSES = (
    "¿Qué *se dañó o se perdió* en el negocio? Responde con los números separados por coma "
    "(ejemplo: *1,4*):\n" + _numbered(BIZ_LOSS_OPTIONS)
)

ASK_BIZ_LOSS_VALUE = (
    "¿Cuánto calculas que *vale lo que se perdió* (sin contar el local)? Un valor aproximado sirve."
)
BIZ_LOSS_VALUE_SECTION = "Valor de las pérdidas"
BIZ_HIGH_LOSS = {"50_200M", "MAS_200M"}
BIZ_LOSS_VALUE_OPTIONS = (
    ("MENOS_1M", "Menos de $1 millón", ""),
    ("1_5M", "$1 a $5 millones", ""),
    ("5_20M", "$5 a $20 millones", ""),
    ("20_50M", "$20 a $50 millones", ""),
    ("50_200M", "$50 a $200 millones", ""),
    ("MAS_200M", "Más de $200 millones", ""),
    ("NO_SABE", "No sé", ""),
)

ASK_BIZ_INSURANCE = "¿El negocio tiene un *seguro* que cubra estos daños?" + SKIP_HINT

# --- Rol de quien reporta ---

def ask_biz_role(name: str | None) -> str:
    return f"¿Cuál es tu *relación* con *{name}*?" if name else "¿Cuál es tu *relación* con el negocio?"


BIZ_ROLE_SECTION = "Relación"
BIZ_ROLE_OPTIONS = (
    ("DUENO", "Dueño(a)", "Propietario del negocio"),
    ("REP_LEGAL", "Representante legal", ""),
    ("SOCIO", "Socio(a)", ""),
    ("GERENTE", "Gerente o administrador", ""),
    ("DIRECTIVO", "Directivo o jefe de área", "En empresas medianas o grandes"),
    ("CONTADOR", "Contador(a)", "Contador o revisor fiscal"),
    ("EMPLEADO", "Empleado(a)", ""),
    ("FAMILIAR", "Familiar del dueño", ""),
    ("OTRO", "Otro", ""),
)
# Quienes conocen las obligaciones y finanzas del negocio: solo ellos ven ese bloque.
BIZ_DECISION_ROLES = {"DUENO", "REP_LEGAL", "SOCIO", "GERENTE", "DIRECTIVO", "CONTADOR"}
# Quien reporta es el representante legal: no se piden sus datos aparte.
BIZ_LEGAL_REP_ROLES = {"DUENO", "REP_LEGAL"}

# --- Daño del local y reapertura ---

ASK_BIZ_STRUCTURAL_DAMAGE = "¿Cómo quedó la *estructura del local*?"
BIZ_STRUCTURAL_DAMAGE_SECTION = "Daño del local"
BIZ_SEVERE_DAMAGE = {"GRAVE", "COLAPSO"}
BIZ_STRUCTURAL_DAMAGE_OPTIONS = (
    ("SIN_DANO", "Sin daños visibles", ""),
    ("MENOR", "Daños menores", "Grietas finas, vidrios rotos o acabados"),
    ("GRAVE", "Daños graves", "Grietas grandes en muros, columnas o techo"),
    ("COLAPSO", "Colapso parcial o total", "Se cayó una parte o todo el local"),
)
STRUCTURAL_WARNING = (
    "Por tu seguridad, *no entres ni atiendas en el local* hasta que lo revise un técnico. "
    f"Si hay riesgo, llama a la línea de emergencias *{EMERGENCY_LINE}*."
)

ASK_BIZ_REOPENING = "¿En cuánto tiempo crees que el negocio podrá *volver a funcionar normal*?"
BIZ_REOPENING_SECTION = "Reapertura"
BIZ_REOPENING_ASKED_FOR = {"PARCIAL", "CERRADO_TEMPORAL"}
BIZ_REOPENING_OPTIONS = (
    ("MENOS_1_SEMANA", "Menos de 1 semana", ""),
    ("1_4_SEMANAS", "De 1 a 4 semanas", ""),
    ("1_3_MESES", "De 1 a 3 meses", ""),
    ("MAS_3_MESES", "Más de 3 meses", ""),
    ("NO_SABE", "No sé", ""),
)

ASK_BIZ_DIGITAL_SALES = "¿El negocio vende por *WhatsApp, redes sociales o domicilios*?"

# --- Obligaciones y finanzas (solo quien toma decisiones) ---

OBLIGATIONS_INTRO = (
    "*Obligaciones y finanzas del negocio*\n\n"
    "Estas preguntas sirven para saber a qué apoyos puede acceder el negocio. "
    "*No se comparten con la DIAN ni con la alcaldía*, y puedes saltar las que prefieras."
)

ASK_BIZ_LEGAL_FORM = "¿Cómo está *constituido* el negocio?"
BIZ_LEGAL_FORM_SECTION = "Tipo de persona"
BIZ_LEGAL_FORM_OPTIONS = (
    ("PERSONA_NATURAL", "Persona natural", "Comerciante a nombre propio"),
    ("SOCIEDAD", "Sociedad", "SAS, Ltda., S.A. u otra"),
    ("SOLIDARIA", "Cooperativa o asociación", "Entidad sin ánimo de lucro o solidaria"),
    ("NO_SABE", "No sé", ""),
)

# Estados de cada obligación
STATUS_UP_TO_DATE = "AL_DIA"
STATUS_PENDING = "PENDIENTE"
STATUS_UNKNOWN = "NO_SABE"
STATUS_NOT_APPLICABLE = "NO_APLICA"
ASK_BIZ_RUT = "¿El *RUT* (Registro Único Tributario) del negocio está *actualizado*?" + SKIP_HINT
ASK_BIZ_EINVOICE = (
    "¿El negocio tiene la *facturación electrónica* de la DIAN al día?\n\n"
    "_Si no sabes, escribe *no sé*._"
)
ASK_BIZ_SOCIAL_SECURITY = (
    "¿Los trabajadores están *afiliados a la seguridad social* (salud, pensión y riesgos laborales) "
    "y los aportes están al día?" + SKIP_HINT
)
ASK_BIZ_ICA = "¿El negocio está al día con el *ICA* (Impuesto de Industria y Comercio) del municipio?" + SKIP_HINT
ASK_BIZ_PREDIAL = "¿Está al día con el *impuesto predial* del local?" + SKIP_HINT
# Nombres para la alerta de obligaciones pendientes (campo de Business -> nombre)
OBLIGATION_LABELS = {
    "rut_status": "RUT",
    "einvoice_status": "facturación electrónica",
    "social_security_status": "seguridad social",
    "ica_status": "ICA",
    "predial_status": "predial",
}

BIZ_DEBT_OPTIONS = (
    ("BANCO", "Un banco o financiera"),
    ("COOPERATIVA", "Una cooperativa o fondo de empleados"),
    ("PROVEEDORES", "Proveedores (mercancía a crédito)"),
    ("GOTA_A_GOTA", "Un prestamista informal o \"gota a gota\""),
    ("FAMILIARES", "Familiares o amigos"),
)
BIZ_INFORMAL_LENDER = "GOTA_A_GOTA"

ASK_BIZ_PAYMENT_ACCOUNT = "Si el negocio recibe un *apoyo en dinero*, ¿dónde lo podría recibir?"
BIZ_PAYMENT_ACCOUNT_SECTION = "Cuenta"
BIZ_PAYMENT_ACCOUNT_OPTIONS = (
    ("BANCO", "Cuenta bancaria", "Del negocio o del dueño"),
    ("BILLETERA", "Nequi, Daviplata u otra", "Billetera digital en el celular"),
    ("AMBAS", "Cuenta y billetera", ""),
    ("NINGUNA", "Ninguna", "No tiene dónde recibirlo"),
)

# --- Necesidades (selección múltiple) ---

# (id, título <= 24 para la lista de "la más urgente", texto de la opción numerada)
BIZ_NEED_OPTIONS = (
    ("CREDITO", "Crédito o refinanciación", "Crédito blando o refinanciación de deudas"),
    ("SUBSIDIO", "Subsidio o capital", "Subsidio o capital no reembolsable"),
    ("NOMINA", "Apoyo para la nómina", "Apoyo para pagar la nómina"),
    ("REPARACION", "Reparar el local", "Reparar o reforzar el local"),
    ("MAQUINARIA", "Reponer maquinaria", "Reponer maquinaria, herramientas o equipos"),
    ("INVENTARIO", "Reponer inventario", "Reponer mercancía o materia prima"),
    ("ARRIENDO", "Alivio de arriendo", "Alivio de arriendo, impuestos o servicios"),
    ("REUBICACION", "Reubicación temporal", "Reubicación temporal del negocio"),
    ("ASESORIA", "Asesoría", "Asesoría legal, contable o para reactivarse"),
    ("MERCADOS", "Clientes y ventas", "Clientes y ventas (ferias, compras públicas, plataformas)"),
)
ASK_BIZ_NEEDS = (
    "¿Qué necesita el negocio para *volver a funcionar*? Puedes elegir varias: responde con los números "
    "separados por coma (ejemplo: *1,4,6*):\n" + _numbered(tuple((v, label) for v, _, label in BIZ_NEED_OPTIONS))
)
ASK_BIZ_TOP_NEED = "De lo que marcaste, ¿qué es lo *más urgente*?"
BIZ_TOP_NEED_SECTION = "Lo más urgente"

ASK_BIZ_REP_NAME = "Escribe el *nombre completo del dueño o representante legal*." + SKIP_HINT
ASK_BIZ_REP_DOCUMENT = (
    "Escribe el *número de documento* del dueño o representante legal, sin puntos." + SKIP_HINT
)
INVALID_REP_DOCUMENT = "El documento debe tener entre 5 y 12 números o letras, sin puntos."
ASK_REPORTER_IDENTITY = "Gracias. Ahora necesitamos *tus* datos, como la persona que hace el reporte."
ASK_BIZ_DEBTS = (
    "¿El negocio tiene *deudas o créditos* con alguno de estos? Responde con los números separados por coma "
    "(ejemplo: *1,3*):\n" + _numbered(BIZ_DEBT_OPTIONS)
)

# --- Identidad ---------------------------------------------------------------------------

ASK_DOC_TYPE = "Ahora tus datos de identificación. ¿Qué *documento de identidad* tienes?"
DOC_TYPE_SECTION = "Documento"
DOC_NONE = "NINGUNO"
DOC_PASSPORT = "PASAPORTE"
DOC_CC = "CC"
DOC_TYPE_OPTIONS = (
    (DOC_CC, "Cédula de ciudadanía", ""),
    ("TI", "Tarjeta de identidad", "Menores de 18 años"),
    ("CE", "Cédula de extranjería", ""),
    ("PPT", "PPT", "Permiso por Protección Temporal"),
    (DOC_PASSPORT, "Pasaporte", ""),
    (DOC_NONE, "No tengo documento", "Lo perdí o no tengo"),
)
DOC_TYPE_LABELS = {value: title.lower() for value, title, _ in DOC_TYPE_OPTIONS}

ASK_ID_METHOD = "¿Tienes tu cédula *a mano* para tomarle una foto?"

ASK_CEDULA = (
    "Envía una *foto clara del frente de tu cédula*.\n"
    "Consejos: buena luz, sin reflejos y que se vea completa.\n\n"
    "_En el stand puedes usar la cédula de muestra._"
)
CEDULA_REUSED = "Usaremos los datos de identificación que ya registraste."
READING_CEDULA = "Recibimos la foto. Estamos leyendo tu cédula…"
ANALYZING_PHOTOS = "Estamos analizando las fotos y registrando tu reporte…"
OCR_RETRY = (
    "No pudimos leer bien la cédula. Intenta otra foto con más luz, sin reflejos "
    "y con la cédula completa dentro de la imagen."
)
OCR_FAILED_MANUAL = "Seguimos sin poder leerla. No te preocupes, escribe los datos a mano."
MEDIA_NOT_IMAGE = "Necesitamos una *foto* (no un PDF ni otro tipo de archivo)."
MEDIA_ERROR = "No pudimos descargar la imagen. ¿Puedes enviarla de nuevo?"


def confirm_id(full_name: str, document_id: str) -> str:
    return f"Leímos estos datos de tu cédula:\n\n*{full_name}*\nCC {document_id}\n\n¿Son correctos?"


ASK_MANUAL_NAME = "Escribe tu *nombre completo* (nombres y apellidos)."
INVALID_NAME = "Escribe tu nombre completo (nombres y apellidos)."


def ask_manual_document(doc_type: str | None) -> str:
    label = DOC_TYPE_LABELS.get(doc_type or DOC_CC, "documento")
    if doc_type == DOC_PASSPORT:
        return f"Escribe el *número de tu {label}*, tal como aparece en el documento."
    return f"Escribe el *número de tu {label}*, solo los números (sin puntos)."


INVALID_DOCUMENT = "El número debe tener entre 5 y 12 dígitos, sin puntos ni letras."
INVALID_PASSPORT = "El número de pasaporte debe tener entre 5 y 12 letras o números."

ASK_SELFIE_CONSENT = (
    "*Foto de tu rostro (opcional)*\n\n"
    "Como no enviaste foto de tu documento, puedes enviarnos una selfie para que el equipo que visite "
    "la vivienda pueda reconocerte.\n\n"
    "La foto del rostro es un *dato sensible (biométrico)*: no es obligatoria y tu reporte sigue igual "
    "si respondes No. Solo la ve el equipo de GeoAid y se elimina al terminar el evento.\n\n"
    "¿Autorizas el uso de una foto de tu rostro?"
)
ASK_SELFIE = (
    "Toma una *selfie de frente* con buena luz (mejor luz natural, sin contraluz). "
    "Sin gafas oscuras, gorra ni tapabocas, y que se vea todo tu rostro.\n\n"
    "Si prefieres no hacerlo, escribe *omitir*."
)
SELFIE_RECEIVED = "Gracias, recibimos tu foto."
SELFIE_SKIPPED = "Está bien, continuamos sin la foto."

def ask_damage_photos(business: bool = False) -> str:
    what = (
        "del negocio: fachada, grietas, mercancía, maquinaria o equipos dañados"
        if business
        else "de la vivienda: fachada, grietas o espacios afectados"
    )
    return f"Por último, envía *fotos de los daños* {what}.\nPuedes enviar de 1 a 3 fotos."


def photo_received(count: int, maximum: int) -> str:
    return f"Recibimos la foto {count} de {maximum}. Puedes enviar otra o pulsar *Listo* para terminar."


ASK_PHOTO_FIRST = "Aún no hemos recibido fotos. Envía al menos una foto del daño."


def submitted(code: str, business: bool = False, home_pending: bool = False) -> str:
    text = (
        "*Tu reporte quedó registrado.*\n\n"
        f"Código de seguimiento: *{code}*\n"
        "Estado: en revisión\n\n"
        "Guarda este código. Un equipo técnico revisará tu caso y priorizará la visita a "
        + ("tu negocio." if business else "tu vivienda.")
    )
    if home_pending:
        text += (
            "\n\nComo el negocio funciona en tu vivienda, puedes reportarla con *Reportar mi vivienda*, "
            "sin repetir la ubicación."
        )
    return text


MENU_PROMPT = "¿Qué quieres hacer ahora?"
MENU_BUTTON = "Ver opciones"
MENU_SECTION = "GeoAid"
NEW_REPORT = "Vamos a registrar el reporte de otra vivienda."
NEW_BUSINESS_REPORT = "Vamos a registrar el reporte de un negocio."
HOME_FROM_BUSINESS = (
    "Vamos a reportar tu vivienda. Usaremos la misma ubicación del negocio, "
    "así que seguimos con la situación del hogar."
)
NO_REPORTS = "Todavía no tienes reportes enviados."

LINK_COLLECTION_CENTERS = (
    f"Encuentra los centros de acopio abiertos cerca de ti y qué están recibiendo hoy:\n{WEB_URL}/centros-de-acopio"
)
LINK_MISSING = f"Busca o reporta a una persona desaparecida:\n{WEB_URL}/desaparecidos"
LINK_HELP_OTHERS = f"Si quieres ayudar, puedes donar o tomar un turno de voluntariado:\n{WEB_URL}/donar\n{WEB_URL}/voluntariado"
SUPPORT = (
    f"Puedes encontrar más ayuda en {WEB_URL}\n\n"
    f"Si hay riesgo para la vida, llama a la línea de emergencias *{EMERGENCY_LINE}*."
)

STATUS_LABELS = {
    "PENDIENTE_REVISION": "En revisión",
    "APROBADO": "Aprobado",
    "RECHAZADO": "No aprobado",
    "REQUIERE_INFO": "Necesitamos más información",
}


def status_summary(lines: list[str]) -> str:
    return "*Tus reportes:*\n\n" + "\n".join(lines)


HELP = (
    "Te estamos guiando paso a paso para registrar el daño de tu vivienda o de tu negocio.\n\n"
    "• Escribe *saltar* para pasar una pregunta que no quieras responder.\n"
    "• Escribe *cancelar* para descartar el reporte en curso.\n"
    f"• Más ayuda: {WEB_URL}\n"
    f"• Emergencias: *{EMERGENCY_LINE}*"
)
CANCELLED = "Listo, descartamos el reporte que estabas llenando."
DEMO_RESET = "Demo reiniciada. Este celular quedó listo para el siguiente visitante."
INVALID = "No entendí tu respuesta."
GENERIC_ERROR = "Tuvimos un problema procesando tu mensaje. Inténtalo de nuevo en unos minutos."
