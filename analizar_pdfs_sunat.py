"""
Script para extraer y analizar los PDFs de documentación SUNAT
Buscando catálogos de unidades de medida y otros datos importantes
"""

import pdfplumber
import re

print("=" * 100)
print("ANÁLISIS DE DOCUMENTACIÓN SUNAT")
print("=" * 100)

# 1. Analizar la Guía XML
print("\n📄 ANALIZANDO: guia+xml+factura+version 2-1+1+0.pdf")
print("-" * 100)

try:
    with pdfplumber.open("guia+xml+factura+version 2-1+1+0 (2)_0 (2) (1).pdf") as pdf:
        print(f"Total de páginas: {len(pdf.pages)}")
        
        # Buscar en todas las páginas palabras clave
        keywords = ["NIU", "unidad", "medida", "catálogo", "catalogo", "código", "codigo"]
        
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                # Buscar si contiene información de unidades
                text_lower = text.lower()
                if any(kw.lower() in text_lower for kw in ["niu", "unidad medida", "catálogo", "catalogo"]):
                    print(f"\n🔍 Página {i+1} - Posible información de unidades:")
                    print("-" * 50)
                    # Extraer solo las líneas relevantes
                    lines = text.split('\n')
                    for line in lines:
                        if any(kw.lower() in line.lower() for kw in keywords):
                            print(f"  → {line.strip()}")
                            
except Exception as e:
    print(f"Error: {e}")

# 2. Analizar Anexos
print("\n\n📄 ANALIZANDO: anexosI-II-III-IV-318-2017.pdf")
print("-" * 100)

try:
    with pdfplumber.open("anexosI-II-III-IV-318-2017.pdf") as pdf:
        print(f"Total de páginas: {len(pdf.pages)}")
        
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                text_lower = text.lower()
                if any(kw.lower() in text_lower for kw in ["niu", "unidad", "medida"]):
                    print(f"\n🔍 Página {i+1} - Posible información:")
                    print("-" * 50)
                    lines = text.split('\n')
                    for line in lines:
                        if any(kw.lower() in line.lower() for kw in ["niu", "unidad", "medida", "código"]):
                            print(f"  → {line.strip()}")
                            
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 100)
