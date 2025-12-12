# -*- coding: utf-8 -*-
"""Comparación PDF vs Imagen"""
from procesador_pdf_v2 import procesar_factura_pdf
from procesador_imagen_v8 import procesar_factura_img

pdf = procesar_factura_pdf('prueba1.pdf')['factura']
img = procesar_factura_img('prueba1.jpeg')['factura']

print('=' * 100)
print('COMPARACION FINAL: PDF vs IMAGEN (v8)')
print('=' * 100)

campos = [
    'razonSocialEmisor', 'direccionEmisor', 'distrito', 'provincia', 'departamento',
    'rucEmisor', 'numeroFactura', 'fechaEmision', 'razonSocialReceptor', 'rucReceptor',
    'tipoMoneda', 'formaPago', 'valorVenta', 'igv', 'importeTotal', 
    'montoNetoPendientePago', 'totalCuota'
]

ok_count = 0
for c in campos:
    vp = str(pdf.get(c, ''))[:35]
    vi = str(img.get(c, ''))[:35]
    ok = 'SI' if str(pdf.get(c)) == str(img.get(c)) else 'NO'
    if ok == 'SI': ok_count += 1
    print(f'{c:25} | {vp:35} | {vi:35} | {ok}')

print()
cuotas_pdf = pdf.get('cuotas', [])
cuotas_img = img.get('cuotas', [])
print(f'CUOTAS: PDF tiene {len(cuotas_pdf)}, IMG tiene {len(cuotas_img)}')

for i in range(max(len(cuotas_pdf), len(cuotas_img))):
    cp = cuotas_pdf[i] if i < len(cuotas_pdf) else {}
    ci = cuotas_img[i] if i < len(cuotas_img) else {}
    fp, mp = cp.get('fechaVencimiento', '-'), cp.get('monto', 0)
    fi, mi = ci.get('fechaVencimiento', '-'), ci.get('monto', 0)
    ok = 'SI' if fp == fi and mp == mi else 'NO'
    print(f'  Cuota {i+1}: PDF({fp}, {mp}) vs IMG({fi}, {mi}) = {ok}')

print()
print(f'RESUMEN: {ok_count}/{len(campos)} campos principales coinciden')
