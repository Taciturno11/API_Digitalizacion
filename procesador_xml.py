import xml.etree.ElementTree as ET
import json
import os
import re

# Importar catálogos SUNAT para conversión de códigos
from catalogos_sunat import convertir_unidad_medida, convertir_moneda

# --- MAPA DE NAMESPACES (Clave para que Python entienda el XML) ---
ns = {
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'ds': 'http://www.w3.org/2000/09/xmldsig#',
    'ext': 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'
}

def obtener_valor(nodo_raiz, ruta, tipo=str):
    """Ayuda a extraer valor de una etiqueta XML de forma segura"""
    try:
        nodo = nodo_raiz.find(ruta, ns)
        if nodo is not None and nodo.text:
            if tipo == float:
                return float(nodo.text)
            return nodo.text.strip()
    except:
        pass
    
    # Valores por defecto si falla
    return 0.00 if tipo == float else ""

def procesar_factura_xml(ruta_archivo):
    """
    Lee un XML UBL 2.1 y retorna el JSON estandarizado.
    """
    if not os.path.exists(ruta_archivo):
        return {"validacion": ["El archivo no existe"]}

    try:
        tree = ET.parse(ruta_archivo)
        root = tree.getroot()

        # --- A. DATOS DE CABECERA ---
        # RUC y Razón Social Emisor
        emisor_nodo = root.find('cac:AccountingSupplierParty/cac:Party', ns)
        ruc_emisor = int(obtener_valor(emisor_nodo, 'cac:PartyIdentification/cbc:ID'))
        razon_emisor = obtener_valor(emisor_nodo, 'cac:PartyLegalEntity/cbc:RegistrationName')
        
        # Dirección Emisor (Construida)
        dir_nodo = emisor_nodo.find('cac:PartyLegalEntity/cac:RegistrationAddress', ns)
        calle = obtener_valor(dir_nodo, 'cac:AddressLine/cbc:Line')
        dist = obtener_valor(dir_nodo, 'cbc:District')
        prov = obtener_valor(dir_nodo, 'cbc:CityName')
        dep = obtener_valor(dir_nodo, 'cbc:CountrySubentity')
        direccion_emisor = f"{calle} {dist} - {prov} - {dep}".strip()

        # Datos Generales
        folio = obtener_valor(root, 'cbc:ID')
        fecha_emision = obtener_valor(root, 'cbc:IssueDate')
        tipo_moneda = obtener_valor(root, 'cbc:DocumentCurrencyCode')

        # --- B. DATOS DEL RECEPTOR ---
        receptor_nodo = root.find('cac:AccountingCustomerParty/cac:Party', ns)
        ruc_receptor = int(obtener_valor(receptor_nodo, 'cac:PartyIdentification/cbc:ID'))
        razon_receptor = obtener_valor(receptor_nodo, 'cac:PartyLegalEntity/cbc:RegistrationName')
        
        # Dirección Cliente (Tomamos la línea completa que viene en el XML)
        dir_cliente_xml = obtener_valor(receptor_nodo, 'cac:PartyLegalEntity/cac:RegistrationAddress/cac:AddressLine/cbc:Line')
        
        # Para mantener consistencia con tu lógica PDF:
        direccion_maestra = dir_cliente_xml 

        # --- C. MONTOS Y TOTALES ---
        # Importe Total
        importe_total = obtener_valor(root, 'cac:LegalMonetaryTotal/cbc:PayableAmount', float)
        
        # Impuestos (IGV)
        # Buscamos en los totales de impuestos donde el código sea VAT (IGV)
        igv = 0.00
        tax_totals = root.findall('cac:TaxTotal', ns)
        for tax in tax_totals:
            subtotal = tax.find('cac:TaxSubtotal', ns)
            if subtotal is not None:
                tax_id = obtener_valor(subtotal, 'cac:TaxCategory/cac:TaxScheme/cbc:ID')
                if tax_id == '1000': # Código SUNAT para IGV
                    igv = obtener_valor(tax, 'cbc:TaxAmount', float)

        # Totales (Gravada, etc)
        subtotal_venta = obtener_valor(root, 'cac:LegalMonetaryTotal/cbc:LineExtensionAmount', float)
        valor_venta = subtotal_venta # Usualmente coinciden en la base
        
        # Otros cargos/Descuentos (Si existieran etiquetas específicas, por ahora 0.00 base)
        descuento = obtener_valor(root, 'cac:LegalMonetaryTotal/cbc:AllowanceTotalAmount', float)
        otros_cargos = obtener_valor(root, 'cac:LegalMonetaryTotal/cbc:ChargeTotalAmount', float)

        # Monto Letras (Son: ...)
        descripcion_importe_total = ""
        notas = root.findall('cbc:Note', ns)
        for nota in notas:
            if nota.text and "SON:" in nota.text:
                # Quitar prefijo "SON:" y espacios extra
                texto_son = nota.text.strip()
                texto_son = re.sub(r'^SON:\s*', '', texto_son, flags=re.IGNORECASE)
                # Limpiar espacios múltiples
                descripcion_importe_total = re.sub(r'\s+', ' ', texto_son).strip()
                break

        # Observaciones
        observaciones = []
        for nota in notas:
            if "SON:" not in nota.text: # Todo lo que no sea el monto en letras es obs
                observaciones.append(nota.text.strip())
        obs_final = " ".join(observaciones)

        # --- D. CUOTAS Y FORMA DE PAGO ---
        payment_terms = root.findall('cac:PaymentTerms', ns)
        lista_cuotas = []
        pendiente_pago = 0.00
        forma_pago = "Contado" # Por defecto

        for term in payment_terms:
            payment_id = obtener_valor(term, 'cbc:ID')
            means_id = obtener_valor(term, 'cbc:PaymentMeansID')
            amount = obtener_valor(term, 'cbc:Amount', float)
            
            if "FormaPago" in payment_id:
                if "Credito" in means_id:
                    forma_pago = "Crédito"
                    pendiente_pago = amount
                elif "Cuota" in means_id:
                    # Es una cuota
                    fecha_venc = obtener_valor(term, 'cbc:PaymentDueDate')
                    # Convertir fecha yyyy-mm-dd a dd/mm/yyyy para tu formato
                    if fecha_venc:
                        anio, mes, dia = fecha_venc.split('-')
                        fecha_venc_fmt = f"{dia}/{mes}/{anio}"
                    else:
                        fecha_venc_fmt = ""
                    
                    # Extraer número de cuota (ej: Cuota001 -> 1)
                    num_cuota = int(re.search(r'\d+', means_id).group()) if re.search(r'\d+', means_id) else len(lista_cuotas) + 1

                    lista_cuotas.append({
                        "numero": num_cuota,
                        "fechaVencimiento": fecha_venc_fmt,
                        "monto": amount
                    })

        # --- E. LÍNEAS DE FACTURA ---
        lista_lineas = []
        invoice_lines = root.findall('cac:InvoiceLine', ns)
        
        for line in invoice_lines:
            cantidad = obtener_valor(line, 'cbc:InvoicedQuantity', float)
            unidad_codigo = line.find('cbc:InvoicedQuantity', ns).get('unitCode')
            descripcion = obtener_valor(line, 'cac:Item/cbc:Description')
            valor_unitario = obtener_valor(line, 'cac:Price/cbc:PriceAmount', float)
            
            # Convertir código de unidad (NIU) a nombre legible (UNIDAD) usando Catálogo N°3
            unidad_nombre = convertir_unidad_medida(unidad_codigo)
            
            lista_lineas.append({
                "cantidad": cantidad,
                "unidadMedida": unidad_nombre,  # Ya convertido a nombre legible
                "descripcion": descripcion,
                "valorUnitario": valor_unitario
            })

        # --- CONSTRUCCIÓN DEL JSON FINAL ---
        resultado = {
            "factura": {
                "razonSocialEmisor": razon_emisor,
                "direccionEmisor": direccion_emisor,
                "departamento": dep,
                "provincia": prov,
                "distrito": dist,
                "rucEmisor": ruc_emisor,
                "numeroFactura": folio,
                
                "fechaEmision": fecha_emision, # XML ya viene en yyyy-mm-dd usualmente
                "fechaContable": fecha_emision,
                
                "razonSocialReceptor": razon_receptor,
                "rucReceptor": ruc_receptor,
                "direccionReceptorFactura": direccion_maestra,
                "direccionCliente": direccion_maestra,
                
                "tipoMoneda": convertir_moneda(tipo_moneda),  # PEN -> SOLES usando Catálogo N°2
                "observacion": obs_final,
                "formaPago": forma_pago,
                
                "lineaFactura": lista_lineas,
                
                "ventaGratuita": 0.00, # Buscar cac:PricingReference si fuera necesario
                "descripcionImporteTotal": descripcion_importe_total,
                "subtotalVenta": subtotal_venta,
                "anticipo": 0.00,
                "descuento": descuento,
                "valorVenta": valor_venta,
                "isc": 0.00, # Implementar si hay TaxCategory 'ISC'
                "igv": igv,
                "otrosCargos": otros_cargos,
                "otrosTributos": 0.00,
                "montoRedondeo": 0.00,
                "importeTotal": importe_total,
                
                "montoNetoPendientePago": pendiente_pago,
                "totalCuota": len(lista_cuotas),
                "cuotas": lista_cuotas
            },
            "validacion": []
        }
        
        return resultado

    except Exception as e:
        return {"validacion": [f"Error procesando XML: {str(e)}"]}