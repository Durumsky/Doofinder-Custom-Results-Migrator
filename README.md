# Doofinder Custom Results Migrator (Selenium, modo asistido)

## ¿Qué problema resuelve?

En el panel de administración de **Doofinder**, la sección **Business Rules → Custom Results** no ofrece exportación/importación ni (en muchos planes) una API para migrar reglas entre tiendas.  
Si necesitas **copiar decenas de Custom Results** (nombre, términos y productos incluidos) de una **tienda origen** a una **tienda destino**, hacerlo a mano es lento y propenso a errores.

## ¿Qué hace este script?

Automatiza con **Selenium (Chrome)** la lectura y creación de **Custom Results**:

- **Lee** desde la tienda **origen**:
  - **Nombre** del Custom Result.  
  - **Términos** de búsqueda y su **tipo de coincidencia** (Broad / Exact / Phrase).  
  - **Productos incluidos** (por nombre, tal como aparecen en la tarjeta).  

- **Crea** en la tienda **destino**:
  - Evita duplicados recopilando previamente **todos los nombres ya existentes** en el destino (paginación asistida).  
  - Para cada Custom Result faltante: crea el registro, añade los términos (con el tipo de match) y añade los productos (buscándolos por nombre y seleccionando el **primer resultado** del modal “Include Items”).

> El script funciona en **modo asistido**: tú haces **login manual** y controlas la **paginación** (Rows per page / cambio de página). El script te va pidiendo **ENTER** para capturar la página actual y **`fin`** cuando termines de repasar todas.

---

## Requisitos

- **Python** 3.8 o superior (recomendado 3.10+).  
- **Google Chrome** instalado (versión reciente).  
- Paquetes Python:
  ```bash
  pip install selenium webdriver-manager pandas
  ```

> **Consejo**: usa un **entorno virtual** por proyecto:
> ```bash
> python -m venv venv
> source venv/bin/activate     # (Windows: venv\Scripts\activate)
> pip install -U pip
> pip install selenium webdriver-manager pandas
> ```

---

## Configuración

Abre el archivo `.py` y ajusta:

```python
# URLs de lista de Custom Results (origen y destino)
SOURCE_URL = "https://admin.doofinder.com/.../custom_results?store_id=TU_STORE_ID_ORIGEN"
DEST_URL   = "https://admin.doofinder.com/.../custom_results?store_id=TU_STORE_ID_DESTINO"

# Ensayo sin crear en destino
DRY_RUN = False
```

**Dónde conseguir las URLs:**  
Entra en Doofinder → **Search → Custom Results** y copia la **URL completa** (incluye `store_id` y `hashid`).

---

## Cómo usarlo (paso a paso)

1. **Ejecuta** el script:
   ```bash
   python doofinder_custom_results_migrator_assisted_pages.py
   ```

2. **ORIGEN – Captura con paginación asistida**  
   - En Chrome: **login** si corresponde.  
   - Abre la lista de Custom Results del **origen**.  
   - Pon **Rows per page = 50** (o la mayor disponible) y/o navega de página.  
   - **ENTER** en la terminal para capturar la página actual.  
   - Cambia de página en el navegador y vuelve a pulsar **ENTER**.  
   - Repite hasta cubrir todas las páginas.  
   - Escribe **`fin`** y pulsa **ENTER**.  
   Se extraerán **nombre, términos y productos** de todos los enlaces.  
   Se generarán:
   - `doofinder_custom_results_origen.json` (detallado)  
   - `doofinder_custom_results_origen_resumen.json` (compacto)

3. **DESTINO – Recopila existentes con paginación asistida**  
   - El script pide **login** y abre la lista del **destino**.  
   - Igual que en origen: **ENTER** para capturar la página actual de existentes.  
   - Cambia de página y **ENTER**.  
   - **`fin`** al terminar.  
   Se reunirá el **set completo** de nombres existentes.

4. **Creación en destino**  
   - El script crea solo los Custom Results **no presentes** en ese set.  
   - Por cada uno: “Add Custom Result” → nombre → términos → productos → “Save”.  
   - Si un clic queda interceptado, el script reintenta de forma robusta.

5. Al final verás cuántos **nuevos creados**.

---

## Sugerencias y límites

- Captura **todas** las páginas del destino para evitar duplicados.  
- Productos: busca por **nombre** y selecciona el **primer resultado**.  
- Tipos de término: si tu UI usa otro idioma/texto, ajusta  
  `parse_match_class_to_text(...)` y `set_term_match_type(...)`.  
- Para errores de “click intercepted”, ajusta `tries` en `safe_click`, `extra_offset`, o esperas  
  (`WebDriverWait` / `time.sleep`).

