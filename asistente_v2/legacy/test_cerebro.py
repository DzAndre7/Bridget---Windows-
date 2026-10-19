# test_cerebro.py
"""
Script de prueba para core/cerebro.py
Corré esto con: python test_cerebro.py
Sirve para verificar que la lectura del cerebro funciona antes de
integrarlo a Bridget. No modifica nada, solo lee.
"""

from core import cerebro

print("=" * 50)
print("PRUEBA 1: ¿Encuentra el vault y lista las notas?")
print("=" * 50)
try:
    notas = cerebro.listar_notas()
    print(f"✅ Vault encontrado. Notas halladas: {len(notas)}")
    for n in notas:
        print(f"   - {n.name}")
except Exception as e:
    print(f"❌ Error: {e}")

print()
print("=" * 50)
print("PRUEBA 2: ¿Puede leer una nota específica?")
print("=" * 50)
try:
    notas = cerebro.listar_notas()
    if notas:
        primera = notas[0].name
        contenido = cerebro.leer_nota(primera)
        if contenido is not None:
            print(f"✅ Leyó '{primera}'. Primeros 100 caracteres:")
            print(f"   {contenido[:100]}")
        else:
            print(f"❌ No pudo leer '{primera}'")
    else:
        print("⚠️  No hay notas para probar. Creá una nota en el vault primero.")
except Exception as e:
    print(f"❌ Error: {e}")

print()
print("=" * 50)
print("PRUEBA 3: ¿Puede buscar texto en las notas?")
print("=" * 50)
try:
    # cambiá 'seguridad' por alguna palabra que sepas que está en tus notas
    palabra = "seguridad"
    resultados = cerebro.buscar_en_notas(palabra)
    print(f"Buscando '{palabra}'... {len(resultados)} resultado(s):")
    for r in resultados:
        print(f"   📄 {r['nota']}")
        print(f"      {r['fragmento']}")
except Exception as e:
    print(f"❌ Error: {e}")

print()
print("=" * 50)
print("Pruebas terminadas.")
print("=" * 50)