"""
PROCESADOR IMAGEN v3 - FACTURA ELECTRÓNICA SUNAT
Usa EasyOCR (deep learning) + preprocesamiento de imagen para máxima precisión.

ESTRUCTURA POR SECCIONES:
=========================
SECCIÓN 1 - CABECERA (EMISOR)
SECCIÓN 2 - RECEPTOR Y OPERACIÓN  
SECCIÓN 3 - LÍNEAS DE FACTURA
SECCIÓN 4 - TOTALES
SECCIÓN 5 - CUOTAS

SIN VALORES HARDCODEADOS - Todo se extrae dinámicamente del texto OCR.
"""

import re
import easyocr
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from catalogos_sunat import convertir_unidad_medida, convertir_moneda

# =============================================================================
# SINGLETON EASYOCR READER
# =============================================================================
_reader = None

def get_reader():
    """Obtiene el reader de EasyOCR (singleton para eficiencia)"""
    global _reader
    if _reader is None:
        print("[OCR] Inicializando EasyOCR...")
        _reader = easyocr.Reader(['es'], gpu=False)
    return _reader


# =============================================================================
# PREPROCESAMIENTO DE IMAGEN
# =============================================================================

def preprocesar_imagen(ruta_imagen):
    """
    Preprocesa la imagen para mejorar la precisión del OCR.
    - Aumenta contraste
    - Convierte a escala de grises
    - Aplica nitidez
    """
    try:
        img = Image.open(ruta_imagen)
        
        # Convertir a RGB si es necesario
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Aumentar contraste
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        
        # Aumentar nitidez
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(2.0)
        
        # Convertir a array numpy para EasyOCR
        return np.array(img)
    except:
        return ruta_imagen  # Si falla, usar original


# =============================================================================
# FUNCIONES DE UTILIDAD
# =============================================================================

def limpiar_texto(texto):
    """Limpia caracteres basura del OCR"""
    if not texto:
        return ""
    # Mantener caracteres válidos
    texto = re.sub(r'[^\w\s\-/.,;:°áéíóúñÁÉÍÓÚÑ()]', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto


def limpiar_moneda(valor_str):
    """
    Convierte string de moneda a float con manejo inteligente de errores OCR.
    Maneja: "S/ 4,500.00", "51 756.00" (OCR error), "5.200.00", "5,200.00"
    """
    if not valor_str:
        return 0.0
    
    valor_str = str(valor_str).strip()
    
    # Guardar original para debug
    original = valor_str
    
    # 1. Quitar símbolos de moneda (S/, SI, 51, $)
    valor_str = re.sub(r'^S/?I?\s*', '', valor_str, flags=re.IGNORECASE)
    valor_str = re.sub(r'^\$\s*', '', valor_str)
    
    # 2. Quitar espacios
    valor_str = valor_str.replace(' ', '')
    
    # 3. Reemplazar O/o por 0 (error común OCR)
    valor_str = re.sub(r'[Oo]', '0', valor_str)
    
    # 4. Detectar formato y normalizar
    # Caso: "5.200.00" o "55.200.00" (punto como separador miles)
    if valor_str.count('.') == 2:
        partes = valor_str.split('.')
        # El último es decimal, los anteriores son miles
        valor_str = ''.join(partes[:-1]) + '.' + partes[-1]
    
    # Caso: "5,200.00" (coma como separador miles) - formato correcto
    elif ',' in valor_str and '.' in valor_str:
        valor_str = valor_str.replace(',', '')
    
    # Caso: solo coma "5,200" -> asumir que es separador miles
    elif ',' in valor_str and '.' not in valor_str:
        valor_str = valor_str.replace(',', '')
    
    try:
        resultado = float(valor_str)
        return resultado
    except:
        return 0.0


def extraer_texto_easyocr(ruta_imagen):
    """
    Extrae texto de la imagen usando EasyOCR con preprocesamiento.
    Retorna: (texto_completo, lineas_ordenadas, resultados_raw)
    """
    ocr = get_reader()
    
    # Preprocesar imagen
    imagen_procesada = preprocesar_imagen(ruta_imagen)
    
    # Leer con EasyOCR
    resultados = ocr.readtext(imagen_procesada, detail=1, paragraph=False)
    
    # Ordenar por posición Y (vertical) y luego X (horizontal)
    resultados_ordenados = sorted(resultados, key=lambda x: (x[0][0][1], x[0][0][0]))
    
    # Construir líneas agrupando por coordenada Y similar
    lineas = []
    linea_actual = []
    y_anterior = -100
    umbral_y = 12  # Píxeles de tolerancia para considerar misma línea
    
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


def buscar_valor_despues_de(texto, etiqueta, tipo='texto'):
    """
    Busca un valor después de una etiqueta.
    tipo: 'texto', 'monto', 'fecha', 'numero'
    """
    patrones = {
        'monto': rf'{etiqueta}\s*:?\s*S?/?I?\s*([\d.,]+)',
        'fecha': rf'{etiqueta}\s*:?\s*(\d{{2}}/\d{{2}}/\d{{4}})',
        'numero': rf'{etiqueta}\s*:?\s*(\d+)',
        'texto': rf'{etiqueta}\s*:?\s*(.+?)(?:\n|$)',
    }
    
    patron = patrones.get(tipo, patrones['texto'])
    match = re.search(patron, texto, re.IGNORECASE)
    
    if match:
        valor = match.group(1).strip()
        if tipo == 'monto':
            return limpiar_moneda(valor)
        return valor
    return None


def extraer_monto_inteligente(texto, etiqueta):
    """
    Extrae un monto de forma inteligente manejando errores comunes del OCR.
    El OCR puede leer "S/ 5,200.00" como "51 5.200.00" o "55.200.00"
    """
    # Buscar la línea que contiene la etiqueta
    lineas = texto.split('\n')
    for linea in lineas:
        if re.search(etiqueta, linea, re.IGNORECASE):
            # Extraer todos los números con decimales de la línea
            numeros = re.findall(r'[\d.,]+\.[\d]{2}', linea)
            
            if numeros:
                # Tomar el último número (generalmente es el valor)
                return limpiar_moneda(numeros[-1])
            
            # Si no hay con decimales, buscar cualquier número
            numeros = re.findall(r'[\d.,]+', linea)
            if numeros:
                return limpiar_moneda(numeros[-1])
    
    return 0.0


# =============================================================================
# PROCESADOR PRINCIPAL POR SECCIONES
# =============================================================================

def procesar_factura_img(ruta_archivo):
    """
    Procesa una imagen de factura SUNAT usando EasyOCR.
    Extrae datos dinámicamente sin valores hardcodeados.
    """
    validaciones = []
    
    try:
        # Extraer texto con EasyOCR
        texto_completo, lineas, resultados_raw = extraer_texto_easyocr(ruta_archivo)
        
        # Debug: mostrar texto extraído
        print("=" * 60)
        print("TEXTO EXTRAIDO POR EASYOCR:")
        print("=" * 60)
        for i, linea in enumerate(lineas):
            print(f"[{i:02d}] {linea}")
        print("=" * 60)
        
        if not lineas:
            return {"validacion": ["No se pudo extraer texto de la imagen"]}
        
        # =====================================================================
        # SECCIÓN 1: CABECERA (EMISOR)
        # =====================================================================
        print("\n[SECCION 1] Procesando CABECERA (EMISOR)...")
        
        # RUC EMISOR - Buscar primer RUC de 11 dígitos (formato 10xxx o 20xxx)
        ruc_emisor = 0
        match_ruc = re.search(r'RUC[:\s]*(\d{11})', texto_completo)
        if match_ruc:
            ruc_emisor = int(match_ruc.group(1))
            print(f"    RUC Emisor: {ruc_emisor}")
        else:
            validaciones.append("SECCION 1: No se encontro RUC del emisor")
        
        # RAZÓN SOCIAL EMISOR - Buscar nombre completo antes del RUC
        razon_social_emisor = ""
        for i, linea in enumerate(lineas[:5]):
            # Buscar línea que contiene RUC
            if 'RUC' in linea and re.search(r'\d{11}', linea):
                # La razón social está antes del RUC en la misma línea o línea anterior
                match = re.search(r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+)\s+RUC', linea)
                if match:
                    razon_social_emisor = match.group(1).strip()
                elif i > 0:
                    # Buscar en línea anterior
                    linea_ant = lineas[i-1]
                    if re.match(r'^[A-ZÁÉÍÓÚÑ]', linea_ant):
                        razon_social_emisor = limpiar_texto(linea_ant)
                print(f"    Razon Social Emisor: {razon_social_emisor}")
                break
        
        # NÚMERO DE FACTURA - Formato E001-XXX o F001-XXX
        numero_factura = ""
        match_factura = re.search(r'([EF]\d{3}[-]?\d+)', texto_completo)
        if match_factura:
            numero_factura = match_factura.group(1)
            if '-' not in numero_factura:
                numero_factura = numero_factura[:4] + '-' + numero_factura[4:]
            print(f"    Numero Factura: {numero_factura}")
        
        # DIRECCIÓN EMISOR - Buscar en primeras líneas
        direccion_emisor = ""
        for linea in lineas[:3]:
            # Buscar dirección típica (Ayacucho, Av., Jr., Cal., etc.)
            if re.search(r'(Ayacucho|Av\.|Jr\.|Cal\.|Calle)\s+\d+', linea, re.IGNORECASE):
                # Extraer parte de dirección
                match = re.search(r'((?:Ayacucho|Av\.|Jr\.|Cal\.|Calle)[^R]+)', linea, re.IGNORECASE)
                if match:
                    direccion_emisor = limpiar_texto(match.group(1))
                    print(f"    Direccion Emisor: {direccion_emisor}")
                    break
        
        # UBICACIÓN GEOGRÁFICA - Buscar patrón XXX-XXX-XXX o XXX XXX XXX
        distrito, provincia, departamento = "", "", ""
        # Buscar en la cabecera el patrón de ubicación
        for linea in lineas[:3]:
            geo_match = re.search(r'(\w+)\s*[-]\s*([A-Z]+)\s*[-]\s*([A-Z]+)', linea)
            if geo_match:
                distrito = geo_match.group(1).strip()
                provincia = geo_match.group(2).strip()
                departamento = geo_match.group(3).strip()
                print(f"    Ubicacion: {distrito} - {provincia} - {departamento}")
                break
        
        # =====================================================================
        # SECCIÓN 2: RECEPTOR Y OPERACIÓN
        # =====================================================================
        print("\n[SECCION 2] Procesando RECEPTOR Y OPERACION...")
        
        # FECHA DE EMISIÓN
        fecha_emision = ""
        match_fecha = re.search(r'Fecha de Emisi[oó]n\s*:?\s*(\d{2}/\d{2}/\d{4})', texto_completo, re.IGNORECASE)
        if match_fecha:
            fecha_emision = match_fecha.group(1)
        else:
            # Buscar cualquier fecha en formato DD/MM/YYYY
            match_fecha = re.search(r'(\d{2}/\d{2}/\d{4})', texto_completo)
            if match_fecha:
                fecha_emision = match_fecha.group(1)
        print(f"    Fecha Emision: {fecha_emision}")
        
        # FORMA DE PAGO - Buscar explícitamente "Contado" o "Crédito"
        forma_pago = "Contado"  # Default
        # Buscar en la línea que contiene "Forma de pago"
        match_forma = re.search(r'Forma de pago\s*:?\s*(Contado|Cr[eé]dito)', texto_completo, re.IGNORECASE)
        if match_forma:
            forma_pago = match_forma.group(1).capitalize()
            if 'cre' in forma_pago.lower() or 'cré' in forma_pago.lower():
                forma_pago = "Credito"
            else:
                forma_pago = "Contado"
        print(f"    Forma de Pago: {forma_pago}")
        
        # RUC RECEPTOR - Buscar segundo RUC diferente al emisor
        ruc_receptor = 0
        todos_rucs = re.findall(r'RUC\s*:?\s*(\d{11})', texto_completo)
        for ruc in todos_rucs:
            ruc_int = int(ruc)
            if ruc_int != ruc_emisor:
                ruc_receptor = ruc_int
                print(f"    RUC Receptor: {ruc_receptor}")
                break
        
        # RAZÓN SOCIAL RECEPTOR - Buscar después de "Señor(es)"
        razon_social_receptor = ""
        for i, linea in enumerate(lineas):
            if 'Se' in linea and 'or' in linea:  # Señor(es)
                # La razón social puede estar en esta línea o la siguiente
                texto_buscar = linea
                if i + 1 < len(lineas):
                    texto_buscar += ' ' + lineas[i + 1]
                
                # Buscar nombre de empresa (MAYUSCULAS, palabras como SOCIEDAD, S.A.C., etc.)
                match = re.search(r'(?:Se.or\(?es\)?\s*:?\s*)?([A-Z][A-Z\s]+(?:SOCIEDAD|S\.?A\.?C?\.?|E\.?I\.?R\.?L\.?|CERRADA|ABIERTA)[A-Z\s]*)', texto_buscar)
                if match:
                    razon_social_receptor = limpiar_texto(match.group(1))
                    print(f"    Razon Social Receptor: {razon_social_receptor}")
                    break
        
        # DIRECCIONES - Estrategia mejorada
        direccion_receptor = ""
        direccion_cliente = ""
        
        # Buscar líneas que contienen las direcciones
        for i, linea in enumerate(lineas):
            # DIRECCIÓN RECEPTOR DE LA FACTURA
            if 'Receptor' in linea and 'factura' in linea:
                # Estructura: "AV... Dirección del Receptor de la factura CRUCE DE..."
                # Parte 1: antes de "Dirección del Receptor"
                parte1 = ""
                match_antes = re.search(r'^(AV\.?[^D]+)', linea, re.IGNORECASE)
                if match_antes:
                    parte1 = match_antes.group(1).strip()
                
                # Parte 2: después de "factura"
                parte2 = ""
                match_despues = re.search(r'factura\s+(.+?)$', linea, re.IGNORECASE)
                if match_despues:
                    parte2 = match_despues.group(1).strip()
                
                # Combinar
                if parte1 and parte2:
                    direccion_receptor = f"{parte1} {parte2}"
                elif parte1:
                    direccion_receptor = parte1
                elif parte2:
                    direccion_receptor = parte2
                
                direccion_receptor = limpiar_texto(direccion_receptor)
                print(f"    Direccion Receptor: {direccion_receptor}")
            
            # DIRECCIÓN CLIENTE
            if 'Cliente' in linea and 'Direcci' in linea:
                # Estructura similar
                parte1 = ""
                match_antes = re.search(r'^(AV\.?[^D]+)', linea, re.IGNORECASE)
                if match_antes:
                    parte1 = match_antes.group(1).strip()
                
                parte2 = ""
                match_despues = re.search(r'Cliente\s+(.+?)(?:Tipo|$)', linea, re.IGNORECASE)
                if match_despues:
                    parte2 = match_despues.group(1).strip()
                
                if parte1 and parte2:
                    direccion_cliente = f"{parte1} {parte2}"
                elif parte1:
                    direccion_cliente = parte1
                elif parte2:
                    direccion_cliente = parte2
                
                direccion_cliente = limpiar_texto(direccion_cliente)
                print(f"    Direccion Cliente: {direccion_cliente}")
        
        # TIPO DE MONEDA
        tipo_moneda = "SOLES"
        match_moneda = re.search(r'Tipo de Moneda\s*:?\s*(\w+)', texto_completo, re.IGNORECASE)
        if match_moneda:
            moneda = match_moneda.group(1).upper()
            if 'DOLAR' in moneda:
                tipo_moneda = "DOLARES"
        print(f"    Tipo Moneda: {tipo_moneda}")
        
        # OBSERVACIÓN
        observacion = ""
        match_obs = re.search(r'Observaci[oó]n\s*:?\s*(.+?)(?:Cantidad|$)', texto_completo, re.IGNORECASE | re.DOTALL)
        if match_obs:
            observacion = limpiar_texto(match_obs.group(1))[:150]
            print(f"    Observacion: {observacion}")
        
        # =====================================================================
        # SECCIÓN 3: LÍNEAS DE FACTURA
        # =====================================================================
        print("\n[SECCION 3] Procesando LINEAS DE FACTURA...")
        lista_lineas = []
        
        # Buscar patrón: cantidad UNIDAD descripción valorUnitario
        for i, linea in enumerate(lineas):
            # Patrón flexible: número UNIDAD/NIU texto número
            match = re.search(r'(\d+\.?\d*)\s*(UNIDAD|NIU|ZZ|UND)\s+(.+?)\s+(\d[\d,]*\.?\d*)\s*$', linea, re.IGNORECASE)
            if match:
                cantidad = float(match.group(1))
                unidad = match.group(2).upper()
                descripcion = limpiar_texto(match.group(3))
                valor_str = match.group(4)
                valor_unitario = limpiar_moneda(valor_str)
                
                # Buscar continuación de descripción en línea siguiente
                if i + 1 < len(lineas):
                    sig_linea = lineas[i + 1]
                    # Si no empieza con número ni palabra clave de totales
                    if not re.match(r'^(\d|Valor|Sub|SON|IGV|Importe|Gratuitas)', sig_linea, re.IGNORECASE):
                        descripcion += ' ' + limpiar_texto(sig_linea)
                
                print(f"    Linea: cant={cantidad}, unidad={unidad}, valor={valor_unitario}")
                print(f"           desc={descripcion[:50]}...")
                
                lista_lineas.append({
                    "cantidad": cantidad,
                    "unidadMedida": convertir_unidad_medida(unidad),
                    "descripcion": descripcion,
                    "valorUnitario": valor_unitario
                })
        
        # Si no encontramos con el patrón completo, buscar alternativo
        if not lista_lineas:
            for linea in lineas:
                if 'UNIDAD' in linea.upper():
                    # Buscar valor numérico grande (precio)
                    numeros = re.findall(r'(\d{3,}\.?\d*)', linea)
                    if numeros:
                        valor_unitario = float(numeros[-1])
                        
                        # Buscar cantidad al inicio
                        match_cant = re.search(r'^(\d+\.?\d*)', linea)
                        cantidad = float(match_cant.group(1)) if match_cant else 1.0
                        
                        # Extraer descripción
                        match_desc = re.search(r'UNIDAD\s+(.+?)\s+\d{3,}', linea, re.IGNORECASE)
                        descripcion = match_desc.group(1) if match_desc else ""
                        
                        lista_lineas.append({
                            "cantidad": cantidad,
                            "unidadMedida": "UNIDAD",
                            "descripcion": limpiar_texto(descripcion),
                            "valorUnitario": valor_unitario
                        })
                        print(f"    Linea (alt): cant={cantidad}, valor={valor_unitario}")
                        break
        
        if not lista_lineas:
            validaciones.append("SECCION 3: No se encontraron lineas de factura")
        
        # =====================================================================
        # SECCIÓN 4: TOTALES
        # =====================================================================
        print("\n[SECCION 4] Procesando TOTALES...")
        
        # Extraer cada monto usando función inteligente
        venta_gratuita = extraer_monto_inteligente(texto_completo, r"Gratuitas")
        print(f"    Venta Gratuita: {venta_gratuita}")
        
        subtotal_venta = extraer_monto_inteligente(texto_completo, r"Sub\s*Total\s*Ventas?")
        print(f"    Subtotal Venta: {subtotal_venta}")
        
        anticipo = extraer_monto_inteligente(texto_completo, r"Anticipos?")
        print(f"    Anticipo: {anticipo}")
        
        descuento = extraer_monto_inteligente(texto_completo, r"Descuentos?")
        print(f"    Descuento: {descuento}")
        
        valor_venta = extraer_monto_inteligente(texto_completo, r"Valor\s*Venta")
        print(f"    Valor Venta: {valor_venta}")
        
        isc = extraer_monto_inteligente(texto_completo, r"ISC(?:\s|$)")
        print(f"    ISC: {isc}")
        
        igv = extraer_monto_inteligente(texto_completo, r"IGV")
        print(f"    IGV: {igv}")
        
        otros_cargos = extraer_monto_inteligente(texto_completo, r"Otros?\s*Cargos?")
        print(f"    Otros Cargos: {otros_cargos}")
        
        otros_tributos = extraer_monto_inteligente(texto_completo, r"Otros?\s*Tributos?")
        print(f"    Otros Tributos: {otros_tributos}")
        
        monto_redondeo = extraer_monto_inteligente(texto_completo, r"[Rr]edondeo")
        print(f"    Monto Redondeo: {monto_redondeo}")
        
        importe_total = extraer_monto_inteligente(texto_completo, r"Importe\s*Total")
        print(f"    Importe Total: {importe_total}")
        
        # VALIDACIÓN CRUZADA: subtotal debe ser coherente con importe_total
        # Si subtotal > importe_total * 5, probablemente hay error OCR
        if subtotal_venta > importe_total * 5 and importe_total > 0:
            # Intentar corregir: quitar primer dígito si es duplicado
            subtotal_str = str(int(subtotal_venta))
            if len(subtotal_str) > 4 and subtotal_str[0] == subtotal_str[1]:
                subtotal_corregido = float(subtotal_str[1:])
                print(f"    [CORRECCION] Subtotal {subtotal_venta} -> {subtotal_corregido}")
                subtotal_venta = subtotal_corregido
        
        # Descripción importe total (SON: ...)
        descripcion_importe = ""
        match_son = re.search(r'SON:\s*(.+?)(?:SOLES|$)', texto_completo, re.IGNORECASE)
        if match_son:
            descripcion_importe = limpiar_texto(match_son.group(1))
            if not descripcion_importe.endswith('SOLES'):
                descripcion_importe += " SOLES"
            print(f"    Descripcion: {descripcion_importe}")
        
        # =====================================================================
        # SECCIÓN 5: CUOTAS
        # =====================================================================
        print("\n[SECCION 5] Procesando CUOTAS...")
        
        monto_pendiente = extraer_monto_inteligente(texto_completo, r"pendiente de pago")
        print(f"    Monto Pendiente: {monto_pendiente}")
        
        # Total de cuotas
        total_cuotas = 0
        match_total = re.search(r'Total de Cuotas\s*:?\s*(\d+)', texto_completo, re.IGNORECASE)
        if match_total:
            total_cuotas = int(match_total.group(1))
        
        # Extraer cuotas
        lista_cuotas = []
        
        # Buscar línea con patrón de cuotas: fecha monto fecha monto...
        for linea in lineas:
            # Patrón: DD/MM/YYYY seguido de monto
            patron = r'(\d{2}/\d{2}/\d{4})\s+([\d.,]+)'
            matches = re.findall(patron, linea)
            
            if len(matches) >= 2:  # Al menos 2 cuotas en la línea
                for idx, (fecha, monto_str) in enumerate(matches, 1):
                    monto = limpiar_moneda(monto_str)
                    
                    lista_cuotas.append({
                        "numero": idx,
                        "fechaVencimiento": fecha,
                        "monto": monto
                    })
                    print(f"    Cuota {idx}: {fecha} - {monto}")
                break
        
        # VALIDACIÓN DE CUOTAS
        # Si hay cuotas y la primera es muy pequeña comparada con las otras, posible error
        if len(lista_cuotas) >= 2:
            primera = lista_cuotas[0]['monto']
            segunda = lista_cuotas[1]['monto']
            
            # Si primera < 500 y segunda > 2000, probable error OCR (se comió dígitos)
            if primera < 500 and segunda > 2000:
                validaciones.append(f"SECCION 5: Cuota 1 monto sospechoso ({primera}), puede faltar digitos")
        
        # VALIDACIÓN CRUZADA: suma de cuotas debe aproximarse a monto pendiente
        if lista_cuotas and monto_pendiente > 0:
            suma_cuotas = sum(c['monto'] for c in lista_cuotas)
            diferencia = abs(suma_cuotas - monto_pendiente)
            
            # Si la diferencia es mayor al 20%, hay error
            if diferencia > monto_pendiente * 0.2:
                validaciones.append(f"SECCION 5: Suma cuotas ({suma_cuotas:.2f}) no coincide con pendiente ({monto_pendiente:.2f})")
        
        if total_cuotas == 0:
            total_cuotas = len(lista_cuotas)
        
        print(f"    Total Cuotas: {total_cuotas}")
        
        # =====================================================================
        # VALIDACIONES FINALES CRUZADAS
        # =====================================================================
        print("\n[VALIDACIONES] Verificando coherencia...")
        
        # Validar: IGV debe ser ~18% de valor_venta (tolerancia 5%)
        if valor_venta > 0 and igv > 0:
            igv_esperado = valor_venta * 0.18
            diferencia_igv = abs(igv - igv_esperado)
            if diferencia_igv > igv_esperado * 0.05:
                validaciones.append(f"IGV ({igv}) no coincide con 18% de valor venta ({igv_esperado:.2f})")
        
        # Validar: importe_total debe ser aproximadamente valor_venta + igv
        if valor_venta > 0 and igv > 0 and importe_total > 0:
            total_esperado = valor_venta + igv
            diferencia_total = abs(importe_total - total_esperado)
            if diferencia_total > total_esperado * 0.05:
                validaciones.append(f"Importe total ({importe_total}) no coincide con valor+IGV ({total_esperado:.2f})")
        
        # =====================================================================
        # CONSTRUIR JSON FINAL
        # =====================================================================
        print("\n[RESULTADO] Construyendo JSON...")
        
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
                "direccionReceptorFactura": direccion_receptor,
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
            "validacion": validaciones
        }
        
    except Exception as e:
        import traceback
        return {
            "validacion": [
                f"Error procesando imagen: {str(e)}",
                traceback.format_exc()
            ]
        }
