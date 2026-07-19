"""
Test 2 de Windows Hello — vía pywinrt (winrt-runtime), que SÍ instala en Python 3.14.

Debería aparecer el diálogo nativo de Windows Hello pidiendo tu PIN.
Timeout de 60 s por si se cuelga (no quedará colgado infinito como el intento anterior).

Uso:
    python test_hello2.py
"""
import asyncio
import winrt.windows.security.credentials.ui as ui

RESULTADOS = {
    0: "Verified            -> identidad confirmada ✓ (¡ESTO buscamos!)",
    1: "DeviceNotPresent",
    2: "NotConfiguredForUser",
    3: "DisabledByPolicy",
    4: "DeviceBusy",
    5: "RetriesExhausted",
    6: "Canceled            -> cancelaste el diálogo",
}


async def main():
    avail = await ui.UserConsentVerifier.check_availability_async()
    print(f"Disponibilidad Hello : {avail} (0 = Available)")
    if int(avail) != 0:
        print("Hello no disponible, abortando.")
        return

    print("\nInvocando diálogo de Windows Hello... ingresá tu PIN.\n")
    try:
        resultado = await asyncio.wait_for(
            ui.UserConsentVerifier.request_verification_async(
                "Confirmá tu identidad para Fatiga Ocular"),
            timeout=60)
        codigo = int(resultado)
        print(f"Resultado: {codigo} — {RESULTADOS.get(codigo, 'desconocido')}")
    except asyncio.TimeoutError:
        print("TIMEOUT: el diálogo nunca apareció (60 s). Necesitaríamos interop HWND.")
    except Exception as e:
        print(f"EXCEPCIÓN: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
