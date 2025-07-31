# doofinder_custom_results_migrator_assisted_pages.py
import time
from typing import List, Dict, Tuple, Any, Set

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, ElementClickInterceptedException,
    StaleElementReferenceException
)
from webdriver_manager.chrome import ChromeDriverManager

# ====================== CONFIGURACIÓN ======================
# Pega aquí las URLs de lista de Custom Results (ORIGEN y DESTINO)
SOURCE_URL = "https://admin.doofinder.com/admin/store/searchengine/business-rules/custom_results?store_id=TU_STORE_ID_ORIGEN"
DEST_URL   = "https://admin.doofinder.com/admin/store/searchengine/business-rules/custom_results?store_id=TU_STORE_ID_DESTINO"
# Ensayo sin crear en destino (True = NO crea nada, solo simula)
DRY_RUN = False

# ====================== DRIVER ======================
def build_driver(headless: bool = False):
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if headless:
        # Para login asistido, se recomienda ventana visible (sin headless)
        options.add_argument("--headless=new")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 30)
    return driver, wait

# ====================== HELPERS GENÉRICOS ======================
def force_https(url: str) -> str:
    return url.replace("http://", "https://")

def accept_cookies_if_any(driver):
    """Intenta aceptar banners de cookies comunes (opcional)."""
    selectors = [
        "//button[normalize-space()='Accept all']",
        "//button[normalize-space()='Accept All']",
        "//button[contains(.,'Akzeptieren')]",
        "//button[contains(.,'Zustimmen')]",
        "//*[@role='button' and normalize-space()='Accept all']",
        "//*[@role='button' and normalize-space()='Accept All']",
    ]
    try:
        for xp in selectors:
            btns = driver.find_elements(By.XPATH, xp)
            if btns:
                btns[0].click()
                time.sleep(0.4)
                break
    except Exception:
        pass

def wait_ready(driver, timeout=20):
    """Espera a document.readyState == 'complete'."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            state = driver.execute_script("return document.readyState")
            if state == "complete":
                return
        except Exception:
            pass
        time.sleep(0.2)

def get_header_height(driver) -> int:
    """Altura de la barra superior para compensar scroll (ajusta si tu UI difiere)."""
    try:
        h = driver.execute_script("""
            const el = document.querySelector('section.ui-top-bar');
            return el ? Math.ceil(el.getBoundingClientRect().height) : 80;
        """)
        return int(h or 80)
    except Exception:
        return 80

def safe_click(driver, by, locator, description="elemento", tries=5, center=True, js_fallback=True, extra_offset=120):
    """
    Clic robusto:
    - scrollIntoView({block:'center'})
    - compensa top bar (offset)
    - click normal -> Actions -> JS click (fallback)
    - reintentos si hay intercept/stale
    """
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            el = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((by, locator)))
            if center:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                time.sleep(0.1)
                header_h = get_header_height(driver) + extra_offset
                driver.execute_script("window.scrollBy(0, -arguments[0]);", header_h)

            try:
                el.click()
                return
            except ElementClickInterceptedException:
                try:
                    ActionChains(driver).move_to_element(el).pause(0.05).click().perform()
                    return
                except (ElementClickInterceptedException, StaleElementReferenceException):
                    pass
                if js_fallback:
                    driver.execute_script("arguments[0].click();", el)
                    return
            except StaleElementReferenceException:
                pass

        except Exception as e:
            last_err = e
        time.sleep(0.4)

    raise last_err if last_err else RuntimeError(f"No se pudo hacer click en {description}")

def get_table_rows(driver, wait):
    tbody = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody.table-align-middle")))
    return tbody.find_elements(By.CSS_SELECTOR, "tr")

def parse_match_class_to_text(classes: str) -> str:
    classes = (classes or "").lower()
    if "term--broad" in classes:  return "Broad Match"
    if "term--exact" in classes:  return "Exact Match"
    if "term--phrase" in classes: return "Phrase Match"
    return "Broad Match"

# ====================== EXTRACCIÓN (ORIGEN) ======================
def capture_current_page_links(driver, wait) -> List[Tuple[str, str]]:
    links = []
    for r in get_table_rows(driver, wait):
        try:
            a = r.find_element(By.CSS_SELECTOR, "td[data-field='name'] a")
            href = a.get_attribute("href")
            name = a.text.strip()
            if href and name:
                links.append((name, force_https(href)))
        except NoSuchElementException:
            pass
    return links

def extract_custom_result(driver, wait) -> Dict[str, Any]:
    # Nombre
    name = ""
    try:
        name_input = driver.find_element(By.CSS_SELECTOR, "input#custom_result_name")
        name = (name_input.get_attribute("value") or name_input.get_attribute("placeholder") or "").strip()
    except NoSuchElementException:
        pass
    # Términos
    terms: List[Dict[str, str]] = []
    try:
        container = driver.find_element(By.CSS_SELECTOR, "#js-terms-container.terms-container")
        for t in container.find_elements(By.CSS_SELECTOR, "div.search-term"):
            try:
                label = t.find_element(By.CSS_SELECTOR, "span.term__label").text.strip()
            except NoSuchElementException:
                label = t.text.strip()
            match_type = parse_match_class_to_text(t.get_attribute("class"))
            if label:
                terms.append({"label": label, "match": match_type})
    except NoSuchElementException:
        pass
    # Productos incluidos
    products: List[str] = []
    try:
        box = driver.find_element(By.CSS_SELECTOR, "#scrollable-included-results")
        for n in box.find_elements(By.CSS_SELECTOR, ".result-items__text span"):
            txt = n.text.strip()
            if txt:
                products.append(txt)
    except NoSuchElementException:
        pass
    return {"name": name, "terms": terms, "products": products}

def scrape_source_assisted_pages(driver, wait, source_url: str) -> List[Dict[str, Any]]:
    print(">> ORIGEN: abriendo lista…")
    driver.get(force_https(source_url))
    accept_cookies_if_any(driver)

    print("\n>>> MODO ASISTIDO (ORIGEN, por páginas) <<<")
    print("1) En Chrome: haz LOGIN si se pide.")
    print("2) En la lista del ORIGEN: selecciona manualmente 'Rows per page = 50' o navega a la página que quieras.")
    print("3) Vuelve aquí y pulsa ENTER para capturar la PÁGINA ACTUAL.")
    print("   Cuando termines todas las páginas, escribe 'fin' y ENTER.\n")

    all_links: List[Tuple[str, str]] = []
    seen = set()
    page_idx = 1
    while True:
        s = input(f"[ORIGEN] Página {page_idx}: ENTER para capturar esta página, o escribe 'fin' para terminar: ").strip().lower()
        if s in ("fin", "q", "quit", "done"):
            break
        links = capture_current_page_links(driver, wait)
        added = 0
        for name, href in links:
            if href not in seen:
                all_links.append((name, href))
                seen.add(href)
                added += 1
        print(f"   · Capturados {added} nuevos (acumulado: {len(all_links)}).")
        print("   · Si hay otra página, ve a la siguiente manualmente y pulsa ENTER. Si no, escribe 'fin'.")
        page_idx += 1

    print(f">> ORIGEN: total enlaces únicos recopilados: {len(all_links)}")
    results: List[Dict[str, Any]] = []
    for i, (name, href) in enumerate(all_links, start=1):
        print(f"   - ({i}/{len(all_links)}) Leyendo: {name}")
        driver.get(href)
        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "#js-terms-container, #scrollable-included-results")))
        data = extract_custom_result(driver, wait)
        if not data.get("name"):
            data["name"] = name
        results.append(data)

    pd.DataFrame(results).to_json("doofinder_custom_results_origen.json",
                                  orient="records", force_ascii=False)
    print(">> ORIGEN: extracción completa.")
    return results

# ====================== CREACIÓN (DESTINO) ======================
def collect_existing_names_current_page(driver, wait) -> Set[str]:
    existing = set()
    for r in get_table_rows(driver, wait):
        try:
            a = r.find_element(By.CSS_SELECTOR, "td[data-field='name'] a")
            nm = a.text.strip()
            if nm:
                existing.add(nm.lower())
        except NoSuchElementException:
            pass
    return existing

def collect_existing_names_assisted_pages(driver, wait) -> Set[str]:
    """
    Reúne los nombres existentes en el DESTINO con paginación asistida.
    """
    print("\n>>> MODO ASISTIDO (DESTINO, por páginas) <<<")
    print("1) En Chrome: haz LOGIN si se pide y muestra 50 filas si es posible.")
    print("2) Pulsa ENTER para capturar la PÁGINA ACTUAL del DESTINO.")
    print("3) Cambia de página y vuelve a pulsar ENTER. Escribe 'fin' al terminar.\n")

    existing_all: Set[str] = set()
    page_idx = 1
    while True:
        s = input(f"[DESTINO] Página {page_idx}: ENTER para capturar esta página, o escribe 'fin' para terminar: ").strip().lower()
        if s in ("fin", "q", "quit", "done"):
            break
        current = collect_existing_names_current_page(driver, wait)
        added = len(current - existing_all)
        existing_all |= current
        print(f"   · Capturados {added} nuevos (acumulado: {len(existing_all)}).")
        print("   · Si hay otra página, navega a ella y pulsa ENTER. Si no, escribe 'fin'.")
        page_idx += 1

    print(f">> DESTINO: total nombres únicos recopilados: {len(existing_all)}")
    return existing_all

def set_term_match_type(driver, wait, match_label: str):
    safe_click(driver, By.CSS_SELECTOR, "#termDropdownMenuButton", description="match dropdown", tries=4)
    time.sleep(0.15)
    menu = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.dropdown-menu.show")))
    opts = menu.find_elements(By.XPATH, f".//*[normalize-space()='{match_label}']")
    if not opts:
        first_word = match_label.split()[0]
        opts = menu.find_elements(By.XPATH, f".//*[contains(normalize-space(), '{first_word}')]")
    if opts:
        opts[0].click()
    else:
        fb = menu.find_elements(By.XPATH, ".//*[normalize-space()='Broad Match']")
        if fb:
            fb[0].click()
    time.sleep(0.15)

def add_terms_in_dest(driver, wait, terms: List[Dict[str, str]]):
    for term in terms:
        label = (term.get("label") or "").strip()
        match = (term.get("match") or "Broad Match").strip() or "Broad Match"
        if not label:
            continue
        set_term_match_type(driver, wait, match)
        inp = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input#id_term_input.search-term-input")))
        inp.clear()
        inp.send_keys(label)
        safe_click(driver, By.XPATH, "//button[@phx-click='add_term']", description="Add term", tries=4)
        time.sleep(0.2)

def open_include_items_modal(driver, wait):
    safe_click(driver, By.CSS_SELECTOR, "#included_results_box-dropdownMenuButton", description="Add results dropdown", tries=4)
    menu = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.dropdown-menu.show")))
    item = menu.find_element(By.XPATH, ".//a[contains(., 'Individual items')]")
    item.click()
    WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "dialog#included-items-modal-modal[open]")))
    time.sleep(0.2)

def add_products_in_dest_via_modal(driver, wait, product_names: List[str]):
    if not product_names:
        return
    open_include_items_modal(driver, wait)
    input_box = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#included-items-modal-input")))
    for pname in product_names:
        input_box.clear()
        input_box.send_keys(pname)
        try:
            results_scroll = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#included-items-modal-scroll.items-selection"))
            )
            first_item_label = WebDriverWait(results_scroll, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".item label"))
            )
            first_item_label.click()
        except TimeoutException:
            print(f"      ! No se encontraron resultados para: {pname}")
        time.sleep(0.3)
    footer_add_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((
        By.XPATH, "//dialog[@id='included-items-modal-modal']//button[contains(@class,'btn-success') and not(@disabled)]"
    )))
    footer_add_btn.click()
    time.sleep(0.6)

def create_one_custom_result_in_dest(driver, wait, cr: Dict[str, Any], max_attempts: int = 3) -> bool:
    name = (cr.get("name") or "").strip()
    if not name:
        return False
    for attempt in range(1, max_attempts + 1):
        try:
            wait_ready(driver, 10)
            safe_click(driver, By.CSS_SELECTOR, "#add_custom_result", description="Add Custom Result", tries=6)
            name_input = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input#custom_result_name")))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", name_input)
            time.sleep(0.1)
            name_input.clear()
            name_input.send_keys(name)
            add_terms_in_dest(driver, wait, cr.get("terms", []))
            add_products_in_dest_via_modal(driver, wait, cr.get("products", []))
            safe_click(driver, By.CSS_SELECTOR, "#id_submit_button", description="Save", tries=6)
            try:
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody.table-align-middle")))
            except TimeoutException:
                driver.get(force_https(DEST_URL))
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody.table-align-middle")))
            return True
        except (ElementClickInterceptedException, StaleElementReferenceException, TimeoutException) as e:
            print(f"      · Reintentando '{name}' (intento {attempt}/{max_attempts}) por: {type(e).__name__}")
            driver.get(force_https(DEST_URL))
            time.sleep(0.8)
            continue
    raise RuntimeError(f"No se pudo crear '{name}' tras {max_attempts} intentos")

def migrate_to_dest_assisted(driver, wait, custom_results: List[Dict[str, Any]], dest_url: str, dry_run: bool = False):
    print("\n>> DESTINO: abriendo lista…")
    driver.get(force_https(dest_url))
    # Recopila EXISTENTES con paginación asistida (igual que en ORIGEN)
    existing_all = collect_existing_names_assisted_pages(driver, wait)

    created = 0
    print("\n>> Comenzando creación (omitiendo existentes recopilados)…")
    for i, cr in enumerate(custom_results, start=1):
        nm = (cr.get("name") or "").strip()
        if not nm:
            print(f"   - ({i}/{len(custom_results)}) [SIN NOMBRE] — saltando.")
            continue
        print(f"   - ({i}/{len(custom_results)}) {nm}")
        if nm.lower() in existing_all:
            print("      · Ya existe (en alguna página) — se omite.")
            continue
        if dry_run:
            print("      · DRY_RUN — simulación, no se crea.")
            continue
        try:
            ok = create_one_custom_result_in_dest(driver, wait, cr, max_attempts=3)
            if ok:
                created += 1
                existing_all.add(nm.lower())
                driver.get(force_https(DEST_URL))
                time.sleep(0.8)
        except Exception as e:
            print(f"      ! Error creando '{nm}': {e}")
            driver.get(force_https(DEST_URL))
            time.sleep(0.8)
    print(f">> DESTINO: creación finalizada. Nuevos creados: {created}.")

# ====================== MAIN ======================
def main():
    driver, wait = build_driver(headless=False)
    try:
        # 1) ORIGEN (asistido por páginas)
        source_data = scrape_source_assisted_pages(driver, wait, SOURCE_URL)

        # 2) Respaldo del origen (compacto)
        df = pd.DataFrame([{
            "name": d.get("name", ""),
            "terms": d.get("terms", []),
            "products": d.get("products", []),
        } for d in source_data])
        df.to_json("doofinder_custom_results_origen_resumen.json",
                   orient="records", force_ascii=False)
        print(">> ORIGEN: respaldo JSON generado.")

        # 3) DESTINO (asistido con paginación para EXISTENTES)
        migrate_to_dest_assisted(driver, wait, source_data, DEST_URL, dry_run=DRY_RUN)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
