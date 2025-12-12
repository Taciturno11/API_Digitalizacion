"""
CATÁLOGOS OFICIALES SUNAT - UBL 2.1
Basado en:
- Guía XML Factura Electrónica v2.1 (SUNAT)
- Anexos I-IV Resolución 318-2017/SUNAT

Este archivo centraliza todos los códigos para conversión automática.
"""

# =============================================================================
# CATÁLOGO N° 03 - UNIDADES DE MEDIDA (UN/ECE Rec 20)
# =============================================================================
# Referencia: Página 58 de la Guía XML SUNAT
# El XML usa códigos UN/ECE, pero la representación impresa usa nombres legibles

CATALOGO_03_UNIDAD_MEDIDA = {
    # Código XML → Nombre para representación impresa
    "NIU": "UNIDAD",           # UNIDAD (BIENES) - El más común
    "ZZ": "UNIDAD",            # UNIDAD (SERVICIOS)
    "UM": "MILLON DE UNIDADES",
    "KGM": "KILOGRAMO",
    "LTR": "LITRO",
    "MTR": "METRO",
    "MTK": "METRO CUADRADO",
    "MTQ": "METRO CUBICO",
    "GRM": "GRAMO",
    "TNE": "TONELADA",
    "BX": "CAJA",              # Box
    "PK": "PAQUETE",           # Pack
    "DZN": "DOCENA",
    "GLL": "GALON",
    "ONZ": "ONZA",
    "LBR": "LIBRA",
    "SET": "JUEGO",
    "ROL": "ROLLO",
    "BG": "BOLSA",
    "PR": "PAR",
    "MLT": "MILILITRO",
    "CMT": "CENTIMETRO",
    "INH": "PULGADA",
    "FOT": "PIE",
    "YRD": "YARDA",
    "GLI": "GALON IMPERIAL",
    "DAY": "DIA",
    "HUR": "HORA",
    "MON": "MES",
    "ANN": "AÑO",
    "MIN": "MINUTO",
    "SEC": "SEGUNDO",
    # Agregar más según necesidad del Anexo II
}

# =============================================================================
# CATÁLOGO N° 02 - TIPO DE MONEDA (ISO 4217)
# =============================================================================
CATALOGO_02_MONEDA = {
    "PEN": "SOLES",
    "USD": "DOLARES AMERICANOS",
    "EUR": "EUROS",
}

# =============================================================================
# CATÁLOGO N° 05 - CÓDIGOS DE TRIBUTOS
# =============================================================================
CATALOGO_05_TRIBUTOS = {
    "1000": {"nombre": "IGV", "codigo_internacional": "VAT", "descripcion": "Impuesto General a las Ventas"},
    "1016": {"nombre": "IVAP", "codigo_internacional": "VAT", "descripcion": "Impuesto a la Venta de Arroz Pilado"},
    "2000": {"nombre": "ISC", "codigo_internacional": "EXC", "descripcion": "Impuesto Selectivo al Consumo"},
    "9995": {"nombre": "EXP", "codigo_internacional": "FRE", "descripcion": "Exportación"},
    "9996": {"nombre": "GRA", "codigo_internacional": "FRE", "descripcion": "Gratuito"},
    "9997": {"nombre": "EXO", "codigo_internacional": "VAT", "descripcion": "Exonerado"},
    "9998": {"nombre": "INA", "codigo_internacional": "FRE", "descripcion": "Inafecto"},
    "9999": {"nombre": "OTROS", "codigo_internacional": "OTH", "descripcion": "Otros tributos"},
}

# =============================================================================
# CATÁLOGO N° 06 - TIPOS DE DOCUMENTO DE IDENTIDAD
# =============================================================================
CATALOGO_06_TIPO_DOCUMENTO = {
    "0": "DOC.TRIB.NO.DOM.SIN.RUC",
    "1": "DNI",
    "4": "CARNET DE EXTRANJERIA",
    "6": "RUC",
    "7": "PASAPORTE",
    "A": "CED. DIPLOMATICA DE IDENTIDAD",
    "B": "DOC.IDENT.PAIS.RESIDENCIA-NO.D",
    "C": "Tax Identification Number - TIN",
    "D": "Identification Number - IN",
    "E": "TAM- Tarjeta Andina de Migración",
}

# =============================================================================
# CATÁLOGO N° 01 - TIPO DE DOCUMENTO
# =============================================================================
CATALOGO_01_TIPO_DOCUMENTO = {
    "01": "FACTURA",
    "03": "BOLETA DE VENTA",
    "07": "NOTA DE CREDITO",
    "08": "NOTA DE DEBITO",
    "09": "GUIA DE REMISION REMITENTE",
    "31": "GUIA DE REMISION TRANSPORTISTA",
}

# =============================================================================
# CATÁLOGO N° 07 - TIPO DE AFECTACIÓN IGV
# =============================================================================
CATALOGO_07_TIPO_AFECTACION_IGV = {
    "10": "Gravado - Operación Onerosa",
    "11": "Gravado - Retiro por premio",
    "12": "Gravado - Retiro por donación",
    "13": "Gravado - Retiro",
    "14": "Gravado - Retiro por publicidad",
    "15": "Gravado - Bonificaciones",
    "16": "Gravado - Retiro por entrega a trabajadores",
    "17": "Gravado - IVAP",
    "20": "Exonerado - Operación Onerosa",
    "21": "Exonerado - Transferencia Gratuita",
    "30": "Inafecto - Operación Onerosa",
    "31": "Inafecto - Retiro por Bonificación",
    "32": "Inafecto - Retiro",
    "33": "Inafecto - Retiro por Muestras Médicas",
    "34": "Inafecto - Retiro por Convenio Colectivo",
    "35": "Inafecto - Retiro por premio",
    "36": "Inafecto - Retiro por publicidad",
    "40": "Exportación de Bienes o Servicios",
}

# =============================================================================
# CATÁLOGO N° 16 - TIPO DE PRECIO
# =============================================================================
CATALOGO_16_TIPO_PRECIO = {
    "01": "Precio unitario (incluye el IGV)",
    "02": "Valor referencial unitario en operaciones no onerosas",
}

# =============================================================================
# FUNCIONES DE CONVERSIÓN
# =============================================================================

def convertir_unidad_medida(codigo_xml: str) -> str:
    """
    Convierte código de unidad de medida XML (UN/ECE) a nombre legible SUNAT.
    Ej: "NIU" → "UNIDAD"
    """
    if not codigo_xml:
        return "UNIDAD"  # Default
    
    codigo_upper = codigo_xml.upper().strip()
    return CATALOGO_03_UNIDAD_MEDIDA.get(codigo_upper, codigo_upper)


def convertir_moneda(codigo_xml: str) -> str:
    """
    Convierte código de moneda ISO 4217 a nombre legible.
    Ej: "PEN" → "SOLES"
    """
    if not codigo_xml:
        return "SOLES"  # Default Perú
    
    codigo_upper = codigo_xml.upper().strip()
    return CATALOGO_02_MONEDA.get(codigo_upper, codigo_upper)


def obtener_nombre_tributo(codigo: str) -> str:
    """
    Obtiene el nombre del tributo desde el código SUNAT.
    Ej: "1000" → "IGV"
    """
    tributo = CATALOGO_05_TRIBUTOS.get(str(codigo), {})
    return tributo.get("nombre", "DESCONOCIDO")


def obtener_tipo_documento(codigo: str) -> str:
    """
    Obtiene el nombre del tipo de documento.
    Ej: "01" → "FACTURA"
    """
    return CATALOGO_01_TIPO_DOCUMENTO.get(str(codigo), "DOCUMENTO")


def validar_ruc(ruc: str) -> dict:
    """
    Valida un RUC peruano y retorna información.
    RUC de 11 dígitos:
    - Empieza con 10: Persona Natural
    - Empieza con 20: Persona Jurídica (Empresa)
    - Empieza con 15, 17: Sector Público
    """
    if not ruc or len(str(ruc)) != 11:
        return {"valido": False, "tipo": "INVALIDO", "mensaje": "RUC debe tener 11 dígitos"}
    
    ruc_str = str(ruc)
    prefijo = ruc_str[:2]
    
    tipos = {
        "10": "PERSONA NATURAL",
        "15": "SECTOR PUBLICO",
        "17": "SECTOR PUBLICO",
        "20": "PERSONA JURIDICA",
    }
    
    tipo = tipos.get(prefijo, "DESCONOCIDO")
    
    return {
        "valido": tipo != "DESCONOCIDO",
        "tipo": tipo,
        "ruc": int(ruc_str),
        "mensaje": f"RUC válido - {tipo}" if tipo != "DESCONOCIDO" else "Prefijo de RUC no reconocido"
    }


# =============================================================================
# CONSTANTES DE FORMATO
# =============================================================================

# Expresiones regulares para validación
REGEX_RUC_EMISOR = r'\b(10\d{9}|20\d{9})\b'  # 10 o 20 + 9 dígitos
REGEX_RUC_RECEPTOR = r'\b(10\d{9}|20\d{9})\b'
REGEX_NUMERO_FACTURA = r'[EF]\s*\d{3}\s*[-.\s]*\d+'  # E001-123, F001-456
REGEX_FECHA_DDMMYYYY = r'\d{2}/\d{2}/\d{4}'
REGEX_FECHA_YYYYMMDD = r'\d{4}-\d{2}-\d{2}'
REGEX_MONTO = r'\d{1,3}(?:,\d{3})*\.\d{2}'  # 1,234.56

# IGV estándar Perú
IGV_TASA = 0.18  # 18%
