import os
import json
import ollama
from datetime import datetime
from pathlib import Path
from config import ASSISTANT_NAME, MODELO_CONVERSACION

REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")

def obtener_archivos_python(ruta_proyecto):
    """Obtiene lista de archivos .py en un proyecto."""
    archivos = []

    if not os.path.isdir(ruta_proyecto):
        return archivos

    for root, dirs, files in os.walk(ruta_proyecto):
        # Ignorar directorios comunes
        dirs[:] = [d for d in dirs if d not in ['.venv', 'venv', '__pycache__', '.git', '.pytest_cache', 'node_modules']]

        for file in files:
            if file.endswith('.py'):
                ruta_completa = os.path.join(root, file)
                archivos.append(ruta_completa)

    return archivos

def leer_codigo(ruta_archivo):
    """Lee el contenido de un archivo."""
    try:
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return None
    except Exception as e:
        return None

def contar_estadisticas(codigo):
    """Cuenta líneas, funciones, clases, etc."""
    lineas = codigo.split('\n')
    total_lineas = len(lineas)
    funciones = len([l for l in lineas if l.strip().startswith('def ')])
    clases = len([l for l in lineas if l.strip().startswith('class ')])
    comentarios = len([l for l in lineas if l.strip().startswith('#')])

    return {
        'total_lineas': total_lineas,
        'funciones': funciones,
        'clases': clases,
        'comentarios': comentarios
    }

def analizar_archivo(ruta_archivo, tipo_analisis="completo"):
    """Analiza un archivo específico usando LLM."""
    codigo = leer_codigo(ruta_archivo)

    if not codigo:
        return None

    estadisticas = contar_estadisticas(codigo)

    if tipo_analisis == "completo":
        prompt = f"""Analiza este código Python de forma profesional.

ARCHIVO: {os.path.basename(ruta_archivo)}
ESTADÍSTICAS: {estadisticas}

CÓDIGO:
```python
{codigo}
```

Proporciona un análisis estructurado:

1. **ERRORES Y BUGS**: Identifica errores, bugs lógicos o problemas.
2. **OPTIMIZACIÓN**: Cómo mejorar rendimiento y eficiencia.
3. **CALIDAD DE CÓDIGO**: Legibilidad, estructura, nombres, mejores prácticas.
4. **SEGURIDAD**: Vulnerabilidades potenciales.
5. **REFACTORING**: Sugerencias de mejora estructural.
6. **SCORE**: Calidad general del código (1-10).

Sé específico, menciona líneas cuando sea posible. Responde en español."""

    elif tipo_analisis == "errores":
        prompt = f"""Identifica TODOS los bugs y errores en este código:

```python
{codigo}
```

Sé muy específico, menciona líneas exactas. Responde en español."""

    elif tipo_analisis == "seguridad":
        prompt = f"""¿Qué vulnerabilidades de seguridad ves en este código?

```python
{codigo}
```

Identifica: inyecciones, validación insuficiente, gestión insegura de datos, etc.
Responde en español."""

    elif tipo_analisis == "optimizacion":
        prompt = f"""¿Cómo optimizar este código para mejor rendimiento?

```python
{codigo}
```

Sugerencias específicas, ejemplos si es posible. Responde en español."""

    else:  # calidad
        prompt = f"""¿Cómo mejorar la calidad y legibilidad de este código?

```python
{codigo}
```

Comenta sobre nombres, estructura, organización. Responde en español."""

    try:
        respuesta = ollama.chat(
            model=MODELO_CONVERSACION,
            messages=[
                {
                    "role": "system",
                    "content": "Eres un experto analizador de código Python. Proporciona análisis profundo y práctico."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        analisis = respuesta["message"]["content"]

        return {
            'archivo': ruta_archivo,
            'tipo_analisis': tipo_analisis,
            'estadisticas': estadisticas,
            'analisis': analisis,
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        return {'error': str(e)}

def analizar_proyecto(ruta_proyecto, tipo_analisis="completo"):
    """Analiza todos los archivos de un proyecto."""
    archivos = obtener_archivos_python(ruta_proyecto)

    if not archivos:
        return None

    resultados = []
    for archivo in archivos:
        print(f"Analizando: {archivo}")
        resultado = analizar_archivo(archivo, tipo_analisis)
        if resultado:
            resultados.append(resultado)

    return {
        'proyecto': ruta_proyecto,
        'total_archivos': len(archivos),
        'archivos_analizados': len(resultados),
        'tipo_analisis': tipo_analisis,
        'resultados': resultados,
        'timestamp': datetime.now().isoformat()
    }

def generar_reporte_markdown(analisis_resultado, tipo="archivo"):
    """Genera un reporte en formato Markdown."""
    if tipo == "archivo":
        nombre_archivo = os.path.basename(analisis_resultado['archivo'])
        contenido = f"""# Análisis de Código: {nombre_archivo}

**Fecha del análisis**: {analisis_resultado['timestamp']}
**Tipo de análisis**: {analisis_resultado['tipo_analisis'].upper()}

## Estadísticas

- Total de líneas: {analisis_resultado['estadisticas']['total_lineas']}
- Funciones: {analisis_resultado['estadisticas']['funciones']}
- Clases: {analisis_resultado['estadisticas']['clases']}
- Comentarios: {analisis_resultado['estadisticas']['comentarios']}

## Análisis

{analisis_resultado['analisis']}

---
*Generado por {ASSISTANT_NAME} - Asistente de Código*
"""
    else:  # proyecto
        contenido = f"""# Análisis de Proyecto

**Proyecto**: {analisis_resultado['proyecto']}
**Fecha**: {analisis_resultado['timestamp']}
**Tipo de análisis**: {analisis_resultado['tipo_analisis'].upper()}

## Resumen

- Archivos encontrados: {analisis_resultado['total_archivos']}
- Archivos analizados: {analisis_resultado['archivos_analizados']}

## Resultados por archivo

"""
        for resultado in analisis_resultado['resultados']:
            nombre = os.path.basename(resultado['archivo'])
            contenido += f"\n### {nombre}\n\n"
            contenido += f"{resultado['analisis']}\n\n---\n"

        contenido += f"\n*Generado por {ASSISTANT_NAME} - Asistente de Código*"

    return contenido

def guardar_reporte(analisis_resultado, formato="markdown", tipo="archivo"):
    """Guarda el reporte en un archivo."""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if tipo == "archivo":
        nombre_base = os.path.splitext(os.path.basename(analisis_resultado['archivo']))[0]
    else:
        nombre_base = os.path.basename(analisis_resultado['proyecto'].rstrip('/'))

    if formato == "markdown":
        nombre_archivo = f"{nombre_base}_{timestamp}.md"
        ruta_reporte = os.path.join(REPORTS_DIR, nombre_archivo)
        contenido = generar_reporte_markdown(analisis_resultado, tipo)

        with open(ruta_reporte, 'w', encoding='utf-8') as f:
            f.write(contenido)

    elif formato == "json":
        nombre_archivo = f"{nombre_base}_{timestamp}.json"
        ruta_reporte = os.path.join(REPORTS_DIR, nombre_archivo)

        with open(ruta_reporte, 'w', encoding='utf-8') as f:
            json.dump(analisis_resultado, f, ensure_ascii=False, indent=2)

    return ruta_reporte

def listar_reportes():
    """Lista todos los reportes generados."""
    if not os.path.exists(REPORTS_DIR):
        return []

    reportes = []
    for archivo in os.listdir(REPORTS_DIR):
        ruta = os.path.join(REPORTS_DIR, archivo)
        if os.path.isfile(ruta):
            reportes.append({
                'nombre': archivo,
                'ruta': ruta,
                'tamaño': os.path.getsize(ruta),
                'modificado': datetime.fromtimestamp(os.path.getmtime(ruta)).isoformat()
            })

    return sorted(reportes, key=lambda x: x['modificado'], reverse=True)

def obtener_reporte(nombre_archivo):
    """Obtiene el contenido de un reporte."""
    ruta = os.path.join(REPORTS_DIR, nombre_archivo)

    if not os.path.exists(ruta):
        return None

    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return None
