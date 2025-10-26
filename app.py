import os
import traceback
from datetime import datetime, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, render_template, jsonify, request, session, redirect,
    url_for, make_response, send_from_directory, Blueprint
)
from flask_mail import Mail

# Load environment variables
load_dotenv()

# ----------------------------------------------------------------------------
# Flask application setup
# ----------------------------------------------------------------------------
app = Flask(__name__, template_folder='templates', static_folder='static')

# Secret key (required). Fail fast if missing.
app.secret_key = os.getenv('SECRET_KEY')
if not app.secret_key:
    raise ValueError("KRITICKÁ CHYBA: SECRET_KEY nie je nastavený v .env súbore!")

app.permanent_session_lifetime = timedelta(hours=8)

# ----------------------------------------------------------------------------
# Mail configuration
# ----------------------------------------------------------------------------
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 465))
app.config['MAIL_USE_TLS'] = str(os.getenv('MAIL_USE_TLS', 'False')).lower() in ['true', '1', 't']
app.config['MAIL_USE_SSL'] = str(os.getenv('MAIL_USE_SSL', 'True')).lower() in ['true', '1', 't']
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv("MAIL_DEFAULT_SENDER")
app.config['MAIL_ASCII_ATTACHMENTS'] = False

if not all([app.config['MAIL_SERVER'], app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'], app.config['MAIL_DEFAULT_SENDER']]):
    print("!!! VAROVANIE: Chýbajú niektoré konfiguračné premenné pre e-mail v .env súbore! Odosielanie e-mailov bude zlyhávať. !!!")

mail = Mail(app)

# ----------------------------------------------------------------------------
# Imports that depend on app context / project modules
# ----------------------------------------------------------------------------
import auth_handler
import production_handler
import expedition_handler
import office_handler
import b2b_handler
import b2c_handler
import db_connector
import fleet_handler
import hygiene_handler
import profitability_handler
import costs_handler
from notification_handler import send_order_confirmation_email, send_b2c_order_confirmation_email_with_pdf
import pdf_generator

# =================================================================
# === DEKORÁTORY A POMOCNÉ FUNKCIE ===
# =================================================================

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                if request.path.startswith('/api/'): return jsonify({'error': 'Prístup zamietnutý. Prosím, prihláste sa.'}), 401
                if 'expedicia' in request.path: return redirect(url_for('page_expedicia'))
                if 'kancelaria' in request.path: return redirect(url_for('page_kancelaria'))
                return redirect(url_for('page_vyroba'))
            
            user_role = session['user'].get('role')
            if user_role != 'admin' and role and user_role not in (role if isinstance(role, list) else [role]):
                if request.path.startswith('/api/'): return jsonify({'error': 'Nemáte oprávnenie na túto akciu.'}), 403
                return redirect(url_for('page_vyroba'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
    
def b2c_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'b2c_user' not in session:
            return jsonify({'error': 'Pre túto akciu musíte byť prihlásený.'}), 401
        return f(*args, **kwargs)
    return decorated_function

def handle_request(handler_func, *args, **kwargs):
    try:
        result = handler_func(*args, **kwargs)
        if isinstance(result, dict) and result.get("error"): return jsonify(result), 400
        if isinstance(result, make_response('').__class__): return result
        return jsonify(result)
    except Exception as e:
        print(f"!!! SERVER ERROR in handler '{handler_func.__name__}' !!!")
        print(traceback.format_exc())
        return jsonify({'error': f"Interná chyba servera. Kontaktujte administrátora."}), 500

# =================================================================
# === HLAVNÉ ROUTY PRE STRÁNKY (VIEWS) ===
# =================================================================
@app.route('/')
def index(): return redirect(url_for('page_vyroba'))

@app.route('/vyroba')
def page_vyroba(): return render_template('vyroba.html')

@app.route('/expedicia')
def page_expedicia(): return render_template('expedicia.html')

@app.route('/kancelaria')
def page_kancelaria(): return render_template('kancelaria.html')

@app.route('/b2b')
def page_b2b(): return render_template('b2b.html')

@app.route('/b2c')
def page_b2c(): return render_template('b2c.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

# =================================================================
# === INTERNÉ PRIHLASOVANIE A SESSION MANAGEMENT ===
# =================================================================
@app.route('/api/internal/login', methods=['POST'])
def internal_login():
    data = request.json
    user = db_connector.execute_query("SELECT * FROM internal_users WHERE username = %s", (data.get('username'),), fetch='one')
    if user and auth_handler.verify_password(data.get('password'), user['password_salt'], user['password_hash']):
        session.permanent = True
        session['user'] = { 'id': user['id'], 'username': user['username'], 'role': user['role'], 'full_name': user['full_name'] }
        return jsonify({'message': 'Prihlásenie úspešné.', 'user': session['user']})
    return jsonify({'error': 'Nesprávne meno alebo heslo.'}), 401

@app.route('/api/internal/logout', methods=['POST'])
def internal_logout():
    session.pop('user', None)
    return jsonify({'message': 'Boli ste úspešne odhlásený.'})

@app.route('/api/internal/check_session')
def check_session():
    return jsonify({'loggedIn': 'user' in session, 'user': session.get('user')})

# =================================================================
# === API ENDPOINTY PRE MODUL: VÝROBA ===
# =================================================================
@app.route('/api/getProductionMenuData')
@login_required(role='vyroba')
def get_prod_menu(): return handle_request(production_handler.get_production_menu_data)

@app.route('/api/calculateRequiredIngredients', methods=['POST'])
@login_required(role=['vyroba', 'kancelaria'])
def calc_ingredients(): return handle_request(production_handler.calculate_required_ingredients, request.json.get('productName'), request.json.get('plannedWeight'))

@app.route('/api/startProduction', methods=['POST'])
@login_required(role='vyroba')
def start_prod(): return handle_request(production_handler.start_production, **request.json)

@app.route('/api/getWarehouseState')
@login_required(role=['vyroba', 'kancelaria'])
def get_warehouse_state(): return handle_request(production_handler.get_warehouse_state)

@app.route('/api/submitInventory', methods=['POST'])
@login_required(role='vyroba')
def submit_inventory(): return handle_request(production_handler.update_inventory, request.json)

@app.route('/api/getAllWarehouseItems')
@login_required(role='vyroba')
def get_warehouse_items(): return handle_request(production_handler.get_all_warehouse_items)

@app.route('/api/manualWriteOff', methods=['POST'])
@login_required(role='vyroba')
def manual_write_off(): return handle_request(production_handler.manual_warehouse_write_off, request.json)

# =================================================================
# === API ENDPOINTY PRE MODUL: EXPEDÍCIA ===
# =================================================================
@app.route('/api/expedicia/getExpeditionData')
@login_required(role='expedicia')
def get_exp_data(): return handle_request(expedition_handler.get_expedition_data)

@app.route('/api/expedicia/getProductionDates')
@login_required(role='expedicia')
def get_prod_dates(): return handle_request(expedition_handler.get_production_dates)

@app.route('/api/expedicia/getProductionsByDate', methods=['POST'])
@login_required(role='expedicia')
def get_prods_by_date(): return handle_request(expedition_handler.get_productions_by_date, request.json.get('date'))

@app.route('/api/expedicia/completeProductions', methods=['POST'])
@login_required(role='expedicia')
def complete_prods(): return handle_request(expedition_handler.complete_multiple_productions, request.json)

@app.route('/api/expedicia/finalizeDay', methods=['POST'])
@login_required(role='expedicia')
def finalize_day(): return handle_request(expedition_handler.finalize_day, request.json.get('date'))

@app.route('/api/expedicia/getAccompanyingLetter', methods=['POST'])
@login_required(role=['expedicia', 'kancelaria'])
def get_letter():
    data = expedition_handler.get_accompanying_letter_data(request.json.get('batchId'))
    if not data: return make_response(f"<h1>Chyba: Dáta pre šaržu '{request.json.get('batchId')}' neboli nájdené.</h1>", 404)
    worker = request.json.get('workerName')
    template_data = {"title": "Sprievodný List", "is_accompanying_letter": True, "report_date": datetime.now().strftime('%d.%m.%Y %H:%M'), "data": {**data, 'prebral': worker}}
    return make_response(render_template('report_template.html', **template_data))

@app.route('/api/expedicia/finalizeSlicing', methods=['POST'])
@login_required(role='expedicia')
def finalize_slicing(): return handle_request(expedition_handler.finalize_slicing_transaction, request.json.get('logId'), request.json.get('actualPieces'))

@app.route('/api/expedicia/getAllFinalProducts')
@login_required(role='expedicia')
def get_final_products(): return handle_request(expedition_handler.get_all_final_products)

@app.route('/api/expedicia/manualReceiveProduct', methods=['POST'])
@login_required(role='expedicia')
def manual_receive(): return handle_request(expedition_handler.manual_receive_product, request.json)

@app.route('/api/expedicia/getSlicableProducts')
@login_required(role='expedicia')
def get_slicable_products(): return handle_request(expedition_handler.get_slicable_products)

@app.route('/api/expedicia/startSlicingRequest', methods=['POST'])
@login_required(role='expedicia')
def start_slicing(): return handle_request(expedition_handler.start_slicing_request, request.json.get('ean'), request.json.get('pieces'))

@app.route('/api/expedicia/logManualDamage', methods=['POST'])
@login_required(role='expedicia')
def manual_damage(): return handle_request(expedition_handler.log_manual_damage, request.json)

@app.route('/api/expedicia/getProductsForInventory')
@login_required(role='expedicia')
def get_products_for_inventory(): return handle_request(expedition_handler.get_products_for_inventory)

@app.route('/api/expedicia/submitProductInventory', methods=['POST'])
@login_required(role='expedicia')
def submit_product_inventory():
    data = request.json
    return handle_request(expedition_handler.submit_product_inventory, data.get('inventoryData'), data.get('workerName'))

# =================================================================
# === API ENDPOINTY PRE MODUL: KANCELÁRIA ===
# =================================================================

# --- Kancelária: pomocné API pre ERP (Blueprint) ---
from db_connector import execute_query  # na priame SELECTy v dvoch pomocných routach

kancelaria_api = Blueprint('kancelaria_api', __name__)

from flask import jsonify
import office_handler  # už v projekte máš

@app.get('/api/kancelaria/baseData')
def base_data_alias():
    from flask import jsonify
    from db_connector import execute_query

    # produkty bez receptu (iba výrobky)
    try:
        products = execute_query("""
          SELECT p.nazov_vyrobku
            FROM produkty p
           WHERE p.typ_polozky LIKE 'VÝROBOK%%'
             AND NOT EXISTS (
                   SELECT 1 FROM recepty r
                   WHERE TRIM(r.nazov_vyrobku) = TRIM(p.nazov_vyrobku)
                 )
           ORDER BY p.nazov_vyrobku
        """) or []
        products_without_recipe = [r['nazov_vyrobku'] for r in products]
    except Exception as e:
        print('baseData products err:', e)
        products_without_recipe = []

    # kategórie receptov (už priradené produktom)
    try:
        cats = execute_query("""
          SELECT DISTINCT kategoria_pre_recepty AS cat
            FROM produkty
           WHERE kategoria_pre_recepty IS NOT NULL AND kategoria_pre_recepty <> ''
           ORDER BY cat
        """) or []
        recipe_categories = [c['cat'] for c in cats]
    except Exception as e:
        print('baseData categories err:', e)
        recipe_categories = []

    # kategórie skladových položiek – ak stĺpec 'kategoria' ešte nemáš, dá default
    try:
        item_types_rows = execute_query("""
          SELECT DISTINCT kategoria FROM sklad
          WHERE kategoria IS NOT NULL AND kategoria <> ''
          ORDER BY kategoria
        """) or []
        item_types = [r['kategoria'] for r in item_types_rows] or ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál']
    except Exception as e:
        print('baseData item_types err:', e)
        item_types = ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál']

    return jsonify({
        "productsWithoutRecipe": products_without_recipe,
        "recipeCategories": recipe_categories,
        "itemTypes": item_types
    })




@kancelaria_api.get('/api/kancelaria/stock/allowed-names-bp')
def stock_allowed_names_bp():
    from flask import jsonify, request
    from db_connector import execute_query

    raw = (request.args.get('category') or '').strip()

    # 1) normalizácia vstupu (prijmeme "maso", "mäso", "MÄSO" atď.)
    s = raw.lower().replace('_',' ').strip()
    mapping = {
        'maso': 'Mäso',
        'mäso': 'Mäso',
        'koreniny': 'Koreniny',
        'korenie': 'Koreniny',
        'obaly': 'Obaly - Črevá',
        'črevá': 'Obaly - Črevá',
        'cerva': 'Obaly - Črevá',
        'pomocny material': 'Pomocný materiál',
        'pomocný materiál': 'Pomocný materiál',
        'pomocny materialy': 'Pomocný materiál',
        'pomocne': 'Pomocný materiál',
    }
    category = mapping.get(s, raw or '')

    # 2) zistíme, či tabuľka 'sklad' má stĺpec 'kategoria'
    has_cat_col = execute_query("""
        SELECT 1
          FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE()
           AND TABLE_NAME = 'sklad'
           AND COLUMN_NAME = 'kategoria'
         LIMIT 1
    """, fetch='one')

    items = []

    try:
        if has_cat_col:
            # 3) plnohodnotný dotaz s koláciou na oboch stranách, bez mix-chyby
            rows = execute_query("""
                SELECT s.nazov AS name,
                       s.is_infinite_stock,
                       s.default_cena_eur_kg,
                       (SELECT z.nakupna_cena_eur_kg
                          FROM zaznamy_prijem z
                         WHERE z.nazov_suroviny COLLATE utf8mb4_slovak_ci
                               = s.nazov COLLATE utf8mb4_slovak_ci
                           AND z.nakupna_cena_eur_kg IS NOT NULL
                         ORDER BY z.datum DESC
                         LIMIT 1) AS last_price
                  FROM sklad s
                 WHERE s.kategoria COLLATE utf8mb4_slovak_ci
                       = %s COLLATE utf8mb4_slovak_ci
                 ORDER BY s.nazov
            """, (category,)) or []

            for r in rows:
                price = r.get('last_price')
                if price is None:
                    price = r.get('default_cena_eur_kg')
                if price is None and int(r.get('is_infinite_stock') or 0) == 1:
                    price = 0.20  # fallback pre nekonečné položky
                items.append({
                    "name": r["name"],
                    "last_price": float(price) if price is not None else None,
                    "is_infinite": bool(r.get("is_infinite_stock"))
                })

        else:
            # 4) fallback bez stĺpca 'kategoria'
            if category.lower().startswith('pomoc'):
                items = [
                    {"name":"Voda","last_price":0.20,"is_infinite":True},
                    {"name":"Ľad","last_price":0.20,"is_infinite":True},
                    {"name":"Ovar","last_price":0.20,"is_infinite":True}
                ]
            else:
                # vrátime rozumný výber, nech UI funguje (user si nájde položky)
                rows = execute_query("""
                    SELECT s.nazov AS name,
                           s.is_infinite_stock,
                           s.default_cena_eur_kg
                      FROM sklad s
                     ORDER BY s.nazov
                     LIMIT 250
                """) or []
                for r in rows:
                    price = r.get('default_cena_eur_kg')
                    items.append({
                        "name": r["name"],
                        "last_price": float(price) if price is not None else None,
                        "is_infinite": bool(r.get("is_infinite_stock"))
                    })

        return jsonify({"items": items})

    except Exception as e:
        # tvrdý fallback, nikdy nevracaj 500 pre frontend „Nový recept“
        print('allowed-names alias error:', e)
        if category.lower().startswith('pomoc'):
            return jsonify({"items": [
                {"name":"Voda","last_price":0.20,"is_infinite":True},
                {"name":"Ľad","last_price":0.20,"is_infinite":True},
                {"name":"Ovar","last_price":0.20,"is_infinite":True}
            ]})
        return jsonify({"items": []})

# Registrácia blueprintu (po definícii aj po vytvorení app)
app.register_blueprint(kancelaria_api)

# --- Kancelária: Dashboard, Sklad a Plánovanie ---
@app.route('/api/kancelaria/getDashboardData')
@login_required(role='kancelaria')
def get_dashboard(): return handle_request(office_handler.get_kancelaria_dashboard_data)

@app.route('/api/kancelaria/getKancelariaBaseData')
@login_required(role='kancelaria')
def get_kancelaria_base(): return handle_request(office_handler.get_kancelaria_base_data)

@app.route('/api/kancelaria/getRawMaterialStockOverview')
@login_required(role='kancelaria')
def get_raw_material_stock_overview():
    return handle_request(office_handler.get_raw_material_stock_overview)

@app.route('/api/kancelaria/getComprehensiveStockView')
@login_required(role='kancelaria')
def get_comprehensive_stock(): return handle_request(office_handler.get_comprehensive_stock_view)

@app.route('/api/kancelaria/receiveStockItems', methods=['POST'])
@login_required(role='kancelaria')
def receive_stock(): return handle_request(office_handler.receive_multiple_stock_items, request.json)

@app.route('/api/kancelaria/getProductionPlan')
@login_required(role='kancelaria')
def get_plan(): return handle_request(office_handler.calculate_production_plan)

@app.route('/api/kancelaria/createTasksFromPlan', methods=['POST'])
@login_required(role='kancelaria')
def create_tasks(): return handle_request(office_handler.create_production_tasks_from_plan, request.json)

@app.route('/api/kancelaria/getPurchaseSuggestions')
@login_required(role='kancelaria')
def get_suggestions(): return handle_request(office_handler.get_purchase_suggestions)

@app.route('/api/kancelaria/getProductionStats', methods=['POST'])
@login_required(role='kancelaria')
def get_stats(): return handle_request(office_handler.get_production_stats, request.json.get('period'), request.json.get('category'))

@app.route('/api/kancelaria/get_7_day_forecast')
@login_required(role='kancelaria')
def get_7_day_forecast_route():
    return handle_request(office_handler.get_7_day_order_forecast)

@app.route('/api/kancelaria/create_urgent_task', methods=['POST'])
@login_required(role='kancelaria')
def create_urgent_task_route():
    return handle_request(office_handler.create_urgent_production_task, request.json)

# --- Kancelária: Expedičný Plán - Nové Endpoints ---
@app.route('/api/kancelaria/get_goods_purchase_suggestion')
@login_required(role='kancelaria')
def get_goods_purchase_suggestion_route():
    return handle_request(office_handler.get_goods_purchase_suggestion)

@app.route('/api/kancelaria/get_promotions_data')
@login_required(role='kancelaria')
def get_promotions_data_route():
    return handle_request(office_handler.get_promotions_data)

@app.route('/api/kancelaria/manage_promotion_chain', methods=['POST'])
@login_required(role='kancelaria')
def manage_promotion_chain_route():
    return handle_request(office_handler.manage_promotion_chain, request.json)

@app.route('/api/kancelaria/save_promotion', methods=['POST'])
@login_required(role='kancelaria')
def save_promotion_route():
    return handle_request(office_handler.save_promotion, request.json)

@app.route('/api/kancelaria/delete_promotion', methods=['POST'])
@login_required(role='kancelaria')
def delete_promotion_route():
    return handle_request(office_handler.delete_promotion, request.json)

@app.route('/api/kancelaria/stock/receiveProduction', methods=['POST'])
@login_required(role='kancelaria')
def receive_production_stock_route():
    return handle_request(office_handler.receive_production_stock, request.json)

@app.route('/api/kancelaria/stock/createProductionItem', methods=['POST'])
@login_required(role='kancelaria')
def create_production_item_route():
    return handle_request(office_handler.create_production_item, request.json)

# ── Dodávatelia: CRUD
@app.route('/api/kancelaria/suppliers', methods=['GET'])
@login_required(role='kancelaria')
def suppliers_list():
    category = request.args.get('category')  # 'koreniny'|'obal'|'pomocny_material' alebo None
    return handle_request(office_handler.list_suppliers, category)

@app.route('/api/kancelaria/suppliers', methods=['POST'])
@login_required(role='kancelaria')
def suppliers_create():
    return handle_request(office_handler.create_supplier, request.json)

@app.route('/api/kancelaria/suppliers/<int:supplier_id>', methods=['PUT'])
@login_required(role='kancelaria')
def suppliers_update(supplier_id):
    data = request.json or {}
    data['id'] = supplier_id
    return handle_request(office_handler.update_supplier, data)

@app.route('/api/kancelaria/suppliers/<int:supplier_id>', methods=['DELETE'])
@login_required(role='kancelaria')
def suppliers_delete(supplier_id):
    return handle_request(office_handler.delete_supplier, supplier_id)

@app.route('/api/kancelaria/stock/transferToProduction', methods=['POST'])
@login_required(role='kancelaria')
def transfer_to_production_route():
    payload = request.json or {}
    user = session.get('user')
    return handle_request(office_handler.transfer_to_production, payload, user)

@app.route('/api/kancelaria/stock/updateProductionItemQty', methods=['POST'])
@login_required(role='kancelaria')
def update_production_item_qty_route():
    return handle_request(office_handler.update_production_item_qty)

@app.route('/api/kancelaria/stock/deleteProductionItem', methods=['POST'])
@login_required(role='kancelaria')
def delete_production_item_route():
    return handle_request(office_handler.delete_production_item)

# --- Kancelária: Správa ERP (Katalóg, Recepty) ---
@app.route('/api/kancelaria/getCatalogManagementData')
@login_required(role='kancelaria')
def get_catalog_data(): return handle_request(office_handler.get_catalog_management_data)

@app.route('/api/kancelaria/addCatalogItem', methods=['POST'])
@login_required(role='kancelaria')
def add_catalog_item(): return handle_request(office_handler.add_catalog_item, request.json)

@app.route('/api/kancelaria/updateCatalogItem', methods=['POST'])
@login_required(role='kancelaria')
def update_catalog_item_route(): return handle_request(office_handler.update_catalog_item, request.json)

@app.route('/api/kancelaria/deleteCatalogItem', methods=['POST'])
@login_required(role='kancelaria')
def delete_catalog_item_route(): return handle_request(office_handler.delete_catalog_item, request.json)

@app.route('/api/kancelaria/addNewStockItem', methods=['POST'])
@login_required(role='kancelaria')
def add_stock_item(): return handle_request(office_handler.add_new_stock_item, request.json)

@app.route('/api/kancelaria/getProductsForMinStock')
@login_required(role='kancelaria')
def get_products_min_stock(): return handle_request(office_handler.get_products_for_min_stock)

@app.route('/api/kancelaria/updateMinStockLevels', methods=['POST'])
@login_required(role='kancelaria')
def update_min_stock(): return handle_request(office_handler.update_min_stock_levels, request.json)

@app.route('/api/kancelaria/addNewRecipe', methods=['POST'])
@login_required(role='kancelaria')
def add_recipe(): return handle_request(office_handler.add_new_recipe, request.json)

@app.route('/api/kancelaria/getAllRecipes')
@login_required(role='kancelaria')
def get_recipes(): return handle_request(office_handler.get_all_recipes_for_editing)

@app.route('/api/kancelaria/getRecipeDetails', methods=['POST'])
@login_required(role='kancelaria')
def get_recipe_details(): return handle_request(office_handler.get_recipe_details, request.json.get('productName'))

@app.route('/api/kancelaria/updateRecipe', methods=['POST'])
@login_required(role='kancelaria')
def update_recipe(): return handle_request(office_handler.update_recipe, request.json)

@app.route('/api/kancelaria/deleteRecipe', methods=['POST'])
@login_required(role='kancelaria')
def delete_recipe(): return handle_request(office_handler.delete_recipe, request.json.get('productName'))

@app.route('/api/kancelaria/getSlicingManagementData')
@login_required(role='kancelaria')
def get_slicing_data(): return handle_request(office_handler.get_slicing_management_data)

@app.route('/api/kancelaria/linkSlicedProduct', methods=['POST'])
@login_required(role='kancelaria')
def link_sliced(): return handle_request(office_handler.link_sliced_product, request.json)

@app.route('/api/kancelaria/createAndLinkSlicedProduct', methods=['POST'])
@login_required(role='kancelaria')
def create_and_link_sliced(): return handle_request(office_handler.create_and_link_sliced_product, request.json)

# --- Kancelária: B2B Administrácia ---
@app.route('/api/kancelaria/getPendingB2BRegistrations')
@login_required(role='kancelaria')
def get_pending_regs(): return handle_request(b2b_handler.get_pending_b2b_registrations)

@app.route('/api/kancelaria/approveB2BRegistration', methods=['POST'])
@login_required(role='kancelaria')
def approve_b2b_reg(): return handle_request(b2b_handler.approve_b2b_registration, request.json)

@app.route('/api/kancelaria/rejectB2BRegistration', methods=['POST'])
@login_required(role='kancelaria')
def reject_b2b_reg(): return handle_request(b2b_handler.reject_b2b_registration, request.json)

@app.route('/api/kancelaria/b2b/getCustomersAndPricelists')
@login_required(role='kancelaria')
def get_b2b_customers_pricelists(): return handle_request(b2b_handler.get_customers_and_pricelists)

@app.route('/api/kancelaria/b2b/updateCustomer', methods=['POST'])
@login_required(role='kancelaria')
def update_b2b_customer(): return handle_request(b2b_handler.update_customer_details, request.json)

@app.route('/api/kancelaria/b2b/getPricelistsAndProducts')
@login_required(role='kancelaria')
def get_b2b_pricelists_products(): return handle_request(b2b_handler.get_pricelists_and_products)

@app.route('/api/kancelaria/b2b/createPricelist', methods=['POST'])
@login_required(role='kancelaria')
def create_b2b_pricelist(): return handle_request(b2b_handler.create_pricelist, request.json)

@app.route('/api/kancelaria/b2b/getPricelistDetails', methods=['POST'])
@login_required(role='kancelaria')
def get_b2b_pricelist_details(): return handle_request(b2b_handler.get_pricelist_details, request.json)

@app.route('/api/kancelaria/b2b/updatePricelist', methods=['POST'])
@login_required(role='kancelaria')
def update_b2b_pricelist(): return handle_request(b2b_handler.update_pricelist, request.json)

@app.route('/api/kancelaria/b2b/getAnnouncement')
@login_required(role='kancelaria')
def get_b2b_announcement(): return handle_request(b2b_handler.get_announcement)

@app.route('/api/kancelaria/b2b/saveAnnouncement', methods=['POST'])
@login_required(role='kancelaria')
def save_b2b_announcement(): return handle_request(b2b_handler.save_announcement, request.json)

@app.route('/api/kancelaria/b2b/getAllOrders', methods=['POST'])
@login_required(role='kancelaria')
def get_all_b2b_orders_admin():
    return handle_request(b2b_handler.get_all_b2b_orders, request.json)

@app.route('/api/kancelaria/b2b/get_order_details/<int:order_id>')
@login_required(role='kancelaria')
def get_b2b_order_details_route(order_id):
    return handle_request(b2b_handler.get_b2b_order_details, order_id)

@app.route('/api/kancelaria/b2b/print_order_pdf/<int:order_id>')
@login_required(role='kancelaria')
def print_b2b_order_pdf_route(order_id):
    order_data = b2b_handler.get_b2b_order_details(order_id)
    if not order_data or 'error' in order_data:
        return make_response(f"<h1>Chyba: Objednávka s ID {order_id} nebola nájdená.</h1>", 404)
    
    pdf_content, _ = pdf_generator.create_order_files(order_data)
    response = make_response(pdf_content)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=objednavka_{order_data.get("order_number", order_id)}.pdf'
    return response

# --- Kancelária: B2C Administrácia ---
@app.route('/api/kancelaria/b2c/get_orders')
@login_required(role='kancelaria')
def get_b2c_orders_admin():
    return handle_request(office_handler.get_b2c_orders_for_admin)

@app.route('/api/kancelaria/b2c/update_order_status', methods=['POST'])
@login_required(role='kancelaria')
def update_b2c_order_status_admin():
    return handle_request(office_handler.update_b2c_order_status, request.json)

@app.route('/api/kancelaria/b2c/finalize_order', methods=['POST'])
@login_required(role='kancelaria')
def finalize_b2c_order_admin():
    return handle_request(office_handler.finalize_b2c_order, request.json)

@app.route('/api/kancelaria/b2c/cancel_order', methods=['POST'])
@login_required(role='kancelaria')
def cancel_b2c_order_admin():
    return handle_request(office_handler.cancel_b2c_order, request.json)

@app.route('/api/kancelaria/b2c/get_customers')
@login_required(role='kancelaria')
def get_b2c_customers_admin():
    return handle_request(office_handler.get_b2c_customers_for_admin)

@app.route('/api/kancelaria/b2c/get_pricelist_admin')
@login_required(role='kancelaria')
def get_b2c_pricelist_admin():
    return handle_request(office_handler.get_b2c_pricelist_for_admin)

@app.route('/api/kancelaria/b2c/update_pricelist', methods=['POST'])
@login_required(role='kancelaria')
def update_b2c_pricelist_admin():
    return handle_request(office_handler.update_b2c_pricelist, request.json)

@app.route('/api/kancelaria/b2c/credit_points', methods=['POST'])
@login_required(role='kancelaria')
def credit_b2c_loyalty_points_admin():
    return handle_request(office_handler.credit_b2c_loyalty_points, request.json)

@app.route('/api/kancelaria/b2c/get_rewards')
@login_required(role='kancelaria')
def get_b2c_rewards_admin():
    return handle_request(office_handler.get_b2c_rewards_for_admin)

@app.route('/api/kancelaria/b2c/add_reward', methods=['POST'])
@login_required(role='kancelaria')
def add_b2c_reward_admin():
    return handle_request(office_handler.add_b2c_reward, request.json)

@app.route('/api/kancelaria/b2c/toggle_reward_status', methods=['POST'])
@login_required(role='kancelaria')
def toggle_b2c_reward_status_admin():
    return handle_request(office_handler.toggle_b2c_reward_status, request.json)

# =================================================================
# === REPORTY A SLEDOVATEĽNOSŤ ===
# =================================================================
@app.route('/traceability/<batch_id>')
@login_required(role=['expedicia', 'kancelaria', 'admin'])
def page_traceability(batch_id):
    return render_template('traceability.html', batch_id=batch_id)

@app.route('/api/traceability/<batch_id>')
@login_required(role=['expedicia', 'kancelaria', 'admin'])
def get_api_traceability_info(batch_id):
    return handle_request(expedition_handler.get_traceability_info, batch_id)

@app.route('/report/receipt')
@login_required(role='kancelaria')
def report_receipt():
    period = request.args.get('period', 'day')
    category = request.args.get('category', 'Všetky')
    return office_handler.get_receipt_report_html(period, category)

@app.route('/report/inventory')
@login_required(role='kancelaria')
def report_inventory():
    date_str = request.args.get('date')
    return office_handler.get_inventory_difference_report_html(date_str)

@app.route('/report/fleet')
@login_required(role='kancelaria')
def get_fleet_report_html():
    vehicle_id = request.args.get('vehicle_id', type=int)
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    return fleet_handler.get_report_html_content(vehicle_id=vehicle_id, year=year, month=month)

@app.route('/report/hygiene')
@login_required(role='kancelaria')
def report_hygiene():
    report_date_str = request.args.get('date')
    period = request.args.get('period', 'denne')
    data = hygiene_handler.get_hygiene_report_data(report_date_str, period=period)
    if not data: return "<h1>Chyba: Nepodarilo sa vygenerovať dáta pre report.</h1>", 400
    return make_response(render_template('hygiene_report_template.html', **data))

@app.route('/report/profitability')
@login_required(role='kancelaria')
def report_profitability():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    report_type = request.args.get('type', 'summary')
    return profitability_handler.get_profitability_report_html(year=year, month=month, report_type=report_type)
# --- Aliasy pre Kanceláriu: základné dáta a allowed-names (bez pádu) ---
from flask import jsonify, request
from db_connector import execute_query

@app.get('/api/kancelaria/baseData_safe')
def base_data_alias_safe():
    try:
        products = execute_query("""
          SELECT p.nazov_vyrobku
            FROM produkty p
           WHERE p.typ_polozky LIKE 'VÝROBOK%%'
             AND NOT EXISTS (
                   SELECT 1 FROM recepty r
                   WHERE TRIM(r.nazov_vyrobku) = TRIM(p.nazov_vyrobku)
                 )
           ORDER BY p.nazov_vyrobku
        """) or []
        products_without_recipe = [r['nazov_vyrobku'] for r in products]
    except Exception as e:
        print('baseData products err:', e)
        products_without_recipe = []

    try:
        cats = execute_query("""
          SELECT DISTINCT kategoria_pre_recepty AS cat
            FROM produkty
           WHERE kategoria_pre_recepty IS NOT NULL AND kategoria_pre_recepty <> ''
           ORDER BY cat
        """) or []
        recipe_categories = [c['cat'] for c in cats]
    except Exception as e:
        print('baseData categories err:', e)
        recipe_categories = []

    try:
        item_types_rows = execute_query("""
          SELECT DISTINCT kategoria FROM sklad
          WHERE kategoria IS NOT NULL AND kategoria <> ''
          ORDER BY kategoria
        """) or []
        item_types = [r['kategoria'] for r in item_types_rows] or ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál']
    except Exception as e:
        print('baseData item_types err:', e)
        item_types = ['Mäso','Koreniny','Obaly - Črevá','Pomocný materiál']

    return jsonify({
        "productsWithoutRecipe": products_without_recipe,
        "recipeCategories": recipe_categories,
        "itemTypes": item_types
    })

@app.get('/api/kancelaria/stock/allowed-names')
def stock_allowed_names_alias():
    category = (request.args.get('category') or '').strip()
    items = []
    try:
        if category:
            rows = execute_query("""
              SELECT s.nazov AS name,
                     s.kategoria,
                     s.is_infinite_stock,
                     s.default_cena_eur_kg,
                     (SELECT z.nakupna_cena_eur_kg
                        FROM zaznamy_prijem z
                       WHERE z.nazov_suroviny = s.nazov
                         AND z.nakupna_cena_eur_kg IS NOT NULL
                       ORDER BY z.datum DESC
                       LIMIT 1) AS last_price
                FROM sklad s
               WHERE s.kategoria = %s
               ORDER BY s.nazov
            """, (category,)) or []
        else:
            rows = []
        for r in rows:
            price = r.get('last_price')
            if price is None:
                price = r.get('default_cena_eur_kg')
            # fallback pre pomocný materiál
            if price is None and str(r.get('kategoria','')) == 'Pomocný materiál' and r.get('name') in ('Voda','Ľad','Ovar'):
                price = 0.20
            items.append({
                "name": r["name"],
                "last_price": float(price) if price is not None else None,
                "is_infinite": bool(r.get("is_infinite_stock"))
            })
    except Exception as e:
        print('allowed-names err:', e)
        if category == 'Pomocný materiál':
            items = [{"name":"Voda","last_price":0.20,"is_infinite":True},
                     {"name":"Ľad","last_price":0.20,"is_infinite":True},
                     {"name":"Ovar","last_price":0.20,"is_infinite":True}]
        else:
            items = []
    return jsonify({"items": items})

# =================================================================
# === SPUSTENIE APLIKÁCIE ===
# =================================================================
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)
