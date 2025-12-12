import pdfplumber
import re
import os

# Importar catálogos SUNAT para conversión de códigos
from catalogos_sunat import convertir_unidad_medida

# --- FUNCIONES DE LIMPIEZA INTERNAS ---
def limpiar_moneda(valor):
    if not valor: return 0.00
    return float(valor.replace('S/', '').replace(',', '').strip())

def limpiar_texto(valor):
    if not valor: return ""
    texto = valor.replace('\n', ' ')
    etiquetas = [
        "Señor(es) :", "Dirección del Receptor de la factura :", 
        "Dirección del Cliente :", "Observación :", "SON:", 
        "Tipo de Moneda : SOLES", "Tipo de Moneda :", 
        "RUC:", "RUC :" 
    ]
    for tag in etiquetas:
        texto = texto.replace(tag, "")
    return re.sub(r'\s+', ' ', texto).strip()

def cortar_basura(texto, texto_referencia=None):
    if not texto: return ""
    if texto_referencia:
        adn = texto_referencia[:10]
        if adn and adn in texto:
            return texto.split(adn)[0].strip()
            
    match_ubicacion = re.search(r'(LIMA\s+LIMA|LIMA\s+-\s+LIMA|CALLAO|AREQUIPA|TRUJILLO|CUSCO)', texto)
    
    if match_ubicacion:
        parte_corte = texto[match_ubicacion.end():] 
        match_inicio_basura = re.search(r'\s+(AV\.|CALLE|JR\.|MZA\.|LOTE|LT\.|URB\.)', parte_corte)
        if match_inicio_basura:
            corte_index = match_ubicacion.end() + match_inicio_basura.start()
            return texto[:corte_index].strip()
    return texto

# --- FUNCIÓN PRINCIPAL (LA QUE LLAMARÁ LA API) ---
def procesar_factura_pdf(ruta_archivo):
    """
    Recibe la ruta de un PDF y retorna un diccionario (JSON) con los datos.
    """
    if not os.path.exists(ruta_archivo):
        return {"validacion": ["El archivo no existe"]}

    try:
        with pdfplumber.open(ruta_archivo) as pdf:
            text = pdf.pages[0].extract_text()

            # --- A. DATOS FIJOS ---
            ruc_emisor_match = re.search(r'RUC:\s*(10\d{9})', text)
            ruc_receptor_match = re.search(r'RUC\s*[:\s]*\s*(20\d{9})', text)
            folio_match = re.search(r'(E\d{3}-\d+)', text)
            fecha_match = re.search(r'Fecha de Emisión\s*:\s*(\d{2}/\d{2}/\d{4})', text)

            # --- B. GEOLOCALIZACIÓN ---
            geo_match = re.search(r'([A-Z\s]+)\s+-\s+([A-Z\s]+)\s+-\s+([A-Z\s]+)(?=\s)', text)
            if geo_match:
                distrito, provincia, departamento = geo_match.group(1).strip(), geo_match.group(2).strip(), geo_match.group(3).strip()
            else:
                distrito, provincia, departamento = "ATE", "LIMA", "LIMA"

            # --- C. DIRECCIONES ---
            dir_emisor_blob = re.search(r'RUC:\s*10\d{9}\s+(.+?)\s+E\d{3}-\d+', text, re.DOTALL)
            dir_emisor = limpiar_texto(dir_emisor_blob.group(1)) if dir_emisor_blob else ""

            # Fiscal (Pieza A)
            match_fiscal = re.search(r'RUC\s*[:\s]*\s*20\d{9}\s+(.+?)(?=Dirección del Receptor)', text, re.DOTALL)
            pieza_fiscal = limpiar_texto(match_fiscal.group(1)) if match_fiscal else ""

            # Entrega (Pieza B)
            match_entrega = re.search(r'Dirección del Receptor de la factura\s*[:\s]*(.+?)(?=Dirección del Cliente)', text, re.DOTALL)
            pieza_entrega_sucia = limpiar_texto(match_entrega.group(1)) if match_entrega else ""
            
            # Limpieza Guillotina
            pieza_entrega = cortar_basura(pieza_entrega_sucia, texto_referencia=pieza_fiscal)

            # Unificación
            if pieza_fiscal and pieza_entrega:
                direccion_maestra = f"{pieza_fiscal} : {pieza_entrega}"
            elif pieza_fiscal:
                direccion_maestra = pieza_fiscal
            else:
                direccion_maestra = pieza_entrega

            # --- D. OTROS DATOS ---
            nombre_blob = re.search(r'Forma de pago: Crédito\s*(.+?)\s*RUC', text, re.DOTALL)
            
            obs_blob = re.search(r'Tipo de Moneda\s*[:\s]*SOLES\s*(.+?)\s*Cantidad', text, re.DOTALL)
            texto_obs = limpiar_texto(obs_blob.group(1)) if obs_blob else ""
            obs_final = f"OPERACIÓN SUJETA AL SPOD {texto_obs}" if "CTA.CTE" in texto_obs and "OPERACIÓN SUJETA" not in texto_obs else texto_obs

            desc_son_match = re.search(r'SON:\s*(.+?)\s*ISC', text, re.DOTALL)

            # --- E. MONTOS ---
            match_gratuita = re.search(r'Operaciones Gratuitas\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_subtotal = re.search(r'Sub Total Ventas\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_anticipo = re.search(r'Anticipos\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_descuento = re.search(r'Descuentos\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_valor_venta = re.search(r'Valor Venta\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_isc = re.search(r'ISC\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_igv = re.search(r'IGV\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_otros_cargos = re.search(r'Otros Cargos\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_otros_tributos = re.search(r'Otros Tributos\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_redondeo = re.search(r'Monto de redondeo\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_total = re.search(r'Importe Total\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)
            match_pendiente = re.search(r'pendiente de pago\s*[:\s]*S/\s*([\d,]+\.\d{2})', text)

            cuotas_raw = re.findall(r'(\d+)\s+(\d{2}/\d{2}/\d{4})\s+([\d,]+\.\d{2})', text)
            lista_cuotas = [{"numero": int(c[0]), "fechaVencimiento": c[1], "monto": limpiar_moneda(c[2])} for c in cuotas_raw]

            # --- F. LÍNEAS ---
            bloque_tabla = re.search(r'Cantidad\s+Unidad Medida\s+Descripción\s+Valor Unitario\s+(.+?)\s+Valor de Venta', text, re.DOTALL)
            contenido_tabla = bloque_tabla.group(1) if bloque_tabla else ""
            lineas_raw = re.findall(r'(\d+\.\d{2})\s+UNIDAD\s+(.+?)\s+([\d,]+\.\d{2})(.*)', contenido_tabla, re.DOTALL)
            
            lista_lineas = []
            if lineas_raw:
                for l in lineas_raw:
                    desc_completa = f"{l[1]} {l[3]}"
                    lista_lineas.append({
                        "cantidad": float(l[0]),
                        "unidadMedida": convertir_unidad_medida("NIU"),  # PDF impreso ya dice UNIDAD, usamos catálogo
                        "descripcion": limpiar_texto(desc_completa), 
                        "valorUnitario": limpiar_moneda(l[2])
                    })

            # --- G. EXTRAER RAZÓN SOCIAL EMISOR (DINÁMICO) ---
            # En PDFs SUNAT, la estructura es:
            # Línea 0: "FACTURA ELECTRONICA" o "BOLETA DE VENTA"
            # Línea 1: Razón Social del Emisor (nombre)
            # Línea 2: "RUC: XXXXXXXXXXX"
            # Línea 3: Dirección
            razon_emisor = ""
            lineas = text.split('\n')
            
            # ESTRATEGIA 1: El nombre está en la línea inmediatamente anterior a "RUC:"
            for i, linea in enumerate(lineas[:10]):
                if re.match(r'\s*RUC\s*:\s*\d{11}', linea, re.IGNORECASE):
                    # La línea anterior debe ser el nombre
                    if i > 0:
                        candidato = lineas[i-1].strip()
                        # Validar que parece un nombre (no dirección, no FACTURA)
                        if (candidato 
                            and "FACTURA" not in candidato 
                            and "BOLETA" not in candidato
                            and not re.match(r'^(CAL\.|AV\.|JR\.|MZA\.|CALLE)', candidato, re.IGNORECASE)
                            and len(candidato) > 5):
                            razon_emisor = candidato
                    break
            
            # ESTRATEGIA 2: Si falla, buscar patrón APELLIDO APELLIDO NOMBRE
            if not razon_emisor:
                match = re.search(r'^([A-ZÁÉÍÓÚÑ]+\s+[A-ZÁÉÍÓÚÑ]+\s+[A-ZÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ]+)?)$', text, re.MULTILINE)
                if match:
                    razon_emisor = match.group(1).strip()

            # --- CONSTRUCCIÓN JSON ---
            return {
                "factura": {
                    "razonSocialEmisor": razon_emisor,  # Ahora dinámico, no hardcodeado
                    "direccionEmisor": dir_emisor,
                    "departamento": departamento,
                    "provincia": provincia,
                    "distrito": distrito,
                    "rucEmisor": int(ruc_emisor_match.group(1)) if ruc_emisor_match else 0,
                    "numeroFactura": folio_match.group(1) if folio_match else "",
                    
                    "fechaEmision": fecha_match.group(1) if fecha_match else "",
                    "razonSocialReceptor": limpiar_texto(nombre_blob.group(1)) if nombre_blob else "",
                    "rucReceptor": int(ruc_receptor_match.group(1)) if ruc_receptor_match else 0,
                    
                    "direccionReceptorFactura": direccion_maestra, 
                    "direccionCliente": direccion_maestra,
                    
                    "fechaContable": fecha_match.group(1) if fecha_match else "",
                    "tipoMoneda": "SOLES",
                    "observacion": obs_final,
                    "formaPago": "Crédito",
                    
                    "lineaFactura": lista_lineas,
                    
                    "ventaGratuita": limpiar_moneda(match_gratuita.group(1)) if match_gratuita else 0.00,
                    "descripcionImporteTotal": limpiar_texto(desc_son_match.group(1)) + " SOLES" if desc_son_match else "",
                    "subtotalVenta": limpiar_moneda(match_subtotal.group(1)) if match_subtotal else 0.00,
                    "anticipo": limpiar_moneda(match_anticipo.group(1)) if match_anticipo else 0.00,
                    "descuento": limpiar_moneda(match_descuento.group(1)) if match_descuento else 0.00,
                    "valorVenta": limpiar_moneda(match_valor_venta.group(1)) if match_valor_venta else 0.00,
                    "isc": limpiar_moneda(match_isc.group(1)) if match_isc else 0.00,
                    "igv": limpiar_moneda(match_igv.group(1)) if match_igv else 0.00,
                    "otrosCargos": limpiar_moneda(match_otros_cargos.group(1)) if match_otros_cargos else 0.00,
                    "otrosTributos": limpiar_moneda(match_otros_tributos.group(1)) if match_otros_tributos else 0.00,
                    "montoRedondeo": limpiar_moneda(match_redondeo.group(1)) if match_redondeo else 0.00,
                    "importeTotal": limpiar_moneda(match_total.group(1)) if match_total else 0.00,
                    "montoNetoPendientePago": limpiar_moneda(match_pendiente.group(1)) if match_pendiente else 0.00,
                    
                    "totalCuota": len(lista_cuotas),
                    "cuotas": lista_cuotas
                },
                "validacion": []
            }

    except Exception as e:
        return {"validacion": [f"Error procesando PDF: {str(e)}"]}