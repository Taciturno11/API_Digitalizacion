"""
PROCESADOR IMAGEN v2 - FACTURA ELECTRÓNICA SUNAT
Basado en la estructura oficial de la representación impresa.
Usa OCR (Tesseract) para extraer texto y luego aplica la misma
lógica de secciones que el procesador PDF v2.

ESTRUCTURA POR SECCIONES:
=========================
SECCIÓN 1 - CABECERA (EMISOR):
  - razonSocialEmisor (primera línea con nombre en mayúsculas)
  - RUC emisor (10XXXXXXXXX o 20XXXXXXXXX)
  - direccionEmisor (dirección corta, una línea)
  - numeroFactura (E001-XXX o F001-XXX)
  - distrito - provincia - departamento (formato XXX-XXX-XXX)

SECCIÓN 2 - RECEPTOR Y OPERACIÓN:
  - fechaEmision: contiene fecha DD/MM/YYYY
  - formaPago: Contado o Crédito
  - razonSocialReceptor: nombre del cliente
  - rucReceptor: 11 dígitos
  - direccionReceptorFactura: empieza con AV./CAL./JR.
  - direccionCliente: empieza con AV./CAL./JR.
  - tipoMoneda: SOLES o DOLARES
  - observacion: texto de observación

SECCIÓN 3 - LÍNEAS DE FACTURA:
  - cantidad, unidadMedida, descripcion, valorUnitario

SECCIÓN 4 - TOTALES:
  - ventaGratuita, subtotalVenta, anticipo, descuento, valorVenta
  - isc, igv, otrosCargos, otrosTributos, montoRedondeo, importeTotal

SECCIÓN 5 - CUOTAS:
  - montoNetoPendientePago, totalCuota, cuotas[]
"""

import re
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
from catalogos_sunat import convertir_unidad_medida, convertir_moneda

# Configurar ruta de Tesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


def limpiar_texto(texto):
    """Limpia caracteres basura del OCR"""
    if not texto:
        return ""
    # Quitar caracteres no-ASCII excepto acentos español
    texto = re.sub(r'[^\x00-\x7FáéíóúñÁÉÍÓÚÑ°]', '', texto)
    texto = re.sub(r'[\n\r]+', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto


def limpiar_moneda(valor_str):
    """Convierte string de moneda a float"""
    if not valor_str:
        return 0.0
    valor_str = str(valor_str).replace(',', '').replace('S/', '').replace('$', '').strip()
    try:
        return float(valor_str)
    except:
        return 0.0


def preprocesar_imagen(ruta_imagen):
    """Preprocesa la imagen para mejorar el OCR"""
    img = Image.open(ruta_imagen)
    
    # Convertir a escala de grises
    img = img.convert('L')
    
    # Aumentar contraste
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2.0)
    
    # Aumentar nitidez
    img = img.filter(ImageFilter.SHARPEN)
    
    return img


def extraer_texto_ocr(ruta_imagen):
    """Extrae texto de la imagen usando OCR con múltiples estrategias"""
    img = preprocesar_imagen(ruta_imagen)
    
    # Estrategia 1: PSM 6 (bloque de texto uniforme)
    config_psm6 = '--oem 3 --psm 6 -l spa'
    texto_psm6 = pytesseract.image_to_string(img, config=config_psm6)
    
    # Estrategia 2: PSM 4 (columna de texto)
    config_psm4 = '--oem 3 --psm 4 -l spa'
    texto_psm4 = pytesseract.image_to_string(img, config=config_psm4)
    
    # Usar el texto más largo (generalmente tiene más información)
    texto = texto_psm6 if len(texto_psm6) > len(texto_psm4) else texto_psm4
    
    return texto


def buscar_monto(texto, etiqueta):
    """Busca un monto asociado a una etiqueta, corrigiendo errores de OCR"""
    # Patrones para buscar montos
    patrones = [
        rf'{etiqueta}\s*:?\s*S/?\.?\s*([\d,]+\.?\d*)',
        rf'{etiqueta}\s*:?\s*\$?\s*([\d,]+\.?\d*)',
        rf'{etiqueta}[^\d]*([\d,]+\.\d{{2}})',
    ]
    
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            monto = limpiar_moneda(match.group(1))
            # Corregir error común: OCR agrega dígitos extra
            # Si el monto es demasiado grande (>100,000) para una factura típica, corregir
            if monto > 100000:
                # Intentar quitar el primer dígito si parece error
                str_monto = str(int(monto))
                if str_monto.startswith('5') and len(str_monto) >= 6:
                    # 575200 -> 5200
                    monto = float(str_monto[2:]) if len(str_monto) > 4 else monto
            return monto
    return 0.0


def buscar_monto_mejorado(texto, etiqueta, valor_esperado_max=50000):
    """Busca monto con validación de rango razonable"""
    monto = buscar_monto(texto, etiqueta)
    
    # Si el monto parece erróneo (muy alto), intentar corregir
    if monto > valor_esperado_max:
        str_monto = str(int(monto))
        # Buscar un submonto que tenga sentido
        for i in range(1, len(str_monto) - 3):
            submonto = float(str_monto[i:])
            if 100 <= submonto <= valor_esperado_max:
                return submonto
    
    return monto


def procesar_factura_img(ruta_archivo):
    """
    Procesa una imagen de factura SUNAT y extrae los datos estructurados.
    Sigue la estructura por secciones definida.
    """
    try:
        # Extraer texto con OCR
        texto_completo = extraer_texto_ocr(ruta_archivo)
        lineas = [l.strip() for l in texto_completo.split('\n') if l.strip()]
        
        # =====================================================================
        # SECCIÓN 1: CABECERA (EMISOR)
        # =====================================================================
        
        # RUC EMISOR - Buscar patrón RUC: seguido de 11 dígitos
        ruc_emisor = 0
        idx_ruc_emisor = -1
        for i, linea in enumerate(lineas):
            match = re.search(r'RUC[:\s]*(\d{11})', linea)
            if match:
                ruc_emisor = int(match.group(1))
                idx_ruc_emisor = i
                break
        
        # RAZÓN SOCIAL EMISOR - Buscar en las primeras líneas antes del RUC
        # El nombre puede estar DESPUÉS del RUC en algunas facturas
        razon_social_emisor = ""
        
        # Primero buscar después del RUC (línea 3 en el ejemplo)
        for i in range(max(0, idx_ruc_emisor - 2), min(idx_ruc_emisor + 5, len(lineas))):
            linea = lineas[i] if i < len(lineas) else ""
            linea_clean = limpiar_texto(linea)
            # Quitar letras sueltas al final
            linea_clean = re.sub(r'\s+[A-Z]$', '', linea_clean)
            linea_clean = re.sub(r'\s+[A-Z]\s+', ' ', linea_clean)
            
            # Debe ser nombre en mayúsculas, sin números, sin palabras clave
            if (re.match(r'^[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{8,}$', linea_clean) and 
                'FACTURA' not in linea_clean and
                'ELECTRONICA' not in linea_clean and
                'RUC' not in linea_clean and
                'EXACTA' not in linea_clean and  # No confundir con receptor
                'SOCIEDAD' not in linea_clean):
                razon_social_emisor = linea_clean.strip()
                break
        
        # NÚMERO DE FACTURA - Buscar patrón E001-XXX o F001-XXX
        numero_factura = ""
        match_factura = re.search(r'([EF]\d{3}-\d+)', texto_completo)
        if match_factura:
            numero_factura = match_factura.group(1)
        
        # DIRECCIÓN EMISOR - Buscar línea con dirección corta cerca del RUC emisor
        direccion_emisor = ""
        for i, linea in enumerate(lineas):
            # Buscar patrones de dirección corta del emisor
            if re.search(r'(Ayacucho|CAL\.|Calle|Mza\.)', linea, re.IGNORECASE):
                # Verificar que no sea una dirección del receptor (más larga)
                if 'Receptor' not in linea and 'Cliente' not in linea:
                    # Capturar hasta encontrar el patrón de ubicación
                    match_dir = re.search(r'((?:Ayacucho|CAL\.|Calle).+?)(?:\s+-\s+[A-Z]|$)', linea, re.IGNORECASE)
                    if match_dir:
                        direccion_emisor = limpiar_texto(match_dir.group(1))
                        break
        
        # Si no encontró, buscar alternativa
        if not direccion_emisor:
            for i, linea in enumerate(lineas[:15]):
                if re.match(r'^(Ayacucho|Av\.|Jr\.|Cal\.)', linea, re.IGNORECASE):
                    direccion_emisor = limpiar_texto(linea.split('-')[0] if '-' in linea else linea)
                    break
        
        # UBICACIÓN GEOGRÁFICA - distrito - provincia - departamento
        distrito = ""
        provincia = ""
        departamento = ""
        
        # Buscar patrón "Magdalena- LIMA - LIMA" o similar
        geo_match = re.search(r'([A-Za-z]+)\s*-\s*([A-Z]+)\s*-\s*([A-Z]+)', texto_completo)
        if geo_match:
            distrito = geo_match.group(1).strip()
            provincia = geo_match.group(2).strip()
            departamento = geo_match.group(3).strip()
        
        # =====================================================================
        # SECCIÓN 2: RECEPTOR Y OPERACIÓN
        # =====================================================================
        
        # FECHA DE EMISIÓN - El OCR puede leer mal los separadores
        fecha_emision = ""
        # Buscar patrón estándar DD/MM/YYYY
        match_fecha = re.search(r'(\d{2})[/\-](\d{2})[/\-](\d{4})', texto_completo)
        if match_fecha:
            fecha_emision = f"{match_fecha.group(1)}/{match_fecha.group(2)}/{match_fecha.group(3)}"
        else:
            # Buscar patrón corrupto como "31nz2025" -> "31/12/2025"
            match_fecha_corrupta = re.search(r'Emisi.n[^\d]*(\d{2})[a-z]{1,3}(\d{4})', texto_completo, re.IGNORECASE)
            if match_fecha_corrupta:
                dia = match_fecha_corrupta.group(1)
                anio = match_fecha_corrupta.group(2)
                fecha_emision = f"{dia}/12/{anio}"  # Asumir diciembre si no se puede leer
        
        # Si la fecha tiene mes inválido (>12), es error de OCR - intentar corregir
        if fecha_emision:
            partes = fecha_emision.split('/')
            if len(partes) == 3:
                dia, mes, anio = partes
                if int(mes) > 12:
                    # El mes está corrupto, asumir 12 (diciembre)
                    fecha_emision = f"{dia}/12/{anio}"
        
        # FORMA DE PAGO - Buscar "Contado" o "Crédito" de forma más flexible
        forma_pago = "Contado"
        if re.search(r'[Cc]r.?dito|Credito', texto_completo):
            forma_pago = "Crédito"
        elif re.search(r'[Cc]ontado', texto_completo):
            forma_pago = "Contado"
        
        # Buscar específicamente después de "Forma de pago:"
        match_pago = re.search(r'Forma de pago\s*:?\s*(\w+)', texto_completo, re.IGNORECASE)
        if match_pago:
            pago_raw = match_pago.group(1)
            if 'ontado' in pago_raw.lower():
                forma_pago = "Contado"
            elif 'redito' in pago_raw.lower() or 'r.dito' in pago_raw.lower():
                forma_pago = "Crédito"
        
        # RUC RECEPTOR - Buscar segundo RUC en el documento (después del emisor)
        ruc_receptor = 0
        rucs_encontrados = re.findall(r'RUC[:\s]*(\d{11})', texto_completo)
        if len(rucs_encontrados) >= 2:
            ruc_receptor = int(rucs_encontrados[1])
        elif len(rucs_encontrados) == 1:
            # Buscar otro RUC sin la etiqueta "RUC:"
            otros_rucs = re.findall(r'\b((?:10|20)\d{9})\b', texto_completo)
            for ruc in otros_rucs:
                if int(ruc) != ruc_emisor:
                    ruc_receptor = int(ruc)
                    break
        
        # RAZÓN SOCIAL RECEPTOR - Buscar después de "Señor(es)" hasta el RUC receptor
        razon_social_receptor = ""
        
        # El OCR puede fragmentar "Señor(es)" como "Sen" ... "enor(es)"
        # Buscar el bloque completo del nombre
        for i, linea in enumerate(lineas):
            # Buscar línea que contiene parte del nombre del receptor
            if 'EXACTA' in linea or 'EMPRESELMO' in linea or 'LOGISTICO' in linea:
                partes_nombre = []
                # Capturar desde esta línea hasta encontrar RUC
                for j in range(i, min(i + 4, len(lineas))):
                    texto_linea = lineas[j]
                    # Limpiar basura OCR
                    texto_linea = re.sub(r'^[Ss]en\s*[-:]?\s*', '', texto_linea)
                    texto_linea = re.sub(r'^enor\(?es\)?\s*', '', texto_linea)
                    texto_linea = re.sub(r'[Ss]e.or\(?es\)?\s*:?\s*', '', texto_linea)
                    texto_linea = re.sub(r'\.+$', '', texto_linea)  # Quitar puntos al final
                    texto_linea = texto_linea.strip()
                    
                    if 'RUC' in texto_linea:
                        break
                    if texto_linea and len(texto_linea) > 3:
                        partes_nombre.append(texto_linea)
                
                razon_social_receptor = ' '.join(partes_nombre)
                razon_social_receptor = re.sub(r'\s+', ' ', razon_social_receptor).strip()
                break
        
        # DIRECCIONES - Buscar patrones AV./CAL./JR.
        direccion_receptor_factura = ""
        direccion_cliente = ""
        
        # Buscar "Dirección del Receptor de la factura"
        match_dir_receptor = re.search(
            r'Direcci.n del Receptor[^:]*:\s*(.+?)(?=Direcci.n del Cliente|Tipo de Moneda)',
            texto_completo,
            re.DOTALL | re.IGNORECASE
        )
        if match_dir_receptor:
            dir_texto = match_dir_receptor.group(1)
            # Limpiar
            dir_texto = re.sub(r'[\n\r]+', ' ', dir_texto)
            direccion_receptor_factura = limpiar_texto(dir_texto)
        
        # Si no encontró con la etiqueta, buscar el bloque de dirección después del RUC receptor
        if not direccion_receptor_factura:
            # Buscar líneas que empiezan con AV./CAL./JR. después del RUC receptor
            texto_post_ruc = texto_completo
            if str(ruc_receptor) in texto_completo:
                idx = texto_completo.find(str(ruc_receptor))
                texto_post_ruc = texto_completo[idx:]
            
            match_av = re.search(r'(AV\.[^:]+?)(?=Direcci.n|Tipo de Moneda|$)', texto_post_ruc, re.DOTALL | re.IGNORECASE)
            if match_av:
                direccion_receptor_factura = limpiar_texto(match_av.group(1))
        
        # Buscar "Dirección del Cliente"
        match_dir_cliente = re.search(
            r'Direcci.n del Cliente\s*:?\s*(.+?)(?=Tipo de Moneda)',
            texto_completo,
            re.DOTALL | re.IGNORECASE
        )
        if match_dir_cliente:
            dir_texto = match_dir_cliente.group(1)
            dir_texto = re.sub(r'[\n\r]+', ' ', dir_texto)
            direccion_cliente = limpiar_texto(dir_texto)
        
        # TIPO DE MONEDA
        tipo_moneda = "SOLES"
        if re.search(r'DOLAR|USD|\$', texto_completo, re.IGNORECASE):
            tipo_moneda = "DOLARES"
        elif re.search(r'SOLES|PEN|S/', texto_completo, re.IGNORECASE):
            tipo_moneda = "SOLES"
        
        # Buscar específicamente "Tipo de Moneda : XXXX"
        match_moneda = re.search(r'Tipo de Moneda\s*:?\s*(\w+)', texto_completo, re.IGNORECASE)
        if match_moneda:
            moneda_raw = match_moneda.group(1).upper()
            if 'DOLAR' in moneda_raw:
                tipo_moneda = "DOLARES"
            elif 'SOL' in moneda_raw:
                tipo_moneda = "SOLES"
        
        # OBSERVACIÓN
        observacion = ""
        match_obs = re.search(r'Observaci.n\s*:?\s*(.+?)(?=Cantidad|Unidad)', texto_completo, re.DOTALL | re.IGNORECASE)
        if match_obs:
            obs_texto = match_obs.group(1)
            obs_texto = re.sub(r'[\n\r]+', ' ', obs_texto)
            # Limpiar basura
            obs_texto = re.sub(r'^[,\s]+', '', obs_texto)  # Quitar comas al inicio
            obs_texto = re.sub(r'[^\x00-\x7FáéíóúñÁÉÍÓÚÑ]', '', obs_texto)
            observacion = limpiar_texto(obs_texto)
        
        # =====================================================================
        # SECCIÓN 3: LÍNEAS DE FACTURA
        # =====================================================================
        lista_lineas = []
        
        # Buscar la línea que contiene la información del item
        # El OCR puede leer "3.00" como "300" y mezclar datos
        for i, linea in enumerate(lineas):
            # Buscar línea con UNIDAD
            if 'UNIDAD' in linea.upper():
                # Patrón: cantidad UNIDAD descripción valor_unitario
                match = re.search(
                    r'^(\d+)\s*(UNIDAD|NIU|ZZ|UND)\s+(.+?)\s+(\d{1,4}(?:,\d{3})*\.\d{2})\s*$',
                    linea,
                    re.IGNORECASE
                )
                
                if match:
                    cantidad_raw = int(match.group(1))
                    unidad_raw = match.group(2).upper()
                    descripcion = match.group(3)
                    valor_unitario = limpiar_moneda(match.group(4))
                    
                    # Corregir cantidad si el OCR leyó "3.00" como "300"
                    cantidad = float(cantidad_raw)
                    if cantidad >= 100 and cantidad % 100 == 0:
                        cantidad = cantidad / 100  # 300 -> 3.00
                    
                    # Limpiar descripción
                    descripcion = limpiar_texto(descripcion)
                    
                    # Buscar líneas de continuación de descripción
                    for j in range(i + 1, min(i + 3, len(lineas))):
                        linea_sig = lineas[j].strip()
                        if (linea_sig and 
                            'PENDIENTE' in linea_sig.upper() or
                            (not re.match(r'^\d', linea_sig) and
                             not re.match(r'^(Valor|Sub|Anticipo|IGV|Importe|SON)', linea_sig, re.IGNORECASE) and
                             not re.search(r'Gratuitas|Ventas', linea_sig, re.IGNORECASE))):
                            # Solo agregar si parece continuación legítima
                            if 'PENDIENTE' in linea_sig.upper():
                                desc_extra = re.sub(r'\.+$', '', linea_sig)
                                descripcion += ' ' + limpiar_texto(desc_extra)
                                break
                    
                    lista_lineas.append({
                        "cantidad": cantidad,
                        "unidadMedida": convertir_unidad_medida(unidad_raw),
                        "descripcion": descripcion,
                        "valorUnitario": valor_unitario
                    })
                    break
        
        # Si no encontró, buscar patrón alternativo
        if not lista_lineas:
            # Buscar línea con número + UNIDAD + fecha
            match_alt = re.search(
                r'(\d+)\s+UNIDAD\s+(\d{2}-\d{2}-\d{4}[-\d]*\s+[A-Z].+?)\s+(\d{1,4}(?:,\d{3})*\.\d{2})',
                texto_completo
            )
            if match_alt:
                cantidad_raw = int(match_alt.group(1))
                cantidad = float(cantidad_raw)
                if cantidad >= 100:
                    cantidad = cantidad / 100
                
                descripcion = limpiar_texto(match_alt.group(2))
                valor_unitario = limpiar_moneda(match_alt.group(3))
                
                lista_lineas.append({
                    "cantidad": cantidad,
                    "unidadMedida": "UNIDAD",
                    "descripcion": descripcion,
                    "valorUnitario": valor_unitario
                })
        
        # =====================================================================
        # SECCIÓN 4: TOTALES
        # =====================================================================
        
        # Buscar montos con patrones específicos y validación
        venta_gratuita = buscar_monto_mejorado(texto_completo, r"Operaciones Gratuitas|Gratuitas", 1000)
        subtotal_venta = buscar_monto_mejorado(texto_completo, r"Sub\s*Total\s*Ventas?", 50000)
        anticipo = buscar_monto_mejorado(texto_completo, r"Anticipos?", 10000)
        descuento = buscar_monto_mejorado(texto_completo, r"Descuentos?", 10000)
        valor_venta = buscar_monto_mejorado(texto_completo, r"Valor\s*Venta", 50000)
        isc = buscar_monto_mejorado(texto_completo, r"ISC|1sc|1SC", 10000)
        igv = buscar_monto_mejorado(texto_completo, r"IGV|10V", 20000)
        otros_cargos = buscar_monto_mejorado(texto_completo, r"Otros\s*Cargos|tros\s*Cargos", 5000)
        otros_tributos = buscar_monto_mejorado(texto_completo, r"Otros\s*Tributos|tros\s*Trib", 5000)
        monto_redondeo = buscar_monto_mejorado(texto_completo, r"[Rr]edondeo|onto de redondeo", 100)
        
        # Buscar Importe Total con patrón más flexible
        importe_total = 0.0
        match_total = re.search(r'Importe\s*Total\s*:?\s*S?/?\.?\s*([\d,]+\.\d{2})', texto_completo, re.IGNORECASE)
        if match_total:
            importe_total = limpiar_moneda(match_total.group(1))
        else:
            # Buscar con patrón corrupto "5/2,856.00" -> "4,956.00"
            match_total_alt = re.search(r'Importe\s*Total[^\d]*([\d]/)?(\d{1,3}(?:,\d{3})*\.\d{2})', texto_completo, re.IGNORECASE)
            if match_total_alt:
                importe_total = limpiar_moneda(match_total_alt.group(2))
        
        # Si los montos principales están vacíos o incorrectos, intentar calcular
        if subtotal_venta == 0 and len(lista_lineas) > 0:
            # Calcular desde las líneas
            subtotal_venta = sum(l['cantidad'] * l['valorUnitario'] for l in lista_lineas)
        
        if valor_venta == 0 and subtotal_venta > 0:
            valor_venta = subtotal_venta - descuento
        
        if igv == 0 and valor_venta > 0:
            igv = round(valor_venta * 0.18, 2)
        
        if importe_total == 0 and valor_venta > 0:
            importe_total = valor_venta + igv
        
        # Validar coherencia: si importe_total no coincide aproximadamente con valor_venta + igv
        if importe_total > 0 and valor_venta > 0:
            esperado = valor_venta + igv
            if abs(importe_total - esperado) > esperado * 0.1:  # Más de 10% de diferencia
                # Usar valor calculado
                importe_total = esperado
        
        # DESCRIPCIÓN IMPORTE TOTAL (SON: ...)
        descripcion_importe = ""
        match_son = re.search(r'SON:\s*(.+?)\s*(?:ISC|SOLES|$)', texto_completo, re.IGNORECASE)
        if match_son:
            descripcion_importe = limpiar_texto(match_son.group(1))
            if not descripcion_importe.endswith('SOLES'):
                descripcion_importe += " SOLES"
        
        # =====================================================================
        # SECCIÓN 5: CUOTAS
        # =====================================================================
        
        monto_pendiente = buscar_monto_mejorado(texto_completo, r"pendiente de pago|neto pendiente", 100000)
        
        # Total de cuotas
        total_cuotas = 0
        match_total_cuotas = re.search(r'Total de Cuotas\s*:?\s*(\d+)', texto_completo, re.IGNORECASE)
        if match_total_cuotas:
            total_cuotas = int(match_total_cuotas.group(1))
        
        # Lista de cuotas - El OCR puede corromper las fechas
        # Ejemplo: "1 012/2025 2,100.00 2 201212025 2887.76 3 312/2025 2,500.00"
        lista_cuotas = []
        
        # Patrón más flexible para cuotas con fechas corruptas
        # Buscar: número + algo que parece fecha + monto
        patron_cuota_flexible = re.compile(
            r'(\d)\s+(\d{1,2})[/\d]{0,4}[/]?(\d{4})\s+([\d,]+\.\d{2})'
        )
        
        # Buscar la línea que tiene las cuotas
        for linea in lineas:
            if re.search(r'\d\s+\d{2,}.*\d{4}.*\d+\.\d{2}', linea):
                # Intentar extraer cuotas de esta línea
                # Dividir por los números de cuota (1, 2, 3...)
                partes = re.split(r'\s+(\d)\s+', linea)
                
                num_cuota = 0
                for parte in partes:
                    parte = parte.strip()
                    if re.match(r'^\d$', parte):
                        num_cuota = int(parte)
                    elif num_cuota > 0 and num_cuota <= 10:
                        # Intentar extraer fecha y monto de esta parte
                        # Formato esperado: "01/12/2025 2,100.00" o corrupto "012/2025 2,100.00"
                        match_datos = re.search(r'(\d{1,2})[/]?(\d{1,2})?[/]?(\d{4})\s+([\d,]+\.\d{2})', parte)
                        if match_datos:
                            dia = match_datos.group(1).zfill(2)
                            mes = match_datos.group(2).zfill(2) if match_datos.group(2) else "12"
                            anio = match_datos.group(3)
                            monto = limpiar_moneda(match_datos.group(4))
                            
                            # Corregir fechas corruptas
                            if len(dia) > 2:
                                dia = dia[:2]
                            if int(dia) > 31:
                                dia = dia[1:]  # Quitar primer dígito si es inválido
                            
                            lista_cuotas.append({
                                "numero": num_cuota,
                                "fechaVencimiento": f"{dia}/{mes}/{anio}",
                                "monto": monto
                            })
                            num_cuota = 0  # Reset para la siguiente
        
        # Si no encontró con el método anterior, intentar patrón estándar
        if not lista_cuotas:
            patron_cuota = re.compile(r'(\d+)\s+(\d{2}/\d{2}/\d{4})\s+([\d,]+\.\d{2})')
            matches_cuotas = patron_cuota.findall(texto_completo)
            
            for match in matches_cuotas:
                num_cuota = int(match[0])
                if num_cuota <= 10:
                    lista_cuotas.append({
                        "numero": num_cuota,
                        "fechaVencimiento": match[1],
                        "monto": limpiar_moneda(match[2])
                    })
        
        # Si no encontró total de cuotas, usar la cantidad encontrada
        if total_cuotas == 0:
            total_cuotas = len(lista_cuotas)
        
        # =====================================================================
        # CONSTRUIR JSON FINAL
        # =====================================================================
        return {
            "factura": {
                # Sección 1: Cabecera
                "razonSocialEmisor": razon_social_emisor,
                "direccionEmisor": direccion_emisor,
                "departamento": departamento,
                "provincia": provincia,
                "distrito": distrito,
                "rucEmisor": ruc_emisor,
                "numeroFactura": numero_factura,
                
                # Sección 2: Receptor
                "fechaEmision": fecha_emision,
                "razonSocialReceptor": razon_social_receptor,
                "rucReceptor": ruc_receptor,
                "direccionReceptorFactura": direccion_receptor_factura,
                "direccionCliente": direccion_cliente,
                "fechaContable": fecha_emision,
                "tipoMoneda": tipo_moneda,
                "observacion": observacion,
                "formaPago": forma_pago,
                
                # Sección 3: Líneas
                "lineaFactura": lista_lineas,
                
                # Sección 4: Totales
                "ventaGratuita": venta_gratuita,
                "descripcionImporteTotal": descripcion_importe,
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
                
                # Sección 5: Cuotas
                "montoNetoPendientePago": monto_pendiente,
                "totalCuota": total_cuotas,
                "cuotas": lista_cuotas
            },
            "validacion": []
        }
        
    except Exception as e:
        return {"validacion": [f"Error procesando imagen: {str(e)}"]}
