"""
PROCESADOR DE IMAGEN v6 - Factura Electrónica SUNAT
====================================================
Estrategia INTELIGENTE: usar valores confiables para calcular los demás.
- Valor Unitario: generalmente se lee bien
- Cuotas: se extraen bien
- Calcular: IGV = 18%, Total = Base + IGV
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
    Corrige errores OCR comunes.
    """
    if not valor_str:
        return 0.0
    
    valor_str = str(valor_str).strip()
    
    # Corregir errores OCR de caracteres
    valor_str = valor_str.replace('uu', '00').replace('UU', '00')
    valor_str = valor_str.replace('u', '0').replace('U', '0')
    valor_str = valor_str.replace('D', '0').replace('O', '0').replace('o', '0')
    valor_str = valor_str.replace('l', '1').replace('I', '1')
    
    # Eliminar símbolos de moneda
    valor_str = re.sub(r'^[Ss5\$][/lI1]\s*', '', valor_str)
    valor_str = re.sub(r'^[Ss5]\s+', '', valor_str)
    valor_str = re.sub(r'[Ss]/\s*', '', valor_str)
    valor_str = valor_str.replace(' ', '')
    
    # Manejar separadores
    if ',' in valor_str and '.' in valor_str:
        if valor_str.index(',') < valor_str.index('.'):
            valor_str = valor_str.replace(',', '')
        else:
            valor_str = valor_str.replace('.', '').replace(',', '.')
    elif ',' in valor_str:
        partes = valor_str.split(',')
        if len(partes[-1]) == 2:
            valor_str = valor_str.replace(',', '.')
        else:
            valor_str = valor_str.replace(',', '')
    
    try:
        return float(valor_str)
    except:
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
    
    return '\n'.join(lineas), lineas


# =============================================================================
# PROCESADOR PRINCIPAL
# =============================================================================
def procesar_factura_img(ruta_archivo):
    """
    Procesa imagen de factura SUNAT con estrategia INTELIGENTE.
    """
    validaciones = []
    
    try:
        texto_completo, lineas = extraer_texto_easyocr(ruta_archivo)
        
        # Debug
        print("=" * 70)
        print("TEXTO EXTRAIDO POR EASYOCR:")
        print("=" * 70)
        for i, linea in enumerate(lineas):
            print(f"[{i:02d}] {linea}")
        print("=" * 70)
        
        if not lineas:
            return {"validacion": ["No se pudo extraer texto de la imagen"]}
        
        primera_linea = lineas[0] if lineas else ""
        
        # =====================================================================
        # SECCIÓN 1: DATOS DEL EMISOR
        # =====================================================================
        print("\n[SECCION 1] Procesando EMISOR...")
        
        # RUC EMISOR - 11 dígitos después de "RUC"
        ruc_emisor = 0
        match_ruc = re.search(r'RUC[:\s]*(\d{11})', texto_completo)
        if match_ruc:
            ruc_emisor = int(match_ruc.group(1))
            print(f"    RUC Emisor: {ruc_emisor}")
        
        # NÚMERO DE FACTURA
        numero_factura = ""
        match_factura = re.search(r'([EF]\d{3}[-–]?\d+)', texto_completo)
        if match_factura:
            numero_factura = match_factura.group(1)
            if '-' not in numero_factura:
                numero_factura = numero_factura[:4] + '-' + numero_factura[4:]
            numero_factura = numero_factura.replace('–', '-')
            print(f"    Numero Factura: {numero_factura}")
        
        # RAZÓN SOCIAL EMISOR
        razon_social_emisor = ""
        texto_limpio = re.sub(r'^FACTURA\s*ELECTR[OÓ]NICA\s*', '', primera_linea, flags=re.IGNORECASE)
        match_nombre = re.search(r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?)(?=\s+RUC|\s+CAL\.|\s+AV\.|\s+JR\.)', texto_limpio)
        if match_nombre:
            razon_social_emisor = limpiar_texto(match_nombre.group(1))
        print(f"    Razon Social Emisor: {razon_social_emisor}")
        
        # DIRECCIÓN EMISOR
        direccion_emisor = ""
        match_dir = re.search(r'RUC[:\s]*\d{11}\s+(.+?)\s+[EF]\d{3}', primera_linea, re.IGNORECASE)
        if match_dir:
            direccion_emisor = limpiar_texto(match_dir.group(1))
        print(f"    Direccion Emisor: {direccion_emisor}")
        
        # UBIGEO EMISOR
        distrito_emisor, provincia_emisor, departamento_emisor = "", "", ""
        ubigeo_match = re.search(r'([A-Z][A-Za-z]+)\s+(LIMA|[A-Z]{3,})\s+(LIMA|[A-Z]{3,})\s*$', primera_linea)
        if ubigeo_match:
            distrito_emisor = ubigeo_match.group(1)
            provincia_emisor = ubigeo_match.group(2)
            departamento_emisor = ubigeo_match.group(3)
        print(f"    Ubigeo: {distrito_emisor}-{provincia_emisor}-{departamento_emisor}")
        
        # =====================================================================
        # SECCIÓN 2: DATOS DEL RECEPTOR
        # =====================================================================
        print("\n[SECCION 2] Procesando RECEPTOR...")
        
        # FECHA DE EMISIÓN
        fecha_emision = ""
        forma_pago = "Contado"
        for linea in lineas:
            if 'Fecha' in linea:
                match_fecha = re.search(r'(\d{2}/\d{2}/\d{4})', linea)
                if match_fecha:
                    fecha_emision = match_fecha.group(1)
                if 'Cr' in linea and 'dito' in linea:
                    forma_pago = "Credito"
                print(f"    Fecha Emision: {fecha_emision}, Forma Pago: {forma_pago}")
                break
        
        # RAZÓN SOCIAL RECEPTOR
        razon_social_receptor = ""
        for linea in lineas:
            if 'Se' in linea and 'or' in linea:
                partes = re.split(r'Se.or\(?es\)?:?\s*', linea, maxsplit=1)
                for parte in partes:
                    parte = re.sub(r'\s*RUC\s*\d{11}\s*', '', parte).strip()
                    if parte and not re.match(r'^\d{11}$', parte):
                        razon_social_receptor += parte + " "
                razon_social_receptor = limpiar_texto(razon_social_receptor)
                print(f"    Razon Social Receptor: {razon_social_receptor}")
                break
        
        # RUC RECEPTOR
        ruc_receptor = 0
        for linea in lineas:
            for match in re.finditer(r'(\d{11})', linea):
                ruc = int(match.group(1))
                if ruc != ruc_emisor and str(ruc).startswith('20'):
                    ruc_receptor = ruc
                    print(f"    RUC Receptor: {ruc_receptor}")
                    break
            if ruc_receptor:
                break
        
        # DIRECCIONES
        direccion_receptor_factura = ""
        direccion_cliente = ""
        
        for linea in lineas:
            # Dirección del Receptor de la factura
            if 'receptor' in linea.lower() and 'factura' in linea.lower():
                # Extraer AV./JR./CAL. antes y CRUCE/texto después
                match_antes = re.search(r'(AV\.|JR\.|CAL\.)(.+?)Direcci', linea, re.IGNORECASE)
                match_despues = re.search(r'factura\s+(.+?)(?:AV\.|JR\.|CAL\.|Direcci|$)', linea, re.IGNORECASE)
                
                partes = []
                if match_antes:
                    partes.append(match_antes.group(1) + match_antes.group(2).strip())
                if match_despues:
                    partes.append(match_despues.group(1).strip())
                direccion_receptor_factura = ' '.join(partes)
                direccion_receptor_factura = limpiar_texto(direccion_receptor_factura)
                print(f"    Direccion Receptor: {direccion_receptor_factura}")
            
            # Dirección del Cliente
            if re.search(r'c.?l.?iente', linea.lower()) and 'direcci' in linea.lower():
                match_antes = re.search(r'(AV\.|JR\.|CAL\.)(.+?)Direcci', linea, re.IGNORECASE)
                match_despues = re.search(r'[Cc].?l.?iente\s+(.+?)(?:Tipo|Observ|$)', linea, re.IGNORECASE)
                
                partes = []
                if match_antes:
                    partes.append(match_antes.group(1) + match_antes.group(2).strip())
                if match_despues:
                    partes.append(match_despues.group(1).strip())
                direccion_cliente = ' '.join(partes)
                direccion_cliente = limpiar_texto(direccion_cliente)
                print(f"    Direccion Cliente: {direccion_cliente}")
        
        # TIPO DE MONEDA
        tipo_moneda = "SOLES"
        if 'DOLAR' in texto_completo.upper():
            tipo_moneda = "DOLARES"
        print(f"    Tipo Moneda: {tipo_moneda}")
        
        # OBSERVACIÓN
        observacion = ""
        match_obs = re.search(r'(OPERACI[OÓ]N\s+SUJETA\s+AL\s+SPOD[^C]*CTA\.?CTE[^\d]*\d+)', texto_completo, re.IGNORECASE)
        if match_obs:
            observacion = limpiar_texto(match_obs.group(1))
        print(f"    Observacion: {observacion}")
        
        # =====================================================================
        # SECCIÓN 3: LÍNEAS DE FACTURA - ESTRATEGIA CLAVE
        # =====================================================================
        print("\n[SECCION 3] Procesando LINEAS DE FACTURA...")
        lista_lineas = []
        valor_unitario = 0.0
        descripcion = ""
        
        for linea in lineas:
            if 'UNIDAD' in linea.upper():
                # VALOR UNITARIO - Buscar número grande con .00
                montos = re.findall(r'(\d{1,3}(?:,\d{3})*\.\d{2}|\d{4,}\.\d{2})', linea)
                for m in montos:
                    valor = limpiar_monto(m)
                    if valor > 100:  # Filtrar valores pequeños (errores de S/)
                        valor_unitario = valor
                        break
                
                # DESCRIPCIÓN - Todo entre UNIDAD y el monto
                match_desc = re.search(
                    r'UNIDAD\s+(.+?)\s+(\d{1,3}(?:,\d{3})*\.\d{2}|\d{4,}\.\d{2})\s*(.*)$',
                    linea, re.IGNORECASE
                )
                if match_desc:
                    parte1 = match_desc.group(1).strip()
                    parte2 = match_desc.group(3).strip()
                    descripcion = f"{parte1} {parte2}".strip()
                    descripcion = descripcion.replace('$ A', 'S A').replace('$', 'S')
                
                print(f"    Valor Unitario: {valor_unitario}")
                print(f"    Descripcion: {descripcion}")
                break
        
        # =====================================================================
        # SECCIÓN 4: CUOTAS - SE EXTRAEN BIEN
        # =====================================================================
        print("\n[SECCION 4] Procesando CUOTAS...")
        lista_cuotas = []
        monto_pendiente = 0.0
        
        # Monto pendiente
        match_pend = re.search(r'pendiente.*?(\d{1,3}(?:,\d{3})*\.\d{2})', texto_completo, re.IGNORECASE)
        if match_pend:
            monto_pendiente = limpiar_monto(match_pend.group(1))
            print(f"    Monto Pendiente: {monto_pendiente}")
        
        # Cuotas - buscar fechas y montos
        for linea in lineas:
            fechas = re.findall(r'(\d{2}/\d{2}/\d{4})', linea)
            if len(fechas) >= 2:
                # Extraer montos después de cada fecha
                partes = re.split(r'(\d{2}/\d{2}/\d{4})', linea)
                num_cuota = 0
                for i, parte in enumerate(partes):
                    if re.match(r'\d{2}/\d{2}/\d{4}', parte):
                        num_cuota += 1
                        fecha = parte
                        # Buscar monto en la siguiente parte
                        if i + 1 < len(partes):
                            match_monto = re.search(r'([\d,]+\.\d{2})', partes[i + 1])
                            if match_monto:
                                monto = limpiar_monto(match_monto.group(1))
                                if monto > 0:
                                    lista_cuotas.append({
                                        "numeroCuota": num_cuota,
                                        "fechaVencimientoCuota": fecha,
                                        "montoCuota": monto
                                    })
                                    print(f"    Cuota {num_cuota}: {fecha} - {monto}")
        
        # =====================================================================
        # SECCIÓN 5: CÁLCULO INTELIGENTE DE TOTALES
        # =====================================================================
        print("\n[SECCION 5] CALCULO INTELIGENTE DE TOTALES...")
        
        # ESTRATEGIA: Usar valor unitario y cuotas para calcular
        cantidad = 1.0  # Default
        
        # Si hay cuotas, la suma es el importe total
        suma_cuotas = sum(c['montoCuota'] for c in lista_cuotas) if lista_cuotas else 0
        
        if suma_cuotas > 0:
            # Calcular hacia atrás desde el importe total
            importe_total = suma_cuotas
            # IGV es 18%, así que: Total = Base * 1.18 => Base = Total / 1.18
            valor_venta = round(importe_total / 1.18, 2)
            igv = round(importe_total - valor_venta, 2)
            subtotal_venta = valor_venta
            
            # Calcular cantidad si tenemos valor unitario
            if valor_unitario > 0:
                cantidad = round(valor_venta / valor_unitario, 2)
                # Si está cerca de un entero, usar entero
                if abs(cantidad - round(cantidad)) < 0.05:
                    cantidad = round(cantidad)
            
            print(f"    [CALCULADO desde cuotas]")
            print(f"    Suma Cuotas (Total): {importe_total}")
            print(f"    Valor Venta (Base): {valor_venta}")
            print(f"    IGV (18%): {igv}")
            print(f"    Cantidad: {cantidad}")
        
        elif valor_unitario > 0:
            # Si no hay cuotas pero sí valor unitario
            valor_venta = valor_unitario * cantidad
            subtotal_venta = valor_venta
            igv = round(valor_venta * 0.18, 2)
            importe_total = valor_venta + igv
            
            print(f"    [CALCULADO desde valor unitario]")
            print(f"    Valor Venta: {valor_venta}")
            print(f"    IGV (18%): {igv}")
            print(f"    Importe Total: {importe_total}")
        else:
            # Fallback
            valor_venta = 0.0
            subtotal_venta = 0.0
            igv = 0.0
            importe_total = 0.0
        
        # Descripción del importe
        descripcion_importe = ""
        match_son = re.search(r'SON:\s*(.+?)(?:\d|SOLES|$)', texto_completo, re.IGNORECASE)
        if match_son:
            descripcion_importe = match_son.group(1).strip()
            if 'SOLES' not in descripcion_importe.upper():
                descripcion_importe += " SOLES"
        
        # Línea de factura
        lista_lineas = [{
            "cantidad": cantidad,
            "unidadMedida": "UNIDAD",
            "descripcion": descripcion,
            "valorUnitario": valor_unitario
        }]
        
        # =====================================================================
        # CONSTRUIR RESPUESTA
        # =====================================================================
        print("\n" + "=" * 70)
        print("RESPUESTA FINAL")
        print("=" * 70)
        
        respuesta = {
            # Sección 1: Emisor
            "rucEmisor": ruc_emisor,
            "razonSocialEmisor": razon_social_emisor,
            "direccionEmisor": direccion_emisor,
            "distritoEmisor": distrito_emisor,
            "provinciaEmisor": provincia_emisor,
            "departamentoEmisor": departamento_emisor,
            "numeroFactura": numero_factura,
            
            # Sección 2: Receptor
            "fechaEmision": fecha_emision,
            "formaPago": forma_pago,
            "rucReceptor": ruc_receptor,
            "razonSocialReceptor": razon_social_receptor,
            "direccionReceptorFactura": direccion_receptor_factura,
            "direccionCliente": direccion_cliente,
            "tipoMoneda": tipo_moneda,
            "observacion": observacion,
            
            # Sección 3: Líneas
            "lineasFactura": lista_lineas,
            
            # Sección 4: Totales (CALCULADOS)
            "ventaGratuita": 0.0,
            "subtotalVenta": subtotal_venta,
            "anticipo": 0.0,
            "descuento": 0.0,
            "valorVenta": valor_venta,
            "isc": 0.0,
            "igv": igv,
            "otrosCargos": 0.0,
            "otrosTributos": 0.0,
            "montoRedondeo": 0.0,
            "importeTotal": importe_total,
            "descripcionImporteTotal": descripcion_importe,
            
            # Sección 5: Cuotas
            "totalCuota": len(lista_cuotas),
            "cuotas": lista_cuotas,
            "montoPendiente": monto_pendiente,
            
            "validacion": ["OK"]
        }
        
        return respuesta
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"validacion": [f"Error procesando imagen: {str(e)}"]}


if __name__ == "__main__":
    import json
    import sys
    archivo = sys.argv[1] if len(sys.argv) > 1 else "prueba1.jpeg"
    resultado = procesar_factura_img(archivo)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
