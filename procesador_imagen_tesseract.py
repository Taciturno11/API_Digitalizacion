# -*- coding: utf-8 -*-
"""
PROCESADOR DE IMAGEN PARA FACTURAS ELECTRÓNICAS SUNAT
Versión: Tesseract OCR (Más preciso que EasyOCR para documentos)
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
    
    # Aumentar contraste
    enhancer = ImageEnhance.Contrast(img_gray)
    img_contrast = enhancer.enhance(2.0)
    
    # Aumentar nitidez
    img_sharp = img_contrast.filter(ImageFilter.SHARPEN)
    
    # Binarización (umbral)
    threshold = 150
    img_binary = img_sharp.point(lambda x: 255 if x > threshold else 0, mode='1')
    
    return img_binary


def extraer_texto_tesseract(imagen_path):
    """
    Extrae texto usando Tesseract con configuración optimizada para facturas.
    """
    # Preprocesar imagen
    img = preprocesar_imagen(imagen_path)
    
    # Configuración de Tesseract optimizada para facturas
    # PSM 6: Assume a single uniform block of text
    # OEM 3: Default, based on what is available
    config = '--oem 3 --psm 6 -l spa'
    
    # Extraer texto
    texto = pytesseract.image_to_string(img, config=config)
    
    return texto


def limpiar_numero(texto):
    """
    Limpia un texto para extraer un número decimal.
    Corrige errores comunes de OCR.
    """
    if not texto:
        return 0.0
    
    # Convertir a string y limpiar
    texto = str(texto).strip()
    
    # Reemplazar caracteres comunes mal leídos
    texto = texto.replace('O', '0').replace('o', '0')
    texto = texto.replace('l', '1').replace('I', '1')
    texto = texto.replace('S/', '').replace('s/', '')
    texto = texto.replace('$', '').replace('€', '')
    texto = texto.replace(' ', '')
    texto = texto.replace(',', '')  # Quitar separadores de miles
    
    # Buscar patrón numérico
    match = re.search(r'(\d+\.?\d*)', texto)
    if match:
        return float(match.group(1))
    
    return 0.0


def extraer_monto_de_linea(linea, patron_prefijo=None):
    """
    Extrae un monto de una línea de texto.
    """
    if patron_prefijo:
        match = re.search(patron_prefijo + r'\s*S?/?\.?\s*([\d,.\s]+)', linea, re.IGNORECASE)
        if match:
            return limpiar_numero(match.group(1))
    
    # Buscar cualquier número con formato de monto
    montos = re.findall(r'[\d,]+\.?\d{0,2}', linea)
    if montos:
        # Tomar el último monto (usualmente es el valor)
        return limpiar_numero(montos[-1])
    
    return 0.0


def extraer_ruc(texto, patron):
    """Extrae RUC usando patrón específico."""
    match = re.search(patron, texto)
    if match:
        ruc = match.group(1) if match.groups() else match.group(0)
        # Limpiar y validar
        ruc = re.sub(r'\D', '', ruc)
        if len(ruc) == 11 and ruc.startswith(('10', '20')):
            return ruc
    return ""


def extraer_fecha(texto):
    """Extrae fecha del texto."""
    patrones = [
        r'(\d{2}/\d{2}/\d{4})',
        r'(\d{2}-\d{2}-\d{4})',
        r'(\d{4}/\d{2}/\d{2})',
        r'(\d{4}-\d{2}-\d{2})',
    ]
    for patron in patrones:
        match = re.search(patron, texto)
        if match:
            return match.group(1)
    return ""


def normalizar_texto(texto):
    """Normaliza espaciado extra en el texto."""
    # Arreglar letras separadas por espacios (ej: "G A M B O A" -> "GAMBOA")
    palabras = texto.split()
    resultado = []
    buffer = []
    
    for palabra in palabras:
        if len(palabra) == 1 and palabra.isalpha():
            buffer.append(palabra)
        else:
            if buffer:
                resultado.append(''.join(buffer))
                buffer = []
            resultado.append(palabra)
    
    if buffer:
        resultado.append(''.join(buffer))
    
    return ' '.join(resultado)


def procesar_factura_img(imagen_path: str) -> dict:
    """
    Procesa una imagen de factura electrónica SUNAT y extrae datos estructurados.
    Usa Tesseract OCR para mejor precisión.
    """
    print("[OCR] Extrayendo texto con Tesseract...")
    
    # Extraer texto con Tesseract
    texto_completo = extraer_texto_tesseract(imagen_path)
    
    # Normalizar
    texto_completo = normalizar_texto(texto_completo)
    
    # Dividir en líneas
    lineas = [l.strip() for l in texto_completo.split('\n') if l.strip()]
    
    print("=" * 70)
    print("TEXTO EXTRAIDO POR TESSERACT:")
    print("=" * 70)
    for i, linea in enumerate(lineas):
        print(f"[{i:02d}] {linea}")
    print("=" * 70)
    
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
    
    texto_unido = ' '.join(lineas)
    
    # ==================== EXTRACCIÓN DE DATOS ====================
    
    # --- RUC EMISOR ---
    patrones_ruc_emisor = [
        r'RUC[:\s]*(\d{11})',
        r'R\.U\.C\.[:\s]*(\d{11})',
    ]
    for patron in patrones_ruc_emisor:
        ruc = extraer_ruc(texto_unido, patron)
        if ruc:
            resultado["rucEmisor"] = ruc
            break
    
    # --- NÚMERO DE FACTURA ---
    patrones_factura = [
        r'([EFB]\d{3}[-\s]?\d+)',
        r'FACTURA.*?([A-Z]\d{3}[-\s]?\d+)',
    ]
    for patron in patrones_factura:
        match = re.search(patron, texto_unido, re.IGNORECASE)
        if match:
            resultado["numeroFactura"] = match.group(1).replace(' ', '')
            break
    
    # --- FECHA DE EMISIÓN ---
    for linea in lineas:
        if 'fecha' in linea.lower() or 'emisi' in linea.lower():
            fecha = extraer_fecha(linea)
            if fecha:
                resultado["fechaEmision"] = fecha
                break
    
    if not resultado["fechaEmision"]:
        resultado["fechaEmision"] = extraer_fecha(texto_unido)
    
    # --- FORMA DE PAGO ---
    if re.search(r'cr[eé]dito', texto_unido, re.IGNORECASE):
        resultado["formaPago"] = "Credito"
    elif re.search(r'contado', texto_unido, re.IGNORECASE):
        resultado["formaPago"] = "Contado"
    
    # --- RAZÓN SOCIAL EMISOR ---
    # Buscar nombre antes del RUC
    match = re.search(r'ELECTRONICA\s+(.+?)\s+RUC', texto_unido, re.IGNORECASE)
    if match:
        resultado["razonSocialEmisor"] = match.group(1).strip()
    
    # --- RUC RECEPTOR ---
    # Buscar segundo RUC en el documento
    todos_ruc = re.findall(r'RUC[:\s]*(\d{11})', texto_unido, re.IGNORECASE)
    if len(todos_ruc) >= 2:
        resultado["rucReceptor"] = todos_ruc[1]
    elif len(todos_ruc) == 1 and not resultado["rucEmisor"]:
        resultado["rucEmisor"] = todos_ruc[0]
    
    # --- RAZÓN SOCIAL RECEPTOR ---
    patrones_receptor = [
        r'Se[ñn]or\(?es?\)?[:\s]*(.+?)(?:RUC|$)',
        r'Cliente[:\s]*(.+?)(?:RUC|$)',
    ]
    for patron in patrones_receptor:
        match = re.search(patron, texto_unido, re.IGNORECASE)
        if match:
            razon = match.group(1).strip()
            razon = re.sub(r'\s+', ' ', razon)
            if len(razon) > 5:
                resultado["razonSocialReceptor"] = razon
                break
    
    # --- TIPO DE MONEDA ---
    if re.search(r'SOLES|PEN', texto_unido, re.IGNORECASE):
        resultado["tipoMoneda"] = "PEN"
    elif re.search(r'D[OÓ]LARES|USD|\$', texto_unido):
        resultado["tipoMoneda"] = "USD"
    
    # --- DIRECCIONES ---
    for i, linea in enumerate(lineas):
        linea_lower = linea.lower()
        if 'direcci' in linea_lower and 'receptor' in linea_lower:
            # Buscar dirección en líneas siguientes
            if i + 1 < len(lineas):
                resultado["direccionReceptor"] = lineas[i + 1]
        elif 'direcci' in linea_lower and 'cliente' in linea_lower:
            if i + 1 < len(lineas):
                resultado["direccionCliente"] = lineas[i + 1]
    
    # --- OBSERVACIÓN ---
    match = re.search(r'Observaci[oó]n[:\s]*(.+?)(?:\n|Cantidad)', texto_unido, re.IGNORECASE)
    if match:
        resultado["observacion"] = match.group(1).strip()
    
    # ==================== LÍNEAS DE FACTURA ====================
    
    linea_factura = {
        "cantidad": 1.0,
        "unidadMedida": "UNIDAD",
        "descripcion": "",
        "valorUnitario": 0.0,
        "valorVenta": 0.0,
        "precioVenta": 0.0,
        "igv": 0.0
    }
    
    # Buscar línea con valor unitario
    for linea in lineas:
        if re.search(r'\d{4}\.00', linea):  # Patrón típico de monto grande
            # Extraer descripción y valor
            match = re.search(r'UNIDAD\s+(.+?)\s+(\d[\d,.]+)$', linea)
            if match:
                linea_factura["descripcion"] = match.group(1).strip()
                linea_factura["valorUnitario"] = limpiar_numero(match.group(2))
            else:
                # Buscar cualquier número al final
                numeros = re.findall(r'(\d[\d,.]+)', linea)
                if numeros:
                    linea_factura["valorUnitario"] = limpiar_numero(numeros[-1])
                # Descripción es todo excepto números
                desc = re.sub(r'[\d,.]+$', '', linea).strip()
                desc = re.sub(r'^UNIDAD\s*', '', desc)
                linea_factura["descripcion"] = desc
    
    # ==================== TOTALES ====================
    
    valor_venta = 0.0
    igv = 0.0
    importe_total = 0.0
    
    for linea in lineas:
        linea_lower = linea.lower()
        
        # Sub Total / Valor de Venta
        if 'sub total' in linea_lower or 'subtotal' in linea_lower:
            numeros = re.findall(r'(\d[\d,.]*\.\d{2})', linea)
            if numeros:
                valor_venta = limpiar_numero(numeros[-1])
        
        # Valor Venta (línea separada)
        elif 'valor venta' in linea_lower and 'operaciones' not in linea_lower:
            numeros = re.findall(r'(\d[\d,.]*\.\d{2})', linea)
            if numeros:
                valor_venta = limpiar_numero(numeros[-1])
        
        # IGV
        elif linea_lower.startswith('igv') or ' igv ' in linea_lower:
            numeros = re.findall(r'(\d[\d,.]*\.\d{2})', linea)
            if numeros:
                igv = limpiar_numero(numeros[-1])
        
        # Importe Total
        elif 'importe total' in linea_lower or 'total' in linea_lower:
            numeros = re.findall(r'(\d[\d,.]*\.\d{2})', linea)
            if numeros:
                # El importe total suele ser el último número
                importe_total = limpiar_numero(numeros[-1])
    
    # ==================== CUOTAS ====================
    
    lista_cuotas = []
    monto_pendiente = 0.0
    
    for linea in lineas:
        linea_lower = linea.lower()
        
        # Monto pendiente
        if 'pendiente' in linea_lower or 'monto neto' in linea_lower:
            match = re.search(r'S/?\.?\s*([\d,]+\.?\d*)', linea)
            if match:
                monto_pendiente = limpiar_numero(match.group(1))
        
        # Cuotas (formato: fecha monto fecha monto)
        fechas = re.findall(r'(\d{2}/\d{2}/\d{4})', linea)
        montos = re.findall(r'(\d[\d,]*\.\d{2})', linea)
        
        if fechas and montos and len(fechas) == len(montos):
            for fecha, monto in zip(fechas, montos):
                monto_num = limpiar_numero(monto)
                if monto_num > 0:
                    lista_cuotas.append({
                        "fechaCuota": fecha,
                        "montoCuota": monto_num
                    })
    
    # ==================== CÁLCULO INTELIGENTE ====================
    
    print("\n[CÁLCULO INTELIGENTE]")
    
    # Si tenemos cuotas, usarlas para calcular
    if lista_cuotas:
        suma_cuotas = sum(c["montoCuota"] for c in lista_cuotas)
        print(f"  Suma de Cuotas: {suma_cuotas}")
        
        if suma_cuotas > 0:
            monto_pendiente = suma_cuotas
    
    # Si tenemos valor unitario, usarlo como base
    if linea_factura["valorUnitario"] > 0:
        valor_unitario = linea_factura["valorUnitario"]
        cantidad = linea_factura["cantidad"]
        
        # Valor venta = cantidad * valor unitario
        if valor_venta == 0:
            valor_venta = valor_unitario * cantidad
        
        # IGV = 18%
        if igv == 0:
            igv = round(valor_venta * 0.18, 2)
        
        # Total = base + IGV
        if importe_total == 0:
            importe_total = round(valor_venta + igv, 2)
        
        print(f"  Valor Unitario: {valor_unitario}")
        print(f"  Cantidad: {cantidad}")
        print(f"  Valor Venta (calculado): {valor_venta}")
        print(f"  IGV (18%): {igv}")
        print(f"  Importe Total: {importe_total}")
    
    # Actualizar línea de factura
    linea_factura["valorVenta"] = valor_venta
    linea_factura["precioVenta"] = importe_total
    linea_factura["igv"] = igv
    
    resultado["lineasFactura"] = [linea_factura]
    
    # Actualizar totales
    resultado["valorVenta"] = valor_venta
    resultado["precioVenta"] = valor_venta
    resultado["igv"] = igv
    resultado["importeTotal"] = importe_total
    resultado["montoPendiente"] = monto_pendiente
    resultado["cuotas"] = lista_cuotas
    resultado["totalCuotas"] = len(lista_cuotas)
    
    print("=" * 70)
    print("RESULTADO FINAL:")
    print(f"  valorVenta: {resultado['valorVenta']}")
    print(f"  igv: {resultado['igv']}")
    print(f"  importeTotal: {resultado['importeTotal']}")
    print(f"  cuotas: {len(lista_cuotas)}")
    print("=" * 70)
    
    return resultado


# Prueba directa
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        resultado = procesar_factura_img(sys.argv[1])
        import json
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
