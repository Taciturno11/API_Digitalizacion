from fastapi import FastAPI, UploadFile, File, HTTPException
import shutil
import os
import uuid

# --- IMPORTAMOS LOS MOTORES ---
from procesador_pdf import procesar_factura_pdf
from procesador_xml import procesar_factura_xml
from procesador_imagen import procesar_factura_img

app = FastAPI(title="API Digitalización Facturas")

@app.get("/")
def home():
    return {"mensaje": "¡La API de Facturas está funcionando correctamente! Ve a /docs para usarla."}

@app.post("/procesar")
async def procesar_documento(file: UploadFile = File(...)):
    """
    Endpoint que recibe un archivo (PDF, XML, IMG), detecta el tipo
    y devuelve el JSON estructurado.
    """
    
    # 1. Validar extensión del archivo
    filename = file.filename.lower()
    extension = filename.split(".")[-1]
    
    if extension not in ["pdf", "xml", "png", "jpg", "jpeg"]:
        return {"validacion": ["Formato de archivo no soportado. Use PDF, XML o Imágenes."]}

    # 2. Guardar el archivo temporalmente
    nombre_temporal = f"temp_{uuid.uuid4()}.{extension}"
    
    try:
        with open(nombre_temporal, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # 3. ENRUTADOR (El Cerebro)
        resultado = {}
        
        if extension == "pdf":
            print(f"📄 Procesando PDF: {filename}")
            resultado = procesar_factura_pdf(nombre_temporal)
            
        elif extension == "xml":
            print(f"🧩 Procesando XML: {filename}")
            # AQUI ESTA EL CAMBIO: Llamamos al motor XML real
            resultado = procesar_factura_xml(nombre_temporal)
            
        elif extension in ["png", "jpg", "jpeg"]:
            print(f"🖼️ Procesando Imagen: {filename}")
            resultado = procesar_factura_img(nombre_temporal)

        return resultado

    except Exception as e:
        return {"validacion": [f"Error interno del servidor: {str(e)}"]}
        
    finally:
        # 4. Limpieza: Borrar el archivo temporal siempre
        if os.path.exists(nombre_temporal):
            try:
                os.remove(nombre_temporal)
            except:
                pass

# Para correrlo: uvicorn api:app --reload