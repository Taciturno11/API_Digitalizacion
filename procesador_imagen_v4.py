"""
PROCESADOR DE IMAGEN v4 - Factura Electrónica SUNAT
===================================================
Versión completamente optimizada basada en análisis del output real de EasyOCR.
Sin valores hardcodeados - extracción dinámica inteligente.
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
    """Singleton para EasyOCR - evita reinicializar el modelo."""
    global _reader
    if _reader is None:
        print("[OCR] Inicializando EasyOCR...")
        _reader = easyocr.Reader(['es', 'en'], gpu=False)
    return _reader


# =============================================================================
# PREPROCESAMIENTO DE IMAGEN
# =============================================================================
def preprocesar_imagen(ruta_imagen):
    """
    Mejora la calidad de la imagen para mejor OCR.
    """
    imagen = Image.open(ruta_imagen)
    
    # Convertir a RGB si es necesario
    if imagen.mode != 'RGB':
        imagen = imagen.convert('RGB')
    
    # Aumentar contraste
    enhancer_contrast = ImageEnhance.Contrast(imagen)
    imagen = enhancer_contrast.enhance(1.5)
    
    # Aumentar nitidez
    enhancer_sharp = ImageEnhance.Sharpness(imagen)
    imagen = enhancer_sharp.enhance(2.0)
    
    return np.array(imagen)


# =============================================================================
# FUNCIONES DE LIMPIEZA Y CONVERSIÓN
# =============================================================================
def limpiar_texto(texto):
    """Limpia y normaliza texto."""
    if not texto:
        return ""
    texto = re.sub(r'\s+', ' ', texto)
    return texto.strip()


def limpiar_moneda(valor_str):
    """
    Convierte string de moneda a float, manejando errores típicos de OCR.
    Errores comunes: 'O' por '0', 'D' por '0', '5/' por 'S/', separadores.
    """
    if not valor_str:
        return 0.0
    
    valor_str = str(valor_str)
    
    # 1. Remover símbolos de moneda y espacios
    valor_str = re.sub(r'[S$/Sl\s]', '', valor_str)
    
    # 2. Reemplazar errores OCR comunes
    valor_str = valor_str.replace('O', '0').replace('o', '0')
    valor_str = valor_str.replace('D', '0').replace('d', '0')
    valor_str = valor_str.replace('I', '1').replace('l', '1')
    valor_str = valor_str.replace('B', '8')
    
    # 3. Detectar formato y normalizar
    # Caso: "5.200.00" (punto como separador miles)
    if valor_str.count('.') == 2:
        partes = valor_str.split('.')
        valor_str = ''.join(partes[:-1]) + '.' + partes[-1]
    
    # Caso: "5,200.00" (coma como separador miles)
    elif ',' in valor_str and '.' in valor_str:
        valor_str = valor_str.replace(',', '')
    
    # Caso: solo coma "5,200"
    elif ',' in valor_str and '.' not in valor_str:
        valor_str = valor_str.replace(',', '')
    
    try:
        return float(valor_str)
    except:
        return 0.0


def extraer_texto_easyocr(ruta_imagen):
    """
    Extrae texto de la imagen usando EasyOCR.
    Retorna: (texto_completo, lineas_agrupadas, resultados_raw)
    """
    ocr = get_reader()
    imagen_procesada = preprocesar_imagen(ruta_imagen)
    resultados = ocr.readtext(imagen_procesada, detail=1, paragraph=False)
    
    # Ordenar por posición Y, luego X
    resultados_ordenados = sorted(resultados, key=lambda x: (x[0][0][1], x[0][0][0]))
    
    # Agrupar en líneas por coordenada Y similar
    lineas = []
    linea_actual = []
    y_anterior = -100
    umbral_y = 12
    
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
    
    texto_completo = '\n'.join(lineas)
    return texto_completo, lineas, resultados_ordenados


# =============================================================================
# FUNCIONES DE EXTRACCIÓN ESPECÍFICAS
# =============================================================================

def extraer_monto_de_linea(linea, despues_de=None):
    """
    Extrae un monto de una línea, opcionalmente después de una palabra clave.
    Maneja el formato S/ X,XXX.XX y errores OCR.
    """
    if despues_de:
        # Buscar después de la palabra clave
        match = re.search(rf'{despues_de}\s*[S5]?/?I?\s*([\d,.\s]+)', linea, re.IGNORECASE)
        if match:
            return limpiar_moneda(match.group(1))
    
    # Buscar patrón S/ seguido de monto
    match = re.search(r'[S5]/?\s*([\d,.\s]+)', linea)
    if match:
        return limpiar_moneda(match.group(1))
    
    # Buscar cualquier número con decimales
    numeros = re.findall(r'[\d,]+\.[\d]{2}', linea)
    if numeros:
        return limpiar_moneda(numeros[-1])
    
    return 0.0


def extraer_cuotas(lineas):
    """
    Extrae información de cuotas de las líneas OCR.
    Formato típico: "01/12/2025 2,100.00 28/12/2025 2,657.76 31/12/2025 2,500.00"
    """
    cuotas = []
    
    for linea in lineas:
        # Buscar patrón: fecha monto (repetido)
        patron = r'(\d{2}/\d{2}/\d{4})\s+([\d,.\s]+?)(?=\d{2}/\d{2}/\d{4}|$)'
        matches = re.findall(patron, linea)
        
        for i, (fecha, monto_str) in enumerate(matches, 1):
            monto = limpiar_moneda(monto_str)
            if monto > 0:
                cuotas.append({
                    "numeroCuota": i,
                    "fechaVencimientoCuota": fecha,
                    "montoCuota": monto
                })
    
    return cuotas


def extraer_direccion_compuesta(lineas, inicio_idx, palabras_fin):
    """
    Extrae una dirección que puede estar en múltiples líneas.
    Reconstruye la dirección desde inicio_idx hasta encontrar palabras_fin.
    """
    partes = []
    
    for i in range(inicio_idx, min(inicio_idx + 5, len(lineas))):
        linea = lineas[i]
        
        # Verificar si llegamos a una línea que indica fin
        if any(p in linea for p in palabras_fin):
            # Extraer solo la parte relevante
            for palabra in palabras_fin:
                if palabra in linea:
                    idx = linea.index(palabra)
                    parte = linea[:idx].strip()
                    if parte:
                        partes.append(parte)
                    break
            break
        else:
            partes.append(linea.strip())
    
    return ' '.join(partes)


# =============================================================================
# PROCESADOR PRINCIPAL
# =============================================================================

def procesar_factura_img(ruta_archivo):
    """
    Procesa una imagen de factura SUNAT usando EasyOCR.
    Extrae todos los datos dinámicamente basándose en el formato real del OCR.
    """
    validaciones = []
    
    try:
        # Extraer texto con EasyOCR
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
        
        # Buscar línea que contiene RUC del emisor (primera aparición)
        ruc_emisor = 0
        razon_social_emisor = ""
        direccion_emisor = ""
        numero_factura = ""
        distrito_emisor, provincia_emisor, departamento_emisor = "", "", ""
        
        for linea in lineas[:5]:  # Solo primeras 5 líneas
            # Buscar RUC con formato 10xxx o 20xxx
            match_ruc = re.search(r'RUC[:\s]*(\d{11})', linea)
            if match_ruc and ruc_emisor == 0:
                ruc_emisor = int(match_ruc.group(1))
                
                # La razón social está ANTES del RUC en la misma línea
                match_nombre = re.search(r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+)\s+RUC', linea)
                if match_nombre:
                    razon_social_emisor = limpiar_texto(match_nombre.group(1))
                
                # La dirección y ubicación están DESPUÉS del RUC
                despues_ruc = linea.split('RUC')[1] if 'RUC' in linea else ""
                
                # Buscar dirección (Ayacucho, Av., Jr., etc.)
                match_dir = re.search(r'\d{11}\s+([A-Za-z]+\s+\d+)', despues_ruc)
                if match_dir:
                    direccion_emisor = match_dir.group(1)
                
                # Buscar ubicación geográfica (XXX-XXX-XXX o después de dirección)
                # Formato típico: "Magdalena del Mar ... Magdalena LIMA LIMA"
                match_ubigeo = re.search(r'([A-Z][a-z]+)\s+([A-Z]+)\s+([A-Z]+)\s*$', linea)
                if match_ubigeo:
                    distrito_emisor = match_ubigeo.group(1)
                    provincia_emisor = match_ubigeo.group(2)
                    departamento_emisor = match_ubigeo.group(3)
                
                print(f"    RUC Emisor: {ruc_emisor}")
                print(f"    Razon Social: {razon_social_emisor}")
                print(f"    Direccion: {direccion_emisor}")
                print(f"    Ubicacion: {distrito_emisor}-{provincia_emisor}-{departamento_emisor}")
            
            # Buscar número de factura (E001-XXX o F001-XXX)
            match_factura = re.search(r'([EF]\d{3}[-]?\d+)', linea)
            if match_factura and not numero_factura:
                numero_factura = match_factura.group(1)
                if '-' not in numero_factura:
                    numero_factura = numero_factura[:4] + '-' + numero_factura[4:]
                print(f"    Numero Factura: {numero_factura}")
        
        if not ruc_emisor:
            validaciones.append("SECCION 1: No se encontro RUC del emisor")
        
        # =====================================================================
        # SECCIÓN 2: RECEPTOR Y OPERACIÓN
        # =====================================================================
        print("\n[SECCION 2] Procesando RECEPTOR Y OPERACION...")
        
        # FECHA DE EMISIÓN - Buscar en línea específica
        fecha_emision = ""
        forma_pago = "Contado"
        
        for linea in lineas:
            if 'Fecha de Emisi' in linea:
                match_fecha = re.search(r'(\d{2}/\d{2}/\d{4})', linea)
                if match_fecha:
                    fecha_emision = match_fecha.group(1)
                
                # Forma de pago suele estar en la misma línea
                if 'Contado' in linea:
                    forma_pago = "Contado"
                elif 'Cr' in linea and ('dito' in linea or 'édito' in linea):
                    forma_pago = "Credito"
                
                print(f"    Fecha Emision: {fecha_emision}")
                print(f"    Forma de Pago: {forma_pago}")
                break
        
        # RECEPTOR - Buscar RUC diferente al emisor
        ruc_receptor = 0
        razon_social_receptor = ""
        
        for i, linea in enumerate(lineas):
            # Buscar línea con "Señor(es)" - indica receptor
            if 'Se' in linea and 'or' in linea:
                # El nombre del receptor puede estar ANTES de "Señor(es)"
                # Formato: "EXACTA EMPRESELMO LOGISTICO Señor(es) SOCIEDAD ANONIMA CERRADA"
                partes = re.split(r'Se.or\(?es\)?', linea, maxsplit=1)
                
                nombre_partes = []
                if len(partes) > 0 and partes[0].strip():
                    nombre_partes.append(partes[0].strip())
                if len(partes) > 1 and partes[1].strip():
                    # Solo agregar si es parte del nombre (MAYUSCULAS, SAC, etc.)
                    parte2 = partes[1].strip()
                    if re.match(r'^[A-Z\s]+(?:SOCIEDAD|S\.?A\.?C?\.?|CERRADA|ABIERTA)?', parte2):
                        nombre_partes.append(parte2)
                
                razon_social_receptor = ' '.join(nombre_partes)
                razon_social_receptor = limpiar_texto(razon_social_receptor)
                print(f"    Razon Social Receptor (parcial): {razon_social_receptor}")
            
            # Buscar RUC del receptor (diferente al emisor)
            match_ruc = re.search(r'RUC\s*(\d{11})', linea)
            if match_ruc:
                ruc_encontrado = int(match_ruc.group(1))
                if ruc_encontrado != ruc_emisor:
                    ruc_receptor = ruc_encontrado
                    print(f"    RUC Receptor: {ruc_receptor}")
        
        # DIRECCIONES - Estrategia basada en análisis real del OCR
        # El OCR produce líneas como:
        # [05] AV. SUCRE 128. JR 28 julio
        # [06] VERTIENTES MZA H LOTE. 4A
        # [07] Dirección del Receptor de factura CRUCE DE AVENIDA BRASIL Y
        # [08] CALLE LIMA LIMA MAGADALENA
        # [09] DEL MAR
        
        direccion_receptor_factura = ""
        direccion_cliente = ""
        
        # Buscar "Dirección del Receptor de factura"
        for i, linea in enumerate(lineas):
            if 'Receptor' in linea and 'factura' in linea:
                # Parte 1: Buscar hacia atrás las líneas con AV. al inicio
                partes_antes = []
                for j in range(max(0, i-3), i):
                    linea_ant = lineas[j]
                    if re.match(r'AV\.|JR\.|CAL', linea_ant, re.IGNORECASE):
                        partes_antes.append(linea_ant)
                    elif partes_antes:  # Si ya empezamos a recolectar
                        partes_antes.append(linea_ant)
                
                # Parte 2: Lo que viene después de "factura"
                partes_despues = []
                match_despues = re.search(r'factura\s+(.+)$', linea, re.IGNORECASE)
                if match_despues:
                    partes_despues.append(match_despues.group(1))
                
                # Agregar líneas siguientes hasta encontrar otra dirección o patrón conocido
                for j in range(i+1, min(i+3, len(lineas))):
                    sig_linea = lineas[j]
                    if 'AV.' in sig_linea or 'Dirección' in sig_linea or 'Tipo' in sig_linea:
                        break
                    partes_despues.append(sig_linea)
                
                # Combinar
                parte_antes = ' '.join(partes_antes)
                parte_despues = ' '.join(partes_despues)
                direccion_receptor_factura = f"{parte_antes} {parte_despues}".strip()
                direccion_receptor_factura = limpiar_texto(direccion_receptor_factura)
                
                print(f"    Direccion Receptor Factura: {direccion_receptor_factura}")
            
            # Buscar "Dirección del Cliente"
            if 'Cliente' in linea and 'Direcci' in linea:
                partes_antes = []
                for j in range(max(0, i-3), i):
                    linea_ant = lineas[j]
                    if re.match(r'AV\.|JR\.|CAL', linea_ant, re.IGNORECASE):
                        partes_antes.append(linea_ant)
                    elif partes_antes:
                        partes_antes.append(linea_ant)
                
                partes_despues = []
                match_despues = re.search(r'Cliente\s+(.+)$', linea, re.IGNORECASE)
                if match_despues:
                    partes_despues.append(match_despues.group(1))
                
                for j in range(i+1, min(i+3, len(lineas))):
                    sig_linea = lineas[j]
                    if 'Tipo' in sig_linea or 'Observ' in sig_linea:
                        break
                    partes_despues.append(sig_linea)
                
                parte_antes = ' '.join(partes_antes)
                parte_despues = ' '.join(partes_despues)
                direccion_cliente = f"{parte_antes} {parte_despues}".strip()
                direccion_cliente = limpiar_texto(direccion_cliente)
                
                print(f"    Direccion Cliente: {direccion_cliente}")
        
        # TIPO DE MONEDA - También verificar en descripción del importe
        tipo_moneda = "SOLES"  # Default para Perú
        for linea in lineas:
            if 'Tipo de Moneda' in linea:
                if 'DOLAR' in linea.upper() and 'SOL' not in linea.upper():
                    tipo_moneda = "DOLARES"
                print(f"    Tipo Moneda (linea): {tipo_moneda}")
                break
        
        # Verificar también si alguna línea con montos dice "SOLES" (más confiable)
        for linea in lineas:
            # Si la línea menciona SOLES y tiene contexto de monto (IGV, Importe, etc.)
            if 'SOLES' in linea.upper() and any(k in linea.upper() for k in ['IGV', 'IMPORTE', 'SON:']):
                tipo_moneda = "SOLES"
                print(f"    Tipo Moneda (confirmado por contexto): {tipo_moneda}")
                break
        
        # OBSERVACIÓN
        observacion = ""
        for linea in lineas:
            if 'Observaci' in linea:
                match = re.search(r'Observaci[oó]n\s+(.+)$', linea, re.IGNORECASE)
                if match:
                    observacion = limpiar_texto(match.group(1))[:150]
                    print(f"    Observacion: {observacion}")
                break
        
        # =====================================================================
        # SECCIÓN 3: LÍNEAS DE FACTURA
        # =====================================================================
        print("\n[SECCION 3] Procesando LINEAS DE FACTURA...")
        lista_lineas = []
        
        # Buscar línea con UNIDAD y extraer datos
        for linea in lineas:
            if 'UNIDAD' in linea.upper():
                # Formato detectado: "28-11-2025-046 TIENDA RYPLEY... 28 UNIDAD 6200.0D PENDIENTE..."
                # Buscar: cantidad UNIDAD precio
                match = re.search(r'(\d+\.?\d*)\s*(UNIDAD|NIU|UND|ZZ)\s+([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    cantidad = float(match.group(1))
                    unidad = match.group(2).upper()
                    valor_str = match.group(3)
                    valor_unitario = limpiar_moneda(valor_str)
                    
                    # Extraer descripción (lo que está entre el inicio y la cantidad)
                    descripcion = ""
                    # Buscar texto descriptivo antes de cantidad UNIDAD
                    match_desc = re.search(r'^.+?(\d{2}-\d{2}-\d{4}[-\d]*\s+.+?)\s+\d+\s*UNIDAD', linea, re.IGNORECASE)
                    if match_desc:
                        descripcion = match_desc.group(1)
                    else:
                        # Alternativa: todo lo que está antes de "cantidad UNIDAD"
                        idx = linea.upper().find('UNIDAD')
                        if idx > 0:
                            # Retroceder para encontrar el número de cantidad
                            texto_antes = linea[:idx]
                            match_antes = re.search(r'^(.+?)\s+\d+\.?\d*\s*$', texto_antes)
                            if match_antes:
                                descripcion = match_antes.group(1)
                    
                    descripcion = limpiar_texto(descripcion)
                    
                    print(f"    Linea: cant={cantidad}, unidad={unidad}, valor={valor_unitario}")
                    print(f"           desc={descripcion[:60]}...")
                    
                    lista_lineas.append({
                        "cantidad": cantidad,
                        "unidadMedida": convertir_unidad_medida(unidad),
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
        
        for linea in lineas:
            # Línea especial: "Valor de Venta de Operaciones Gratuitas S/ 100.00 Sub Total Ventas S/5200.00"
            if 'Gratuitas' in linea and 'Sub Total' in linea:
                # Extraer Gratuitas
                match_grat = re.search(r'Gratuitas\s*[S5]?/?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match_grat:
                    venta_gratuita = limpiar_moneda(match_grat.group(1))
                
                # Extraer SubTotal - puede aparecer como "5/5200" o "S/5200"
                match_sub = re.search(r'Sub\s*Total\s*Vent\w*\s*[S5]?/?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match_sub:
                    subtotal_venta = limpiar_moneda(match_sub.group(1))
                
                # Si hay dos montos en la línea, el segundo es subtotal
                if subtotal_venta == 0:
                    montos = re.findall(r'[\d,]+\.[\d]{2}', linea)
                    if len(montos) >= 2:
                        venta_gratuita = limpiar_moneda(montos[0])
                        subtotal_venta = limpiar_moneda(montos[1])
                
                print(f"    Venta Gratuita: {venta_gratuita}")
                print(f"    Subtotal Venta: {subtotal_venta}")
                continue
            
            # Solo Gratuitas (sin Sub Total en misma línea)
            if 'Gratuitas' in linea and 'Sub Total' not in linea:
                match_grat = re.search(r'Gratuitas\s*[S5]?/?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match_grat:
                    venta_gratuita = limpiar_moneda(match_grat.group(1))
                    print(f"    Venta Gratuita: {venta_gratuita}")
            
            # Solo Sub Total (sin Gratuitas en misma línea)
            if 'Sub Total' in linea and 'Gratuitas' not in linea:
                match_sub = re.search(r'Sub\s*Total\s*Vent\w*\s*[S5]?/?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match_sub:
                    subtotal_venta = limpiar_moneda(match_sub.group(1))
                    print(f"    Subtotal Venta: {subtotal_venta}")
            
            # Anticipos
            if 'Antic' in linea:
                anticipo = extraer_monto_de_linea(linea)
                print(f"    Anticipo: {anticipo}")
            
            # Descuentos
            if 'Descuento' in linea:
                descuento = extraer_monto_de_linea(linea)
                print(f"    Descuento: {descuento}")
            
            # Valor Venta (sin "Gratuitas" o "Sub Total")
            if 'Valor Venta' in linea and 'Gratuitas' not in linea and 'Operaciones' not in linea:
                # Extraer monto directamente ya que la línea es simple
                match_vv = re.search(r'Valor\s*Venta\s*([\d,.\.]+)', linea, re.IGNORECASE)
                if match_vv:
                    valor_venta = limpiar_moneda(match_vv.group(1))
                print(f"    Valor Venta: {valor_venta}")
            
            # ISC y descripción
            if 'ISC' in linea:
                match_isc = re.search(r'ISC\s*([\d,.]+)', linea)
                if match_isc:
                    isc = limpiar_moneda(match_isc.group(1))
                
                # Buscar descripción "SON: ..."
                match_son = re.search(r'SON:\s*([A-ZÁÉÍÓÚ\s]+)', linea, re.IGNORECASE)
                if match_son:
                    descripcion_importe = match_son.group(1).strip()
                    if not descripcion_importe.endswith('SOLES'):
                        descripcion_importe += " SOLES"
                
                print(f"    ISC: {isc}")
            
            # IGV (puede aparecer como IGV, IGv, igv)
            if 'IGV' in linea.upper():
                match_igv = re.search(r'IGV\s*([\d,.]+)', linea, re.IGNORECASE)
                if match_igv:
                    igv = limpiar_moneda(match_igv.group(1))
                print(f"    IGV: {igv}")
            
            # Otros Cargos
            if 'Otros Cargos' in linea:
                otros_cargos = extraer_monto_de_linea(linea)
                print(f"    Otros Cargos: {otros_cargos}")
            
            # Otros Tributos
            if 'Otros Tributos' in linea:
                otros_tributos = extraer_monto_de_linea(linea)
                print(f"    Otros Tributos: {otros_tributos}")
            
            # Redondeo
            if 'redondeo' in linea.lower():
                # El OCR puede poner {0.0D en lugar de 0.00
                match = re.search(r'redondeo\s*[\{]?\s*([\d,.]+)', linea, re.IGNORECASE)
                if match:
                    monto_redondeo = limpiar_moneda(match.group(1))
                print(f"    Monto Redondeo: {monto_redondeo}")
            
            # Importe Total
            if 'Importe Total' in linea:
                importe_total = extraer_monto_de_linea(linea)
                print(f"    Importe Total: {importe_total}")
        
        # VALIDACIÓN CRUZADA: IGV debería ser ~18% del valor_venta
        if valor_venta > 0 and igv > 0:
            igv_esperado = valor_venta * 0.18
            diferencia_pct = abs(igv - igv_esperado) / igv_esperado * 100
            if diferencia_pct > 5:  # Más de 5% de diferencia
                validaciones.append(f"VALIDACION: IGV ({igv}) difiere >5% del esperado ({igv_esperado:.2f})")
        
        # VALIDACIÓN CRUZADA: Inferir cantidad correcta si subtotal/valorUnitario es coherente
        # Solo corregir si el resultado es un número entero razonable (1-100)
        if lista_lineas and subtotal_venta > 0:
            linea_fact = lista_lineas[0]
            valor_unit = linea_fact.get("valorUnitario", 0)
            
            if valor_unit > 0:
                cantidad_inferida = subtotal_venta / valor_unit
                cantidad_ocr = linea_fact.get("cantidad", 0)
                
                # Solo corregir si la cantidad inferida es un entero razonable
                cantidad_inferida_int = round(cantidad_inferida)
                
                # Verificar que sea un entero limpio (diferencia < 0.1) y razonable
                es_entero_limpio = abs(cantidad_inferida - cantidad_inferida_int) < 0.1
                es_razonable = 1 <= cantidad_inferida_int <= 100
                
                if es_entero_limpio and es_razonable and abs(cantidad_inferida_int - cantidad_ocr) > 1:
                    print(f"    [CORRECCION] Cantidad OCR ({cantidad_ocr}) -> Inferida ({cantidad_inferida_int})")
                    print(f"                 (subtotal {subtotal_venta} / valor {valor_unit} = {cantidad_inferida:.2f})")
                    lista_lineas[0]["cantidad"] = float(cantidad_inferida_int)
                    validaciones.append(f"CORRECCION: Cantidad ajustada de {cantidad_ocr} a {cantidad_inferida_int} (calculada)")
                elif abs(cantidad_inferida_int - cantidad_ocr) > 5:
                    # La cantidad OCR parece errónea pero no podemos inferir la correcta
                    validaciones.append(f"ADVERTENCIA: Cantidad OCR ({cantidad_ocr}) puede ser incorrecta")
        
        # =====================================================================
        # SECCIÓN 5: CUOTAS (CRÉDITO)
        # =====================================================================
        print("\n[SECCION 5] Procesando CUOTAS...")
        
        total_cuotas = 0
        lista_cuotas = []
        monto_pendiente = 0.0
        
        for linea in lineas:
            # Buscar monto pendiente
            if 'pendiente de pago' in linea.lower():
                monto_pendiente = extraer_monto_de_linea(linea)
                print(f"    Monto Pendiente: {monto_pendiente}")
            
            # Buscar línea con múltiples fechas y montos (las cuotas)
            # Formato: "01/12/2025 2,100.00 28/12/2025 2,657.76 31/12/2025 2,500.00"
            fechas = re.findall(r'\d{2}/\d{2}/\d{4}', linea)
            if len(fechas) >= 2:  # Al menos 2 fechas indica línea de cuotas
                # Estrategia: Buscar todos los pares (fecha, monto) usando lookahead
                # Cada fecha es seguida por un monto hasta la siguiente fecha o fin de línea
                
                # Primero obtenemos todas las fechas y sus posiciones
                pos_fechas = [(m.start(), m.group()) for m in re.finditer(r'\d{2}/\d{2}/\d{4}', linea)]
                
                for idx, (pos, fecha) in enumerate(pos_fechas):
                    # El monto está entre esta fecha y la siguiente (o fin de línea)
                    inicio_monto = pos + len(fecha)
                    if idx + 1 < len(pos_fechas):
                        fin_monto = pos_fechas[idx + 1][0]
                    else:
                        fin_monto = len(linea)
                    
                    texto_monto = linea[inicio_monto:fin_monto]
                    # Extraer el primer número con formato de monto
                    match_monto = re.search(r'([\d,.]+)', texto_monto)
                    if match_monto:
                        monto = limpiar_moneda(match_monto.group(1))
                        if monto > 0:
                            lista_cuotas.append({
                                "numeroCuota": idx + 1,
                                "fechaVencimientoCuota": fecha,
                                "montoCuota": monto
                            })
                            print(f"    Cuota {idx + 1}: {fecha} - {monto}")
        
        total_cuotas = len(lista_cuotas)
        print(f"    Total Cuotas: {total_cuotas}")
        
        # VALIDACIÓN: Suma de cuotas debería aproximar al monto pendiente
        if lista_cuotas and monto_pendiente > 0:
            suma_cuotas = sum(c["montoCuota"] for c in lista_cuotas)
            # La suma puede diferir un poco por redondeos
            if abs(suma_cuotas - monto_pendiente) > monto_pendiente * 0.5:
                validaciones.append(f"VALIDACION: Suma cuotas ({suma_cuotas}) difiere mucho del pendiente ({monto_pendiente})")
        
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
    
    archivo = sys.argv[1] if len(sys.argv) > 1 else "factura_prueba.jpeg"
    print(f"\nProcesando: {archivo}\n")
    
    resultado = procesar_factura_img(archivo)
    
    print("\n" + "=" * 70)
    print("RESULTADO FINAL (JSON):")
    print("=" * 70)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
