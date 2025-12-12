# -*- coding: utf-8 -*-
"""
PROCESADOR DE IMAGEN PARA FACTURAS ELECTRÓNICAS SUNAT
Versión 7: Tesseract OCR con extracción mejorada
"""

import re
import os
from PIL import Image, ImageFilter, ImageEnhance
import pytesseract

# Configurar path de Tesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


def preprocesar_imagen(imagen_path):
    """
    Preprocesa la imagen para mejorar la calidad del OCR.
    """
    img = Image.open(imagen_path)
    
    # Convertir a RGB si es necesario
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Convertir a escala de grises
    img_gray = img.convert('L')
    
    # Aumentar contraste moderadamente
    enhancer = ImageEnhance.Contrast(img_gray)
    img_contrast = enhancer.enhance(1.8)
    
    return img_contrast


def extraer_texto_tesseract(imagen_path):
    """
    Extrae texto usando Tesseract con configuración optimizada para facturas.
    """
    img = preprocesar_imagen(imagen_path)
    
    # Configuración para preservar layout
    # PSM 4: Assume a single column of text of variable sizes
    config = '--oem 3 --psm 4 -l spa'
    
    texto = pytesseract.image_to_string(img, config=config)
    
    return texto


def limpiar_numero(texto):
    """
    Limpia un texto para extraer un número decimal.
    """
    if not texto:
        return 0.0
    
    texto = str(texto).strip()
    
    # Quitar símbolos de moneda
    texto = re.sub(r'S/?\.?', '', texto)
    texto = texto.replace('$', '').replace('€', '')
    
    # Quitar espacios
    texto = texto.replace(' ', '')
    
    # Formato: 4,200.00 o 4200.00
    texto = texto.replace(',', '')
    
    # Buscar patrón numérico
    match = re.search(r'(\d+\.?\d*)', texto)
    if match:
        return float(match.group(1))
    
    return 0.0


def extraer_ruc(texto):
    """Extrae todos los RUCs de 11 dígitos."""
    rucs = re.findall(r'\b(\d{11})\b', texto)
    # Filtrar RUCs válidos (empiezan con 10 o 20)
    rucs_validos = [r for r in rucs if r.startswith(('10', '20'))]
    return rucs_validos


def extraer_fecha(texto):
    """Extrae fecha del texto."""
    match = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
    if match:
        return match.group(1)
    return ""


def procesar_factura_img(imagen_path: str) -> dict:
    """
    Procesa una imagen de factura electrónica SUNAT y extrae datos estructurados.
    Usa Tesseract OCR para mejor precisión en números.
    """
    print("[OCR] Extrayendo texto con Tesseract...")
    
    # Extraer texto con Tesseract
    texto_raw = extraer_texto_tesseract(imagen_path)
    
    print("=" * 70)
    print("TEXTO EXTRAIDO POR TESSERACT:")
    print("=" * 70)
    print(texto_raw[:2000])
    print("=" * 70)
    
    # Trabajar con el texto completo sin dividir excesivamente
    texto = texto_raw.replace('\n', ' ').replace('  ', ' ')
    
    # Inicializar resultado
    resultado = {
        "rucEmisor": "",
        "tipoDocEmisor": "6",
        "numeroFactura": "",
        "razonSocialEmisor": "",
        "direccionEmisor": "",
        "direccionCliente": "",
        "ubigeoEmisor": "",
        "rucReceptor": "",
        "tipoDocReceptor": "6",
        "razonSocialReceptor": "",
        "direccionReceptor": "",
        "fechaEmision": "",
        "horaEmision": "",
        "formaPago": "",
        "tipoMoneda": "PEN",
        "observacion": "",
        "lineasFactura": [],
        "valorVenta": 0.0,
        "precioVenta": 0.0,
        "igv": 0.0,
        "isc": 0.0,
        "otrosTributos": 0.0,
        "otrosCargos": 0.0,
        "descuentos": 0.0,
        "anticipos": 0.0,
        "importeTotal": 0.0,
        "operacionesGratuitas": 0.0,
        "montoPendiente": 0.0,
        "totalCuotas": 0,
        "cuotas": []
    }
    
    # ==================== EXTRACCIÓN DE DATOS ====================
    
    # --- RUCs ---
    rucs = extraer_ruc(texto)
    print(f"\n[INFO] RUCs encontrados: {rucs}")
    
    # El primer RUC suele ser del emisor (10...) o receptor (20...)
    # En facturas SUNAT, el emisor es persona natural (10) o empresa (20)
    for ruc in rucs:
        if ruc.startswith('10') and not resultado["rucEmisor"]:
            resultado["rucEmisor"] = ruc
        elif ruc.startswith('20') and not resultado["rucReceptor"]:
            resultado["rucReceptor"] = ruc
    
    # Si no hay emisor con 10, usar el primero
    if not resultado["rucEmisor"] and rucs:
        resultado["rucEmisor"] = rucs[0]
        if len(rucs) > 1:
            resultado["rucReceptor"] = rucs[1]
    
    # --- NÚMERO DE FACTURA ---
    # Buscar patrón E001-131, F001-123, etc.
    match = re.search(r'([EFB]\d{3}[-\s]?\d+)', texto, re.IGNORECASE)
    if match:
        resultado["numeroFactura"] = match.group(1).replace(' ', '').replace('-', '-')
    
    # --- FECHA DE EMISIÓN ---
    # Buscar fecha cerca de "Emisión" - varios formatos posibles
    patrones_fecha_emision = [
        r'Fecha\s*(?:de\s*)?Emisi[oó]n[:\s]*(\d{2}/\d{2}/\d{4})',
        r'Emisi[oó]n[:\s]*(\d{2}/\d{2}/\d{4})',
        r'Fecha\s*(?:de\s*)?Emisi[oó]n[:\s]*(\d{8})',  # Sin barras: 30112025
    ]
    for patron in patrones_fecha_emision:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            fecha = match.group(1)
            # Si viene sin barras, formatear
            if len(fecha) == 8 and '/' not in fecha:
                fecha = f"{fecha[:2]}/{fecha[2:4]}/{fecha[4:]}"
            resultado["fechaEmision"] = fecha
            break
    
    if not resultado["fechaEmision"]:
        # Última opción: primera fecha encontrada
        resultado["fechaEmision"] = extraer_fecha(texto)
    
    # --- FORMA DE PAGO ---
    if re.search(r'Cr[eé]dito', texto, re.IGNORECASE):
        resultado["formaPago"] = "Credito"
    elif re.search(r'Contado', texto, re.IGNORECASE):
        resultado["formaPago"] = "Contado"
    
    # --- RAZÓN SOCIAL EMISOR ---
    # Patrón: FACTURA ELECTRONICA <NOMBRE> RUC o antes del primer RUC
    match = re.search(r'(?:ELECTRONICA|ELECTR[OÓ]NICA)\s+(.+?)\s+(?:RUC|CAL|AV)', texto, re.IGNORECASE)
    if match:
        nombre = match.group(1).strip()
        nombre = re.sub(r'\s+', ' ', nombre)
        resultado["razonSocialEmisor"] = nombre
    
    # --- RAZÓN SOCIAL RECEPTOR ---
    match = re.search(r'Se[ñn]or\(?es?\)?[:\s]*(.+?)\s+RUC', texto, re.IGNORECASE)
    if match:
        nombre = match.group(1).strip()
        nombre = re.sub(r'\s+', ' ', nombre)
        resultado["razonSocialReceptor"] = nombre
    
    # --- TIPO DE MONEDA ---
    if re.search(r'SOLES|PEN', texto, re.IGNORECASE):
        resultado["tipoMoneda"] = "PEN"
    elif re.search(r'DOLARES|USD', texto, re.IGNORECASE):
        resultado["tipoMoneda"] = "USD"
    
    # --- OBSERVACIÓN ---
    match = re.search(r'Observaci[oó]n\s+(.+?)(?:Cantidad|Descripci)', texto, re.IGNORECASE)
    if match:
        resultado["observacion"] = match.group(1).strip()
    
    # --- DIRECCIONES ---
    match = re.search(r'Direcci[oó]n\s+del\s+Receptor[:\s]+(.+?)(?:AV\.|Direcci|Tipo)', texto, re.IGNORECASE)
    if match:
        resultado["direccionReceptor"] = match.group(1).strip()
    
    match = re.search(r'Direcci[oó]n\s+del\s+Cliente[:\s]+(.+?)(?:Tipo|Moneda)', texto, re.IGNORECASE)
    if match:
        resultado["direccionCliente"] = match.group(1).strip()
    
    # ==================== VALOR UNITARIO ====================
    
    valor_unitario = 0.0
    cantidad = 1.0
    descripcion = ""
    
    # Buscar patrón: 1.00 UNIDAD descripción 4200.00
    match = re.search(r'(\d+\.?\d*)\s*UNIDAD[:\s]*(.+?)\s+(\d{3,}\.00)', texto, re.IGNORECASE)
    if match:
        cantidad = float(match.group(1))
        descripcion = match.group(2).strip()
        valor_unitario = float(match.group(3))
        print(f"[INFO] Línea encontrada: cantidad={cantidad}, desc={descripcion[:50]}..., valor={valor_unitario}")
    else:
        # Buscar valor unitario cerca de "Valor Unitario"
        match = re.search(r'Valor\s+Unitario\s+(\d+\.?\d*)\s*UNIDAD', texto, re.IGNORECASE)
        if match:
            valor_unitario = float(match.group(1))
    
    # ==================== TOTALES ====================
    
    importe_total = 0.0
    valor_venta = 0.0
    igv = 0.0
    
    # Trabajar línea por línea para mayor precisión
    lineas = texto_raw.split('\n')
    
    for linea in lineas:
        linea_clean = linea.strip()
        linea_lower = linea_clean.lower()
        
        # Valor Venta (línea que empieza con "Valor Venta")
        if linea_lower.startswith('valor venta') and 'operaciones' not in linea_lower:
            match = re.search(r'([\d,]+\.?\d*)\s*$', linea_clean)
            if match:
                valor_venta = limpiar_numero(match.group(1))
                print(f"[INFO] Valor Venta (línea): {valor_venta}")
        
        # Sub Total Ventas
        elif 'sub total' in linea_lower:
            # Buscar número entre corchetes o al final
            match = re.search(r'\[?([\d,]+\.?\d*)\]?\s*$', linea_clean)
            if match:
                subtotal = limpiar_numero(match.group(1))
                if subtotal > 0 and valor_venta == 0:
                    valor_venta = subtotal
                    print(f"[INFO] Sub Total Ventas: {subtotal}")
        
        # IGV
        elif linea_lower.startswith('igv') or re.match(r'^igv\s', linea_lower):
            match = re.search(r'([\d,]+\.?\d*)\s*$', linea_clean)
            if match:
                igv = limpiar_numero(match.group(1))
                print(f"[INFO] IGV (línea): {igv}")
        
        # Importe Total
        elif 'importe total' in linea_lower:
            # El número viene después de "Importe Total"
            match = re.search(r'importe\s+total\s+S?/?\.?\s*([\d,]+\.?\d*)', linea_clean, re.IGNORECASE)
            if match:
                importe_total = limpiar_numero(match.group(1))
                print(f"[INFO] Importe Total (línea): {importe_total}")
    
    # ==================== CUOTAS ====================
    
    lista_cuotas = []
    monto_pendiente = 0.0
    
    # Buscar monto pendiente
    match = re.search(r'(?:pendiente|Monto\s+neto)[:\s]+S/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        monto_pendiente = limpiar_numero(match.group(1))
        print(f"[INFO] Monto pendiente: {monto_pendiente}")
    
    # Buscar total de cuotas
    total_cuotas_esperado = 0
    match = re.search(r'Total\s+(?:de\s+)?Cuotas\s+(\d+)', texto, re.IGNORECASE)
    if match:
        total_cuotas_esperado = int(match.group(1))
        print(f"[INFO] Total cuotas esperado: {total_cuotas_esperado}")
    
    # Buscar cuotas: fecha + monto (formato más flexible)
    # Ejemplo: 01/12/2025 2,100.00
    cuotas_match = re.findall(r'(\d{2}/\d{2}/\d{4})\s+([\d,]+\.\d{2})', texto_raw)
    print(f"[DEBUG] Pares fecha-monto encontrados: {cuotas_match}")
    
    # Filtrar: solo montos mayores a 100 y fechas que no sean de emisión
    fecha_emision = resultado.get("fechaEmision", "")
    
    for fecha, monto in cuotas_match:
        monto_num = limpiar_numero(monto)
        # Filtrar: montos razonables (mayor a 100) y no sea la fecha de emisión
        if monto_num > 100 and fecha != fecha_emision:
            # Evitar duplicados
            existe = any(c["fechaCuota"] == fecha for c in lista_cuotas)
            if not existe:
                lista_cuotas.append({
                    "fechaCuota": fecha,
                    "montoCuota": monto_num
                })
                print(f"[INFO] Cuota encontrada: {fecha} - {monto_num}")
    
    # ==================== CÁLCULO INTELIGENTE ====================
    
    print("\n[CÁLCULO INTELIGENTE]")
    
    # ESTRATEGIA: El valor unitario es el más confiable porque está aislado
    # Usar valor unitario para calcular todo
    
    if valor_unitario > 0:
        print(f"  Usando Valor Unitario como base: {valor_unitario}")
        
        # Valor Venta = cantidad * valor unitario
        valor_venta = valor_unitario * cantidad
        
        # IGV = 18% del valor venta
        igv = round(valor_venta * 0.18, 2)
        
        # Importe Total = valor venta + IGV
        importe_total = round(valor_venta + igv, 2)
        
        print(f"    Calculado: Valor Venta = {valor_venta}")
        print(f"    Calculado: IGV (18%) = {igv}")
        print(f"    Calculado: Importe Total = {importe_total}")
    
    # Si no hay valor unitario pero sí cuotas
    elif lista_cuotas:
        suma_cuotas = sum(c["montoCuota"] for c in lista_cuotas)
        print(f"  Usando suma de Cuotas: {suma_cuotas}")
        
        # El monto de cuotas puede tener descuentos, usar como referencia
        monto_pendiente = suma_cuotas
        
        # Para calcular el total original, verificar si hay descuento
        # Por ahora usar el monto pendiente
        importe_total = suma_cuotas
        valor_venta = round(importe_total / 1.18, 2)
        igv = round(importe_total - valor_venta, 2)
    
    # Validación final
    if valor_venta > 0 and igv == 0:
        igv = round(valor_venta * 0.18, 2)
    
    if valor_venta > 0 and importe_total == 0:
        importe_total = round(valor_venta * 1.18, 2)
    
    print(f"\n  RESULTADO:")
    print(f"    Valor Venta: {valor_venta}")
    print(f"    IGV: {igv}")
    print(f"    Importe Total: {importe_total}")
    
    # ==================== CONSTRUIR RESULTADO ====================
    
    # Línea de factura
    linea_factura = {
        "cantidad": cantidad,
        "unidadMedida": "UNIDAD",
        "descripcion": descripcion,
        "valorUnitario": valor_unitario if valor_unitario > 0 else valor_venta,
        "valorVenta": valor_venta,
        "precioVenta": importe_total,
        "igv": round(valor_unitario * 0.18 * cantidad, 2) if valor_unitario > 0 else igv
    }
    
    resultado["lineasFactura"] = [linea_factura]
    
    # Totales
    resultado["valorVenta"] = valor_venta
    resultado["precioVenta"] = valor_venta
    resultado["igv"] = igv
    resultado["importeTotal"] = importe_total
    resultado["montoPendiente"] = monto_pendiente if monto_pendiente > 0 else importe_total
    resultado["cuotas"] = lista_cuotas
    resultado["totalCuotas"] = len(lista_cuotas)
    
    print("=" * 70)
    print("EXTRACCIÓN COMPLETADA")
    print("=" * 70)
    
    return resultado


# Prueba directa
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        resultado = procesar_factura_img(sys.argv[1])
        import json
        print("\n" + "=" * 70)
        print("JSON FINAL:")
        print("=" * 70)
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
