#test_escritura.py
from core import cerebro

print("Probando guardado directo...")
ruta = cerebro.guardar_nota(
    titulo="Prueba de escritura",
    contenido="Esta es una nota de prueba creada por el test.",
    carpeta="conversaciones",
    enlaces=["Ciberseguridad", "IP"]
)
print(f"✅ Nota creada en: {ruta}" if ruta else "❌ Falló")

print("\nProbando guardado en inbox...")
ruta_inbox = cerebro.guardar_en_inbox(
    titulo="Idea estimada por Bridget",
    contenido="Algo que Bridget creyó que valía la pena.",
    motivo="Apareció varias veces en la conversación."
)
print(f"✅ Inbox creado en: {ruta_inbox}" if ruta_inbox else "❌ Falló")