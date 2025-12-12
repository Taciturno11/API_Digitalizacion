"""
PROCESADOR PDF v2 - FACTURA ELECTRÓNICA SUNAT
Basado en la estructura oficial de la representación impresa.

ESTRUCTURA POR SECCIONES:
=========================
SECCIÓN 1 - CABECERA (EMISOR):
  - Línea 0: "FACTURA ELECTRONICA" (ignorar)
  - Línea 1: razonSocialEmisor (siempre 1 línea)
  - Línea 2: "RUC: XXXXXXXXXXX" 
  - Línea 3: direccionEmisor (siempre 1 línea)
  - Línea 4: numeroFactura (E001-XXX o F001-XXX)
  - Línea 5: distrito - provincia - departamento (formato XXX-XXX-XXX)

SECCIÓN 2 - RECEPTOR Y OPERACIÓN:
  - fechaEmision: 1 línea (contiene fecha)
  - formaPago: en la misma línea que fecha (lado derecho)
  - razonSocialReceptor: 1, 2 o 3 líneas (termina cuando aparece RUC 11 dígitos)
  - rucReceptor: 1 línea (11 dígitos: 20XXXXXXXXX)
  - direccionReceptor: empieza con AV./CAL./JR., puede ser varias líneas
  - direccionCliente: mismo patrón
  - tipoMoneda: 1 línea
  - observacion: 1, 2 o 3 líneas

SECCIÓN 3 - LÍNEAS DE FACTURA:
  - cantidad, unidadMedida, descripcion (1-3 líneas), valorUnitario

SECCIÓN 4 - TOTALES:
  - Todos campos de 1 línea con formato "etiqueta : S/ X,XXX.XX"
"""

import pdfplumber
import re
import os
from catalogos_sunat import convertir_unidad_medida, convertir_moneda

# =============================================================================
# FUNCIONES DE UTILIDAD
# =============================================================================

def limpiar_moneda(valor):
    """Convierte string de moneda a float: 'S/ 4,500.00' -> 4500.00"""
    if not valor:
        return 0.00
    valor = str(valor).replace('S/', '').replace('$', '').replace(',', '').strip()
    try:
        return float(valor)
    except:
        return 0.00

def normalizar_texto_espaciado(texto):
    """
    Corrige texto con letras individuales separadas por espacios.
    Ejemplo: "GAMB O A" -> "GAMBOA", "S A C" -> "SAC", "M A R I A" -> "MARIA"
    
    Estrategia:
    1. Primero, unir todas las secuencias de letras individuales consecutivas
    2. Luego, si una palabra termina y le siguen pocas letras (1-2), unirlas
    """
    if not texto:
        return texto
    
    palabras = texto.split()
    if not palabras:
        return texto
    
    # Paso 1: Identificar y marcar grupos de letras individuales
    grupos = []
    i = 0
    while i < len(palabras):
        palabra = palabras[i]
        
        if len(palabra) == 1 and palabra.isalpha():
            # Inicio de secuencia de letras individuales
            letras = [palabra]
            j = i + 1
            while j < len(palabras) and len(palabras[j]) == 1 and palabras[j].isalpha():
                letras.append(palabras[j])
                j += 1
            grupos.append(('letras', ''.join(letras)))
            i = j
        else:
            grupos.append(('palabra', palabra))
            i += 1
    
    # Paso 2: Unir grupos inteligentemente
    resultado = []
    i = 0
    while i < len(grupos):
        tipo, valor = grupos[i]
        
        if tipo == 'palabra':
            # Verificar si el siguiente grupo son pocas letras (1-2) que deberían unirse
            if i + 1 < len(grupos) and grupos[i + 1][0] == 'letras':
                siguiente_letras = grupos[i + 1][1]
                if len(siguiente_letras) <= 2:
                    # Pocas letras después de palabra = probablemente parte de la palabra
                    # Ej: "GAMB" + "OA" = "GAMBOA"
                    resultado.append(valor + siguiente_letras)
                    i += 2
                    continue
            resultado.append(valor)
        else:
            # Es un grupo de letras - agregarlo como palabra
            resultado.append(valor)
        i += 1
    
    return ' '.join(resultado)

def extraer_geo_de_linea(linea):
    """
    Extrae distrito, provincia, departamento de una línea con formato:
    "XXX - XXX - XXX" o "XXX-XXX-XXX"
    Retorna: (distrito, provincia, departamento)
    """
    # Normalizar separadores
    partes = re.split(r'\s*-\s*', linea.strip())
    if len(partes) >= 3:
        return partes[0].strip(), partes[1].strip(), partes[2].strip()
    return "", "", ""

def buscar_monto(texto, etiqueta):
    """Busca un monto con formato 'etiqueta : S/ X,XXX.XX'"""
    patron = re.compile(etiqueta + r'\s*:\s*S/\s*([\d,]+\.\d{2})', re.IGNORECASE)
    match = patron.search(texto)
    return limpiar_moneda(match.group(1)) if match else 0.00

# =============================================================================
# PROCESADOR PRINCIPAL
# =============================================================================

def procesar_factura_pdf(ruta_archivo):
    """
    Procesa un PDF de Factura Electrónica SUNAT y extrae todos los campos.
    """
    if not os.path.exists(ruta_archivo):
        return {"validacion": ["El archivo no existe"]}

    try:
        with pdfplumber.open(ruta_archivo) as pdf:
            texto_completo = pdf.pages[0].extract_text()
            lineas = texto_completo.split('\n')
            
            # Extraer anotaciones del PDF AQUÍ, mientras está abierto
            pdf_anotaciones = []
            page = pdf.pages[0]
            if hasattr(page, 'annots') and page.annots:
                for annot in page.annots:
                    if annot.get('contents'):
                        pdf_anotaciones.append(str(annot['contents']).strip())
        
        # =====================================================================
        # SECCIÓN 1: CABECERA (EMISOR)
        # =====================================================================
        # Línea 0: "FACTURA ELECTRONICA" - ignoramos
        # Línea 1: razonSocialEmisor
        # Línea 2: RUC: XXXXXXXXXXX
        # Línea 3: direccionEmisor
        # Línea 4: numeroFactura (E001-XXX)
        # Línea 5: distrito - provincia - departamento
        
        razon_social_emisor = lineas[1].strip() if len(lineas) > 1 else ""
        razon_social_emisor = normalizar_texto_espaciado(razon_social_emisor)
        
        # RUC Emisor (buscar en línea 2 o cercanas)
        ruc_emisor = 0
        for i in range(min(5, len(lineas))):
            match = re.search(r'RUC\s*:\s*(\d{11})', lineas[i])
            if match:
                ruc_emisor = int(match.group(1))
                break
        
        direccion_emisor = lineas[3].strip() if len(lineas) > 3 else ""
        
        # Número de Factura (buscar E001-XXX o F001-XXX)
        numero_factura = ""
        for i in range(min(6, len(lineas))):
            match = re.search(r'([EF]\d{3}-\d+)', lineas[i])
            if match:
                numero_factura = match.group(1)
                break
        
        # Geolocalización (línea 5: distrito - provincia - departamento)
        distrito, provincia, departamento = "", "", ""
        if len(lineas) > 5:
            distrito, provincia, departamento = extraer_geo_de_linea(lineas[5])
        
        # =====================================================================
        # SECCIÓN 2: RECEPTOR Y OPERACIÓN
        # =====================================================================
        
        # Fecha de Emisión y Forma de Pago (están en la misma línea generalmente)
        fecha_emision = ""
        forma_pago = "Contado"
        
        for linea in lineas[6:15]:
            # Buscar fecha
            match_fecha = re.search(r'(\d{2}/\d{2}/\d{4})', linea)
            if match_fecha:
                fecha_emision = match_fecha.group(1)
            # Buscar forma de pago
            if 'Crédito' in linea or 'Credito' in linea:
                forma_pago = "Crédito"
            elif 'Contado' in linea:
                forma_pago = "Contado"
        
        # -----------------------------------------------------------------
        # RAZÓN SOCIAL RECEPTOR
        # Estrategia: Capturar todo desde después de la línea de fecha
        # hasta encontrar la línea con RUC de 11 dígitos
        # El RUC receptor puede empezar con 10 (persona natural) o 20 (empresa)
        # Pero debe estar DESPUÉS de la línea "Señor(es)" para no confundir con emisor
        # -----------------------------------------------------------------
        razon_social_receptor = ""
        ruc_receptor = 0
        idx_ruc_receptor = -1
        idx_senor = -1
        
        # Primero encontrar la línea "Señor(es)"
        for i, linea in enumerate(lineas):
            if 'Se' in linea and 'or' in linea and '(' in linea:  # Señor(es) o Sefior(es)
                idx_senor = i
                break
        
        # Buscar RUC receptor DESPUÉS de "Señor(es)" (para no confundir con emisor)
        if idx_senor > 0:
            for i in range(idx_senor, min(idx_senor + 10, len(lineas))):
                # Buscar RUC que NO sea el del emisor
                match = re.search(r'RUC\s*:\s*(\d{11})', lineas[i])
                if match:
                    ruc_encontrado = int(match.group(1))
                    # Verificar que no sea el RUC emisor
                    if ruc_encontrado != ruc_emisor:
                        ruc_receptor = ruc_encontrado
                        idx_ruc_receptor = i
                        break
        
        # Ahora capturar razón social (entre fecha y RUC receptor)
        if idx_ruc_receptor > 0:
            # Buscar inicio (después de la línea de fecha)
            idx_inicio = -1
            for i in range(6, idx_ruc_receptor):
                if re.search(r'\d{2}/\d{2}/\d{4}', lineas[i]):
                    idx_inicio = i + 1
                    break
            
            if idx_inicio > 0 and idx_inicio < idx_ruc_receptor:
                # Capturar todas las líneas entre fecha y RUC
                partes_nombre = []
                for i in range(idx_inicio, idx_ruc_receptor):
                    linea = lineas[i].strip()
                    # Limpiar etiquetas como "Señor(es) :"
                    linea = re.sub(r'Se.or\(es\)\s*:', '', linea).strip()
                    if linea and not re.match(r'^\s*$', linea):
                        partes_nombre.append(linea)
                razon_social_receptor = ' '.join(partes_nombre)
        
        # -----------------------------------------------------------------
        # DIRECCIÓN RECEPTOR Y CLIENTE
        # Estrategia basada en la estructura real del PDF:
        # - direccionReceptorFactura: desde después del RUC receptor hasta 
        #   "Dirección del Receptor de la factura : XXX-XXX-XXX" (incluye el patrón)
        # - direccionCliente: desde después de esa línea hasta "Tipo de Moneda"
        # -----------------------------------------------------------------
        direccion_receptor = ""
        direccion_cliente = ""
        
        # Encontrar índices clave
        idx_ruc_receptor_linea = -1
        idx_dir_receptor_label = -1
        idx_dir_cliente_label = -1
        idx_tipo_moneda = -1
        
        for i, linea in enumerate(lineas):
            # Línea del RUC receptor (ya la tenemos de antes)
            if idx_ruc_receptor > 0 and i == idx_ruc_receptor:
                idx_ruc_receptor_linea = i
            # Línea "Dirección del Receptor de la factura : XXX-XXX-XXX"
            if 'Direcci' in linea and 'Receptor' in linea and 'factura' in linea:
                idx_dir_receptor_label = i
            # Línea "Dirección del Cliente :"
            if 'Direcci' in linea and 'Cliente' in linea:
                idx_dir_cliente_label = i
            # Línea "Tipo de Moneda"
            if 'Tipo de Moneda' in linea:
                idx_tipo_moneda = i
                break
        
        # DIRECCIÓN RECEPTOR: desde RUC+1 hasta la línea con "Dirección del Receptor" (inclusive el patrón XXX-XXX-XXX)
        if idx_ruc_receptor > 0 and idx_dir_receptor_label > idx_ruc_receptor:
            partes_dir = []
            for i in range(idx_ruc_receptor + 1, idx_dir_receptor_label + 1):
                linea = lineas[i].strip()
                # Extraer el patrón XXX-XXX-XXX de la línea "Dirección del Receptor de la factura :"
                if 'Direcci' in linea and 'Receptor' in linea:
                    match_patron = re.search(r':\s*([A-Z]+-[A-Z]+-[A-Z]+)', linea)
                    if match_patron:
                        partes_dir.append(match_patron.group(1))
                else:
                    if linea:
                        partes_dir.append(linea)
            direccion_receptor = ' '.join(partes_dir)
        
        # DIRECCIÓN CLIENTE: Buscar desde la etiqueta "Dirección del Cliente" hacia atrás
        # hasta encontrar una línea que empiece con AV./CAL./JR.
        # Y luego incluir todo hasta "Tipo de Moneda"
        if idx_dir_cliente_label > 0 and idx_tipo_moneda > idx_dir_cliente_label:
            partes_dir = []
            
            # Primero, buscar hacia atrás desde "Dirección del Cliente" para encontrar
            # la línea que empieza con AV./CAL./JR. (esa es el inicio real)
            idx_inicio_cliente = idx_dir_cliente_label
            for i in range(idx_dir_cliente_label - 1, idx_dir_receptor_label, -1):
                linea = lineas[i].strip()
                if re.match(r'^(AV|CAL|JR)\.?\s', linea, re.IGNORECASE):
                    idx_inicio_cliente = i
                    break
            
            # Ahora capturar desde idx_inicio_cliente hasta idx_tipo_moneda
            for i in range(idx_inicio_cliente, idx_tipo_moneda):
                linea = lineas[i].strip()
                
                # Limpiar etiqueta "Dirección del Cliente :" si existe
                if 'Direcci' in linea and 'Cliente' in linea:
                    match_inline = re.search(r'Cliente\s*:\s*(.+)', linea)
                    if match_inline:
                        partes_dir.append(match_inline.group(1).strip())
                else:
                    if linea:
                        partes_dir.append(linea)
            
            direccion_cliente = ' '.join(partes_dir)
            
            # También ajustar direccionReceptorFactura para que termine ANTES de donde empieza direccionCliente
            if idx_inicio_cliente < idx_dir_cliente_label:
                partes_dir_receptor = []
                for i in range(idx_ruc_receptor + 1, idx_inicio_cliente):
                    linea = lineas[i].strip()
                    if 'Direcci' in linea and 'Receptor' in linea:
                        match_patron = re.search(r':\s*(.+)', linea)
                        if match_patron:
                            partes_dir_receptor.append(match_patron.group(1).strip())
                    else:
                        if linea:
                            partes_dir_receptor.append(linea)
                direccion_receptor = ' '.join(partes_dir_receptor)
        
        # -----------------------------------------------------------------
        # TIPO DE MONEDA
        # -----------------------------------------------------------------
        tipo_moneda = "SOLES"
        for linea in lineas:
            match = re.search(r'Tipo de Moneda\s*:\s*(\w+)', linea)
            if match:
                moneda_raw = match.group(1).strip()
                # Normalizar
                if 'DOLAR' in moneda_raw.upper():
                    tipo_moneda = "DOLARES"
                elif 'SOL' in moneda_raw.upper():
                    tipo_moneda = "SOLES"
                else:
                    tipo_moneda = moneda_raw
                break
        
        # -----------------------------------------------------------------
        # OBSERVACIÓN
        # Estrategia: Todo entre "Tipo de Moneda" y la tabla de items
        # -----------------------------------------------------------------
        observacion = ""
        idx_moneda = -1
        idx_items = -1
        
        for i, linea in enumerate(lineas):
            if 'Tipo de Moneda' in linea:
                idx_moneda = i
            if 'Cantidad' in linea and 'Unidad' in linea and 'Descripci' in linea:
                idx_items = i
                break
        
        if idx_moneda > 0 and idx_items > idx_moneda:
            partes_obs = []
            for i in range(idx_moneda + 1, idx_items):
                linea = lineas[i].strip()
                # Limpiar etiqueta "Observación :"
                linea = re.sub(r'Observaci.n\s*:', '', linea).strip()
                if linea:
                    partes_obs.append(linea)
            observacion = ' '.join(partes_obs)
        
        # =====================================================================
        # SECCIÓN 3: LÍNEAS DE FACTURA
        # =====================================================================
        lista_lineas = []
        
        # Buscar línea que tiene: cantidad UNIDAD descripcion valor
        for i, linea in enumerate(lineas):
            # Patrón: 5.00 UNIDAD descripcion... 6200.00
            match = re.match(r'(\d+\.\d{2})\s+(\w+)\s+(.+?)\s+(\d+(?:,\d{3})*\.\d{2})$', linea.strip())
            if match:
                cantidad = float(match.group(1))
                unidad_raw = match.group(2)
                descripcion_parte1 = match.group(3).strip()
                valor_unitario = limpiar_moneda(match.group(4))
                
                # Verificar si hay continuación en la siguiente línea
                descripcion_completa = descripcion_parte1
                if i + 1 < len(lineas):
                    siguiente = lineas[i + 1].strip()
                    # Si la siguiente NO empieza con número ni con palabras de totales
                    if (siguiente 
                        and not re.match(r'^(\d|Valor|Sub|SON|ISC|IGV|Importe|Operaciones|Anticipos)', siguiente, re.IGNORECASE)
                        and not re.match(r'^\d+\.\d{2}\s+\w+', siguiente)):
                        descripcion_completa = f"{descripcion_parte1} {siguiente}"
                
                lista_lineas.append({
                    "cantidad": cantidad,
                    "unidadMedida": convertir_unidad_medida(unidad_raw),
                    "descripcion": descripcion_completa,
                    "valorUnitario": valor_unitario
                })
        
        # =====================================================================
        # SECCIÓN 4: TOTALES
        # =====================================================================
        venta_gratuita = buscar_monto(texto_completo, "Operaciones Gratuitas")
        subtotal_venta = buscar_monto(texto_completo, "Sub Total Ventas")
        anticipo = buscar_monto(texto_completo, "Anticipos")
        descuento = buscar_monto(texto_completo, "Descuentos")
        valor_venta = buscar_monto(texto_completo, "Valor Venta")
        isc = buscar_monto(texto_completo, "ISC")
        igv = buscar_monto(texto_completo, "IGV")
        otros_cargos = buscar_monto(texto_completo, "Otros Cargos")
        otros_tributos = buscar_monto(texto_completo, "Otros Tributos")
        monto_redondeo = buscar_monto(texto_completo, "Monto de redondeo")
        importe_total = buscar_monto(texto_completo, "Importe Total")
        monto_pendiente = buscar_monto(texto_completo, "pendiente de pago")
        
        # Descripción importe total (SON: ...)
        descripcion_importe = ""
        match_son = re.search(r'SON:\s*(.+?)\s*(?:ISC|SOLES|$)', texto_completo, re.IGNORECASE)
        if match_son:
            descripcion_importe = match_son.group(1).strip()
            # Agregar "SOLES" si no lo tiene
            if not descripcion_importe.endswith('SOLES'):
                descripcion_importe += " SOLES"
        
        # =====================================================================
        # SECCIÓN 5: CUOTAS
        # =====================================================================
        # Formato: N° Cuota Fec. Venc. Monto (repetido horizontalmente)
        # Ejemplo: 1 01/12/2025 2,100.00 2 28/12/2025 2,657.76 3 30/12/2025 2,625.00
        # También puede ser: fecha monto fecha monto fecha monto (sin número de cuota)
        # IMPORTANTE: Algunas cuotas pueden estar como anotaciones del PDF (no texto)
        lista_cuotas = []
        
        # Método 1: Buscar cuotas en el texto normal
        for linea in lineas:
            # Formato 1: número fecha monto (repetido)
            cuotas_matches = re.findall(r'(\d+)\s+(\d{2}/\d{2}/\d{4})\s+([\d,]+\.\d{2})', linea)
            if cuotas_matches:
                for match in cuotas_matches:
                    num_cuota = int(match[0])
                    # Validar que el número de cuota sea razonable (1-20)
                    if 1 <= num_cuota <= 20:
                        lista_cuotas.append({
                            "numero": num_cuota,
                            "fechaVencimiento": match[1],
                            "monto": limpiar_moneda(match[2])
                        })
            else:
                # Formato 2: fecha monto (sin número de cuota explícito)
                # Ejemplo: 01/12/2025 2,100.00 28/12/2025 2,657.76 31/12/2025 2,500.00
                cuotas_sin_num = re.findall(r'(\d{2}/\d{2}/\d{4})\s+([\d,]+\.\d{2})', linea)
                if cuotas_sin_num and len(cuotas_sin_num) >= 2:  # Al menos 2 cuotas en la línea
                    for idx, match in enumerate(cuotas_sin_num):
                        lista_cuotas.append({
                            "numero": idx + 1,
                            "fechaVencimiento": match[0],
                            "monto": limpiar_moneda(match[1])
                        })
        
        # Método 2: Buscar cuotas en las ANOTACIONES del PDF
        # (algunas cuotas pueden estar como anotaciones FreeText agregadas manualmente)
        # Usamos pdf_anotaciones que ya extrajimos mientras el PDF estaba abierto
        if pdf_anotaciones:
            numeros_cuota = []
            fechas_cuota = []
            montos_cuota = []
            
            for texto in pdf_anotaciones:
                # Es un número de cuota? (1-20)
                if re.match(r'^\d{1,2}$', texto):
                    num = int(texto)
                    if 1 <= num <= 20:
                        numeros_cuota.append(num)
                # Es una fecha?
                elif re.match(r'^\d{2}/\d{2}/\d{4}$', texto):
                    fechas_cuota.append(texto)
                # Es un monto?
                elif re.match(r'^[\d,]+\.\d{2}$', texto):
                    montos_cuota.append(limpiar_moneda(texto))
            
            # Si encontramos datos de cuotas en anotaciones, agregarlas
            if numeros_cuota and fechas_cuota and montos_cuota:
                for i, num in enumerate(numeros_cuota):
                    if i < len(fechas_cuota) and i < len(montos_cuota):
                        # Verificar si esta cuota ya existe
                        existe = any(c['numero'] == num for c in lista_cuotas)
                        if not existe:
                            lista_cuotas.append({
                                "numero": num,
                                "fechaVencimiento": fechas_cuota[i],
                                "monto": montos_cuota[i]
                            })
        
        # Eliminar duplicados por número de cuota (mantener el primero)
        cuotas_unicas = {}
        for cuota in lista_cuotas:
            if cuota['numero'] not in cuotas_unicas:
                cuotas_unicas[cuota['numero']] = cuota
        lista_cuotas = list(cuotas_unicas.values())
        lista_cuotas.sort(key=lambda x: x['numero'])
        
        # Leer "Total de Cuotas" del texto
        total_cuotas_texto = len(lista_cuotas)  # Por defecto usar la cantidad encontrada
        match_total_cuotas = re.search(r'Total de Cuotas\s*:?\s*(\d+)', texto_completo)
        if match_total_cuotas:
            total_cuotas_texto = int(match_total_cuotas.group(1))
        if match_total_cuotas:
            total_cuotas_texto = int(match_total_cuotas.group(1))
        
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
                "totalCuota": total_cuotas_texto,
                "cuotas": lista_cuotas
            },
            "validacion": []
        }

    except Exception as e:
        return {"validacion": [f"Error procesando PDF: {str(e)}"]}
