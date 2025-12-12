# -*- coding: utf-8 -*-
import json

def comparar_jsons(pdf_file, img_file, nombre):
    with open(pdf_file, 'r', encoding='utf-8') as f:
        pdf = json.load(f)
    with open(img_file, 'r', encoding='utf-8') as f:
        img = json.load(f)
    
    # El PDF tiene estructura anidada en 'factura', la imagen es plana
    if 'factura' in pdf:
        pdf = pdf['factura']
    
    print('='*90)
    print(f'ANALISIS DETALLADO: {nombre}')
    print('='*90)
    print(f"{'CAMPO':<35} | {'PDF':<25} | {'IMAGEN':<25} | MATCH")
    print('-'*90)
    
    coincidencias = 0
    diferencias = 0
    campos_comparados = 0
    detalles_diferencias = []
    
    # Mapeo de campos PDF -> Imagen
    mapeo = {
        'rucEmisor': 'rucEmisor',
        'numeroFactura': 'numeroFactura',
        'razonSocialEmisor': 'razonSocialEmisor',
        'direccionEmisor': 'direccionEmisor',
        'rucReceptor': 'rucReceptor',
        'razonSocialReceptor': 'razonSocialReceptor',
        'fechaEmision': 'fechaEmision',
        'tipoMoneda': 'tipoMoneda',
        'formaPago': 'formaPago',
        'observacion': 'observacion',
        'valorVenta': 'valorVenta',
        'igv': 'igv',
        'importeTotal': 'importeTotal',
        'ventaGratuita': 'operacionesGratuitas',
        'montoNetoPendientePago': 'montoPendiente',
        'totalCuota': 'totalCuotas',
    }
    
    for campo_pdf, campo_img in mapeo.items():
        val_pdf = pdf.get(campo_pdf, 'N/A')
        val_img = img.get(campo_img, 'N/A')
        
        # Normalizar para comparacion
        val_pdf_str = str(val_pdf).strip().upper() if val_pdf else ''
        val_img_str = str(val_img).strip().upper() if val_img else ''
        
        # Comparar numeros con tolerancia
        try:
            if isinstance(val_pdf, (int, float)) and isinstance(val_img, (int, float)):
                match = abs(float(val_pdf) - float(val_img)) < 0.01
            else:
                match = val_pdf_str == val_img_str
        except:
            match = val_pdf_str == val_img_str
        
        campos_comparados += 1
        if match:
            coincidencias += 1
            estado = 'OK'
        else:
            diferencias += 1
            estado = 'DIFERENTE'
            detalles_diferencias.append((campo_pdf, val_pdf, val_img))
        
        # Truncar valores largos
        val_pdf_show = str(val_pdf)[:23] if len(str(val_pdf)) > 23 else str(val_pdf)
        val_img_show = str(val_img)[:23] if len(str(val_img)) > 23 else str(val_img)
        
        print(f"{campo_pdf:<35} | {val_pdf_show:<25} | {val_img_show:<25} | {estado}")
    
    # Comparar cuotas
    print('-'*90)
    print('CUOTAS:')
    cuotas_pdf = pdf.get('cuotas', [])
    cuotas_img = img.get('cuotas', [])
    
    print(f'  Total cuotas PDF: {len(cuotas_pdf)}')
    print(f'  Total cuotas IMG: {len(cuotas_img)}')
    
    for i, c in enumerate(cuotas_pdf):
        fecha_pdf = c.get('fechaVencimiento', c.get('fechaCuota', ''))
        monto_pdf = c.get('monto', c.get('montoCuota', 0))
        
        if i < len(cuotas_img):
            fecha_img = cuotas_img[i].get('fechaCuota', '')
            monto_img = cuotas_img[i].get('montoCuota', 0)
            match_fecha = fecha_pdf == fecha_img
            match_monto = abs(monto_pdf - monto_img) < 0.01
            
            estado_cuota = "OK" if match_fecha and match_monto else "DIFERENTE"
            print(f'  Cuota {i+1}: PDF({fecha_pdf}, {monto_pdf}) vs IMG({fecha_img}, {monto_img}) = {estado_cuota}')
            
            if match_fecha and match_monto:
                coincidencias += 2
            else:
                diferencias += 2
                if not match_fecha:
                    detalles_diferencias.append((f'cuota{i+1}_fecha', fecha_pdf, fecha_img))
                if not match_monto:
                    detalles_diferencias.append((f'cuota{i+1}_monto', monto_pdf, monto_img))
            campos_comparados += 2
        else:
            print(f'  Cuota {i+1}: PDF({fecha_pdf}, {monto_pdf}) vs IMG(NO EXISTE) = FALTA EN IMG')
            diferencias += 2
            campos_comparados += 2
    
    # Cuotas extra en imagen
    for i in range(len(cuotas_pdf), len(cuotas_img)):
        c = cuotas_img[i]
        print(f'  Cuota {i+1}: PDF(NO EXISTE) vs IMG({c["fechaCuota"]}, {c["montoCuota"]}) = EXTRA en IMG (editada)')
    
    # Lineas de factura
    print('-'*90)
    print('LINEAS FACTURA:')
    lineas_pdf = pdf.get('lineaFactura', [])
    lineas_img = img.get('lineasFactura', [])
    
    if lineas_pdf and lineas_img:
        l_pdf = lineas_pdf[0]
        l_img = lineas_img[0]
        
        for campo in ['cantidad', 'valorUnitario']:
            v_pdf = l_pdf.get(campo, 0)
            v_img = l_img.get(campo, 0)
            match = abs(float(v_pdf) - float(v_img)) < 0.01
            estado_linea = "OK" if match else "DIFERENTE"
            print(f'  {campo}: PDF({v_pdf}) vs IMG({v_img}) = {estado_linea}')
            campos_comparados += 1
            if match:
                coincidencias += 1
            else:
                diferencias += 1
                detalles_diferencias.append((f'linea_{campo}', v_pdf, v_img))
    
    print('='*90)
    pct = 100*coincidencias/campos_comparados if campos_comparados > 0 else 0
    print(f'RESUMEN: {coincidencias}/{campos_comparados} campos coinciden ({pct:.1f}%)')
    print(f'         {diferencias} diferencias encontradas')
    
    if detalles_diferencias:
        print()
        print('DIFERENCIAS DETECTADAS:')
        for campo, v_pdf, v_img in detalles_diferencias:
            print(f'  - {campo}:')
            print(f'      PDF: {v_pdf}')
            print(f'      IMG: {v_img}')
    
    print('='*90)
    print()
    
    return coincidencias, diferencias, campos_comparados

if __name__ == "__main__":
    # Comparar prueba1
    c1, d1, t1 = comparar_jsons('resultado_pdf1.json', 'resultado_img1.json', 'PRUEBA1 (PDF vs JPEG)')

    # Comparar prueba2  
    c2, d2, t2 = comparar_jsons('resultado_pdf2.json', 'resultado_img2.json', 'PRUEBA2 (PDF vs JPEG)')

    print()
    print('='*90)
    print('RESUMEN FINAL')
    print('='*90)
    pct1 = 100*c1/t1 if t1 > 0 else 0
    pct2 = 100*c2/t2 if t2 > 0 else 0
    print(f'PRUEBA1: {c1}/{t1} campos coinciden ({pct1:.1f}%) - {d1} diferencias')
    print(f'PRUEBA2: {c2}/{t2} campos coinciden ({pct2:.1f}%) - {d2} diferencias')
    print('='*90)
