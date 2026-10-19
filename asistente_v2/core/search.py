from ddgs import DDGS

def buscar_web(consulta, max_resultados=3):
    try:
        resultados = []
        with DDGS() as ddgs:
            for r in ddgs.text(consulta, region="es-es", max_results=max_resultados):
                resultados.append({
                    "titulo": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })
        return resultados
    except Exception as e:
        print(f"DEBUG SEARCH ERROR: {e}")
        return []

def formatear_resultados(resultados):
    if not resultados:
        return "No encontré información en internet."
    
    texto = ""
    for i, r in enumerate(resultados):
        texto += f"{i+1}. {r['titulo']}\n{r['snippet']}\n\n"
    
    return texto.strip()