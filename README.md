# Simulador de efectos de audio en tiempo real

## Descripción del problema
Los pedales y software de audio profesional son costosos y poco accesibles para estudiantes y aficionados. Se necesita una herramienta sencilla y gratuita que permita experimentar con efectos de sonido básicos y, al mismo tiempo, entender cómo se transforman las señales a través de conceptos de procesamiento digital de audio.

## Objetivos principales
1. **Implementar una aplicación interactiva** que permita aplicar efectos básicos (eco, reverberación, distorsión, filtros, etc.) a archivos de audio o al micrófono en tiempo real.
2. **Ofrecer una interfaz simple e intuitiva** que facilite la interacción con los parámetros de cada efecto.
3. **Visualización educativa**: Mostrar de manera clara cómo cambian las señales, no solo a través del sonido, sino también mediante gráficas en el dominio temporal y espectral antes y después de aplicar cada efecto.

## Plan de trabajo inicial
- **Fase 1:** Revisión de librerías de procesamiento de audio y visualización de señales.
- **Fase 2:** Implementación de los efectos principales y lógica de procesamiento.
- **Fase 3:** Creación de la interfaz gráfica básica con Dash, controles de parámetros y visualización.
- **Fase 4:** Pruebas con distintos fragmentos de audio y con el micrófono, comprobando tanto la parte auditiva como las representaciones gráficas.
- **Fase 5:** Documentación completa en el repositorio y despliegue de un prototipo funcional.

---

## Acceso y Ejecución

Tienes dos formas de utilizar esta aplicación: a través de la web (Render) o ejecutándola en tu propio ordenador (Local).

### 1. Versión Web (Render)
Puedes acceder a la aplicación desplegada directamente en el siguiente enlace:

🔗 **[https://dash-frontend-7ft4.onrender.com](https://dash-frontend-7ft4.onrender.com)**

> **Nota importante sobre la versión web:** Debido a las restricciones de hardware en los servidores en la nube, la funcionalidad de **"Microphone (live)"** está deshabilitada en esta versión. Para probar los efectos, por favor selecciona la opción **"WAV file"** y sube un archivo de audio para procesarlo. Ejemplo de uso:
> 1. Descargar el audio [*music/rain-raw.wav*](https://github.com/javierdrp/audio-effects-simulator/blob/main/music/rain-raw.wav)
> 2. Seleccionar el preset *Rain Delay*
> 3. Subir el WAV descargado. Tardará unos segundos en procesarse.

### 2. Ejecución local (Recomendado)
Para utilizar la funcionalidad de micrófono en tiempo real y obtener la menor latencia posible, se recomienda ejecutar la aplicación localmente.

#### Pasos de instalaciónc

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/javierdrp/audio-effects-simulator
   cd audio-effects-simulator
   ```

2. **Crear y activar un entorno virtual:**
   *   **En Windows:**
       ```bash
       python -m venv venv
       venv\Scripts\activate
       ```
   *   **En Mac/Linux:**
       ```bash
       python3 -m venv venv
       source venv/bin/activate
       ```

3. **Instalar dependencias base:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Ejecutar la aplicación:**
   Este script levanta tanto el backend como el frontend automáticamente e instala las librerías de audio necesarias.
   ```bash
   python run.py
   ```

5. **Abrir en el navegador:**
   Visita **[http://127.0.0.1:8050](http://127.0.0.1:8050)**.
