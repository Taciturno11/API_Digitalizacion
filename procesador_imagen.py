# -*- coding: utf-8 -*-
"""
PROCESADOR DE IMAGEN PARA FACTURAS ELECTRÓNICAS SUNAT
Versión 10: Usando docTR OCR - Estructura JSON idéntica al PDF
"""

import re
import warnings
warnings.filterwarnings('ignore')

from doctr.io import DocumentFile
from doctr.models import ocr_predictor


# Cargar modelo docTR (singleton)
print("[OCR] Cargando modelo docTR...")
_modelo_doctr = None


def obtener_modelo_doctr():
    """Obtiene el modelo docTR (singleton para no cargar múltiples veces)."""
    global _modelo_doctr
    if _modelo_doctr is None:
        _modelo_doctr = ocr_predictor(pretrained=True)
    return _modelo_doctr


def extraer_texto_doctr(imagen_path):
    """Extrae texto usando docTR."""
    model = obtener_modelo_doctr()
    doc = DocumentFile.from_images(imagen_path)
    result = model(doc)
    
    lineas = []
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                texto_linea = ' '.join([word.value for word in line.words])
                lineas.append(texto_linea)
    
    return '\n'.join(lineas)


def limpiar_numero(texto):
    """Limpia un texto para extraer un número decimal."""
    if not texto:
        return 0.0
    texto = str(texto).strip()
    texto = re.sub(r'S/?\.?', '', texto)
    texto = re.sub(r'SI\s*', '', texto)
    texto = texto.replace('$', '').replace('€', '').replace(' ', '').replace(',', '')
    match = re.search(r'(\d+\.?\d*)', texto)
    return float(match.group(1)) if match else 0.0


def extraer_ruc(texto):
    """Extrae todos los RUCs de 11 dígitos."""
    rucs = re.findall(r'\b(\d{11})\b', texto)
    return [r for r in rucs if r.startswith(('10', '20'))]


def procesar_factura_img(imagen_path: str) -> dict:
    """
    Procesa una imagen de factura SUNAT y devuelve JSON con estructura IDÉNTICA al PDF.
    """
    print("[OCR] Extrayendo texto con docTR...")
    
    texto_raw = extraer_texto_doctr(imagen_path)
    lineas = texto_raw.split('\n')
    texto = texto_raw.replace('\n', ' ').replace('  ', ' ')
    
    print("=" * 70)
    print("TEXTO EXTRAIDO POR docTR:")
    print("=" * 70)
    print(texto_raw[:2000])
    print("=" * 70)
    
    # ==================== EXTRACCIÓN DE DATOS ====================
    
    # --- RUCs ---
    rucs = extraer_ruc(texto)
    print(f"\n[INFO] RUCs encontrados: {rucs}")
    
    ruc_emisor = 0
    ruc_receptor = 0
    for ruc in rucs:
        if ruc.startswith('10') and ruc_emisor == 0:
            ruc_emisor = int(ruc)
        elif ruc.startswith('20') and ruc_receptor == 0:
            ruc_receptor = int(ruc)
    
    if ruc_emisor == 0 and rucs:
        ruc_emisor = int(rucs[0])
        if len(rucs) > 1:
            ruc_receptor = int(rucs[1])
    
    # --- NÚMERO DE FACTURA ---
    numero_factura = ""
    match = re.search(r'([EFB]\d{3}[-\s]?\d+)', texto, re.IGNORECASE)
    if match:
        numero_factura = match.group(1).replace(' ', '')
    
    # --- FECHA DE EMISIÓN ---
    fecha_emision = ""
    for patron in [r'Fecha\s*(?:de\s*)?Emisi[oó]n[:\s]*(\d{2}/\d{2}/\d{4})', r'Emisi[oó]n[:\s]*(\d{2}/\d{2}/\d{4})']:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            fecha_emision = match.group(1)
            break
    
    # --- RAZÓN SOCIAL EMISOR ---
    razon_social_emisor = ""
    match = re.search(r'(?:ELECTRONICA|ELECTR[OÓ]NICA)\s+(.+?)\s+(?:RUC|CAL|AV)', texto, re.IGNORECASE)
    if match:
        razon_social_emisor = re.sub(r'\s+', ' ', match.group(1).strip())
    
    # --- DIRECCIÓN EMISOR ---
    direccion_emisor = ""
    match = re.search(r'RUC:\s*\d{11}\s+(.+?)(?:E\d{3}|F\d{3}|B\d{3})', texto, re.IGNORECASE)
    if match:
        direccion_emisor = match.group(1).strip()
    
    # --- UBIGEO (departamento, provincia, distrito) ---
    departamento = "LIMA"
    provincia = "LIMA"
    distrito = ""
    match = re.search(r'([A-Za-záéíóúñÑ\s]+)[-\s]*-\s*LIMA\s*-\s*LIMA', texto, re.IGNORECASE)
    if match:
        distrito = match.group(1).strip().replace('-', '').strip()
        # Capitalizar primera letra
        if distrito:
            distrito = distrito.title()
    
    # --- RAZÓN SOCIAL RECEPTOR ---
    razon_social_receptor = ""
    for i, linea in enumerate(lineas):
        if re.search(r'se[ñn]or\(?es?\)?', linea, re.IGNORECASE):
            partes = []
            if i > 0:
                nombre_comercial = lineas[i-1].strip()
                if nombre_comercial and not re.match(r'^(Forma|Fecha|RUC|AV\.|CAL\.|JR\.)', nombre_comercial, re.IGNORECASE):
                    partes.append(nombre_comercial)
            if i + 1 < len(lineas):
                razon_formal = lineas[i+1].strip()
                if razon_formal and not re.match(r'^(RUC|AV\.|CAL\.|JR\.|\d)', razon_formal, re.IGNORECASE):
                    partes.append(razon_formal)
            if partes:
                razon_social_receptor = ' '.join(partes)
            break
    
    # --- DIRECCIONES RECEPTOR Y CLIENTE ---
    # Las direcciones siempre empiezan con AV., CAL., JR., etc. y terminan con patrón xxx-xxx-xxx
    direccion_receptor_factura = ""
    direccion_cliente = ""
    
    # Buscar índices de líneas clave
    idx_dir_receptor = -1
    idx_dir_cliente = -1
    idx_tipo_moneda = -1
    
    for i, linea in enumerate(lineas):
        linea_lower = linea.lower()
        if 'direcci' in linea_lower and 'receptor' in linea_lower:
            idx_dir_receptor = i
        elif 'direcci' in linea_lower and 'cliente' in linea_lower:
            idx_dir_cliente = i
        elif 'tipo de moneda' in linea_lower:
            idx_tipo_moneda = i
            break
    
    print(f"[DEBUG] idx_dir_receptor={idx_dir_receptor}, idx_dir_cliente={idx_dir_cliente}, idx_tipo_moneda={idx_tipo_moneda}")
    
    # Buscar dirección fiscal (después de RUC receptor hasta "Dirección del Receptor")
    if idx_dir_receptor > 0:
        partes_receptor = []
        # Buscar hacia atrás desde "Dirección del Receptor" hasta encontrar RUC o AV./CAL./JR.
        for i in range(idx_dir_receptor - 1, -1, -1):
            linea = lineas[i].strip()
            if re.match(r'^RUC', linea, re.IGNORECASE) or re.match(r'^[-\s]*\d{11}', linea):
                break
            if linea and not re.match(r'^(Senor|SOCIEDAD|EXACTA|Forma)', linea, re.IGNORECASE):
                partes_receptor.insert(0, linea)
        
        # Agregar contenido de la línea "Dirección del Receptor" (después de ":")
        linea_receptor = lineas[idx_dir_receptor]
        if ':' in linea_receptor:
            parte_despues = linea_receptor.split(':', 1)[1].strip()
            if parte_despues:
                partes_receptor.append(parte_despues)
        
        # Agregar líneas después hasta "AV." o "Dirección del Cliente"
        for i in range(idx_dir_receptor + 1, len(lineas)):
            linea = lineas[i].strip()
            if re.match(r'^(AV\.|CAL\.|JR\.)', linea, re.IGNORECASE):
                break
            if 'direcci' in linea.lower() and 'cliente' in linea.lower():
                break
            if linea:
                partes_receptor.append(linea)
        
        direccion_receptor_factura = ' '.join(partes_receptor)
    
    # Dirección del Cliente: desde línea anterior a "Dirección del Cliente" (si es AV./CAL./JR.)
    # hasta "Tipo de Moneda"
    if idx_dir_cliente > 0 and idx_tipo_moneda > idx_dir_cliente:
        partes_cliente = []
        
        # Verificar si hay líneas con AV./CAL./JR. ANTES de "Dirección del Cliente"
        # que pertenecen a la dirección del cliente
        for i in range(idx_dir_cliente - 1, idx_dir_receptor, -1):
            linea = lineas[i].strip()
            if re.match(r'^(AV\.|CAL\.|JR\.)', linea, re.IGNORECASE):
                # Capturar desde esta línea hasta idx_dir_cliente
                for j in range(i, idx_dir_cliente):
                    if lineas[j].strip():
                        partes_cliente.append(lineas[j].strip())
                break
        
        # Agregar líneas después de "Dirección del Cliente" hasta "Tipo de Moneda"
        for i in range(idx_dir_cliente + 1, idx_tipo_moneda):
            linea = lineas[i].strip()
            if linea:
                partes_cliente.append(linea)
        
        direccion_cliente = ' '.join(partes_cliente)
    
    print(f"[DEBUG] direccion_receptor_factura: {direccion_receptor_factura}")
    print(f"[DEBUG] direccion_cliente: {direccion_cliente}")
    
    # --- TIPO DE MONEDA ---
    tipo_moneda = "SOLES"
    for i, linea in enumerate(lineas):
        if 'tipo de moneda' in linea.lower():
            if i + 1 < len(lineas):
                moneda = lineas[i+1].strip().upper()
                if 'DOLARES' in moneda or 'USD' in moneda:
                    tipo_moneda = "DOLARES"
                else:
                    tipo_moneda = "SOLES"
            break
    
    # --- FORMA DE PAGO ---
    forma_pago = "Crédito"
    for linea in lineas:
        if 'forma de pago' in linea.lower():
            if 'contado' in linea.lower():
                forma_pago = "Contado"
            elif 'cr' in linea.lower():
                forma_pago = "Crédito"
            break
    
    # --- OBSERVACIÓN ---
    observacion = ""
    for i, linea in enumerate(lineas):
        if re.match(r'^observaci[oó]n$', linea.strip(), re.IGNORECASE):
            partes = []
            if i > 0:
                obs_antes = lineas[i-1].strip()
                if 'OPERACION' in obs_antes.upper():
                    obs_antes = obs_antes.replace('OPERACION', 'OPERACIÓN')
                    partes.append(obs_antes)
            if i + 1 < len(lineas):
                obs_despues = lineas[i+1].strip()
                if obs_despues and not re.match(r'^(Cantidad|Descripci)', obs_despues, re.IGNORECASE):
                    partes.append(obs_despues)
            if partes:
                observacion = ' '.join(partes)
            break
    
    # ==================== LÍNEA DE FACTURA ====================
    
    cantidad = 1.0
    valor_unitario = 0.0
    descripcion = ""
    
    match = re.search(r'(\d+\.?\d*)\s*UNIDAD\s+(.+?)\s+(\d{3,}\.?\d*)\s+(?:PENDIENTE|$)', texto, re.IGNORECASE)
    if match:
        cantidad = float(match.group(1))
        descripcion = match.group(2).strip()
        valor_unitario = float(match.group(3))
    else:
        match = re.search(r'(\d+\.?\d*)\s*UNIDAD[^0-9]+(\d{3,}\.?\d*)', texto, re.IGNORECASE)
        if match:
            cantidad = float(match.group(1))
            valor_unitario = float(match.group(2))
    
    # Buscar descripción completa incluyendo PENDIENTE
    match_desc = re.search(r'UNIDAD\s+(.+?)\s+Valor\s+de\s+Venta', texto, re.IGNORECASE)
    if match_desc:
        descripcion = match_desc.group(1).strip()
        # Limpiar números sueltos al final
        descripcion = re.sub(r'\s+\d+\.?\d*\s*$', '', descripcion)
    
    print(f"[INFO] Línea: cantidad={cantidad}, valor_unitario={valor_unitario}")
    
    # ==================== TOTALES ====================
    
    venta_gratuita = 0.0
    subtotal_venta = 0.0
    valor_venta = 0.0
    igv = 0.0
    isc = 0.0
    otros_cargos = 0.0
    otros_tributos = 0.0
    monto_redondeo = 0.0
    importe_total = 0.0
    monto_pendiente = 0.0
    anticipo = 0.0
    descuento = 0.0
    descripcion_total = ""
    
    for i, linea in enumerate(lineas):
        linea_clean = linea.strip()
        linea_lower = linea_clean.lower()
        
        def extraer_valor(idx):
            match = re.search(r'([\d,]+\.?\d*)\s*$', lineas[idx].strip()) if idx < len(lineas) else None
            return limpiar_numero(match.group(1)) if match else 0.0
        
        if 'gratuita' in linea_lower or 'operaciones gratuitas' in linea_lower:
            venta_gratuita = extraer_valor(i) or extraer_valor(i+1)
            print(f"[INFO] Venta Gratuita: {venta_gratuita}")
        
        elif 'sub total' in linea_lower:
            subtotal_venta = extraer_valor(i) or extraer_valor(i+1)
            print(f"[INFO] SubTotal: {subtotal_venta}")
        
        elif linea_lower.startswith('valor venta') and 'operaciones' not in linea_lower:
            valor_venta = extraer_valor(i) or extraer_valor(i+1)
            print(f"[INFO] Valor Venta: {valor_venta}")
        
        elif linea_lower.startswith('igv') or re.match(r'^igv\s', linea_lower):
            igv = extraer_valor(i) or extraer_valor(i+1)
            print(f"[INFO] IGV: {igv}")
        
        elif 'importe total' in linea_lower:
            importe_total = extraer_valor(i) or extraer_valor(i+1)
            print(f"[INFO] Importe Total: {importe_total}")
        
        elif 'pendiente' in linea_lower and 'pago' in linea_lower:
            monto_pendiente = extraer_valor(i) or extraer_valor(i+1)
            print(f"[INFO] Monto Pendiente: {monto_pendiente}")
        
        elif linea_lower.startswith('son:'):
            descripcion_total = linea_clean.replace('SON:', '').strip()
            if not descripcion_total.endswith('SOLES'):
                descripcion_total += ' SOLES'
    
    # ==================== CUOTAS ====================
    
    lista_cuotas = []
    total_cuotas = 0
    
    match = re.search(r'Total\s+(?:de\s+)?Cuotas\s+(\d+)', texto, re.IGNORECASE)
    if match:
        total_cuotas = int(match.group(1))
        print(f"[INFO] Total Cuotas: {total_cuotas}")
    
    cuotas_match = re.findall(r'(\d{2}/\d{2}/\d{4})\s+([\d,]+\.\d{2})', texto_raw)
    print(f"[DEBUG] Pares fecha-monto: {cuotas_match}")
    
    numero_cuota = 1
    for fecha, monto in cuotas_match:
        monto_num = limpiar_numero(monto)
        if monto_num > 100:
            existe = any(c["fechaVencimiento"] == fecha and c["monto"] == monto_num for c in lista_cuotas)
            if not existe:
                lista_cuotas.append({
                    "numero": numero_cuota,
                    "fechaVencimiento": fecha,
                    "monto": monto_num
                })
                print(f"[INFO] Cuota {numero_cuota}: {fecha} - {monto_num}")
                numero_cuota += 1
    
    # ==================== CONSTRUIR JSON IDÉNTICO AL PDF ====================
    
    # Construir línea de factura
    linea_factura = []
    if valor_unitario > 0:
        linea_factura.append({
            "cantidad": cantidad,
            "unidadMedida": "UNIDAD",
            "descripcion": descripcion,
            "valorUnitario": valor_unitario
        })
    
    # Estructura EXACTA del PDF
    resultado = {
        "factura": {
            "razonSocialEmisor": razon_social_emisor,
            "direccionEmisor": direccion_emisor,
            "departamento": departamento,
            "provincia": provincia,
            "distrito": distrito,
            "rucEmisor": ruc_emisor,
            "numeroFactura": numero_factura,
            "fechaEmision": fecha_emision,
            "razonSocialReceptor": razon_social_receptor,
            "rucReceptor": ruc_receptor,
            "direccionReceptorFactura": direccion_receptor_factura,
            "direccionCliente": direccion_cliente,
            "fechaContable": fecha_emision,  # Igual a fecha emisión
            "tipoMoneda": tipo_moneda,
            "observacion": observacion,
            "formaPago": forma_pago,
            "lineaFactura": linea_factura,
            "ventaGratuita": venta_gratuita,
            "descripcionImporteTotal": descripcion_total,
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
            "montoNetoPendientePago": monto_pendiente,
            "totalCuota": len(lista_cuotas),
            "cuotas": lista_cuotas
        },
        "validacion": []
    }
    
    print("=" * 70)
    print("EXTRACCIÓN COMPLETADA")
    print("=" * 70)
    
    return resultado


# Prueba directa
if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        resultado = procesar_factura_img(sys.argv[1])
        print("\n" + "=" * 70)
        print("JSON FINAL:")
        print("=" * 70)
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
