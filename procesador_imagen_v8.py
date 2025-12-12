# -*- coding: utf-8 -*-
"""
PROCESADOR DE IMAGEN PARA FACTURAS ELECTRÓNICAS SUNAT
Versión 8: Tesseract OCR - Estructura IDÉNTICA al procesador PDF
"""

import re
import os
from PIL import Image, ImageEnhance
import pytesseract

# Configurar path de Tesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


def preprocesar_imagen(imagen_path):
    """Preprocesa la imagen para mejorar OCR."""
    img = Image.open(imagen_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img_gray = img.convert('L')
    enhancer = ImageEnhance.Contrast(img_gray)
    return enhancer.enhance(1.8)


def extraer_texto_tesseract(imagen_path):
    """Extrae texto usando Tesseract."""
    img = preprocesar_imagen(imagen_path)
    config = '--oem 3 --psm 4 -l spa'
    return pytesseract.image_to_string(img, config=config)


def limpiar_numero(texto):
    """Limpia texto para extraer número. Maneja formatos S/, 5/, etc."""
    if not texto:
        return 0.0
    texto = str(texto).strip()
    # Quitar S/, 5/, $, €, y espacios
    texto = re.sub(r'^[S5]\s*/\s*', '', texto)  # S/ o 5/ al inicio
    texto = re.sub(r'[S5]/\.?\s*', '', texto)   # S/ en cualquier lugar
    texto = texto.replace('$', '').replace('€', '').replace(' ', '')
    # Manejar coma como separador de miles
    texto = texto.replace(',', '')
    # Extraer número
    match = re.search(r'(\d+\.?\d*)', texto)
    return float(match.group(1)) if match else 0.0


def validar_ruc(ruc: str) -> bool:
    """
    Valida un RUC peruano verificando el dígito verificador.
    RUC debe tener 11 dígitos y empezar con 10, 15, 17 o 20.
    """
    if not ruc or len(ruc) != 11:
        return False

    if not ruc.startswith(('10', '15', '17', '20')):
        return False

    try:
        # Factores para el cálculo del dígito verificador
        factores = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
        suma = sum(int(ruc[i]) * factores[i] for i in range(10))
        resto = suma % 11
        digito_esperado = 11 - resto if resto > 1 else resto
        return int(ruc[10]) == digito_esperado
    except (ValueError, IndexError):
        return False


def extraer_cuentas_bancarias(texto: str) -> list:
    """
    Extrae números de cuentas bancarias del texto.
    Detecta: CCI (20 dígitos), cuentas corrientes, cuentas de ahorro.
    """
    cuentas = []

    # Patrones de cuentas bancarias peruanas
    patrones_cuentas = [
        # CCI - Código de Cuenta Interbancario (20 dígitos con guiones)
        (r'CCI[:\s]*(\d{3}[-\s]?\d{3}[-\s]?\d{12}[-\s]?\d{2})', 'CCI'),
        (r'CCI[:\s]*(\d{20})', 'CCI'),

        # Cuenta Corriente con formato común
        (r'(?:CTA\.?\s*(?:CTE|CORRIENTE)|CUENTA\s*CORRIENTE)[:\s#]*(\d{3}[-\s]?\d{6,8}[-\s]?\d{1,2}[-\s]?\d{2})', 'CUENTA_CORRIENTE'),
        (r'(?:CTA\.?\s*(?:CTE|CORRIENTE)|CUENTA\s*CORRIENTE)[:\s#]*(\d{10,14})', 'CUENTA_CORRIENTE'),

        # Cuenta de Ahorros
        (r'(?:CTA\.?\s*(?:AHO|AHORROS?)|CUENTA\s*(?:DE\s*)?AHORROS?)[:\s#]*(\d{3}[-\s]?\d{6,8}[-\s]?\d{1,2}[-\s]?\d{2})', 'CUENTA_AHORROS'),
        (r'(?:CTA\.?\s*(?:AHO|AHORROS?)|CUENTA\s*(?:DE\s*)?AHORROS?)[:\s#]*(\d{10,14})', 'CUENTA_AHORROS'),

        # Número de cuenta genérico después de palabras clave bancarias
        (r'(?:BANCO|BCP|BBVA|INTERBANK|SCOTIABANK|BN)[:\s]*(?:CTA\.?|CUENTA)?[:\s#]*(\d{3}[-\s]?\d{6,8}[-\s]?\d{1,2}[-\s]?\d{2})', 'CUENTA_BANCARIA'),

        # CCI en formato con guiones estándar
        (r'(\d{3}-\d{3}-\d{12}-\d{2})', 'CCI'),
    ]

    for patron, tipo in patrones_cuentas:
        matches = re.findall(patron, texto, re.IGNORECASE)
        for match in matches:
            numero = re.sub(r'[-\s]', '', match)  # Limpiar guiones y espacios
            if len(numero) >= 10 and numero not in [c['numero'] for c in cuentas]:
                cuentas.append({
                    'tipo': tipo,
                    'numero': numero,
                    'formato_original': match
                })

    return cuentas


def extraer_direccion_mejorada(texto: str, lineas: list, contexto: str = 'emisor') -> dict:
    """
    Extrae dirección con mayor precisión usando prefijos peruanos.
    Retorna dict con dirección, distrito, provincia, departamento.
    """
    resultado = {
        'direccion': '',
        'distrito': '',
        'provincia': '',
        'departamento': ''
    }

    # Prefijos comunes de direcciones peruanas
    prefijos = r'(?:CAL\.?|CALLE|AV\.?|AVENIDA|JR\.?|JIRON|JIRÓN|PSJE\.?|PASAJE|URB\.?|URBANIZACIÓN|URBANIZACION|MZA?\.?|MANZANA|LT\.?|LOTE|PJ\.?|PROLONGACIÓN|PROL\.?|CDRA\.?|CUADRA)'

    # Patrón para dirección completa con prefijo
    patron_direccion = rf'({prefijos}[.,]?\s*[A-ZÁÉÍÓÚÑa-záéíóúñ0-9\s,.\-#]+?)(?=\s*[-–]\s*[A-Z]{{3,}}|\s*(?:LIMA|CALLAO|AREQUIPA|CUSCO|TRUJILLO)|RUC|Señor|Cliente|\d{{11}}|$)'

    match = re.search(patron_direccion, texto, re.IGNORECASE)
    if match:
        resultado['direccion'] = re.sub(r'\s+', ' ', match.group(1).strip())

    # Extraer ubigeo: DISTRITO - PROVINCIA - DEPARTAMENTO
    patrones_ubigeo = [
        r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?)\s*[-–]\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?)\s*[-–]\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?)(?=\s*RUC|\s*Señor|\s*$|\s*\d{11})',
        r'(LIMA|CALLAO|SAN\s+\w+|MIRAFLORES|SURCO|LA\s+MOLINA|SAN\s+ISIDRO|JESUS\s+MARIA|LINCE|MAGDALENA|PUEBLO\s+LIBRE|SAN\s+MIGUEL|BREÑA|RIMAC|LA\s+VICTORIA|ATE|SANTA\s+ANITA|EL\s+AGUSTINO|SAN\s+JUAN\s+DE\s+\w+|VILLA\s+\w+|CHORRILLOS|BARRANCO|SURQUILLO)\s*[-–]\s*(LIMA)\s*[-–]\s*(LIMA)',
    ]

    for patron in patrones_ubigeo:
        match_ubigeo = re.search(patron, texto, re.IGNORECASE)
        if match_ubigeo:
            resultado['distrito'] = match_ubigeo.group(1).strip().upper()
            resultado['provincia'] = match_ubigeo.group(2).strip().upper()
            resultado['departamento'] = match_ubigeo.group(3).strip().upper()
            break

    # Si no encontró dirección con prefijo, buscar en líneas específicas
    if not resultado['direccion'] and contexto == 'emisor':
        for i, linea in enumerate(lineas):
            if re.search(prefijos, linea, re.IGNORECASE):
                resultado['direccion'] = linea.strip()
                # Buscar ubigeo en la siguiente línea
                if i + 1 < len(lineas):
                    sig_linea = lineas[i + 1]
                    if re.search(r'\w+\s*-\s*\w+\s*-\s*\w+', sig_linea):
                        resultado['direccion'] += ' ' + sig_linea.strip()
                break

    return resultado


def procesar_factura_img(imagen_path: str) -> dict:
    """
    Procesa una imagen de factura electrónica SUNAT.
    Retorna estructura IDÉNTICA al procesador PDF.
    """
    
    # Extraer texto
    texto_raw = extraer_texto_tesseract(imagen_path)
    texto = texto_raw.replace('\n', ' ')
    lineas = [l.strip() for l in texto_raw.split('\n') if l.strip()]
    
    # === INICIALIZAR ESTRUCTURA IDÉNTICA AL PDF (todos float como en PDF) ===
    factura = {
        "razonSocialEmisor": "",
        "direccionEmisor": "",
        "departamento": "",
        "provincia": "",
        "distrito": "",
        "rucEmisor": 0,
        "numeroFactura": "",
        "fechaEmision": "",
        "razonSocialReceptor": "",
        "rucReceptor": 0,
        "direccionReceptorFactura": "",
        "direccionCliente": "",
        "fechaContable": "",
        "tipoMoneda": "SOLES",
        "observacion": "",
        "formaPago": "",
        "lineaFactura": [],
        "ventaGratuita": 0.0,
        "descripcionImporteTotal": "",
        "subtotalVenta": 0.0,
        "anticipo": 0.0,
        "descuento": 0.0,
        "valorVenta": 0.0,
        "isc": 0.0,
        "igv": 0.0,
        "otrosCargos": 0.0,
        "otrosTributos": 0.0,
        "montoRedondeo": 0.0,
        "importeTotal": 0.0,
        "montoNetoPendientePago": 0.0,
        "totalCuota": 0,
        "cuotas": []
    }
    
    # === EXTRAER RUCs ===
    rucs = re.findall(r'\b(\d{11})\b', texto)
    rucs_validos = [r for r in rucs if r.startswith(('10', '20'))]
    
    for ruc in rucs_validos:
        if ruc.startswith('10') and factura["rucEmisor"] == 0:
            factura["rucEmisor"] = int(ruc)
        elif ruc.startswith('20') and factura["rucReceptor"] == 0:
            factura["rucReceptor"] = int(ruc)
    
    # === NÚMERO DE FACTURA ===
    match = re.search(r'([EFB]\d{3}-\d+)', texto)
    if match:
        factura["numeroFactura"] = match.group(1)
    
    # === FECHA DE EMISIÓN ===
    patrones_fecha = [
        r'Fecha\s*(?:de\s*)?Emisi[oó]n[:\s]*(\d{2}/\d{2}/\d{4})',
        r'Emisi[oó]n[:\s]*(\d{2}/\d{2}/\d{4})',
    ]
    for patron in patrones_fecha:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            factura["fechaEmision"] = match.group(1)
            factura["fechaContable"] = match.group(1)
            break
    
    # === FORMA DE PAGO (buscar en contexto de "Forma de pago:") ===
    match_pago = re.search(r'Forma\s*de\s*pago[:\s]*(Contado|Cr[eé]dito)', texto, re.IGNORECASE)
    if match_pago:
        pago = match_pago.group(1)
        if 'Contado' in pago:
            factura["formaPago"] = "Contado"
        else:
            factura["formaPago"] = "Crédito"
    elif re.search(r'Contado', texto, re.IGNORECASE):
        factura["formaPago"] = "Contado"
    elif re.search(r'Cr[eé]dito', texto, re.IGNORECASE):
        factura["formaPago"] = "Crédito"
    
    # === RAZÓN SOCIAL EMISOR ===
    # El nombre puede estar ANTES o DESPUÉS del RUC emisor
    ruc_emisor_idx = -1
    for i, linea in enumerate(lineas):
        if re.search(r'RUC[:\s]*10\d{9}', linea):
            ruc_emisor_idx = i
            # Verificar si el nombre está en la misma línea (antes del RUC)
            match_nombre = re.search(r'^(.+?)\s*RUC', linea)
            if match_nombre:
                factura["razonSocialEmisor"] = match_nombre.group(1).strip()
            break
    
    # Si no encontró nombre en la línea del RUC, buscar en línea anterior
    if not factura["razonSocialEmisor"] and ruc_emisor_idx > 0:
        for j in range(ruc_emisor_idx - 1, -1, -1):
            candidato = lineas[j].strip()
            if candidato and 'FACTURA' not in candidato.upper() and 'ELECTRONICA' not in candidato.upper():
                factura["razonSocialEmisor"] = candidato
                break
    
    # Si aún no hay nombre, buscar línea después del RUC
    if not factura["razonSocialEmisor"] and ruc_emisor_idx >= 0:
        for j in range(ruc_emisor_idx + 1, min(ruc_emisor_idx + 4, len(lineas))):
            nombre = lineas[j].strip()
            if nombre and not re.match(r'^(CAL|AV|JR|MZA|LOTE|URB|Ayacucho|Calle)', nombre, re.IGNORECASE):
                factura["razonSocialEmisor"] = nombre
                break
    
    # === DIRECCIÓN EMISOR ===
    for i, linea in enumerate(lineas):
        # Buscar línea que sea dirección (antes del número de factura)
        if re.search(r'^(CAL\.?|AV\.?|JR\.?|MZA\.?|LOTE|URB\.?|Ayacucho|Calle|Avenida|Jiron)', linea, re.IGNORECASE):
            # Solo si está antes del receptor
            if i < len(lineas) - 5:
                factura["direccionEmisor"] = linea.strip()
                break
    
    # === UBIGEO (Distrito - Provincia - Departamento) ===
    match = re.search(r'([A-Z]+)\s*-\s*([A-Z]+)\s*-\s*([A-Z]+)', texto)
    if match:
        factura["distrito"] = match.group(1).strip()
        factura["provincia"] = match.group(2).strip()
        factura["departamento"] = match.group(3).strip()
    
    # === RAZÓN SOCIAL RECEPTOR ===
    # Buscar líneas entre "Señor(es)" y "RUC 20..." - GENÉRICO
    ruc_receptor_idx = -1
    for i, linea in enumerate(lineas):
        if re.search(r'RUC\s*[:\s]*20\d{9}', linea):
            ruc_receptor_idx = i
            break
    
    if ruc_receptor_idx > 0:
        nombre_receptor_partes = []
        # Buscar hacia atrás desde el RUC receptor
        for j in range(ruc_receptor_idx - 1, max(ruc_receptor_idx - 5, 0), -1):
            linea = lineas[j].strip()
            # Limpiar prefijos como "Señor(es)", "Señ", "ñor(es)"
            linea = re.sub(r'^Se[ñn]or\(?es\)?\s*[:\s]*', '', linea)
            linea = re.sub(r'^[ñn]or\(?es\)?\s*[:\s]*', '', linea)
            linea = re.sub(r'^Se[ñn]\s*', '', linea)
            
            # Si la línea contiene palabras relevantes del nombre
            if linea and not re.search(r'(Fecha|Emisi|pago|RUC|\d{11}|Cr[eé]dito|Contado)', linea, re.IGNORECASE):
                nombre_receptor_partes.insert(0, linea)
            
            # Parar si llegamos a la línea de fecha
            if 'Fecha' in lineas[j] or 'Emisión' in lineas[j] or re.search(r'\d{2}/\d{2}/\d{4}', lineas[j]):
                break
        
        if nombre_receptor_partes:
            nombre_completo = ' '.join(nombre_receptor_partes)
            # Limpiar duplicaciones
            nombre_completo = re.sub(r'\s*Se[ñn]or\(?es\)?\s*', ' ', nombre_completo)
            factura["razonSocialReceptor"] = nombre_completo.strip()
    
    # === DIRECCIONES RECEPTOR ===
    # Buscar direcciones después del RUC receptor hasta "Dirección del Cliente"
    if ruc_receptor_idx > 0:
        dir_receptor_partes = []
        dir_cliente_partes = []
        en_dir_receptor = True
        en_dir_cliente = False
        
        for j in range(ruc_receptor_idx + 1, min(ruc_receptor_idx + 20, len(lineas))):
            linea = lineas[j].strip()
            
            # Detectar "Dirección del Cliente"
            if 'Direcci' in linea and 'Cliente' in linea:
                en_dir_receptor = False
                en_dir_cliente = True
                # Extraer contenido después de ":"
                match = re.search(r'Cliente[:\s]*(.+)$', linea)
                if match:
                    dir_cliente_partes.append(match.group(1).strip())
                continue
            
            # Detectar fin de direcciones
            if re.search(r'^(Tipo|Moneda|Observaci|Cantidad|OPERACI)', linea, re.IGNORECASE):
                break
            
            # Limpiar línea de "Dirección del Receptor..."
            linea_limpia = re.sub(r'Direcci[oó]n del Receptor.*?:\s*', '', linea)
            
            if linea_limpia:
                if en_dir_cliente:
                    dir_cliente_partes.append(linea_limpia)
                elif en_dir_receptor:
                    dir_receptor_partes.append(linea_limpia)
        
        # Combinar dirección receptor
        if dir_receptor_partes:
            dir_completa = ' '.join(dir_receptor_partes)
            dir_completa = dir_completa.replace('EL.', 'EL')
            dir_completa = re.sub(r'\s+', ' ', dir_completa).strip()
            
            # Detectar y limpiar duplicaciones
            # Si hay más de una dirección (AV. aparece 2+ veces), tomar solo la primera completa
            av_count = len(re.findall(r'AV\.', dir_completa, re.IGNORECASE))
            if av_count >= 2:
                # Encontrar el fin de la primera dirección (antes del segundo AV.)
                partes = re.split(r'\s+AV\.', dir_completa)
                if partes:
                    dir_completa = partes[0].strip()
            
            factura["direccionReceptorFactura"] = dir_completa
        
        # Dirección del Cliente - usar la parte después de "Dirección del Cliente:"
        # Si está incompleta, complementar con parte de direccionReceptorFactura
        if dir_cliente_partes:
            dir_cliente = ' '.join(dir_cliente_partes)
            dir_cliente = dir_cliente.replace('EL.', 'EL')
            dir_cliente = re.sub(r'\s+', ' ', dir_cliente).strip()
            
            # Si la dirección del cliente parece incompleta (empieza con CRUCE), agregar prefijo
            if dir_cliente.startswith('CRUCE') and factura["direccionReceptorFactura"]:
                # Extraer la parte de AV. hasta antes de CRUCE de la dirección receptor
                match_av = re.search(r'^(AV\..*?(?:LOTE\.?\s*\d+[A-Z]?))', factura["direccionReceptorFactura"], re.IGNORECASE)
                if match_av:
                    prefijo = match_av.group(1).strip()
                    # Agregar guion antes de COO. si existe
                    prefijo = prefijo.replace(' COO.', ' - COO.')
                    dir_cliente = prefijo + ' ' + dir_cliente
            
            # Cambiar LIMA LIMA a LIMA-LIMA si existe
            dir_cliente = re.sub(r'LIMA\s+LIMA', 'LIMA-LIMA', dir_cliente)
            
            factura["direccionCliente"] = dir_cliente
    
    # === TIPO DE MONEDA ===
    # Buscar específicamente "Tipo de Moneda" en el texto
    match_moneda = re.search(r'Tipo\s*(?:de\s*)?Moneda[:\s]*(SOLES|DOLARES|D[OÓ]LAR|PEN|USD)', texto, re.IGNORECASE)
    if match_moneda:
        moneda = match_moneda.group(1).upper()
        if 'DOLAR' in moneda or 'USD' in moneda:
            factura["tipoMoneda"] = "DOLARES"
        else:
            factura["tipoMoneda"] = "SOLES"
    elif re.search(r'D[OÓ]LARES|USD', texto, re.IGNORECASE):
        factura["tipoMoneda"] = "DOLARES"
    else:
        factura["tipoMoneda"] = "SOLES"
    
    # === OBSERVACIÓN (buscar en líneas para capturar texto dividido) ===
    obs_partes = []
    en_obs = False
    for linea in lineas:
        # Buscar "OPERACIÓN SUJETA" que puede estar antes de "Observación"
        if 'OPERACI' in linea.upper() and 'SUJETA' in linea.upper():
            obs_partes.append(linea.strip())
        # Buscar línea de Observación
        if 'Observaci' in linea:
            en_obs = True
            match = re.search(r'Observaci[oó]n[:\s]*(.+)$', linea)
            if match and match.group(1).strip():
                obs_partes.append(match.group(1).strip())
            continue
        if en_obs:
            # Parar en Cantidad o Unidad
            if re.search(r'^(Cantidad|Unidad)', linea):
                break
            if linea.strip():
                obs_partes.append(linea.strip())
    
    if obs_partes:
        obs_texto = ' '.join(obs_partes)
        # Extraer CTA.CTE
        match_cta = re.search(r'(CTA\.?\s*CTE\s*BN\s*N\.?\s*\d+)', obs_texto, re.IGNORECASE)
        if match_cta:
            cta = match_cta.group(1).upper().replace(' ', '')
            cta = re.sub(r'CTA\.?CTE', 'CTA.CTE ', cta)
            cta = re.sub(r'BNN\.?', 'BN N.', cta)
            # Buscar prefijo
            match_prefijo = re.search(r'(OPERACI[OÓ]N\s+SUJETA\s+(?:AL\s+SPOD|DEL\s+PODER))', obs_texto, re.IGNORECASE)
            if match_prefijo:
                prefijo = match_prefijo.group(1).upper()
                prefijo = prefijo.replace('OPERACION', 'OPERACIÓN')
                factura["observacion"] = prefijo + " " + cta
            else:
                factura["observacion"] = "OPERACIÓN SUJETA AL SPOD " + cta
        else:
            factura["observacion"] = obs_texto
    
    # === LÍNEA DE FACTURA ===
    valor_unitario = 0.0
    cantidad = 1.0
    descripcion = ""
    
    # Buscar patrón: cantidad UNIDAD descripción valor
    match = re.search(r'(\d+\.?\d*)\s*UNIDAD[:\s]*(.+?)\s+(\d{3,}\.00)', texto, re.IGNORECASE)
    if match:
        cantidad = float(match.group(1))
        valor_unitario = float(match.group(3))
    
    # Buscar descripción específica: después de UNIDAD y valor hasta PENDIENTE o valor
    match_desc = re.search(r'UNIDAD[:\s]*(\d{2}-\d{2}-\d{4}-\d+\s+.+?)\s+\d{4}\.00', texto, re.IGNORECASE)
    if match_desc:
        descripcion = match_desc.group(1).strip()
    
    # Buscar parte PENDIENTE
    match_pendiente = re.search(r'PENDIENTE\s+(.+?)(?=Valor\s+de|Sub\s*Total|$)', texto, re.IGNORECASE)
    if match_pendiente:
        parte_pendiente = match_pendiente.group(1).strip()
        # Limpiar
        parte_pendiente = re.sub(r'\s+', ' ', parte_pendiente)
        parte_pendiente = re.sub(r'\s*\d+\.00.*$', '', parte_pendiente)
        if descripcion:
            descripcion = descripcion + " PENDIENTE " + parte_pendiente
        else:
            descripcion = "PENDIENTE " + parte_pendiente
    
    factura["lineaFactura"] = [{
        "cantidad": float(cantidad),
        "unidadMedida": "UNIDAD",
        "descripcion": descripcion,
        "valorUnitario": float(valor_unitario)
    }]
    
    # === TOTALES - Calcular desde valor unitario ===
    if valor_unitario > 0:
        factura["subtotalVenta"] = float(valor_unitario * cantidad)
        factura["valorVenta"] = float(valor_unitario * cantidad)
        factura["igv"] = round(factura["valorVenta"] * 0.18, 2)
        factura["importeTotal"] = round(factura["valorVenta"] + factura["igv"], 2)
    
    # === DESCRIPCIÓN IMPORTE TOTAL (SON:...) ===
    match = re.search(r'SON[:\s]*(.+?)(?=ISC|IGV|Otros|$)', texto, re.IGNORECASE)
    if match:
        desc_total = match.group(1).strip()
        # Limpiar basura del OCR ("sc 00", "150:", "161:", números extraños, corchetes)
        desc_total = re.sub(r'\s*sc\s*\d+\s*', ' ', desc_total, flags=re.IGNORECASE)
        desc_total = re.sub(r'\s*\d{2,3}:\s*[\d\.]+\s*', ' ', desc_total)  # Quitar "150: 0.00"
        desc_total = re.sub(r'\s*\d{6,}\]?\s*', ' ', desc_total)  # Quitar números largos
        desc_total = re.sub(r'[\[\]]', '', desc_total)  # Quitar corchetes
        desc_total = re.sub(r'\s+', ' ', desc_total).strip()
        # Asegurar que termine con SOLES si es la moneda
        if 'SOLES' not in desc_total and factura["tipoMoneda"] == "SOLES":
            desc_total = desc_total + " SOLES"
        factura["descripcionImporteTotal"] = desc_total
    
    # === CUOTAS ===
    # Buscar cuotas en la sección de "Información del crédito" o después de "Total de Cuotas"
    cuotas_match = re.findall(r'(\d{2}/\d{2}/\d{4})\s+([\d,]+\.\d{2})', texto_raw)
    
    fecha_emision = factura["fechaEmision"]
    num_cuota = 1
    
    # Las cuotas aparecen después de la sección de totales
    # Solo filtrar si la fecha coincide con emisión Y el monto es muy grande (no es cuota)
    for fecha, monto in cuotas_match:
        monto_num = limpiar_numero(monto)
        # Una cuota típica es entre 100 y 50000
        if 100 < monto_num < 50000:
            factura["cuotas"].append({
                "numero": num_cuota,
                "fechaVencimiento": fecha,
                "monto": float(monto_num)
            })
            num_cuota += 1
    
    factura["totalCuota"] = len(factura["cuotas"])
    
    # === MONTO PENDIENTE ===
    match = re.search(r'(?:pendiente|Monto\s+neto)[^S]*S/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["montoNetoPendientePago"] = limpiar_numero(match.group(1))
    else:
        # Calcular como suma de cuotas
        factura["montoNetoPendientePago"] = sum(c["monto"] for c in factura["cuotas"])
    
    # === RETORNAR CON ESTRUCTURA IDÉNTICA AL PDF ===
    return {
        "factura": factura,
        "validacion": []
    }


# Prueba directa
if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        resultado = procesar_factura_img(sys.argv[1])
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
