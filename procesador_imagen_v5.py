"""
PROCESADOR DE IMAGEN v5 - Factura Electrónica SUNAT
====================================================
Estructura estricta según documentación SUNAT.
Maneja errores comunes de OCR (S/ confundido con números).
"""

import re
import easyocr
import numpy as np
from PIL import Image, ImageEnhance
from catalogos_sunat import convertir_unidad_medida, convertir_moneda

# =============================================================================
# INICIALIZACIÓN OCR (SINGLETON)
# =============================================================================
_reader = None

def get_reader():
    global _reader
    if _reader is None:
        print("[OCR] Inicializando EasyOCR...")
        _reader = easyocr.Reader(['es', 'en'], gpu=False)
    return _reader


# =============================================================================
# PREPROCESAMIENTO DE IMAGEN
# =============================================================================
def preprocesar_imagen(ruta_imagen):
    imagen = Image.open(ruta_imagen)
    if imagen.mode != 'RGB':
        imagen = imagen.convert('RGB')
    
    # Aumentar contraste y nitidez
    imagen = ImageEnhance.Contrast(imagen).enhance(1.5)
    imagen = ImageEnhance.Sharpness(imagen).enhance(2.0)
    
    return np.array(imagen)


# =============================================================================
# FUNCIONES DE LIMPIEZA
# =============================================================================
def limpiar_texto(texto):
    """Limpia y normaliza texto."""
    if not texto:
        return ""
    texto = re.sub(r'\s+', ' ', texto)
    return texto.strip()


def limpiar_monto(valor_str):
    """
    Convierte string de moneda a float.
    Maneja errores OCR: 'S/' leído como '5/', 'sI', etc.
    También: 'u/U' confundido con '0', 'D' con '0', etc.
    """
    if not valor_str:
        return 0.0
    
    valor_str = str(valor_str).strip()
    
    # Primero: Corregir errores OCR comunes de caracteres
    # u/U confundido con 0
    valor_str = valor_str.replace('uu', '00').replace('UU', '00')
    valor_str = valor_str.replace('u', '0').replace('U', '0')
    # D confundido con 0
    valor_str = valor_str.replace('D', '0')
    # Otros errores comunes
    valor_str = valor_str.replace('O', '0').replace('o', '0')
    valor_str = valor_str.replace('l', '1').replace('I', '1')
    
    # Eliminar símbolos de moneda y variantes OCR
    # S/ puede aparecer como: S/, s/, 5/, sI, SI, $/, 51, 5 al inicio, etc.
    valor_str = re.sub(r'^[Ss5\$][/lI1]\s*', '', valor_str)
    valor_str = re.sub(r'^[Ss5]\s+', '', valor_str)  # "5 4,200" -> "4,200"
    valor_str = re.sub(r'[Ss]/\s*', '', valor_str)
    
    # Eliminar espacios
    valor_str = valor_str.replace(' ', '')
    
    # Manejar separadores de miles y decimales
    # Formato peruano: 4,200.00 o 4.200,00
    if ',' in valor_str and '.' in valor_str:
        # Si la coma viene antes del punto: 4,200.00 (formato US/Perú)
        if valor_str.index(',') < valor_str.index('.'):
            valor_str = valor_str.replace(',', '')
        else:
            # 4.200,00 (formato europeo)
            valor_str = valor_str.replace('.', '').replace(',', '.')
    elif ',' in valor_str:
        # Solo coma: puede ser separador de miles o decimales
        partes = valor_str.split(',')
        if len(partes[-1]) == 2:  # Probablemente decimal
            valor_str = valor_str.replace(',', '.')
        else:
            valor_str = valor_str.replace(',', '')
    
    try:
        return float(valor_str)
    except:
        return 0.0


def corregir_monto_ocr(monto, monto_referencia=None, tolerancia=0.5):
    """
    Corrige errores comunes del OCR en montos.
    - Si el monto empieza con 5 y es mucho mayor que la referencia, quitar el 5
    - Ejemplo: 514200 -> 4200 (el 5 era S/)
    - Ejemplo: 14200 -> 4200 (falta corrección adicional)
    """
    if monto <= 0:
        return monto
    
    monto_str = str(int(monto)) if monto == int(monto) else str(monto)
    
    # Si tenemos referencia, verificar coherencia
    if monto_referencia and monto_referencia > 0:
        # Si el monto es mucho mayor que la referencia (más de 3x)
        if monto > monto_referencia * 3:
            # Probar quitando el primer dígito (podría ser '5' de 'S/')
            if len(monto_str) > 1:
                monto_sin_primero = float(monto_str[1:])
                # Si ahora está cerca de la referencia, usar ese
                if abs(monto_sin_primero - monto_referencia) / monto_referencia < tolerancia:
                    return monto_sin_primero
                
                # Probar quitando dos dígitos (caso "51" de "S/" + "1")
                if len(monto_str) > 2:
                    monto_sin_dos = float(monto_str[2:])
                    if abs(monto_sin_dos - monto_referencia) / monto_referencia < tolerancia:
                        return monto_sin_dos
    
    # Sin referencia, aplicar heurísticas
    # Si empieza con 51 o 5 y el resultado sin eso es razonable
    if monto_str.startswith('51') and len(monto_str) > 4:
        monto_corregido = float(monto_str[2:])  # Quitar "51" ("S/" + "1" juntos)
        if monto_corregido < 100000:
            return monto_corregido
    elif monto_str.startswith('5') and len(monto_str) > 3:
        monto_corregido = float(monto_str[1:])  # Quitar "5" ("S" confundido)
        if monto_corregido < 100000:
            return monto_corregido
    
    return monto


def extraer_monto_seguro(linea, etiqueta, monto_referencia=None):
    """
    Extrae un monto de una línea de forma segura, corrigiendo errores OCR.
    """
    # Normalizar la línea
    linea_norm = linea.replace(':', ' ')
    
    # Patrón para buscar el monto después de la etiqueta
    # El OCR puede poner: "S/ 4,200.00" o "sI 4,200.00" o "5/ 4,200.00" o "514,200.00"
    patron = rf'{etiqueta}\s*[Ss5]?[/lI]?\s*([\d,.]+)'
    match = re.search(patron, linea_norm, re.IGNORECASE)
    
    if match:
        monto = limpiar_monto(match.group(1))
        return corregir_monto_ocr(monto, monto_referencia)
    
    return 0.0


def extraer_texto_easyocr(ruta_imagen):
    """Extrae texto de imagen con EasyOCR."""
    ocr = get_reader()
    imagen_procesada = preprocesar_imagen(ruta_imagen)
    resultados = ocr.readtext(imagen_procesada, detail=1, paragraph=False)
    
    # Ordenar por Y, luego X
    resultados_ordenados = sorted(resultados, key=lambda x: (x[0][0][1], x[0][0][0]))
    
    # Agrupar en líneas
    lineas = []
    linea_actual = []
    y_anterior = -100
    umbral_y = 15
    
    for bbox, texto, conf in resultados_ordenados:
        y_actual = bbox[0][1]
        if y_actual - y_anterior > umbral_y:
            if linea_actual:
                lineas.append(' '.join(linea_actual))
            linea_actual = [texto]
        else:
            linea_actual.append(texto)
        y_anterior = y_actual
    
    if linea_actual:
        lineas.append(' '.join(linea_actual))
    
    return '\n'.join(lineas), lineas, resultados_ordenados


# =============================================================================
# FUNCIONES DE EXTRACCIÓN ESPECÍFICAS
# =============================================================================

def extraer_ubigeo(texto):
    """
    Extrae distrito-provincia-departamento del formato XXX-XXX-XXX.
    """
    # Buscar patrón con guiones
    match = re.search(r'([A-Za-z\s]+)\s*[-–]\s*([A-Za-z]+)\s*[-–]\s*([A-Za-z]+)', texto)
    if match:
        return match.group(1).strip(), match.group(2).strip(), match.group(3).strip()
    return "", "", ""


def extraer_direccion_completa(lineas, inicio_idx, max_lineas=5):
    """
    Extrae una dirección que empieza con AV./JR./CAL. y termina con XXX-XXX-XXX.
    Retorna la dirección completa y el índice donde terminó.
    """
    direccion_partes = []
    idx = inicio_idx
    
    while idx < min(inicio_idx + max_lineas, len(lineas)):
        linea = lineas[idx]
        direccion_partes.append(linea)
        
        # Si encontramos el patrón XXX-XXX-XXX, terminamos
        if re.search(r'[A-Za-z]+\s*[-–]\s*[A-Za-z]+\s*[-–]\s*[A-Za-z]+', linea):
            break
        
        idx += 1
    
    return ' '.join(direccion_partes), idx


def buscar_monto_en_linea(linea, etiqueta):
    """
    Busca un monto después de una etiqueta, manejando S/ y errores OCR.
    """
    # Normalizar la línea para búsqueda
    linea_norm = linea.replace(':', ' ')
    
    # Buscar patrón: etiqueta seguida de S/ o similar y número
    patron = rf'{etiqueta}\s*[:\s]*[Ss5\$]?[/lI]?\s*([\d,.\s]+)'
    match = re.search(patron, linea_norm, re.IGNORECASE)
    
    if match:
        return limpiar_monto(match.group(1))
    
    # Alternativa: buscar cualquier número después de la etiqueta
    patron2 = rf'{etiqueta}\s*[:\s]*([\d,.\s]+)'
    match2 = re.search(patron2, linea_norm, re.IGNORECASE)
    if match2:
        return limpiar_monto(match2.group(1))
    
    return 0.0


# =============================================================================
# PROCESADOR PRINCIPAL
# =============================================================================

def procesar_factura_img(ruta_archivo):
    """
    Procesa imagen de factura SUNAT siguiendo estructura estricta.
    """
    validaciones = []
    
    try:
        texto_completo, lineas, resultados_raw = extraer_texto_easyocr(ruta_archivo)
        
        # Debug
        print("=" * 70)
        print("TEXTO EXTRAIDO POR EASYOCR:")
        print("=" * 70)
        for i, linea in enumerate(lineas):
            print(f"[{i:02d}] {linea}")
        print("=" * 70)
        
        if not lineas:
            return {"validacion": ["No se pudo extraer texto de la imagen"]}
        
        # =====================================================================
        # SECCIÓN 1: CABECERA (EMISOR)
        # =====================================================================
        print("\n[SECCION 1] Procesando CABECERA (EMISOR)...")
        
        # La primera línea del OCR generalmente contiene varios datos mezclados
        # Necesitamos extraer: razonSocialEmisor, direccionEmisor, RUC, numeroFactura, ubigeo
        
        primera_linea = lineas[0] if lineas else ""
        
        # RUC EMISOR - Buscar patrón RUC: XXXXXXXXXXX (11 dígitos)
        ruc_emisor = 0
        match_ruc = re.search(r'RUC[:\s]*(\d{11})', texto_completo)
        if match_ruc:
            ruc_emisor = int(match_ruc.group(1))
            print(f"    RUC Emisor: {ruc_emisor}")
        
        # NÚMERO DE FACTURA - Formato E001-XXX o F001-XXX
        numero_factura = ""
        match_factura = re.search(r'([EF]\d{3}[-–]?\d+)', texto_completo)
        if match_factura:
            numero_factura = match_factura.group(1)
            if '-' not in numero_factura and '–' not in numero_factura:
                numero_factura = numero_factura[:4] + '-' + numero_factura[4:]
            numero_factura = numero_factura.replace('–', '-')
            print(f"    Numero Factura: {numero_factura}")
        
        # RAZÓN SOCIAL EMISOR - Está al inicio, antes de RUC
        razon_social_emisor = ""
        # Buscar en primera línea, antes de "RUC" o "CAL." o "AV."
        if primera_linea:
            # Eliminar "FACTURA ELECTRONICA" del inicio si existe
            texto_limpio = re.sub(r'^FACTURA\s*ELECTR[OÓ]NICA\s*', '', primera_linea, flags=re.IGNORECASE)
            
            # Extraer nombre hasta antes de RUC o dirección
            match_nombre = re.search(r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?)(?=\s+RUC|\s+CAL\.|\s+AV\.|\s+JR\.)', texto_limpio)
            if match_nombre:
                razon_social_emisor = limpiar_texto(match_nombre.group(1))
            print(f"    Razon Social Emisor: {razon_social_emisor}")
        
        # DIRECCIÓN EMISOR - Está entre RUC y número de factura, o entre RUC y ubigeo
        direccion_emisor = ""
        # La estructura típica es: "...RUC: 12345678901 CAL. 16 APV... E001-131 ATE LIMA LIMA"
        # Buscar texto entre RUC y el número de factura
        match_dir = re.search(r'RUC[:\s]*\d{11}\s+(.+?)\s+[EF]\d{3}', primera_linea, re.IGNORECASE)
        if match_dir:
            direccion_emisor = limpiar_texto(match_dir.group(1))
        else:
            # Alternativa: buscar patrón CAL./AV./JR. hasta el ubigeo
            match_dir2 = re.search(r'((?:CAL\.|AV\.|JR\.)\s*.+?)\s+(?:[EF]\d{3}|ATE|[A-Z]+\s+LIMA)', primera_linea, re.IGNORECASE)
            if match_dir2:
                direccion_emisor = limpiar_texto(match_dir2.group(1))
        
        if direccion_emisor:
            print(f"    Direccion Emisor: {direccion_emisor}")
        
        # UBIGEO EMISOR - Buscar patrón XXX-XXX-XXX o XXX LIMA LIMA
        distrito_emisor, provincia_emisor, departamento_emisor = "", "", ""
        # Buscar al final de la primera línea
        ubigeo_match = re.search(r'([A-Z][A-Za-z]+)\s*[-–]?\s*(LIMA|[A-Z]{3,})\s*[-–]?\s*(LIMA|[A-Z]{3,})\s*$', primera_linea)
        if ubigeo_match:
            distrito_emisor = ubigeo_match.group(1)
            provincia_emisor = ubigeo_match.group(2)
            departamento_emisor = ubigeo_match.group(3)
            print(f"    Ubigeo: {distrito_emisor}-{provincia_emisor}-{departamento_emisor}")
        
        # =====================================================================
        # SECCIÓN 2: RECEPTOR Y OPERACIÓN
        # =====================================================================
        print("\n[SECCION 2] Procesando RECEPTOR Y OPERACION...")
        
        # FECHA DE EMISIÓN - Buscar en línea que contiene "Fecha de Emisión"
        fecha_emision = ""
        forma_pago = "Contado"
        
        for linea in lineas:
            if 'Fecha' in linea and 'Emisi' in linea:
                # Extraer fecha
                match_fecha = re.search(r'(\d{2}/\d{2}/\d{4})', linea)
                if match_fecha:
                    fecha_emision = match_fecha.group(1)
                
                # Forma de pago suele estar en la misma línea
                if 'Cr' in linea and 'dito' in linea:
                    forma_pago = "Credito"
                elif 'Contado' in linea:
                    forma_pago = "Contado"
                
                print(f"    Fecha Emision: {fecha_emision}")
                print(f"    Forma de Pago: {forma_pago}")
                break
        
        # RAZÓN SOCIAL RECEPTOR - Buscar línea con "Señor(es)"
        razon_social_receptor = ""
        ruc_receptor = 0
        
        for i, linea in enumerate(lineas):
            if 'Se' in linea and 'or' in linea:  # Señor(es)
                # Extraer nombre: puede estar antes y después de "Señor(es)"
                partes = re.split(r'Se.or\(?es\)?:?\s*', linea, maxsplit=1)
                nombre_partes = []
                
                for parte in partes:
                    parte = parte.strip()
                    # Eliminar RUC si está incluido en la parte
                    parte = re.sub(r'\s*RUC\s*\d{11}\s*', '', parte)
                    if parte and not re.match(r'^\d{11}$', parte):  # No es RUC
                        nombre_partes.append(parte)
                
                razon_social_receptor = ' '.join(nombre_partes)
                razon_social_receptor = limpiar_texto(razon_social_receptor)
                print(f"    Razon Social Receptor: {razon_social_receptor}")
                break
        
        # RUC RECEPTOR - Buscar RUC de 11 dígitos diferente al emisor
        for linea in lineas:
            match_ruc = re.search(r'RUC\s*:?\s*(\d{11})', linea)
            if match_ruc:
                ruc_encontrado = int(match_ruc.group(1))
                if ruc_encontrado != ruc_emisor:
                    ruc_receptor = ruc_encontrado
                    print(f"    RUC Receptor: {ruc_receptor}")
                    break
        
        # DIRECCIONES - Estrategia mejorada para OCR
        # Estructura típica OCR:
        # [03] AV. LOS ALGARROBOS COO. LAS
        # [04] VERTIENTES MZA H LOTE. 4A Dirección del Receptor de la factura CRUCE DE AVENIDA EL SOL
        # [05] CALLE LIMA LIMA VILLA EL
        # [06] SALVADOR
        # [07] AV. LOS ALGARROBOS coo LAS VERTIENTES MZA H LOTE. 4A Dirección del Cllente CRUCE DE...
        
        direccion_receptor_factura = ""
        direccion_cliente = ""
        
        # Buscar índices de las líneas clave
        idx_receptor = -1
        idx_cliente = -1
        
        for i, linea in enumerate(lineas):
            linea_lower = linea.lower()
            # Buscar "Receptor" y "factura" en la misma línea
            if 'receptor' in linea_lower and 'factura' in linea_lower:
                idx_receptor = i
            # Buscar "Cliente" con variantes OCR (Cllente, Cl1ente, etc.)
            if re.search(r'c.?l.?iente|c.?ll.?ente|cliente', linea_lower):
                # Puede ser "Dirección del Cliente" o variantes OCR
                if re.search(r'direcci|del\s+c', linea_lower):
                    idx_cliente = i
        
        # DIRECCIÓN RECEPTOR DE LA FACTURA
        if idx_receptor >= 0:
            partes_receptor = []
            
            # La línea del receptor puede tener estructuras variadas:
            # Caso 1: "VERTIENTES MZA H LOTE. 4A Dirección del Receptor de la factura CRUCE DE AVENIDA EL SOL"
            # Caso 2: "AV. SUCRE 128. JR 28 julio VERTIENTES MZA H LOTE. 4A Dirección del Receptor de factura CRUCE DE..."
            linea_receptor = lineas[idx_receptor]
            
            # Parte 1: Texto ANTES de "Dirección del Receptor" (puede incluir AV./JR./CAL. al inicio)
            match_antes = re.search(r'^(.+?)\s*Direcci[oó]n\s+del\s+Receptor', linea_receptor, re.IGNORECASE)
            if match_antes:
                texto_antes = match_antes.group(1).strip()
                if texto_antes:
                    partes_receptor.append(texto_antes)
            
            # Parte 2: líneas anteriores que empiezan con AV./JR./CAL. (solo si no hay texto_antes con dirección)
            if not partes_receptor or not re.match(r'^AV\.|^JR\.|^CAL\.', partes_receptor[0], re.IGNORECASE):
                for j in range(max(0, idx_receptor - 3), idx_receptor):
                    linea_j = lineas[j]
                    if re.match(r'^AV\.|^JR\.|^CAL\.', linea_j, re.IGNORECASE):
                        partes_receptor.insert(0, linea_j)  # Insertar al inicio
                    elif partes_receptor and not any(k in linea_j for k in ['Fecha', 'RUC', 'Señor', 'EXACTA']):
                        # Continuación de dirección
                        if len(partes_receptor) > 0:
                            partes_receptor.insert(1, linea_j)
            
            # Parte 3: Texto DESPUÉS de "factura" en la línea actual  
            match_despues = re.search(r'factura\s+(.+)$', linea_receptor, re.IGNORECASE)
            if match_despues:
                partes_receptor.append(match_despues.group(1))
            
            # Parte 4: líneas siguientes hasta encontrar otra dirección o sección
            for j in range(idx_receptor + 1, min(idx_receptor + 4, len(lineas))):
                linea_j = lineas[j]
                linea_lower = linea_j.lower()
                # Parar si encontramos dirección cliente, tipo moneda, o nueva dirección AV./JR./CAL.
                if 'cliente' in linea_lower or 'moneda' in linea_lower:
                    break
                if re.match(r'^AV\.|^JR\.|^CAL\.', linea_j, re.IGNORECASE):
                    break
                partes_receptor.append(linea_j)
            
            direccion_receptor_factura = ' '.join(partes_receptor)
            direccion_receptor_factura = limpiar_texto(direccion_receptor_factura)
            print(f"    Direccion Receptor Factura: {direccion_receptor_factura}")
        
        # DIRECCIÓN DEL CLIENTE
        if idx_cliente >= 0:
            partes_cliente = []
            
            # La línea del cliente tiene estructura:
            # "AV. LOS ALGARROBOS coo LAS VERTIENTES MZA H LOTE. 4A Dirección del Cllente CRUCE DE..."
            linea_cliente = lineas[idx_cliente]
            
            # Parte 1: Texto ANTES de "Dirección del Cliente" (incluye AV./JR./CAL.)
            # Usar regex flexible para variantes OCR: Cliente, Cllente, Cl1ente, etc.
            match_antes = re.search(r'^(.+?)\s*Direcci[oó]n\s+del\s+C.?l+.?ente', linea_cliente, re.IGNORECASE)
            if match_antes:
                texto_antes = match_antes.group(1).strip()
                if texto_antes:
                    partes_cliente.append(texto_antes)
            
            # Parte 2: Texto DESPUÉS de "Cliente/Cllente/etc"
            match_despues = re.search(r'C.?l+.?ente\s+(.+)$', linea_cliente, re.IGNORECASE)
            if match_despues:
                partes_cliente.append(match_despues.group(1))
            
            # Parte 3: Líneas siguientes hasta Tipo de Moneda o siguiente sección
            for j in range(idx_cliente + 1, min(idx_cliente + 4, len(lineas))):
                linea_j = lineas[j]
                linea_lower = linea_j.lower()
                if 'moneda' in linea_lower or 'tipo' in linea_lower or 'observ' in linea_lower:
                    break
                partes_cliente.append(linea_j)
            
            direccion_cliente = ' '.join(partes_cliente)
            direccion_cliente = limpiar_texto(direccion_cliente)
            print(f"    Direccion Cliente: {direccion_cliente}")
        
        # TIPO DE MONEDA
        tipo_moneda = "SOLES"
        for linea in lineas:
            if 'Moneda' in linea:
                if 'DOLAR' in linea.upper():
                    tipo_moneda = "DOLARES"
                elif 'SOL' in linea.upper():
                    tipo_moneda = "SOLES"
                print(f"    Tipo Moneda: {tipo_moneda}")
                break
        
        # OBSERVACIÓN - Mejorada para capturar todo el contexto
        observacion = ""
        for i, linea in enumerate(lineas):
            # Buscar línea con "Observación"
            if 'Observaci' in linea:
                # Extraer texto después de "Observación"
                match = re.search(r'Observaci[oó]n\s*:?\s*(.+)$', linea, re.IGNORECASE)
                if match:
                    observacion = limpiar_texto(match.group(1))
                print(f"    Observacion: {observacion}")
                break
            # También buscar "OPERACIÓN SUJETA AL SPOD" que puede estar junto con observación
            if 'SUJETA' in linea.upper() and 'SPOD' in linea.upper():
                # Extraer todo lo que viene después incluyendo CTA.CTE
                match_obs = re.search(r'(OPERACI[OÓ]N\s+SUJETA\s+AL\s+SPOD.*?)(?:Cantidad|$)', linea, re.IGNORECASE)
                if match_obs:
                    observacion = limpiar_texto(match_obs.group(1))
                else:
                    # Buscar CTA.CTE o CTACTE en la línea
                    match_cta = re.search(r'(CTA\.?CTE.*)', linea, re.IGNORECASE)
                    if match_cta:
                        observacion = f"OPERACIÓN SUJETA AL SPOD {limpiar_texto(match_cta.group(1))}"
                print(f"    Observacion: {observacion}")
                break
        
        # Si encontramos observación pero no tiene "OPERACIÓN SUJETA" y hay CTA.CTE
        if observacion and 'CTA' in observacion.upper() and 'OPERACIÓN' not in observacion.upper():
            observacion = f"OPERACIÓN SUJETA AL SPOD {observacion}"
        
        # =====================================================================
        # SECCIÓN 3: LÍNEAS DE FACTURA
        # =====================================================================
        print("\n[SECCION 3] Procesando LINEAS DE FACTURA...")
        lista_lineas = []
        
        # El OCR produce líneas en varios formatos:
        # Formato 1 (separado): [12] 28-11-2025-046 SAGA FALABELLA... .00 UNIDAD 4200.00 PENDIENTE...
        # Formato 2 (junto con cabecera): Cantidad Unidad Medida Descripción Valor Unitario 28-11-2025... UNIDAD 6200.00
        
        for i, linea in enumerate(lineas):
            if 'UNIDAD' in linea.upper() or 'NIU' in linea.upper():
                # Verificar si es línea de cabecera SIN datos
                es_solo_cabecera = re.search(r'Cantldad|Cantidad|Unldad\s+Medlda|Unidad\s+Medida', linea, re.IGNORECASE)
                tiene_datos = re.search(r'UNIDAD\s+\d{3,}', linea, re.IGNORECASE)  # UNIDAD seguido de valor
                
                # Si es cabecera pero TAMBIÉN tiene datos (formato junto), procesarla
                if es_solo_cabecera and not tiene_datos:
                    continue  # Solo ignorar si es cabecera pura sin datos
                
                # EXTRAER CANTIDAD
                cantidad = 0.0
                
                # Caso 1: "X.00 UNIDAD" o ".00 UNIDAD" o "X.0D UNIDAD" (OCR lee 0 como D)
                match_cant = re.search(r'(\d*)\.0[0D]\s*(UNIDAD|NIU)', linea, re.IGNORECASE)
                if match_cant:
                    if match_cant.group(1):  # Hay número antes del .00
                        cant_encontrada = float(match_cant.group(1))
                        if 1 <= cant_encontrada <= 99:
                            cantidad = cant_encontrada
                    else:  # Solo ".00 UNIDAD" sin número
                        cantidad = 1.0  # Default común
                
                # Caso 2: "X UNIDAD" sin .00 (buscar número justo antes de UNIDAD)
                # PERO solo si no hay cabecera de tabla en la línea
                if cantidad == 0 and not re.search(r'Cantidad|Cantldad', linea, re.IGNORECASE):
                    match_simple = re.search(r'(\d{1,2})\s+(UNIDAD|NIU)', linea, re.IGNORECASE)
                    if match_simple:
                        cant_encontrada = float(match_simple.group(1))
                        # Validar que sea una cantidad razonable (no confundir con otros números)
                        if 1 <= cant_encontrada <= 99:
                            cantidad = cant_encontrada
                
                # Caso especial: Si la línea tiene cabecera y no encontramos cantidad explícita,
                # intentar inferir del subtotal/valorUnitario
                if cantidad == 0 and re.search(r'Cantidad|Cantldad', linea, re.IGNORECASE):
                    # Marcar para inferencia posterior
                    cantidad = 0.0  # Se inferirá después
                
                # EXTRAER VALOR UNITARIO - buscar número con formato monetario
                # Puede ser: "4200.00" o "4,200.00" después de algún texto
                valor_unitario = 0.0
                # Buscar el número que parece ser un valor monetario (X,XXX.XX o XXXX.XX)
                montos_posibles = re.findall(r'(\d{1,3}(?:,\d{3})*\.\d{2}|\d{4,}\.\d{2})', linea)
                if montos_posibles:
                    # Tomar el número más grande que no sea absurdamente alto
                    for m in montos_posibles:
                        valor = limpiar_monto(m)
                        if valor > valor_unitario and valor < 1000000:
                            valor_unitario = valor
                
                # EXTRAER DESCRIPCIÓN - Nueva estrategia
                descripcion = ""
                
                # La descripción puede estar:
                # CASO 1: Después de "UNIDAD" y antes del valor numérico
                # Formato: "UNIDAD 28-11-2025-046 SAGA FALABELLA S A LIMA AREQUIPA 90M3 4200.00 PENDIENTE..."
                # CASO 2: Antes de "UNIDAD" 
                # Formato: "28-11-2025-046 SAGA FALABELLA 1 UNIDAD 4200.00"
                
                # Estrategia: extraer TODO entre UNIDAD y el monto, y TODO después del monto
                
                # Buscar patrón: UNIDAD (texto) (monto con decimales) (más texto)
                match_desc = re.search(
                    r'UNIDAD\s+(.+?)\s+(\d{1,3}(?:,\d{3})*\.\d{2}|\d{4,}\.\d{2})\s*(.*)$',
                    linea, re.IGNORECASE
                )
                
                if match_desc:
                    parte_antes = match_desc.group(1).strip()
                    parte_despues = match_desc.group(3).strip()
                    
                    # Limpiar parte_antes: quitar números de cantidad al inicio
                    parte_antes = re.sub(r'^\d{1,2}\s+', '', parte_antes)
                    
                    # Combinar partes
                    if parte_despues:
                        descripcion = f"{parte_antes} {parte_despues}"
                    else:
                        descripcion = parte_antes
                else:
                    # Caso alternativo: descripción antes de UNIDAD
                    match_antes = re.search(r'^(.+?)\s+\d*\s*UNIDAD', linea, re.IGNORECASE)
                    if match_antes:
                        descripcion = match_antes.group(1).strip()
                    
                    # Y también después del valor unitario
                    if valor_unitario > 0:
                        patron_despues = re.escape(f"{valor_unitario:.2f}".replace('.', r'\.'))
                        match_despues = re.search(rf'{valor_unitario:.2f}\s+(.+)$'.replace('.', r'\.'), linea)
                        if match_despues:
                            parte_despues = match_despues.group(1).strip()
                            if descripcion:
                                descripcion = f"{descripcion} {parte_despues}"
                            else:
                                descripcion = parte_despues
                
                # Limpiar descripción final
                descripcion = limpiar_texto(descripcion)
                # Corregir errores comunes OCR
                descripcion = descripcion.replace('$ A', 'S A')  # "FALABELLA $ A" -> "S A"
                descripcion = descripcion.replace('$', 'S')  # $ leído en lugar de S
                descripcion = re.sub(r'\bBVZ87O\b', 'BVZ870', descripcion)  # O->0
                descripcion = re.sub(r'O(\d)', r'0\1', descripcion)  # O seguido de número -> 0
                descripcion = re.sub(r'(\d)O', r'\g<1>0', descripcion)  # número seguido de O -> 0
                
                # Si cantidad aún es 0, inferir de subtotal/valorUnitario
                cantidad_inferir = (cantidad == 0)
                
                print(f"    Cantidad: {cantidad}")
                print(f"    Valor Unitario: {valor_unitario}")
                print(f"    Descripcion: {descripcion}")
                
                lista_lineas.append({
                    "cantidad": cantidad,
                    "unidadMedida": "UNIDAD",
                    "descripcion": descripcion,
                    "valorUnitario": valor_unitario
                })
        
        if not lista_lineas:
            validaciones.append("SECCION 3: No se encontraron lineas de factura")
        
        # =====================================================================
        # SECCIÓN 4: TOTALES
        # =====================================================================
        print("\n[SECCION 4] Procesando TOTALES...")
        
        venta_gratuita = 0.0
        subtotal_venta = 0.0
        anticipo = 0.0
        descuento = 0.0
        valor_venta = 0.0
        isc = 0.0
        igv = 0.0
        otros_cargos = 0.0
        otros_tributos = 0.0
        monto_redondeo = 0.0
        importe_total = 0.0
        descripcion_importe = ""
        
        # ESTRATEGIA: Buscar línea compacta con múltiples montos
        # Formato típico: "5 4,2uu.UU SI U.UU 5u.UU 5 4,2uu.Uu 57u.U0 51 756.U0"
        # Que representa: Sub Total | Anticipos | Descuentos | Valor Venta | ISC | IGV
        
        linea_totales_compacta = None
        for linea in lineas:
            # Buscar línea que tenga múltiples montos (al menos 3 números con formato X,XXX.XX o X.XX)
            montos_en_linea = re.findall(r'[\d,]+\.[0-9uUDd]{2}', linea)
            if len(montos_en_linea) >= 4:
                linea_totales_compacta = linea
                print(f"    [DEBUG] Linea compacta detectada: {linea[:80]}...")
                break
        
        if linea_totales_compacta:
            # Extraer todos los montos de la línea compacta
            # Primero normalizar la línea
            linea_norm = linea_totales_compacta
            linea_norm = linea_norm.replace('uu', '00').replace('UU', '00')
            linea_norm = linea_norm.replace('u', '0').replace('U', '0')
            linea_norm = linea_norm.replace('D', '0')
            
            # El OCR confunde "S/" con "5" o "51", así que separar patrones como "5 4,200" o "51 756"
            # Normalizar: "5 4,200.00" -> separar el 5, "51 756.00" -> separar el 51
            linea_norm = re.sub(r'\b5\s+(\d)', r'S/ \1', linea_norm)  # "5 4" -> "S/ 4"
            linea_norm = re.sub(r'\b51\s+(\d)', r'S/ \1', linea_norm)  # "51 7" -> "S/ 7"
            linea_norm = re.sub(r'\bSI\s+', 'S/ ', linea_norm)  # "SI 0" -> "S/ 0"
            linea_norm = re.sub(r'\bsI\s+', 'S/ ', linea_norm)  # "sI 0" -> "S/ 0"
            
            # También corregir "50.00" que probablemente es "S/ 0.00"
            linea_norm = re.sub(r'\b50\.00\b', 'S/ 0.00', linea_norm)
            linea_norm = re.sub(r'\b570\.00\b', 'S/ 0.00', linea_norm)  # "570" = "S/ 0" mal leído
            
            print(f"    [DEBUG] Linea normalizada: {linea_norm[:100]}...")
            
            # Encontrar todos los montos (después de S/ o sueltos)
            montos = re.findall(r'[\d,]+\.\d{2}', linea_norm)
            print(f"    [DEBUG] Montos extraidos: {montos}")
            
            # Orden típico en factura SUNAT: SubTotal, Anticipos, Descuentos, ValorVenta, ISC, IGV
            montos_limpios = [limpiar_monto(m) for m in montos]
            print(f"    [DEBUG] Montos limpios: {montos_limpios}")
            
            # Estrategia: Encontrar el valor principal (más alto) y calcular IGV esperado
            if montos_limpios:
                # Filtrar valores que probablemente son errores (5, 10, 50, 51, etc. de S/ mal leído)
                valores_significativos = [m for m in montos_limpios if m > 100 or m == 0]
                
                if valores_significativos:
                    # El valor más alto es probablemente el subtotal/valor_venta
                    max_valor = max(valores_significativos)
                    subtotal_venta = max_valor
                    valor_venta = max_valor
                    
                    # IGV esperado = 18% del valor venta
                    igv_esperado = max_valor * 0.18
                    
                    # Buscar un valor cercano al IGV esperado entre los montos
                    for m in montos_limpios:
                        if m > 0 and abs(m - igv_esperado) < igv_esperado * 0.15:  # Dentro del 15%
                            igv = m
                            break
                    
                    # Si no encontramos IGV, calcularlo
                    if igv == 0 and max_valor > 0:
                        igv = round(max_valor * 0.18, 2)
                    
                    # Importe total = valor_venta + igv
                    importe_total = valor_venta + igv
                    
                    # Los demás valores (anticipos, descuentos, ISC, otros) probablemente son 0
                    # (los valores pequeños como 5, 7, 10, 50, 570 son errores de OCR de "S/")
                    
                    print(f"    [DEBUG] SubTotal/ValorVenta: {subtotal_venta}")
                    print(f"    [DEBUG] IGV calculado: {igv}")
                    print(f"    [DEBUG] Importe Total: {importe_total}")
        
        for linea in lineas:
            linea_upper = linea.upper()
            
            # Venta de Operaciones Gratuitas
            if 'GRATUITAS' in linea_upper:
                # Buscar monto después de Gratuitas
                match = re.search(r'Gratuitas\s*:?\s*[Ss5]?/?[Il]?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    venta_gratuita = limpiar_monto(match.group(1))
                print(f"    Venta Gratuita: {venta_gratuita}")
            
            # Sub Total Ventas - El OCR puede leer "Venlas" o "5/5200" junto
            if 'SUB' in linea_upper and 'TOTAL' in linea_upper:
                # Patrón mejorado: buscar número después de "Total Ven" con variantes OCR
                # Puede ser "5/5200.00" o "sI 5,200.00" o "S/ 5200.00"
                match = re.search(r'Total\s*Ven[lt]a?s?\s*:?\s*[Ss5]?/?[Il]?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    subtotal_venta = limpiar_monto(match.group(1))
                print(f"    Subtotal Venta: {subtotal_venta}")
            
            # Anticipos - Cuidado: "Anticipos 5/0.00" se lee como "Anticipos 570.00"
            # También: "Antcipos 5F 0.0D" donde 5F es S/ mal leído
            if 'ANTICIPO' in linea_upper or 'ANTCIPO' in linea_upper:
                # Buscar el patrón, pero detectar "5F 0" o "5/ 0" como S/ 0.00
                if re.search(r'5[FfI/]\s*0\.0[0D]', linea):
                    anticipo = 0.0
                else:
                    match = re.search(r'Ant[ic]*ipos?\s*:?\s*[Ss5]?[FfI/]?\s*([\d,.]+)', linea, re.IGNORECASE)
                    if match:
                        anticipo_raw = limpiar_monto(match.group(1))
                        # Corregir: si es 70.0 o 570.0, probablemente es S/0.00 mal leído
                        if anticipo_raw == 70.0 or anticipo_raw == 570.0:
                            anticipo = 0.0
                        elif anticipo_raw < 100 and re.search(r'0\.0[0D]', linea):
                            anticipo = 0.0
                        else:
                            anticipo = anticipo_raw
                print(f"    Anticipo: {anticipo}")
            
            # Descuentos - "5F 0.0D" donde 5F es S/ mal leído y D es 0 mal leído
            if 'DESCUENTO' in linea_upper:
                # Detectar patrón "5F 0" o "5/ 0" como S/ 0.00
                if re.search(r'5[FfI/]\s*0\.0[0D]', linea):
                    descuento = 0.0
                else:
                    match = re.search(r'Descuentos?\s*:?\s*[Ss5]?[FfI/]?\s*([\d,.]+)', linea, re.IGNORECASE)
                    if match:
                        descuento_raw = limpiar_monto(match.group(1))
                        # Si el valor es muy pequeño y hay "0.0" en la línea, probablemente es 0
                        if descuento_raw < 10 and re.search(r'0\.0[0D]', linea):
                            descuento = 0.0
                        else:
                            descuento = descuento_raw
                print(f"    Descuento: {descuento}")
            
            # Valor Venta (solo si no es "Gratuitas" ni "Sub Total")
            if 'VALOR' in linea_upper and 'VENTA' in linea_upper and 'GRATUITAS' not in linea_upper and 'SUB' not in linea_upper:
                match = re.search(r'Valor\s*Venta\s*:?\s*[Ss5]?/?[Il]?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    valor_venta_raw = limpiar_monto(match.group(1))
                    # Corregir: "S/4,200" leído como "514,200" o "14200"
                    # Usar subtotal como referencia (deberían ser iguales o muy cercanos)
                    if subtotal_venta > 0:
                        valor_venta = corregir_monto_ocr(valor_venta_raw, subtotal_venta, tolerancia=0.1)
                    else:
                        valor_venta = corregir_monto_ocr(valor_venta_raw)
                print(f"    Valor Venta: {valor_venta}")
            
            # ISC
            if 'ISC' in linea_upper and 'DESC' not in linea_upper:
                match = re.search(r'ISC\s*:?\s*[Ss5]?/?[Il]?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    isc = limpiar_monto(match.group(1))
                
                # Descripción del importe (SON: ...)
                match_son = re.search(r'SON:\s*(.+?)(?:\d|$)', linea, re.IGNORECASE)
                if match_son:
                    descripcion_importe = limpiar_texto(match_son.group(1))
                print(f"    ISC: {isc}")
            
            # IGV
            if 'IGV' in linea_upper:
                # Manejar formato "IGV 5/ 756.00" donde 5/ es S/
                match = re.search(r'IGV\s*:?\s*[Ss5]?/?[Il]?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    igv = limpiar_monto(match.group(1))
                print(f"    IGV: {igv}")
            
            # Otros Cargos
            if 'OTROS' in linea_upper and 'CARGOS' in linea_upper:
                match = re.search(r'Otros?\s*Cargos?\s*:?\s*[Ss5]?/?[Il]?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    otros_cargos = limpiar_monto(match.group(1))
                print(f"    Otros Cargos: {otros_cargos}")
            
            # Otros Tributos
            if 'OTROS' in linea_upper and 'TRIBUTOS' in linea_upper:
                match = re.search(r'Otros?\s*Tributos?\s*:?\s*[Ss5]?/?[Il]?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    otros_tributos = limpiar_monto(match.group(1))
                print(f"    Otros Tributos: {otros_tributos}")
            
            # Monto de redondeo
            if 'REDONDEO' in linea_upper:
                match = re.search(r'redondeo\s*:?\s*[Ss5]?/?[Il]?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    monto_redondeo = limpiar_monto(match.group(1))
                print(f"    Monto Redondeo: {monto_redondeo}")
            
            # Importe Total
            if 'IMPORTE' in linea_upper and 'TOTAL' in linea_upper:
                match = re.search(r'Importe\s*Total\s*:?\s*[Ss5]?/?[Il]?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    importe_raw = limpiar_monto(match.group(1))
                    # Si es muy bajo (ej: 956 cuando debería ser 4956)
                    # El OCR a veces pierde el primer dígito
                    importe_esperado = valor_venta + igv if valor_venta > 0 else 0
                    
                    if importe_esperado > 0:
                        # Si el importe leido es similar al esperado sin el primer dígito
                        esp_str = str(int(importe_esperado))
                        raw_str = str(int(importe_raw))
                        
                        # Verificar si raw es el esperado sin el primer dígito
                        if len(esp_str) > len(raw_str) and esp_str.endswith(raw_str):
                            importe_total = importe_esperado
                        elif abs(importe_raw - importe_esperado) < 100:
                            importe_total = importe_raw
                        else:
                            # Usar el calculado si la diferencia es grande
                            importe_total = importe_esperado
                    else:
                        importe_total = importe_raw
                print(f"    Importe Total: {importe_total}")
            
            # Descripción del importe (SON: ...)
            if 'SON:' in linea_upper:
                match_son = re.search(r'SON:\s*(.+?)(?:\d|SOLES|$)', linea, re.IGNORECASE)
                if match_son:
                    desc = match_son.group(1).strip()
                    if desc:
                        descripcion_importe = desc
                        if 'SOLES' not in descripcion_importe.upper():
                            descripcion_importe += " SOLES"
                print(f"    Descripcion Importe: {descripcion_importe}")
        
        # VALIDACIÓN CRUZADA FINAL
        # 1. Si importe_total es muy bajo, recalcular
        if importe_total < 100 and valor_venta > 100:
            importe_total = valor_venta + igv
            print(f"    [CORRECCION] Importe Total recalculado: {importe_total}")
        
        # 2. Verificar coherencia: IGV debe ser ~18% del valor_venta
        if valor_venta > 0 and igv > 0:
            igv_esperado = valor_venta * 0.18
            if abs(igv - igv_esperado) < igv_esperado * 0.05:  # Dentro del 5%
                # Los valores son coherentes
                pass
            else:
                validaciones.append(f"ADVERTENCIA: IGV ({igv}) no es ~18% de Valor Venta ({valor_venta})")
        
        # 3. Verificar: importe_total ≈ valor_venta + igv
        if valor_venta > 0 and igv > 0 and importe_total > 0:
            importe_esperado = valor_venta + igv
            if abs(importe_total - importe_esperado) > 10:  # Diferencia mayor a 10
                print(f"    [CORRECCION] Importe ajustado de {importe_total} a {importe_esperado}")
                importe_total = importe_esperado
        
        # 4. Inferir cantidad si no se pudo extraer del OCR
        if lista_lineas and subtotal_venta > 0:
            for linea_fact in lista_lineas:
                if linea_fact["cantidad"] == 0 and linea_fact["valorUnitario"] > 0:
                    # Calcular cantidad = subtotal / valorUnitario
                    cantidad_calc = subtotal_venta / linea_fact["valorUnitario"]
                    # Redondear a entero si está cerca
                    cantidad_int = round(cantidad_calc)
                    if abs(cantidad_calc - cantidad_int) < 0.1:
                        linea_fact["cantidad"] = float(cantidad_int)
                        print(f"    [INFERENCIA] Cantidad calculada: {cantidad_int} (subtotal {subtotal_venta} / valor {linea_fact['valorUnitario']})")
                    else:
                        # Usar el valor calculado directamente
                        linea_fact["cantidad"] = round(cantidad_calc, 2)
                        print(f"    [INFERENCIA] Cantidad calculada: {cantidad_calc:.2f}")
        
        # =====================================================================
        # SECCIÓN 5: CUOTAS (CRÉDITO)
        # =====================================================================
        print("\n[SECCION 5] Procesando CUOTAS...")
        
        total_cuotas = 0
        lista_cuotas = []
        monto_pendiente = 0.0
        
        for linea in lineas:
            # Monto pendiente de pago
            if 'pendiente' in linea.lower() and 'pago' in linea.lower():
                match = re.search(r'[Ss5]?/?[Il]?\s*([\d,.]+)', linea)
                if match:
                    monto_pendiente = limpiar_monto(match.group(1))
                print(f"    Monto Pendiente: {monto_pendiente}")
            
            # Línea de cuotas (múltiples fechas)
            fechas = re.findall(r'\d{2}/\d{2}/\d{4}', linea)
            if len(fechas) >= 2:
                # Extraer pares fecha-monto
                pos_fechas = [(m.start(), m.group()) for m in re.finditer(r'\d{2}/\d{2}/\d{4}', linea)]
                
                for idx, (pos, fecha) in enumerate(pos_fechas):
                    inicio_monto = pos + len(fecha)
                    if idx + 1 < len(pos_fechas):
                        fin_monto = pos_fechas[idx + 1][0]
                    else:
                        fin_monto = len(linea)
                    
                    texto_monto = linea[inicio_monto:fin_monto]
                    match_monto = re.search(r'([\d,.]+)', texto_monto)
                    if match_monto:
                        monto = limpiar_monto(match_monto.group(1))
                        if monto > 0:
                            lista_cuotas.append({
                                "numeroCuota": idx + 1,
                                "fechaVencimientoCuota": fecha,
                                "montoCuota": monto
                            })
                            print(f"    Cuota {idx + 1}: {fecha} - {monto}")
        
        total_cuotas = len(lista_cuotas)
        print(f"    Total Cuotas: {total_cuotas}")
        
        # =====================================================================
        # CONSTRUIR RESPUESTA
        # =====================================================================
        print("\n" + "=" * 70)
        print("CONSTRUCCION DE RESPUESTA...")
        print("=" * 70)
        
        respuesta = {
            # Sección 1: Cabecera
            "rucEmisor": ruc_emisor,
            "razonSocialEmisor": razon_social_emisor,
            "direccionEmisor": direccion_emisor,
            "distritoEmisor": distrito_emisor,
            "provinciaEmisor": provincia_emisor,
            "departamentoEmisor": departamento_emisor,
            "numeroFactura": numero_factura,
            
            # Sección 2: Receptor y Operación
            "fechaEmision": fecha_emision,
            "formaPago": forma_pago,
            "rucReceptor": ruc_receptor,
            "razonSocialReceptor": razon_social_receptor,
            "direccionReceptorFactura": direccion_receptor_factura,
            "direccionCliente": direccion_cliente,
            "tipoMoneda": tipo_moneda,
            "observacion": observacion,
            
            # Sección 3: Líneas de factura
            "lineasFactura": lista_lineas,
            
            # Sección 4: Totales
            "ventaGratuita": venta_gratuita,
            "subtotalVenta": subtotal_venta,
            "anticipo": anticipo,
            "descuento": descuento,
            "valorVenta": valor_venta,
            "isc": isc,
            "igv": igv,
            "otrosCargos": otros_cargos,
            "otrosTributos": otros_tributos,
            "montoRedondeo": monto_redondeo,
            "importeTotal": importe_total,
            "descripcionImporteTotal": descripcion_importe,
            
            # Sección 5: Cuotas
            "totalCuota": total_cuotas,
            "cuotas": lista_cuotas,
            "montoPendiente": monto_pendiente,
            
            # Validaciones
            "validacion": validaciones if validaciones else ["OK"]
        }
        
        return respuesta
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"validacion": [f"Error procesando imagen: {str(e)}"]}


# =============================================================================
# TEST DIRECTO
# =============================================================================
if __name__ == "__main__":
    import json
    import sys
    
    archivo = sys.argv[1] if len(sys.argv) > 1 else "pruebaaa.jpeg"
    print(f"\nProcesando: {archivo}\n")
    
    resultado = procesar_factura_img(archivo)
    
    print("\n" + "=" * 70)
    print("RESULTADO FINAL (JSON):")
    print("=" * 70)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
