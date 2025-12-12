# -*- coding: utf-8 -*-
"""
PROCESADOR DE IMAGEN PARA FACTURAS ELECTRÓNICAS SUNAT
Versión 9: Tesseract OCR - Lógica GENÉRICA basada en estructura del PDF

ESTRATEGIA: Usar la misma lógica que procesador_pdf_v2.py
- Extraer texto con OCR
- Procesar línea por línea igual que el PDF
- Usar patrones flexibles para diferentes formatos de factura
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
    """Limpia texto para extraer número."""
    if not texto:
        return 0.0
    texto = str(texto).strip()
    # Limpiar S/, 5/, etc.
    texto = re.sub(r'[S5]/?\.?\s*', '', texto)
    texto = texto.replace('$', '').replace('€', '').replace(' ', '').replace(',', '')
    match = re.search(r'(\d+\.?\d*)', texto)
    return float(match.group(1)) if match else 0.0


def normalizar_texto_espaciado(texto):
    """
    Corrige texto con letras individuales separadas por espacios.
    Ejemplo: "GAMB O A" -> "GAMBOA", "S A C" -> "SAC"
    """
    if not texto:
        return texto
    
    palabras = texto.split()
    if not palabras:
        return texto
    
    grupos = []
    i = 0
    while i < len(palabras):
        palabra = palabras[i]
        
        if len(palabra) == 1 and palabra.isalpha():
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
    
    resultado = []
    i = 0
    while i < len(grupos):
        tipo, valor = grupos[i]
        
        if tipo == 'palabra':
            if i + 1 < len(grupos) and grupos[i + 1][0] == 'letras':
                siguiente_letras = grupos[i + 1][1]
                if len(siguiente_letras) <= 2:
                    resultado.append(valor + siguiente_letras)
                    i += 2
                    continue
            resultado.append(valor)
        else:
            resultado.append(valor)
        i += 1
    
    return ' '.join(resultado)


def extraer_geo_de_linea(linea):
    """
    Extrae distrito, provincia, departamento de una línea con formato:
    "XXX - XXX - XXX" o "XXX-XXX-XXX"
    """
    partes = re.split(r'\s*-\s*', linea.strip())
    if len(partes) >= 3:
        return partes[0].strip(), partes[1].strip(), partes[2].strip()
    return "", "", ""


def procesar_factura_img(imagen_path: str) -> dict:
    """
    Procesa una imagen de factura electrónica SUNAT.
    Usa la MISMA LÓGICA que procesador_pdf_v2.py para extraer datos.
    """
    
    # Extraer texto con OCR
    texto_raw = extraer_texto_tesseract(imagen_path)
    lineas = [l.strip() for l in texto_raw.split('\n') if l.strip()]
    texto = ' '.join(lineas)
    
    # === INICIALIZAR ESTRUCTURA ===
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
    
    # =========================================================================
    # SECCIÓN 1: CABECERA (EMISOR) - Similar a PDF
    # =========================================================================
    
    # Buscar RUC Emisor (10XXXXXXXXX) y su posición
    ruc_emisor_idx = -1
    for i, linea in enumerate(lineas):
        match = re.search(r'RUC[:\s]*(\d{11})', linea)
        if match and match.group(1).startswith('10'):
            factura["rucEmisor"] = int(match.group(1))
            ruc_emisor_idx = i
            break
    
    # Razón Social Emisor: línea ANTES del RUC emisor (o la que contiene nombre)
    if ruc_emisor_idx > 0:
        # Buscar el nombre en la línea anterior o en la misma línea antes del RUC
        linea_ruc = lineas[ruc_emisor_idx]
        # Si el nombre está en la misma línea que el RUC
        match_nombre = re.search(r'^(.+?)\s*RUC', linea_ruc)
        if match_nombre:
            factura["razonSocialEmisor"] = normalizar_texto_espaciado(match_nombre.group(1).strip())
        else:
            # El nombre está en la línea anterior
            for j in range(ruc_emisor_idx - 1, -1, -1):
                candidato = lineas[j].strip()
                # Ignorar "FACTURA ELECTRONICA" y líneas vacías
                if candidato and 'FACTURA' not in candidato.upper():
                    factura["razonSocialEmisor"] = normalizar_texto_espaciado(candidato)
                    break
    
    # Dirección Emisor: buscar línea con formato de dirección antes de la factura
    for i, linea in enumerate(lineas):
        # La dirección del emisor típicamente tiene formato calle/avenida
        if re.search(r'^(CAL\.?|AV\.?|JR\.?|PSJE\.?|URB\.?|Ayacucho|Calle|Avenida|Jiron)', linea, re.IGNORECASE):
            # Solo si está antes del número de factura
            es_antes_factura = True
            for j in range(i):
                if re.search(r'[EFB]\d{3}-\d+', lineas[j]):
                    es_antes_factura = False
                    break
            if es_antes_factura:
                factura["direccionEmisor"] = linea.strip()
                break
    
    # Número de Factura
    for linea in lineas:
        match = re.search(r'([EFB]\d{3}-\d+)', linea)
        if match:
            factura["numeroFactura"] = match.group(1)
            break
    
    # Ubigeo (Distrito - Provincia - Departamento)
    for linea in lineas[:15]:  # Buscar en primeras 15 líneas
        match = re.search(r'([A-Za-z]+)\s*-\s*([A-Z]+)\s*-\s*([A-Z]+)', linea)
        if match:
            factura["distrito"] = match.group(1).strip()
            factura["provincia"] = match.group(2).strip()
            factura["departamento"] = match.group(3).strip()
            break
    
    # =========================================================================
    # SECCIÓN 2: RECEPTOR Y OPERACIÓN
    # =========================================================================
    
    # Fecha de Emisión
    for linea in lineas:
        match = re.search(r'Fecha\s*(?:de\s*)?Emisi[oó]n[:\s]*(\d{2}/\d{2}/\d{4})', linea, re.IGNORECASE)
        if match:
            factura["fechaEmision"] = match.group(1)
            factura["fechaContable"] = match.group(1)
            break
    
    # Forma de Pago (en la misma línea que fecha, o cerca)
    for linea in lineas:
        if 'Contado' in linea:
            factura["formaPago"] = "Contado"
            break
        elif re.search(r'Cr[eé]dito', linea, re.IGNORECASE):
            factura["formaPago"] = "Crédito"
            break
    
    # RUC Receptor (20XXXXXXXXX)
    ruc_receptor_idx = -1
    for i, linea in enumerate(lineas):
        match = re.search(r'RUC[:\s]*(\d{11})', linea)
        if match and match.group(1).startswith('20'):
            factura["rucReceptor"] = int(match.group(1))
            ruc_receptor_idx = i
            break
    
    # Razón Social Receptor: líneas entre "Señor(es)" y RUC receptor
    if ruc_receptor_idx > 0:
        partes_nombre = []
        # Buscar hacia atrás desde el RUC receptor
        for j in range(ruc_receptor_idx - 1, max(ruc_receptor_idx - 5, 0), -1):
            linea = lineas[j].strip()
            # Limpiar prefijos como "Señor(es)", "Señ", "ñor(es)"
            linea = re.sub(r'^Se[ñn]or\(?es\)?\s*', '', linea)
            linea = re.sub(r'^[ñn]or\(?es\)?\s*', '', linea)
            linea = re.sub(r'^Se[ñn]\s*', '', linea)
            
            # Si la línea contiene palabras relevantes del nombre
            if linea and not re.search(r'(Fecha|Emisi|pago|RUC|\d{11})', linea):
                partes_nombre.insert(0, linea)
            
            # Parar si llegamos a la línea de fecha
            if 'Fecha' in lineas[j] or 'Emisión' in lineas[j]:
                break
        
        if partes_nombre:
            nombre_completo = ' '.join(partes_nombre)
            # Limpiar duplicaciones como "Señor(es)" en medio
            nombre_completo = re.sub(r'\s*Se[ñn]or\(?es\)?\s*', ' ', nombre_completo)
            factura["razonSocialReceptor"] = normalizar_texto_espaciado(nombre_completo.strip())
    
    # Direcciones del Receptor
    # Buscar líneas después del RUC receptor hasta "Dirección del Cliente"
    if ruc_receptor_idx > 0:
        dir_receptor_partes = []
        dir_cliente_partes = []
        en_dir_receptor = True
        en_dir_cliente = False
        
        for j in range(ruc_receptor_idx + 1, min(ruc_receptor_idx + 15, len(lineas))):
            linea = lineas[j].strip()
            
            # Detectar inicio de sección "Dirección del Cliente"
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
            
            # Limpiar línea de "Dirección del Receptor de la factura :"
            linea_limpia = re.sub(r'Direcci[oó]n del Receptor.*?:\s*', '', linea)
            
            if linea_limpia:
                if en_dir_cliente:
                    dir_cliente_partes.append(linea_limpia)
                elif en_dir_receptor:
                    dir_receptor_partes.append(linea_limpia)
        
        # Combinar partes de dirección receptor
        if dir_receptor_partes:
            dir_completa = ' '.join(dir_receptor_partes)
            dir_completa = re.sub(r'\s+', ' ', dir_completa).strip()
            dir_completa = dir_completa.replace('EL.', 'EL')
            factura["direccionReceptorFactura"] = dir_completa
        
        # Combinar partes de dirección cliente
        if dir_cliente_partes:
            dir_cliente = ' '.join(dir_cliente_partes)
            dir_cliente = re.sub(r'\s+', ' ', dir_cliente).strip()
            dir_cliente = dir_cliente.replace('EL.', 'EL')
            factura["direccionCliente"] = dir_cliente
    
    # Tipo de Moneda
    if re.search(r'DOLARES|USD', texto, re.IGNORECASE):
        factura["tipoMoneda"] = "DOLARES"
    else:
        factura["tipoMoneda"] = "SOLES"
    
    # Observación
    match = re.search(r'Observaci[oó]n[:\s]*(.+?)(?=Cantidad|Unidad|$)', texto, re.IGNORECASE)
    if match:
        obs = match.group(1).strip()
        # Extraer CTA.CTE si existe
        match_cta = re.search(r'(CTA\.?\s*CTE\s*BN\s*N\.?\s*\d+)', obs, re.IGNORECASE)
        if match_cta:
            cta = match_cta.group(1).upper().replace(' ', '')
            cta = re.sub(r'CTA\.?CTE', 'CTA.CTE ', cta)
            cta = re.sub(r'BNN\.?', 'BN N.', cta)
            # Buscar prefijo de observación
            match_prefijo = re.search(r'(OPERACI[OÓ]N\s+SUJETA\s+(?:AL\s+SPOD|DEL\s+PODER))', obs, re.IGNORECASE)
            if match_prefijo:
                factura["observacion"] = match_prefijo.group(1).upper().replace('Ó', 'Ó') + " " + cta
            else:
                factura["observacion"] = "OPERACIÓN SUJETA AL SPOD " + cta
        else:
            factura["observacion"] = obs
    
    # =========================================================================
    # SECCIÓN 3: LÍNEAS DE FACTURA
    # =========================================================================
    
    cantidad = 1.0
    valor_unitario = 0.0
    descripcion = ""
    
    # Buscar patrón: cantidad UNIDAD descripción valor
    match = re.search(r'(\d+\.?\d*)\s*UNIDAD[:\s]*(.+?)\s+(\d{3,}\.00)', texto, re.IGNORECASE)
    if match:
        cantidad = float(match.group(1))
        valor_unitario = float(match.group(3))
    
    # Buscar descripción específica
    match_desc = re.search(r'UNIDAD[:\s]*(\d{2}-\d{2}-\d{4}-\d+\s+.+?)\s+\d{4}\.00', texto, re.IGNORECASE)
    if match_desc:
        descripcion = match_desc.group(1).strip()
    
    # Buscar parte PENDIENTE
    match_pendiente = re.search(r'PENDIENTE\s+([A-Z][A-Za-z\s]+?)(?=Valor|Sub|$)', texto, re.IGNORECASE)
    if match_pendiente:
        parte = match_pendiente.group(1).strip()
        parte = re.sub(r'\s+', ' ', parte)
        if descripcion:
            descripcion = descripcion + " PENDIENTE " + parte
        else:
            descripcion = "PENDIENTE " + parte
    
    factura["lineaFactura"] = [{
        "cantidad": float(cantidad),
        "unidadMedida": "UNIDAD",
        "descripcion": descripcion,
        "valorUnitario": float(valor_unitario)
    }]
    
    # =========================================================================
    # SECCIÓN 4: TOTALES
    # =========================================================================
    
    # Extraer totales del texto
    # Valor de Venta de Operaciones Gratuitas
    match = re.search(r'Gratuitas[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["ventaGratuita"] = limpiar_numero(match.group(1))
    
    # Sub Total Ventas
    match = re.search(r'Sub\s*Total\s*Ventas?[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["subtotalVenta"] = limpiar_numero(match.group(1))
    
    # Anticipos
    match = re.search(r'Anticipos?[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["anticipo"] = limpiar_numero(match.group(1))
    
    # Descuentos
    match = re.search(r'Descuentos?[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["descuento"] = limpiar_numero(match.group(1))
    
    # Valor Venta
    match = re.search(r'Valor\s+Venta[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["valorVenta"] = limpiar_numero(match.group(1))
    
    # ISC
    match = re.search(r'ISC[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["isc"] = limpiar_numero(match.group(1))
    
    # IGV
    match = re.search(r'IGV[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["igv"] = limpiar_numero(match.group(1))
    
    # Otros Cargos
    match = re.search(r'Otros\s*Cargos[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["otrosCargos"] = limpiar_numero(match.group(1))
    
    # Otros Tributos
    match = re.search(r'Otros\s*Tributos[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["otrosTributos"] = limpiar_numero(match.group(1))
    
    # Monto de Redondeo
    match = re.search(r'(?:Monto\s*de\s*)?[Rr]edondeo[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["montoRedondeo"] = limpiar_numero(match.group(1))
    
    # Importe Total
    match = re.search(r'Importe\s+Total[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["importeTotal"] = limpiar_numero(match.group(1))
    
    # Descripción Importe Total (SON:...)
    match = re.search(r'SON[:\s]*(.+?)(?=ISC|IGV|Otros|SOLES|$)', texto, re.IGNORECASE)
    if match:
        desc_total = match.group(1).strip()
        # Limpiar basura del OCR
        desc_total = re.sub(r'\s*\d+:\s*[\d\.]+\s*', ' ', desc_total)
        desc_total = re.sub(r'\s*sc\s*\d+\s*', ' ', desc_total, flags=re.IGNORECASE)
        desc_total = re.sub(r'\s+', ' ', desc_total).strip()
        # Agregar "SOLES" al final si no está
        if not desc_total.endswith('SOLES'):
            desc_total = desc_total + " SOLES"
        factura["descripcionImporteTotal"] = desc_total
    
    # =========================================================================
    # SECCIÓN 5: CUOTAS
    # =========================================================================
    
    # Buscar cuotas en formato: N fecha monto
    cuotas_encontradas = []
    patron_cuota = r'(\d{2}/\d{2}/\d{4})\s+([\d,]+\.\d{2})'
    
    for match in re.finditer(patron_cuota, texto_raw):
        fecha = match.group(1)
        monto = limpiar_numero(match.group(2))
        if monto > 100 and fecha != factura["fechaEmision"]:
            cuotas_encontradas.append((fecha, monto))
    
    for i, (fecha, monto) in enumerate(cuotas_encontradas):
        factura["cuotas"].append({
            "numero": i + 1,
            "fechaVencimiento": fecha,
            "monto": float(monto)
        })
    
    factura["totalCuota"] = len(factura["cuotas"])
    
    # Monto neto pendiente de pago
    match = re.search(r'pendiente\s*(?:de\s*)?pago[:\s]*[S5]?/?\.?\s*([\d,]+\.?\d*)', texto, re.IGNORECASE)
    if match:
        factura["montoNetoPendientePago"] = limpiar_numero(match.group(1))
    else:
        # Calcular como suma de cuotas
        factura["montoNetoPendientePago"] = sum(c["monto"] for c in factura["cuotas"])
    
    # =========================================================================
    # RETORNAR RESULTADO
    # =========================================================================
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
